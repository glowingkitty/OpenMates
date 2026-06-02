---
name: ios
description: Start an iOS/macOS Apple app development or web-parity audit session — loads design rules, maps web sources to native code, supports Linux static audits, and verifies with Xcode when available
user-invocable: true
argument-hint: "<task description>"
---

## Instructions

This skill sets up context for working on the Apple app (`apple/OpenMates/`). Use it for native Swift implementation, Apple/web parity audits, testability work, and Linux-side planning before Mac/Xcode verification is available.

### Step 1: Load iOS rules and docs

1. Read `.claude/rules/apple-ui.md` (design tokens, forbidden controls, file mappings)
2. Read `apple/AGENTS.md` (architecture, primitives, cross-references)
3. Read `apple/CLAUDE.md` (implementation notes)

### Step 2: Choose Work Mode

Use one of two modes depending on the environment and task:

- **Mac implementation mode:** XcodeBuildMCP is available. Use build/run/screenshot verification after changes.
- **Linux parity audit mode:** XcodeBuildMCP is unavailable. Do static source audits, generate parity specs, update mappings, compare web test IDs with Apple accessibility identifiers, and prepare Mac verification checklists. Do not claim runtime parity until a Mac build/simulator pass verifies it.

### Step 3: Verify XcodeBuildMCP setup (Mac only)

Call `session_show_defaults`. If project/scheme/simulator are not set:

```
session_set_defaults:
  projectPath: apple/OpenMates.xcodeproj
  scheme: OpenMates_iOS
  simulatorName: <pick latest available iPhone>
```

Skip this step on Linux and record `Mac verification required` in the final summary.

### Step 4: Identify affected Swift files or parity surface

From the user's task description, identify which Swift files will be touched.
For each Swift file:

1. Read the `// ─── Web source` header block to find the mapped Svelte/CSS files
2. Read those Svelte components and CSS files BEFORE writing any Swift code
3. Note exact pixel values, class names, and responsive breakpoints from the CSS

If the Swift file has no web source header, check the mapping table in `.claude/rules/apple-ui.md`.

For feature parity audits, identify the product surface first, then read all relevant web and Apple sources. Good vertical slices include:

- sync and offline lifecycle
- message processing and persistence
- AI streaming
- notifications, unread counts, and banners
- auth and recovery
- settings pages
- embeds and skill outputs
- chat shell, composer, and message UI

### Step 5: Start session

```bash
python3 scripts/sessions.py start --mode <feature|bug> --task "<task>"
```

### Step 6: Linux parity audit loop

When working without Xcode/Mac access:

1. Read `docs/architecture/apple/parity-matrix.md` if it exists.
2. Run or update `scripts/apple_parity_audit.py` to compare web `data-testid` values with Apple `.accessibilityIdentifier(...)` values.
3. Read the relevant web Playwright specs and source files.
4. Read the corresponding Apple Swift files.
5. Compare protocol names, data models, state machines, error states, loading states, offline behavior, and testability identifiers.
6. Document findings in `docs/architecture/apple/<surface>-parity.md`.
7. Separate findings into `Confirmed from source`, `Likely gap`, `Intentional native difference`, and `Needs Mac verification`.
8. Produce a Mac verification checklist with exact screens, actions, expected screenshots, and tests to add/run later.

Linux audits may update docs, scripts, and safe static identifiers. Do not make broad Swift behavior changes that require compiler validation unless the user explicitly asks and accepts Mac verification later.

### Step 7: Build-run-verify loop (Mac only)

After each code change:
1. Build and run: use `build_run_sim` (or manual xcodebuild fallback)
2. Screenshot the simulator: use `screenshot`
3. Compare against the web app (use `firecrawl_scrape` with `screenshot` format on the equivalent page)
4. If mismatch: re-read the CSS, fix the Swift code, repeat

### Reminders

- **Always read the web CSS before writing Swift.** The CSS is the spec.
- **Never hardcode colors, spacing, fonts, or radii.** Use generated tokens.
- **Never edit `*.generated.swift` or `Icons.xcassets` manually.** They come from `npm run build:tokens`.
- **Icons.xcassets uses template rendering.** Use `.renderingMode(.original)` only for icons with built-in colors (e.g. openmates favicon).
- **Responsive sizing matters.** Check `.mate-profile-small-mobile`, container width breakpoints, and `horizontalSizeClass` in Swift.
- **No native product UI.** See forbidden controls table in apple-ui.md.
- **Parity is surface-level, not file-level.** Do not force one Swift file per Svelte/TS file. Maintain traceable many-to-many mappings instead.
- **Use stable identifiers.** Apple `.accessibilityIdentifier(...)` values should match web `data-testid` names when the product concept is the same, unless a native-only control needs a native-specific name.
- **Document native-only differences.** Example: native offline storage of the last 100 chats is allowed if it preserves web sync semantics and is explicitly documented in the parity spec.
