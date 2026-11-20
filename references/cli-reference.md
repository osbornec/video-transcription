# CLI Reference, Setup, and Prerequisites

Complete command flags, manual installation commands, runtime compatibility, and system dependencies for `video-transcription`.

*(Use `python3` on macOS/Linux or `python` on Windows.)*

---

## Agent Runtime & Model Compatibility

All 6 core pipeline scripts (`prepare_compact_video.py`, `transcribe_media.py`, `extract_enhanced_clips.py`, `capture_slides.py`, `fix_gdocs_toc_links.py`, and `build_changelog.py`) use the **Python 3.10+ standard library only** at import time. Optional `Pillow` + `numpy` enable pixel-exact PiP crop detection in `capture_slides.py`, optional `playwright` powers Stage 0B live webinar capture (`attend_webinar.py`, imported lazily), and optional `pypdf` / `python-pptx` / `python-docx` handle attached reference decks or legacy `.docx` draft comparisons.

| Agent / Runtime | Stages 3 to 4 (Audio + Visual Pass) | Stage 5 Google Docs Publishing *(Optional)* | Stage 5 Markdown Output |
| :--- | :--- | :--- | :--- |
| **Google Antigravity** | Native `read_file` with a Gemini 4 model *(no API key needed)* | Built-in `gdocs` CLI | Always included (`.md` only, no `.docx`) |
| **Claude Code / Codex / Cursor / CLI** | [`scripts/transcribe_media.py`](../scripts/transcribe_media.py) + `GEMINI_API_KEY` *(defaults to `gemini-4-neon`)* | [`scripts/fix_gdocs_toc_links.py`](../scripts/fix_gdocs_toc_links.py) via `gcloud auth` or `GOOGLE_ACCESS_TOKEN` | Always included (no cloud auth needed) |

- **In Google Antigravity:** Select a Gemini 4 multimodal model in the model picker so `read_file` inspects `.mp4` / `.mkv` frames and `.wav` clips natively.
- **Outside Antigravity (`transcribe_media.py`):** Defaults to `gemini-4-neon`; pass `--model <id>` to select another Gemini 4 model ID.

---

## System Binaries & Optional Python Packages

| Dependency | Needed For | macOS | Windows | Linux (Debian / Ubuntu) |
| :--- | :--- | :--- | :--- | :--- |
| **Python 3.10+** | Running all helper scripts | `brew install python` | `winget install Python.Python.3.12` | `sudo apt install python3` |
| **`ffmpeg` + `ffprobe`** | Compaction, silence trim, and PCM `.wav` extraction | `brew install ffmpeg` | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` |
| **`yt-dlp`** *(optional)* | Stage 0 `--url` downloads | `brew install yt-dlp` | `winget install yt-dlp.yt-dlp` | `pip install -U yt-dlp` |
| **`playwright` + Chromium** *(optional)* | Stage 0B live webinar capture (`attend_webinar.py`) | `pip install playwright && playwright install chromium` | `pip install playwright; playwright install chromium` | `pip install playwright && playwright install chromium` |
| **`Pillow` + `numpy`** *(optional)* | Stage 4B pixel-exact PiP canvas crop detection (`capture_slides.py detect-crop`) | `pip install pillow numpy` | `pip install pillow numpy` | `pip install pillow numpy` |
| **`GEMINI_API_KEY`** *(outside Antigravity)* | Joint video/audio Gemini 4 API pass | Export from [Google AI Studio](https://aistudio.google.com/) | `$env:GEMINI_API_KEY = "..."` | Export in shell profile |
| **`gcloud` CLI** *(optional outside Antigravity)* | Exporting to Google Docs via REST | `brew install --cask google-cloud-sdk` | `winget install Google.CloudSDK` | `apt install google-cloud-cli` |
| **`pypdf` / `python-pptx`** *(optional)* | Stage 3 text extraction from attached PDFs or `.pptx` decks | `pip install pypdf python-pptx` | `pip install pypdf python-pptx` | `pip install pypdf python-pptx` |
| **`python-docx`** *(optional)* | Comparing an old `.docx` draft in `build_changelog.py` | `pip install python-docx` | `pip install python-docx` | `pip install python-docx` |

---

## Manual Install

Use `npx skills add osbornec/video-transcription` for automatic setup, or copy the skill manually:

### macOS & Linux (bash / zsh)

```bash
git clone https://github.com/osbornec/video-transcription.git video-transcription
cd video-transcription

# Google Antigravity (global)
mkdir -p ~/.gemini/config/skills && cp -R . ~/.gemini/config/skills/video-transcription

# OpenAI Codex (global)
mkdir -p ~/.codex/skills && cp -R . ~/.codex/skills/video-transcription

# Claude Code (global)
mkdir -p ~/.claude/skills && cp -R . ~/.claude/skills/video-transcription

# Project-local discovery (.agents/skills/)
mkdir -p /path/to/project/.agents/skills && cp -R . /path/to/project/.agents/skills/video-transcription
```

### Windows (PowerShell)

```powershell
git clone https://github.com/osbornec/video-transcription.git video-transcription
Set-Location video-transcription

# Google Antigravity (global)
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\skills\video-transcription" | Out-Null
Copy-Item -Recurse -Force ".\SKILL.md", ".\scripts", ".\references" "$HOME\.gemini\config\skills\video-transcription\"

# OpenAI Codex (global)
New-Item -ItemType Directory -Force -Path "$HOME\.codex\skills\video-transcription" | Out-Null
Copy-Item -Recurse -Force ".\SKILL.md", ".\scripts", ".\references" "$HOME\.codex\skills\video-transcription\"

# Project-local discovery (.agents/skills/)
New-Item -ItemType Directory -Force -Path "C:\path\to\project\.agents\skills\video-transcription" | Out-Null
Copy-Item -Recurse -Force ".\SKILL.md", ".\scripts", ".\references" "C:\path\to\project\.agents\skills\video-transcription\"
```

---

## CLI Toolkit Reference

### 1. [`scripts/attend_webinar.py`](../scripts/attend_webinar.py) *(Optional Stage 0B Live Webinar Capture)*
Attends Zoom Events, Zoom Web Client, and browser webinars in headless Chromium (`--headless=new`) with camera and microphone hard-disabled (`permissions=[]` + `getUserMedia` `NotAllowedError` lock), records tab video (`1280x720` VP8) and audio (`48 kHz` Opus, local speakers silent) straight to disk, detects session end or post-speech silence, trims waiting-room silence losslessly (`-c copy`), and exposes live JSON status/command files. See [`webinar-capture.md`](./webinar-capture.md).

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--url` | `""` | Webinar join URL (required unless `--self-test` is set) |
| `--slug` | `webinar` | Output filename slug (`<slug>.mkv`, `<slug>_status.json`, `<slug>_live.png`) |
| `--recordings-dir` | `recordings` | Directory for the finalized `.mkv` recording |
| `--scratch-dir` | `scratch` | Directory for temporary chunks, live screenshots, status JSON, and command JSON |
| `--max-minutes` | `90.0` | Maximum total runtime in minutes before graceful stop and finalization |
| `--fps` | `10` | Capture video frame rate |
| `--video-bps` | `1200000` | Video bitrate in bps |
| `--audio-bps` | `128000` | Opus audio bitrate in bps |
| `--end-silence-seconds` | `180.0` | Auto-stop after N seconds of sustained silence (`-45 dB`) following live speech (`0` disables) |
| `--no-auto-trim-silence` | `false` | Keep full leading waiting-room and trailing silence instead of trimming losslessly |
| `--no-suppress-local-audio` | `false` | Keep local desktop speaker playback unmuted during capture |
| `--record-immediately` | `false` | Start recording immediately on load instead of waiting for webinar join |
| `--self-test` | `false` | Run a 6-second synthetic capture and `getUserMedia` camera/mic block check |

```bash
python3 scripts/attend_webinar.py --self-test --scratch-dir "./scratch"
python3 scripts/attend_webinar.py --url "https://events.zoom.us/ej/..." --slug "q3_webinar" --recordings-dir "./recordings" --scratch-dir "./scratch" --max-minutes 90
```

### 2. [`scripts/prepare_compact_video.py`](../scripts/prepare_compact_video.py)
Downloads optional URL sources (YouTube, YouTube Music, Loom, Apple Podcasts, Spotify episode URLs via public RSS, + `.info.json`), audits stereo phase difference, compacts video without upscaling (`<=720p` download fallback, concurrent HLS fetching, `--screen-share` preset), preserves lossless or `128k` audio, and splits long outputs into lossless chunks.

| Flag | Default | Description |
| :--- | :--- | :--- |
| `-i`, `--input-path` | `""` | Local source media path (`.mp4`, `.mov`, `.mkv`, `.webm`, `.m4a`, `.mp3`, `.wav`, `.flac`) |
| `-u`, `--url` | `""` | Online video or podcast URL (YouTube, YouTube Music, Loom, Apple Podcasts, Spotify episode) |
| `-o`, `--output-path` | `<stem>_compact_1fps.*` | Target compact media path |
| `--download-dir` | parent of `--output-path` | Directory for raw `--url` downloads and `.info.json` metadata |
| `--concurrent-fragments` | `8` | Concurrent HLS/DASH fragment connections for `yt-dlp` |
| `--audio-only` | `false` | Download/extract audio only without video frames (podcasts & YouTube Music) |
| `--screen-share` | `false` | Screen-share / slide preset (`>=960px` max width, `<=28` CRF, and tighter `600s` / `15 min` / `25 MB` segmentation) |
| `--capture-slides` | `false` | Two-tier slide capture preset: downloads native `1080p` source for Stage 4B PNG grabs while building the `960px` `--screen-share` `1 FPS` proxy |
| `--width` | `480` | Max width in pixels (never upscales smaller inputs; keeps even width/height) |
| `--fps` | `1` | Compact frame rate for visual speaker diarization |
| `--crf` | `35` | x264 CRF quality factor |
| `--segment-seconds` | `1200` (`600` with `--screen-share`) | Segment duration in seconds when split threshold triggers (`0` disables) |
| `--segment-trigger-minutes` | `25.0` (`15.0` with `--screen-share`) | Auto-split outputs exceeding N minutes |
| `--segment-trigger-mb` | `45.0` (`25.0` with `--screen-share`) | Auto-split outputs exceeding N MB |

```bash
python3 scripts/prepare_compact_video.py --input-path "./recordings/panel_session.mp4"
python3 scripts/prepare_compact_video.py --input-path "./recordings/q3_webinar.mkv" --screen-share -o "./work/q3_webinar_compact_1fps.mkv"
python3 scripts/prepare_compact_video.py --url "https://www.youtube.com/watch?v=VIDEO_ID" -o "./work/session_compact_1fps.mp4"
python3 scripts/prepare_compact_video.py --url "https://www.loom.com/share/VIDEO_ID" --download-dir "./recordings" -o "./work/loom_compact_1fps.mp4"
python3 scripts/prepare_compact_video.py --url "https://podcasts.apple.com/us/podcast/.../id123?i=456"
python3 scripts/prepare_compact_video.py --url "https://open.spotify.com/episode/EPISODE_ID"
python3 scripts/prepare_compact_video.py --url "https://music.youtube.com/watch?v=VIDEO_ID" --audio-only
```

### 3. [`scripts/transcribe_media.py`](../scripts/transcribe_media.py) *(Non-Antigravity Multimodal Helper)*
Uploads compact video segments, audio podcast tracks, or enhanced `.wav` clips to the Gemini Files API (`GEMINI_API_KEY`), adapts prompts for video vs. audio-only podcast diarization, and deletes temporary remote uploads on exit.

| Flag | Default | Description |
| :--- | :--- | :--- |
| `-i`, `--input` | *(required)* | One or more `.mp4`, `.mkv`, `.wav`, or `.m4a` paths |
| `-m`, `--mode` | `transcribe` | `transcribe` (Pass 1 visual+audio transcript + low-SNR windows) or `audit-wav` (Pass 2 clip review) |
| `--offset` | `00:00` | Base timestamp offset (`MM:SS` or `HH:MM:SS`) added to segment timestamps |
| `--context` | `""` | Inline notes or `@path/to/context.json` for speaker spellings and chapter markers |
| `-o`, `--output` | stdout | Destination Markdown path (flushed directly to disk) |
| `--model` | `gemini-4-neon` | Gemini model ID (override with any Gemini 4 model ID) |
| `--api-key` | `$GEMINI_API_KEY` | Gemini API key override (reads `GEMINI_API_KEY` env var by default) |
| `--keep-remote` | `false` | Retain remote file on Gemini Files API instead of deleting after completion |

```bash
python3 scripts/transcribe_media.py -m transcribe -i "./work/session_compact_1fps_part01.mp4" --offset "20:00" --context "@./work/session.info.json" -o "./scratch/verbatim_chunk_02.md"
python3 scripts/transcribe_media.py -m audit-wav -i "./scratch/w01_000410_000435.wav" --context "Check speaker transition near 04:20"
```

### 4. [`scripts/extract_enhanced_clips.py`](../scripts/extract_enhanced_clips.py)
Extracts targeted windows (flagged `[unclear]` intervals and `+/-4s` mid-sentence segment seams) from the unsplit original source media as uncompressed 16-bit PCM `.wav` clips filtered to `100 Hz to 8 kHz` with `dynaudnorm`.

| Flag | Default | Description |
| :--- | :--- | :--- |
| `-i`, `--input-path` | *(required)* | Original uncompressed/high-quality media source |
| `-o`, `--output-dir` | `.` | Directory for extracted `.wav` clips |
| `-w`, `--windows` | *(required)* | Space- or comma-separated intervals (`04:10-04:35`, `01:02:10-01:02:40`) |
| `--split-channels` | `false` | Export separate `_L.wav` and `_R.wav` mono tracks when `channels >= 2` |

```bash
python3 scripts/extract_enhanced_clips.py -i "./recordings/panel_session.mp4" -o "./scratch" -w "04:10-04:35" "28:30-29:05"
```

### 5. [`scripts/capture_slides.py`](../scripts/capture_slides.py) *(Optional Stage 4B Slide Capture and HITL Curation)*
Detects fixed conference broadcast PiP slide canvas crops (`detect-crop`), extracts lossless full-resolution slide PNGs from the original source video (`extract`), builds an interactive chronological HTML HITL curation page (`review-html`), and packages approved reusable assets with timestamped filenames and `assets/index.md` (`package`). See [`slide-curation-guide.md`](./slide-curation-guide.md).

| Subcommand & Flag | Default | Description |
| :--- | :--- | :--- |
| `detect-crop -i/--input-path` | *(required)* | Full-resolution source video path |
| `detect-crop -t/--timestamps` | *(required)* | One or more sample light-background slide timestamps (`HH:MM:SS`) |
| `extract -i/--input-path` | *(required)* | Full-resolution source video path |
| `extract -m/--manifest` | *(required)* | Slide manifest JSON covering all visual states |
| `extract -o/--output-dir` | *(required)* | Output directory for candidate PNGs |
| `extract --crop` | manifest crop | Optional `ffmpeg` crop filter (e.g. `crop=1470:826:434:16` or `none`) |
| `review-html -m/--manifest` | *(required)* | Slide manifest JSON |
| `review-html --slides-dir` | *(required)* | Relative or sibling folder containing extracted candidate PNGs |
| `review-html -o/--output-html` | *(required)* | Output path for the interactive HTML curation page |
| `review-html --before-sample` | `""` | Optional raw uncropped broadcast frame filename inside `--slides-dir` |
| `review-html --after-sample` | `""` | Optional cropped slide PNG filename inside `--slides-dir` |
| `package -m/--manifest` | *(required)* | Slide manifest JSON (including dropped-slide `urls` for harvesting) |
| `package -d/--decisions` | `""` | Optional HITL decisions JSON exported from the review HTML |
| `package --slides-dir` | *(required)* | Folder containing extracted candidate PNGs |
| `package -o/--output-dir` | *(required)* | Target `<package_dir>/assets` directory |

```bash
python3 scripts/capture_slides.py detect-crop -i "./recordings/talk.mp4" -t 00:00:48 00:02:06 00:13:38
python3 scripts/capture_slides.py extract -i "./recordings/talk.mp4" -m "./scratch/manifest.json" -o "./scratch/slide_candidates" --crop "crop=1470:826:434:16"
python3 scripts/capture_slides.py review-html -m "./scratch/manifest.json" --slides-dir "slide_candidates" -o "./scratch/slide_curation_review.html" --before-sample "_raw_0048.png" --after-sample "01_chart.png"
python3 scripts/capture_slides.py package -m "./scratch/manifest.json" -d "./scratch/hitl_slide_decisions.json" --slides-dir "./scratch/slide_candidates" -o "./transcripts/My_Talk/assets"
```

### 6. [`scripts/fix_gdocs_toc_links.py`](../scripts/fix_gdocs_toc_links.py) *(Optional Google Docs Exporter)*
Uploads Markdown to Google Docs, optionally embeds local `./assets/*.png` images inline (`--embed-local-images`), resolves imported `headingId` targets, rebinds all `#slug` Table of Contents anchors to `#heading=h.xxx`, and writes local `.url` / `.webloc` shortcuts.

| Flag | Default | Description |
| :--- | :--- | :--- |
| `doc_id` | `""` | Existing Google Doc ID (omit when creating a new Doc via `--import-md`) |
| `--import-md` | `""` | Local Markdown file to create or update |
| `--embed-local-images` | `false` | Stage unique placeholders, embed local `./assets/*.png` images inline via `gdocs`, clean placeholders in one batched `sed`, and verify image count |
| `--title` | derived | Google Doc title when creating a new Doc |
| `--tab` | `""` | Optional Google Docs tab ID (`t.0`) |
| `--shortcut-dir` | `""` | Folder to write local `.url` / `.webloc` shortcut file(s) |
| `--shortcut-format` | `url` | `url`, `webloc` (macOS Finder plist), `both`, or `auto` |
| `--backend` | `auto` | `auto`, `gdocs` (Antigravity CLI), or `rest` (Google Drive v3 + Docs v1 REST APIs) |

```bash
python3 scripts/fix_gdocs_toc_links.py --import-md "./out/Session_Thematic_Clean_Read_Transcript.md" --embed-local-images --title "Session: Thematic Clean-Read" --shortcut-dir "./out" --shortcut-format auto
```

### 7. [`scripts/build_changelog.py`](../scripts/build_changelog.py)
Generates a turn-by-turn Markdown diff changelog comparing a rough `.md`, `.txt`, or legacy `.docx` draft against the verified `*_Perfect_Transcript.md`.

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--old` | *(required)* | Initial draft file (`.md`, `.txt`, or `.docx`) |
| `--new` | *(required)* | Verified `*_Perfect_Transcript.md` path |
| `--output` | *(required)* | Destination `Transcript_Corrections_Changelog.md` path |
| `--tolerance` | `45` | Timestamp matching tolerance in seconds when aligning draft and verified turns |

```bash
python3 scripts/build_changelog.py --old "./drafts/initial_draft.md" --new "./out/Session_Perfect_Transcript.md" --output "./out/Transcript_Corrections_Changelog.md"
```
