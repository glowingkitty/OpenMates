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
- **Light threads in the preview**: Ink/Stitch renders thread colours with an HLS
  lightness above 0.85 darker and more saturated (measured: cream `#fdf0e0` came
  out as `#e7cb70`, white as `#c5c5c5`; page colour and thread palette make no
  difference). `preview.py` marks the area of each light thread from the stitch
  data and repaints it with the real thread colour, keeping the render's shading
  (measured after: `#fdf0e0` area mean `#ede1d2`). Other threads are untouched.
- **Estimated minutes**: ceil(stitches / 480 + thread changes x 1), minimum 1; per thread ceil(stitches / 480).
  480 stitches per minute comes from one home machine's own reading of a real 47,067-stitch design
  (99 min; per thread 30 / 44 / 20 / 5 min, ours 30 / 46 / 19 / 5). Rough by intent, not tuned per machine.
- **Estimated thread** (`thread_length_m`, per thread and total): sewn path with the needle down plus 1 mm per
  stitch, in metres with one decimal; bobbin thread not included. The card shows size, time and thread length
  instead of the stitch count.
- **Early abort**: stitch estimate = fill area x 0.36 / row spacing (x 1.4 on
  stretchy) + fill outline length (outer and hole outlines) x 3.09 + 2.2 per
  separate fill part + satin length x 6.4 + running length x 0.97 + 8 per line,
  within 3.1 % of the real counts on 17 measured conversions (see below). Over 150,000, or more than fits into the
  time left at 700 stitches/s (after 10 s fixed cost), fails as
  `too_many_stitches` before Ink/Stitch starts. The pipeline stops itself 5 s
  before the provider's 180 s hard kill so it can still report `timeout`.

## Previews

`previews/after-01_single_shape.webp` ... `previews/after-07_findings.webp`, plus
`previews/before-03_stars_background.webp` and
`previews/before-06_illustration.webp` for comparison (background sewn,
stars sewn twice over it, 26/52 thread changes).

## Sew-on border

Assertion `design-embroidery.prepare.sew-on-border`; code in
`embroidery_sandbox/border.py`. Measured 2026-11-10 in real E2B sandboxes
(template `openmates-embroidery`) with the worktree pipeline, 120 mm wide, normal
fabric. Motifs: an orange flame ornament with sharp spikes, four curls whose
inner openings are 4.0 / 5.2 / 7.2 / 9.6 mm wide and 40 dark spots each holding a
magenta spot; the simple fox head (orange, cream muzzle, near-black ears, eyes
and nose); two islands 4 mm apart with a satin wave, a running zigzag, a satin
ring and a running line.

Geometry: silhouette = union of fills, satin bands (with caps) and running lines
widened to 0.3 mm each side. Outline = silhouette grown by `border_mm` with round
joins; this equals a morphological closing (grow then shrink by `b`) followed by
the growth, so every gap or opening narrower than `2 b` is filled and a wider one
keeps an opening `2 b` narrower. Slits under 1 mm left by the growth are closed.
Border fill = outline minus the silhouette shrunk by 0.45 mm, so it covers the
band, the filled gaps and a 0.45 mm strip under the design's edge, never the
whole design. It is sewn first; design shapes in the border colour that can be
sewn at once follow without a thread change. Band width measured from the
outer edge of the border to the design in the prepared SVG.

| Motif | Border | Sewn size mm | Stitches (estimate) | Threads in sewing order (stitches) | Pipeline s / sandbox s | Band width min / median / max mm |
|---|---|---|---|---|---|---|
| Flame | none | 120.2 x 219.8 | 28750 (27663) | orange 21548, dark 5354, magenta 1848 | 41.8 / 48.4 | - |
| Flame | 3 mm black | 126.2 x 226.0 | 38966 (37218) | black 10316, orange 21163, dark 5460, magenta 2027 | 60.9 / 66.5 | 2.99 / 3.00 / 3.25 |
| Flame | 6 mm `#1d3557` | 132.2 x 231.8 | 40794 (39675) | navy 12376, orange 21023, dark 5397, magenta 1998 | 67.5 / 75.0 | 5.98 / 6.00 / 6.14 |
| Fox | none | 120.0 x 134.2 | 15049 (12872) | orange 10580, cream 2552, near-black `#111111` 1917 | 12.9 / 19.9 | - |
| Fox | 3 mm black | 126.2 x 140.2 | 19539 (17355) | black 4468, orange 10593, cream 2561, near-black `#111111` 1917 | 18.9 / 25.1 | 2.99 / 3.00 / 3.04 |
| Islands | none | 120.0 x 58.4 | 9191 (8862) | blue, teal, yellow, red, white, black (6 threads) | 8.7 / 13.8 | - |
| Islands | 3 mm black | 126.4 x 64.2 | 13188 (12636) | black 3652 first, then the same 6 threads | 13.1 / 20.5 | 2.99 / 3.00 / 3.25 |

Sandbox seconds of the bordered runs include about 1 s of measuring. Maximum
band widths above `b` are the filled concave corners (flame spikes, the gap
between the islands).

Checked in the previews: with 3 mm the flame's 4.0 and 5.2 mm curl openings are
filled, the 7.2 and 9.6 mm ones stay open (narrowed by 6 mm); with 6 mm all four
are filled. The 4 mm gap between the islands is filled, giving one border. No
fabric shows between border and design; the border is sewn under the design only
in the 0.45 mm strip (plus 2.5 mm² at the flame's spike tips, which are thinner
than the strip). Width and height grow by `2 b` within 0.2 mm.

Stitch estimate: the first estimate counted only the fill area (with an extra
factor for the border band) and was 33-52 % low on a spotted ornament with 68
small islands, because short rows, edge runs and travel grow with the outline,
not the area. The estimate now counts area and outline length (formula under
"Early abort"). Measured against real conversions:

| Design | Sewn size mm | Real stitches | Estimate | Error | Old estimate |
| --- | --- | --- | --- | --- | --- |
| 01_single_shape, 100 mm | 100.4 x 92.6 | 8,644 | 8,722 | +0.9 % | +2.8 % |
| 02_overlapping_fills, 100 mm | 100.4 x 87.8 | 11,229 | 11,145 | -0.7 % | -10.1 % |
| 03_stars_background, 100 mm | 100.4 x 99.8 | 7,072 | 6,885 | -2.6 % | -2.9 % |
| 03_stars_background, border 3 | 106.4 x 106.0 | 16,228 | 16,011 | -1.3 % | -0.7 % |
| 05_logo, 100 mm | 100.4 x 100.4 | 6,817 | 6,852 | +0.5 % | -7.7 % |
| 06_illustration, 100 mm | 100.4 x 90.8 | 13,904 | 13,493 | -3.0 % | -0.2 % |
| 06_illustration, 200 mm | 200.4 x 181.4 | 40,497 | 39,966 | -1.3 % | -8.1 % |
| fox, 120 mm | 120.0 x 134.2 | 15,049 | 15,114 | +0.4 % | -14.5 % |
| fox, border 3 | 126.2 x 140.2 | 19,539 | 19,903 | +1.9 % | -11.2 % |
| islands, 120 mm | 120.0 x 58.4 | 9,191 | 9,418 | +2.5 % | -3.6 % |
| islands, border 3 | 126.4 x 64.2 | 13,188 | 13,329 | +1.1 % | -4.2 % |
| flame, 120 mm | 120.2 x 219.8 | 28,750 | 28,055 | -2.4 % | -3.8 % |
| flame, border 3 | 126.2 x 226.0 | 38,966 | 38,023 | -2.4 % | -4.5 % |
| flame, border 6 | 132.2 x 231.8 | 40,794 | 40,656 | -0.3 % | -2.7 % |
| spotted ornament, 90 mm | 90.0 x 170.8 | 14,887 | 14,420 | -3.1 % | -52.5 % |
| spotted ornament, border 3 | 96.0 x 176.8 | 22,862 | 22,808 | -0.2 % | -33.3 % |
| spotted ornament, fit 200x300, border 3 | 159.8 x 298.4 | 47,067 | 46,855 | -0.5 % | -28.4 % |

The estimates are the fitted formula applied to the measured shapes. Ink/Stitch
speed varies far more than the stitch count: 171 stitches/s (stars with border)
to 1,364 stitches/s; the hoop-filling spotted ornament needed 125 s of Ink/Stitch
and 150 s of sandbox time, close to the 180 s limit that applied then; the limit is now 600 s.

Fill the hoop (`fit_hoop`, assertion `design-embroidery.prepare.fill-the-hoop`):
the design is prepared once to learn its proportions, then sized so the design
plus border fills the hoop minus 1 mm on every side (turned by 90 degrees when
that is larger). The spotted ornament in the 200x300 hoop with a 3 mm border
sews at 159.8 x 298.4 mm, border band 2.99-3.37 mm (median 3.00).

Transparent preview (`preview_transparent`, PNG, longest side capped at 1600 px;
the render itself is about 1200 px): Ink/Stitch renders on an opaque page in the
page colour whatever `inkscape:pageopacity` says (tested 0 and no named view:
both opaque). The PNG therefore keeps the area covered by stitches (from the
stitch data, shrunk by 1 px) fully opaque, gives edge pixels an opacity from
their distance to the page colour (6 = page, 48 = thread) and takes the page
colour back out of soft edge pixels; nothing outside the stitch area (grown by 1
px) is kept. Light threads are corrected as in the WebP preview. Measured: 37-46 %
of the pixels fully transparent, below 0.2 % partly transparent, no page halo on
a blue background.
