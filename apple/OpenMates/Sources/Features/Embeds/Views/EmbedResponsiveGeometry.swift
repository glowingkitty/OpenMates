// Size allocation for responsive result panels and fixed preview footers.
// Web: frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//      frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
//      frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.layout.responsive-history

import SwiftUI

enum EmbedPreviewFooterLayout {
    static let height: CGFloat = 61

    static func detailsHeight(cardHeight: CGFloat) -> CGFloat {
        max(0, cardHeight - height)
    }
}

enum EmbedCalendarColumnLayout {
    /// Preserve the minimum readable overlap lanes on phones. A wide calendar
    /// distributes its remaining measured viewport width across all seven days.
    static func widths(minimumWidths: [CGFloat], availableWidth: CGFloat,
                       hasTimeColumn: Bool) -> [CGFloat] {
        guard !minimumWidths.isEmpty else { return [] }
        let timeWidth: CGFloat = hasTimeColumn ? 44 : 0
        let remaining = max(0, availableWidth - timeWidth - minimumWidths.reduce(0, +))
        let addition = remaining / CGFloat(minimumWidths.count)
        return minimumWidths.map { $0 + addition }
    }
}

#if DEBUG
/// The fixture reads actual production geometry; these preferences do not
/// participate in product layout or replace any visible card controls.
struct EmbedPreviewGeometryKey: PreferenceKey {
    static let defaultValue: [String: CGRect] = [:]
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, next in next })
    }
}

struct EmbedPreviewGeometryProbe: View {
    let name: String
    var body: some View {
        GeometryReader { geometry in
            Color.clear.preference(key: EmbedPreviewGeometryKey.self,
                value: [name: geometry.frame(in: .named("responsive-preview-fixture"))])
        }
        .allowsHitTesting(false).accessibilityHidden(true)
    }
}
#endif
