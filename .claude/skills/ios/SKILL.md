---
name: ios
description: Start an iOS/macOS Apple app development or web-parity audit session — loads design rules, maps web sources to native code, supports Linux static audits, and verifies with Xcode when available
user-invocable: true
argument-hint: "<task description>"
---

## Instructions

This skill sets up context for working on the Apple app (`apple/OpenMates/`). Use it for native Swift implementation, Apple/web parity audits, testability work, and Linux-side planning before Mac/Xcode verification is available.

For new shared features, app skills, focus modes, embeds, memory types, and
provider-backed behavior, Apple parity is the last phase. Before changing Apple
implementation, confirm the spec or session contract has completed evidence for
CLI implementation/testing against the dev server, npm SDK and pip SDK
parity/testing locally against the dev server when applicable, GitHub Actions
CI/daily-test reproduction only after local CLI and SDK success, web
implementation/testing, and user confirmation that deployed dev web behavior
works and looks correct. If any earlier phase is missing, stop Apple
implementation and record the missing gate unless the spec contains an explicit
waiver or accepted external blocker. Mocked OpenMates API calls, mocked SDK
clients, stubbed servers, direct function calls, and fixture replay do not count
as completed CLI evidence.

### Step 1: Load iOS rules and docs

1. Read `.claude/rules/apple-ui.md` (design tokens, forbidden controls, file mappings)
2. Read `apple/AGENTS.md` (architecture, primitives, cross-references)
3. Read `apple/CLAUDE.md` (implementation notes)

### Step 2: Choose Work Mode

Use one of three modes depending on the environment and task:

- **Mac implementation mode:** XcodeBuildMCP is available. Use build/run/screenshot verification after changes.
- **Remote Mac verification mode:** OpenCode runs on Linux/dev server, but a trusted Mac is reachable through operator-provided SSH configuration. Use SSH to run `git`, `xcodebuild`, and `xcrun simctl` on the Mac. Never commit hostnames, IPs, usernames, SSH aliases, tailnet names, auth keys, device names, or personal local paths to repo files.
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

For remote Mac verification mode, use only local runtime configuration supplied by the operator, such as `~/.ssh/config`, environment variables, or the current chat. Before building, verify key-based SSH access, check the Mac checkout with `git status --short`, and avoid overwriting local user changes. Use generic placeholders in notes and committed docs.

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
2. For broad UI parity work, read `docs/specs/apple-ui-parity-program/spec.yml` and use its chat-first inventory before adding one-off native tests.
3. Run or update `scripts/apple_parity_audit.py` to compare web `data-testid` values with Apple `.accessibilityIdentifier(...)` values and refresh `test-results/apple-parity-inventory.json`.
4. For chat parity, run `scripts/apple_chat_parity_audit.py`; it verifies the chat guardrails and the `programs.apple_ui_parity_program` inventory section.
5. Read the relevant web Playwright specs and source files.
6. Read the corresponding Apple Swift files.
7. Compare protocol names, data models, state machines, error states, loading states, offline behavior, and testability identifiers.
8. Document findings in `docs/architecture/apple/<surface>-parity.md`.
9. Separate findings into `Confirmed from source`, `Likely gap`, `Intentional native difference`, and `Needs Mac verification`.
10. Produce a Mac verification checklist with exact screens, actions, expected screenshots, and tests to add/run later.

The Apple UI parity program uses a hybrid gate: deterministic structure,
identifier, fixture, native-test, known-renderer, fallback, behavior, and
ordering gaps are blocking; visual/style differences stay warning-only until a
specific surface and state are reviewed and promoted with explicit tolerance and
artifact rules.

Linux audits may update docs, scripts, and safe static identifiers. Do not make broad Swift behavior changes that require compiler validation unless the user explicitly asks and accepts Mac verification later.

### Step 7: Build-run-verify loop (Mac only)

After each code change:
1. Build and run: use `build_run_sim` (or manual xcodebuild fallback)
2. Screenshot the simulator: use `screenshot`
3. Compare against the web app (use `firecrawl_scrape` with `screenshot` format on the equivalent page)
4. If mismatch: re-read the CSS, fix the Swift code, repeat
5. When verification is complete, shut down any simulator booted by this session unless the operator asks to keep it running

For Apple UI parity work, success requires visual proof. Include either a
simulator screenshot artifact, a UI test artifact, or an explicit blocker/skip
reason. For composer, header, settings, auth, upload, audio, and navigation
controls, tests must prove rendered visibility and clickability, not only that
an accessibility element exists.

### Step 8: Remote Mac CLI verification loop

When XcodeBuildMCP is unavailable but SSH to a trusted Mac is available:

1. Run `python3 scripts/apple_remote.py status`.
2. Run `python3 scripts/apple_remote.py doctor` to verify Xcode, simulator, checkout, scheme, and Watch-test readiness with sanitized output.
3. Confirm the remote Mac has a clean checkout or only the current session's expected changes.
4. Run `git pull --ff-only` in the remote checkout only when it is clean.
5. Build with `python3 scripts/apple_remote.py build-ios --simulator "iPhone 17"`, `build-macos`, or `build-watch` depending on the affected surface.
6. For targeted tests, use `test-ios --only-testing "OpenMatesTests/<TestName>"`, `test-ios --only-testing "OpenMatesUITests/<TestName>"`, or `test-macos --only-testing "OpenMatesMacUITests/<TestName>"`.
7. For startup/crash/log-status/screenshot-status evidence, use `verify-ios-startup`, `verify-macos-startup`, or `verify-watch-startup` instead of hand-rolled `simctl` steps. Add `verify-ios-startup --fresh-install` only when first-run or clean-container state is required. The startup verifiers clean temporary artifacts by default; use a targeted native UI test artifact for durable visual evidence.
8. Current Watch unit tests live under the iOS unit-test target. Use `test-ios --only-testing "OpenMatesTests/<WatchTestName>"` unless `doctor` reports a dedicated Watch test scheme.
9. After verification, run `python3 scripts/apple_remote.py cleanup` for any simulator booted by this session unless the operator asks to keep it running.
10. Clean up only temporary artifacts created by the current session, such as copied screenshots or throwaway build logs. Do not delete unrelated DerivedData, caches, or local checkout changes.
11. Keep private connection details out of repo files and final summaries; refer to the remote host only generically.

12. For visual or interaction parity, capture a simulator screenshot after the
   app reaches the changed state and record where the artifact lives. If the
   screenshot cannot be captured, report the sanitized blocker and do not claim
   visual parity complete.

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
