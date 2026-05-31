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

The Svelte app is the source of truth for component structure and behavior. Native SwiftUI should mirror the Svelte components intentionally instead of approximating them with platform defaults.

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
