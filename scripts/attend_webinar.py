#!/usr/bin/env python3
"""Remote webinar attendance and tab video+audio capture via Playwright Chromium.

Attends a Zoom Event or browser-based webinar silently with camera and microphone
hard-disabled, captures the active webinar tab's video (VP8) and audio (Opus)
via cross-tab getDisplayMedia + MediaRecorder streamed directly to disk, trims
leading waiting-room and trailing post-webinar silence losslessly (-c copy),
and exposes a live JSON status + command file interface for agent supervision.

Playwright is imported lazily only when launching Chromium, keeping --help and
helper functions standard-library compatible.

Optional setup for live capture:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import platform
import re
import shutil
import signal
import socketserver
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAPTURE_TITLE_TOKEN = "WEBINAR_CAPTURE_TARGET"

END_PHRASES = (
    "this webinar has been ended by host",
    "this webinar has ended",
    "the host has ended this webinar",
    "this meeting has been ended by host",
    "the host has ended this meeting",
    "webinar has ended",
    "post webinar survey",
    "thank you for attending",
)

END_URL_FRAGMENTS = (
    "/meeting/survey",
    "/postattendee",
    "/wc/leave",
)

BLOCK_CAMERA_MIC_JS = """
(() => {
  const deny = () => Promise.reject(
    new DOMException('Camera and microphone disabled for passive webinar attendance', 'NotAllowedError')
  );
  if (navigator.mediaDevices) {
    try {
      Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
        value: deny,
        configurable: true,
      });
    } catch (_) {
      navigator.mediaDevices.getUserMedia = deny;
    }
  }
  if (navigator.getUserMedia) {
    navigator.getUserMedia = (_c, _s, err) => { if (err) err(new Error('NotAllowedError')); };
  }
})();
"""

RECORDER_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>RECORDER_CTRL</title></head>
<body>
<script>
let currentStream = null;
let currentMr = null;
let currentSeg = 0;
let audioCtx = null;
let analyser = null;
let meterTimer = null;
let pendingUploads = 0;

window.startCapture = async (segNum, fps, videoBps, audioBps, suppressLocal) => {
  if (currentMr && currentMr.state !== 'inactive') {
    await window.stopCapture();
  }
  currentSeg = segNum;
  const audioConstraints = suppressLocal
    ? { suppressLocalAudioPlayback: true, echoCancellation: false, noiseSuppression: false, autoGainControl: false }
    : { echoCancellation: false, noiseSuppression: false, autoGainControl: false };

  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { frameRate: fps, width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: audioConstraints
  });
  currentStream = stream;

  const audioTracks = stream.getAudioTracks();
  if (audioTracks.length > 0) {
    try {
      audioCtx = new AudioContext();
      const src = audioCtx.createMediaStreamSource(new MediaStream(audioTracks));
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      src.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      meterTimer = setInterval(() => {
        if (!analyser) return;
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        let peak = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = Math.abs(buf[i]);
          sum += v * v;
          if (v > peak) peak = v;
        }
        const rms = Math.sqrt(sum / buf.length);
        const rmsDb = rms > 1e-7 ? 20 * Math.log10(rms) : -120;
        const peakDb = peak > 1e-7 ? 20 * Math.log10(peak) : -120;
        fetch('/telemetry', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            seg: currentSeg,
            rms_db: Math.round(rmsDb * 10) / 10,
            peak_db: Math.round(peakDb * 10) / 10,
            state: currentMr ? currentMr.state : 'none',
            video_tracks: stream.getVideoTracks().map(t => t.readyState),
            audio_tracks: stream.getAudioTracks().map(t => t.readyState)
          })
        }).catch(() => {});
      }, 3000);
    } catch (e) {
      console.error('Meter init error:', e);
    }
  }

  let mimeType = 'video/webm;codecs=vp8,opus';
  if (!MediaRecorder.isTypeSupported(mimeType)) {
    mimeType = 'video/webm;codecs=vp9,opus';
  }
  if (!MediaRecorder.isTypeSupported(mimeType)) {
    mimeType = 'video/webm';
  }

  const mr = new MediaRecorder(stream, {
    mimeType,
    videoBitsPerSecond: videoBps,
    audioBitsPerSecond: audioBps
  });
  currentMr = mr;

  mr.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) {
      pendingUploads++;
      fetch('/chunk?seg=' + currentSeg, {
        method: 'POST',
        body: e.data
      }).finally(() => { pendingUploads--; });
    }
  };

  mr.start(5000);
  return {
    mimeType,
    tracks: stream.getTracks().map(t => t.kind + ':' + t.label + ':' + t.readyState)
  };
};

window.stopCapture = async () => {
  if (meterTimer) { clearInterval(meterTimer); meterTimer = null; }
  if (currentMr && currentMr.state !== 'inactive') {
    await new Promise((resolve) => {
      currentMr.onstop = resolve;
      try { currentMr.requestData(); } catch (_) {}
      currentMr.stop();
    });
  }
  const deadline = Date.now() + 8000;
  while (pendingUploads > 0 && Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 150));
  }
  if (currentStream) {
    currentStream.getTracks().forEach(t => t.stop());
    currentStream = null;
  }
  if (audioCtx) {
    try { await audioCtx.close(); } catch (_) {}
    audioCtx = null;
    analyser = null;
  }
  currentMr = null;
  return { stopped: true, pendingUploads };
};
</script>
</body>
</html>
"""

SELF_TEST_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Self Test Webinar Page</title></head>
<body style="margin:0;background:#0a192f;color:#fff;font-family:sans-serif">
<canvas id="c" width="1280" height="720"></canvas>
<script>
const ctx = document.getElementById('c').getContext('2d');
let f = 0;
setInterval(() => {
  ctx.fillStyle = (f % 2 === 0) ? '#0b3d91' : '#12263a';
  ctx.fillRect(0, 0, 1280, 720);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 56px sans-serif';
  ctx.fillText('Webinar Capture Self-Test Frame ' + (f++), 120, 360);
}, 250);
const ac = new AudioContext();
const osc = ac.createOscillator();
osc.frequency.value = 440;
const gain = ac.createGain();
gain.gain.value = 0.25;
osc.connect(gain);
gain.connect(ac.destination);
osc.start();
</script>
</body>
</html>
"""


def require_binary(name: str) -> str:
    """Return path to a required binary or raise a cross-platform install hint."""
    found = shutil.which(name)
    if found:
        return found
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        hint = "Install on macOS via: brew install ffmpeg"
    elif sys_name == "windows":
        hint = "Install on Windows via: winget install Gyan.FFmpeg"
    else:
        hint = "Install on Linux via: sudo apt install ffmpeg"
    raise FileNotFoundError(f"Required executable '{name}' not found on PATH. {hint}")


def require_playwright() -> Any:
    """Lazily import playwright.sync_api.sync_playwright with a clear install hint."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        return sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for live webinar attendance. Install it with:\n"
            "  pip install playwright && playwright install chromium"
        ) from exc


def detect_end_signal(text: str, url: str) -> str | None:
    """Detect whether a webinar page URL or visible frame text indicates the session ended."""
    low_url = (url or "").lower()
    for frag in END_URL_FRAGMENTS:
        if frag in low_url:
            return f"url:{frag}"
    low_text = (text or "").lower()
    for phrase in END_PHRASES:
        if phrase in low_text:
            return phrase
    return None


def parse_silencedetect_output(stderr_text: str) -> list[tuple[float, float]]:
    """Parse ffmpeg silencedetect stderr lines into a list of (start, end) intervals."""
    intervals: list[tuple[float, float]] = []
    pending_start: float | None = None
    start_re = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
    end_re = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")
    for line in stderr_text.splitlines():
        m_start = start_re.search(line)
        if m_start:
            pending_start = float(m_start.group(1))
            continue
        m_end = end_re.search(line)
        if m_end and pending_start is not None:
            intervals.append((pending_start, float(m_end.group(1))))
            pending_start = None
    return intervals


def compute_trim_bounds(
    silences: list[tuple[float, float]],
    duration: float,
    lead_pad: float = 3.0,
    tail_pad: float = 4.0,
    min_trim_savings: float = 10.0,
) -> tuple[float, float] | None:
    """Compute lossless (start, end) trim bounds from leading/trailing silence intervals.

    Returns None if no meaningful leading or trailing silence can be removed safely.
    """
    if duration <= 0 or not silences:
        return None
    trim_start = 0.0
    trim_end = duration

    first_start, first_end = silences[0]
    if first_start <= 2.0 and first_end < duration - 5.0:
        trim_start = max(0.0, round(first_end - lead_pad, 2))

    last_start, last_end = silences[-1]
    if last_end >= duration - 2.0 and last_start > trim_start + 5.0:
        trim_end = min(duration, round(last_start + tail_pad, 2))

    saved = trim_start + (duration - trim_end)
    if saved < min_trim_savings or trim_end <= trim_start + 5.0:
        return None
    return (trim_start, trim_end)


def find_chromium_executable() -> str | None:
    """Locate Playwright's downloaded Chromium executable on Windows/macOS/Linux."""
    candidates: list[Path] = []
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        pw_root = Path(local_app) / "ms-playwright"
        if pw_root.exists():
            for d in sorted(pw_root.glob("chromium-*"), reverse=True):
                for rel in ("chrome-win64/chrome.exe", "chrome-win/chrome.exe"):
                    exe = d / rel
                    if exe.exists():
                        candidates.append(exe)
    for base in (Path.home() / ".cache" / "ms-playwright", Path.home() / "Library" / "Caches" / "ms-playwright"):
        if base.exists():
            for d in sorted(base.glob("chromium-*"), reverse=True):
                for rel in (
                    "chrome-linux/chrome",
                    "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
                    "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                ):
                    exe = d / rel
                    if exe.exists():
                        candidates.append(exe)
    return str(candidates[0]) if candidates else None


class ChunkServer:
    """Local HTTP server serving the recorder page and writing WebM chunks to disk."""

    def __init__(self, work_dir: Path, slug: str) -> None:
        self.work_dir = work_dir
        self.slug = slug
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.files: dict[int, Path] = {}
        self.handles: dict[int, Any] = {}
        self.bytes_by_seg: dict[int, int] = {}
        self.chunks_by_seg: dict[int, int] = {}
        self.last_chunk_ts: float = 0.0
        self.telemetry: dict[str, Any] = {}

        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path.startswith("/recorder"):
                    body = RECORDER_HTML.encode("utf-8")
                elif self.path.startswith("/selftest"):
                    body = SELF_TEST_HTML.encode("utf-8")
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = self.rfile.read(length) if length > 0 else b""
                if self.path.startswith("/chunk"):
                    seg = 1
                    if "seg=" in self.path:
                        try:
                            seg = int(self.path.split("seg=")[1].split("&")[0])
                        except ValueError:
                            seg = 1
                    outer.write_chunk(seg, payload)
                elif self.path.startswith("/telemetry"):
                    try:
                        data = json.loads(payload.decode("utf-8"))
                        with outer.lock:
                            outer.telemetry = data
                            outer.telemetry["updated_at"] = datetime.now(timezone.utc).isoformat()
                    except Exception:
                        pass
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format: str, *args: Any) -> None:
                pass

        class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        self.server = ThreadedServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def write_chunk(self, seg: int, data: bytes) -> None:
        with self.lock:
            if seg not in self.handles:
                path = self.work_dir / f"{self.slug}_seg{seg:02d}.webm"
                self.files[seg] = path
                self.handles[seg] = open(path, "wb")
                self.bytes_by_seg[seg] = 0
                self.chunks_by_seg[seg] = 0
            fh = self.handles[seg]
            fh.write(data)
            fh.flush()
            self.bytes_by_seg[seg] += len(data)
            self.chunks_by_seg[seg] += 1
            self.last_chunk_ts = time.time()

    def total_bytes(self) -> int:
        with self.lock:
            return sum(self.bytes_by_seg.values())

    def close(self) -> list[Path]:
        self.server.shutdown()
        self.server.server_close()
        with self.lock:
            for fh in self.handles.values():
                try:
                    fh.flush()
                    fh.close()
                except Exception:
                    pass
            self.handles.clear()
            return [
                self.files[k]
                for k in sorted(self.files.keys())
                if self.files[k].exists() and self.files[k].stat().st_size > 0
            ]


def trim_recording_silence(
    ffmpeg_bin: str,
    ffprobe_bin: str,
    media_path: Path,
    noise_db: str = "-50dB",
    min_silence_sec: int = 15,
) -> tuple[float, float] | None:
    """Detect and losslessly (-c copy) trim leading waiting-room and trailing silence."""
    dur_res = subprocess.run(
        [
            ffprobe_bin, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            str(media_path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        duration = float(dur_res.stdout.strip())
    except ValueError:
        return None

    sd_res = subprocess.run(
        [
            ffmpeg_bin, "-hide_banner", "-i", str(media_path),
            "-af", f"silencedetect=noise={noise_db}:d={min_silence_sec}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    silences = parse_silencedetect_output(sd_res.stderr)
    bounds = compute_trim_bounds(silences, duration)
    if not bounds:
        return None

    trim_start, trim_end = bounds
    tmp_trimmed = media_path.with_name(f"{media_path.stem}_trimmed{media_path.suffix}")
    trim_res = subprocess.run(
        [
            ffmpeg_bin, "-hide_banner", "-y",
            "-ss", f"{trim_start:.2f}",
            "-to", f"{trim_end:.2f}",
            "-i", str(media_path),
            "-c", "copy",
            str(tmp_trimmed),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if trim_res.returncode == 0 and tmp_trimmed.exists() and tmp_trimmed.stat().st_size > 0:
        tmp_trimmed.replace(media_path)
        return bounds
    if tmp_trimmed.exists():
        tmp_trimmed.unlink(missing_ok=True)
    return None


def finalize_recordings(
    segments: list[Path],
    output_mkv: Path,
    auto_trim_silence: bool = True,
) -> Path | None:
    """Remux captured WebM segment(s) into a seekable MKV with intact VP8+Opus streams."""
    if not segments:
        return None
    ffmpeg_bin = require_binary("ffmpeg")
    ffprobe_bin = require_binary("ffprobe")
    output_mkv.parent.mkdir(parents=True, exist_ok=True)
    if len(segments) == 1:
        cmd = [ffmpeg_bin, "-hide_banner", "-y", "-i", str(segments[0]), "-c", "copy", str(output_mkv)]
    else:
        concat_list = segments[0].parent / f"{output_mkv.stem}_concat.txt"
        lines = []
        for s in segments:
            clean = s.with_suffix(".clean.mkv")
            subprocess.run(
                [ffmpeg_bin, "-hide_banner", "-y", "-i", str(s), "-c", "copy", str(clean)],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            target = clean if clean.exists() and clean.stat().st_size > 0 else s
            safe = str(target.resolve()).replace("'", "'\\''")
            lines.append(f"file '{safe}'")
        concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            ffmpeg_bin, "-hide_banner", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(output_mkv),
        ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0 and output_mkv.exists() and output_mkv.stat().st_size > 0:
        if auto_trim_silence:
            bounds = trim_recording_silence(ffmpeg_bin, ffprobe_bin, output_mkv)
            if bounds:
                print(f"Auto-trimmed waiting-room/trailing silence losslessly to {bounds[0]:.1f}s -> {bounds[1]:.1f}s", flush=True)
        return output_mkv
    return segments[-1]


def safe_visible_buttons(page: Any) -> list[str]:
    try:
        items = page.evaluate("""() => {
            const out = [];
            const els = document.querySelectorAll('button, [role="button"], a[role="menuitem"], [role="menuitem"]');
            for (const el of els) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                const txt = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
                if (!txt) continue;
                const dis = el.disabled || el.getAttribute('aria-disabled') === 'true';
                out.push((dis ? '[DISABLED] ' : '') + txt.slice(0, 60));
                if (out.length >= 25) break;
            }
            return out;
        }""")
        return items or []
    except Exception:
        return []


def collect_frame_texts(page: Any) -> str:
    texts = []
    for frame in page.frames:
        try:
            t = frame.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText.slice(0, 2000) : ''")
            if t:
                texts.append(t)
        except Exception:
            pass
    return "\n---\n".join(texts)


def try_click_in_any_frame(page: Any, selector: str | None = None, text: str | None = None) -> str | None:
    for frame in page.frames:
        try:
            if selector:
                loc = frame.locator(selector).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=3000)
                    return f"clicked selector={selector} in {frame.url[:80]}"
            elif text:
                loc = frame.get_by_text(text, exact=False).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=3000)
                    return f"clicked text={text} in {frame.url[:80]}"
        except Exception:
            continue
    return None


def try_zoom_events_join_web(page: Any) -> str | None:
    """In Zoom Events Lobby, select Join Method -> Web and click Join once enabled."""
    try:
        if "/ejl/" not in page.url and "Lobby" not in (page.title() or ""):
            return None

        join_btn = page.locator("button:has-text('Join')").first
        if join_btn.count() == 0:
            return None
        is_disabled = join_btn.is_disabled() or (join_btn.get_attribute("aria-disabled") == "true")
        if is_disabled:
            return None

        menu_clicked = False
        for sel in (
            "button[aria-label*='Join method' i]",
            "button[aria-label*='more' i]",
            "button[aria-haspopup='menu']",
            "button:has-text('...')",
        ):
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                try:
                    loc.click(timeout=2500)
                    time.sleep(0.6)
                    menu_clicked = True
                    break
                except Exception:
                    pass

        if menu_clicked:
            for web_sel in (
                "[role='menuitem']:has-text('Web')",
                "li:has-text('Web')",
                "button:has-text('Web')",
                "text=/^Web$/",
            ):
                wloc = page.locator(web_sel).first
                if wloc.count() > 0 and wloc.is_visible():
                    if wloc.get_attribute("aria-disabled") != "true":
                        wloc.click(timeout=2500)
                        time.sleep(0.5)
                        break

        if "/ejl/" in page.url:
            join_btn = page.locator("button:has-text('Join')").first
            if join_btn.count() > 0 and join_btn.is_visible() and not join_btn.is_disabled():
                join_btn.click(timeout=3000)
                return "clicked Web + Join in Zoom Events Lobby"
        return "selected Web in Zoom Events Lobby"
    except Exception as exc:
        return f"join attempt error: {exc}"


def try_zoom_web_client_dismiss_and_audio(page: Any) -> list[str]:
    """Handle common Zoom Web Client interstitial modals without enabling cam/mic."""
    # Never click modal OK buttons if the webinar has already ended!
    if detect_end_signal(collect_frame_texts(page), page.url):
        return []

    actions: list[str] = []
    safe_button_texts = (
        "Join Audio by Computer",
        "Join audio by computer",
        "Computer Audio",
        "Accept Cookies",
        "Accept All",
        "Got it",
        "Continue without microphone and camera",
        "Continue without audio and video",
        "I Agree",
        "Agree",
    )
    for frame in page.frames:
        for label in safe_button_texts:
            try:
                loc = frame.locator(f"button:has-text('{label}')").first
                if loc.count() > 0 and loc.is_visible() and not loc.is_disabled():
                    txt = (loc.inner_text() or "").strip()
                    low = txt.lower()
                    if any(bad in low for bad in ("leave", "end meeting", "start video", "unmute", "share screen")):
                        continue
                    loc.click(timeout=2000)
                    actions.append(f"clicked '{txt}'")
                    time.sleep(0.5)
            except Exception:
                pass
    return actions


def check_webinar_ended(page: Any) -> str | None:
    return detect_end_signal(collect_frame_texts(page), getattr(page, "url", ""))


def start_recording_target(
    ctrl_page: Any,
    target_page: Any,
    seg_num: int,
    fps: int,
    video_bps: int,
    audio_bps: int,
    suppress_local: bool,
) -> dict[str, Any]:
    """Temporarily tag target_page title so Chromium auto-selects it for tab capture."""
    orig_title = ""
    try:
        orig_title = target_page.title()
    except Exception:
        pass
    target_page.evaluate(f"document.title = {json.dumps(CAPTURE_TITLE_TOKEN)}")
    time.sleep(0.3)
    res = ctrl_page.evaluate(
        "([seg, fps, vbps, abps, sup]) => window.startCapture(seg, fps, vbps, abps, sup)",
        [seg_num, fps, video_bps, audio_bps, suppress_local],
    )
    try:
        if orig_title:
            target_page.evaluate(f"document.title = {json.dumps(orig_title)}")
    except Exception:
        pass
    target_page.bring_to_front()
    return res


def run_self_test(scratch_dir: Path) -> int:
    sync_playwright = require_playwright()
    ffmpeg_bin = require_binary("ffmpeg")
    ffprobe_bin = require_binary("ffprobe")
    srv = ChunkServer(scratch_dir, "self_test")
    exe = find_chromium_executable()
    print(f"Self-test Chromium: {exe}")
    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "args": [
                "--headless=new",
                f"--auto-select-tab-capture-source-by-title={CAPTURE_TITLE_TOKEN}",
                "--enable-usermedia-screen-capturing",
                "--allow-http-screen-capture",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ],
        }
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = p.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, permissions=[])
        ctx.add_init_script(BLOCK_CAMERA_MIC_JS)
        target = ctx.new_page()
        target.goto(f"http://127.0.0.1:{srv.port}/selftest")
        ctrl = ctx.new_page()
        ctrl.goto(f"http://127.0.0.1:{srv.port}/recorder")
        res = start_recording_target(ctrl, target, 1, 10, 1200000, 128000, suppress_local=True)
        print("Capture started:", res)
        gum_res = target.evaluate("""async () => {
            try { await navigator.mediaDevices.getUserMedia({audio: true, video: true}); return 'ALLOWED'; }
            catch (e) { return 'BLOCKED:' + e.name; }
        }""")
        print("getUserMedia check:", gum_res)
        time.sleep(6.5)
        print("Live telemetry:", srv.telemetry)
        ctrl.evaluate("window.stopCapture()")
        time.sleep(0.5)
        browser.close()
    segs = srv.close()
    out_mkv = scratch_dir / "self_test_final.mkv"
    final = finalize_recordings(segs, out_mkv, auto_trim_silence=False)
    print("Final file:", final)
    if final and final.exists():
        probe = subprocess.run(
            [
                ffprobe_bin, "-v", "error", "-show_entries", "format=duration,size",
                "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate,channels",
                "-of", "default=noprint_wrappers=1", str(final),
            ],
            capture_output=True, text=True,
        )
        print(probe.stdout.strip())
        astats = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", str(final), "-af", "astats=measure_perchannel=0", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        for line in astats.stderr.splitlines():
            if "RMS level dB" in line or "Peak level dB" in line:
                print(line.strip())
        for f in segs + [out_mkv]:
            if f.exists():
                f.unlink()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attend a webinar headlessly with cam/mic disabled and capture tab video+audio."
    )
    parser.add_argument("--url", help="Webinar join URL (e.g. Zoom Events /ej/ or Zoom Web link)")
    parser.add_argument("--slug", default="webinar", help="Output filename slug (default: webinar)")
    parser.add_argument("--recordings-dir", default="recordings", help="Final MKV output directory (default: recordings)")
    parser.add_argument("--scratch-dir", default="scratch", help="Temporary chunk, screenshot, and status directory (default: scratch)")
    parser.add_argument("--max-minutes", type=float, default=90.0, help="Maximum total runtime in minutes (default: 90)")
    parser.add_argument("--fps", type=int, default=10, help="Capture video frame rate (default: 10)")
    parser.add_argument("--video-bps", type=int, default=1200000, help="Video bitrate in bps (default: 1200000)")
    parser.add_argument("--audio-bps", type=int, default=128000, help="Opus audio bitrate in bps (default: 128000)")
    parser.add_argument(
        "--end-silence-seconds",
        type=float,
        default=180.0,
        help="Auto-stop after N seconds of sustained silence (-45 dB) following live speech (default: 180; 0 disables)",
    )
    parser.add_argument(
        "--no-auto-trim-silence",
        action="store_true",
        help="Keep full leading waiting-room and trailing silence instead of trimming losslessly",
    )
    parser.add_argument("--no-suppress-local-audio", action="store_true", help="Keep local speaker playback unmuted")
    parser.add_argument("--record-immediately", action="store_true", help="Start recording immediately instead of waiting for join")
    parser.add_argument("--self-test", action="store_true", help="Run a 6-second synthetic capture and cam/mic-block self-test")
    args = parser.parse_args()

    scratch_dir = Path(args.scratch_dir).resolve()
    recordings_dir = Path(args.recordings_dir).resolve()
    scratch_dir.mkdir(parents=True, exist_ok=True)
    recordings_dir.mkdir(parents=True, exist_ok=True)

    if args.self_test:
        return run_self_test(scratch_dir)

    if not args.url:
        parser.error("--url is required unless --self-test is passed")

    sync_playwright = require_playwright()
    require_binary("ffmpeg")
    require_binary("ffprobe")

    status_path = scratch_dir / f"{args.slug}_status.json"
    screenshot_path = scratch_dir / f"{args.slug}_live.png"
    cmd_path = scratch_dir / f"{args.slug}_cmd.json"
    if cmd_path.exists():
        cmd_path.unlink()

    stop_flag = {"stop": False, "reason": ""}

    def handle_sig(signum: int, _frame: Any) -> None:
        stop_flag["stop"] = True
        stop_flag["reason"] = f"signal {signum}"

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    srv = ChunkServer(scratch_dir, args.slug)
    exe = find_chromium_executable()
    started_at = time.time()
    deadline = started_at + args.max_minutes * 60.0
    suppress_local = not args.no_suppress_local_audio

    state: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "slug": args.slug,
        "recording": False,
        "segment": 0,
        "joined_web": False,
        "speech_seen": False,
        "events_log": [],
        "last_cmd_result": None,
    }

    def log_event(msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        print(entry, flush=True)
        state["events_log"].append(entry)
        state["events_log"] = state["events_log"][-40:]

    def write_status(target_page: Any, ctx: Any) -> None:
        try:
            url = target_page.url
            title = target_page.title()
            buttons = safe_visible_buttons(target_page)
        except Exception:
            url, title, buttons = "", "", []
        pages_info = []
        for idx, pg in enumerate(ctx.pages):
            try:
                pages_info.append({"idx": idx, "url": pg.url[:140], "title": pg.title()[:80]})
            except Exception:
                pass
        payload = {
            **state,
            "updated_at": datetime.now().isoformat(),
            "elapsed_sec": round(time.time() - started_at, 1),
            "target_url": url,
            "target_title": title,
            "open_pages": pages_info,
            "visible_buttons": buttons,
            "bytes_recorded": srv.total_bytes(),
            "chunks_by_seg": dict(srv.chunks_by_seg),
            "telemetry": dict(srv.telemetry),
        }
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with sync_playwright() as p:
        log_event(f"Launching Chromium ({exe or 'playwright default'})")
        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "args": [
                "--headless=new",
                f"--auto-select-tab-capture-source-by-title={CAPTURE_TITLE_TOKEN}",
                "--enable-usermedia-screen-capturing",
                "--allow-http-screen-capture",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-features=CalculateNativeWinOcclusion",
            ],
        }
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = p.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, permissions=[])
        ctx.add_init_script(BLOCK_CAMERA_MIC_JS)

        ctrl_page = ctx.new_page()
        ctrl_page.goto(f"http://127.0.0.1:{srv.port}/recorder", wait_until="domcontentloaded")

        target_page = ctx.new_page()
        new_pages_queue: list[Any] = []

        def on_new_page(pg: Any) -> None:
            if pg != ctrl_page:
                new_pages_queue.append(pg)

        ctx.on("page", on_new_page)

        log_event(f"Navigating to {args.url[:80]}...")
        target_page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(5.0)
        try:
            target_page.screenshot(path=str(screenshot_path))
        except Exception:
            pass
        log_event(f"Loaded: {target_page.title()} | {target_page.url[:80]}")

        if args.record_immediately:
            state["segment"] += 1
            rec_info = start_recording_target(
                ctrl_page, target_page, state["segment"],
                args.fps, args.video_bps, args.audio_bps, suppress_local,
            )
            state["recording"] = True
            log_event(f"Started recording seg {state['segment']}: {rec_info}")

        last_shot = time.time()
        last_dismiss = 0.0
        ended_consecutive = 0
        silence_since: float | None = None
        write_status(target_page, ctx)

        while not stop_flag["stop"] and time.time() < deadline:
            # 1. Switch to newly opened webinar tab if Join opened a popup/new tab
            if new_pages_queue:
                newest = new_pages_queue.pop(0)
                try:
                    newest.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                log_event(f"New tab opened: {newest.title()} | {newest.url[:100]}")
                old_page = target_page
                target_page = newest
                target_page.bring_to_front()
                state["joined_web"] = True
                state["segment"] += 1
                try:
                    rec_info = start_recording_target(
                        ctrl_page, target_page, state["segment"],
                        args.fps, args.video_bps, args.audio_bps, suppress_local,
                    )
                    state["recording"] = True
                    log_event(f"Attached recorder seg {state['segment']} to new tab: {rec_info}")
                except Exception as exc:
                    log_event(f"Error attaching recorder to new tab: {exc}")
                try:
                    if old_page != ctrl_page and "/ejl/" in old_page.url:
                        old_page.close()
                except Exception:
                    pass
                try:
                    target_page.screenshot(path=str(screenshot_path))
                    last_shot = time.time()
                except Exception:
                    pass

            # 2. If still on Zoom Events Lobby, attempt Join via Web as soon as enabled
            if not state["joined_web"]:
                join_msg = try_zoom_events_join_web(target_page)
                if join_msg:
                    log_event(join_msg)
                    time.sleep(3.0)
                    if "/ejl/" not in target_page.url:
                        state["joined_web"] = True
                        if not state["recording"]:
                            state["segment"] += 1
                            try:
                                rec_info = start_recording_target(
                                    ctrl_page, target_page, state["segment"],
                                    args.fps, args.video_bps, args.audio_bps, suppress_local,
                                )
                                state["recording"] = True
                                log_event(f"Started recording seg {state['segment']} after same-tab join: {rec_info}")
                            except Exception as exc:
                                log_event(f"Error starting recorder: {exc}")
                    try:
                        target_page.screenshot(path=str(screenshot_path))
                        last_shot = time.time()
                    except Exception:
                        pass

            # 3. Check webinar-ended signals FIRST (before dismissing modals!)
            if state["recording"] and srv.total_bytes() > 500_000:
                ended_signal = check_webinar_ended(target_page)
                if ended_signal:
                    ended_consecutive += 1
                    if ended_consecutive >= 3:
                        log_event(f"Detected webinar end signal ('{ended_signal}') consistently; stopping cleanly.")
                        stop_flag["stop"] = True
                        stop_flag["reason"] = f"webinar ended: {ended_signal}"
                        break
                else:
                    ended_consecutive = 0

                # Track post-speech sustained silence fallback
                rms_db = srv.telemetry.get("rms_db")
                if isinstance(rms_db, (int, float)):
                    if rms_db > -45.0:
                        state["speech_seen"] = True
                        silence_since = None
                    elif state["speech_seen"] and args.end_silence_seconds > 0:
                        if silence_since is None:
                            silence_since = time.time()
                        elif (time.time() - silence_since) >= args.end_silence_seconds:
                            log_event(
                                f"Detected {int(args.end_silence_seconds)}s of sustained silence after speech; stopping cleanly."
                            )
                            stop_flag["stop"] = True
                            stop_flag["reason"] = "sustained post-speech silence"
                            break

            # 4. Inside Zoom Web Client: dismiss benign interstitials without enabling cam/mic
            if (state["joined_web"] or "/wc/" in target_page.url or "zoom.us/s/" in target_page.url) and (time.time() - last_dismiss > 5.0):
                last_dismiss = time.time()
                acts = try_zoom_web_client_dismiss_and_audio(target_page)
                if acts:
                    log_event("Auto-handled Zoom UI: " + "; ".join(acts))
                    if not state["recording"]:
                        state["segment"] += 1
                        try:
                            rec_info = start_recording_target(
                                ctrl_page, target_page, state["segment"],
                                args.fps, args.video_bps, args.audio_bps, suppress_local,
                            )
                            state["recording"] = True
                            log_event(f"Started recording seg {state['segment']}: {rec_info}")
                        except Exception as exc:
                            log_event(f"Error starting recorder: {exc}")
                    try:
                        target_page.screenshot(path=str(screenshot_path))
                        last_shot = time.time()
                    except Exception:
                        pass

            # 5. Check for agent command file
            if cmd_path.exists():
                try:
                    cmd_data = json.loads(cmd_path.read_text(encoding="utf-8"))
                    cmd_path.unlink()
                    act = cmd_data.get("action", "")
                    if act == "stop":
                        stop_flag["stop"] = True
                        stop_flag["reason"] = "agent stop command"
                        state["last_cmd_result"] = "stopping"
                        log_event("Received stop command")
                    elif act == "screenshot":
                        target_page.screenshot(path=str(screenshot_path))
                        last_shot = time.time()
                        state["last_cmd_result"] = f"screenshot saved at {datetime.now().isoformat()}"
                        log_event("Saved on-demand screenshot")
                    elif act == "start_recording":
                        state["segment"] += 1
                        rec_info = start_recording_target(
                            ctrl_page, target_page, state["segment"],
                            args.fps, args.video_bps, args.audio_bps, suppress_local,
                        )
                        state["recording"] = True
                        state["last_cmd_result"] = f"started seg {state['segment']}: {rec_info}"
                        log_event(state["last_cmd_result"])
                    elif act == "click":
                        r = try_click_in_any_frame(target_page, selector=cmd_data.get("selector"))
                        state["last_cmd_result"] = r or "not found"
                        log_event(f"cmd click: {state['last_cmd_result']}")
                        time.sleep(1.0)
                        target_page.screenshot(path=str(screenshot_path))
                    elif act == "click_text":
                        r = try_click_in_any_frame(target_page, text=cmd_data.get("text"))
                        state["last_cmd_result"] = r or "not found"
                        log_event(f"cmd click_text: {state['last_cmd_result']}")
                        time.sleep(1.0)
                        target_page.screenshot(path=str(screenshot_path))
                    elif act == "switch_page":
                        idx = int(cmd_data.get("index", 0))
                        if 0 <= idx < len(ctx.pages) and ctx.pages[idx] != ctrl_page:
                            target_page = ctx.pages[idx]
                            target_page.bring_to_front()
                            state["last_cmd_result"] = f"switched to page {idx}: {target_page.url}"
                            target_page.screenshot(path=str(screenshot_path))
                    elif act == "dump_text":
                        txt_path = scratch_dir / f"{args.slug}_dom.txt"
                        txt_path.write_text(collect_frame_texts(target_page), encoding="utf-8")
                        state["last_cmd_result"] = f"dumped text to {txt_path}"
                except Exception as exc:
                    state["last_cmd_result"] = f"cmd error: {exc}"
                    log_event(state["last_cmd_result"])

            # 6. Periodic screenshot (every 20s during first 8 min, every 90s thereafter)
            shot_interval = 20.0 if (time.time() - started_at) < 480 else 90.0
            if time.time() - last_shot >= shot_interval:
                try:
                    target_page.screenshot(path=str(screenshot_path))
                    last_shot = time.time()
                except Exception:
                    pass

            write_status(target_page, ctx)
            time.sleep(2.0)

        log_event(f"Shutting down recorder ({stop_flag['reason'] or 'deadline reached'})...")
        if state["recording"]:
            try:
                ctrl_page.evaluate("window.stopCapture()")
                time.sleep(1.0)
            except Exception as exc:
                log_event(f"stopCapture warning: {exc}")
        try:
            target_page.screenshot(path=str(screenshot_path))
        except Exception:
            pass
        write_status(target_page, ctx)
        browser.close()

    segments = srv.close()
    final_mkv = recordings_dir / f"{args.slug}.mkv"
    final_path = finalize_recordings(segments, final_mkv, auto_trim_silence=not args.no_auto_trim_silence)
    state["recording"] = False
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    state["final_media_path"] = str(final_path) if final_path else None
    state["segments"] = [str(s) for s in segments]
    status_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"DONE. Final recording: {final_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
