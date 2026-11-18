# Changelog

All notable changes to the `video-transcription` agent skill and toolkit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-19

### Added
- **Width-matched format selection and `--screen-share` preset (`prepare_compact_video.py`, `prepare_compact_video.ps1`):** Added `build_video_format_selector(max_width)` so talking-head runs (`<=480px`) fall back to `<=720p` before higher tiers while `--screen-share` (`>=960px`, `CRF <=28`) or `--width > 480` selects `720p` (or `1080p`) so UI labels and slide text stay readable.
- **Download separation and parallel HLS fetching (`prepare_compact_video.py`, `prepare_compact_video.ps1`):** Added `--download-dir` / `-DownloadDir` to save raw `--url` downloads and `.info.json` outside working compact folders, plus `--concurrent-fragments` / `-ConcurrentFragments` (default `8`) for fragmented HLS/DASH streams.
- **Loom URL workflow (`SKILL.md`, `README.md`, `troubleshooting.md`):** Documented `loom.com/share/...` support alongside YouTube, Spotify, and Apple Podcasts, including troubleshooting sections for Loom metadata skew and Stage 4 `.wav` batching.
- **Safe `.info.json` filtering (`transcribe_media.py`):** Filtered `@*.info.json` context files down to `SAFE_INFO_JSON_KEYS` (`title`, `fulltitle`, `channel`, `uploader`, `upload_date`, `duration`, `duration_string`, `description`, `chapters`, `webpage_url`), stripping raw `formats`, stream URLs, and cookies.
- **Doc dash hygiene & Gemini 4 payload tests (`tests/test_scripts.py`):** Added `test_no_em_or_en_dashes_in_docs` plus tests for `DEFAULT_MODEL`, Gemini 4 request payloads, thought-part filtering, format selectors, and sequential clip numbering.

### Changed
- **Gemini 4 API default and model guidance (`transcribe_media.py`, `README.md`, `SKILL.md`):** Updated the default `--model` from `gemini-2.5-pro` to `gemini-4-neon`, added Gemini 4 model-selection guidance for Google Antigravity and CLI users, removed the deprecated `temperature` sampling parameter from `generationConfig`, set `maxOutputTokens` to `32768`, raised the HTTP request timeout to 20 minutes (`1200s`), and filtered out `thought` summary parts when assembling text output.
- **Outcome-led public documentation and visual refresh (`README.md`, `SKILL.md`, `examples/sample_outputs.md`, `assets/social-preview.svg`):** Rewrote above-the-fold positioning around reusable team and agent knowledge assets (comparing against both auto-captions and browser-trapped AI web chats), moved codec and signal-processing mechanics into a dedicated "How It Works Under the Hood" section, and redesigned the `1280x640` social preview card with a studio split layout showing before/after audio verification and themed Markdown output.
- **Stage 0 metadata handling (`SKILL.md`):** Updated instructions to fall back from `channel` to `uploader`, treat `.info.json` chapter titles and durations as provisional hints rather than ground truth (`ffprobe` stream duration governs timelines when platform trimmers edit recordings), and cross-check auto-generated proper-noun spellings against spoken audio.
- **Stage 4 `.wav` audit batching (`SKILL.md`, `troubleshooting.md`):** Standardized opening `.wav` clips in batches of 3 to 5 per turn via `read_file` to prevent oversized multimodal turn payloads.
- **Stage 5 filename reconciliation and editorial cues (`SKILL.md`, `editorial-style-guide.md`, `sample_outputs.md`):** Added a final check to rename provisional Stage 0 file slugs (`*_compact_1fps.*` and `*_Transcript.md`) after Stage 3/4 proper-noun verification, documented timestamped turn breaks for long single-speaker monologues, and added `*[audio splice]*` to distinguish server-trimmed jump cuts from network dropouts.
- **Legacy PowerShell parity (`prepare_compact_video.ps1`, `extract_enhanced_clips.ps1`):** Synced parameter support and sequential `wNN_` clip numbering with the primary Python scripts.

### Fixed
- **Skipped `720p` downloads on Loom and similar hosts (`prepare_compact_video.py`):** Sources without a `480p` stream no longer jump straight to `1080p`/`4K`, avoiding redundant multi-hundred-megabyte downloads when `720p` exists.
- **Multi-pass `w01_` filename collisions (`extract_enhanced_clips.py`):** Added `next_clip_start_index()` so iterative `.wav` extractions into the same `--output-dir` continue numbering after existing `wNN_*.wav` files.
- **Literal space in `yt-dlp` output template (`prepare_compact_video.py`):** Replaced `"%(title).80B [%(id)s].%(ext)s"` with `"%(title).80B_[%(id)s].%(ext)s"`.
- **Windows wildcard cleanup note (`SKILL.md`, `troubleshooting.md`):** Added explicit guidance to use `Remove-Item -Path *.wav` (not `-LiteralPath`) on Windows PowerShell.

## [1.0.0] - 2026-11-15

### Added
- **Cross-platform Python 3 CLI suite** (macOS, Linux, and Windows, standard library only):
  - `scripts/prepare_compact_video.py`: URL intake via `yt-dlp` (`format_id!*=-drc` non-DRC audio, `height<=480`, `--write-info-json`), stereo vs. dual-mono topology detection (`-45.0 dB` RMS threshold), no-upscale even-dimension scaling (`scale=trunc(min(width\,iw)/2)*2:-2`), 10-second keyframe cadence (`-g`), and compaction-safe auto-segmentation (`--segment-seconds 1200` when `>45 MB` or `>25 minutes`).
  - `scripts/extract_enhanced_clips.py`: Extracts speech-filtered (`100 Hz to 8 kHz` band-pass + `dynaudnorm`) 16-bit PCM `.wav` verification clips from low-SNR windows, with `--split-channels` support for true-stereo crosstalk.
  - `scripts/transcribe_media.py`: Zero-dependency Gemini Files + `generateContent` helper (`GEMINI_API_KEY`) enabling Stages 3 and 4 outside Antigravity (Claude Code, OpenAI Codex, Cursor, standalone CLI) with automatic remote cleanup.
  - `scripts/fix_gdocs_toc_links.py`: Dual backend (`gdocs` CLI + direct Google Drive v3 / Docs v1 REST API fallback via `gcloud auth` / `GOOGLE_ACCESS_TOKEN`), native `#heading=h.xxx` Table of Contents anchor binder, and `.url` / `.webloc` shortcut generator (`--shortcut-format`).
  - `scripts/build_changelog.py`: Generates turn-by-turn Markdown verification changelogs comparing `[unclear]` drafts against verified Markdown transcripts.
- **6-stage multimodal transcription runbook (`SKILL.md` + `references/`):** Includes quick decision trees, critical rules, `references/editorial-style-guide.md`, `references/troubleshooting.md`, fixes for dual-mono codec dither false positives, context compaction loss via chunk-by-chunk scratch persistence, and transparent VoIP packet-loss annotation.
- **Repository documentation, examples, and unit test suite (`tests/test_scripts.py`).**
- Retained `prepare_compact_video.ps1` and `extract_enhanced_clips.ps1` for backward compatibility on Windows PowerShell environments.
