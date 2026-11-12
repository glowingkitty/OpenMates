// Send, edit and stop for chats rendered from the core window.
//
// The Rust core owns transport, encryption, persistence and streaming for these
// turns; this file only maps composer state to core options, starts the turn
// through `CoreChatActions` and keeps the Swift-side presentation state.
//
// Specification: specifications/features/chats/specification.yml
//   (chats.send.immediate-admission, chats.completion.independent-metadata)
// Plan: docs/plans/apple-client-core-migration

// Signed-in chats drawn from the core window send, edit and stop through the
// Rust core (`CoreChatActions`); Swift keeps only UI state: provisional title,
// follow-up chips, composer embeds, streaming flag and the admission haptic.
// The core stores the user message and the reply; nothing is persisted here.
// Plan: docs/plans/apple-client-core-migration/plan.yml
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.send.immediate-admission, chats.completion.independent-metadata
import Foundation

extension ChatViewModel {
    /// Sends or edits one user message through the core. Returns whether the
    /// core accepted the turn.
    func sendThroughCore(
        _ content: String,
        in currentChat: Chat,
        piiMappings: [PIIMapping],
        excludedPIIOriginals: Set<String>,
        excludedPIIPlaceholders: Set<String>,
        composerEmbeds explicitComposerEmbeds: [ComposerPendingEmbed]?,
        messageId: String?,
        editingMessageID: String?
    ) async -> Bool {
        let composerEmbeds = explicitComposerEmbeds ?? pendingComposerEmbeds
        let records = composerEmbeds.compactMap { CoreSendMapping.embedRecord(from: $0) }
        guard records.count == composerEmbeds.count else {
            error = AppStrings.genericProcessingError
            return false
        }
        let options = CoreSendMapping.options(
            reservedMessageId: messageId,
            embeds: records,
            excludedPiiOriginals: excludedPIIOriginals,
            excludedPiiPlaceholders: excludedPIIPlaceholders,
            piiMappings: sendPipeline.combinedPIIMappings(textMappings: piiMappings, composerEmbeds: composerEmbeds),
            projectId: nil)
        let turn: CoreChatTurn = editingMessageID.map { .edit(messageId: $0, text: content, options: options) }
            ?? .send(text: content, options: options)
        let provisionalTitle = allMessages.contains(where: { $0.role == .user })
            ? nil
            : ChatHeaderPresentation.provisionalTitle(
                from: ChatSendPipeline.provisionalTitleSource(content: content, composerEmbeds: composerEmbeds) ?? "")
        let chatId = currentChat.id
        let hapticScope = wsManager?.messageHapticScope
        let acceptance = await coreActions.startTurn(turn, chatId: chatId) { [weak self] end in
            self?.finishCoreTurn(end, chatId: chatId)
        }
        switch acceptance {
        case .accepted:
            // `.accepted` arrives when the server admitted the message, as the
            // old pipeline's admitted-and-stored haptic gate did.
            if let hapticScope {
                NativeHaptics.shared.confirmed(.messageAccepted, id: messageId ?? UUID().uuidString, scope: hapticScope)
            }
            guard chat?.id == chatId else { return true }
            if let presentedChat = chat.map({
                ChatGeneratedMetadataPolicy.applyingProvisionalTitle(provisionalTitle, to: $0)
            }) {
                chat = presentedChat
                // Plaintext provisional titles stay in memory; SwiftData never receives them.
                chatStore?.performWithoutPersistence { chatStore?.upsertChat(presentedChat) }
            }
            followUpSuggestions = ChatFollowUpSuggestionPolicy.clearForAcceptedSend(followUpSuggestions)
            if explicitComposerEmbeds != nil {
                let sentIDs = Set(composerEmbeds.map(\.id))
                pendingComposerEmbeds.removeAll { sentIDs.contains($0.id) }
            } else {
                pendingComposerEmbeds.removeAll()
            }
            isStreaming = true
            streamingContent = ""
            error = nil
            return true
        case .rejected(let failure):
            if chat?.id == chatId { error = CoreChatActions.userMessage(for: failure) }
            isStreaming = false
            return false
        case .cancelled:
            isStreaming = false
            return false
        case .noCore:
            error = AppStrings.genericProcessingError
            return false
        }
    }

    private func finishCoreTurn(_ end: CoreTurnEnd, chatId: String) {
        guard chat?.id == chatId else { return }
        switch end.outcome {
        case .completed:
            if !end.isQueued { isStreaming = false }
        case .failed(let failure):
            isStreaming = false
            if let message = CoreChatActions.userMessage(for: failure) { error = message }
        case .cancelled:
            isStreaming = false
        }
    }

    /// Cancels the running turn or reply through the core; the caller resets
    /// the presentation state.
    func stopThroughCore(chatId: String, taskId: String?) {
        streamingLifecycle.apply(.cancelRequested(chatId: chatId, taskId: taskId))
        Task { @MainActor in
            do {
                let result = try await coreActions.stop(chatId: chatId)
                if result == .nothingToStop, let taskId {
                    try await coreActions.stopReply(chatId: chatId, taskId: taskId)
                }
            } catch {
                if self.chat?.id == chatId, let message = CoreChatActions.userMessage(for: error) {
                    self.error = message
                }
            }
        }
    }
}
