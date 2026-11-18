// ImageVersionBadge — the "v2" pill on a generated-image card that has more
// than one version, plus the pure label rule. The version and head numbers
// come from the Rust core (embed head / version history); this file only
// decides the label and draws the pill.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
//          ({#if versionBadge} <span class="version-badge" data-testid="image-generate-version-badge">)
//          frontend/packages/ui/src/components/embeds/images/imageVersionScope.ts (versionBadgeLabel)
// CSS:     ImageGenerateEmbedPreview.svelte <style>: .version-badge
// Tokens:  SpacingTokens (spacing1, spacing3, spacing4), radius2, Font.omTiny, Color.fontButton
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/images-generate/specification.yml
// Assertions: images-generate.revision.message-shows-its-version

import SwiftUI

enum ImageVersionBadgeState {
    /// `versionBadgeLabel`: only when the image has more than one version.
    static func label(version: Int?, headVersion: Int?) -> String? {
        guard let version, version > 0, let headVersion, headVersion > 1 else { return nil }
        return "v\(version)"
    }

    /// Version and head of the stored embed record (the core's head version and
    /// version history); the card shows the head until a message pins a version.
    static func versions(of embed: EmbedRecord) -> (version: Int?, head: Int?) {
        let head = embed.versionHistory.map(\.versionNumber).max() ?? embed.versionNumber
        return (embed.versionNumber ?? head, max(head ?? 0, embed.versionNumber ?? 0))
    }
}

struct ImageVersionBadge: View {
    let version: Int?
    let headVersion: Int?

    var body: some View {
        if let label = ImageVersionBadgeState.label(version: version, headVersion: headVersion) {
            Text(label)
                .font(.omTiny)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontButton)
                .padding(.vertical, .spacing1)
                .padding(.horizontal, .spacing3)
                .background(Color.black.opacity(0.55))
                .clipShape(RoundedRectangle(cornerRadius: .radius2))
                .padding(.spacing4)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .allowsHitTesting(false)
                .accessibilityIdentifier("image-generate-version-badge")
        }
    }
}
