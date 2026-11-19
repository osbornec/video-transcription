# Video Transcription

Transcribe videos, live webinars, and podcasts straight into Markdown and Google Docs.

Auto-captions misspell company names and label everyone `Speaker 1`. Browser AI chats trap summaries inside one person's tab. Long recordings cut off halfway through, and live webinars clash with your calendar.

This skill handles the whole workflow inside your coding agent. Drop in a recording, Loom, YouTube video, podcast, or live webinar link, plus any supporting PDF or slide deck. Your agent reads speaker names on screen, checks unclear lines against the original audio, and attends browser webinars silently with camera and mic off. Everything lands as Markdown files in your workspace or formatted Google Docs your whole team and their agents can use.

```bash
npx skills add osbornec/video-transcription
```

## Outputs

Every run writes Markdown files into your workspace rather than leaving summaries inside a browser chat tab. See the [synthetic sample outputs](examples/sample_outputs.md) for side-by-side excerpts across all four editions.

| Output | Use |
| :--- | :--- |
| `*_Perfect_Transcript.md` | Full spoken record with timestamps, verified speaker names, and explicit audio-dropout markers |
| `*_Clean_Read_Transcript.md` | Spoken fillers trimmed while keeping all facts, numbers, speaker voice, and `[MM:SS]` timestamps |
| `*_Thematic_Clean_Read_Transcript.md` | Numbered chapters, one-sentence takeaways, and a clickable Table of Contents with working links in Markdown and Google Docs |
| `Transcript_Corrections_Changelog.md` | Turn-by-turn diff logging resolved `[unclear]` spans and speaker fixes against an existing draft |

## Run a transcription

| Ask your agent | What happens |
| :--- | :--- |
| "Transcribe this Loom (`https://www.loom.com/share/...`) into Clean-Read and Thematic Markdown." | Downloads non-DRC audio and compact `1 FPS` video, reads speaker names on screen, checks unclear timestamps against isolated `.wav` clips, and writes Markdown. |
| "Attend this Zoom Events webinar (`https://events.zoom.us/ej/...`) with camera and mic off and transcribe it." | Joins in headless Chromium with camera and microphone hard-blocked, records video and audio silently to disk, stops when the webinar ends, trims waiting-room silence, and transcribes in chunks. |
| "Transcribe `./recordings/presentation.mp4` using `./deck.pdf` for names and terminology." | Extracts plain text from attached PDF reports, PowerPoint `.pptx` decks, or Google Slides as spelling hints without filling visual context or altering what speakers said aloud. |
| "Transcribe this podcast (`https://open.spotify.com/episode/...`) and publish a Google Doc." | Resolves the public RSS audio enclosure, attributes speakers, writes Markdown, and exports to Google Docs with working native Table of Contents links and local shortcuts. |
| "Audit `./draft.md` against `./recordings/call.mp4`." | Extracts `100 Hz to 8 kHz` PCM `.wav` clips for every flagged timestamp from the original recording and writes `Transcript_Corrections_Changelog.md`. |

To preserve speech accuracy without hitting context limits, `prepare_compact_video.py` shrinks video to `1 FPS` while copying original speech audio bit-for-bit (`-c:a copy`), splits long files into lossless chunks written sequentially to disk (`20` min standard, `10` min with `--screen-share` for `960px` slides), checks stereo phase separation before splitting channels, and audits both unclear timestamps and `+/-4s` mid-sentence segment seams against the unsplit source media. When source audio is genuinely lost, the transcript marks `*[heavy packet loss / audio dropouts]*` or `*[audio splice]*` instead of guessing. Skip this skill for real-time live captions, `.srt`/`.vtt` subtitle syncing, burnt-in captions, or DRM-locked paid podcast feeds.

- [CLI reference, manual install, and prerequisites](references/cli-reference.md)
- [Editorial style guide and heading slug rules](references/editorial-style-guide.md)
- [Headless webinar capture architecture and privacy locks](references/webinar-capture.md)
- [Cross-platform troubleshooting](references/troubleshooting.md)

## Develop and verify

The repository root is the installable skill folder. The 5 core scripts use the Python 3.10+ standard library and `ffmpeg`, with optional Playwright for live webinar capture and `GEMINI_API_KEY` (Gemini 4) outside Antigravity.

```bash
python3 -m unittest discover -s tests -v
```

The test suite checks CLI `--help` exit codes (including stdlib-only lazy imports), podcast RSS resolution, webinar end-signal and silence-trim logic, `--screen-share` segmentation defaults, zero hardcoded personal paths, and zero em/en dashes in tracked docs. See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

MIT. See [LICENSE](LICENSE).
