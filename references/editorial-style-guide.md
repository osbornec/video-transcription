# Editorial Style & Formatting Guide

Reference specification for generating consistent Markdown and Google Docs transcript deliverables in Stage 5.

---

## 1. Edition Comparison

| Dimension | Verbatim Perfect (`*_Perfect_Transcript.md`) | Companion Clean-Read (`*_Clean_Read_Transcript.md`) | Thematic Clean-Read (`*_Thematic_Clean_Read_Transcript.md`) |
| :--- | :--- | :--- | :--- |
| **Spoken fillers** (*"like"*, *"you know"*, *"um"*) | Keep verbatim | Remove purely filler tics | Remove purely filler tics |
| **False starts & stutters** | Keep verbatim with hyphens (`-`) | Smooth grammar cleanly without altering meaning | Smooth grammar cleanly without altering meaning |
| **Factual claims, numbers, examples** | 100% preserved | 100% preserved | 100% preserved |
| **Speaker voice & humor** | Preserved (`*[chuckles]*`, etc.) | Preserved | Preserved |
| **Timestamps (`[MM:SS]`)** | On every turn & off-mic cue | On every turn | On every turn + section headers |
| **Curated slide assets** *(when Stage 4B is used)* | Clickable links (`[Figure NN](./assets/...)`) only | Inline Markdown images (`![Figure NN](./assets/...)`) + italic captions | Inline Markdown images + italic captions + Google Docs inline embeds |
| **Structure** | Chronological linear transcript | Chronological linear transcript | Table of Contents + numbered `### N. Title` sections + 1-sentence italic takeaways + On-Slide Links & Resources |

---

## 2. Speaker Turn & Annotation Conventions

- **Turn format:** `**[MM:SS] Speaker Name:** Dialogue text...` (colon inside the bold span; `scripts/build_changelog.py` parses this format alongside `**[MM:SS] Speaker**:` and unbolded turns).
- **Single-speaker monologues:** Start a new `**[MM:SS] Speaker Name:**` turn every ~20 to 60 seconds on natural topic shifts so long monologues stay readable and compatible with `build_changelog.py`.
- **Multi-speaker / off-mic interjections:** Inline as `*[Speaker B: "..."]*` or start a dedicated timestamped turn when Speaker B takes the floor.
- **Visual context & non-speech cues:** Wrap brief stage, slide, or avatar transitions in italic brackets:
  `*[00:05] [Title slide displayed: "..."]*`
- **Network packet loss / unrecoverable noise:** Never invent plausible words when audio is distorted or cut out by VoIP jitter. Annotate exact drop intervals transparently:
  `*[heavy packet loss / audio dropouts]* ...word fragment... *[garbled]*`
- **Platform edit / auto-trim splices:** When platforms such as Loom, Descript, or Riverside remove pauses or retakes mid-phrase, mark the cut transparently without mislabeling it as network packet loss:
  `...about who we- *[audio splice]* I think secondly...`

---

## 3. Clean-Read Guardrails

When converting Verbatim Perfect to Clean-Read:
1. **Never replace domain terminology or casual metaphors** with generic corporate synonyms (for example, keep a speaker's exact phrase like *"too many chefs in the kitchen"*).
2. **Never invent intermediate timestamps** mid-monologue unless verified against the media timeline.
3. **Preserve numeric precision** (`15%`, `42 ms`, `$2.5 billion`, `200+`) identically across editions. In Markdown targeting both KaTeX previewers and Google Docs, escape currency `$` as `\$` only when two dollar signs appear in the same paragraph and would otherwise be parsed as inline LaTeX math; verify Google Docs renders plain `$` cleanly after import.

---

## 4. Table of Contents & Heading Slug Rules (`Thematic Clean-Read`)

Google Docs native heading binding (`scripts/fix_gdocs_toc_links.py`) matches ToC `[text](#slug)` links against headings using GitHub-style slug rules:

1. Use sequential numbered `### N. Section Title` headings:
   ```markdown
   ## Table of Contents

   - [1. Architecture Overview](#1-architecture-overview) (*00:00 to 08:15*)
   - [2. Benchmarks and Tradeoffs](#2-benchmarks-and-tradeoffs) (*08:15 to 19:40*)
   ```
2. **Keep heading punctuation simple** (`a-z`, `0-9`, spaces, commas) so GitHub anchors match Google Docs cleanly:
   - `&` and `/` are stripped by GitHub slug rules, turning `"1. I/O & Caching"` into `#1-io--caching` (note the double hyphen `--` between stripped `&`). Prefer plain words (`and`, `or`) in section headings when authoring from scratch.
   - Even if double hyphens occur, `fix_gdocs_toc_links.py` falls back across exact slug, collapsed single-hyphen slug, and leading number (`^(\d+)\.`).
3. Start each section immediately below `### N. Title` with a one-sentence italic executive summary (`*Takeaway: ...*`).
