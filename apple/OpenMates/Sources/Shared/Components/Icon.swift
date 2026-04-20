// Icon — renders a web app SVG icon from Icons.xcassets.
// Replaces Image(systemName:) everywhere in the app to match the web app's icon set.

// ─── Web source ─────────────────────────────────────────────────────
// Assets: frontend/packages/ui/src/tokens/generated/swift/Icons.xcassets
// Icons:  Lucide SVGs + custom branded SVGs, all as template imagesets
//         (template-rendering-intent = fills with current foreground color)
// Web:    getLucideIcon() / categoryUtils.ts, static/icons/*.svg
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Renders a named SVG from Icons.xcassets at the given point size.
/// The icon fills `.foregroundStyle` (template rendering — same tinting as SF Symbols).
///
/// Usage:
///   Icon("search", size: 20)          // web: search.svg
///   Icon("close", size: 16)           // web: close.svg
///   Icon("recordaudio", size: 22)     // web: recordaudio.svg
struct Icon: View {
    let name: String
    var size: CGFloat = 20

    var body: some View {
        Image(name)
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
    }
}
