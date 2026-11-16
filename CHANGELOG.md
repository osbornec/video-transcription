# Changelog

All notable changes to the `video-transcription` agent skill and toolkit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-15

### Added
- **Cross-platform Python 3 CLI suite** (macOS, Linux, and Windows, standard library only):
  - `scripts/prepare_compact_video.py`: URL intake via `yt-dlp` (`format_id!*=-drc` non-DRC audio, `height<=480`, `--write-info-json`), stereo vs. dual-mono topology detection (`-45.0 dB` RMS threshold), no-upscale even-dimension scaling (`scale=trunc(min(width\,iw)/2)*2:-2`), 10-second keyframe cadence (`-g`), and compaction-safe auto-segmentation (`--segment-seconds 1200` when `>45 MB` or `>25 minutes`).
  - `scripts/extract_enhanced_clips.py`: Extracts speech-filtered (`100 Hz – 8 kHz` band-pass + `dynaudnorm`) 16-bit PCM `.wav` verification clips from low-SNR windows, with `--split-channels` support for true-stereo crosstalk.
  - `scripts/transcribe_media.py`: Zero-dependency Gemini Files + `generateContent` helper (`GEMINI_API_KEY`) enabling Stages 3 and 4 outside Antigravity (Claude Code, OpenAI Codex, Cursor, standalone CLI) with automatic remote cleanup.
  - `scripts/fix_gdocs_toc_links.py`: Dual backend (`gdocs` CLI + direct Google Drive v3 / Docs v1 REST API fallback via `gcloud auth` / `GOOGLE_ACCESS_TOKEN`), native `#heading=h.xxx` Table of Contents anchor binder, and `.url` / `.webloc` shortcut generator (`--shortcut-format`).
  - `scripts/build_changelog.py`: Generates turn-by-turn Markdown verification changelogs comparing `[unclear]` drafts against verified Markdown transcripts.
- **6-Stage Multimodal Transcription Runbook (`SKILL.md` + `references/`):** Includes quick decision trees, critical guardrails, progressive-disclosure `references/editorial-style-guide.md` & `references/troubleshooting.md`, fixes for dual-mono codec dither false positives, context compaction loss via chunk-by-chunk scratch persistence, and transparent VoIP packet-loss annotation.
- **Repository documentation, examples, and unit test suite (`tests/test_scripts.py`).**
- Retained `prepare_compact_video.ps1` and `extract_enhanced_clips.ps1` for backward compatibility on Windows PowerShell environments.
