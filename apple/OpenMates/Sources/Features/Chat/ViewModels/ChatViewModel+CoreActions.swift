// The chat view model's delete-message and fork for personal chats the Rust
// core owns (plan apple-client-core-migration A5), through `CoreChatActions`.
// The core re-reads the open window after a delete; a fork's new chat arrives
// in the core's chat list. Still Swift: Team chat forks (the core forks
// personal chats only). Send, edit and stop stay on the Swift pipeline until
// the core send takes attachments, PII mappings, queued follow-ups, temporary
// chat ids and new-chat sends.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.shell.allowed-responsibilities, client-core.apple.strangler-order

import Foundation

extension ChatViewModel {
    /// Deletes `messageId` of the shown personal chat in the core, which
    /// re-reads the open window; the Swift caches drop the row too.
    func deleteMessageThroughCore(_ messageId: String) async {
        guard let chat, canMutatePersonalMessages, ownsCoreWindow(chat.id) else {
            error = AppStrings.error
            return
        }
        let chatId = chat.id
        let scope = OfflineStore.shared.scopeGeneration
        do {
            try await coreActions.deleteMessage(chatId: chatId, messageId: messageId)
        } catch {
            if self.chat?.id == chatId, let message = CoreChatActions.userMessage(for: error) {
                self.error = message
            }
            return
        }
        // The Swift stores keep their copies until the cache lane retires them.
        guard OfflineStore.shared.scopeGeneration == scope else { return }
        do {
            try OfflineStore.shared.removeMessageIDs([messageId], from: chatId, scope: scope)
        } catch {
            NativeDiagnostics.warning("core_delete_message_local_cache_failed", category: "core_bridge")
        }
        chatStore?.removeMessageIDs([messageId], from: chatId)
        consumeForegroundMessageDeletion(chatId: chatId, messageId: messageId)
        await HighlightsManager.shared.consume(
            type: "message_deleted", fields: ["chat_id": chatId, "message_id": messageId], scope: scope)
    }

    /// Whether a fork of `chat` runs in the core (personal chats it holds).
    func canForkThroughCore(_ chat: Chat) -> Bool {
        coreActions.isAttached && canForkReadableMessages && chat.teamId == nil && ownsCoreWindow(chat.id)
    }

    /// Forks `chatId` up to and including `messageId` in the core; the new
    /// chat arrives in the core's chat list and is opened through `forkedChatId`.
    func forkThroughCore(chatId: String, messageId: String, title: String?) async -> Bool {
        do {
            let forked = try await coreActions.forkChat(chatId: chatId, messageId: messageId, title: title)
            guard self.chat?.id == chatId else { return false }
            forkedChatId = forked
            return true
        } catch {
            if self.chat?.id == chatId, let message = CoreChatActions.userMessage(for: error) {
                self.error = message
            }
            return false
        }
    }
}
