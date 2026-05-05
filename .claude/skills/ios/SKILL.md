---
name: ios
description: Start an iOS/macOS Apple app development session — loads design rules, verifies Xcode build setup, and reads the web source files for any Swift file being modified
user-invocable: true
argument-hint: "<task description>"
---

## Instructions

This skill sets up context for working on the Apple app (`apple/OpenMates/`).

### Step 1: Load iOS rules and docs

1. Read `.claude/rules/apple-ui.md` (design tokens, forbidden controls, file mappings)
2. Read `apple/AGENTS.md` (architecture, primitives, cross-references)
3. Read `apple/CLAUDE.md` (implementation notes)

### Step 2: Verify XcodeBuildMCP setup

Call `session_show_defaults`. If project/scheme/simulator are not set:

```
session_set_defaults:
  projectPath: apple/OpenMates.xcodeproj
  scheme: OpenMates_iOS
  simulatorName: <pick latest available iPhone>
```

### Step 3: Identify affected Swift files

From the user's task description, identify which Swift files will be touched.
For each Swift file:

1. Read the `// ─── Web source` header block to find the mapped Svelte/CSS files
2. Read those Svelte components and CSS files BEFORE writing any Swift code
3. Note exact pixel values, class names, and responsive breakpoints from the CSS

If the Swift file has no web source header, check the mapping table in `.claude/rules/apple-ui.md`.

### Step 4: Start session

```bash
python3 scripts/sessions.py start --mode <feature|bug> --task "<task>"
```

### Step 5: Build-run-verify loop

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
