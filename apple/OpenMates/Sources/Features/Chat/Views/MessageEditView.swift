// Edit message — inline editing of user messages with save/cancel controls.
// Mirrors the web app's message edit flow: editable text field replaces the message bubble,
// saves via PATCH to backend, and updates the local message list on success.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatMessage.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct MessageEditView: View {
    let message: Message
    let onSave: (String) async -> Void
    let onCancel: () -> Void

    @StateObject private var composerSession: NativeComposerSession
    @State private var isSaving = false
    @State private var isFocused = false

    init(message: Message, onSave: @escaping (String) async -> Void, onCancel: @escaping () -> Void) {
        self.message = message
        self.onSave = onSave
        self.onCancel = onCancel
        self._composerSession = StateObject(
            wrappedValue: NativeComposerSession(canonicalMarkdown: message.content ?? "")
        )
    }

    private var hasChanges: Bool {
        composerSession.canonicalMarkdown != (message.content ?? "")
    }

    var body: some View {
        VStack(alignment: .trailing, spacing: .spacing3) {
            NativeComposerEditorView(
                session: composerSession,
                isFocused: $isFocused,
                isEditable: true,
                accessibilityHint: AppStrings.typeMessage,
                onSubmit: save
            )
                .frame(minHeight: 60)
                .padding(.spacing3)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
                .overlay(
                    RoundedRectangle(cornerRadius: .radius4)
                        .stroke(Color.buttonPrimary.opacity(0.5), lineWidth: 1)
                )
                .accessibleInput("Edit message", hint: "Modify the message content, then tap Save to confirm")
                .accessibilityIdentifier("native-message-edit-editor")

            HStack(spacing: .spacing3) {
                Button("Cancel") {
                    onCancel()
                }
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .accessibleButton("Cancel edit", hint: "Discards changes and closes the editor")
                .accessibilityIdentifier("native-message-edit-cancel")

                Button {
                    save()
                } label: {
                    if isSaving {
                        ProgressView()
                            .frame(width: 16, height: 16)
                            .accessibilityHidden(true)
                    } else {
                        Text(AppStrings.save)
                            .font(.omSmall).fontWeight(.medium)
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.buttonPrimary)
                .disabled(
                    !hasChanges
                        || composerSession.canonicalMarkdown.trimmingCharacters(in: .whitespaces).isEmpty
                        || composerSession.hasBlockingEmbeds
                        || isSaving
                )
                .accessibleButton(
                    isSaving ? "Saving" : "Save message",
                    hint: isSaving ? nil : "Saves the edited message"
                )
                .accessibilityIdentifier("native-message-edit-save")
            }
        }
        .padding(.spacing4)
        .onAppear { isFocused = true }
    }

    private func save() {
        isSaving = true
        Task {
            await onSave(composerSession.canonicalMarkdown)
            isSaving = false
            AccessibilityAnnouncement.announce("Message saved")
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
                    createdAt: messages[index].createdAt,
                    updatedAt: ISO8601DateFormatter().string(from: Date()),
                    appId: messages[index].appId,
                    isStreaming: messages[index].isStreaming,
                    embedRefs: messages[index].embedRefs,
                    modelName: messages[index].modelName,
                    piiMappings: messages[index].piiMappings,
                    encryptedPIIMappings: messages[index].encryptedPIIMappings
                )
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
