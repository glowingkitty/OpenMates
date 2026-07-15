# OpenMates Apple App Instructions

This app must be built as a custom OpenMates interface, not as a stock iOS/macOS app with native controls.

## Product UI Rule

Do not use default platform product UI for OpenMates screens. Product UI includes chat, settings, embeds, fullscreen embeds, account/auth flows, share flows, legal/public chats, and app chrome.

Avoid these SwiftUI defaults in product UI:

- `List`
- `Form`
- default `NavigationStack` / `NavigationView` chrome
- `.toolbar`, `ToolbarItem`, `.navigationTitle`, `.navigationBarTitleDisplayMode`
- default `Menu`
- default `Picker`
- default `Toggle`
- default `Button` appearance
- default `.sheet` or `.alert` for app-owned flows
- default `.contextMenu` for app-owned menus

Allowed exceptions are OS-owned capability pickers or controllers where the system UI is the product contract, such as photo picker, file importer/exporter, share sheet, camera capture, passkeys, permissions, and platform authentication prompts.

## Required Architecture

Build product UI from OpenMates primitives in `OpenMates/Sources/Shared/Components`.

Use custom primitives for:

- buttons and icon buttons
- text inputs and composer controls
- settings rows, settings sections, tabs, and selectors
- app-owned overlays, dialogs, popovers, action menus, and fullscreen chrome
- embed cards, embed grouping, and embed fullscreen controls
- chat header, chat list rows, message actions, and composer

Every primitive should consume generated design tokens from the web app where possible:

- `ColorTokens.generated.swift`
- `SpacingTokens.generated.swift`
- `TypographyTokens.generated.swift`
- `GradientTokens.generated.swift`
- `ComponentTokens.generated.swift`
- `Icons.xcassets`

The rendered Svelte app is the source of truth for component structure, behavior, and visual values. Native SwiftUI should mirror the browser-computed component intentionally instead of approximating it from platform defaults or source files alone.

Before touching native product UI, inspect the actual web app route where the component appears and record the rendered element tree plus computed CSS values. Prefer the regular product route because it includes real parent layout, container widths, runtime classes, stores, and responsive state. Use `/dev/preview` only when the regular app cannot expose the needed state or an isolated harness is more accurate.

If an interaction state is needed, drive the existing `*.spec.ts` test or a temporary browser/scripted flow based on existing tests to reach that state, then inspect the computed values. Svelte and CSS source files explain intent, but the browser-computed output is the final parity target.

## SwiftUI / UIKit Strategy

OpenMates is SwiftUI-first for product UI composition, design-token usage, and parity with the Svelte web source of truth. Do not rewrite screens to UIKit by default.

Use UIKit selectively when a surface is performance-critical, platform-owned, or cannot be implemented correctly in SwiftUI:

- long virtualized feeds
- chat transcript/message lists when profiling shows scroll hitches or streaming jank
- rich embed grids/lists with many images, videos, maps, PDFs, animations, or dynamically-sized cells
- gesture-heavy real-time interactions where direct view manipulation avoids SwiftUI state-diffing churn
- PDF, map, video, web, camera, canvas/sketching, share, authentication, and similar system-backed views

Before replacing a SwiftUI product surface with UIKit:

1. Identify a concrete bottleneck through profiling, visible jank, or a repeatable reproduction.
2. First reduce expensive SwiftUI body work, broad state invalidation, and avoidable layout churn.
3. If the issue is scrolling, virtualization, reuse, or frame stability, wrap a UIKit `UICollectionView` or `UIScrollView` implementation in SwiftUI with `UIViewRepresentable`.
4. Keep surrounding app chrome and screen composition in SwiftUI unless the whole surface is proven problematic.

## Svelte ↔ Swift Cross References

Every Swift product UI file must list its source Svelte/CSS files in the header comment.

Every Svelte product UI file must list its native Swift counterpart files in its header comment when a counterpart exists. The header should include a `Native Swift counterparts:` section with project-relative paths, for example:

```svelte
<!--
  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift
  - apple/OpenMates/Sources/Features/Chat/Views/ChatHeaderView.swift
-->
```

If no native counterpart exists yet, write `Native Swift counterparts: none yet` so the gap is explicit.

## Implementation Standard

When touching a screen that still uses default product UI, convert the touched area to OpenMates primitives before adding new behavior. Do not add new default controls to legacy screens.

Prefer:

- `ScrollView` / `LazyVStack` with custom rows over `List` or `Form`
- custom header bars over `.toolbar`
- custom segmented/select controls over `Picker`
- custom toggle rows over `Toggle`
- custom overlays over app-owned `.sheet`
- `Icon(...)` assets over `Image(systemName:)`
- `.buttonStyle(.plain)` plus OpenMates styling over default button rendering

Performance matters. Avoid expensive work in SwiftUI `body`, including markdown parsing, JSON parsing, image decoding, sorting/filtering large arrays, embed payload normalization, and repeated formatter construction. Cache parsed render data with stable IDs, and keep state scoped narrowly so message-level updates do not invalidate entire screens.

## Native Diagnostics And Logging

Use `NativeDiagnostics` for Apple product diagnostics instead of adding new ad-hoc `print` calls or isolated `Logger` calls. Use `NativeSyncPerfLog` for sync/chat-opening/embed-hydration phase timings so those entries continue to reach unified logging and issue/debug buffers.

Diagnostics must remain privacy-safe: never log message plaintext, encryption keys, auth/session tokens, cookies, push tokens, full share URL fragments, request/response bodies, private file paths, or raw typed text. For performance instrumentation, use the approved diagnostics helpers (`NativePerformanceMonitor`, MetricKit summaries, or signpost-style phase logs) and keep payloads to counts, durations, sanitized categories, and hashed/prefixed identifiers only.

## Remote Mac Verification

When the active OpenCode session runs on a Linux/dev server, attempt Apple
verification through the redacted wrapper in `scripts/apple_remote.py` before
saying Mac/Xcode verification is unavailable. This is mandatory for changes that
affect Apple-backed surfaces such as chat, sync, auth, settings, embeds,
billing, shared UI, app chrome, or provider result rendering.

Use only operator-provided connection details from local runtime configuration,
such as `~/.ssh/config`, environment variables, or the current chat. Never commit
private connection details to the open source repository. This includes
hostnames, IP addresses, usernames, SSH aliases, tailnet names, device names,
auth keys, and local filesystem paths outside generic placeholders.

Remote verification flow:

1. Run `python3 scripts/apple_remote.py status` to confirm redacted SSH reachability before running build commands.
2. Run `python3 scripts/apple_remote.py doctor` to verify Xcode, simulator,
   repository, scheme, and current Watch-test readiness. The doctor command is
   intentionally sanitized and should be the first stop for AI agents before
   deeper native debugging.
3. Locate the Mac checkout without printing private paths. Prefer known local
   configuration; if needed, use a sanitized project lookup for
   `apple/OpenMates.xcodeproj` and report only success or `project_not_found`.
4. Commit and push intended local changes before Mac verification. Do not copy
   edited source files to the Mac checkout by hand except for throwaway local
   experiments that will never be committed. Git is the source of truth for
   getting updated source onto the Mac.
5. In the Mac checkout, run `git status --short` and avoid overwriting local user changes.
6. Update the Mac checkout with `git pull --ff-only` when the tree is clean. If
   the Mac checkout is dirty, stop and resolve the dirty state explicitly before
   testing committed changes.
7. Before native end-to-end UI tests that depend on first-run, login, signup,
   permissions, local storage, Keychain, or notification prompts, uninstall the
   app from the target simulator so the run starts from a clean app container:
   `python3 scripts/apple_remote.py simctl -- uninstall booted org.openmates.app`.
   Ignore the uninstall error only when the app is already absent.
8. At minimum, run `python3 scripts/apple_remote.py build-ios --simulator "iPhone 17"`
   to prove the native project compiles.
9. For native test coverage, run `python3 scripts/apple_remote.py test-ios --simulator "iPhone 17" --only-testing "OpenMatesUITests/<testName>"`.
10. For iOS startup, crash, screenshot-status, and log-status evidence, run
    `python3 scripts/apple_remote.py verify-ios-startup --simulator "iPhone 17" --duration 60`.
    Add `--fresh-install` only when the check intentionally needs first-run or
    clean-container state.
11. For macOS startup, crash, and log evidence, run
    `python3 scripts/apple_remote.py verify-macos-startup --duration 60`.
    The macOS verifier skips broad desktop screenshots by default for privacy;
    use a targeted macOS UI test artifact for visual evidence.
12. For Apple Watch runtime launch checks, run
    `python3 scripts/apple_remote.py verify-watch-startup --simulator "Apple Watch Series 11 (46mm)" --duration 60`.
    Current Watch unit tests live under the iOS unit-test target, so use
    `python3 scripts/apple_remote.py test-ios --only-testing "OpenMatesTests/<WatchTestName>"`
    until `doctor` reports a dedicated Watch test scheme.
13. After verification, shut down any simulator booted by the session with
    `python3 scripts/apple_remote.py cleanup` unless the operator explicitly asks
    to keep it running.
14. Clean up only temporary artifacts created by the current session, such as
    copied screenshots or throwaway build logs. Do not delete unrelated
    DerivedData, caches, or local checkout changes.
15. Report only generic evidence in committed docs and summaries: build command
    class, scheme, simulator family, result, and sanitized failure classes such as
    `ssh_failed`, `project_not_found`, or `xcode_build_failed`. Keep private
    connection details in local shell history or operator notes, not repo files.

For cross-client work, prefer the parity wrapper from the repo root so Apple
verification is sequenced after CLI/SDK and web evidence:

```bash
python3 scripts/verify_parity.py --run --web-spec <name>.spec.ts --apple build
```

Use `--apple test --only-testing "OpenMatesUITests/<testName>"` when a targeted
native test exists. Use `--apple skip --skip-apple "Apple not affected"` only
when the changed surface has no Apple counterpart.

Validated 2026-06-08 from the Linux dev server: a configured SSH alias reached
a Tailscale Mac, `xcodebuild -version` responded, sanitized project lookup found
the checkout, `xcodebuild -showBuildSettings` worked, and a generic
`OpenMates_iOS` iOS Simulator build completed successfully.
