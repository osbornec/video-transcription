# Slide Capture and Visual Asset Curation Guide

Reference methodology for **Stage 4B (Optional Slide Capture and Visual Curation)** when transcribing slide-heavy talks, technical presentations, webinars, or conference videos.

---

## 1. Two-Tier Video Capture Architecture

Never extract slide images from the compressed `1 FPS` transcription proxy (`work/`). Use a two-tier split:

1. **Full-resolution source (`recordings/`):** Pass `--capture-slides` to `scripts/prepare_compact_video.py` (which downloads `1080p` video plus original non-DRC audio and avoids auto-dubbed tracks when selecting the primary audio stream). Keep the raw source in `recordings/` for all PNG grabs and Stage 4 `.wav` audits.
2. **Compact transcription proxy (`work/`):** `--capture-slides` automatically enables `--screen-share` (`960px`, `CRF 28`, `1 FPS`, `600s` / `15 min` / `25 MB` segments) so Stage 3 transcription stays well inside multimodal context budgets.
3. **Full-resolution OCR accuracy bonus:** Extracting cropped PNGs from the native `1080p` source frequently corrects small-font numbers or axis labels that looked ambiguous in the `960px` proxy.

---

## 2. Broadcast PiP Auto-Crop Detection

Conference recordings often place a 16:9 slide deck inside a fixed picture-in-picture broadcast layout (sponsor logo + speaker camera on the left, black lower-third banner on the bottom).

- Run `scripts/capture_slides.py detect-crop` on 2 to 3 clean light-background slides from the full-res source video to find the exact consensus slide canvas rectangle (`crop=W:H:X:Y`, inset by 1px and rounded to clean even dimensions).
- Apply that single fixed crop uniformly across **every** slide in the deck (including dark or full-bleed slides where edge detection would otherwise fail), while setting `"use_crop": false` on full-screen conference intro/outro bumpers.
- Visually verify the cropped result on a contact sheet or before/after comparison before delivering.

---

## 3. Frame-Selection Rules (Settled and Legible States)

Choose timestamps deliberately so every saved PNG is crisp and legible:

- **Additive multi-step builds:** Capture the **final settled frame** right before the next slide transition so all bullet points, arrows, and callouts are present.
- **Spotlight or dimming builds:** When a slide shows a complete diagram first and then dims 3 to 4 sections while highlighting one layer at a time, capture the **early un-dimmed overview frame** so the entire framework is crisp and readable.
- **Zoom-in reveals:** When a dense chart or taxonomy starts small inside another card and later zooms full-width, capture the **zoomed full-width state**.
- **Sparkle / fade-in animations:** Verify via contact sheet that title or label animations have fully settled (never save mid-fade frames).

---

## 4. Validated Editorial Curation Rubric

Classify every distinct visual state in the presentation into **IN**, **BORDERLINE**, or **OUT**:

| Verdict | What Belongs Here | Examples |
| :--- | :--- | :--- |
| **IN (High Signal)** | Visuals that convey structured information, quantitative data, or architectural relationships prose alone cannot capture cleanly | Bar/line/step/stacked charts, benchmark matrices, system and architecture diagrams, dependency boundaries, incident timelines with code, dense reference taxonomies, progressive framework extensions anchoring distinct chapters (e.g., 2-column intro expanded into a 3-column capstone), high-signal primary-source tweets with concrete quantitative metrics, real-world production evidence screenshots (logs, fuzzing reports, Slack bot output) with data not read aloud |
| **BORDERLINE (Ask in HTML Review)** | Visuals sitting between data and decoration where user preference matters | Visual metaphors with structured labels, dense tool screenshots partially obscured by overlays, fast animated demo stills |
| **OUT (Exclude)** | Decorative, redundant, or text-only slides that add visual clutter without information gain | Conference intro/outro bumpers, title and closing slides (metadata already belongs in document titles and headers), big-font statement or section-divider slides, pure cartoons or memes without data, large atmospheric photos talked over with no data points, incomplete build frames, exact repeat slides (cross-reference the first figure instead), superseded slides (e.g., Tweet #1 already quoted verbatim inside Tweet #2) |

### URL and Resource Harvesting Rule (Critical)

Whenever a slide is dropped (for example, an obscured tool UI screenshot or an animated screen-recording still), **harvest every unique GitHub repository URL, product link, CLI flag, or tool name shown on that slide** into:
1. Inline links in the transcript prose at the relevant timestamp,
2. A consolidated **On-Slide Links and Resources** section at the bottom of the transcript, and
3. The **Harvested On-Slide URLs and Resources** section in `assets/index.md`.

Zero actionable references should be lost when omitting low-signal images.

---

## 5. Interactive HTML HITL Review Checkpoint

Do not ask disconnected point questions in chat about individual slides. Instead, let the human review the **entire deck in chronological context**:

1. Write a JSON manifest covering **all** visual states (IN, BORDERLINE, and OUT) with timestamps, chapter names, spoken quotes, editorial justifications, cross-references, and open questions.
2. Extract candidate PNGs with `scripts/capture_slides.py extract` and build the interactive review page with `scripts/capture_slides.py review-html` (including a before/after auto-crop proof).
3. Present the clickable `file:///` link to `scratch/slide_curation_review.html`. The reviewer can filter by `All / IN / Borderline / OUT / Questions / Overrides`, zoom any slide in a full-res lightbox, toggle **Keep IN / Drop OUT**, add per-slide or rubric notes, and click **Copy HITL Feedback** or **Download JSON** to return their decisions.

---

## 6. Self-Contained Package Layout and Edition Embedding Policy

Organize every video transcription project into a self-contained per-video package folder under `transcripts/`:

```text
transcripts/<Speaker_Or_Org_Slug>/
  <Slug>_Perfect_Transcript.md
  <Slug>_Clean_Read_Transcript.md
  <Slug>_Thematic_Clean_Read_Transcript.md
  <Slug>_Thematic_Clean_Read_Transcript (Google Doc).url
  Transcript_Corrections_Changelog.md        # when auditing an existing draft
  assets/
    index.md                                 # figure catalog + harvested on-slide URLs
    01_00m48s_first_chart_slug.png
    02_01m27s_second_diagram_slug.png
    ...
```

### Per-Edition Integration Rules

- **Verbatim Perfect (`*_Perfect_Transcript.md`):** Keep text-pure for diffing and archival; insert clickable relative links (`[Figure 01: ...](./assets/01_00m48s_....png)`) inside italic visual notes rather than inline image embeds.
- **Clean-Read (`*_Clean_Read_Transcript.md`) & Thematic Clean-Read (`*_Thematic_Clean_Read_Transcript.md`):** Embed approved PNGs inline via relative Markdown (`![Figure 01: ...](./assets/01_00m48s_....png)`) immediately followed by a concise italic caption (`*Figure 01 (`00:48`): ...*`).
- **Google Docs Export:** Pass `--embed-local-images` to `scripts/fix_gdocs_toc_links.py` (`gdocs` backend) to stage unique `[[IMG_EMBED_NN]]` placeholders, upload and embed every local PNG directly in place above its caption, strip the placeholders in one batched `sed` call, bind all ToC `#slug` links to native Google Docs `headingId` targets, and write the `.url` / `.webloc` shortcut into the package folder.

---

## 7. Future Backlog

- **Short video/GIF clip capture for embedded screen-recording demos:** Some technical talks play brief sped-up UI demos (for example, property-based UI fuzzing recordings) where a single static PNG loses the motion. A future iteration can support extracting short looping `.mp4` or `.webp`/`.gif` clips (`-ss START -to END`) into `assets/` alongside PNG figures.
