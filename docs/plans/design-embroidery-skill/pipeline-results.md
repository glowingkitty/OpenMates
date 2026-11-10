# design.embroidery pipeline results (Lane A)

Measured 2026-11-10 in real E2B sandboxes on template `openmates-embroidery`
(id `lr6es5k6ceqze4lh4tta`, 2 vCPU / 2048 MB, Ink/Stitch 3.3.0, Inkscape 1.2.2,
Debian 12, Python 3.11). Fixtures: `backend/tests/fixtures/embroidery/`.
Pipeline: `backend/apps/design/embroidery_sandbox/`, provider:
`backend/shared/providers/e2b_embroidery.py`.

## Before / after (100 mm wide, normal fabric)

"Before" = the raw SVG handed to Ink/Stitch with only its canvas sized to 100 mm
(no preparation). "After" = the full pipeline. Stitches / thread changes /
jumps (travel over 3 mm). Seconds = Ink/Stitch time (all five machine formats,
thread list and realistic render in one launch).

| Fixture | Before: stitches / changes / jumps / s | After: stitches / changes / jumps / s | Notes |
|---|---|---|---|
| 01 single shape | 2678 / 0 / 0 / 5.4 | 8644 / 0 / 0 / 11.9 | Before was 48.8 mm wide (canvas, not content); after scales the content to 100 mm |
| 02 overlapping fills | 11132 / 2 / 0 / 11.7 | 11229 / 2 / 0 / 13.3 | Hidden parts cut; same stitches although the lower shapes are now smaller because underlay is added |
| 03 stars + background | 22234 / 26 / 0 / 21.8 | 7072 / 7 / 18 / 10.5 | Background left out; 25 to 7 thread changes; jumps are trimmed (18 trims) |
| 04 lines | 363 / 5 / 0 / 3.0 | 2181 / 5 / 0 / 4.5 | Lines of 1 mm and more became satin, thinner ones running/bean stitch |
| 05 logo | 5724 / 3 / 4 / 6.9 | 6817 / 2 / 5 / 9.6 | 3 to 2 thread changes, satin ring |
| 06 illustration (16 colours) | 29738 / 52 / 5 / 29.2 | 13904 / 15 / 41 / 20.6 | Background dropped, 33 overlaps cut, 51 to 15 changes; finding more_than_12_colours |
| 07 findings | not run | 11708 / 1 / 0 / 11.7 | Gradient flattened to its average colour, text/image/filter left out with notes |
| 08 background only | not run | `nothing_to_sew` in 0.3 s | "Nothing to sew after leaving out the background." |

The "after" jumps are intentional colour-block travel: each one ends in a trim
(`trim_after` when the next same-colour shape is more than 5 mm away).

Seconds per stage (after, warm sandbox): check 0.00, prepare 0.05-0.20,
Ink/Stitch 4.5-20.6, stitch report 0.005-0.04, WebP preview 0.16-0.39. The
first Ink/Stitch launch in a fresh sandbox costs about 6-8 s extra
(01 above: 11.9 s against about 5 s once warm).

Other sizes and fabrics:

| Case | Result |
|---|---|
| 05 logo, light / stretchy | 5903 / 9231 stitches (normal 6817) |
| 02, stretchy | 15272 stitches |
| 03, 120 mm, stretchy, hoop 100x100 | 12653 stitches, 7 changes, 20.3 s; note does_not_fit_hoop, fits_hoop "no" |
| 03, 400 mm | 71822 stitches, 83.8 s Ink/Stitch |
| 06, 400 mm | `too_many_stitches` before Ink/Stitch starts (sandbox 7.0 s incl. check). Before the throughput rule it ran into the 180 s timeout |
| 05 logo, 40 mm | finding detail_below_1mm; pupils left out as tiny details |

## Provider timings (real E2B)

- Template build: 45-87 s.
- Sandbox create 1.0-1.7 s; provider enter (key, create, upload of the pipeline) 2.3-3.4 s.
- Logo with check then convert: enter 3.1 s, check 2.1 s, convert 10 s, sandbox total 15 s.
- Background warm-up (one tiny DST export started during the upload), three runs
  each of 05 logo at 90 mm: sandbox_seconds 20.4 / 14.4 / 15.4 with warm-up against
  18.7 / 17.9 / 16.2 without. That is about 1-3 s saved, so it stays. The template's
  start-command warm-up keeps Ink/Stitch's caches but does not remove the cold
  first-launch cost.

## Decisions

- **Sandbox during rework**: when the check needs a model rework, the check session is closed before the model call and a second session converts; E2B billed 65 s (2 started minutes) for a 40 s idle rework, about 25 s expected. Without rework one session does both.
- **Overlaps**: a lower fill keeps only the part not covered by fills or satin
  above it, minus a 0.4 mm strip (`OVERLAP_MM`) that stays under the upper
  shape's edge, so fabric pull cannot open gaps. Fills also use Ink/Stitch
  `expand_mm` (0.1/0.2/0.3 mm by fabric). Running lines are clipped but never
  hide what lies below. The 02 crop at 300 dpi showed no gaps.
- **Pull compensation**: fill `pull_compensation_mm` made Ink/Stitch about 9x
  slower (43 s instead of 5 s for one heart), so fills use `expand_mm`. Satins
  keep `pull_compensation_mm` (cheap there).
- **Fill angle**: each fill's rows follow its long axis (rounded to 15 degrees),
  then the first of +0/+45/-45/+90 that differs by at least 30 degrees from
  touching fills of other colours.
- **Colour grouping**: greedy over colour blocks with stacking dependencies:
  prefer the kind order fill, satin, running; a colour that can be finished now;
  then the longest available run. Touching fills of one colour in one block are
  merged into one element.
- **Lines**: stroke width of at least 1 mm becomes satin (`satin_column`, centre-walk underlay under
  2 mm, contour, plus zigzag from 4 mm or on stretchy, split above 7 mm);
  thinner lines become running stitch (bean stitch from 0.6 mm).
- **Fabric presets** (row spacing, satin zigzag spacing / pull compensation):
  light 0.35 mm, 0.45/0.15; normal 0.30 mm, 0.40/0.25; stretchy 0.27 mm,
  0.36/0.35, with a second crossed fill underlay.
- **Preview**: Ink/Stitch's realistic render (via Inkscape) at about 1200 px on the
  longest side (dpi 30-600), composited on fabric colour `#f4f1ea` and saved as WebP quality 72. Cost: about
  3.7 s at 150 dpi, 4.8 s at 300 dpi, so no Pillow fallback was needed.
  Product previews are 56-272 KB; the copies here are re-encoded at 900 px.
- **Estimated minutes**: ceil(stitches / 600 + thread changes x 1), minimum 1.
- **Early abort**: stitch estimate = fill area x 0.41 / row spacing (x 1.4 on
  stretchy) + satin length / 0.4 x 2.6 + running length / 2 x 3 + 100 per element,
  within about 10 % of the real counts. Over 150,000, or more than fits into the
  time left at 700 stitches/s (after 10 s fixed cost), fails as
  `too_many_stitches` before Ink/Stitch starts. The pipeline stops itself 5 s
  before the provider's 180 s hard kill so it can still report `timeout`.

## Previews

`previews/after-01_single_shape.webp` ... `previews/after-07_findings.webp`, plus
`previews/before-03_stars_background.webp` and
`previews/before-06_illustration.webp` for comparison (background sewn,
stars sewn twice over it, 26/52 thread changes).
