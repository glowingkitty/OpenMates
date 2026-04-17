// Edit message — inline editing of user messages with save/cancel controls.
// Mirrors the web app's message edit flow: editable text field replaces the message bubble,
// saves via PATCH to backend, and updates the local message list on success.

import SwiftUI

struct MessageEditView: View {
    let message: Message
    let onSave: (String) async -> Void
    let onCancel: () -> Void

    @State private var editedContent: String
    @State private var isSaving = false
    @FocusState private var isFocused: Bool

    init(message: Message, onSave: @escaping (String) async -> Void, onCancel: @escaping () -> Void) {
        self.message = message
        self.onSave = onSave
        self.onCancel = onCancel
        self._editedContent = State(initialValue: message.content ?? "")
    }

    private var hasChanges: Bool {
        editedContent != (message.content ?? "")
    }

    var body: some View {
        VStack(alignment: .trailing, spacing: .spacing3) {
            TextEditor(text: $editedContent)
                .font(.omP)
                .frame(minHeight: 60)
                .padding(.spacing3)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
                .focused($isFocused)
                .overlay(
                    RoundedRectangle(cornerRadius: .radius4)
                        .stroke(Color.buttonPrimary.opacity(0.5), lineWidth: 1)
                )

            HStack(spacing: .spacing3) {
                Button("Cancel") {
                    onCancel()
                }
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)

                Button {
                    save()
                } label: {
                    if isSaving {
                        ProgressView()
                            .frame(width: 16, height: 16)
                    } else {
                        Text("Save")
                            .font(.omSmall).fontWeight(.medium)
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.buttonPrimary)
                .disabled(!hasChanges || editedContent.trimmingCharacters(in: .whitespaces).isEmpty || isSaving)
            }
        }
        .padding(.spacing4)
        .onAppear { isFocused = true }
    }

    private func save() {
        isSaving = true
        Task {
            await onSave(editedContent)
            isSaving = false
        }
    }
}

// MARK: - ViewModel extension for editing

extension ChatViewModel {
    func editMessage(_ messageId: String, newContent: String) async {
        guard let chatId = chat?.id else { return }
        do {
            let _: Data = try await APIClient.shared.request(
                .patch, path: "/v1/chats/\(chatId)/messages/\(messageId)",
                body: ["content": newContent]
            )
            if let index = messages.firstIndex(where: { $0.id == messageId }) {
                messages[index] = Message(
                    id: messages[index].id,
                    chatId: messages[index].chatId,
                    role: messages[index].role,
                    content: newContent,
                    encryptedContent: messages[index].encryptedContent,
                    contentIv: messages[index].contentIv,
                    createdAt: messages[index].createdAt,
                    updatedAt: ISO8601DateFormatter().string(from: Date()),
                    appId: messages[index].appId,
                    isStreaming: messages[index].isStreaming,
                    embedRefs: messages[index].embedRefs
                )
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
