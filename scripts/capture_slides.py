"""
Extract high-resolution slide PNGs from full-resolution source video, detect fixed
broadcast PiP slide crop boxes, generate an interactive HTML HITL curation review
page, and package approved reusable assets with an index.md catalog.

Standard-library only at import time (Pillow/numpy optional for pixel-exact crop
detection, with automatic fallback when unavailable). Requires ffmpeg on PATH.

Usage:
    python capture_slides.py detect-crop --input-path recordings/talk.mp4 --timestamps 00:00:48 00:02:06
    python capture_slides.py extract --input-path recordings/talk.mp4 --manifest scratch/manifest.json --output-dir scratch/slide_candidates --crop crop=1470:826:434:16
    python capture_slides.py review-html --manifest scratch/manifest.json --slides-dir scratch/slide_candidates --output-html scratch/slide_curation_review.html
    python capture_slides.py package --manifest scratch/manifest.json --decisions scratch/hitl_slide_decisions.json --slides-dir scratch/slide_candidates --output-dir transcripts/My_Talk/assets
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def require_ffmpeg() -> str:
    """Locate ffmpeg on PATH or raise a clear installation hint."""
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError(
            "Required executable 'ffmpeg' not found on PATH. "
            "Install via winget install Gyan.FFmpeg (Windows), brew install ffmpeg (macOS), "
            "or sudo apt install ffmpeg (Linux)."
        )
    return found


def slugify(text: str, max_len: int = 44) -> str:
    """Create a clean lowercase underscore slug suitable for cross-platform filenames."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "slide").lower()).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_")
    return cleaned or "slide"


def timestamp_to_tag(ts: str) -> str:
    """Convert HH:MM:SS or MM:SS into a compact filename tag like 02m06s or 1h02m06s."""
    parts = [int(p) for p in ts.strip().split(":")]
    if len(parts) == 3:
        h, m, s = parts
        return f"{h}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"
    if len(parts) == 2:
        m, s = parts
        return f"{m:02d}m{s:02d}s"
    raise ValueError(f"Unsupported timestamp format: {ts}")


def build_asset_filename(order_idx: int, ts: str, title: str, slug_override: str = "") -> str:
    """Build chronological, timestamped, reusable asset filename NN_MMmSSs_slug.png."""
    tag = timestamp_to_tag(ts)
    slug = slugify(slug_override or title)
    return f"{order_idx:02d}_{tag}_{slug}.png"


def _even_inset_box(x0: int, y0: int, x1: int, y1: int, inset: int = 1) -> tuple[int, int, int, int]:
    """Inset a detected [x0..x1, y0..y1] canvas box slightly and round to clean even WxH."""
    nx0 = x0 + inset
    ny0 = y0 + inset
    nx1 = x1 - inset
    ny1 = y1 - inset
    w = max(2, (nx1 - nx0 + 1) // 2 * 2)
    h = max(2, (ny1 - ny0 + 1) // 2 * 2)
    return nx0, ny0, w, h


def detect_white_canvas_box(image_path: Path, white_threshold: int = 240) -> tuple[int, int, int, int] | None:
    """
    Detect a bright/white rectangular slide canvas embedded inside a dark broadcast PiP frame.
    Returns (x, y, w, h) or None if the frame is already full-bleed or Pillow/numpy is missing.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None

    im = Image.open(image_path).convert("RGB")
    arr = np.array(im)
    height, width, _ = arr.shape

    white = (
        (arr[:, :, 0] >= white_threshold)
        & (arr[:, :, 1] >= white_threshold)
        & (arr[:, :, 2] >= white_threshold)
    )

    row_counts = white.sum(axis=1)
    candidate_rows = np.where(row_counts > int(width * 0.40))[0]
    if len(candidate_rows) < int(height * 0.35):
        return None

    # Find largest contiguous vertical run of bright slide rows
    splits = np.where(np.diff(candidate_rows) > 4)[0] + 1
    runs = np.split(candidate_rows, splits)
    best_y_run = max(runs, key=len)
    y0, y1 = int(best_y_run[0]), int(best_y_run[-1])

    col_frac = white[y0 : y1 + 1, :].mean(axis=0)
    candidate_cols = np.where(col_frac > 0.50)[0]
    if len(candidate_cols) < int(width * 0.40):
        return None

    col_splits = np.where(np.diff(candidate_cols) > 4)[0] + 1
    col_runs = np.split(candidate_cols, col_splits)
    best_x_run = max(col_runs, key=len)
    x0, x1 = int(best_x_run[0]), int(best_x_run[-1])

    # If the bright area covers nearly the entire frame, treat as uncropped full-frame slide
    if (x1 - x0 + 1) >= int(width * 0.96) and (y1 - y0 + 1) >= int(height * 0.96):
        return None

    return _even_inset_box(x0, y0, x1, y1, inset=1)


def detect_broadcast_crop(ffmpeg_bin: str, video_path: Path, timestamps: list[str]) -> str:
    """Probe sample timestamps from full-res video and return consensus ffmpeg crop filter or 'none'."""
    boxes: list[tuple[int, int, int, int]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for i, ts in enumerate(timestamps, start=1):
            frame_path = tmp / f"probe_{i:02d}.png"
            subprocess.run(
                [ffmpeg_bin, "-y", "-ss", ts, "-i", str(video_path), "-frames:v", "1", str(frame_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            box = detect_white_canvas_box(frame_path)
            if box:
                boxes.append(box)
                x, y, w, h = box
                print(f"Probe {ts}: detected canvas x={x}, y={y}, w={w}, h={h} (aspect={w/h:.4f})")
            else:
                print(f"Probe {ts}: full-frame or non-white canvas (no PiP crop detected)")

    if not boxes:
        return "none"

    # Use median across probed frames for stability against single-frame outliers
    xs = sorted(b[0] for b in boxes)
    ys = sorted(b[1] for b in boxes)
    ws = sorted(b[2] for b in boxes)
    hs = sorted(b[3] for b in boxes)
    mid = len(boxes) // 2
    crop_str = f"crop={ws[mid]}:{hs[mid]}:{xs[mid]}:{ys[mid]}"
    print(f"Recommended broadcast crop: {crop_str}")
    return crop_str


def extract_manifest_slides(
    ffmpeg_bin: str,
    video_path: Path,
    manifest: dict,
    output_dir: Path,
    default_crop: str = "",
) -> list[Path]:
    """Extract lossless PNG frames from the full-res source video for every entry in manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    slides = manifest.get("slides", [])
    crop_filter = default_crop if default_crop and default_crop.lower() != "none" else manifest.get("crop", "")
    if crop_filter and crop_filter.lower() == "none":
        crop_filter = ""

    for item in slides:
        fname = item["file"]
        ts = item["ts"]
        use_crop = item.get("use_crop", True)
        out_path = output_dir / fname
        cmd = [ffmpeg_bin, "-y", "-ss", ts, "-i", str(video_path), "-frames:v", "1"]
        if use_crop and crop_filter:
            cmd.extend(["-vf", crop_filter])
        cmd.append(str(out_path))
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        written.append(out_path)
        print(f"Extracted #{item.get('num', len(written)):02d} [{ts}] -> {out_path}")

    return written


def render_review_html(
    manifest: dict,
    slides_rel_dir: str,
    before_sample: str = "",
    after_sample: str = "",
) -> str:
    """Render a self-contained interactive HITL curation HTML page from a slide manifest."""
    title = manifest.get("title", "Slide Curation Review")
    subtitle = manifest.get("subtitle", "")
    crop = manifest.get("crop", "none")
    slides = manifest.get("slides", [])
    n_total = len(slides)
    n_in = sum(1 for s in slides if s.get("verdict") == "IN")
    n_border = sum(1 for s in slides if s.get("verdict") == "BORDERLINE")
    n_out = sum(1 for s in slides if s.get("verdict") == "OUT")
    n_q = sum(1 for s in slides if s.get("question"))
    storage_key = "hitl_slide_review_" + slugify(title, 36)

    crop_compare_html = ""
    if before_sample and after_sample:
        crop_compare_html = f"""
    <div class="crop-compare">
      <figure>
        <img src="{slides_rel_dir}/{before_sample}" alt="Before auto-crop" onclick="openStaticLightbox(this.src, 'Before Auto-Crop: Raw source frame')" />
        <figcaption><strong>Before:</strong> Raw broadcast source frame</figcaption>
      </figure>
      <figure>
        <img src="{slides_rel_dir}/{after_sample}" alt="After auto-crop" onclick="openStaticLightbox(this.src, 'After Auto-Crop: Clean slide asset ({crop})')" />
        <figcaption><strong>After:</strong> Auto-cropped reusable slide PNG (<code>{crop}</code>)</figcaption>
      </figure>
    </div>"""

    slides_json = json.dumps(slides, ensure_ascii=False)
    safe_title = title.replace("<", "&lt;").replace(">", "&gt;")
    safe_sub = subtitle.replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>HITL Slide Curation Review - {safe_title}</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #171a23; --surface-2: #1f2430; --border: #2c3344;
    --text: #e8ecf4; --muted: #9aa4b8; --green: #22c55e; --green-bg: rgba(34,197,94,0.12);
    --green-border: rgba(34,197,94,0.45); --amber: #f59e0b; --amber-bg: rgba(245,158,11,0.13);
    --amber-border: rgba(245,158,11,0.5); --blue: #60a5fa; --blue-bg: rgba(96,165,250,0.13);
    --radius: 12px;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }}
  .container {{ max-width: 1440px; margin: 0 auto; padding: 24px 24px 96px; }}
  header.hero {{ background: linear-gradient(135deg, #171b26 0%, #1c2233 100%); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px 26px; margin-bottom: 18px; }}
  h1 {{ margin: 0 0 6px; font-size: 1.5rem; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; margin: 0; }}
  .stats-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
  .stat-pill {{ background: var(--surface-2); border: 1px solid var(--border); border-radius: 999px; padding: 5px 13px; font-size: 0.83rem; font-weight: 600; }}
  details.methodology {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 18px; margin-bottom: 16px; }}
  details.methodology summary {{ cursor: pointer; font-weight: 700; font-size: 0.94rem; }}
  .crop-compare {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }}
  .crop-compare figure {{ margin: 0; background: #0b0d12; border: 1px solid var(--border); border-radius: 8px; padding: 8px; }}
  .crop-compare img {{ width: 100%; height: auto; display: block; border-radius: 4px; cursor: zoom-in; }}
  .crop-compare figcaption {{ font-size: 0.78rem; color: var(--muted); margin-top: 6px; text-align: center; }}
  .questions-banner {{ background: rgba(245,158,11,0.08); border: 1px solid var(--amber-border); border-radius: var(--radius); padding: 12px 16px; margin-bottom: 16px; }}
  .questions-banner h2 {{ margin: 0 0 8px; font-size: 0.92rem; color: #fbbf24; }}
  .q-chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .q-chip {{ background: rgba(245,158,11,0.14); border: 1px solid rgba(245,158,11,0.35); color: #fde68a; padding: 4px 10px; border-radius: 8px; font-size: 0.8rem; cursor: pointer; text-decoration: none; }}
  .toolbar {{ position: sticky; top: 0; z-index: 40; background: rgba(15,17,23,0.94); backdrop-filter: blur(10px); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }}
  .filter-group, .action-group {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  button.btn {{ background: var(--surface-2); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 6px 11px; font-size: 0.82rem; font-weight: 600; cursor: pointer; }}
  button.btn.active {{ background: var(--blue-bg); border-color: var(--blue); color: #bfdbfe; }}
  button.btn-primary {{ background: #2563eb; border-color: #3b82f6; color: #fff; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(540px, 1fr)); gap: 18px; }}
  @media (max-width: 640px) {{ .grid {{ grid-template-columns: 1fr; }} .crop-compare {{ grid-template-columns: 1fr; }} }}
  .group-header {{ grid-column: 1 / -1; margin: 14px 0 4px; padding: 9px 14px; border-radius: 8px; font-weight: 700; background: var(--surface); border-left: 4px solid var(--blue); }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; display: flex; flex-direction: column; }}
  .card.user-keep {{ border-color: var(--green-border); }}
  .card.user-drop {{ opacity: 0.88; }}
  .card.verdict-BORDERLINE {{ border-color: var(--amber-border); }}
  .card.overridden {{ box-shadow: 0 0 0 2px rgba(96,165,250,0.55); }}
  .card-head {{ padding: 10px 14px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .meta-row {{ display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }}
  .slide-num {{ font-family: ui-monospace, monospace; font-size: 0.8rem; font-weight: 700; background: #0f1117; padding: 2px 7px; border-radius: 6px; border: 1px solid var(--border); }}
  .ts-badge {{ font-family: ui-monospace, monospace; font-size: 0.78rem; color: var(--muted); }}
  .cat-tag {{ font-size: 0.74rem; padding: 2px 8px; border-radius: 999px; background: rgba(148,163,184,0.14); color: #cbd5e1; }}
  .verdict-pill {{ font-size: 0.74rem; font-weight: 700; padding: 3px 9px; border-radius: 999px; }}
  .vp-IN {{ background: var(--green-bg); color: #86efac; border: 1px solid var(--green-border); }}
  .vp-BORDERLINE {{ background: var(--amber-bg); color: #fde68a; border: 1px solid var(--amber-border); }}
  .vp-OUT {{ background: rgba(100,116,139,0.2); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.35); }}
  .override-pill {{ font-size: 0.7rem; font-weight: 700; padding: 2px 7px; border-radius: 999px; background: var(--blue-bg); color: #93c5fd; }}
  .img-wrap {{ position: relative; background: #0a0c10; border-bottom: 1px solid var(--border); cursor: zoom-in; }}
  .img-wrap img {{ width: 100%; height: auto; display: block; }}
  .card-body {{ padding: 13px 15px 15px; display: flex; flex-direction: column; gap: 9px; flex: 1; }}
  .slide-title {{ margin: 0; font-size: 1rem; font-weight: 700; }}
  .chapter-line {{ font-size: 0.77rem; color: var(--muted); margin-top: -5px; }}
  .spoken-quote {{ font-size: 0.83rem; color: #cbd5e1; border-left: 3px solid #3b82f6; padding: 4px 10px; background: rgba(59,130,246,0.06); }}
  .rationale {{ font-size: 0.85rem; }}
  .question-box {{ background: var(--amber-bg); border: 1px solid var(--amber-border); border-radius: 8px; padding: 8px 11px; font-size: 0.83rem; color: #fef3c7; }}
  .hitl-bar {{ margin-top: auto; padding-top: 9px; border-top: 1px dashed var(--border); display: flex; flex-direction: column; gap: 8px; }}
  .seg {{ display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  .seg button {{ background: var(--surface-2); color: var(--muted); border: none; padding: 5px 13px; font-size: 0.8rem; font-weight: 700; cursor: pointer; }}
  .seg button.sel-keep {{ background: var(--green); color: #052e16; }}
  .seg button.sel-drop {{ background: #475569; color: #f8fafc; }}
  .note-input, .global-notes textarea {{ width: 100%; background: #10131b; border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; color: var(--text); font-size: 0.83rem; font-family: inherit; }}
  .global-notes {{ margin-top: 26px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 18px; }}
  .lightbox {{ display: none; position: fixed; inset: 0; z-index: 100; background: rgba(5,7,11,0.92); align-items: center; justify-content: center; flex-direction: column; padding: 20px; }}
  .lightbox.open {{ display: flex; }}
  .lightbox img {{ max-width: 94vw; max-height: 82vh; border-radius: 8px; background: #fff; }}
  .lb-bar {{ margin-top: 10px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: center; }}
  .toast {{ position: fixed; bottom: 24px; right: 24px; background: #16a34a; color: #fff; padding: 10px 16px; border-radius: 8px; font-weight: 600; font-size: 0.85rem; opacity: 0; pointer-events: none; transition: opacity 0.2s; z-index: 200; }}
  .toast.show {{ opacity: 1; }}
</style>
</head>
<body>
<div class="container">
  <header class="hero">
    <h1>HITL Slide Curation Review - {safe_title}</h1>
    <p class="subtitle">{safe_sub}</p>
    <div class="stats-row">
      <span class="stat-pill">{n_total} Total Visuals</span>
      <span class="stat-pill">{n_in} Recommended IN</span>
      <span class="stat-pill">{n_border} Borderline</span>
      <span class="stat-pill">{n_out} Recommended OUT</span>
      <span class="stat-pill" id="liveSummaryPill">Selection: -</span>
    </div>
  </header>
  {f'<details class="methodology" open><summary>Auto-Crop Proof ({crop})</summary>{crop_compare_html}</details>' if crop_compare_html else ''}
  {f'<section class="questions-banner"><h2>Open Editorial Calls ({n_q})</h2><div class="q-chips" id="questionChips"></div></section>' if n_q else ''}
  <div class="toolbar">
    <div class="filter-group">
      <button class="btn active" data-filter="ALL" onclick="setFilter('ALL')">All ({n_total})</button>
      <button class="btn" data-filter="IN" onclick="setFilter('IN')">IN ({n_in})</button>
      <button class="btn" data-filter="BORDERLINE" onclick="setFilter('BORDERLINE')">Borderline ({n_border})</button>
      <button class="btn" data-filter="OUT" onclick="setFilter('OUT')">OUT ({n_out})</button>
      <button class="btn" data-filter="QUESTIONS" onclick="setFilter('QUESTIONS')">Questions ({n_q})</button>
      <button class="btn" data-filter="OVERRIDES" onclick="setFilter('OVERRIDES')" id="btnOverrides">Overrides (0)</button>
      <button class="btn" id="btnGroupToggle" onclick="toggleGroupMode()">Order: Chronological</button>
    </div>
    <div class="action-group">
      <button class="btn btn-primary" onclick="copyReviewMarkdown()">Copy HITL Feedback</button>
      <button class="btn" onclick="downloadJson()">Download JSON</button>
      <button class="btn" onclick="resetDefaults()">Reset</button>
    </div>
  </div>
  <main class="grid" id="slideGrid"></main>
  <section class="global-notes">
    <h2 style="margin:0 0 6px;font-size:1rem;">Overall Rubric &amp; Skill Feedback (Optional)</h2>
    <textarea id="globalNotes" rows="3" placeholder="Optional overall notes on crop framing, rubric rules, or embedding preferences..."></textarea>
  </section>
</div>
<div class="lightbox" id="lightbox" onclick="if(event.target===this) closeLightbox()">
  <img id="lbImg" src="" alt="" />
  <div class="lb-bar">
    <button class="btn" onclick="stepLightbox(-1)">Prev</button>
    <span id="lbCaption"></span>
    <button class="btn" onclick="stepLightbox(1)">Next</button>
    <button class="btn" onclick="closeLightbox()">Close (Esc)</button>
  </div>
</div>
<div class="toast" id="toast">Copied!</div>
<script>
const SLIDES = {slides_json};
const SLIDES_DIR = {json.dumps(slides_rel_dir)};
const DOC_TITLE = {json.dumps(title)};
const CROP_VAL = {json.dumps(crop)};
const STORAGE_KEY = {json.dumps(storage_key)};
let state = {{ decisions: {{}}, notes: {{}}, globalNotes: "", filter: "ALL", grouped: false }};
function pad2(n) {{ return String(n).padStart(2, "0"); }}
function esc(s) {{ return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }}
function loadState() {{
  try {{ const r = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}"); state.decisions = r.decisions || {{}}; state.notes = r.notes || {{}}; state.globalNotes = r.globalNotes || ""; }} catch(e) {{}}
  for (const s of SLIDES) if (typeof state.decisions[s.num] !== "boolean") state.decisions[s.num] = Boolean(s.default_keep);
  document.getElementById("globalNotes").value = state.globalNotes;
}}
function saveState() {{ try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify({{ decisions: state.decisions, notes: state.notes, globalNotes: state.globalNotes }})); }} catch(e) {{}} }}
function isOv(s) {{ return state.decisions[s.num] !== Boolean(s.default_keep); }}
function jumpTo(num) {{ if (state.filter !== "ALL") setFilter("ALL"); setTimeout(() => {{ const el = document.getElementById("slide-" + num); if (el) el.scrollIntoView({{ behavior: "smooth", block: "center" }}); }}, 30); }}
function setFilter(f) {{ state.filter = f; document.querySelectorAll("[data-filter]").forEach(b => b.classList.toggle("active", b.dataset.filter === f)); render(); }}
function toggleGroupMode() {{ state.grouped = !state.grouped; document.getElementById("btnGroupToggle").textContent = state.grouped ? "Order: Grouped" : "Order: Chronological"; render(); }}
function setDec(num, keep) {{ state.decisions[num] = keep; saveState(); render(); }}
function setNote(num, v) {{ state.notes[num] = v; saveState(); }}
function resetDefaults() {{ if (!confirm("Reset choices?")) return; state.decisions = {{}}; state.notes = {{}}; state.globalNotes = ""; for (const s of SLIDES) state.decisions[s.num] = Boolean(s.default_keep); document.getElementById("globalNotes").value = ""; saveState(); render(); }}
function makeCard(s) {{
  const keep = state.decisions[s.num], ov = isOv(s), card = document.createElement("article");
  card.id = "slide-" + s.num;
  card.className = `card verdict-${{s.verdict}} ${{keep ? "user-keep" : "user-drop"}} ${{ov ? "overridden" : ""}}`;
  const q = s.question ? `<div class="question-box"><strong>Open Question:</strong> ${{esc(s.question)}}</div>` : "";
  card.innerHTML = `<div class="card-head"><div class="meta-row"><span class="slide-num">#${{pad2(s.num)}}</span><span class="ts-badge">${{esc(s.ts)}}</span><span class="cat-tag">${{esc(s.category)}}</span></div><div class="meta-row">${{ov ? '<span class="override-pill">OVERRIDDEN</span>' : ''}}<span class="verdict-pill vp-${{s.verdict}}">${{esc(s.verdict)}}</span></div></div><div class="img-wrap" onclick="openLightbox(${{s.num}})"><img src="${{SLIDES_DIR}}/${{esc(s.file)}}" alt="${{esc(s.title)}}" loading="lazy" /></div><div class="card-body"><h3 class="slide-title">${{esc(s.title)}}</h3><div class="chapter-line">${{esc(s.chapter)}}</div><div class="spoken-quote">${{esc(s.spoken)}}</div><div class="rationale"><strong>Editorial Call:</strong> ${{esc(s.rationale)}}</div>${{q}}<div class="hitl-bar"><div class="seg"><button class="${{keep ? "sel-keep" : ""}}" onclick="setDec(${{s.num}}, true)">Keep IN</button><button class="${{!keep ? "sel-drop" : ""}}" onclick="setDec(${{s.num}}, false)">Drop OUT</button></div><input class="note-input" type="text" value="${{esc(state.notes[s.num] || '')}}" placeholder="Optional feedback on #${{pad2(s.num)}}..." oninput="setNote(${{s.num}}, this.value)" /></div></div>`;
  return card;
}}
function render() {{
  const kept = SLIDES.filter(s => state.decisions[s.num]).length, ov = SLIDES.filter(isOv).length;
  document.getElementById("liveSummaryPill").textContent = `Selection: ${{kept}} IN / ${{SLIDES.length - kept}} OUT (${{ov}} overrides)`;
  document.getElementById("btnOverrides").textContent = `Overrides (${{ov}})`;
  const grid = document.getElementById("slideGrid"); grid.innerHTML = "";
  const list = SLIDES.filter(s => state.filter === "ALL" ? true : state.filter === "QUESTIONS" ? Boolean(s.question) : state.filter === "OVERRIDES" ? isOv(s) : s.verdict === state.filter);
  if (state.grouped) {{
    for (const v of ["IN", "BORDERLINE", "OUT"]) {{
      const items = list.filter(s => s.verdict === v);
      if (!items.length) continue;
      const h = document.createElement("div"); h.className = "group-header"; h.textContent = `${{v}} (${{items.length}})`; grid.appendChild(h);
      items.forEach(s => grid.appendChild(makeCard(s)));
    }}
  }} else list.forEach(s => grid.appendChild(makeCard(s)));
}}
let lbNum = null;
function openLightbox(num) {{ lbNum = num; const s = SLIDES.find(x => x.num === num); document.getElementById("lbImg").src = SLIDES_DIR + "/" + s.file; document.getElementById("lbCaption").textContent = `#${{pad2(s.num)}} [${{s.ts}}] ${{s.title}}`; document.getElementById("lightbox").classList.add("open"); }}
function openStaticLightbox(src, cap) {{ lbNum = null; document.getElementById("lbImg").src = src; document.getElementById("lbCaption").textContent = cap; document.getElementById("lightbox").classList.add("open"); }}
function closeLightbox() {{ document.getElementById("lightbox").classList.remove("open"); }}
function stepLightbox(d) {{ if (lbNum === null) return; let n = lbNum + d; if (n < 1) n = SLIDES.length; if (n > SLIDES.length) n = 1; openLightbox(n); }}
document.addEventListener("keydown", e => {{ if (!document.getElementById("lightbox").classList.contains("open")) return; if (e.key === "Escape") closeLightbox(); if (e.key === "ArrowRight") stepLightbox(1); if (e.key === "ArrowLeft") stepLightbox(-1); }});
function showToast(m) {{ const t = document.getElementById("toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2400); }}
function copyReviewMarkdown() {{
  const kept = SLIDES.filter(s => state.decisions[s.num]), ov = SLIDES.filter(isOv);
  const lines = [`## HITL Slide Curation Decisions - ${{DOC_TITLE}}`, `- **Final count:** ${{kept.length}} IN / ${{SLIDES.length - kept.length}} OUT (${{ov.length}} overrides)`, ""];
  if (ov.length) {{ lines.push("### Overrides"); ov.forEach(s => lines.push(`- **#${{pad2(s.num)}} [${{s.ts}}]** ${{s.title}} -> **${{state.decisions[s.num] ? "IN" : "OUT"}}**${{state.notes[s.num] ? " - " + state.notes[s.num] : ""}}`)); lines.push(""); }}
  lines.push(`### Final KEEP List (${{kept.length}} slides)`, kept.map(s => `#${{pad2(s.num)}} (${{s.ts}} ${{s.title}})`).join("; "), "");
  const notes = SLIDES.filter(s => (state.notes[s.num] || "").trim() && !isOv(s));
  if (notes.length) {{ lines.push("### Additional Per-Slide Notes"); notes.forEach(s => lines.push(`- **#${{pad2(s.num)}} [${{s.ts}}, ${{state.decisions[s.num] ? "IN" : "OUT"}}]** ${{s.title}}: ${{state.notes[s.num].trim()}}`)); lines.push(""); }}
  const g = document.getElementById("globalNotes").value.trim();
  if (g) lines.push("### Overall Notes", g);
  navigator.clipboard.writeText(lines.join("\\n")).then(() => showToast("Copied HITL feedback to clipboard!"));
}}
function downloadJson() {{
  const payload = {{ title: DOC_TITLE, crop: CROP_VAL, globalNotes: document.getElementById("globalNotes").value.trim(), slides: SLIDES.map(s => ({{ num: s.num, file: s.file, ts: s.ts, title: s.title, recommended: s.verdict, keep: state.decisions[s.num], overridden: isOv(s), note: (state.notes[s.num] || "").trim() }})) }};
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }})); a.download = "hitl_slide_decisions.json"; a.click(); showToast("Downloaded hitl_slide_decisions.json");
}}
document.getElementById("globalNotes").addEventListener("input", e => {{ state.globalNotes = e.target.value; saveState(); }});
loadState();
const qWrap = document.getElementById("questionChips");
if (qWrap) SLIDES.filter(s => s.question).forEach(s => {{ const a = document.createElement("a"); a.className = "q-chip"; a.href = "#slide-" + s.num; a.textContent = `#${{pad2(s.num)}} (${{s.ts}}) ${{s.title.slice(0,38)}}`; a.onclick = e => {{ e.preventDefault(); jumpTo(s.num); }}; qWrap.appendChild(a); }});
render();
</script>
</body>
</html>
"""


def package_approved_assets(
    manifest: dict,
    decisions: dict | None,
    slides_dir: Path,
    output_dir: Path,
) -> Path:
    """Copy approved slides into output_dir with timestamped names and generate index.md."""
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_map: dict[int, bool] = {}
    if decisions:
        for entry in decisions.get("slides", []):
            decision_map[int(entry["num"])] = bool(entry["keep"])

    kept_rows: list[tuple[int, str, str, str, str]] = []
    harvested_resources: list[str] = list(manifest.get("resources", []))

    order = 0
    for slide in manifest.get("slides", []):
        num = int(slide["num"])
        keep = decision_map.get(num, bool(slide.get("default_keep", False)))
        for url in slide.get("urls", []):
            entry_str = f"{slide.get('title', 'Slide')} ({slide.get('ts', '')}): {url}"
            if entry_str not in harvested_resources:
                harvested_resources.append(entry_str)
        if not keep:
            continue
        order += 1
        dest_name = build_asset_filename(order, slide["ts"], slide["title"], slide.get("asset_slug", ""))
        src_file = slides_dir / slide["file"]
        if not src_file.is_file():
            raise FileNotFoundError(f"Approved slide image not found: {src_file}")
        shutil.copy2(src_file, output_dir / dest_name)
        kept_rows.append((order, slide["ts"], dest_name, slide.get("category", "Slide"), slide.get("summary", slide["title"])))

    index_lines = [
        f"# Visual Asset Index - {manifest.get('title', 'Presentation')}",
        "",
        f"- **Retained Slides:** {len(kept_rows)} of {len(manifest.get('slides', []))} total visual states",
        f"- **Crop Filter:** `{manifest.get('crop', 'none')}`",
        "",
        "## Retained Reusable Slide Assets",
        "",
        "| Fig | Time | Asset File | Category | Summary |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for fig, ts, fname, cat, summary in kept_rows:
        index_lines.append(f"| {fig:02d} | `{ts}` | [{fname}](./{fname}) | {cat} | {summary} |")

    if harvested_resources:
        index_lines.extend(["", "## Harvested On-Slide URLs and Resources", ""])
        for item in harvested_resources:
            index_lines.append(f"- {item}")

    index_path = output_dir / "index.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"Packaged {len(kept_rows)} approved assets into {output_dir} (catalog: {index_path})")
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect PiP slide crops, extract full-res PNG slides, build HITL HTML review, and package approved assets."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_crop = sub.add_parser("detect-crop", help="Detect fixed PiP slide canvas bounds from sample timestamps")
    p_crop.add_argument("-i", "--input-path", required=True, help="Full-resolution source video path")
    p_crop.add_argument("-t", "--timestamps", nargs="+", required=True, help="Sample light-background slide timestamps (HH:MM:SS)")

    p_ext = sub.add_parser("extract", help="Extract slide PNGs from full-res video according to a JSON manifest")
    p_ext.add_argument("-i", "--input-path", required=True, help="Full-resolution source video path")
    p_ext.add_argument("-m", "--manifest", required=True, help="Path to slide manifest JSON")
    p_ext.add_argument("-o", "--output-dir", required=True, help="Directory for extracted candidate PNGs")
    p_ext.add_argument("--crop", default="", help="Optional ffmpeg crop filter (e.g. crop=1470:826:434:16 or none)")

    p_html = sub.add_parser("review-html", help="Build interactive HTML HITL slide curation page")
    p_html.add_argument("-m", "--manifest", required=True, help="Path to slide manifest JSON")
    p_html.add_argument("--slides-dir", required=True, help="Relative or sibling directory containing candidate PNGs")
    p_html.add_argument("-o", "--output-html", required=True, help="Output HTML file path")
    p_html.add_argument("--before-sample", default="", help="Optional uncropped raw frame filename inside slides-dir")
    p_html.add_argument("--after-sample", default="", help="Optional cropped slide filename inside slides-dir")

    p_pkg = sub.add_parser("package", help="Copy approved slides with timestamped names and generate assets/index.md")
    p_pkg.add_argument("-m", "--manifest", required=True, help="Path to slide manifest JSON")
    p_pkg.add_argument("-d", "--decisions", default="", help="Optional HITL decisions JSON downloaded from review HTML")
    p_pkg.add_argument("--slides-dir", required=True, help="Directory containing extracted candidate PNGs")
    p_pkg.add_argument("-o", "--output-dir", required=True, help="Target package assets/ directory")

    args = parser.parse_args()

    if args.command == "detect-crop":
        ffmpeg_bin = require_ffmpeg()
        detect_broadcast_crop(ffmpeg_bin, Path(args.input_path), args.timestamps)
        return 0

    if args.command == "extract":
        ffmpeg_bin = require_ffmpeg()
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        extract_manifest_slides(ffmpeg_bin, Path(args.input_path), manifest, Path(args.output_dir), args.crop)
        return 0

    if args.command == "review-html":
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        out_html = Path(args.output_html)
        out_html.parent.mkdir(parents=True, exist_ok=True)
        html_doc = render_review_html(manifest, args.slides_dir, args.before_sample, args.after_sample)
        out_html.write_text(html_doc, encoding="utf-8")
        print(f"Wrote interactive HITL review page: {out_html}")
        return 0

    if args.command == "package":
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8")) if args.decisions else None
        package_approved_assets(manifest, decisions, Path(args.slides_dir), Path(args.output_dir))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
