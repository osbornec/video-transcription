# Contributing to `video-transcription`

Thank you for helping improve the `video-transcription` agent skill and Python CLI toolkit.

## Principles
1. **Zero extra Python runtime dependencies for core scripts:** `prepare_compact_video.py`, `transcribe_media.py`, `extract_enhanced_clips.py`, `fix_gdocs_toc_links.py`, and `build_changelog.py` must run cleanly using only the Python 3.10+ standard library. Keep optional libraries (like `playwright` in `attend_webinar.py` and `python-docx` in `build_changelog.py`) guarded by lazy imports with actionable install error messages so `--help` and stdlib unit tests always pass.
2. **Cross-platform parity:** Avoid OS-specific shell assumptions, hardcoded home paths, or platform-only path separators (`\` vs `/`). Always use `pathlib.Path` or `os.path` and `shutil.which()`.
3. **Preserve audio fidelity:** Never down-encode compressed audio solely to shave file size during transcription prep.

## Local Development & Verification

Run the unit test suite from the repository root:

```bash
# macOS / Linux
python3 -m unittest discover -s tests -v

# Windows
python -m unittest discover -s tests -v
```

When modifying `SKILL.md`, `references/`, or `scripts/`:
- Update usage examples in both `SKILL.md` and `README.md`.
- Add or update unit tests in `tests/test_scripts.py`.
- Confirm zero personal workspace paths and zero em/en dashes (`\u2014`, `\u2013`) appear in tracked docs (`tests/test_scripts.py` checks both automatically).
