---
name: video-transcription
description: >-
  Transcribe video, audio, YouTube videos, and podcasts (Spotify, Apple Podcasts, YouTube Music)
  to text with speaker diarization, speech-to-text PCM audio auditing, and Markdown / Google Docs
  publishing. Use for video to text, audio to text, YouTube transcript, podcast transcript, or
  fixing [unclear] spans. Skip for live streaming captioning or video subtitle burn-in.
license: MIT
metadata:
  version: "1.0.0"
references:
  - editorial-style-guide
  - troubleshooting
---

# Video, Audio & YouTube Transcription (Podcast & Speaker Diarization)

A cross-platform **6-stage speech-to-text & transcription runbook (Stages 0–5)** for turning YouTube videos, podcasts (Spotify, Apple Podcasts, YouTube Music), webinars, interviews, and local recordings into speaker-diarized, verified Markdown (`.md`) and Google Docs transcripts across **macOS, Linux, and Windows**.

## When to Use This Skill

**Use when (Positive Triggers):**
- Transcribing or visually diarizing a recorded video, panel, webinar, interview, podcast, or meeting (local file or YouTube/video URL).
- Auditing `[unclear]` spans, misheard technical jargon, or misattributed speakers in an existing `.md`/`.txt`/`.docx` draft against the original media.
- Producing **Verbatim**, **Clean-Read**, **Thematic Clean-Read** (with clickable Table of Contents), or **Verification Changelog** editions in Markdown (`.md`) and optional Google Docs.

**Skip when (Negative Triggers):**
- Real-time live-stream captioning, SRT/VTT subtitle timing generation, or burning hardcoded captions into video frames.
- Editing prose-only documents that have no audio or video source.

**Example Prompts:**
- *"Transcribe this YouTube panel (`https://www.youtube.com/watch?v=...`), verify speakers visually, and export Verbatim and Thematic Clean-Read Markdown editions."*
- *"Audit `./draft.md` against `./recordings/session.mp4`, extract enhanced audio clips for every `[unclear]` timestamp, and generate `Transcript_Corrections_Changelog.md`."*
- *"Publish `./Session_Thematic_Clean_Read_Transcript.md` to Google Docs with working Table of Contents links."*

## Critical Rules (Always Apply)

> [!CAUTION]
> **Never downsample compressed speech audio to shave file size** (for example, `32k` AAC). Generational lossy audio compression smears high-frequency consonants (`s`, `t`, `k`, `p`, `f`) and causes hallucinations on quiet or off-mic speech. Reduce size by compacting video frames to `<=480px` at `1 FPS` while keeping `-c:a copy` (or `128k` AAC for PCM/FLAC).

> [!IMPORTANT]
> - **Outputs are strictly Markdown (`.md`) + optional Google Docs (+ local `.url`/`.webloc` shortcuts). Never generate `.docx` outputs** unless the user explicitly asks for Word format.
> - **Chunk recordings longer than 25 minutes** (`1200s` segments) and flush each verbatim segment (`verbatim_chunk_XX.md`) to disk immediately before reading the next segment so LLM context compaction never wipes un-persisted dialogue.
> - **Never invent missing words** during unrecoverable VoIP packet loss or source dropouts—verify via PCM `.wav` extraction first, then annotate lost intervals transparently (`*[heavy packet loss / audio dropouts]* ... *[garbled]*`).

---

## Quick Decision Trees

### 1. Input Source Routing
```text
What input did the user provide?
├─ Online video URL (YouTube, etc.) ──> Stage 0 (prepare_compact_video.py --url) -> Stage 1..5
├─ Local video (.mp4/.mov/.mkv/.webm) > Stage 1 -> Stage 2 (prepare_compact_video.py --input-path) -> Stage 3..5
├─ Local audio (.m4a/.mp3/.wav/.flac) > Stage 1 -> Stage 2 (<90 MB compressed copied; PCM -> 128k AAC) -> Stage 3..5
└─ Existing draft (.md/.docx) + media > Stages 1..4 verification -> build_changelog.py + updated .md
```

### 2. Agent Runtime Routing
```text
Which environment is executing this skill?
├─ Google Antigravity
│  ├─ Stages 3 & 4 media ingestion ────> Native read_file directly on compact chunks & .wav clips
│  └─ Stage 5 Google Docs publishing ─> fix_gdocs_toc_links.py (auto-selects built-in gdocs CLI)
└─ Claude Code / OpenAI Codex / Cursor / CLI
   ├─ Stages 3 & 4 media ingestion ────> scripts/transcribe_media.py (requires GEMINI_API_KEY)
   └─ Stage 5 publishing
      ├─ Markdown (.md) deliverables ──> Always generated cleanly (zero external credentials)
      └─ Optional Google Docs ─────────> fix_gdocs_toc_links.py (Drive v3 + Docs v1 REST via gcloud/OAuth)
```

### 3. Deliverable Editions Routing
```text
Which artifacts should Stage 5 produce?
├─ Full archival record ───────────────> *_Perfect_Transcript.md
├─ Stakeholder / quote-review copy ────> *_Clean_Read_Transcript.md
├─ Structured chapter navigation ──────> *_Thematic_Clean_Read_Transcript.md (+ native ToC links)
└─ Fixing an existing [unclear] draft ─> Transcript_Corrections_Changelog.md (build_changelog.py)
```

---

## Environment Setup Check

Verify core tools before starting:

```bash
python3 --version
ffmpeg -version | head -n 1
ffprobe -version | head -n 1
yt-dlp --version 2>/dev/null || python3 -m yt_dlp --version 2>/dev/null || echo "yt-dlp optional (needed only for --url)"
```

See [`references/troubleshooting.md`](./references/troubleshooting.md) if any tool is missing on macOS, Windows, or Linux.

> **Path convention:** Replace `<skill_dir>` below with the folder containing this `SKILL.md` (for example `~/.gemini/config/skills/video-transcription`, `~/.codex/skills/video-transcription`, `~/.claude/skills/video-transcription`, or `.agents/skills/video-transcription`). On Windows PowerShell, invoke Python with `python` instead of `python3`.

---

## Stage 0: URL Acquisition & Metadata Intake (Optional)

When starting from an online video or podcast URL (YouTube, YouTube Music, Apple Podcasts, Spotify episode URLs, or direct feeds):

1. **Download non-DRC audio + `<=480p` video (or `--audio-only`) + `.info.json` metadata:**
   ```bash
   python3 "<skill_dir>/scripts/prepare_compact_video.py" \
     --url "<video_or_podcast_url>" \
     --output-path "<work_dir>/<slug>_compact_1fps.mp4"

   # Audio podcasts or music.youtube.com URLs (skips video download/transcode)
   python3 "<skill_dir>/scripts/prepare_compact_video.py" \
     --url "<podcast_or_ytm_url>" \
     --audio-only
   ```
   `prepare_compact_video.py` prefers `bv*[height<=480]+ba[format_id!*=-drc]` (or `ba[format_id!*=-drc]` with `--audio-only`), resolves Spotify/Apple Podcasts episodes to their public DRM-free RSS audio enclosures, writes `.info.json`, and continues automatically into Stages 1 and 2.
2. **Inspect `.info.json` before Pass 1:** Extract `title`, `channel`, `upload_date`, `duration_string`, `description`, and `chapters` to establish official section boundaries, show-note guest names, and exact proper-noun spellings.

---

## Stage 1: Stream & Channel Topology Audit

Automated by `prepare_compact_video.py`, or inspect manually:

```bash
ffprobe -v error -show_entries format=duration,size \
  -show_entries stream=index,codec_type,codec_name,bit_rate,channels,sample_rate,width,height \
  -of default=noprint_wrappers=1 "<input_media>"
```

When `channels=2`, check L/R phase separation (`c0 - c1`):

```bash
ffmpeg -hide_banner -i "<input_media>" -af "pan=mono|c0=c0-c1,astats=measure_perchannel=0" -f null -
```

- `RMS level dB: -inf` or `<= -45.0 dB`: **Dual-mono or codec dither** (e.g., Zoom/AAC encoding variance around `-65 dB`). Omit `--split-channels`.
- `> -45.0 dB` (and not `-inf`): **True stereo** (panned panel microphones). Pass `--split-channels` in Stage 4 to isolate Left/Right crosstalk.

---

## Stage 2: Lossless-Audio Compaction & Auto-Segmentation

Run [`scripts/prepare_compact_video.py`](./scripts/prepare_compact_video.py):

```bash
python3 "<skill_dir>/scripts/prepare_compact_video.py" --input-path "<input_media>"
```

Script behavior by input format:
- **Video + AAC/MP3 (`.mp4`, `.mov`):** Scales with a **no-upscale even-dimension guard** (`trunc(min(480,iw)/2)*2:-2`) at `1 FPS` (`-crf 35`, `10s` keyframe cadence `-g`) and preserves audio bit-for-bit (`-c:a copy`).
- **Video + Opus/Vorbis (`.webm`, `.mkv`):** Copies audio lossless into `.mkv` (or transcodes to `128k` AAC if `.mp4` output path is explicitly given).
- **Video + PCM/FLAC:** Encodes audio to high-bitrate `128k` AAC `.mp4`.
- **Audio-Only (`.m4a`, `.mp3`, `.wav`, `.flac`, `.ogg`, or `--audio-only`):** Copies compressed files under `90 MB` directly, strips video lossless (`-vn -c:a copy`) when `--audio-only` is passed on a video/music-video source, or encodes uncompressed PCM/FLAC to `128k` AAC `.m4a`.
- **Compaction-Safe Auto-Segmentation (`>45 MB` or `>25 min`):** Automatically creates keyframe-aligned `20-minute` (`1200s`) lossless segments (`*_part00.*`, `*_part01.*`, ...).

---

## Stage 3: Pass 1 — Chunked Multimodal Transcription & Visual Diarization

1. **Process segments sequentially** (or chapter-aligned chunks from `.info.json`) when duration exceeds 25 minutes. Adjust relative timestamps by each segment's start `--offset` and **immediately write each completed chunk (`<scratch_dir>/verbatim_chunk_XX.md`) to disk** before reading the next segment:
   - **In Google Antigravity:** Call `read_file` directly on each segment.
   - **Outside Antigravity (`GEMINI_API_KEY` set):**
     ```bash
     python3 "<skill_dir>/scripts/transcribe_media.py" \
       --mode transcribe \
       --input "<work_dir>/<slug>_compact_1fps_part00.mp4" \
       --offset "00:00" \
       --context "@<work_dir>/<slug>.info.json" \
       --output "<scratch_dir>/verbatim_chunk_01.md"
     ```
2. **Use visual or audio diarization cues:**
   - *Video:* Confirm speaker identity and spelling from lower-thirds, speaker thumbnails, active-speaker borders, slides, and mic handoffs.
   - *Audio podcasts (`mp3`/`m4a`/`wav`):* Confirm speakers from `.info.json` episode metadata/show notes, spoken introductions (*"I'm X, joined by Y"*), direct addressing, vocal timbre, and stereo L/R panning (`transcribe_media.py` switches to audio-podcast diarization prompting automatically when given audio inputs).
3. **Log every low-SNR window (`HH:MM:SS-HH:MM:SS`):** Never silently guess off-mic audience questions, overlapping crosstalk, fast numbers, or proper nouns.
4. **Use conversational callbacks as a checksum:** Later references often verify an earlier off-mic remark (e.g., *"As I teased about the tail latency spike earlier..."* confirms an unclear quip was *"Check the tail latency!"*).

---

## Stage 4: Pass 2 — Speech-Enhanced 16-Bit PCM `.wav` Audit

Extract every flagged low-SNR window directly from the **original source file** with a `100 Hz – 8 kHz` speech band-pass filter and dynamic normalization (`dynaudnorm`):

```bash
python3 "<skill_dir>/scripts/extract_enhanced_clips.py" \
  --input-path "<original_media>" \
  --output-dir "<scratch_dir>" \
  --windows "00:04:10-00:04:35" "00:28:30-00:29:05"
```

- Add `--split-channels` on true-stereo recordings to isolate `_L.wav` and `_R.wav`.
- Verify every clip:
  - **In Google Antigravity:** Open each `.wav` clip via `read_file`.
  - **Outside Antigravity:**
    ```bash
    python3 "<skill_dir>/scripts/transcribe_media.py" \
      --mode audit-wav \
      --input "<scratch_dir>/w01_000410_000435.wav" \
      --context "Uncertain technical phrase near 04:20"
    ```
- Apply verified corrections into the assembled transcript (marking genuine source distortion/VoIP drops as `*[heavy packet loss / audio dropouts]*`), then remove temporary `.wav` and chunk scratch files.

---

## Stage 5: Editorial Formatting & Publishing

Follow [`references/editorial-style-guide.md`](./references/editorial-style-guide.md) when producing any requested combination of:
1. `*_Perfect_Transcript.md` (full verbatim record)
2. `*_Clean_Read_Transcript.md` (fillers trimmed, 100% of substance & timestamps preserved)
3. `*_Thematic_Clean_Read_Transcript.md` (clickable Table of Contents + numbered sections + 1-sentence italic takeaways)
4. `Transcript_Corrections_Changelog.md` via [`scripts/build_changelog.py`](./scripts/build_changelog.py):
   ```bash
   python3 "<skill_dir>/scripts/build_changelog.py" \
     --old "<draft.md|draft.docx>" \
     --new "<verified_perfect.md>" \
     --output "<work_dir>/Transcript_Corrections_Changelog.md"
   ```

### Optional Google Docs Publishing & ToC Binding
If publishing to Google Docs, run [`scripts/fix_gdocs_toc_links.py`](./scripts/fix_gdocs_toc_links.py) to import Markdown and rebind `#slug` Table of Contents anchors to native Google Docs `#heading=h.xxx` targets (automatically choosing Antigravity's `gdocs` CLI or direct Drive v3 / Docs v1 REST APIs):

```bash
python3 "<skill_dir>/scripts/fix_gdocs_toc_links.py" \
  --import-md "<work_dir>/<slug>_Thematic_Clean_Read_Transcript.md" \
  --title "<Document Title>" \
  --shortcut-dir "<work_dir>" \
  --shortcut-format auto
```

Outside Antigravity without Google Cloud OAuth configured, skip `fix_gdocs_toc_links.py` and deliver the Markdown deliverables (whose `#slug` anchors already navigate cleanly in GitHub, VS Code, and Obsidian).

---

## Verification Checklist

- [ ] If starting from a URL, non-DRC audio and `.info.json` metadata/chapters were inspected before Pass 1.
- [ ] Compact media stayed `<45 MB` and `<=25 min` per segment with original audio fidelity preserved and zero low-resolution upscaling.
- [ ] On recordings `>25 minutes`, verbatim draft chunks (`verbatim_chunk_XX.md`) were persisted sequentially to disk before assembly.
- [ ] All flagged low-SNR windows were extracted as PCM `.wav` clips and audited; temporary `.wav` and chunk files were removed afterward.
- [ ] Zero unverified `[unclear]` guesses remain (genuine distortion/packet loss marked honestly).
- [ ] Final deliverables exist as Markdown (`.md`) (plus Google Docs + shortcuts when publishing is enabled)—zero `.docx` files created.
- [ ] Any Google Doc containing a Table of Contents passed `fix_gdocs_toc_links.py` verification with native `headingId` links active.
