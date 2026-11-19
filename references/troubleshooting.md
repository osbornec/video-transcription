# Cross-Platform Troubleshooting Guide

Setup, media edge-case, and runtime fixes across macOS, Linux, and Windows.

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

A 60-minute `1 FPS` MP4 (~55 to 65 MB) fits under a 100 MB upload cap while still overflowing active agent context once `.wav` verification clips are loaded.

- **Default mitigation:** `prepare_compact_video.py` automatically segments outputs exceeding **`45 MB`** or **`25 minutes`** into **`1200s` (20-minute)** lossless chunks (`*_part00.mp4`, `*_part01.mp4`, ...), forcing a keyframe every `10s` (`-g 10`) so `-c copy` splits stay within seconds of cut boundaries. With `--screen-share` (`>=960px`), thresholds tighten automatically to **`25 MB`** / **`15 minutes`** and **`600s` (10-minute)** chunks.
- **Pass 1 safeguard:** Write each segment's verbatim output (`verbatim_chunk_01.md`, `verbatim_chunk_02.md`, ...) directly to disk before opening the next segment.
- **Pass 2 seam check:** Include a `+/-4s` Stage 4 `.wav` audit clip around any mid-sentence segment boundary against the unsplit original media.
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

---

## 8. Loom & HLS Video Sources (Metadata Skew, `720p` Fallback, and Audio Splices)

- **No `480p` rendition on Loom:** Many Loom recordings offer only `720p` and `1080p` HLS playlists. `prepare_compact_video.py` falls back to `<=720p` before `1080p` and downloads HLS fragments concurrently (`--concurrent-fragments 8`) to cut bandwidth and wait time. For dense screen-shares or UI demos, pass `--screen-share` (`>=960px`, `CRF 28`).
- **`channel: null` and `.info.json` duration drift:** Loom populates speaker identity in `uploader` while leaving `channel` null, and Loom server-side silence/pause trimming can shorten the actual rendered MP4 relative to `.info.json` metadata (`duration` and `chapters`). Always use `ffprobe` stream duration as timeline ground truth.
- **Auto-chapter misspellings & audio splices:** Treat AI-generated `.info.json` chapter titles as provisional hints only; cross-check company and speaker spellings against spoken audio and `.wav` clips. Mark platform jump cuts as `*[audio splice]*` rather than network packet loss.

---

## 9. Stage 4 `.wav` Batch Size & PowerShell Wildcard Cleanup

- **Limit parallel `.wav` reads:** Inside Google Antigravity, open extracted `.wav` clips in batches of **3 to 5 files per turn** via `read_file`. Loading 10+ uncompressed `.wav` binaries in one turn can trigger model output errors or force context compaction.
- **PowerShell `-LiteralPath` vs. `-Path`:** On Windows PowerShell, `Remove-Item -LiteralPath ".\scratch\*.wav"` treats `*` literally and deletes nothing. Use `-Path`:
  ```powershell
  Remove-Item -Path ".\scratch\*.wav" -Force
  ```

---

## 10. Remote Webinar Capture (`attend_webinar.py`) & Segment Boundary Seams

See [`webinar-capture.md`](./webinar-capture.md) for the complete Chromium audio flag, localhost controller, and Zoom Events architecture.

- **Playwright Chromium missing:** `attend_webinar.py` imports Playwright lazily so `--help` and stdlib unit tests work without extra packages. For live capture, install once:
  ```bash
  pip install playwright && playwright install chromium
  ```
- **Confirming camera & mic stay off:** Run `python3 scripts/attend_webinar.py --self-test` before joining a live call and confirm `getUserMedia check: BLOCKED:NotAllowedError` alongside non-silent Opus RMS telemetry (`> -40 dB`).
- **Zoom Events post-webinar survey redirect:** When a host ends a Zoom Event, Zoom displays `"This webinar has been ended by host"` with an `OK` button and redirects to `/meeting/survey`. `attend_webinar.py` checks end-of-webinar text and URL patterns before dismissing modals, falls back to sustained post-speech silence (`--end-silence-seconds 180`), and losslessly trims leading waiting-room and trailing silence (`-c copy`) during finalization.
- **High-resolution `--screen-share` context limits:** Loading a 20-minute `960px` `1 FPS` segment (`~35 MB`) in a busy agent context can trigger payload/context errors. `prepare_compact_video.py --screen-share` automatically tightens segmentation to `600s` (10-minute, `~15-17 MB`) chunks.
- **Mid-sentence segment seams:** Lossless `-f segment -c copy` cuts on keyframes and can occasionally split a spoken phrase across `part00` and `part01`. Always include a `+/-4s` Stage 4 `.wav` audit clip around any mid-sentence segment boundary against the unsplit original recording.
