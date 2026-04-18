// Edit message store — tracks the message currently being edited in a chat.
// Mirrors the web app's editMessageStore.ts: stores the editing context so
// the input field can load the original content, and the message list can
// dim other messages during editing.

import Foundation
import SwiftUI

@MainActor
final class EditMessageStore: ObservableObject {
    static let shared = EditMessageStore()

    @Published private(set) var editingContext: EditContext?

    struct EditContext: Equatable {
        let chatId: String
        let messageId: String
        let originalContent: String
        let createdAt: String
    }

    var isEditing: Bool { editingContext != nil }
    var editingMessageId: String? { editingContext?.messageId }
    var editingChatId: String? { editingContext?.chatId }

    private init() {}

    func startEdit(chatId: String, messageId: String, content: String, createdAt: String) {
        editingContext = EditContext(
            chatId: chatId,
            messageId: messageId,
            originalContent: content,
            createdAt: createdAt
        )
    }

    func cancelEdit() {
        editingContext = nil
    }

    func completeEdit() {
        editingContext = nil
    }

    func isMessageBeingEdited(_ messageId: String) -> Bool {
        editingContext?.messageId == messageId
    }

    func isInEditMode(chatId: String) -> Bool {
        editingContext?.chatId == chatId
    }
}
