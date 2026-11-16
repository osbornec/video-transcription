"""
Upload compact 1 FPS video segments or speech-enhanced .wav clips to the Gemini API
for non-Antigravity agents (Claude Code, OpenAI Codex, Cursor, standalone CLI).

Uses only the Python 3 standard library (urllib.request) and requires GEMINI_API_KEY
(or GOOGLE_API_KEY). Uploaded media is automatically deleted from the Gemini Files
API when processing completes unless --keep-remote is passed.

Usage:
    python3 transcribe_media.py -i part00.mp4 --offset 00:00 -o scratch/verbatim_chunk_01.md
    python3 transcribe_media.py -i w01.wav w02.wav --mode audit-wav --context @draft_lines.txt
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://generativelanguage.googleapis.com"

AUDIO_EXTENSIONS = {".m4a", ".aac", ".mp3", ".wav", ".flac", ".ogg", ".opus"}

MIME_OVERRIDES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
}


def is_audio_only_batch(filenames: list[str | Path]) -> bool:
    """Return True when every file in the batch is an audio-only container."""
    return bool(filenames) and all(Path(f).suffix.lower() in AUDIO_EXTENSIONS for f in filenames)


def detect_mime_type(file_path: Path) -> str:
    """Determine MIME type for common video and audio containers cleanly across OSes."""
    ext = file_path.suffix.lower()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    guessed, _ = mimetypes.guess_type(str(file_path))
    return guessed or "application/octet-stream"


def parse_offset_label(offset_str: str) -> str:
    """Validate and normalize timestamp offset (MM:SS or HH:MM:SS)."""
    cleaned = offset_str.strip()
    if not re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", cleaned):
        raise ValueError(f"Invalid --offset format '{offset_str}'. Expected MM:SS or HH:MM:SS.")
    return cleaned


def load_context_text(context_arg: str) -> str:
    """Load inline context or read context from '@filepath'."""
    if not context_arg:
        return ""
    if context_arg.startswith("@"):
        ctx_path = Path(context_arg[1:]).expanduser()
        if not ctx_path.is_file():
            raise FileNotFoundError(f"Context file not found: {ctx_path}")
        return ctx_path.read_text(encoding="utf-8", errors="replace").strip()
    return context_arg.strip()


def build_prompts(
    mode: str,
    offset_label: str,
    context_text: str,
    filenames: list[str],
    audio_only: bool | None = None,
) -> tuple[str, str]:
    """Construct high-accuracy transcription or WAV audit prompts for Gemini."""
    context_block = f"\n\n### Reference Context / Metadata\n{context_text}" if context_text else ""

    if mode == "audit-wav":
        system_instruction = (
            "You are a forensic audio transcription reviewer. Listen closely to the "
            "speech-enhanced 16-bit PCM WAV clip(s) provided and transcribe the exact "
            "spoken words without fabricating or smoothing missing words."
        )
        user_prompt = (
            f"Audit the attached enhanced WAV clip(s): {', '.join(filenames)}.\n"
            "For each file:\n"
            "1. Provide the exact verbatim words heard, noting speaker switches or overlap.\n"
            "2. Distinguish similar-sounding technical terms, numbers, and proper nouns.\n"
            "3. If audio is genuinely destroyed by distortion or VoIP packet loss, explicitly "
            "mark `[heavy packet loss]` or `[garbled]` instead of guessing."
            f"{context_block}"
        )
        return system_instruction, user_prompt

    is_audio = is_audio_only_batch(filenames) if audio_only is None else audio_only
    if is_audio:
        system_instruction = (
            "You are an expert audio transcriptionist and speaker diarist. "
            "Use episode metadata/show notes, spoken self-introductions, conversational addressing, "
            "vocal timbre, and Left/Right stereo separation to produce an exact word-for-word "
            "verbatim Markdown transcript."
        )
        user_prompt = (
            f"Transcribe the attached audio podcast / recording segment(s) ({', '.join(filenames)}) verbatim.\n\n"
            "Requirements:\n"
            f"- Add the segment base offset (`+{offset_label}`) to every relative timestamp so all "
            "`**[MM:SS] Speaker Name:**` headings reflect absolute recording time.\n"
            "- Diarize speakers accurately using spoken introductions (*'I'm Alice, joined by Bob'*), "
            "direct addressing, voice timbre, and reference metadata; only use `Host` / `Guest 1` "
            "temporarily if names are not yet introduced.\n"
            "- Preserve exact spoken wording, self-corrections, and notable audio cues.\n"
            "- Never fabricate words during dropouts or crosstalk; mark `[heavy packet loss]` or `[unclear]` honestly.\n"
            "- At the very end, include a `## Low-SNR Audit Windows` bullet list with `HH:MM:SS-HH:MM:SS` "
            "windows for any unclear, quiet, overlapping, or proper-noun passages that warrant PCM WAV extraction."
            f"{context_block}"
        )
        return system_instruction, user_prompt

    system_instruction = (
        "You are an expert multimodal transcriptionist and visual speaker diarist. "
        "Use BOTH audio waveforms and visual frames (lower-thirds, speaker thumbnails, "
        "active-speaker highlights, slides, seating, mic handoffs) to produce an exact "
        "word-for-word verbatim Markdown transcript."
    )
    user_prompt = (
        f"Transcribe the attached compact media segment(s) ({', '.join(filenames)}) verbatim.\n\n"
        "Requirements:\n"
        f"- Add the segment base offset (`+{offset_label}`) to every relative timestamp so all "
        "`**[MM:SS] Speaker Name:**` headings reflect absolute recording time.\n"
        "- Preserve exact spoken wording, self-corrections, and meaningful visual transitions.\n"
        "- Verify spelling of all names/brands from slides, Zoom labels, or reference context.\n"
        "- Never fabricate words during packet loss or dropouts; mark `[heavy packet loss]` or `[unclear]` honestly.\n"
        "- At the very end, include a `## Low-SNR Audit Windows` bullet list with `HH:MM:SS-HH:MM:SS` "
        "windows for any unclear, quiet, fast, or overlapping phrases that warrant PCM WAV extraction."
        f"{context_block}"
    )
    return system_instruction, user_prompt


def _http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 300,
) -> tuple[dict[str, str], bytes]:
    """Execute HTTP request and surface clear Gemini API JSON errors on failure."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp_headers, resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API HTTP {exc.code} on {method} {url.split('?')[0]}:\n{body}") from exc


def upload_media_file(api_key: str, file_path: Path, poll_interval: float = 3.0) -> dict[str, str]:
    """Resumable upload to Gemini Files API and wait until file state is ACTIVE."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Media file not found: {file_path}")

    mime_type = detect_mime_type(file_path)
    file_bytes = file_path.read_bytes()
    size = len(file_bytes)
    start_url = f"{API_BASE}/upload/v1beta/files?key={urllib.parse.quote(api_key)}"
    meta = json.dumps({"file": {"display_name": file_path.name}}).encode("utf-8")

    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json; charset=utf-8",
    }
    resp_headers, _ = _http_request(start_url, method="POST", headers=headers, data=meta, timeout=60)
    upload_url = resp_headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError(f"Gemini Files upload did not return X-Goog-Upload-URL for {file_path.name}")

    upload_headers = {
        "Content-Length": str(size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize",
    }
    _, body = _http_request(upload_url, method="POST", headers=upload_headers, data=file_bytes, timeout=600)
    file_info = json.loads(body.decode("utf-8")).get("file", {})
    file_name = file_info.get("name", "")
    file_uri = file_info.get("uri", "")
    state = file_info.get("state", "ACTIVE")

    poll_url = f"{API_BASE}/v1beta/{file_name}?key={urllib.parse.quote(api_key)}"
    while state == "PROCESSING":
        time.sleep(poll_interval)
        _, poll_body = _http_request(poll_url, method="GET", timeout=60)
        file_info = json.loads(poll_body.decode("utf-8"))
        state = file_info.get("state", "ACTIVE")
        file_uri = file_info.get("uri", file_uri)

    if state == "FAILED":
        raise RuntimeError(f"Gemini Files processing failed for {file_path.name}: {json.dumps(file_info)}")

    return {"name": file_name, "uri": file_uri, "mime_type": mime_type}


def delete_remote_file(api_key: str, file_name: str) -> None:
    """Best-effort deletion of temporary remote media from Gemini Files API."""
    if not file_name:
        return
    del_url = f"{API_BASE}/v1beta/{file_name}?key={urllib.parse.quote(api_key)}"
    try:
        _http_request(del_url, method="DELETE", timeout=30)
    except Exception as exc:
        print(f"Warning: failed to delete remote file {file_name}: {exc}", file=sys.stderr)


def generate_multimodal(
    api_key: str,
    model: str,
    uploaded_files: list[dict[str, str]],
    system_instruction: str,
    user_prompt: str,
) -> str:
    """Invoke Gemini generateContent with uploaded file URIs and text instructions."""
    parts: list[dict] = [
        {"file_data": {"mime_type": f["mime_type"], "file_uri": f["uri"]}}
        for f in uploaded_files
    ]
    parts.append({"text": user_prompt})

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.1},
    }
    url = f"{API_BASE}/v1beta/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(api_key)}"
    _, body = _http_request(
        url,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
        data=json.dumps(payload).encode("utf-8"),
        timeout=600,
    )
    resp = json.loads(body.decode("utf-8"))
    candidates = resp.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini API returned no candidates:\n{json.dumps(resp, indent=2)}")

    text_chunks = [
        p.get("text", "")
        for p in candidates[0].get("content", {}).get("parts", [])
        if "text" in p
    ]
    return "\n".join(text_chunks).strip()


def resolve_api_key(cli_key: str) -> str:
    """Resolve Gemini API key from CLI flag or standard environment variables."""
    key = (cli_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Create a free/billed key in Google AI Studio and set "
            "GEMINI_API_KEY (or pass --api-key)."
        )
    return key


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe compact video chunks or audit enhanced WAV clips via Gemini API."
    )
    parser.add_argument("-i", "--input", nargs="+", required=True, help="Media file path(s) (.mp4, .mkv, .wav, etc.)")
    parser.add_argument(
        "-m",
        "--mode",
        choices=["transcribe", "audit-wav"],
        default="transcribe",
        help="Workflow mode: full visual-audio pass ('transcribe') or WAV clip check ('audit-wav')",
    )
    parser.add_argument("--offset", default="00:00", help="Segment start time offset (MM:SS or HH:MM:SS)")
    parser.add_argument(
        "--context",
        default="",
        help="Optional context/chapter/draft text or '@path/to/context.txt'",
    )
    parser.add_argument("-o", "--output", default="", help="Write Markdown output directly to this file")
    parser.add_argument("--model", default="gemini-2.5-pro", help="Gemini model ID (default: gemini-2.5-pro)")
    parser.add_argument("--api-key", default="", help="Optional Gemini API key (defaults to GEMINI_API_KEY)")
    parser.add_argument(
        "--keep-remote",
        action="store_true",
        help="Retain uploaded files on Gemini Files API instead of deleting after completion",
    )
    args = parser.parse_args()

    api_key = resolve_api_key(args.api_key)
    offset_label = parse_offset_label(args.offset)
    context_text = load_context_text(args.context)
    input_paths = [Path(p).expanduser().resolve() for p in args.input]
    for p in input_paths:
        if not p.is_file():
            raise FileNotFoundError(f"Media file not found: {p}")

    system_instruction, user_prompt = build_prompts(
        args.mode, offset_label, context_text, [p.name for p in input_paths]
    )

    uploaded: list[dict[str, str]] = []
    try:
        for p in input_paths:
            print(f"Uploading {p.name} to Gemini Files API...", file=sys.stderr)
            info = upload_media_file(api_key, p)
            uploaded.append(info)

        print(f"Running {args.mode} with {args.model}...", file=sys.stderr)
        result_text = generate_multimodal(api_key, args.model, uploaded, system_instruction, user_prompt)
    finally:
        if not args.keep_remote:
            for item in uploaded:
                delete_remote_file(api_key, item.get("name", ""))

    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path} ({len(result_text)} chars)", file=sys.stderr)
    else:
        print(result_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
