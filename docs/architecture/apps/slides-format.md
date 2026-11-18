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

## Themes and templates

Specification: `slides.templates.*`, `slides.focus.*`. A template uses the deck grammar with
`kind="template"`; its slides are the sample slide of each layout.

```slides
<deck title="Club Green" aspect="16:9" template="builtin:plain" kind="template">
  <theme heading="Trebuchet MS" body="Verdana" background="#f4faf5" foreground="#12301c" accent="#1f9d55" accent-2="#f2c94c" muted="#5b7a65" surface="#ffffff"/>
  <slide id="s1" layout="title"> ... </slide>
  <slide id="s2" layout="section"> ... </slide>
  <slide id="s3" layout="content"> ... </slide>
  <slide id="s4" layout="image"> ... </slide>
  <slide id="s5" layout="quote"> ... </slide>
  <slide id="s6" layout="closing"> ... </slide>
</deck>
```

- `deck kind`: `deck` (default, never serialised) | `template`. Serialised order of the deck
  attributes: `title aspect template kind`. A ```` ```slides ```` fence whose normalised root has
  `kind="template"` creates a `template` embed (app `slides`, frontend type `slides-template`,
  same fields as a deck: `slides_markup`, `title`, `slide_count`, `aspect`; `diff_editable`).
- `theme` (at most one; always serialised as the first line inside `deck`, self-closing, two-space
  indent): `heading`, `body` (safe font names, canonical spelling as for `text font`) and the six
  colour tokens `background foreground accent accent-2 muted surface` as `#hex` (3 or 6 digits,
  serialised lower case). Serialised attribute order is exactly that order; missing or invalid
  attributes are dropped; a theme without any valid attribute is dropped. Renderers use a theme
  value when present and fall back to Plain (the app's light/dark design tokens) per token.
- Layouts: `title`, `section`, `content` (alias `title-and-content`), `two-column`, `image`, `quote`,
  `closing`. A template offers at least `title section content image quote closing`. Renderers have
  built-in slot positions for every one of them for elements without `x y w h`.
- Built-in templates: `backend/apps/slides/templates/<id>.slides` (normalised template markup; ids
  `plain`, `bold-pitch`, `clean-business`, `friendly-classroom`, `calm-talk`). The web gets them from
  the generated `frontend/packages/ui/src/components/embeds/slides/slidesBuiltinTemplates.generated.ts`
  (`scripts/generate_slides_builtin_templates.py`, `--check` in pytest). Plain has no theme.
- Built-in shortcut: a fence `<deck kind="template" template="builtin:<id>"></deck>` without slides is
  expanded by the normaliser into that built-in template's markup (how the assistant shows built-in
  template cards without writing them out).
- Built-in decks: when a deck (kind `deck`) references `template="builtin:<id>"` other than `plain`
  and has no `theme`, normalisation inserts that template's theme and, for every slide whose layout
  the template has a sample for, (a) inserts the sample slide's `shape` elements first in paint order
  (decorations) and (b) gives each `text` element without `x y w h` the position, `size`, `align`,
  `weight` and `color` of the sample's text element with the same role and index, where those are
  absent. Because a deck then carries a theme, normalising again changes nothing.
- Library templates: a deck made from or applied with a saved template carries
  `template="library:<template embed id>"` and a copy of its theme. Applying a template (Rust core
  operation `set_theme`) replaces only `template` and `theme`; slides and elements stay unchanged.
- Library: a template embed with the encrypted `saved` flag (Save action) belongs to the library of
  the account (Personal or Team) that owns its chat.
