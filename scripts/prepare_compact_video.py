"""
Prepare an ingestion-ready compact media file while preserving audio fidelity.

Supports online video and podcast URLs (YouTube, YouTube Music, Apple Podcasts,
Spotify episodes via public RSS enclosure matching, direct media URLs), local video
files (MP4, MOV, MKV, WebM), audio-only files (M4A, MP3, WAV, FLAC, OGG), diverse
audio codecs (AAC, MP3, Opus, Vorbis, PCM), true-stereo vs. dual-mono topology checks
(-45 dB RMS threshold), no-upscale scaling, and compaction-safe lossless segmentation.

Usage:
    python prepare_compact_video.py --input-path panel.mp4
    python prepare_compact_video.py --url "https://www.youtube.com/watch?v=..." -o out/compact.mp4
    python prepare_compact_video.py --url "https://podcasts.apple.com/..."
    python prepare_compact_video.py --url "https://open.spotify.com/episode/..."
    python prepare_compact_video.py --input-path interview.wav
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

COMPRESSED_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "libopus", "libvorbis"}
MP4_COPY_CODECS = {"aac", "mp3"}
MKV_COPY_CODECS = {"opus", "vorbis", "libopus", "libvorbis"}
AUDIO_ONLY_EXT_BY_CODEC = {
    "aac": ".m4a",
    "mp3": ".mp3",
    "opus": ".opus",
    "libopus": ".opus",
    "vorbis": ".ogg",
    "libvorbis": ".ogg",
}
HTTP_USER_AGENT = "Mozilla/5.0 (compatible; video-transcription-skill/1.0)"


def require_binary(name: str) -> str:
    """Return path to a required binary or raise a helpful cross-platform error."""
    found = shutil.which(name)
    if found:
        return found
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        hint = "Install on macOS via: brew install ffmpeg"
    elif sys_name == "windows":
        hint = "Install on Windows via: winget install Gyan.FFmpeg"
    else:
        hint = "Install on Linux via: sudo apt install ffmpeg (or your distro package manager)"
    raise FileNotFoundError(f"Required executable '{name}' not found on PATH. {hint}")


def _http_get_bytes(url: str, timeout: int = 30) -> tuple[str, dict[str, str], bytes]:
    """Fetch a public HTTP resource with a standard User-Agent header."""
    req = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.geturl(), headers, resp.read()


def is_spotify_episode_url(url: str) -> bool:
    """Return True for Spotify podcast episode URLs."""
    parsed = urllib.parse.urlparse(url)
    return "open.spotify.com" in parsed.netloc.lower() and "/episode/" in parsed.path


def is_apple_podcasts_url(url: str) -> bool:
    """Return True for Apple Podcasts URLs."""
    return "podcasts.apple.com" in urllib.parse.urlparse(url).netloc.lower()


def _normalize_title(text: str) -> str:
    """Normalize episode or show titles for reliable fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", " ", html_lib.unescape(text or "").lower()).strip()


def _titles_match(target: str, candidate: str) -> bool:
    """Check whether two normalized podcast episode titles match closely."""
    t_norm = _normalize_title(target)
    c_norm = _normalize_title(candidate)
    if not t_norm or not c_norm:
        return False
    if t_norm == c_norm or t_norm in c_norm or c_norm in t_norm:
        return True
    t_words = set(t_norm.split())
    c_words = set(c_norm.split())
    overlap = len(t_words & c_words)
    return overlap >= max(3, int(0.8 * min(len(t_words), len(c_words))))


def _safe_filename_stem(title: str, item_id: str) -> str:
    """Build a cross-platform ASCII-safe stem matching yt-dlp --restrict-filenames style."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", title or "podcast_episode").strip("_.")
    cleaned = cleaned[:80] or "podcast_episode"
    return f"{cleaned}_[{item_id}]" if item_id else cleaned


def _format_upload_date(raw_date: str) -> str:
    """Convert ISO-8601 or RSS RFC-2822 dates into YYYYMMDD."""
    if not raw_date:
        return ""
    iso_m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw_date.strip())
    if iso_m:
        return "".join(iso_m.groups())
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(raw_date).strftime("%Y%m%d")
    except Exception:
        return ""


def _parse_duration_seconds(raw_val: str | int | float | None) -> int:
    """Parse duration from seconds, milliseconds, or HH:MM:SS string into whole seconds."""
    if raw_val is None or raw_val == "":
        return 0
    if isinstance(raw_val, (int, float)):
        return int(raw_val)
    text = str(raw_val).strip()
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if all(p.isdigit() for p in parts) and 2 <= len(parts) <= 3:
        total = 0
        for p in parts:
            total = total * 60 + int(p)
        return total
    return 0


def _format_duration_string(seconds: int) -> str:
    """Format seconds as MM:SS or H:MM:SS."""
    if seconds <= 0:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _fetch_spotify_episode_meta(url: str) -> tuple[str, str, str]:
    """Extract (episode_id, episode_title, show_name) from public Spotify episode metadata."""
    m = re.search(r"/episode/([A-Za-z0-9]+)", url)
    ep_id = m.group(1) if m else ""
    oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url, safe='')}"
    _, _, obody = _http_get_bytes(oembed_url, timeout=20)
    oembed = json.loads(obody.decode("utf-8"))
    ep_title = html_lib.unescape(oembed.get("title", "")).strip()

    show_name = ""
    try:
        _, _, page_bytes = _http_get_bytes(url, timeout=20)
        page_html = page_bytes.decode("utf-8", errors="replace")
        og_desc = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', page_html)
        if og_desc:
            raw_desc = html_lib.unescape(og_desc.group(1))
            show_name = raw_desc.split("·")[0].strip()
        if not show_name:
            meta_desc = re.search(r'from\s+(.+?)\s+on Spotify', page_html)
            if meta_desc:
                show_name = html_lib.unescape(meta_desc.group(1)).strip()
    except Exception:
        pass
    return ep_id, ep_title, show_name


def _parse_rss_for_episode(feed_url: str, ep_title: str, show_name: str = "") -> dict | None:
    """Scan a podcast RSS feed XML for an episode matching ep_title."""
    if not feed_url:
        return None
    _, _, xml_bytes = _http_get_bytes(feed_url, timeout=30)
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return None
    channel_title = (channel.findtext("title") or show_name).strip()
    itunes_ns = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        if not _titles_match(ep_title, title):
            continue
        enc = item.find("enclosure")
        enc_url = enc.attrib.get("url", "").strip() if enc is not None else ""
        if not enc_url:
            continue
        dur_sec = _parse_duration_seconds(item.findtext(f"{itunes_ns}duration"))
        return {
            "title": title,
            "channel": channel_title,
            "description": re.sub(r"<[^>]+>", " ", item.findtext("description") or "").strip(),
            "upload_date": _format_upload_date(item.findtext("pubDate") or ""),
            "duration": dur_sec,
            "enclosure_url": enc_url,
            "enclosure_type": enc.attrib.get("type", "") if enc is not None else "",
        }
    return None


def _find_podcast_episode_meta(show_name: str, ep_title: str, apple_url: str = "") -> dict | None:
    """Resolve a public podcast audio enclosure via iTunes Lookup/Search APIs and RSS."""
    if apple_url:
        cid_m = re.search(r"/id(\d+)", apple_url)
        tid_m = re.search(r"[?&]i=(\d+)", apple_url)
        if cid_m:
            cid, tid = cid_m.group(1), (tid_m.group(1) if tid_m else "")
            lookup_url = f"https://itunes.apple.com/lookup?id={cid}&entity=podcastEpisode&limit=50"
            _, _, lbody = _http_get_bytes(lookup_url, timeout=20)
            results = json.loads(lbody.decode("utf-8")).get("results", [])
            feed_url = results[0].get("feedUrl", "") if results else ""
            show_fallback = results[0].get("collectionName", show_name) if results else show_name
            for entry in results[1:]:
                if (tid and str(entry.get("trackId", "")) == tid) or (
                    ep_title and _titles_match(ep_title, entry.get("trackName", ""))
                ):
                    if entry.get("episodeUrl"):
                        return {
                            "title": entry.get("trackName", ep_title),
                            "channel": entry.get("collectionName", show_fallback),
                            "description": entry.get("description", ""),
                            "upload_date": _format_upload_date(entry.get("releaseDate", "")),
                            "duration": int(entry.get("trackTimeMillis", 0) // 1000),
                            "enclosure_url": entry["episodeUrl"],
                            "enclosure_type": "",
                        }
            if feed_url and ep_title:
                found = _parse_rss_for_episode(feed_url, ep_title, show_fallback)
                if found:
                    return found

    queries = [q for q in (f"{show_name} {ep_title}".strip(), ep_title) if q]
    for q in queries:
        search_url = (
            "https://itunes.apple.com/search?media=podcast&entity=podcastEpisode&limit=15&term="
            + urllib.parse.quote(q)
        )
        _, _, sbody = _http_get_bytes(search_url, timeout=20)
        for entry in json.loads(sbody.decode("utf-8")).get("results", []):
            if not entry.get("episodeUrl"):
                continue
            if _titles_match(ep_title, entry.get("trackName", "")):
                if show_name and not _titles_match(show_name, entry.get("collectionName", "")):
                    if _normalize_title(show_name) not in _normalize_title(entry.get("collectionName", "")):
                        continue
                return {
                    "title": entry.get("trackName", ep_title),
                    "channel": entry.get("collectionName", show_name),
                    "description": entry.get("description", ""),
                    "upload_date": _format_upload_date(entry.get("releaseDate", "")),
                    "duration": int(entry.get("trackTimeMillis", 0) // 1000),
                    "enclosure_url": entry["episodeUrl"],
                    "enclosure_type": "",
                }

    if show_name:
        show_url = (
            "https://itunes.apple.com/search?media=podcast&entity=podcast&limit=5&term="
            + urllib.parse.quote(show_name)
        )
        _, _, shbody = _http_get_bytes(show_url, timeout=20)
        for show in json.loads(shbody.decode("utf-8")).get("results", []):
            found = _parse_rss_for_episode(show.get("feedUrl", ""), ep_title, show.get("collectionName", show_name))
            if found:
                return found
    return None


def _guess_audio_ext(final_url: str, content_type: str, fallback_type: str = "") -> str:
    """Determine audio file extension from HTTP Content-Type or enclosure URL path."""
    ctype = (content_type or fallback_type or "").split(";")[0].strip().lower()
    type_map = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/flac": ".flac",
    }
    if ctype in type_map:
        return type_map[ctype]
    suffix = Path(urllib.parse.urlparse(final_url).path).suffix.lower()
    return suffix if suffix in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"} else ".mp3"


def resolve_and_download_podcast(url: str, dl_dir: Path) -> Path:
    """Resolve Spotify or Apple Podcasts episode URL to public RSS enclosure audio + info.json."""
    parsed = urllib.parse.urlparse(url)
    if "open.spotify.com" in parsed.netloc.lower() and not is_spotify_episode_url(url):
        raise RuntimeError(
            "Pass a specific Spotify episode URL (open.spotify.com/episode/...), not a show or playlist URL."
        )

    item_id = ""
    if is_spotify_episode_url(url):
        item_id, ep_title, show_name = _fetch_spotify_episode_meta(url)
        print(f"\nResolving Spotify episode via public podcast RSS directory: '{ep_title}' ({show_name or 'podcast'})...")
        meta = _find_podcast_episode_meta(show_name, ep_title)
    else:
        slug_m = re.search(r"/podcast/([^/]+)/id(\d+)", parsed.path)
        track_m = re.search(r"[?&]i=(\d+)", url)
        ep_title = slug_m.group(1).replace("-", " ") if slug_m else ""
        item_id = track_m.group(1) if track_m else (slug_m.group(2) if slug_m else "")
        print("\nResolving Apple Podcasts episode via public iTunes/RSS directory...")
        meta = _find_podcast_episode_meta("", ep_title, apple_url=url)

    if not meta or not meta.get("enclosure_url"):
        raise RuntimeError(
            f"Could not resolve a public DRM-free RSS audio enclosure for '{url}'. "
            "If this is a platform-exclusive paid/subscriber feed, download or export the audio locally and use --input-path."
        )

    print(f"Downloading podcast audio enclosure: {meta['enclosure_url']}")
    final_url, resp_headers, audio_bytes = _http_get_bytes(meta["enclosure_url"], timeout=120)
    ext = _guess_audio_ext(final_url, resp_headers.get("content-type", ""), meta.get("enclosure_type", ""))
    stem = _safe_filename_stem(meta["title"], item_id)
    audio_path = dl_dir / f"{stem}{ext}"
    audio_path.write_bytes(audio_bytes)

    dur = int(meta.get("duration") or 0)
    info_payload = {
        "title": meta["title"],
        "channel": meta.get("channel", ""),
        "uploader": meta.get("channel", ""),
        "upload_date": meta.get("upload_date", ""),
        "duration": dur,
        "duration_string": _format_duration_string(dur),
        "description": meta.get("description", ""),
        "webpage_url": url,
        "enclosure_url": final_url,
        "extractor": "podcast-rss",
    }
    info_path = audio_path.with_suffix(".info.json")
    info_path.write_text(json.dumps(info_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Downloaded: {audio_path} (metadata -> {info_path.name})")
    return audio_path


def download_source_video(url: str, output_path: str | None, audio_only: bool = False) -> Path:
    """Download online video or podcast URL preferring non-DRC audio and writing .info.json."""
    dl_dir = Path(output_path).parent if output_path else Path.cwd()
    if not str(dl_dir):
        dl_dir = Path.cwd()
    dl_dir.mkdir(parents=True, exist_ok=True)

    if is_spotify_episode_url(url) or ("open.spotify.com" in urllib.parse.urlparse(url).netloc.lower()):
        return resolve_and_download_podcast(url, dl_dir)

    out_template = str(dl_dir / "%(title).80B [%(id)s].%(ext)s")
    yt_exe = shutil.which("yt-dlp")
    base_cmd = [yt_exe] if yt_exe else [sys.executable, "-m", "yt_dlp"]
    if audio_only:
        fmt = "ba[format_id!*=-drc][ext=m4a]/ba[format_id!*=-drc]/ba/b"
        merge_args: list[str] = []
        mode_note = "audio-only, non-DRC, info.json"
    else:
        fmt = "bv*[height<=480]+ba[format_id!*=-drc]/b[height<=480]/bv*+ba[format_id!*=-drc]/b/ba[format_id!*=-drc]/ba"
        merge_args = ["--merge-output-format", "mp4"]
        mode_note = "non-DRC audio, height<=480 or audio feed, info.json"

    cmd = [
        *base_cmd,
        "-f",
        fmt,
        *merge_args,
        "--write-info-json",
        "--restrict-filenames",
        "-o",
        out_template,
        "--print",
        "after_move:filepath",
        url,
    ]

    print(f"\nDownloading source media ({mode_note})...")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        if is_apple_podcasts_url(url):
            print("yt-dlp failed on Apple Podcasts URL; falling back to iTunes/RSS resolver...", file=sys.stderr)
            return resolve_and_download_podcast(url, dl_dir)
        if res.stdout:
            print(res.stdout, file=sys.stderr)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
        hint = (
            "Ensure yt-dlp is installed (macOS: brew install yt-dlp | "
            "Windows: winget install yt-dlp.yt-dlp | pip install -U yt-dlp)."
        )
        raise RuntimeError(f"yt-dlp failed with exit code {res.returncode}. {hint}")

    candidates = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    downloaded = next((Path(p) for p in reversed(candidates) if Path(p).is_file()), None)
    if not downloaded:
        if is_apple_podcasts_url(url):
            return resolve_and_download_podcast(url, dl_dir)
        raise FileNotFoundError("Download finished but output file path could not be resolved.")

    print(f"Downloaded: {downloaded}")
    return downloaded


def probe_field(ffprobe_bin: str, media_path: Path, probe_args: list[str]) -> str:
    """Run ffprobe with given selection args and return stripped stdout."""
    res = subprocess.run(
        [ffprobe_bin, "-v", "error", *probe_args, str(media_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return res.stdout.strip()


def probe_duration_sec(ffprobe_bin: str, media_path: Path) -> float:
    """Return media duration in seconds via ffprobe, or 0.0 if unavailable."""
    raw = probe_field(
        ffprobe_bin,
        media_path,
        ["-show_entries", "format=duration", "-of", "default=nw=1:nk=1"],
    )
    try:
        return float(raw)
    except ValueError:
        return 0.0


def inspect_topology(ffmpeg_bin: str, resolved_input: Path, channels: int) -> None:
    """Check whether a 2-channel track has real stereo separation or dual-mono dither."""
    if channels == 1:
        print("\nChannel topology: Mono (1 channel).")
        return
    if channels != 2:
        print(f"\nChannel topology: {channels} audio channels detected.")
        return

    print("\nChecking stereo channel difference (c0 - c1)...")
    res = subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-i",
            str(resolved_input),
            "-af",
            "pan=mono|c0=c0-c1,astats=measure_perchannel=0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = f"{res.stderr}\n{res.stdout}"
    match = re.search(r"RMS level dB:\s*(-inf|[-\d\.]+)", combined)
    if not match:
        return

    rms_str = match.group(1)
    is_dual_mono = rms_str == "-inf"
    if not is_dual_mono:
        try:
            is_dual_mono = float(rms_str) <= -45.0
        except ValueError:
            is_dual_mono = False

    if is_dual_mono:
        print(
            f"Channel topology: Dual-mono / negligible stereo separation "
            f"(RMS diff = {rms_str} dB). Safe to downmix to mono."
        )
    else:
        print(f"Channel topology: True stereo (RMS diff = {rms_str} dB). Preserving spatial separation.")
        print("Tip: Pass --split-channels to extract_enhanced_clips.py to isolate Left/Right crosstalk.")


def compact_audio_only(
    ffmpeg_bin: str,
    resolved_input: Path,
    audio_codec: str,
    orig_mb: float,
    output_path: Path | None,
    has_video: bool = False,
) -> Path:
    """Compact or pass through an audio-only target while preserving speech clarity."""
    native_ext = AUDIO_ONLY_EXT_BY_CODEC.get(audio_codec, ".m4a")
    print(f"\nPreparing audio-only output (source codec: {audio_codec}, has_video: {has_video}).")

    if not has_video and audio_codec in COMPRESSED_AUDIO_CODECS and orig_mb < 90.0:
        if output_path is None:
            print(f"Audio is already compressed ({audio_codec}) and under 90 MB ({orig_mb} MB). Keep as-is.")
            return resolved_input
        if output_path.suffix.lower() == resolved_input.suffix.lower():
            if output_path != resolved_input:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resolved_input, output_path)
                print(f"Copied compact audio directly without re-encoding -> {output_path} ({orig_mb} MB)")
            return output_path

    if has_video and audio_codec in COMPRESSED_AUDIO_CODECS:
        target = output_path or resolved_input.with_name(f"{resolved_input.stem}_compact{native_ext}")
        can_copy = (
            (target.suffix.lower() == native_ext)
            or (audio_codec in {"opus", "libopus"} and target.suffix.lower() == ".webm")
            or (audio_codec == "aac" and target.suffix.lower() == ".mp4")
        )
        if can_copy:
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"Extracting audio-only track cleanly (-vn -c:a copy) -> {target}")
            res = subprocess.run(
                [ffmpeg_bin, "-y", "-i", str(resolved_input), "-vn", "-c:a", "copy", str(target), "-loglevel", "error"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode != 0:
                raise RuntimeError(f"ffmpeg audio stream extraction failed ({res.returncode}): {res.stderr}")
            return target

    target = output_path or resolved_input.with_name(f"{resolved_input.stem}_compact.m4a")
    target.parent.mkdir(parents=True, exist_ok=True)
    enc_map = {".mp3": ("libmp3lame", "192k"), ".ogg": ("libvorbis", "128k"), ".opus": ("libopus", "96k")}
    enc_codec, enc_bitrate = enc_map.get(target.suffix.lower(), ("aac", "128k"))
    print(f"Encoding audio ({audio_codec}, {orig_mb} MB) to {enc_bitrate} {enc_codec} -> {target}")
    res = subprocess.run(
        [ffmpeg_bin, "-y", "-i", str(resolved_input), "-vn", "-c:a", enc_codec, "-b:a", enc_bitrate, str(target), "-loglevel", "error"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg audio compaction failed ({res.returncode}): {res.stderr}")
    return target


def compact_video_stream(
    ffmpeg_bin: str,
    resolved_input: Path,
    audio_codec: str,
    output_path: Path | None,
    width: int,
    fps: int,
    crf: int,
) -> Path:
    """Transcode video down to low-FPS no-upscale H.264 with lossless or 128k AAC audio."""
    if audio_codec in MP4_COPY_CODECS:
        default_ext = ".mp4"
        audio_args = ["-c:a", "copy"]
        audio_mode = "lossless bitstream copy (-c:a copy)"
    elif audio_codec in MKV_COPY_CODECS:
        if output_path and output_path.suffix.lower() == ".mp4":
            print(
                f"Warning: Audio codec '{audio_codec}' cannot be safely muxed into .mp4 with -c:a copy. "
                "Transcoding audio to 128k AAC (omit --output-path to preserve -c:a copy in .mkv).",
                file=sys.stderr,
            )
            default_ext = ".mp4"
            audio_args = ["-c:a", "aac", "-b:a", "128k"]
            audio_mode = "high-bitrate 128k AAC transcode"
        else:
            default_ext = ".mkv"
            audio_args = ["-c:a", "copy"]
            audio_mode = "lossless bitstream copy into .mkv (-c:a copy)"
    else:
        print(
            f"Warning: Uncompressed/lossless audio codec '{audio_codec}' detected. "
            "Encoding at high-bitrate 128k AAC to stay under ingestion size limits.",
            file=sys.stderr,
        )
        default_ext = ".mp4"
        audio_args = ["-c:a", "aac", "-b:a", "128k"]
        audio_mode = "high-bitrate 128k AAC transcode"

    target = output_path or resolved_input.with_name(f"{resolved_input.stem}_compact_{fps}fps{default_ext}")
    target.parent.mkdir(parents=True, exist_ok=True)
    gop_frames = max(1, fps * 10)
    vf = f"scale=trunc(min({width}\\,iw)/2)*2:-2,fps={fps}"

    print(
        f"\nCreating {fps} FPS video (max {width}px wide, no upscale, CRF {crf}, "
        f"keyint {gop_frames}) with {audio_mode}..."
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(resolved_input),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-g",
        str(gop_frames),
        "-crf",
        str(crf),
        "-preset",
        "veryfast",
        *audio_args,
        str(target),
        "-loglevel",
        "error",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg video compaction failed ({res.returncode}): {res.stderr}")
    return target


def segment_if_needed(
    ffmpeg_bin: str,
    ffprobe_bin: str,
    output_path: Path,
    new_mb: float,
    segment_seconds: int,
    trigger_minutes: float,
    trigger_mb: float,
) -> list[Path]:
    """Split oversized or long (>25 min) compact media into lossless ingestion chunks."""
    if segment_seconds <= 0:
        return []

    out_duration_min = round(probe_duration_sec(ffprobe_bin, output_path) / 60.0, 2)
    if new_mb <= trigger_mb and out_duration_min <= trigger_minutes:
        return []

    print(
        f"\nOutput ({new_mb} MB, {out_duration_min} min) exceeds compaction-safe threshold "
        f"({trigger_mb} MB / {trigger_minutes} min). Splitting into {segment_seconds}s lossless segments..."
    )
    seg_dir = output_path.parent
    seg_base = output_path.stem
    seg_ext = output_path.suffix
    seg_pattern = seg_dir / f"{seg_base}_part%02d{seg_ext}"

    res = subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(output_path),
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            "-c",
            "copy",
            str(seg_pattern),
            "-loglevel",
            "error",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg segmentation failed ({res.returncode}): {res.stderr}")

    segments = sorted(seg_dir.glob(f"{seg_base}_part*{seg_ext}"))
    for seg in segments:
        part_mb = round(seg.stat().st_size / (1024 * 1024), 2)
        print(f"  Segment: {seg} ({part_mb} MB)")
    return segments


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compact video/audio to <=480px 1 FPS with lossless/high-bitrate audio and auto-segmentation."
    )
    parser.add_argument("-i", "--input-path", dest="input_path", default="", help="Local source media file")
    parser.add_argument(
        "-u",
        "--url",
        default="",
        help="Online video or podcast URL (YouTube, YouTube Music, Apple Podcasts, Spotify episode)",
    )
    parser.add_argument("-o", "--output-path", dest="output_path", default="", help="Target compact media path")
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download/extract audio-only without video frames (ideal for podcasts & music.youtube.com)",
    )
    parser.add_argument("--width", type=int, default=480, help="Max video width in pixels (default: 480, no upscale)")
    parser.add_argument("--fps", type=int, default=1, help="Target video frame rate (default: 1)")
    parser.add_argument("--crf", type=int, default=35, help="x264 CRF quality factor (default: 35)")
    parser.add_argument(
        "--segment-seconds",
        type=int,
        default=1200,
        help="Lossless segment duration in seconds when threshold exceeded (default: 1200; 0 disables)",
    )
    parser.add_argument(
        "--segment-trigger-minutes",
        type=float,
        default=25.0,
        help="Auto-segment compact outputs longer than N minutes (default: 25.0)",
    )
    parser.add_argument(
        "--segment-trigger-mb",
        type=float,
        default=45.0,
        help="Auto-segment compact outputs larger than N MB (default: 45.0)",
    )
    args = parser.parse_args()

    if not args.input_path and not args.url:
        parser.error("Provide either --input-path <file> or --url <video_url>.")

    ffmpeg_bin = require_binary("ffmpeg")
    ffprobe_bin = require_binary("ffprobe")

    if args.url and not args.input_path:
        input_path = download_source_video(args.url, args.output_path or None, audio_only=args.audio_only)
    else:
        input_path = Path(args.input_path).expanduser()

    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    resolved_input = input_path.resolve()
    output_arg = Path(args.output_path).expanduser().resolve() if args.output_path else None
    orig_mb = round(resolved_input.stat().st_size / (1024 * 1024), 2)

    print(f"Inspecting streams for: {resolved_input} ({orig_mb} MB)")
    info_res = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-show_entries",
            "stream=index,codec_type,codec_name,bit_rate,channels,sample_rate,width,height",
            "-of",
            "default=noprint_wrappers=1",
            str(resolved_input),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if info_res.stdout:
        print(info_res.stdout.rstrip())

    video_streams = probe_field(
        ffprobe_bin, resolved_input, ["-select_streams", "v", "-show_entries", "stream=index", "-of", "csv=p=0"]
    )
    has_video = bool(video_streams)
    audio_codec = probe_field(
        ffprobe_bin, resolved_input, ["-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1"]
    ).lower()
    channels_raw = probe_field(
        ffprobe_bin, resolved_input, ["-select_streams", "a:0", "-show_entries", "stream=channels", "-of", "default=nw=1:nk=1"]
    )
    channels = int(channels_raw) if channels_raw.isdigit() else 0

    if channels == 0 or not audio_codec:
        raise RuntimeError(f"No audio stream found in: {resolved_input}")

    inspect_topology(ffmpeg_bin, resolved_input, channels)

    if args.audio_only or not has_video:
        final_output = compact_audio_only(
            ffmpeg_bin, resolved_input, audio_codec, orig_mb, output_arg, has_video=has_video
        )
    else:
        final_output = compact_video_stream(
            ffmpeg_bin, resolved_input, audio_codec, output_arg, args.width, args.fps, args.crf
        )

    new_mb = round(final_output.stat().st_size / (1024 * 1024), 2)
    print("\nCompaction summary:")
    print(f"Original size : {orig_mb} MB")
    print(f"Compact size  : {new_mb} MB")
    print(f"Output path   : {final_output}")

    segment_if_needed(
        ffmpeg_bin,
        ffprobe_bin,
        final_output,
        new_mb,
        args.segment_seconds,
        args.segment_trigger_minutes,
        args.segment_trigger_mb,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
