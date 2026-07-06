// Initial OpenMates Watch root view.
// This minimal shell proves standalone watchOS target wiring before auth and
// chat runtime are introduced. It avoids hardcoded user-visible strings and
// uses generated OpenMates color and spacing tokens from the web token pipeline.
// Later spec tasks replace this loading shell with pair login and chat routing.
// The view deliberately avoids stock navigation/list chrome.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Header.svelte
// CSS:     frontend/packages/ui/src/styles/header.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct WatchRootView: View {
    var body: some View {
        ZStack {
            Color.grey100
                .ignoresSafeArea()

            Circle()
                .fill(Color.buttonPrimary)
                .frame(width: .iconSizeXl, height: .iconSizeXl)
                .overlay {
                    Circle()
                        .stroke(Color.grey0.opacity(0.82), lineWidth: 2)
                        .padding(.spacing2)
                }
                .accessibilityHidden(true)

            ProgressView()
                .controlSize(.small)
                .tint(Color.grey0)
                .offset(y: .spacing24)
                .accessibilityIdentifier("watch-root-loading-indicator")
        }
        .accessibilityIdentifier("watch-root")
    }
}

#Preview {
    WatchRootView()
}
