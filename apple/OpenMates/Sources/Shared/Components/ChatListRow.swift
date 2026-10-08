// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Chat list row — single row in the chat sidebar.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.drafts.preview-persistence

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/chats/Chat.svelte
// Preview: frontend/packages/ui/src/utils/draftPreview.ts
//          frontend/packages/ui/src/services/drafts/draftSave.ts
// CSS:     frontend/packages/ui/src/components/chats/Chat.svelte <style>
//          .category-circle-wrapper { flex:0 0 28px; height:28px }
//          .category-circle { width:28px; height:28px; border-radius:50%;
//            box-shadow:0 2px 4px rgba(0,0,0,.1); border:2px solid var(--color-background) }
//          .chat-title { font-size:var(--font-size-p); font-weight:500 }
//          Ordinary titled chats have no timestamp/status line; drafts use status-message.
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ChatListRow: View {
    let chat: Chat
    @ObservedObject private var unreadStore = UnreadMessagesStore.shared
    let processing: Bool
    let activeSubChatCount: Int
    let suppliedDraftPreview: String?
    private let formattedDraftPreview: String?

    init(chat: Chat, suppliedDraftPreview: String? = nil, processing: Bool = false, activeSubChatCount: Int = 0) {
        self.chat = chat; self.suppliedDraftPreview = suppliedDraftPreview
        self.processing = processing; self.activeSubChatCount = activeSubChatCount
        let preview = ChatDraftPreviewFormatter.format(suppliedDraftPreview)
        formattedDraftPreview = preview.isEmpty ? nil : preview
    }

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
        return formattedDraftPreview
    }

    private var isDraftOnly: Bool { ChatSidebarDisplayPolicy.isDraftOnly(chat, preview: formattedDraftPreview) }
    private var titleForDisplay: String { isDraftOnly ? AppStrings.draftBadge : chat.displayTitle }

    var body: some View {
        HStack(spacing: 16) {
            if isSubChatRow {
                Rectangle()
                    .fill(Color.grey40)
                    .frame(width: 2, height: 28)
                    .padding(.leading, .spacing4)
                    .accessibilityHidden(true)
            }

            if !isDraftOnly {
            Group {
            if processing { ChatProcessingWheel() }
            else if let descriptor = publicIconDescriptor {
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

            }
            // Web .unread-badge: 21px circle, bottom/right -2px, small medium text.
            .overlay(alignment: .bottomTrailing) {
                if let text = ChatSidebarDisplayPolicy.unreadBadgeText(
                    count: unreadStore.getUnreadCount(chatId: chat.id), processing: processing, draftOnly: isDraftOnly) {
                    Text(text)
                        .font(.omSmall).fontWeight(.medium).foregroundStyle(.white)
                        .frame(width: 21, height: 21)
                        .background(Circle().fill(Color.buttonPrimary))
                        .overlay { Circle().stroke(Color.grey0, lineWidth: 2) }
                        .offset(x: 2, y: 2)
                        .accessibilityIdentifier("unread-badge")
                }
            }
            .accessibilityIdentifier("chat-row-profile")
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(titleForDisplay)
                    .font(isDraftOnly ? .omXs : .omP)
                    .fontWeight(.medium)
                    .foregroundStyle(isDraftOnly ? Color.fontTertiary : Color.fontPrimary)
                    .accessibilityIdentifier(isDraftOnly ? "chat-draft-status" : "chat-row-title")
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 2)

                if activeSubChatCount > 0 {
                    Text(LocalizationManager.shared.text(activeSubChatCount == 1 ? "chats.activity.subchats_single" : "chats.activity.subchats", replacements: ["count": String(activeSubChatCount)]))
                        .font(.omXs).foregroundStyle(Color.fontSecondary).accessibilityIdentifier("running-subchat-count")
                }
                if let preview = isDraftOnly ? formattedDraftPreview : draftPreview, preview != titleForDisplay {
                    Text(preview)
                        .font(isDraftOnly ? .omP : .omXs)
                        .foregroundStyle(isDraftOnly ? Color.fontPrimary : Color.fontTertiary)
                        .accessibilityIdentifier("chat-draft-preview")
                        .lineLimit(1)

                }
            }.frame(maxWidth: .infinity, alignment: .leading)

            if chat.isPinned == true {
                Icon("pin", size: 12)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.vertical, 12)
        .padding(.leading, isSubChatRow ? 40 : 16)
        .padding(.trailing, 16)
        // The full row, including spacing around title and draft, opens
        // the chat. Text-only hit regions dropped valid search-result taps.
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(isSubChatRow ? "sub-chat-item" : "chat-item-wrapper")
        .accessibilityValue(accessibilityValue)
        .accessibilityLabel("\(titleForDisplay)\(isDraftOnly ? formattedDraftPreview.map { ": " + $0 } ?? "" : "")\(isSubChatRow ? ", sub-chat" : "")\(chat.isPinned == true ? ", pinned" : "")")
        .accessibilityHint("Double tap to open, long press for options")
    }
}

/// Presentation only: decrypting and storing the canonical draft stay unchanged.
/// Parse once when the row receives a preview, never from its SwiftUI body.
@MainActor
enum ChatDraftPreviewFormatter {
    private static let fences = try! NSRegularExpression(pattern: "```(?:json|json_embed)\\b\\s*([\\s\\S]*?)(?:```|$)")
    private static let referenceObjects = try! NSRegularExpression(pattern: #"\{[^{}]*"embed_id"\s*:[^{}]*\}"#)
    private static let referenceLinks = try! NSRegularExpression(pattern: #"\[[^\]]*\]\(embed:[^)]+\)"#)
    private static let typeField = try! NSRegularExpression(pattern: #""type"\s*:\s*"([a-zA-Z0-9_-]+)""#)
    private static let markers = try! NSRegularExpression(pattern: "<<<TEST_LIVE_MOCK:[^>]+>>>")
    private static let knownTypes: Set<String> = ["image", "audio", "audio-recording", "recording", "website", "web-website", "video", "videos-video", "location", "maps", "pdf", "file", "book", "code", "code-code", "code-code-group"]

    static func format(_ value: String?) -> String {
        guard let value, !value.isEmpty else { return "" }
        var text = value
        if let data = value.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if object["type"] as? String == "doc", let content = object["content"] as? [[String: Any]] {
                text = content.map(tiptapText).joined(separator: " ")
            } else if object["version"] as? Int == 1, let nodes = object["nodes"] as? [[String: Any]],
                      nodes.allSatisfy({ ["text", "embed", "mention", "hardBreak"].contains($0["kind"] as? String ?? "") }) {
                text = nodes.map { node in
                    switch node["kind"] as? String {
                    case "embed": return " \(label(node["embedType"] as? String)) "
                    case "mention": return node["displayLabel"] as? String ?? node["canonicalSyntax"] as? String ?? ""
                    case "hardBreak": return " "
                    default: return node["source"] as? String ?? ""
                    }
                }.joined()
            }
        }
        text = replacing(markers, in: text) { _ in " " }
        text = replacing(fences, in: text) { match in
            let content = (text as NSString).substring(with: match.range(at: 1))
            return " \(referenceLabel(content, fallback: "code")) "
        }
        text = replacing(referenceObjects, in: text) { match in
            " \(referenceLabel((text as NSString).substring(with: match.range), fallback: nil)) "
        }
        // Legacy clients truncated preview strings before closing the JSON/fence.
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.hasPrefix("{"), trimmed.contains("\"embed_id\""), typeField.firstMatch(in: trimmed, range: NSRange(trimmed.startIndex..., in: trimmed)) != nil {
            text = referenceLabel(trimmed, fallback: nil)
        }
        text = replacing(referenceLinks, in: text) { _ in " \(label(nil)) " }
        return text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    private static func tiptapText(_ node: [String: Any]) -> String {
        let type = node["type"] as? String ?? ""
        let attrs = node["attrs"] as? [String: Any] ?? [:]
        switch type {
        case "text": return node["text"] as? String ?? ""
        case "hardBreak": return " "
        case "embed", "embedPreview", "embedPreviewLarge":
            return " \(label(attrs["type"] as? String ?? attrs["embedType"] as? String)) "
        case "mention": return attrs["label"] as? String ?? attrs["displayLabel"] as? String ?? attrs["canonicalSyntax"] as? String ?? ""
        case "codeBlock": return " \(label("code")) "
        default:
            let content = node["content"] as? [[String: Any]] ?? []
            let separator = ["doc", "blockquote", "bulletList", "orderedList", "listItem"].contains(type) ? " " : ""
            return content.map(tiptapText).joined(separator: separator)
        }
    }

    private static func referenceLabel(_ content: String, fallback: String?) -> String {
        guard let match = typeField.firstMatch(in: content, range: NSRange(content.startIndex..., in: content)) else {
            return label(content.contains("\"embed_id\"") ? nil : fallback)
        }
        let type = (content as NSString).substring(with: match.range(at: 1))
        return label(content.contains("\"embed_id\"") || knownTypes.contains(type) ? type : fallback)
    }

    private static func label(_ type: String?) -> String {
        AppStrings.draftEmbedPreviewLabel(type: type ?? "embed")
    }

    private static func replacing(_ regex: NSRegularExpression, in text: String, replacement: (NSTextCheckingResult) -> String) -> String {
        var result = text
        for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
            guard let range = Range(match.range, in: result) else { continue }
            result.replaceSubrange(range, with: replacement(match))
        }
        return result
    }
}
