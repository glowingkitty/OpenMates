# OpenMates Design Guidelines

This file is the agent-facing source of truth for generating OpenMates UI and media designs. Claude Code, Codex, OpenCode, Remotion/video agents, and future design-capable agents should read this before creating or changing visual output.

Use this document to keep new Svelte, React, native app, video, print, social, and marketing designs consistent with the existing OpenMates design language. It describes the current implementation; do not invent a new brand direction unless the user explicitly asks.

## Source Files

Use these files for exact implementation details:

| Area | Source |
|---|---|
| Design token sources | `frontend/packages/ui/src/tokens/sources/*.yml` |
| Generated web tokens | `frontend/packages/ui/src/tokens/generated/theme.generated.css` |
| Global styles | `frontend/packages/ui/src/styles/theme.css` |
| Typography | `frontend/packages/ui/src/styles/fonts.css`, `frontend/packages/ui/src/tokens/sources/typography.yml` |
| Buttons, fields, cards | `frontend/packages/ui/src/styles/buttons.css`, `fields.css`, `cards.css` |
| Settings rules | `docs/design-guide/settings-ui.md`, `frontend/packages/ui/src/components/settings/elements/` |
| Embed base components | `frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte`, `UnifiedEmbedFullscreen.svelte`, `EmbedHeader.svelte`, `BasicInfosBar.svelte`, `EmbedTopBar.svelte` |
| Media generation | `docs/architecture/integrations/media-generation.md` |

When implementation and this document diverge, inspect the source files, update the implementation if needed, and update this file when the reusable visual rule changed.

## Design Personality

OpenMates is a practical, friendly, privacy-aware product UI. It should feel like a modern chat app with helpful digital team mates, not like a dense enterprise dashboard or a generic AI SaaS landing page.

Core traits:

| Trait | Rule |
|---|---|
| Familiar | Reuse chat-app patterns: sidebars, message bubbles, rounded cards, clear action rows. |
| Calm | Prefer soft surfaces, rounded corners, readable spacing, and restrained shadows. |
| Capable | App and embed surfaces can use vivid gradients, animated headers, and rich preview cards. |
| Trustworthy | Prioritize clear hierarchy, accessible focus states, dark-mode correctness, and privacy-safe media handling. |
| Human | Use plain language and friendly rounded UI; avoid overly technical visual metaphors unless the surface is developer-facing. |

## Token System

The token system is the visual source of truth. Do not hardcode reusable colors, spacing, typography, radii, shadows, z-index values, or transitions when a token exists.

Token sources live in `frontend/packages/ui/src/tokens/sources/` and generate CSS, TypeScript, and Swift outputs.

Use token values across media:

| Medium | Token Adaptation |
|---|---|
| Web/Svelte | Use CSS custom properties such as `var(--color-grey-20)`. |
| React | Use the same CSS variables or generated token constants. |
| Native app | Use generated Swift tokens from `frontend/packages/ui/src/tokens/generated/swift/`. |
| Video/Remotion | Use token colors, Lexend typography, rounded panels, app gradients, and motion timings translated into Remotion styles. |
| Print/social | Use token colors, gradients, type hierarchy, and spacing proportions adapted to fixed canvas dimensions. |

## Color

### Neutral System

The grey scale is the primary surface and text system. It is theme-aware and inverts for dark mode.

| Role | Token | Light | Dark |
|---|---|---:|---:|
| Main page/card surface | `--color-grey-0` | `#ffffff` | `#171717` |
| Subtle surface | `--color-grey-10` | `#f9f9f9` | `#1c1c1c` |
| Panel/background surface | `--color-grey-20` | `#f3f3f3` | `#212121` |
| Embed preview surface | `--color-grey-25` | `#e8e8e8` | `#252525` |
| Borders/dividers | `--color-grey-25`, `--color-grey-30` | `#e8e8e8`, `#e3e3e3` | `#252525`, `#2c2c2c` |
| Primary text | `--color-font-primary` | `#000000` | `#e6e6e6` |
| Secondary text | `--color-font-secondary` | `#a9a9a9` | `#cfcfcf` |
| Tertiary text | `--color-font-tertiary` | `#6b6b6b` | `#c0c0c0` |

Rules:

| Do | Avoid |
|---|---|
| Use grey tokens for all surfaces and text. | Raw `white`, `black`, `#fff`, `#000`, or ad-hoc grey values. |
| Check light and dark themes for every visual surface. | Assuming a light-only background. |
| Use `--color-grey-blue` for user chat bubble surfaces where existing chat UI does. | Replacing chat bubbles with unrelated brand colors. |

### Primary Colors

OpenMates currently has two important primary-looking colors with distinct roles.

| Role | Token | Usage |
|---|---|---|
| Global action orange | `--color-button-primary` `#ff553b` | Default global CTAs, text selection highlight, global focus ring, visible action emphasis. |
| Orange hover | `--color-button-primary-hover` `#ff6b54` | Hover state for global orange actions. |
| Orange pressed | `--color-button-primary-pressed` `#ff4422` | Pressed state for global orange actions. |
| Brand/product blue gradient | `--color-primary`, `--gradient-primary` | Settings primary buttons, gradient text links, product-brand accents, OpenMates/chat app gradient. |
| Primary gradient stops | `#4867cd` to `#5a85eb` | Use at 135deg with 9.04% to 90.06% stops. |

Rule: orange is the global action/focus color. Blue gradient is the product-brand/settings accent and the default OpenMates app gradient. Do not randomly swap these roles.

### App Gradients

Every app has a gradient in `frontend/packages/ui/src/tokens/sources/gradients.yml`. All app gradients use:

```css
linear-gradient(135deg, start 9.04%, end 90.06%)
```

Use app gradients for:

| Surface | Rule |
|---|---|
| App icons | Gradient circle/square backgrounds with white icon masks. |
| Embed headers | Full-width animated gradient banners. |
| App cards | Top strips, icon backgrounds, and app-specific accents. |
| Media/social/video | Backgrounds, title cards, lower-thirds, and section accents. |

Do not create new app colors outside `gradients.yml` if the color will be reused.

### Semantic Colors

Use the semantic tokens that exist for errors, warnings, and highlights:

| Role | Token |
|---|---|
| Error text/action | `--color-error` |
| Error background | `--color-error-light` |
| Warning text | `--color-warning` |
| Warning background | `--color-warning-bg` |
| Search/message highlight | `--color-highlight-yellow`, `--color-highlight-yellow-solid` |

Avoid introducing undeclared semantic variables such as `--color-info`, `--color-success`, `--color-background-*`, or `--color-border-*` without adding them to token sources first.

## Typography

OpenMates uses Lexend Deca everywhere.

| Role | Rule |
|---|---|
| Font family | `Lexend Deca Variable`, with system sans fallback. |
| Default weight | `500` for most readable UI text. |
| Bold emphasis | `700`. |
| Extra-bold emphasis | `800`, used sparingly for hero/display emphasis. |
| Font units | Use `rem` on web. Never use `px` for `font-size`. |

Type scale:

| Token | Desktop | Mobile | Usage |
|---|---:|---:|---|
| `--font-size-h1` | `3.75rem` | `2.25rem` | Large marketing/page hero titles. |
| `--font-size-h2` | `1.875rem` | `1.5rem` | Page and major section titles. |
| `--font-size-h3` | `1.25rem` | `1.125rem` | Card/header titles, embed headers. |
| `--font-size-h4` | `1rem` | `1rem` | Small section headings. |
| `--font-size-p` | `1rem` | `1rem` | Body text, buttons, inputs. |
| `--font-size-small` | `0.875rem` | same | Secondary UI text. |
| `--font-size-xs` | `0.8125rem` | same | Labels, metadata. |
| `--font-size-xxs` | `0.75rem` | same | Compact metadata. |
| `--font-size-tiny` | `0.6875rem` | same | Dense auxiliary labels only. |

Rules:

| Do | Avoid |
|---|---|
| Use sentence case and clear labels. | All-caps labels except tiny technical badges. |
| Keep text hierarchy shallow. | More than 3 active type sizes in a small component. |
| Clamp long titles in cards and embed bars. | Letting long URLs/titles break layout. |
| Use `line-height: 1.5` for explanatory text. | Dense paragraphs with low line-height. |

## Spacing, Radius, Shadows

### Spacing

Use the token scale from `spacing.yml`:

| Token | Value | Common Use |
|---|---:|---|
| `--spacing-2` | `4px` | Tight icon/text gaps. |
| `--spacing-4` | `8px` | Common component gaps. |
| `--spacing-6` | `12px` | Chat bubble padding, compact cards. |
| `--spacing-8` | `16px` | Standard section spacing. |
| `--spacing-10` | `20px` | Embed preview side padding. |
| `--spacing-12` | `24px` | Header and page padding. |
| `--spacing-16` | `32px` | Large section breaks. |
| `--spacing-24` | `48px` | Hero/marketing spacing. |

### Radius

OpenMates is strongly rounded.

| Token/Value | Use |
|---|---|
| `--radius-2` / `6px` | Code blocks, compact technical surfaces. |
| `--radius-3` / `8px` | Standard small cards and controls. |
| `--radius-5` / `12px` | Settings cards and notification blocks. |
| `--radius-6` / `14px` | Chat/header banner corners. |
| `--radius-8` / `20px` | Primary pill buttons. |
| `--radius-full` / `9999px` | Pills, avatars, icon buttons. |
| `24px` | Settings inputs/buttons where existing canonical components use it. |
| `30px` | Embed preview cards and BasicInfosBar. |

Prefer token radii. Keep exact non-token radii only when matching established components like embed previews.

### Shadows

Use soft elevation, not harsh outlines.

| Token | Value | Use |
|---|---|---|
| `--shadow-xs` | `0 2px 4px rgba(0,0,0,.1)` | Subtle control lift. |
| `--shadow-sm` | `0 2px 8px rgba(0,0,0,.05)` | Inputs and light cards. |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,.15)` | Cards and menus. |
| `--shadow-lg` | `0 4px 16px rgba(0,0,0,.15)` | Modals/overlays. |
| `--shadow-xl` | `0 4px 16px rgba(0,0,0,.25)` | Strong hover/dialog emphasis. |

Embed previews use a stronger two-layer floating shadow: `0 8px 24px rgba(0,0,0,.16)` plus `0 2px 6px rgba(0,0,0,.1)`.

## Layout

OpenMates uses a three-zone structure wherever possible:

| Zone | Web App | Website/Docs |
|---|---|---|
| Left panel | Chat list/sidebar. | Page/chapter navigation. |
| Center | Current chat, page content, auth flow. | Main page content. |
| Right panel | Settings/detail panels, hidden by default. | Language/settings side panel when needed. |

Breakpoints and dimensions:

| Token | Value | Rule |
|---|---:|---|
| `--breakpoint-mobile` | `730px` | Switch major UI to mobile layout. |
| `--breakpoint-chats-open` | `1440px` | Chat sidebar opens by default above this width. |
| `--layout-chat-content-max-width` | `1000px` | Keep chat readable on wide screens. |

Rules:

| Do | Avoid |
|---|---|
| Design mobile and desktop together. | Desktop-only layouts. |
| Keep primary reading/action area centered and readable. | Full-width text on large screens. |
| Use side panels for navigation/settings instead of modal sprawl. | Inventing unrelated navigation structures. |
| Use logical CSS properties for direction-aware layout. | Hardcoding left/right when inline-start/end is appropriate. |

## Components

### Buttons

Global default buttons are orange, pill-shaped, shadowed, and pressable. Settings buttons are canonical components with blue-gradient primary styling.

| Context | Use |
|---|---|
| General/global CTA | Orange `--color-button-primary`, radius around `20px`, hover scale `1.02`, active scale `0.98`. |
| Settings pages | `SettingsButton` only. Primary is blue gradient; danger is `--color-error`; secondary is grey/white; ghost is transparent. |
| Embed top bar/icon actions | Small circular/pill icon buttons, grey surface, hover scale around `1.08`, active scale around `0.95`. |
| Navigation arrows | 36px circles, grey fill, white chevron, opacity increase on hover, scale-down on active. |

Avoid relying on global `button` styles inside complex components. Reset or use canonical primitives where needed.

### Inputs

General input pattern:

| Property | Value |
|---|---|
| Width | `100%`, max `350px` for standalone auth/global fields. |
| Padding | `12px 16px`, `48px` inline-start when icon is present. |
| Radius | `24px`. |
| Surface | `--color-grey-0`. |
| Shadow | `0 2px 8px rgba(0,0,0,.05)`. |
| Focus | Orange border and soft ring. |

Settings input pattern:

| Property | Value |
|---|---|
| Width | Full width inside settings page container. |
| Padding | Around `1.0625rem 1.4375rem`. |
| Radius | `1.5rem`. |
| Shadow | `0 0.25rem 0.25rem rgba(0,0,0,.1)`. |
| Focus | Blue primary outline/ring. |

### Cards

Use cards for grouped choices, previews, settings sections, and app surfaces.

| Context | Rule |
|---|---|
| App cards | Rounded, gradient edge or app-gradient accent, soft hover lift. |
| Settings cards | `SettingsCard`, `0.75rem` radius, grey-10 surface, grey-25 border, padding variants. |
| Embed previews | Fixed rounded floating card with BasicInfosBar and optional image/content section. |
| Marketing/media cards | Use grey surfaces, blue or app-gradient accents, rounded corners, and soft shadows. |

## Settings UI

Settings pages must use canonical settings components only. Do not create custom local settings UI unless a new canonical element is explicitly justified.

Canonical source: `frontend/packages/ui/src/components/settings/elements/`.

Required patterns:

| Need | Component |
|---|---|
| Page wrapper | `SettingsPageContainer` |
| Page title/description | `SettingsPageHeader` |
| Section card | `SettingsCard` |
| Key-value row | `SettingsDetailRow` |
| Menu/action row | `SettingsItem` |
| Button | `SettingsButton` |
| Button group | `SettingsButtonGroup` |
| Error/warning/info/success | `SettingsInfoBox` |
| Loading/empty/generating | `SettingsLoadingState` |
| Progress | `SettingsProgressBar` |
| Status pill | `SettingsBadge` |
| Destructive confirmation | `SettingsConfirmBlock` |
| Code/secret text | `SettingsCodeBlock` |
| Avatar | `SettingsAvatar` |
| Divider | `SettingsDivider` |
| Gradient link | `SettingsGradientLink` |
| Checkbox list | `SettingsCheckboxList` |

Settings layout rules:

| Rule | Value |
|---|---|
| Container gap | `0.75rem`. |
| Container widths | `24rem` narrow, `32rem` default, `40rem` wide. |
| Page padding | `0.75rem 0`. |
| Cards | `0.75rem` radius, `1rem` to `1.5rem` padding. |
| Row hover | Subtle `--color-grey-10` background. |
| Buttons | Pill radius `1.5rem`, press scale `0.97`. |

Never in settings pages:

| Avoid |
|---|
| Custom `.save-button`, `.delete-button`, `.primary-button`, `.cancel-button` CSS. |
| Custom loading spinners or local `@keyframes spin`. |
| Custom card backgrounds or bespoke error containers. |
| Raw colors or one-off layout CSS that duplicates canonical elements. |

Create a new settings element only when the pattern appears in at least three settings pages, has a clear visual spec, and can be expressed with a small prop surface.

## Chat UI

Chat should remain familiar and readable.

| Element | Rule |
|---|---|
| Assistant bubble | `--color-grey-0`, radius `13px`, 12px padding, speech-bubble tail on inline-start. |
| User bubble | `--color-grey-blue`, radius `13px`, 12px padding, speech-bubble tail on inline-end. |
| Bubble shadow | Existing drop shadow language, not heavy card shadows. |
| Message alignment | Assistant left/start, user right/end, with compact behavior below 500px container width. |
| Processing details | Muted, clickable, aligned with assistant avatar offset. |
| Embedded cards in chat | Horizontal scroll, snap, compact gaps, no layout-breaking overflow. |

Do not replace chat with a generic card feed. The chat metaphor is central.

## Embeds

Embeds are a major OpenMates design pattern. New embed previews and fullscreens should build from the unified base components.

### Embed Previews

Use `UnifiedEmbedPreview.svelte`.

| Property | Rule |
|---|---|
| Desktop size | `300px × 200px`. |
| Mobile size | `150px × 290px`. |
| Large container | Full width by `400px` via container query. |
| Surface | `--color-grey-25`. |
| Radius | `30px`. |
| Shadow | Floating two-layer shadow. |
| Layout | Details section above, `BasicInfosBar` below. |
| Text selection | Disabled; preview acts as one interactive object. |
| Finished state | Pointer cursor, keyboard activation, hover/tilt, active press. |
| Error state | Error border and error-tinted background. |

Preview interaction:

| State | Rule |
|---|---|
| Hover | Subtle 3D tilt toward pointer, max about `3deg`; large previews max about `1deg`. |
| Hover scale | Slight press-in feel around `0.985`; large cards around `0.995`. |
| Active | Scale to about `0.96`. |
| Reduced motion | Disable tilt/scroll-driven effects. |

### BasicInfosBar

Use `BasicInfosBar.svelte` through `UnifiedEmbedPreview`.

| Element | Desktop Rule |
|---|---|
| Bar | `61px` tall, `--color-grey-30`, `30px` radius. |
| App icon | `61px × 61px` gradient circle/container. |
| Inner app icon | White mask around `26px × 26px`. |
| Skill icon | Around `29px × 29px`, grey-70. |
| Text | Bold title, status/subtitle below, clamp long labels. |

Mobile BasicInfosBar stacks vertically, uses a smaller gradient app pill, centered text, and compact spacing.

### Embed Fullscreen

Use `UnifiedEmbedFullscreen.svelte` and `EmbedHeader.svelte`.

| Element | Rule |
|---|---|
| Overlay | Fills parent, `--color-grey-20`, radius `17px`, shadow `0 4px 20px rgba(0,0,0,.3)`. |
| Opening | Slide up from `translateY(100%)` to `0`. No scale. |
| Duration/easing | `320ms cubic-bezier(0.32, 0, 0.2, 1)`. |
| Content | Scrollable, selectable text, subtle scrollbar. |
| Scroll cue | 48px bottom fade to `--color-grey-20`. |

### Embed Header

Embed headers use an animated app-gradient banner.

| Element | Rule |
|---|---|
| Desktop height | `240px`. |
| Mobile height | `190px` at max-width `730px`. |
| Inner radius | Bottom corners around `14px`, top flush with overlay. |
| Background | App gradient from `gradients.yml`. |
| Orbs | Three blurred `220px` radial blobs, opacity about `0.55`, blur `28px`, slow morph/drift. |
| Decorative icons | Large white skill/app icons around `126px`, opacity about `0.4`, slow floating motion. |
| Center icon | `38px`, white skill mask or app icon. |
| Title | `--font-size-h3`, weight `700`, white, max two lines. |
| Subtitle | Small text, white at about `0.85` opacity. |
| CTA area | Peeks out from bottom center; header height does not grow. |

Reduce or disable header animations for `prefers-reduced-motion: reduce`.

## Motion

Motion should make the UI feel alive and responsive without distracting users.

Use existing timings:

| Token/Value | Use |
|---|---|
| `--duration-fast` / `0.15s` | Hover states, micro interactions. |
| `--duration-normal` / `0.2s` | General transitions. |
| `--duration-slow` / `0.3s` | Modal/overlay transitions. |
| `320ms cubic-bezier(0.32,0,0.2,1)` | Embed fullscreen slide transition. |

Approved motion patterns:

| Pattern | Rule |
|---|---|
| Button hover | Slight shadow increase or scale, normally `1.02` max. |
| Button press | Scale down around `0.97` to `0.98`; small icon buttons may use `0.95`. |
| Cards | Soft hover lift or embed tilt only when card is interactive. |
| Embed headers | Slow blurred gradient orb drift and decorative icon float. |
| Loading | Use canonical loading components; shimmer/pulse only for active processing states. |
| Overlay open | Translate/slide, not zoom-heavy effects. |

Required accessibility:

| Rule |
|---|
| Respect `prefers-reduced-motion: reduce` for new animations. |
| Do not animate large blurred elements without performance consideration. |
| Avoid infinite motion outside headers and active processing states. |
| Keep motion functional: state feedback, spatial continuity, loading, or brand atmosphere. |

## Accessibility

Accessibility is part of the design language.

| Area | Rule |
|---|---|
| Focus | Use visible `:focus-visible`; default ring is orange, orange buttons use blue/primary contrast. |
| Keyboard | Clickable cards/embeds need keyboard activation and role semantics. |
| Text selection | Global UI disables selection, but readable/copyable content must opt back in. |
| Touch targets | Prefer at least 36px for compact icon buttons and larger for primary actions. |
| Mobile | Verify at and below 730px; chat sidebar is closed by default at <=1440px. |
| Dark mode | Every surface must use theme-aware tokens and remain legible. |
| Scrollbars | Keep scroll affordances visible enough for long panels and embed content. |

## Video, Remotion, Social, And Print

Video and static media must use the same token source as the product UI. Check this `DESIGN.md` before creating Remotion compositions, product videos, OG images, social posts, print layouts, or marketing exports.

Token-based video rules:

| Area | Rule |
|---|---|
| Typography | Use Lexend Deca. Use the same hierarchy: hero/title, h2/h3 section text, small metadata. |
| Color | Use theme grey surfaces, OpenMates blue gradient, orange action accents, and app gradients. |
| Backgrounds | Prefer dark or light token surfaces with app-gradient accents; avoid unrelated palettes. |
| Panels | Use rounded cards/panels with radii proportional to `12px`, `20px`, `30px` UI shapes. |
| Lower thirds | Use rounded pill/card surfaces, Lexend text, app-gradient icon or accent strip. |
| Title cards | Use OpenMates blue gradient or the relevant app gradient; keep text large, centered, and uncluttered. |
| Captions/subtitles | Use high-contrast Lexend, token text colors, and safe margins. |
| Motion | Use smooth 0.15s to 0.3s micro motion for UI elements; use slower, subtle gradient/orb motion for atmosphere. |
| Device frames | Prefer real app screenshots through media-generation templates when showing product UI. |
| Safe areas | Keep important text/action content away from platform crop zones; maintain generous margins. |

For Remotion specifically:

| Rule |
|---|
| Import or mirror token values rather than inventing per-composition colors. |
| Use app gradients for scene identity and section transitions. |
| Prefer transform/opacity animation over layout thrash. |
| Keep animation readable at 1x speed and in thumbnail previews. |
| If a reusable video style is introduced, update this file and the relevant media-generation docs. |

For print:

| Rule |
|---|
| Use Lexend Deca and the same hierarchy, but adapt sizes to physical format. |
| Use high contrast and avoid relying on subtle shadows alone. |
| App gradients may be used as accents, dividers, covers, or section bands. |
| Keep rounded cards and pill labels to preserve OpenMates identity. |

## Do And Avoid

### Do

| Rule |
|---|
| Start from existing tokens and canonical components. |
| Preserve the chat-app mental model. |
| Use Lexend Deca, rounded surfaces, soft shadows, theme-aware greys, app gradients, and clear focus states. |
| Use `UnifiedEmbedPreview` and `UnifiedEmbedFullscreen` for embeds. |
| Use `settings/elements` components for settings screens. |
| Check desktop, mobile, light theme, and dark theme. |
| Update this file when changing reusable visual rules. |

### Avoid

| Anti-pattern |
|---|
| Raw reusable colors, especially raw whites/blacks/greys. |
| New local settings CSS that duplicates canonical settings elements. |
| Generic SaaS cards that ignore chat, embeds, and app-gradient identity. |
| New semantic CSS variables without adding token source definitions. |
| Assuming global `button` styling is safe inside complex components. |
| Excessive animation, unbounded infinite motion, or missing reduced-motion handling. |
| Pixel font sizes on web. Use `rem`. |
| Designs that only work in light mode or only on desktop. |

## Maintenance Rule

Updating this file is mandatory when a change introduces or modifies a reusable design rule.

Update `DESIGN.md` when you change:

| Change Type | Examples |
|---|---|
| Tokens | Colors, gradients, typography, spacing, radii, shadows, breakpoints, motion timings. |
| Components | New settings primitives, embed base changes, new shared buttons/cards/fields. |
| Layout patterns | Sidebar behavior, panel structure, fullscreen behavior, media templates. |
| Motion patterns | New animation families, Remotion scene transitions, processing/loading styles. |
| Cross-medium rules | Video, print, social, native app visual conventions. |

If a visual change is one-off and not reusable, do not expand this file. If it becomes a pattern, update this file with concrete values and source references.
