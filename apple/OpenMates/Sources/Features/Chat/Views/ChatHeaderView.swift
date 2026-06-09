// Chat header — compact inline toolbar title with app icon and chat title.
// Replaces the old 80pt hardcoded gradient banner.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHeader.svelte
//          Inline navigation-bar variant (title + small app icon in HStack).
//          The full gradient banner for new chats is implemented separately
//          in ChatBannerView.swift.
// Tokens:  GradientTokens.generated.swift  (LinearGradient.appAi, .appWeb, etc.)
//          ColorTokens.generated.swift
//          TypographyTokens.generated.swift (Font.omSmall)
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ChatHeaderView: View {
    let chat: Chat?
    let isLoading: Bool

    private var appId: String? { chat?.category ?? chat?.appId }
    private var title: String { chat?.displayTitle ?? "" }

    var body: some View {
        HStack(spacing: .spacing3) {
            if let appId {
                AppIconView(appId: appId, size: 20)
                    .accessibilityIdentifier("chat-header-icon")
            }

            VStack(alignment: .leading, spacing: 0) {
                Text(title)
                    .font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                    .accessibilityIdentifier("chat-header-title")
            }

            Spacer()

            if isLoading {
                ProgressView()
                    .scaleEffect(0.6)
            }
        }
        .padding(.horizontal, .spacing4)
    }

}
