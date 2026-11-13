---
status: draft
last_verified: 2026-11-10
key_files:
- backend/shared/python_utils/slides_markup.py
- backend/apps/slides/app.yml
- backend/apps/ai/utils/slides_fences.py
- backend/core/api/app/services/slides_embed_service.py
- backend/tests/test_slides_markup.py
- backend/tests/test_slides_stream_consumer.py
---

# Slides markup format

Plan: `docs/plans/slides-core/plan.yml`; Specification: `specifications/features/slides/`.
The assistant writes a deck in one ```` ```slides ```` fence. `stream_consumer.py` defers the
fence until it closes, `normalise_slides_markup` validates and re-serialises it, and
`EmbedService.create_deck_embed` stores a `deck` embed (app `slides`, frontend type
`slides-deck`, `diff_editable`). Stored fields: `slides_markup` (normalised string), `title`,
`slide_count`, `aspect`. Follow-up edits use `diff:<embed_ref>`; the patch applies to
`slides_markup` and the result is normalised again (invalid result -> "Suggested Changes" card).

## Grammar

```slides
<deck title="Q3 results" aspect="16:9" template="builtin:plain">
  <slide id="s1" layout="title-and-content" transition="fade">
    <text id="e1" x="80" y="60" w="1200" h="120" role="title">Q3 <b>results</b></text>
    <image id="e2" x="1000" y="220" w="800" h="500" src="embed:revenue-chart" alt="Revenue chart"/>
    <video id="e3" x="80" y="220" w="860" h="484" src="youtube:abc123"/>
    <shape id="e4" x="0" y="1000" w="1920" h="80" kind="rect" fill="accent"/>
    <notepad id="e5" x="80" y="740" w="860" h="260" title="Ideas"/>
    <todo id="e6" x="1000" y="760" w="800" h="240" title="Next"><item done="false">Book venue</item></todo>
    <link id="e7" href="https://example.com">Source</link>
    <block id="e8" x="1000" y="760" w="800" h="240"><!-- verbatim --></block>
    <notes>Speaker notes.</notes>
  </slide>
</deck>
```

- `deck`: `title` (max 200), `aspect` 16:9 (default) | 16:10 | 4:3 (canvas 1920 wide, height 1080/1200/1440),
  `template` `builtin:<name>` or `library:<ref>` (default `builtin:plain`). At least one `slide`; a deck
  without a `<deck>` wrapper but with slides is accepted. Limits: 200 slides, 200 elements per slide, 1 MB.
- `slide`: `id`, `layout` (template layout name), `transition` none | fade | slide.
- Common element attributes: `id`, `x`, `y`, `w`, `h` (integers in canvas units, clamped into the canvas;
  may be omitted when the layout positions the element), `animate` fade | slide-in | appear, `step` 0-99.
- `text`: `role` title | subtitle | body | caption | quote, `font` (`heading`, `body` or a safe font name:
  Arial, Helvetica, Georgia, Times New Roman, Courier New, Verdana, Trebuchet MS, system-ui, serif,
  sans-serif, monospace), `size` 8-400, `color` (token background | foreground | accent | accent-2 | muted |
  surface, or `#hex`), `align`, `weight`. Content: plain text plus `b i u s br ul ol li`.
- `image`: `src="embed:<ref>"` only, `alt`, `fit` cover | contain. Anything else drops the element.
- `video`: `src` `embed:<ref>` | `youtube:<id>` | `vimeo:<id>`. Any other https address becomes
  `<link href=...>`; other values drop the element.
- `shape`: `kind` rect | ellipse | line | triangle, `fill`, `stroke`. `notepad`/`todo`: `title`; todo holds `item done="true|false"`.
- `link`: `href` https only; label is plain text. `notes`: plain text, once per slide.
- `block`: free HTML/CSS/JS, kept byte-for-byte up to the first `</block>`, never interpreted by the
  backend, only rendered in the isolated sandbox. Unterminated blocks are dropped.

## Normalisation

Parsed with the stdlib HTML tokenizer (no regex stripping). Outside `block`: script, style, iframe, object
and other dangerous elements are removed with their content; other unknown elements are unwrapped (their
known children are kept); unknown attributes, every `on*` attribute and every URL other than the https
`link href` are dropped; invalid attribute values are dropped. Output is one element per line with a stable
attribute order (`id`, `x y w h`, element attributes, `animate step`). Missing slide ids become `s<n>`, element
ids `e<n>` (existing valid ids are kept and never reused), so unified diffs stay small and elements are
addressable. Normalising normalised markup returns it unchanged.
