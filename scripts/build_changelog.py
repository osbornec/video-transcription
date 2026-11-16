"""
Generate a Markdown turn-by-turn Corrections & Verification Changelog comparing
an earlier draft transcript (.docx, .md, or .txt, typically containing [unclear] tags)
against a verified Markdown transcript.

Usage:
    python build_changelog.py --old draft.docx --new verified.md --output Transcript_Corrections_Changelog.md
"""

import argparse
import os
import re


def to_seconds(ts: str) -> int:
    """Convert MM:SS or HH:MM:SS timestamp into total seconds."""
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Unsupported timestamp format: {ts}")


def normalize_speaker(name: str) -> str:
    """Normalize smart apostrophes and whitespace for speaker comparison."""
    return re.sub(r"\s+", " ", name.replace("\u2019", "'").strip())


def load_lines(path: str) -> list[str]:
    """Read non-empty stripped lines/paragraphs from .docx, .md, or .txt."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "python-docx is required to read .docx drafts (pip install python-docx)."
            ) from exc
        doc = docx.Document(path)
        return [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.read().splitlines() if line.strip()]


def parse_turns(lines: list[str]) -> list[dict]:
    """Extract chronological speaker turns from block or inline timestamped lines."""
    turns: list[dict] = []
    block_re = re.compile(r"^(?:\*\*)?\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s+(.+?)(?:\*\*)?$")
    inline_re = re.compile(r"^(?:\*\*)?\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:*]+?)(?::\*\*|\*\*:|:)\s+(.+)$")

    i = 0
    while i < len(lines):
        line = lines[i]
        m_inline = inline_re.match(line)
        if m_inline:
            ts, spk, txt = m_inline.group(1), m_inline.group(2).strip(), m_inline.group(3).strip()
            turns.append({"ts": ts, "sec": to_seconds(ts), "speaker": spk, "text": txt})
            i += 1
            continue

        m_block = block_re.match(line)
        if m_block:
            ts, spk = m_block.group(1), m_block.group(2).strip()
            body_parts: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if inline_re.match(nxt) or block_re.match(nxt) or nxt.startswith("#"):
                    break
                body_parts.append(nxt)
                j += 1
            if body_parts:
                turns.append(
                    {
                        "ts": ts,
                        "sec": to_seconds(ts),
                        "speaker": spk,
                        "text": " ".join(body_parts),
                    }
                )
            i = j
            continue

        i += 1

    return turns


def match_turns(
    old_turns: list[dict], new_turns: list[dict], tolerance_sec: int = 25
) -> list[tuple[dict, dict | None]]:
    """Align each old turn chronologically to its closest verified turn within tolerance."""
    used_new: set[int] = set()
    aligned: list[tuple[dict, dict | None]] = []

    for old in old_turns:
        best_idx = None
        best_dist = tolerance_sec + 1
        for idx, new in enumerate(new_turns):
            if idx in used_new:
                continue
            dist = abs(new["sec"] - old["sec"])
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
            elif new["sec"] - old["sec"] > tolerance_sec:
                break

        if best_idx is not None and best_dist <= tolerance_sec:
            used_new.add(best_idx)
            aligned.append((old, new_turns[best_idx]))
        else:
            aligned.append((old, None))

    return aligned


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Markdown diff changelog for transcript verification.")
    parser.add_argument("--old", required=True, help="Path to original draft (.docx, .md, or .txt)")
    parser.add_argument("--new", required=True, help="Path to verified Markdown transcript (.md)")
    parser.add_argument("--output", required=True, help="Output Markdown changelog path")
    parser.add_argument("--tolerance", type=int, default=25, help="Timestamp match tolerance in seconds (default: 25)")
    args = parser.parse_args()

    old_turns = parse_turns(load_lines(args.old))
    new_turns = parse_turns(load_lines(args.new))

    total_old_unclear = sum(len(re.findall(r"\[unclear\]", t["text"], re.I)) for t in old_turns)
    total_new_unclear = sum(len(re.findall(r"\[unclear\]", t["text"], re.I)) for t in new_turns)

    aligned = match_turns(old_turns, new_turns, tolerance_sec=args.tolerance)
    rows: list[str] = []
    affected_unclear_turns = 0
    speaker_fixes = 0

    for old, new in aligned:
        if old["speaker"].lower() in ("recording note",):
            continue
        has_unclear = "[unclear]" in old["text"].lower()
        if has_unclear:
            affected_unclear_turns += 1

        if new is None:
            if has_unclear:
                old_esc = old["text"].replace("|", "\\|").replace("[unclear]", "**`[unclear]`**")
                rows.append(
                    f"| `[{old['ts']}]` | ~~{old['speaker']}~~ -> *(Merged / restructured)* | {old_esc} | *(Consolidated into adjacent turn)* |"
                )
            continue

        old_spk_norm = normalize_speaker(old["speaker"])
        new_spk_norm = normalize_speaker(new["speaker"])
        spk_changed = old_spk_norm != new_spk_norm
        text_changed = old["text"].strip() != new["text"].strip()

        if spk_changed:
            speaker_fixes += 1

        if has_unclear or spk_changed or text_changed:
            ts_col = f"`[{old['ts']}]`" if old["ts"] == new["ts"] else f"`[{old['ts']}]` -> `[{new['ts']}]`"
            spk_col = f"**{new['speaker']}**" if not spk_changed else f"~~{old['speaker']}~~ -> **{new['speaker']}**"
            old_esc = old["text"].replace("|", "\\|").replace("[unclear]", "**`[unclear]`**")
            new_esc = new["text"].replace("|", "\\|")
            rows.append(f"| {ts_col} | {spk_col} | {old_esc} | {new_esc} |")

    old_name = os.path.basename(args.old)
    new_name = os.path.basename(args.new)
    out_lines = [
        "# Transcript Corrections & Verification Changelog",
        "",
        "## Summary of Improvements",
        f"- **Draft Source:** `{old_name}` ({len(old_turns)} parsed turns)",
        f"- **Verified Transcript:** `{new_name}` ({len(new_turns)} parsed turns)",
        f"- **`[unclear]` Markers Resolved:** **{total_old_unclear - total_new_unclear}** (originally **{total_old_unclear}** across **{affected_unclear_turns}** turns; **{total_new_unclear}** remaining).",
        f"- **Speaker Attribution Fixes:** **{speaker_fixes}** turns updated.",
        f"- **Total Turns Modified:** **{len(rows)}** rows logged below.",
        "",
        "---",
        "",
        "## Complete Turn-by-Turn Diff",
        "",
        f"| Timestamp | Speaker | Original Draft (`{old_name}`) | Verified Transcript (`{new_name}`) |",
        "| :--- | :--- | :--- | :--- |",
        *rows,
        "",
    ]

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))

    print(f"Wrote {args.output} ({len(rows)} diff rows; {total_old_unclear} -> {total_new_unclear} [unclear] markers).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
