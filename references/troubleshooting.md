# Cross-Platform Troubleshooting Guide

Common setup and runtime issues across macOS, Linux, and Windows and how the toolkit handles them.

---

## 1. `ffmpeg` / `ffprobe` / `yt-dlp` Not Found on `PATH`

Verify installation in your active terminal:

```bash
ffmpeg -version
ffprobe -version
yt-dlp --version || python3 -m yt_dlp --version
```

- **macOS (Homebrew):** `brew install ffmpeg yt-dlp`
- **Windows (`winget`):** `winget install Gyan.FFmpeg yt-dlp.yt-dlp` (restart your shell so `PATH` refreshes)
- **Debian / Ubuntu:** `sudo apt update && sudo apt install -y ffmpeg && pip install -U yt-dlp`

If `yt-dlp` is installed only inside Python (`pip install yt-dlp`), `prepare_compact_video.py` automatically falls back to `[sys.executable, "-m", "yt_dlp"]`.

---

## 2. PowerShell Strict Mode Stops on `ffmpeg` `stderr` Info

`ffmpeg` writes normal progress, filter statistics (`astats`), and stream metadata to `stderr`. Older PowerShell wrappers running under `$ErrorActionPreference = "Stop"` with `2>&1` abort with a false error.

- **Recommended fix:** Use the cross-platform Python scripts (`prepare_compact_video.py`, `extract_enhanced_clips.py`), which work consistently across macOS, Linux, and Windows without PowerShell stderr quirks.
- If using the legacy `.ps1` wrappers, both already scope `$ErrorActionPreference = "Continue"` around `ffmpeg astats` and `yt-dlp`.

---

## 3. Dual-Mono vs. True Stereo (`-SplitChannels` / `--split-channels`)

Conference platforms (Zoom, Meet, Teams) and YouTube AAC encoders frequently export dual-mono tracks (`channels=2`) whose Left and Right channels differ only by low-level AAC dithering (`RMS level dB: -65 dB` to `-80 dB`).

- `prepare_compact_video.py` treats `RMS diff <= -45.0 dB` (or `-inf`) as **dual-mono** and omits unnecessary channel splitting.
- Only recordings with genuine L/R stereo microphone panning (`RMS diff > -45.0 dB`) benefit from `--split-channels` in `extract_enhanced_clips.py`.

---

## 4. Long Videos Triggering Agent Context Compaction

A 60-minute `1 FPS` MP4 (~55–65 MB) can fit inside a single 100 MB file-size limit while still overflowing active agent context once `.wav` verification clips are loaded.

- **Default mitigation:** `prepare_compact_video.py` automatically segments outputs exceeding **`45 MB`** or **`25 minutes`** into **`1200s` (20-minute)** lossless chunks (`*_part00.mp4`, `*_part01.mp4`, ...), forcing a keyframe every `10s` (`-g 10`) so `-c copy` splits stay within seconds of cut boundaries.
- **Pass 1 safeguard:** Write each segment's verbatim output (`verbatim_chunk_01.md`, `verbatim_chunk_02.md`, ...) directly to disk before opening the next segment.
- Override segment length if needed: `--segment-seconds 900` (15-minute chunks).

---

## 5. `transcribe_media.py` Upload & API Errors (Non-Antigravity Users)

- **`GEMINI_API_KEY is not set`:** Create a key at Google AI Studio and export `GEMINI_API_KEY` (or pass `--api-key`).
- **Timeouts on slow connections:** Split compact videos into smaller segments (`--segment-seconds 600` for 10-minute chunks ~10 MB each).
- **Orphaned temporary files:** `transcribe_media.py` deletes uploaded media automatically in a `finally:` block unless `--keep-remote` is set.

---

## 6. Google Docs Publishing & REST Auth Errors (`fix_gdocs_toc_links.py`)

### A. `No 'gdocs' CLI or Google OAuth access token found`
- **Inside Google Antigravity:** Ensure the `gdocs` plugin is enabled and invoke bare `gdocs` on `PATH` (not a hardcoded `~/.gemini/...` batch file, which may bypass the plugin's injected auth wrapper).
- **Outside Antigravity:** Either authenticate with Application Default Credentials:
  ```bash
  gcloud auth application-default login \
    --scopes=https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/cloud-platform
  ```
  or export `GOOGLE_ACCESS_TOKEN`, **or** skip Google Docs completely and deliver the `.md` files alone.

### B. `HTTP 403` / `API has not been used in project` / `insufficientPermissions`
Enable both APIs in your Google Cloud project:
```bash
gcloud services enable drive.googleapis.com docs.googleapis.com
```
And re-run `gcloud auth application-default login` with the `--scopes` list above.

### C. Broken Table of Contents Anchor Links After Manual Upload
If a Google Doc was created previously via manual upload or `gdocs mutate import-md` without running the binder, pass its `<DOC_ID>` directly to repair existing `#slug` links in place:
```bash
python3 scripts/fix_gdocs_toc_links.py <DOC_ID>
```

---

## 7. Audio Podcasts (Spotify, Apple Podcasts & YouTube Music)

- **Spotify (`open.spotify.com/episode/...`):** Direct Spotify audio streams use DRM, so `prepare_compact_video.py` automatically resolves the episode title/show via Spotify public metadata to the publisher's **DRM-free public RSS audio enclosure** (`.mp3`/`.m4a`) and writes a `.info.json` metadata file. Pass an **episode** URL (`/episode/...`), not a show URL (`/show/...`).
- **Platform-Exclusive Paid/Subscriber Feeds:** Episodes distributed *only* inside Spotify/Apple paid channels without a public RSS enclosure cannot be fetched remotely; export or download the audio file locally and pass `--input-path`.
- **YouTube Music (`music.youtube.com/watch?v=...`):** Add `--audio-only` so `prepare_compact_video.py` skips downloading video frames and fetches only the non-DRC audio stream (`ba[format_id!*=-drc]`).
