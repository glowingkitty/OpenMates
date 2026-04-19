// Chat list row — single row in the chat sidebar.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/chats/Chat.svelte
// CSS:     frontend/packages/ui/src/components/chats/Chat.svelte <style>
//          .category-circle-wrapper { flex:0 0 28px; height:28px }
//          .category-circle { width:28px; height:28px; border-radius:50%;
//            box-shadow:0 2px 4px rgba(0,0,0,.1); border:2px solid var(--color-background) }
//          .chat-title { font-size:var(--font-size-p); font-weight:500 }
//          .chat-time  { font-size:14px; color:var(--color-font-tertiary) }
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ChatListRow: View {
    let chat: Chat

    var body: some View {
        HStack(spacing: .spacing4) {
            if let appId = chat.appId {
                AppIconView(appId: appId, size: 28)
                    .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 2)
            } else {
                Circle()
                    .fill(LinearGradient.primary)
                    .frame(width: 28, height: 28)
                    .overlay {
                        Image.iconChat
                            .resizable()
                            .frame(width: 16, height: 16)
                            .foregroundStyle(.white)
                    }
                    .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 2)
            }

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(chat.displayTitle)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)

                if let date = chat.lastMessageDate {
                    Text(date, style: .relative)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }
            }

            Spacer()

            if chat.isPinned == true {
                Image(systemName: SFSymbol.pin)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.vertical, .spacing4)
        .padding(.horizontal, .spacing6)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("chat-item-wrapper")
        .accessibilityLabel("\(chat.displayTitle)\(chat.isPinned == true ? ", pinned" : "")")
        .accessibilityHint("Double tap to open, long press for options")
    }
}
