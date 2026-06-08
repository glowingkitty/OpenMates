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

## Remote Mac Verification

When the active OpenCode session runs on a Linux/dev server but a trusted Mac is available over a private network, use SSH for Apple verification instead of guessing from static source.

Use only operator-provided connection details from local runtime configuration, such as `~/.ssh/config`, environment variables, or the current chat. Never commit private connection details to the open source repository. This includes hostnames, IP addresses, usernames, SSH aliases, tailnet names, device names, auth keys, and local filesystem paths outside generic placeholders.

Remote verification flow:

1. Confirm SSH access with key-based authentication before running build commands.
2. In the Mac checkout, run `git status --short` and avoid overwriting local user changes.
3. Update the Mac checkout with `git pull --ff-only` when the tree is clean, or copy only the files intentionally changed in the current session.
4. Build with `xcodebuild -project apple/OpenMates.xcodeproj -scheme OpenMates_iOS -destination "platform=iOS Simulator,name=<simulator>" build`.
5. To verify simulator control, boot the simulator, install the built app, launch it, optionally adjust simulator UI state, and capture a screenshot using `xcrun simctl`.
6. After verification, shut down any simulator booted by the session with `xcrun simctl shutdown <simulator>` unless the operator explicitly asks to keep it running.
7. Clean up only temporary artifacts created by the current session, such as copied screenshots or throwaway build logs. Do not delete unrelated DerivedData, caches, or local checkout changes.
8. Report only generic evidence in committed docs and summaries. Keep private connection details in local shell history or operator notes, not repo files.
