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

    private struct PublicIconDescriptor {
        let icon: String
        let gradient: LinearGradient
    }

    private var publicIconDescriptor: PublicIconDescriptor? {
        switch chat.id {
        case "demo-for-everyone":
            return .init(icon: "hand", gradient: CategoryMapping.gradient(for: "openmates_official"))
        case "demo-for-developers":
            return .init(icon: "code", gradient: CategoryMapping.gradient(for: "openmates_official"))
        case "demo-who-develops-openmates":
            return .init(icon: "user", gradient: CategoryMapping.gradient(for: "openmates_official"))
        case "announcements-introducing-openmates-v09":
            return .init(icon: "megaphone", gradient: CategoryMapping.gradient(for: "openmates_official"))
        case "legal-privacy":
            return .init(icon: "shield-check", gradient: CategoryMapping.gradient(for: "openmates_official"))
        case "legal-terms":
            return .init(icon: "file-text", gradient: CategoryMapping.gradient(for: "openmates_official"))
        case "legal-imprint":
            return .init(icon: "building", gradient: CategoryMapping.gradient(for: "openmates_official"))
        case "example-gigantic-airplanes":
            return .init(icon: "plane", gradient: CategoryMapping.gradient(for: "general_knowledge"))
        case "example-artemis-ii-mission":
            return .init(icon: "rocket", gradient: CategoryMapping.gradient(for: "science"))
        case "example-beautiful-single-page-html":
            return .init(icon: "code", gradient: CategoryMapping.gradient(for: "software_development"))
        case "example-eu-chat-control-law":
            return .init(icon: "shield", gradient: CategoryMapping.gradient(for: "legal_law"))
        case "example-flights-berlin-bangkok":
            return .init(icon: "plane", gradient: CategoryMapping.gradient(for: "general_knowledge"))
        case "example-creativity-drawing-meetups-berlin":
            return .init(icon: "pencil", gradient: CategoryMapping.gradient(for: "general_knowledge"))
        default:
            return nil
        }
    }

    var body: some View {
        HStack(spacing: .spacing4) {
            if let descriptor = publicIconDescriptor {
                Circle()
                    .fill(descriptor.gradient)
                    .frame(width: 28, height: 28)
                    .overlay {
                        LucideNativeIcon(descriptor.icon, size: 16)
                            .foregroundStyle(.white)
                    }
                    .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 2)
            } else if let appId = chat.appId {
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

                // Hide timestamps for demo/example/legal chats (static content)
                if let date = chat.lastMessageDate, !chat.id.hasPrefix("demo-"),
                   !chat.id.hasPrefix("example-"), !chat.id.hasPrefix("legal-"),
                   !chat.id.hasPrefix("announcements-") {
                    Text(date, style: .relative)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }
            }

            Spacer()

            if chat.isPinned == true {
                Icon("pin", size: 12)
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
