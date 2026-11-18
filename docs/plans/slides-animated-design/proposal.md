# Slides: complex, beautiful, animated backgrounds - research and design proposal

Caveat: competitor facts come from WebSearch result snippets (official help pages where listed); I did not open every page. Items marked (unverified) are third-party or vendor claims.

## 1. Competitor findings

| Tool | Backgrounds / layers | Animated backgrounds | Element animation and timing | Morph-like | Theme / AI | Reduced motion |
|---|---|---|---|---|---|---|
| PowerPoint | Slide background fill (solid/gradient/picture/pattern), master-level backgrounds, shapes with transparency, layered by z-order | Looping video background, animated GIF, 3D models; no native SVG animation | Animation Pane: Start = On Click / With Previous / After Previous, Duration, Delay, Repeat; entrance/emphasis/exit; motion paths | Morph: objects on two consecutive slides are matched, `!!Name` prefix forces matching; text/shape/picture/SVG interpolate | Designer ("Design Ideas") proposes layouts; Copilot generates a deck, picks a theme, "try a new design" re-themes the whole deck | OS setting reduces some effects (not found in sources) |
| Keynote | Slide background fill (color, gradient, image); object fills; masters | Video/movie background, imported animated media | Builds: build in / build out / action; Start = On Tap / With Previous / After Previous / After Transition; Delay; reorder in Build Order | Magic Move: duplicate slide, change objects, shared objects animate; options Duration, Acceleration, Fade Unmatched Objects; not for tables, charts, movies | Themes + master slides | not covered |
| Canva | Background colour/image/video, layered elements with transparency, effects | Video backgrounds, GIF, Lottie (vendor claim), animated stickers; export as video/GIF | Per-element intro/outro presets with speed or exact duration; "Show element timing" timeline; "Appear on click" with Click order; limits ~10 s per animation, ~50 per design (unverified) | "Magic Animate"/smart transitions across pages (not verified) | Magic Design generates layouts from content; Brand Kit (colours, fonts, logos) | Canva states Reduce Motion removes transitions, background animations, masks, overlays |
| Gamma | Theme-level page backgrounds and gradients on cards (changelog: gradients in theme palette); card-level images are treated as disposable during regeneration | "AI animations" image source (paid plans); card block animations fade/slide/scale (unverified) | Few controls: block entrance presets per card | none found | Whole deck generated from a prompt; custom themes (palette, fonts, logo, AI image style prompts); layouts chosen automatically | not covered |
| Pitch | Backgrounds, shapes, GIF/video/3D/prototype embeds | Embedded video/GIF | Enter/exit animations, a transition that moves blocks between slides | Move-between-slides transition (G2 listing, unverified) | Brand assets, custom fonts, team templates, slide styles saved for reuse | not covered |

Sources:
- PowerPoint Morph: https://support.microsoft.com/en-us/office/bc7f48ff-f152-4ee8-9081-d3121788024f , https://office-watch.com/2023/selective-morph-transitions-in-powerpoint/ , https://insider.microsoft365.com/de-de/blog/morph-improvements-more-control-over-which-objects-morph-insider-on-windows-and-insider-fast-on-mac
- PowerPoint timing: https://support.microsoft.com/en-us/PowerPoint/set-the-start-time-and-speed-of-an-animation-effect , https://support.office.com/article/305a1c94-83b1-4778-8df5-fcf7a9b7b7c6
- Copilot/Designer: https://support.microsoft.com/topic/3222ee03-f5a4-4d27-8642-9c387ab4854d , https://support.microsoft.com/en-au/office/making-your-presentations-look-great-with-copilot-in-powerpoint-c8bc6df5-37ed-4398-8b90-f78a8fdcf9bb
- Keynote Magic Move: https://help.apple.com/keynote/mac/6.6/en.lproj/tan2bdb4d136.html ; builds/order: https://support.apple.com/guide/keynote-iphone/tan3ad5f8d82/ios
- Canva: https://www.canva.com/help/article/animate-designs/ , https://lottiefiles.com/blog/tips-and-tutorials/animation-lottiefiles-canva
- Gamma: https://ideas.gamma.app/changelog , https://ideas.gamma.app/ideas/p/feature-request-turn-ai-generated-graphics-directly-into-reusable-themes-or-temp
- Pitch: https://pitch.com/product , https://pitch.com/teams/design

Patterns worth copying:
1. Three start triggers (on click / with previous / after previous) plus delay and duration; one ordered list per slide. All three desktop tools use exactly this model.
2. Morph works by identity: same name on two slides = one object that interpolates. Cheap to implement with our existing element `id`s.
3. Backgrounds are a slide/theme property separate from content, so edits to text never disturb them (Gamma's card-image problem shows what goes wrong otherwise).
4. AI quality comes from a constrained vocabulary (themes, layouts) plus automatic restyling, not from free drawing.
5. Reduced motion: Canva removes background animation as well, not only transitions.

## 2. Our current state

Spec feature.slides v2 (draft), slides.animations.preset-set: elements fade in, slide in or appear on click as ordered build steps; transitions from a fixed set; no animation under reduced motion; "more elaborate motion only inside an interactive block". slides.security.host-rendered-and-isolated: host draws validated properties only; unknown elements and properties discarded. slides.media.images-from-files-and-embeds: SVGs shown as images (inert).

Code (`slidesMarkup.ts`): elements text/image/video/shape/notepad/todo/link/block; shape kinds rect/ellipse/line/triangle; `ANIMATIONS = fade|slide-in|appear`, `step="n"`; `TRANSITIONS = none|fade|slide`; theme = 6 colour tokens + heading/body safe fonts; `svg` is in `DANGEROUS_TAGS` and dropped. Ids are `^[a-z][a-z0-9-]{0,31}$`. `SlideCanvas.svelte`: CSS keyframes (0.5 s, fixed), `@media (prefers-reduced-motion: reduce)` sets `animation: none`; slide background is only `--slide-color-background`; "decoration" of built-in templates is internal to templates. Assistant instructions (`backend/apps/slides/app.yml` lines ~90-110, plus focus modes design-template and plan-presentation SKILL.md): absolute x/y/w/h, tokens, `animate=` + `step=`, use `<block>` for anything else, images only from embed refs.

Gaps for "complex and beautiful":
- No slide or theme background beyond a flat colour: no gradient, image layer, overlay, blend or opacity. No z-order control beyond document order, no element opacity/rotation/blur/blend.
- No vector art the assistant can write inline. Today it must generate an SVG embed (static, inert) or use a `<block>` (isolated HTML, not editable by hand, not exportable, state lost, a heavy sandbox per decorative background).
- Motion: 3 presets, fixed 0.5 s, no delay/duration/easing/trigger (every `step` is click), no exit/emphasis, no looping, no motion path, no cross-slide morph.
- Templates carry decoration only internally; a deck copies only colours and fonts when a template is applied, so decorative looks do not travel with the theme.
- Manual editing: toolbar edits text, position, colour; nothing for backgrounds or animation timing.
- Export: PowerPoint maps preset transitions; PDF static.

## 3. Proposed design

Principle: keep the host-rendered, validated-property model. Add two declarative primitives (layered backgrounds, sanitized vector art with declarative animation) and a richer but still preset-based motion model. No new execution surface.

### 3.1 Layered `<background>` (slide and theme level)
```
<theme ... >
  <background preset="aurora"/>            <!-- theme default for every slide -->
</theme>
<slide layout="title">
  <background>
    <layer kind="gradient" type="linear" angle="135" stops="background 0, accent 60, accent-2 100"/>
    <layer kind="image" src="embed:img1" fit="cover" opacity="0.35" blend="multiply" blur="8"/>
    <layer kind="svg" id="bg-waves" motion="drift"> ...sanitized svg... </layer>
    <layer kind="overlay" color="background" opacity="0.4"/>
  </background>
```
- Layers draw bottom to top, behind all elements, max 8 per slide. kinds: color, gradient (linear/radial/conic, up to 6 stops, tokens or hex), image (embed ref only), svg, overlay. Properties: opacity 0-1, blend from {normal, multiply, screen, overlay, soft-light}, blur 0-40 (px at 1920 wide).
- A slide `<background>` replaces the theme background; `<background inherit="theme">` plus extra layers stacks on top. Themes therefore give one consistent look; slides can vary.
- Theme `preset` = named, built-in, token-driven backgrounds (aurora, mesh-glow, waves, grid-dots, bokeh, paper-grain, spotlight), each a hand-built layer stack using only theme tokens so it recolours with the theme and always has safe contrast. Applying a template carries its background with the theme (fixes the current "decoration does not travel" gap).
- Contrast guard: renderer computes luminance of the foreground token against an estimated background mean (gradient stops / a configurable `scrim`) and, if below 4.5:1, applies an automatic overlay layer for text elements (a soft scrim). Presets declare their own scrim.

### 3.2 Sanitized animated SVG (`<svg>` as layer and as element)
- New element `<vector id=".." x y w h animate=...>` containing `<svg>`, plus `kind="svg"` layers. The parser stops dropping `svg` globally: it is allowed only as the child of `<layer>`/`<vector>`, parsed with DOMParser into a whitelist tree and re-serialised (never `innerHTML` of author text), then rendered inline-in-the-host DOM inside a container with `contain: strict` (not as `<img>`, because `<img>` SVG blocks nothing but also cannot be paused or reduced-motion-gated per element; inline lets us pause with `animation-play-state`).
- Allowed tags: svg, g, defs, path, rect, circle, ellipse, line, polyline, polygon, text, tspan, linearGradient, radialGradient, stop, pattern, clipPath, mask, filter with only feGaussianBlur/feColorMatrix/feTurbulence/feDisplacementMap/feBlend/feOffset/feFlood/feComposite/feMerge, use (fragment href `#id` only), symbol, title, desc, animate, animateTransform, animateMotion, mpath, set, style (keyframes only, see below).
- Allowed attributes: geometry and presentation attributes, `id`, `class`, `transform`, `viewBox` (forced), SMIL attributes (attributeName from an allowed list, values, from/to, dur, begin as number/`indefinite`/id.event for ids inside the same svg only, repeatCount, calcMode, keyTimes, keySplines, path). Colours: hex, `currentColor` and `var(--slide-color-<token>)` so art follows the theme.
- Stripped: `script`, `foreignObject`, `iframe`, `image` with non-fragment href, `a`, every `on*` attribute, `style` attributes containing `url(`/`expression`/`@import`/`behavior`, any `href`/`xlink:href` not starting with `#`, any `url(...)` not `url(#id)`, `<set>`/`<animate>` targeting `href`/`xlink:href`/`style` strings that could introduce URLs, `<use>` of external documents, `<style>` with `@import`, `@font-face`, `url()` or selectors escaping the svg subtree (rules are scoped by prefixing a per-layer class). Only `@keyframes` and class rules for allowed properties (transform, opacity, fill, stroke, stroke-dashoffset, stroke-dasharray, filter limited to blur, offset-distance/offset-path) are kept.
- Budgets: 64 KB per svg, 500 nodes, max 20 animated nodes, `dur` clamped to 0.5-120 s, infinite repeats allowed for background layers only, filter region and blur radius capped (cost). Violation: drop the node, keep the rest, show a repair notice in the editor.
- Performance: animation is paused when the slide is not visible, in thumbnails/strip/preview cards (static first frame by `animation-play-state` and SMIL `pauseAnimations()`), and while the editor is dragging.
- Validated once at parse; the sanitizer lives in the Rust core where deck parsing already belongs (per client-core rule) with the TS sanitizer as the shell binding, so web, CLI text rendering and a future Apple renderer agree.

### 3.3 Per-element motion model
Replace `animate` + `step` with (old attributes remain valid and map onto the new ones):
```
<text id="t1" animate="fade|slide-in|appear|zoom|rise|blur-in|wipe|draw" from="left|right|top|bottom"
      emphasis="pulse|float|spin|shimmer" exit="fade|slide-out|zoom-out"
      trigger="click|with-previous|after-previous|after-transition"
      delay="0.3" duration="0.6" easing="ease|ease-out|spring|linear" order="2" loop="false"/>
```
- Defaults: duration 0.5 s, delay 0, trigger `click` when `step>0`, else `after-transition`. delay 0-10 s, duration 0.1-5 s (emphasis loops up to 60 s or infinite for `float`/`pulse`).
- `order` is the explicit sequence (defaults to document order); the editor shows an animation list that reorders it, like PowerPoint's pane and Keynote's build order.
- `draw` animates stroke-dashoffset of `shape kind=line` and svg paths; `<vector animate="draw">` draws all strokes.
- Motion path: `path="M0,0 C..."` (SVG path string, validated) on any element, or `animateMotion` inside svg; no code.
- Stagger helper for assistants: `stagger="0.15"` on a group id-prefix or on `<text role="body">` lists applies incremental delay, avoiding forty hand-written delays.
- Transitions: add `morph`, `push`, `zoom`, `cover`; `duration` attribute.
- Morph: when both consecutive slides contain an element (or svg layer/vector) with the same `id` and kind, `transition="morph"` interpolates x, y, w, h, rotation, opacity, colour (WAAPI/FLIP; text content crossfades if it differs); unmatched elements fade (Keynote "Fade Unmatched Objects" default). Optional `morph="off"` per element. svg vectors with identical path structure interpolate `d` (same command list); otherwise crossfade. Works in presentation, present remote and follow-live because it only needs two consecutive slides' markup.

### 3.4 Reduced motion
Single host function `motionAllowed()` (prefers-reduced-motion plus a per-deck "Play animations" toggle in the viewer). When false: all elements visible at their final state, transitions are instant, `morph` is a cut, SVG background animation is paused at a designed still frame (`<layer still="0.5">` seconds into the animation, else frame 0, never a half-blank state), looping and emphasis stop. Also honours `Save-Data`/low-power: offer pause. Add an always-visible pause control for any layer that loops longer than 5 s (WCAG 2.2.2).

### 3.5 Assistant guidance (so output stays beautiful)
- Teach presets first: "choose `<theme preset=...>` and a background preset; write custom svg only when asked or when it clearly improves the slide." A small library of vetted SVG art motifs (waves, orbits, constellation, grid pulse, blobs, gradient mesh, flowing lines) the assistant instantiates by name with parameters, e.g. `<layer kind="svg" motif="waves" speed="slow" tint="accent"/>`; the host expands the motif. Free-form svg stays allowed.
- Rules in prompt: backgrounds stay low-contrast, max one animated layer per slide, motion slow (dur >= 8 s loops), text always on a scrim; max 3 animation orders per slide; reuse the same ids across slides for morph; use tokens, never hex, in art; keep svg under 4 KB where possible.
- Tooling feedback loop: the deck validator returns "repair notices" (dropped nodes, contrast warning, too many animated layers) in the tool result so the assistant can self-correct in the same turn; the plan-presentation review phase adds a motion/readability check.
- Diff editing: backgrounds and animation attributes are separate nodes, so a text diff never rewrites them; manual values stay preserved (existing rule).
- Template designer focus mode: step "design choice" offers three backgrounds, including one animated, shown in real template card previews.

### 3.6 Manual editing UI
- Toolbar "Background": preset gallery, colour/gradient editor, image layer picker (existing embed picker), opacity/blend/blur sliders, layer list with reorder and visibility, "Apply to all slides" / "Set as theme".
- Element panel "Animate": effect gallery, trigger select, delay/duration sliders, order list, "Preview" button; slide panel "Transition" with morph.
- Animated svg layers are editable as markup only through the assistant (like blocks) but can be recoloured via tokens, paused, replaced, and deleted by hand.
- Preview cards and strips render the still frame.

### 3.7 Export and remote
- PDF: still frame of each background; builds flattened to final state (existing notice extended).
- PowerPoint: gradient and image layers map to slide background plus shapes; trigger/delay/duration map to timing nodes for fade/appear/fly-in/wipe/zoom; morph maps to Morph transition when ids are used as `!!id` names; svg layers are rasterised to PNG (loss notice lists "animated backgrounds become pictures").
- Present remote/follow-live send only slide index and build step (unchanged); the build step now counts `click` triggers only; `with-previous/after-previous` are derived locally and deterministic.
- Text surfaces (CLI/TUI/SDK) ignore backgrounds; they may list "[animated background]".
- Size: 64 KB svg cap keeps decks and shared links small; the media rule "stored as own encrypted item" is not needed for inline vector.
- Imports: PowerPoint import keeps solid/gradient/picture backgrounds and delay/duration; Morph imports as morph when ids match by name.

### 3.8 Rollout order
1. Sanitizer + `<background>` with gradient/image/overlay + theme presets (biggest visual win, no animation risk).
2. Timing model (trigger/delay/duration/order/stagger) with back-compat.
3. Animated svg layers and motifs.
4. Morph and motion paths; editor panels in parallel with each step; export mapping last.

## 4. Proposed spec changes (feature.slides v3, new rule ids with one example each)
- `slides.background.layers`: a slide and the theme can have a layered background (colour, gradient, image from an embed, overlay, sanitized vector) with opacity, blend and blur; the slide's own background replaces or stacks on the theme's; backgrounds sit behind elements and are never changed by text edits.
  Example: Alice asks for a calm launch deck; the assistant sets a theme preset with a soft gradient and a faint image; every slide shows it, and Bob editing the title text leaves it unchanged.
- `slides.background.theme-presets-contrast`: built-in background presets follow theme colour tokens and keep body text readable (automatic scrim when contrast is below 4.5:1).
  Example: Carol switches the template from Calm talk to Bold pitch; the background recolours and the white title stays readable.
- `slides.security.vector-sanitized`: vector art is parsed into an allow-list of shapes, gradients, simple filters and declarative animation (SMIL and keyframes); scripts, event handlers, foreign objects, external references, url() other than local fragments and imports are discarded; size, node and animation budgets apply to decks from the assistant, uploads, imports and shared links.
  Example: A shared deck carries a svg with an onload attribute and a remote image; the deck opens, the art draws without them, and nothing is requested.
- `slides.animations.timing-model`: each element can have an entrance, emphasis and exit effect with trigger (click, with previous, after previous, after transition), delay, duration, easing and explicit order; the editor shows the order list; old preset decks look the same.
  Example: Bob sets bullets to "after previous" with 0.2 s delay; presenting, the three appear in sequence without clicks, and the fourth press moves on.
- `slides.animations.morph-by-id`: a morph transition moves, resizes and recolours elements that share an id on consecutive slides, and fades the rest.
  Example: Alice's circle with id "hero" is small left on slide 2 and large centred on slide 3; moving to slide 3 slides and grows it.
- `slides.animations.reduced-motion-stills`: with reduced motion (or the viewer's pause control) all elements show in final state, transitions are cuts, and looping backgrounds hold a designed still frame; loops longer than five seconds have a visible pause control.
  Example: Carol's device reduces motion; the waves background is still, all bullets are visible, slide changes are cuts.
- `slides.assistant.motion-and-background-guidance`: the assistant prefers presets and vetted motifs, uses theme tokens, at most one animated layer per slide, and corrects repair notices from the deck validator in the same turn.
  Example: "Make it look more dynamic"; the assistant adds a slow animated motif to the title and closing slides only and mentions the validator warning it fixed.
- Amend `slides.animations.preset-set` (replace "more elaborate motion only inside a block"), `slides.security.host-rendered-and-isolated` (vector allow-list), `slides.export.pdf-and-powerpoint-with-loss-notice` (backgrounds, svg to pictures, morph mapping) and `slides.media.images-from-files-and-embeds` (inline vector separate from SVG images, which stay inert).
- `slides.editor.direct-manipulation`: add background and animation panels (mutations become versions).

## 5. Decisions needed from the owner
1. Inline sanitized SVG with SMIL/keyframes vs keeping SVG inert images + presets only. Recommendation: allow inline sanitized SVG (section 3.2) with the budgets and Rust-core sanitizer, plus vetted motifs as the default assistant path; it is what makes "assistant-produced animated backgrounds" possible without blocks, and the allow-list removes script/network risk. Fallback if rejected: motifs only (no free-form svg).
2. Does an animated background play by default in the shared/follow-live and chat card views, or only in fullscreen/presentation? Recommendation: card, strip and thumbnails show the still frame; fullscreen and presenting animate; viewers get a pause toggle (saves battery and satisfies accessibility).
3. PowerPoint export of animated svg backgrounds: picture only (recommended, with loss notice) vs trying to translate SMIL to PowerPoint animation (high cost, partial fidelity).

No decision needed: layer model and limits, timing attributes and defaults, back-compat mapping of `animate/step`, morph-by-id matching, reduced-motion behaviour, contrast scrim, theme presets, editor panels, rollout order, spec rule ids, Rust-core location of the sanitizer.
