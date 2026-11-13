# images.modify engine: real runs on dev

Plan: `docs/plans/images-modify-skill/plan.yml` (required check "Real sandbox runs against the
built template for at least five cases"). Run on 2026-11-10 inside the dev `api` container
with the worktree modules (`modify_author.py`, `modify_program.py`, `modify_review.py`,
`e2b_image_edit.py`) loaded from the worktree. Every case ran end to end through
`author_modification` with the real author model, the real sandbox template and, when
requirements were given, the real Jev review.

- Template: `openmates-image-edit` (E2B id `iq1p1d2n1fpvtz1bw548`), built on the dev E2B account
  with `backend/scripts/build_image_edit_template.py --execute` (40 s build; Pillow 11.3.0,
  NumPy 2.2.6, OpenCV 4.12.0, CairoSVG 2.8.2, 290 fonts).
- Author: `openai/gpt-6.1-sol` answered every case (first model in the order); no fallback was needed.
- Inputs: a private outfit photo (1512 x 2016, used only for these runs and not stored in the
  repository), a flame motif screenshot (1170 x 2532, white background, black bars at top and bottom), the
  transparent stitch preview of an embroidery result (1068 x 1185 RGBA), and generated inputs: five
  synthetic photos (1200x800, 800x1200, 1000x1000, 1600x900, 640x480), a coast picture with a
  lighthouse (2400 x 1350) and an SVG logo (240 x 120).
- Result files are local to the dev host under `/tmp/img-modify/results/` (picture and program
  per case); they are not committed.

## Final runs

| # | Case | Rounds (delivered) | Review | Sandbox s per run | Author tokens in/out per call | Jev input tokens | Wall s | Output | File |
|---|------|--------------------|--------|-------------------|-------------------------------|------------------|--------|--------|------|
| 1 | Motif on outfit photo, 3 requirements | 3 (1) | unmet_delivered: "the rest of the photo is unchanged" | 1.51, 0.99, 1.18 | 2708/1896, 4408/1583, 4425/1945 | 1516, 1519, 1516 | 89.2 | 1512x2016 JPEG, 859 KB | case1-motif-on-outfit.jpg |
| 2 | Collage of five, 1 requirement | 1 (1) | accepted | 1.34 | 5275/880 | 2396 | 27.4 | 3172x1248 PNG, 2.1 MB | case2-collage-of-five.png |
| 3 | Crop to square around subject, warmer, more contrast | 1 (1) | skipped | 0.70 | 1806/620 | none | 17.7 | 1350x1350 JPEG, 261 KB | case3-crop-and-grade.jpg |
| 4 | SVG logo bottom-right, 15 degrees, 20 % width | 1 (1) | skipped | 0.93 | 2470/244 | none | 13.6 | 2400x1350 JPEG, 407 KB | case4-logo-on-photo.jpg |
| 5 | Injected crashing first program, then real correction | 2 (2) | skipped | 0.77, 0.64 | 0/0 (injected), 1924/74 | none | 10.9 | 1200x1350 PNG, 956 KB | case5-forced-crash.png |
| 6 | Follow-up change of case 1's program ("a bit higher, 20 % smaller") | 1 (1) | skipped | 1.52 | 4046/1429 | none | 19.2 | 1512x2016 JPEG, 852 KB | case6-follow-up-change.jpg |
| 7 | Extra: embroidery stitch preview (RGBA) on outfit photo, 2 requirements | 1 (1) | accepted | 1.36 | 3231/1224 | 1456 | 38.2 | 1512x2016 JPEG, 841 KB | case7-stitch-preview-on-outfit.jpg |

Every sandbox run is far below one minute, so each costs 5 credits (one started minute) plus tokens.

## Findings per case (pictures viewed)

1. **Motif on outfit.** The ornament is cut out of the screenshot with the black bars removed. Enclosed white
   holes are transparent and there is no visible fringe at 3x zoom. It is upright, about a third of the measured
   panel width, and lies on the black panel below the hood. A pixel diff against the original shows changes only
   inside the ornament's box; the mean difference outside it is 0.62, which is JPEG re-encoding. Jev still judged
   "the rest of the photo is unchanged" as not met in all three rounds, because the photo already carries a
   similar print and the new ornament overlaps it. This is a reviewer false negative that cost two extra rounds.
   The delivered picture is the first round's (the earliest picture with the fewest misses).
2. **Collage.** One large picture on the left and a 2x2 grid on the right, with exactly equal white gaps. The
   cell sizes follow the pictures' aspect ratios, so no picture is distorted or cut.
3. **Crop and grade.** A square around the lighthouse, slightly warmer, a little more contrast. Nothing is drawn
   into it.
4. **Logo.** The SVG is rasterised at its final size, so it stays crisp. It is rotated 15 degrees
   counter-clockwise (positive angle), about 20 % of the width, and sits in the bottom-right with a margin. The
   output was byte-identical in all three runs.
5. **Forced failure.** The injected program read `inputs[3]` and raised `IndexError`. The traceback
   (`program.py, line 4`) went back to the author, and the corrected program cropped the right half. The output
   was byte-identical across runs.
6. **Follow-up change.** The author changed only two constants of case 1's program: width 1/3 to 0.8/3 and
   vertical centre 0.575 to 0.55. It then ran again on the original photo and motif. The result has one
   ornament (not two), 0.8x as wide (164 px against 205 px of changed area), moved up, and as sharp as the first.
7. **Stitch preview.** The final run keeps the preview's own transparency, and the fox lies on the back panel.
   An earlier run (before the prompt was tuned) put the fox on an opaque white square. Jev accepted that because
   no requirement covered it.

## What was tuned and why

- **Sandbox start overlaps the first author call.** At first the progress step "writing" started 2-10 s late,
  because the sandbox was created before the first call. The sandbox now also imports the libraries in the
  background, so the first run fell from about 4.6 s to about 1 s.
- **Fringe removal.** After round 1 a thin light outline was visible around the ornament on the dark panel. The
  prompt now asks to un-mix the background colour from semi-transparent pixels and to shrink the alpha by about
  1 px at the final size. No fringe was visible afterwards.
- **Collage layout.** In round 1 the pictures were letterboxed inside equal cells, which left uneven white space.
  The prompt now asks for cell sizes derived from the aspect ratios when every picture must stay whole, so the
  gaps are exactly equal.
- **Existing content and correction drift.** In round 2 the author reacted to Jev's "rest unchanged" verdict by
  painting over the photo's existing print, which left faint ghosts. Three changes followed:
  - the prompt forbids removing or covering existing content unless asked;
  - the correction message says to fix only the named problem and never to edit more of the base to satisfy a
    check;
  - on a tie in the number of unmet requirements, the earlier picture is delivered (it was the later one before).

## Open points

- Jev is unreliable on "unchanged" requirements when the edit overlaps similar existing content. A deterministic
  check of the base picture outside the edited region would be more reliable, but it needs a contract change (not
  in the Specification).
- Only `openai/gpt-6.1-sol` was exercised for real. The fallback models (`anthropic/claude-haiku-5-5`,
  `google/gemini-3.8-flash`) declare image input and use the same `image_url` path, but they were not run.
