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
    @ObservedObject private var draftService = DraftService.shared

    private struct PublicIconDescriptor {
        let icon: String
        let gradient: LinearGradient
        var usesAssetIcon = false
    }

    private var publicIconDescriptor: PublicIconDescriptor? {
        switch chat.id {
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

    private var accessibilityScope: String {
        if isSubChatRow { return "sub-chat" }
        if chat.id.hasPrefix("demo-") || chat.id.hasPrefix("example-") ||
            chat.id.hasPrefix("announcements-") || chat.id.hasPrefix("tips-") ||
            chat.id.hasPrefix("legal-") {
            return "public-chat"
        }
        return "user-chat"
    }

    private var accessibilityValue: String {
        guard accessibilityScope == "user-chat",
              ProcessInfo.processInfo.arguments.contains("--ui-test-expose-chat-ids") else {
            return accessibilityScope
        }
        return "user-chat:\(chat.id)"
    }

    private var isSubChatRow: Bool {
        chat.isSubChat == true || chat.parentId != nil
    }

    private var draftPreview: String? {
        guard (chat.draftV ?? 0) > 0 else { return nil }
        let preview = draftService.draftPreview(chatId: chat.id)?.trimmingCharacters(in: .whitespacesAndNewlines)
        return preview?.isEmpty == false ? preview : nil
    }

    private var titleForDisplay: String {
        let title = chat.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if title.isEmpty, let draftPreview {
            return draftPreview
        }
        return chat.displayTitle
    }

    var body: some View {
        HStack(spacing: .spacing4) {
            if isSubChatRow {
                Rectangle()
                    .fill(Color.grey40)
                    .frame(width: 2, height: 28)
                    .padding(.leading, .spacing4)
                    .accessibilityHidden(true)
            }

            if let descriptor = publicIconDescriptor {
                Circle()
                    .fill(descriptor.gradient)
                    .frame(width: 28, height: 28)
                    .overlay {
                        if descriptor.usesAssetIcon {
                            Icon(descriptor.icon, size: 16)
                                .foregroundStyle(.white)
                        } else {
                            LucideNativeIcon(descriptor.icon, size: 16)
                                .foregroundStyle(.white)
                        }
                    }
                    .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 2)
            } else if let category = chat.category, !category.isEmpty {
                Circle()
                    .fill(CategoryMapping.gradient(for: category))
                    .frame(width: 28, height: 28)
                    .overlay {
                        LucideNativeIcon(chat.icon ?? CategoryMapping.lucideIconName(for: category), size: 16)
                            .foregroundStyle(.white)
                    }
                    .overlay {
                        Circle()
                            .stroke(Color.grey0, lineWidth: 2)
                    }
                    .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 2)
            } else {
                Circle()
                    .fill(Color.grey40)
                    .frame(width: 28, height: 28)
                    .overlay {
                        LucideNativeIcon("help-circle", size: 16)
                            .foregroundStyle(.white)
                    }
                    .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 2)
            }

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(titleForDisplay)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)

                if let preview = draftPreview, preview != titleForDisplay {
                    Text(preview)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                        .lineLimit(1)
                // Hide timestamps for demo/example/legal chats (static content)
                } else if let date = chat.lastMessageDate, !chat.id.hasPrefix("demo-"),
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
        .padding(.leading, isSubChatRow ? .spacing10 : .spacing6)
        .padding(.trailing, .spacing6)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(isSubChatRow ? "sub-chat-item" : "chat-item-wrapper")
        .accessibilityValue(accessibilityValue)
        .accessibilityLabel("\(titleForDisplay)\(isSubChatRow ? ", sub-chat" : "")\(chat.isPinned == true ? ", pinned" : "")")
        .accessibilityHint("Double tap to open, long press for options")
    }
}
