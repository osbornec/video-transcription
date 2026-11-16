"""
Extract targeted low-SNR windows from media as uncompressed 16-bit PCM .wav clips
with speech band-pass filtering (100 Hz - 8 kHz) and dynamic normalization.
Supports optional Left/Right stereo channel isolation (--split-channels).

Usage:
    python extract_enhanced_clips.py -i panel.mp4 -o ./scratch -w 00:01:40-00:02:20 28:30-29:05
    python extract_enhanced_clips.py -i stereo.mp4 -o ./scratch -w 10:00-10:30 --split-channels
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_FILTER = "highpass=f=100,lowpass=f=8000,dynaudnorm=f=150:g=15"


def require_binary(name: str) -> str:
    """Return path to a required binary or raise a helpful cross-platform error."""
    found = shutil.which(name)
    if found:
        return found
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        hint = "Install on macOS via: brew install ffmpeg"
    elif sys_name == "windows":
        hint = "Install on Windows via: winget install Gyan.FFmpeg"
    else:
        hint = "Install on Linux via: sudo apt install ffmpeg"
    raise FileNotFoundError(f"Required executable '{name}' not found on PATH. {hint}")


def normalize_timestamp(ts: str) -> str:
    """Convert MM:SS(.fff) timestamps into HH:MM:SS(.fff) for ffmpeg."""
    cleaned = ts.strip()
    if re.match(r"^\d{1,2}:\d{2}(\.\d+)?$", cleaned):
        return f"00:{cleaned}"
    return cleaned


def parse_windows(raw_tokens: list[str]) -> list[tuple[str, str]]:
    """Expand space- or comma-separated window strings into validated (start, end) pairs."""
    tokens: list[str] = []
    for item in raw_tokens:
        tokens.extend(part.strip() for part in item.split(",") if part.strip())

    parsed: list[tuple[str, str]] = []
    for win in tokens:
        parts = win.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid window format '{win}'. Expected 'HH:MM:SS-HH:MM:SS' or 'MM:SS-MM:SS'.")
        parsed.append((normalize_timestamp(parts[0]), normalize_timestamp(parts[1])))
    return parsed


def extract_clip(ffmpeg_bin: str, resolved_input: Path, start: str, end: str, audio_filter: str, out_file: Path) -> None:
    """Extract a single speech-enhanced 16-bit PCM WAV clip via ffmpeg."""
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        start,
        "-to",
        end,
        "-i",
        str(resolved_input),
        "-af",
        audio_filter,
        "-c:a",
        "pcm_s16le",
        str(out_file),
        "-loglevel",
        "error",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0 or not out_file.is_file():
        raise RuntimeError(f"Failed to extract clip ({start} -> {end}) to {out_file}: {res.stderr}")
    print(f"Created: {out_file} ({start} -> {end})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract speech-enhanced uncompressed 16-bit PCM .wav clips for low-SNR verification."
    )
    parser.add_argument("-i", "--input-path", required=True, help="Source media file path")
    parser.add_argument("-o", "--output-dir", default=".", help="Directory to write extracted .wav clips")
    parser.add_argument(
        "-w",
        "--windows",
        nargs="+",
        required=True,
        help="One or more time windows, e.g. 00:01:40-00:02:20 28:30-29:05",
    )
    parser.add_argument(
        "--split-channels",
        action="store_true",
        help="Split stereo inputs into separate _L.wav and _R.wav tracks",
    )
    args = parser.parse_args()

    ffmpeg_bin = require_binary("ffmpeg")
    ffprobe_bin = require_binary("ffprobe")

    input_path = Path(args.input_path).expanduser()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    resolved_input = input_path.resolve()

    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    split_channels = args.split_channels
    if split_channels:
        ch_res = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=channels",
                "-of",
                "default=nw=1:nk=1",
                str(resolved_input),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        ch_raw = ch_res.stdout.strip()
        channels = int(ch_raw) if ch_raw.isdigit() else 0
        if channels < 2:
            print(
                f"Warning: --split-channels requested, but input has {channels} audio channel(s). "
                "Extracting single mixed clips instead.",
                file=sys.stderr,
            )
            split_channels = False

    windows = parse_windows(args.windows)
    for idx, (start, end) in enumerate(windows, start=1):
        tag_start = re.sub(r"[:.]", "", start)
        tag_end = re.sub(r"[:.]", "", end)
        stem = f"w{idx:02d}_{tag_start}_{tag_end}"
        if split_channels:
            extract_clip(ffmpeg_bin, resolved_input, start, end, f"pan=mono|c0=c0,{BASE_FILTER}", out_dir / f"{stem}_L.wav")
            extract_clip(ffmpeg_bin, resolved_input, start, end, f"pan=mono|c0=c1,{BASE_FILTER}", out_dir / f"{stem}_R.wav")
        else:
            extract_clip(ffmpeg_bin, resolved_input, start, end, BASE_FILTER, out_dir / f"{stem}.wav")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
