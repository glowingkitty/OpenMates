// OpenMates Watch root view.
// Owns the top-level auth routing for the standalone watchOS client. Pair login
// is implemented natively on Watch and authenticated users enter the Watch chat
// shell backed by direct backend refresh plus local offline cache.
// The view deliberately avoids stock navigation/list chrome.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Header.svelte
// CSS:     frontend/packages/ui/src/styles/header.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct WatchRootView: View {
    @StateObject private var authStore = WatchAuthStore()
    @StateObject private var phoneBridge = WatchPhoneLoginBridge.shared

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
                WatchHubView(
                    currentUserId: authStore.currentUser?.id,
                    currentUsername: authStore.currentUser?.username,
                    webSocketToken: authStore.webSocketToken,
                    onOpenItem: { request in
                        _ = phoneBridge.sendItemOpenRequest(request)
                    },
                    onOpenSettings: {
                        _ = phoneBridge.sendSettingsOpenRequest()
                    },
                    onCreate: { section in
                        switch section {
                        case .tasks: _ = phoneBridge.sendCollectionOpenRequest(kind: .task)
                        case .workflows: _ = phoneBridge.sendCollectionOpenRequest(kind: .workflow)
                        case .chat: break
                        }
                    }
                )
                .task { phoneBridge.start(onApproval: { _ in }, onAcknowledgment: { _ in }) }
            }
        }
        .task { await authStore.checkSession() }
        .accessibilityElement(children: .contain)
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
