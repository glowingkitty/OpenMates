# Claude / Human Implementation Notes

The Apple app must not be implemented with stock iOS/macOS product UI. Use the custom OpenMates SwiftUI design system and generated web design tokens.

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

If a touched file still uses default product UI, migrate that touched surface toward reusable OpenMates primitives rather than layering more modifiers onto native controls.

Every touched Svelte product UI file must include a `Native Swift counterparts:` block in its header comment. Every touched Swift product UI file must include the matching Svelte/CSS source files in its header comment. Do not leave counterpart mapping implicit.
