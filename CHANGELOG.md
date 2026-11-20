# Changelog

All notable changes to the `video-transcription` agent skill and toolkit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.1] - 2026-11-20

### Added
- **PowerShell parity for slide capture (`scripts/prepare_compact_video.ps1`):** Added `-CaptureSlides` switch matching `prepare_compact_video.py --capture-slides` (`1080p` source download + `960px` `1 FPS` screen-share proxy).
- **Complete CLI flag tables and optional dependencies (`references/cli-reference.md`):** Added full flag tables for all four `capture_slides.py` subcommands (`detect-crop`, `extract`, `review-html`, `package`), added `--tolerance` to `build_changelog.py`, and documented optional `Pillow` and `numpy` packages.
- **Slide asset examples (`examples/sample_outputs.md`):** Updated synthetic excerpts to illustrate per-video `<Slug>/` folders, clickable slide links in Verbatim Perfect, inline slide PNG embeds in Clean-Read and Thematic Clean-Read, and an `assets/index.md` catalog with harvested URLs from skipped slides.

### Changed
- **Contributor and cleanup docs (`CONTRIBUTING.md`, `SKILL.md`):** Added `capture_slides.py` (with lazy optional `Pillow`/`numpy` imports) to the 6 core stdlib scripts list in `CONTRIBUTING.md`, and updated the `SKILL.md` Final Checklist to explicitly remove temporary `slide_candidates/` and `slide_curation_review.html` scratch files after packaging.

## [1.3.0] - 2026-11-20

### Added
- **Slide capture, PiP auto-crop, and interactive HTML human-in-the-loop (HITL) curation (`scripts/capture_slides.py`, `references/slide-curation-guide.md`, `SKILL.md`, `README.md`, `references/cli-reference.md`):** Added Stage 4B for capturing lossless full-resolution slide PNGs directly from source media (`recordings/`, never the `1 FPS` proxy). Includes consensus fixed broadcast PiP canvas auto-crop detection (`detect-crop`), manifest-driven lossless PNG extraction (`extract`), an interactive chronological HTML review page showing all IN/BORDERLINE/OUT visuals with editorial commentary, lightbox zoom, and clipboard/JSON decision export (`review-html`), and timestamped asset packaging (`NN_MMmSSs_slug.png` + `assets/index.md`) with automatic URL and resource harvesting from dropped slides (`package`).
- **Two-tier slide-capture intake flag (`scripts/prepare_compact_video.py`):** Added `--capture-slides` to download native `1080p` source video plus original non-DRC audio into `recordings/` while automatically enabling `--screen-share` (`960px`, `CRF 28`, `600s` / `15 min` / `25 MB`) for the Stage 3 transcription proxy.
- **Inline local image embedding for Google Docs (`scripts/fix_gdocs_toc_links.py`):** Added `--embed-local-images` (for the `gdocs` backend) to stage unique `[[IMG_EMBED_NN]]` placeholder paragraphs, strip local `./` links cleanly, upload and embed every local `./assets/*.png` image inline above its caption, clean up placeholders in one batched `sed` call, verify embedded image count via `list-images`, and bind native ToC `headingId` links.
- **Self-contained per-video package layout (`SKILL.md`, `references/slide-curation-guide.md`, `references/editorial-style-guide.md`):** Standardized delivering each talk inside `<transcripts_dir>/<Slug>/` containing the Markdown editions, Google Doc shortcut, optional changelog, and `assets/` (inline embeds in Clean-Read and Thematic; clickable links only in Verbatim Perfect).
- **Google Docs image-embedding and YouTube auto-dub troubleshooting (`references/troubleshooting.md`):** Added Section 11 covering `gdocs mutate insert-image-from-file` `--alt-title`/`--alt-description` errors, literal matching in `gdocs mutate sed`, Windows `.CMD` shim resolution via `shutil.which()`, and selecting the original non-DRC audio stream on multi-language auto-dubbed YouTube videos.
- **Unit tests for Stage 4B and Google Docs image staging (`tests/test_scripts.py`):** Added unit tests covering `capture_slides.py` helpers, HTML generation, asset packaging with URL harvesting, `--capture-slides` format selection, and `fix_gdocs_toc_links.stage_markdown_for_gdocs_images`.

## [1.2.0] - 2026-11-19

### Added
- **Remote webinar attendance and capture (`scripts/attend_webinar.py`, `references/webinar-capture.md`, `SKILL.md`, `README.md`, `CONTRIBUTING.md`, `troubleshooting.md`):** Added Stage 0B and a dedicated webinar-capture reference guide for passive browser webinar attendance (Zoom Events, Zoom Web Client, and web streams) via headless Chromium (`--headless=new`), hard-blocking camera and microphone (`permissions=[]` + `getUserMedia` `NotAllowedError` override), capturing tab video (`1280x720` VP8) and audio (`48 kHz` `128 kbps` Opus, `suppressLocalAudioPlayback: true`, never `--mute-audio`) directly to disk without virtual audio cables, streaming live JSON telemetry + screenshots, and accepting agent commands via JSON file.
- **Reference-document grounding for any recording (`SKILL.md`, `README.md`):** Added optional Stage 3 grounding for supporting PDF reports, PowerPoint `.pptx` decks, Google Slides, and handouts across all recordings (presentations, Looms, webinars, and calls). Extracts document text to plain text via Python (`pypdf`, `python-pptx`, or Slides/Docs text export) as spelling and terminology hints, sharpening proper nouns and frameworks without filling up visual context or altering what speakers actually said aloud.
- **Auto-end detection & lossless silence trimming (`scripts/attend_webinar.py`):** Detects end-of-webinar phrases and post-webinar survey URLs before dismissing interstitials, falls back to sustained post-speech silence (`--end-silence-seconds 180` at `-45 dB`), and losslessly (`-c copy`) trims leading waiting-room and trailing silence using `ffmpeg silencedetect`.
- **Unit tests for webinar helpers and `--screen-share` segmentation (`tests/test_scripts.py`):** Added tests for `detect_end_signal`, `parse_silencedetect_output`, `compute_trim_bounds`, `attend_webinar.py --help` (stdlib-only lazy Playwright import), and `prepare_compact_video.resolve_segment_settings`.

### Changed
- **Compaction-safe `--screen-share` segmentation (`scripts/prepare_compact_video.py`, `scripts/prepare_compact_video.ps1`, `SKILL.md`, `README.md`, `troubleshooting.md`):** Tightened default `--screen-share` / `-ScreenShare` (`>=960px`) segmentation from `1200s / 25 min / 45 MB` to `600s / 15 min / 25 MB` across both Python and PowerShell prep scripts so high-resolution slide captures stay safely inside multimodal agent context limits.
- **Stage 4 segment-boundary verification (`SKILL.md`, `README.md`, `troubleshooting.md`):** Added explicit guidance to extract `+/-4s` enhanced `.wav` clips around any mid-sentence segment boundary against the unsplit original recording so keyframe cuts never drop boundary words.
- **Compact README & dedicated CLI reference (`README.md`, `references/cli-reference.md`, `SKILL.md`, `assets/social-preview.svg`):** Rewrote `README.md` into a concise, artifact-led layout (`Outputs`, `Ask your agent`, `Develop and verify`) matching `osbornec/weekly-product-review`, moved full CLI flag tables and manual install commands into `references/cli-reference.md`, tightened `SKILL.md` frontmatter and opening copy, and redesigned `assets/social-preview.svg` on a clean light studio canvas showing a synthetic Thematic Clean-Read transcript card.

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
