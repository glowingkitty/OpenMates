// Embed sharing entry point using the shared custom Apple share panel.
// Replaces the legacy stock Form and NavigationStack implementation so embedded
// content follows the same encrypted sharing flow and visual contract as chats.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// CSS:     frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ShareEmbedView: View {
    let context: AppleShareContext
    let onClose: () -> Void
    let onGenerated: (URL, Bool, ShareDuration) async -> Void

    var body: some View {
        AppleSharePanel(
            context: context,
            onClose: onClose,
            onGenerated: onGenerated,
            onStopSharing: nil
        )
    }
}
