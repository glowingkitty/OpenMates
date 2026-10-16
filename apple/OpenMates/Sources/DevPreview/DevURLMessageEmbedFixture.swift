// Deterministic sent-user-message fixture using production URL preparation/bubble.
// Web source: frontend/packages/ui/src/components/ChatMessage.svelte
//             frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts
// CSS: frontend/packages/ui/src/styles/chat.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.persistence.client-encrypted
#if DEBUG
import SwiftUI

struct DevURLMessageEmbedFixture: View {
    let variant: String
    @State private var prepared: URLMessageEmbedPreparation.Prepared?
    @State private var route: EmbedRecord?

    private var isShare: Bool { variant.hasPrefix("url-share-") }
    private var isVideo: Bool { variant.hasSuffix("video") }
    private var records: [String: EmbedRecord] {
        Dictionary(uniqueKeysWithValues: (prepared?.embeds ?? []).map {
            let record = ComposerPendingEmbed.fromURL($0).record
            return (record.id, record)
        })
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                if let prepared {
                    let content = isShare
                        ? (try? BackgroundChatSendContract.redactedContentForSend(text: prepared.content, embeds: []).content) ?? prepared.content
                        : prepared.content
                    let message = Message(id: "url-message-fixture", chatId: "url-chat-fixture", role: .user,
                        content: content, encryptedContent: nil, createdAt: "2026-10-03T00:00:00Z",
                        updatedAt: nil, appId: nil, isStreaming: false,
                        embedRefs: prepared.embeds.map { EmbedRef(id: $0.id, type: $0.type, status: $0.status, data: nil) })
                    ScrollView {
                        MessageBubble(message: message, chatId: message.chatId, appId: nil,
                            embeds: Array(records.values), allEmbedRecords: records,
                            streamingContent: nil, thinkingContent: nil, isThinkingStreaming: false,
                            piiMappings: [], isPIIRevealed: false, containerWidth: geometry.size.width,
                            isSearchTarget: false, searchHighlightQuery: nil,
                            onEmbedTap: { route = $0 }, onOpenPublicChat: nil,
                            onInteractiveQuestionSubmit: nil, onShowActions: nil)
                            .padding(.spacing4)
                    }
                    .accessibilityIdentifier("dev-url-message-scroll")
                    .allowsHitTesting(route == nil)
                    .accessibilityHidden(route != nil)
                }
                if let route {
                    EmbedFullscreenContainer(embeds: [route], initialEmbedId: route.id,
                        allEmbedRecords: records, chatId: nil, onOpenEmbed: { _, _ in },
                        onClose: { self.route = nil })
                        .background(Color.grey0)
                        .accessibilityIdentifier("dev-url-message-fullscreen")
                }
            }
        }
        .task(id: variant) {
            let text = isVideo
                ? "https://m.youtube.com/watch?v=fThppBugFXk\nsummarize the video"
                : "Read https://example.invalid/article\nsummarize this website"
            prepared = try? await URLMessageEmbedPreparation.prepare(text: text, credits: 0,
                validate: {}, fetch: { _, _ in
                    ["title": "Public URL fixture article", "description": "A public website fixture used for URL send parity."]
                }, makeID: { "url-fixture-embed" })
        }
    }
}
#endif
