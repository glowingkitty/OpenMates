---
status: planned
created: 2026-04-04
linear_task: OPE-326
key_files:
  - frontend/packages/ui/src/styles/theme.css
  - frontend/packages/ui/src/styles/fonts.css
  - frontend/packages/ui/src/styles/constants.ts
  - frontend/packages/ui/scripts/build-translations.js
  - frontend/packages/ui/package.json
---

# Unified Design Token System

> Single YAML source of truth for all visual tokens, generating CSS custom properties (web), TypeScript constants (Svelte logic), and Swift extensions + Xcode asset catalogs (native Apple app). Ensures web and native platforms stay pixel-identical from a shared definition.

Linear task: OPE-326

## Why This Exists

OpenMates is adding a native Swift/SwiftUI Apple ecosystem app (iOS, iPadOS, macOS, watchOS). The current styling system has two problems:

1. **No cross-platform source of truth.** The 231 CSS custom properties in `theme.css` only serve the web app. A native app would need to manually duplicate every color, font size, and spacing value into Swift code — then keep them in sync forever.

2. **~1,500+ hardcoded values in Svelte components.** Despite having a token system, most components bypass it with raw `px`, hex colors, and magic numbers in their `<style>` blocks. This makes bulk changes (dark mode tuning, brand refresh, native parity) require touching hundreds of files.

### Hardcoded values audit

| Category | Most common value | Instances of that value | Total hardcoded instances |
|----------|-------------------|------------------------|--------------------------|
| Font sizes | `14px` | 416 | ~1,100 |
| Spacing (gap) | `8px` | 184 | ~620 |
| Border radius | `8px` | 230 | ~580 |
| Colors | `#ffffff` / `#fff` | 50 | ~230 |
| Transitions | `all 0.2s ease` | 49 | ~130 |
| Z-index | `1` through `99999` | 42+ | ~120 |
| Shadows | `0 2px 4px rgba(0,0,0,0.1)` | 13 | ~40 |

## Architecture

```
frontend/packages/ui/src/tokens/
  sources/                          # YAML source files (single source of truth)
    colors.yml                      # Grey scale (light/dark), font, semantic, button
    gradients.yml                   # 50+ app gradients, icon, primary, footer
    typography.yml                  # Font families, weights, sizes (rem + pt)
    spacing.yml                     # Spacing scale
    radii.yml                       # Border radius scale
    shadows.yml                     # Shadow presets
    z-index.yml                     # Named layer system
    transitions.yml                 # Duration/easing presets
    icons.yml                       # Icon size scale
    icons-mapping.yml               # Lucide → SF Symbol mapping + icon aliases
    layout.yml                      # Breakpoints, max-widths
  generated/                        # AUTO-GENERATED — never edit
    theme.generated.css             # Replaces :root / [data-theme="dark"] blocks
    tokens.generated.ts             # TypeScript typed constants + icon mapping
    swift/
      ColorTokens.generated.swift   # SwiftUI Color extensions
      TypographyTokens.generated.swift
      SpacingTokens.generated.swift
      GradientTokens.generated.swift
      IconMapping.generated.swift   # SFSymbol enum + Image extensions + aliases
      Tokens.generated.swift        # Umbrella re-export
      Assets.xcassets/              # Color catalog with light/dark pairs
      Icons.xcassets/               # SVG icon catalog (202 custom icons)
```

This mirrors the i18n pipeline: `src/i18n/sources/*.yml` -> `build-translations.js` -> `src/i18n/locales/*.json`.

### Build pipeline

```
pnpm --filter @repo/ui build:tokens
  |
  Reads src/tokens/sources/*.yml
  |
  Generates -> theme.generated.css     (web — identical format to current theme.css)
            -> tokens.generated.ts     (Svelte logic / programmatic access)
            -> swift/*.generated.swift (iOS/macOS/watchOS)
            -> swift/Assets.xcassets/  (Xcode adaptive color catalog)
```

Runs as the first step in `prepare` / `prebuild` / `build` chains, before `build:translations`. A Vite file watcher triggers rebuild during dev when YAML sources change.

## YAML Schema

### colors.yml — theme-aware colors

```yaml
# Colors with light/dark theme support.
# Tokens with both light/dark values generate:
#   CSS:   :root { --color-grey-0: #ffffff; }
#          [data-theme="dark"] { --color-grey-0: #171717; }
#   Swift: Color("grey-0") via asset catalog (automatic theme switching)
# Tokens with a single `value` are theme-independent.

grey:
  0:    { light: "#ffffff", dark: "#171717" }
  10:   { light: "#f9f9f9", dark: "#1c1c1c" }
  20:   { light: "#f3f3f3", dark: "#212121" }
  25:   { light: "#e8e8e8", dark: "#252525" }
  30:   { light: "#e3e3e3", dark: "#2c2c2c" }
  40:   { light: "#c4c4c4", dark: "#404040" }
  50:   { light: "#a6a6a6", dark: "#606060" }
  60:   { light: "#888888", dark: "#808080" }
  70:   { light: "#666666", dark: "#a0a0a0" }
  80:   { light: "#444444", dark: "#c0c0c0" }
  90:   { light: "#222222", dark: "#e0e0e0" }
  100:  { light: "#000000", dark: "#ffffff" }
  blue: { light: "#e6eaff", dark: "#2d2f35" }

font:
  primary:           { light: "#000000", dark: "#e6e6e6" }
  secondary:         { light: "#a9a9a9", dark: "#cfcfcf" }
  tertiary:          { light: "#6b6b6b", dark: "#c0c0c0" }
  button:            { value: "#ffffff" }
  field-placeholder: { value: "#9e9e9e" }
  bold:              { light: "#503ba0", dark: "#c9bbff" }

semantic:
  error:        { light: "#e74c3c", dark: "#ff6b6b" }
  error-light:  { light: "rgba(231, 76, 60, 0.1)", dark: "rgba(255, 107, 107, 0.15)" }
  warning:      { light: "#e67e22", dark: "#f0a050" }
  warning-bg:   { light: "rgba(230, 126, 34, 0.1)", dark: "rgba(240, 160, 80, 0.15)" }

button:
  primary:         { value: "#ff553b" }
  primary-hover:   { value: "#ff6b54" }
  primary-pressed: { value: "#ff4422" }
  secondary:       { value: "#808080" }
  secondary-hover: { value: "#909090" }
  secondary-pressed: { value: "#606060" }
```

### gradients.yml — app gradients

```yaml
# All gradients use the standard 135deg / 9.04%->90.06% stops.
# The angle and stops are NOT repeated per entry — the generator applies them.
# CSS output: --color-app-{name}-start, --color-app-{name}-end, --color-app-{name}
# Swift output: LinearGradient.app{Name}

apps:
  ai:               { start: "#b85a3a", end: "#e8956e" }
  health:           { start: "#fd50a0", end: "#f42c2d" }
  life-coaching:    { start: "#fdb250", end: "#f42c2d" }
  nutrition:        { start: "#fd8450", end: "#f42c2d" }
  finance:          { start: "#0a6e04", end: "#2cb81e" }
  fitness:          { start: "#8a0048", end: "#d63084" }
  legal:            { start: "#239cff", end: "#005ba5" }
  weather:          { start: "#005ba5", end: "#00a7c9" }
  travel:           { start: "#059db3", end: "#13daf5" }
  news:             { start: "#c90820", end: "#f95a6e" }
  jobs:             { start: "#049363", end: "#00c382" }
  # ... all 50+ apps (full list extracted from theme.css)

icons:
  default:  { start_ref: "color-grey-20", end_ref: "color-grey-30" }
  focus:    { start: "#5951d0", end: "#7d74ff" }
  skill:    { start: "#fefefe", end: "#eaeaea" }
  memory:   { start: "#b5008e", end: "#f03ed0" }

primary:    { start: "#4867cd", end: "#5a85eb" }

footer:
  light:    { start: "#4867cd", end: "#5a85eb" }
  dark:     { start: "#293d7f", end: "#263969" }
```

### spacing.yml — spacing scale

```yaml
# Scale derived from audit of actual usage across 352 components.
# CSS output: --spacing-{key}: {value}px
# Swift output: CGFloat.spacing{key}
# Values in px.

scale:
  0:  0
  1:  2
  2:  4       # 101 uses as gap
  3:  6       # 91 uses
  4:  8       # 184 uses (most common)
  5:  10      # 61 uses
  6:  12      # 113 uses
  8:  16      # 69 uses
  10: 20      # 48 uses
  12: 24      # 45 uses
  16: 32
  20: 40
  24: 48
  32: 64
```

### radii.yml — border radius scale

```yaml
# CSS output: --radius-{key}: {value}px
# Swift output: CGFloat.radius{key}

scale:
  1:    4     # 70 uses (small UI elements)
  2:    6     # 72 uses (code blocks, blockquotes)
  3:    8     # 230 uses (cards, buttons — most common)
  4:    10    # 48 uses (medium components)
  5:    12    # 119 uses (notifications, modals)
  6:    14    # chat headers, banners
  7:    16
  8:    20    # primary buttons
  full: 9999  # pill shapes
```

### typography.yml — font system

```yaml
# rem for CSS (accessibility), pt for Swift.
# CSS output: --font-size-{key}: {rem}rem and --font-size-{key}-mobile: {mobile_rem}rem
# Swift output: Font.custom("LexendDeca-Variable", size: {pt})

font-family:
  primary: "Lexend Deca Variable"

font-weight:
  medium:     500
  bold:       700
  extra-bold: 800

font-size:
  h1:    { rem: 3.75,   pt: 60, mobile_rem: 2.25,  mobile_pt: 36 }
  h2:    { rem: 1.875,  pt: 30, mobile_rem: 1.5,   mobile_pt: 24 }
  h3:    { rem: 1.25,   pt: 20, mobile_rem: 1.125, mobile_pt: 18 }
  h4:    { rem: 1,      pt: 16 }
  body:  { rem: 1,      pt: 16 }
  small: { rem: 0.875,  pt: 14 }
  xs:    { rem: 0.8125, pt: 13 }
  xxs:   { rem: 0.75,   pt: 12 }
  tiny:  { rem: 0.6875, pt: 11 }
```

### shadows.yml — shadow presets

```yaml
# CSS output: --shadow-{key}: {value}
# Swift: not directly applicable (SwiftUI uses .shadow() modifier)

presets:
  xs: "0 2px 4px rgba(0, 0, 0, 0.1)"     # 13 uses
  sm: "0 2px 8px rgba(0, 0, 0, 0.05)"     # 8 uses
  md: "0 4px 12px rgba(0, 0, 0, 0.1)"     # 12 uses
  lg: "0 4px 16px rgba(0, 0, 0, 0.15)"    # 8 uses
  xl: "0 6px 16px rgba(0, 0, 0, 0.15)"    # card hover
```

### z-index.yml — named layer system

```yaml
# Replaces the current chaos (values from 1 to 99999 with no coordination).
# CSS output: --z-index-{key}: {value}
# Components MUST use var(--z-index-{key}) instead of magic numbers.

layers:
  base:      0
  raised:    1
  dropdown:  100
  sticky:    200
  overlay:   300
  modal:     400
  popover:   500
  toast:     600
  tooltip:   700
  skip-link: 100000
```

### transitions.yml — timing presets

```yaml
# CSS output: --duration-{key}: {value} and --easing-{key}: {value}

duration:
  fast:   "0.15s"   # 21 uses
  normal: "0.2s"    # 49 uses (most common)
  slow:   "0.3s"

easing:
  default: "ease"
  in-out:  "ease-in-out"
```

### icons.yml — icon size scale

```yaml
# CSS output: --icon-size-{key}: {value}px
# Swift output: CGFloat.iconSize{Key}

size:
  xs:  16    # 38 uses
  sm:  20    # 62 uses
  md:  24    # 37 uses
  lg:  32    # 36 uses
  xl:  40    # 39 uses
  xxl: 48    # 15 uses
```

### icons-mapping.yml — cross-platform icon mapping

```yaml
# Maps semantic icon names to platform implementations.
# Web uses Lucide (@lucide/svelte), iOS uses SF Symbols.
# Custom SVGs (static/icons/*.svg) are shared via xcassets.

# Lucide → SF Symbol mapping (31 icons used in web app)
lucide:
  bell:          { sf: "bell.fill" }
  book-open:     { sf: "book.fill" }
  chevron-left:  { sf: "chevron.left" }
  heart:         { sf: "heart.fill" }
  # ... 27 more

# App/feature name → actual SVG filename aliases
aliases:
  health: heart        # health app → heart.svg
  finance: money       # finance app → money.svg
  code: coding         # code app → coding.svg
  # ... 18 more
```

**Generated outputs:**
- **TypeScript:** `LucideToSF` mapping + `IconAlias` mapping (in `tokens.generated.ts`)
- **Swift:** `SFSymbol` enum, `Image` extensions for all 202 custom SVGs, `IconAlias` enum
- **xcassets:** `Icons.xcassets/` with 202 SVG image sets (Xcode imports directly)

**Cross-platform icon strategy:**
- Standard UI icons: web uses Lucide, iOS uses SF Symbols (native look on each platform)
- Custom/brand icons: shared SVGs via xcassets (identical on both platforms)
- Icon sizes: tokenized via `--icon-size-*` / `CGFloat.iconSize*`

### layout.yml — breakpoints and dimensions

```yaml
# CSS output: --breakpoint-{key}: {value}px, --layout-{key}: {value}px
# Replaces current constants.ts

breakpoints:
  mobile:     730    # current MOBILE_BREAKPOINT
  chats-open: 1440   # current CHATS_DEFAULT_OPEN_BREAKPOINT

dimensions:
  chat-content-max-width: 1000
```

## Generated Output Formats

### CSS — replaces theme.css token blocks

```css
/* AUTO-GENERATED by build-tokens.js — DO NOT EDIT */
/* Source: frontend/packages/ui/src/tokens/sources/ */

:root {
  /* Grey scale */
  --color-grey-0: #ffffff;
  --color-grey-10: #f9f9f9;
  /* ... */

  /* Spacing */
  --spacing-0: 0px;
  --spacing-1: 2px;
  --spacing-2: 4px;
  --spacing-4: 8px;
  /* ... */

  /* App gradients */
  --color-app-ai-start: #b85a3a;
  --color-app-ai-end: #e8956e;
  --color-app-ai: linear-gradient(135deg, var(--color-app-ai-start) 9.04%, var(--color-app-ai-end) 90.06%);
  /* ... */
}

[data-theme="dark"] {
  --color-grey-0: #171717;
  --color-grey-10: #1c1c1c;
  /* ... */
}

@media (max-width: 600px) {
  :root {
    --font-size-h1: 2.25rem;
    /* ... */
  }
}
```

The generated CSS must be byte-identical to the current `theme.css` `:root` and `[data-theme="dark"]` blocks for backwards compatibility. Existing `var(--color-grey-20)` references in all 352 components continue working unchanged.

### TypeScript — replaces constants.ts

```typescript
// AUTO-GENERATED by build-tokens.js — DO NOT EDIT
export const Color = Object.freeze({
  grey0: 'var(--color-grey-0)',
  grey10: 'var(--color-grey-10)',
  // ...
  fontPrimary: 'var(--color-font-primary)',
  error: 'var(--color-error)',
} as const);

export const Spacing = Object.freeze({
  s0: 0, s1: 2, s2: 4, s3: 6, s4: 8, s5: 10,
  s6: 12, s8: 16, s10: 20, s12: 24, s16: 32,
  s20: 40, s24: 48, s32: 64,
} as const);

export const ZIndex = Object.freeze({
  base: 0, raised: 1, dropdown: 100, sticky: 200,
  overlay: 300, modal: 400, popover: 500, toast: 600,
  tooltip: 700, skipLink: 100000,
} as const);

export const Breakpoint = Object.freeze({
  mobile: 730,
  chatsOpen: 1440,
} as const);
```

### Swift — Color extensions + asset catalog

```swift
// AUTO-GENERATED by build-tokens.js — DO NOT EDIT
import SwiftUI

extension Color {
    // Grey scale — theme-aware via asset catalog
    static let grey0  = Color("grey-0")
    static let grey10 = Color("grey-10")
    // ...

    // Font colors
    static let fontPrimary   = Color("font-primary")
    static let fontSecondary = Color("font-secondary")

    // Button colors
    static let buttonPrimary = Color(hex: 0xFF553B)
}

extension LinearGradient {
    // Standard OpenMates gradient helper (135 deg, 9.04% -> 90.06%)
    static func omGradient(start: Color, end: Color) -> LinearGradient {
        LinearGradient(
            gradient: Gradient(stops: [
                .init(color: start, location: 0.0904),
                .init(color: end, location: 0.9006)
            ]),
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static let appAi = omGradient(start: Color(hex: 0xB85A3A), end: Color(hex: 0xE8956E))
    // ... all 50+ app gradients
    static let primary = omGradient(start: Color(hex: 0x4867CD), end: Color(hex: 0x5A85EB))
}

extension CGFloat {
    // Spacing scale
    static let spacing0: CGFloat = 0
    static let spacing1: CGFloat = 2
    static let spacing2: CGFloat = 4
    static let spacing4: CGFloat = 8
    // ...

    // Border radius
    static let radius1: CGFloat = 4
    static let radius3: CGFloat = 8
    static let radius5: CGFloat = 12
    // ...
}
```

For theme-aware colors, the generator also produces `.xcassets` JSON so iOS auto-switches light/dark:

```
swift/Assets.xcassets/
  grey-0.colorset/Contents.json     # light: #ffffff, dark: #171717
  grey-10.colorset/Contents.json    # light: #f9f9f9, dark: #1c1c1c
  font-primary.colorset/Contents.json
  ...
```

## Cross-Platform Naming Convention

CSS property names are **preserved exactly** for backwards compatibility.

| Category | CSS | TypeScript | Swift |
|----------|-----|-----------|-------|
| Grey color | `--color-grey-20` | `Color.grey20` | `Color.grey20` |
| Font color | `--color-font-primary` | `Color.fontPrimary` | `Color.fontPrimary` |
| Spacing | `--spacing-4` | `Spacing.s4` | `CGFloat.spacing4` |
| Font size | `--font-size-small` | `FontSize.small` | `Font.omSmall` |
| Radius | `--radius-3` | `Radius.r3` | `CGFloat.radius3` |
| Shadow | `--shadow-sm` | `Shadow.sm` | (N/A) |
| Z-index | `--z-index-modal` | `ZIndex.modal` | `CGFloat.zIndexModal` |
| App gradient | `--color-app-ai` | `AppGradient.ai` | `LinearGradient.appAi` |
| Icon size | `--icon-size-sm` | `IconSize.sm` | `CGFloat.iconSizeSm` |
| Breakpoint | `--breakpoint-mobile` | `Breakpoint.mobile` | `CGFloat.breakpointMobile` |

## Generator Script

New file: `frontend/packages/ui/scripts/build-tokens.js`

Follows the same pattern as `build-translations.js`:
- ESM module with `yaml` package (already a dependency)
- `__dirname` setup via `fileURLToPath`
- Reads YAML, validates schema, writes output files
- Every generated file has a `// AUTO-GENERATED` header

### Build pipeline integration

**`package.json`** — add to scripts:
```json
"build:tokens": "node scripts/build-tokens.js"
```

Prepend to `prepare`, `prebuild`, `build` chains (before `build:translations`).

**`turbo.json`** — add `**/tokens/generated/**` to build outputs.

## theme.css Split

Current `theme.css` (954 lines) contains both tokens AND global utility styles. Split into:

- `src/tokens/generated/theme.generated.css` — just `:root { ... }` and `[data-theme="dark"] { ... }` with all custom properties
- `src/styles/theme.css` — retains utility classes (`.color-grey-*`), scrollbar styles, focus-visible system, offline placeholder. Imports the generated file:

```css
@import '../tokens/generated/theme.generated.css';

/* Utility classes, scrollbar, focus-visible, etc. — not generated */
```

The import chain in `+layout.svelte` stays unchanged — it still imports `theme.css`.

## Migration Strategy

Incremental, non-breaking. Each batch is a separate commit verified by visual regression tests.

### Batch A — spacing + radii (~650 changes)

Highest frequency, lowest risk. Pure mechanical find-replace within `<style>` blocks.

| Find | Replace with | Count |
|------|-------------|-------|
| `gap: 8px` | `gap: var(--spacing-4)` | 184 |
| `border-radius: 8px` | `border-radius: var(--radius-3)` | 230 |
| `border-radius: 12px` | `border-radius: var(--radius-5)` | 119 |
| `gap: 12px` | `gap: var(--spacing-6)` | 113 |

### Batch B — hardcoded colors (~230 changes)

Replace hex literals with existing `var(--color-*)` tokens.

| Find | Replace with | Count |
|------|-------------|-------|
| `#ffffff` / `#fff` | `var(--color-grey-0)` | 50 |
| `#888` | `var(--color-grey-60)` | 38 |
| `#f5f5f5` | `var(--color-grey-10)` | 38 |
| `#333` | `var(--color-grey-90)` | 33 |
| `#1a1a1a` | `var(--color-grey-0)` (dark) or appropriate | 29 |
| `#666` | `var(--color-grey-70)` | 23 |
| `#ff4444` | `var(--color-error)` | 21 |

### Batch C — font sizes px to rem (~1,100 changes)

Accessibility fix — `px` font sizes don't respect browser zoom settings.

| Find | Replace with | Count |
|------|-------------|-------|
| `font-size: 14px` | `font-size: var(--font-size-small)` | 416 |
| `font-size: 12px` | `font-size: var(--font-size-xxs)` | 196 |
| `font-size: 16px` | `font-size: var(--font-size-body)` | 172 |
| `font-size: 13px` | `font-size: var(--font-size-xs)` | 168 |
| `font-size: 11px` | `font-size: var(--font-size-tiny)` | 68 |

### Batch D — shadows, transitions, z-index (~300 changes)

| Category | Example find | Example replace | Count |
|----------|-------------|----------------|-------|
| Shadow | `0 2px 4px rgba(0,0,0,0.1)` | `var(--shadow-xs)` | ~40 |
| Transition | `all 0.2s ease` | `all var(--duration-normal) var(--easing-default)` | ~130 |
| Z-index | `z-index: 1000` | `z-index: var(--z-index-modal)` | ~120 |

### Codemod script

A helper `scripts/migrate-tokens.js` automates the mechanical find-replace within `<style>` blocks. Run per batch, review diff, commit.

## Visual Regression Testing

Piggybacks on the **existing E2E specs** (~81 specs, ~200 screenshots via `createStepScreenshotter()`). No separate visual regression spec needed.

### Approach: extend createStepScreenshotter()

The existing `createStepScreenshotter()` in `signup-flow-helpers.ts` already captures named PNGs at every key UI state. Extend it to optionally assert against baselines:

```typescript
// When E2E_VISUAL_REGRESSION=1, each screenshot also runs a pixel comparison
if (process.env.E2E_VISUAL_REGRESSION) {
  await expect(page).toHaveScreenshot(`${prefix}-${label}.png`, {
    maxDiffPixelRatio: 0.01,
    animations: 'disabled',
  });
}
```

This gives ~200 baseline comparisons from existing tests with zero new spec files.

### Existing coverage (already screenshotted)

| UI area | Specs | Screenshots |
|---------|-------|------------|
| Auth (login/signup/2FA/recovery) | 8+ specs | ~60 |
| Chat (messages/AI/sidebar) | 4+ specs | ~40 |
| Settings (security/billing/API keys) | 6+ specs | ~50 |
| Files/embeds | 3+ specs | ~30 |
| Multi-device/encryption | 3+ specs | ~20 |

### Gaps to fill with 1-2 new specs

- **Dark mode** — existing tests all run light mode
- **Mobile/tablet viewports** — existing tests all run at default 1280px

### Configuration

```typescript
// playwright.config.ts additions
expect: {
  toHaveScreenshot: {
    maxDiffPixelRatio: 0.01,   // 1% tolerance for antialiasing
    animations: 'disabled',
  }
},
snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}{ext}',
```

Baselines stored in `tests/__screenshots__/` and committed to git. PRs that change styles show the baseline diff.

### Workflow

- `E2E_VISUAL_REGRESSION=1` env var enables comparison mode in CI
- `--update-snapshots` input flag added to `playwright-spec.yml` for intentional baseline updates after migration batches
- Comparison is a **blocker** — any pixel diff beyond 1% fails the workflow

## Token Validation

New script: `frontend/packages/ui/scripts/validate-token-usage.js`

Runs during build (alongside `validate-icon-refs.js`). Warns on:

- Raw hex/rgb colors in `<style>` blocks not inside `var()`
- `font-size` with `px` units (accessibility violation)
- Z-index values not using `var(--z-index-*)`

This prevents new hardcoded values from being introduced after migration.

## CLAUDE.md Updates

Add to the Styling section:

```
- All spacing, radii, shadows, transitions, and z-index values MUST use design tokens via var(--token-name)
- Token definitions: frontend/packages/ui/src/tokens/sources/*.yml — NEVER edit generated files
- To add a token: edit YAML source, run pnpm --filter @repo/ui build:tokens
- Architecture: docs/architecture/frontend/design-tokens.md
```
