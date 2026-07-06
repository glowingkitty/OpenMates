// OpenMates Watch root view.
// Owns the top-level auth routing for the standalone watchOS client. Pair login
// is implemented natively on Watch while later spec slices replace the temporary
// authenticated loading shell with chat/offline sync surfaces.
// The view deliberately avoids stock navigation/list chrome.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Header.svelte
// CSS:     frontend/packages/ui/src/styles/header.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct WatchRootView: View {
    @StateObject private var authStore = WatchAuthStore()

    var body: some View {
        ZStack {
            Color.grey100
                .ignoresSafeArea()

            switch authStore.state {
            case .initializing:
                loadingView
            case .unauthenticated:
                WatchPairLoginView(authStore: authStore)
            case .authenticated:
                VStack(spacing: .spacing3) {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Color.grey0)
                    Text(WatchStrings.loadingChats)
                        .font(.omSmall)
                        .foregroundStyle(Color.grey0.opacity(0.82))
                        .multilineTextAlignment(.center)
                }
                .accessibilityIdentifier("watch-authenticated-loading")
            }
        }
        .task { await authStore.checkSession() }
        .accessibilityIdentifier("watch-root")
    }

    private var loadingView: some View {
        VStack(spacing: .spacing3) {
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
                .accessibilityIdentifier("watch-root-loading-indicator")
        }
    }
}

#Preview {
    WatchRootView()
}
