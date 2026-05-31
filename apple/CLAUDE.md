# Claude / Human Implementation Notes

The Apple app must not be implemented with stock iOS/macOS product UI. Use the custom OpenMates SwiftUI design system and generated web design tokens.

OpenMates is SwiftUI-first, not SwiftUI-only. Keep app chrome, screen composition, and Svelte-to-native product UI parity in SwiftUI by default. Use UIKit selectively for measured performance bottlenecks, platform-owned capabilities, and surfaces where UIKit's reuse/direct-manipulation model is clearly better.

The web Svelte app is the source of truth for:

- chat header structure
- message input/composer behavior
- settings layout and rows
- embed cards, grouping, and fullscreen
- custom menus, overlays, and action buttons
- spacing, color, typography, gradients, icons, and interaction states

Do not introduce product UI using:

- `List`
- `Form`
- default navigation bars/toolbars
- `ToolbarItem`
- `.navigationTitle`
- default `Menu`
- default `Picker`
- default `Toggle`
- default button styling
- app-owned default sheets/alerts/context menus

Use OS UI only for OS-owned workflows: camera/photo/file pickers, share sheets, passkeys, permissions, and similar system contracts.

Use UIKit wrappers for long virtualized feeds, chat transcript/message lists with proven scroll or streaming jank, rich embed lists with heavy media, gesture-heavy real-time interactions, PDF/map/video/web/canvas surfaces, and similar performance-critical views. Prefer `UIViewRepresentable`/`NSViewRepresentable` or a contained UIKit/AppKit component over migrating the whole screen or app shell.

Before replacing SwiftUI with UIKit, identify a concrete bottleneck, optimize expensive SwiftUI `body` work and state invalidation first, then move only the hot surface. For scrolling/reuse problems, prefer a UIKit `UICollectionView`/`UIScrollView` wrapper while preserving surrounding SwiftUI composition.

If a touched file still uses default product UI, migrate that touched surface toward reusable OpenMates primitives rather than layering more modifiers onto native controls.

Every touched Svelte product UI file must include a `Native Swift counterparts:` block in its header comment. Every touched Swift product UI file must include the matching Svelte/CSS source files in its header comment. Do not leave counterpart mapping implicit.
