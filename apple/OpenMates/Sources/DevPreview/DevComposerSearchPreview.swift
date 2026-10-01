// Account-independent fixture for the real composer search and embed insertion.
// Web source: frontend/packages/ui/src/components/NewChatSuggestions.svelte
//             frontend/packages/ui/src/components/ChatSearchSuggestions.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.suggestions.contextual, message-input.embeds.gated-send

#if DEBUG
import SwiftUI

struct DevComposerSearchPreview: View {
    @StateObject private var store = ChatStore()
    @StateObject private var session = NativeComposerSession(canonicalMarkdown: "Berlin")
    @State private var focused = false
    @State private var action = "idle"
    @State private var openedEmbed: EmbedRecord?

    var body: some View {
        VStack(spacing: .spacing8) {
            ComposerSearchSuggestionsHost(store: store, text: ComposerPIIDecorations.visibleText(document: session.controller.document),
                authenticated: true, accountID: nil, currentChatID: "preview-current",
                onOpenChat: { action = "opened-chat:\($0)" }, onSelectEmbed: insert)
            MessageComposerView(session: session, isFocused: $focused,
                compact: false, placeholder: AppStrings.typeMessage, expandedMinHeight: 100,
                accessibilityHint: AppStrings.typeMessage, onSubmit: { action = "sent:\(session.canonicalMarkdown)" }) {
                EmptyView()
            } overlayContent: {
                EmptyView()
            } actionButtons: {
                MessageComposerSendButton(title: AppStrings.sendAction, disabled: false,
                    accessibilityLabel: AppStrings.sendMessage) { action = "sent:\(session.canonicalMarkdown)" }
            }
            Text(action).font(.omMicro).accessibilityIdentifier("composer-search-preview-action")
        }
        .overlay {
            if let openedEmbed {
                EmbedFullscreenContainer(embeds: [openedEmbed], initialEmbedId: openedEmbed.id,
                    allEmbedRecords: [openedEmbed.id: openedEmbed], chatId: nil,
                    onClose: { self.openedEmbed = nil })
            }
        }
        .onAppear {
            let chat = Chat(id: "preview-berlin", title: "Berlin travel planning", lastMessageAt: nil,
                createdAt: "2026-09-29T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
                appId: "travel", category: "travel", icon: "travel", encryptedTitle: nil, encryptedChatKey: nil)
            store.performWithoutPersistence {
                store.upsertChat(chat)
                store.upsertEmbeds([Self.fixtureEmbed], for: chat.id)
            }
        }
    }

    static var fixtureEmbed: EmbedRecord {
        EmbedRecord(id: "preview-berlin-notebook", type: "code-notebook", status: .finished,
            data: .raw(["filename": AnyCodable("berlin_bike_ride_forecast.ipynb"),
                "title": AnyCodable("Berlin bike forecast"), "code": AnyCodable("print('Synthetic Berlin forecast')")]),
            encryptedContent: nil, encryptedType: nil, encryptedTextPreview: nil, parentEmbedId: nil,
            appId: "code", skillId: nil, embedIds: nil, createdAt: "2026-09-29T12:00:00Z")
    }

    private func insert(_ result: ComposerEmbedSearchResult) {
        let nodeID = "composer:search:fixture"
        do {
            try result.insert(into: session, nodeID: nodeID)
            try session.configureEmbedActions(nodeID: nodeID, onOpen: { _ in openedEmbed = result.record },
                onRetry: { _ in }, onRemove: { _ in action = "removed-embed" })
            action = "inserted-embed:\(result.id)"
            focused = true
        } catch { action = "insertion-failed" }
    }
}
#endif
