// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.inline-entity-interaction, chats.persistence.client-encrypted
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.privacy.ciphertext-boundary, storage.integrity.observable-reconcilable, storage.surface.semantic-parity
// Edit message — inline editing of user messages with save/cancel controls.
// Mirrors the web app's message edit flow: editable text field replaces the message bubble,
// delegates Save to the ordinary encrypted send pipeline.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatMessage.svelte
// Svelte:  frontend/packages/ui/src/components/settings/fork/SettingsFork.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css, SettingsFork.svelte
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import CryptoKit

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
                Button(AppStrings.cancel) {
                    onCancel()
                }
                .buttonStyle(OMSecondaryButtonStyle())
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
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(
                    !hasChanges
                        || composerSession.canonicalMarkdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
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
        guard !isSaving, hasChanges, !composerSession.hasBlockingEmbeds,
              !composerSession.canonicalMarkdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        isSaving = true
        Task {
            await onSave(composerSession.canonicalMarkdown)
            isSaving = false

        }
    }
}

// Web Edit uses a normal encrypted replacement send after deleting its suffix.
// This pure plan never derives a boundary from text or a partial rendered window.
enum MessageContextActionError: Error { case unavailable, missingBoundary, staleContext, incompleteHistory }
struct MessageEditPlan {
    let retained: [Message]
    let removed: [Message]
    static func make(messages: [Message], chatID: String, messageID: String) throws -> Self {
        guard messages.allSatisfy({ $0.chatId == chatID }), Set(messages.map(\.id)).count == messages.count,
              let index = messages.firstIndex(where: { $0.id == messageID }), messages[index].role == .user else {
            throw MessageContextActionError.missingBoundary
        }
        return .init(retained: Array(messages[..<index]), removed: Array(messages[index...]))
    }
}
enum RememberMessageDraft {
    static func format(_ content: String) -> String {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "Remember my earlier message:" }
        return "Remember my earlier message:\n\n" + trimmed.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n").map { "> " + $0 }.joined(separator: "\n")
    }
    static func append(_ content: String, to draft: String) -> String {
        draft + (draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "" : "\n\n") + format(content)
    }
    static func isForgotten(_ message: Message, messages: [Message], checkpoint: Int?) -> Bool {
        guard let checkpoint else { return false }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let createdAt = fractional.date(from: message.createdAt)
            ?? ISO8601DateFormatter().date(from: message.createdAt) else { return false }
        return Int(createdAt.timeIntervalSince1970) <= checkpoint
    }

    static func latestBoundary(_ fields: [String: Any], chatID: String) -> Int? {
        var values = ((fields["compression_checkpoints_by_chat_id"] as? [String: Any])?[chatID] as? [[String: Any]]) ?? []
        if fields["chat_id"] as? String == chatID || (fields["chat_details"] as? [String: Any])?["id"] as? String == chatID {
            values += fields["compression_checkpoints"] as? [[String: Any]] ?? []
            if let checkpoint = fields["checkpoint"] as? [String: Any] { values.append(checkpoint) }
        }
        // A compression-completed plaintext summary is not a stored checkpoint.
        return values.filter { ($0["encrypted_summary"] as? String)?.isEmpty == false }
            .max(by: { ($0["created_at"] as? Int ?? 0) < ($1["created_at"] as? Int ?? 0) })?["compressed_up_to_timestamp"] as? Int
    }

}

enum MessageEditExecutor {
    static func removeSuffix(_ plan: MessageEditPlan, validate: () throws -> Void,
                             remove: (String) async throws -> Void,
                             isolation: isolated (any Actor)? = #isolation) async throws {
        // Keep the original edit boundary until its dependants are gone, so a
        // partial transport failure leaves an addressable retry boundary.
        for message in plan.removed.reversed() { try validate(); try await remove(message.id) }
        try validate()
    }
}

struct MessageForkPrepared {
    let chat: Chat
    let messages: [Message]
    let payload: [String: Any]
}
enum MessageForkPayloadBuilder {
    @MainActor static func prepare(source: Chat, messages: [Message], id: String, now: Date,
                                  key: SymmetricKey, wrappedKey: String, title requestedTitle: String? = nil, validate: () throws -> Void) async throws -> MessageForkPrepared {
        let crypto = CryptoManager.shared
        let material = (key: key, encryptedChatKey: wrappedKey)
        func optional(_ value: String?, key: SymmetricKey) async throws -> String? {
            guard let value else { return nil }; return try await crypto.encryptContent(value, key: key)
        }
        try validate()
        guard !wrappedKey.isEmpty, !messages.isEmpty, messages.allSatisfy({ $0.chatId == source.id }),
              Set(messages.map(\.id)).count == messages.count else { throw MessageContextActionError.incompleteHistory }
        let title = requestedTitle?.trimmingCharacters(in: .whitespacesAndNewlines) ?? source.title ?? AppStrings.newChat
        let encryptedTitle = try await crypto.encryptContent(title, key: material.key)
        let encryptedCategory = try await optional(source.category, key: material.key)
        let encryptedIcon = try await optional(source.icon, key: material.key)
        var history: [[String: Any]] = [], copied: [Message] = []
        for message in messages {
            try validate()
            guard let content = message.content else { throw MessageContextActionError.incompleteHistory }
            let messageID = "\(id.suffix(10))-\(UUID().uuidString)"
            let encrypted = try await crypto.encryptContent(content, key: material.key)
            let sender = try await optional(message.senderName, key: material.key)
            let category = try await optional(message.category, key: material.key)
            let model = try await optional(message.modelName, key: material.key)
            var row: [String: Any] = ["message_id": messageID, "chat_id": id, "role": message.role.rawValue,
                                     "encrypted_content": encrypted, "created_at": ChatSendPipeline.unixSeconds(from: message.createdAt)]
            row["encrypted_sender_name"] = sender; row["encrypted_category"] = category; row["encrypted_model_name"] = model
            history.append(row)
            copied.append(Message(id: messageID, chatId: id, role: message.role, content: content, encryptedContent: encrypted,
                                  createdAt: message.createdAt, updatedAt: nil, appId: message.appId, isStreaming: false,
                                  embedRefs: message.embedRefs, modelName: message.modelName, senderName: message.senderName,
                                  category: message.category, encryptedSenderName: sender, encryptedCategory: category, encryptedModelName: model))
        }
        var payload: [String: Any] = ["chat_id": id, "encrypted_chat_key": material.encryptedChatKey,
            "encrypted_title": encryptedTitle, "message_history": history,
            "versions": ["messages_v": copied.count, "title_v": 1, "last_edited_overall_timestamp": Int(now.timeIntervalSince1970)]]
        payload["encrypted_chat_category"] = encryptedCategory; payload["encrypted_icon"] = encryptedIcon
        try validate()
        let fork = Chat(id: id, title: title, lastMessageAt: copied.last?.createdAt,
            createdAt: ChatSendPipeline.isoString(from: now), updatedAt: ChatSendPipeline.isoString(from: now), isArchived: false, isPinned: false,
            appId: source.appId, category: source.category, icon: source.icon, encryptedTitle: encryptedTitle,
            encryptedCategory: encryptedCategory, encryptedIcon: encryptedIcon, encryptedChatKey: material.encryptedChatKey,
            messagesV: copied.count, titleV: 1)
        return .init(chat: fork, messages: copied, payload: payload)
    }
}

struct NativeMessageForkContext: Identifiable {
    let sourceChatID: String
    let upToMessageID: String
    let defaultTitle: String
    let messageCount: Int
    let onFork: (String) async throws -> Void
    var id: String { sourceChatID + "|" + upToMessageID }
}
struct NativeMessageForkPanel: View {
    let context: NativeMessageForkContext
    let onClose: () -> Void
    @State private var name: String
    @State private var isRunning = false
    @State private var failed = false
    init(context: NativeMessageForkContext, onClose: @escaping () -> Void) {
        self.context = context; self.onClose = onClose; _name = State(initialValue: context.defaultTitle)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            Text(AppStrings.localized("chats.fork.name_label.text")).font(.omSmall)
            TextField(AppStrings.localized("chats.fork.name_placeholder.text"), text: $name)
                .textFieldStyle(OMTextFieldStyle()).accessibilityIdentifier("message-fork-name")
            HStack {
                Text(AppStrings.localized("chats.fork.messages_label.text"))
                Spacer(); Text(String(context.messageCount))
            }.font(.omSmall)
                .accessibilityElement(children: .combine)
                .accessibilityLabel(AppStrings.localized("chats.fork.messages_label.text"))
                .accessibilityValue(String(context.messageCount))
                .accessibilityIdentifier("message-fork-count")
            if failed { Text(AppStrings.error).foregroundStyle(Color.error).accessibilityIdentifier("message-fork-error") }
            Button {
                isRunning = true; failed = false
                Task {
                    do { try await context.onFork(name); onClose() } catch { failed = true }
                    isRunning = false
                }
            } label: {
                HStack { if isRunning { ProgressView() }; Text(AppStrings.localized("chats.fork.fork_button.text")) }
            }.buttonStyle(OMPrimaryButtonStyle()).disabled(isRunning || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("message-fork-confirm")
        }.padding(.spacing6).accessibilityElement(children: .contain).accessibilityIdentifier("message-fork-panel")
    }
}


/// The same encryption boundary as the web compression checkpoint handler.
/// Plain summaries never become disk rows or Remember eligibility evidence.
@MainActor
enum MessageCompressionCheckpointRuntime {
    private struct Pending {
        let captured: MessageHighlightRuntimeScope
        let chatID: String
        let keyFingerprint: Data
        let deletionVersion: Int
        let writer: MessageCompressionCheckpointWriter
    }
    private static var pending: [String: Pending] = [:]

    private static func isCurrent(_ entry: Pending, socket: WebSocketManager, transport: Int) async -> Bool {
        let accountID = await AuthManager.currentUserId()
        guard entry.captured.scope == OfflineStore.shared.scopeGeneration,
              entry.captured.server == ServerProfile.current(),
              TeamWorkspaceContext.shared.isCurrent(entry.captured.team),
              entry.captured.team.teamID == nil || TeamWorkspaceContext.shared.selectedTeam?.canContribute == true,
              socket.transportGeneration == transport, entry.captured.accountID == accountID,
              OfflineStore.shared.chatDeletionVersion(entry.chatID) == entry.deletionVersion,
              let key = ChatKeyManager.shared.key(for: entry.chatID) else { return false }
        return Data(SHA256.hash(data: key.withUnsafeBytes { Data($0) })) == entry.keyFingerprint
    }

    private static func binding(_ captured: MessageHighlightRuntimeScope) -> MessageCompressionCheckpointJournalBinding {
        .init(accountID: captured.accountID, server: captured.server.apiBaseURL.absoluteString, teamID: captured.team.teamID)
    }

    private static func restoredWriter(chatID: String, checkpointID: String, captured: MessageHighlightRuntimeScope,
                                       key: SymmetricKey) throws -> MessageCompressionCheckpointWriter {
        guard let sealed = try OfflineStore.shared.loadCompressionCheckpointJournal(
            chatID: chatID, checkpointID: checkpointID, scope: captured.scope) else { return .init() }
        let journal = try MessageCompressionCheckpointJournal.open(sealed, using: key, binding: binding(captured),
            chatID: chatID, checkpointID: checkpointID)
        return .init(prepared: journal.prepared)
    }

    private static func retain(_ prepared: MessageCompressionCheckpointPrepared, entry: Pending, key: SymmetricKey) throws {
        if let sealed = try OfflineStore.shared.loadCompressionCheckpointJournal(
            chatID: entry.chatID, checkpointID: prepared.checkpointID, scope: entry.captured.scope) {
            let retained = try MessageCompressionCheckpointJournal.open(sealed, using: key, binding: binding(entry.captured),
                chatID: entry.chatID, checkpointID: prepared.checkpointID)
            guard retained.prepared == prepared else { throw MessageCompressionCheckpointError.changedBoundary }
            try OfflineStore.shared.retainCompressionCheckpointJournal(sealed, chatID: entry.chatID,
                checkpointID: prepared.checkpointID, scope: entry.captured.scope)
            return
        }
        let journal = MessageCompressionCheckpointJournal(binding: binding(entry.captured), prepared: prepared)
        try OfflineStore.shared.retainCompressionCheckpointJournal(journal.sealed(using: key), chatID: entry.chatID,
            checkpointID: prepared.checkpointID, scope: entry.captured.scope)
    }

    static func consume(type: String, fields: [String: Any], socket: WebSocketManager,
                        captured: MessageHighlightRuntimeScope, transport: Int) async {
        // Fanout stored events are not pending-write proof. Only the registered
        // exact request waiter below may persist its validated canonical row.
        guard type == "chat_compression_completed", let chatID = fields["chat_id"] as? String,
              !IncognitoChatSession.isIncognitoChatId(chatID) else { return }
        do {
            let proposal = try MessageCompressionCheckpointProposal(fields: fields)
            guard let summary = fields["summary_content"] as? String, !summary.isEmpty,
                  let key = ChatKeyManager.shared.key(for: chatID) else { return }
            pending = pending.filter { $0.value.captured.scope == captured.scope }
            let identity = "\(captured.scope.uuidString):\(chatID):\(proposal.checkpointID)"
            let entry: Pending
            if let retained = pending[identity], retained.captured == captured {
                entry = retained
            } else {
                entry = Pending(captured: captured, chatID: chatID, keyFingerprint: Data(SHA256.hash(data: key.withUnsafeBytes { Data($0) })),
                    deletionVersion: OfflineStore.shared.chatDeletionVersion(chatID),
                    writer: try restoredWriter(chatID: chatID, checkpointID: proposal.checkpointID, captured: captured, key: key))
                pending[identity] = entry
            }
            guard await isCurrent(entry, socket: socket, transport: transport) else { return }
            try await entry.writer.save(proposal: proposal, summary: summary, keyVersion: fields["key_version"] as? Int,
                encrypt: { try await CryptoManager.shared.encryptContent($0, key: key) },
                request: { payload, matches in
                    let receipt = try await socket.sendAndWait(
                        WSOutboundMessage(type: "store_chat_compression_checkpoint", payload: payload),
                        responseTypes: ["chat_compression_checkpoint_stored"], matching: matches,
                        beforeSend: {
                            guard await isCurrent(entry, socket: socket, transport: transport) else { throw MessageContextActionError.staleContext }
                        })
                    return receipt.fields
                }, validate: {
                    guard await isCurrent(entry, socket: socket, transport: transport) else { throw MessageContextActionError.staleContext }
                }, retain: { try retain($0, entry: entry, key: key) }, persist: {
                    try OfflineStore.shared.storeCompressionCheckpoint($0, chatID: chatID, scope: captured.scope,
                        clearingPendingCheckpointID: proposal.checkpointID)
                    notifyPersisted($0, chatID: chatID, scope: captured.scope, transport: transport)
                })
        } catch MessageCompressionCheckpointError.writeInProgress {
            // An identical event can race its existing registered waiter.
        } catch {
            NativeDiagnostics.warning("compression_checkpoint_store_failed", category: "chat")
        }
    }

    /// Call after authenticated reconnection with the new transport generation.
    /// Reuses the retained payload; neither summary encryption nor request ID is rebuilt.
    static func retryPending(socket: WebSocketManager, captured: MessageHighlightRuntimeScope, transport: Int) async {
        let accountID = await AuthManager.currentUserId()
        guard captured.scope == OfflineStore.shared.scopeGeneration, captured.server == ServerProfile.current(),
              TeamWorkspaceContext.shared.isCurrent(captured.team), socket.transportGeneration == transport,
              accountID == captured.accountID else { return }
        pending = pending.filter { $0.value.captured.scope == captured.scope }
        do {
            for record in try OfflineStore.shared.loadCompressionCheckpointJournals(scope: captured.scope) {
                let identity = "\(captured.scope.uuidString):\(record.chatID):\(record.checkpointID)"
                if let existing = pending[identity], existing.captured == captured { continue }
                guard let key = ChatKeyManager.shared.key(for: record.chatID) else { continue }
                // Wrong account, Team or rotated key never adopts or erases the journal.
                guard let writer = try? restoredWriter(chatID: record.chatID, checkpointID: record.checkpointID, captured: captured, key: key) else { continue }
                pending[identity] = Pending(captured: captured, chatID: record.chatID,
                    keyFingerprint: Data(SHA256.hash(data: key.withUnsafeBytes { Data($0) })),
                    deletionVersion: OfflineStore.shared.chatDeletionVersion(record.chatID), writer: writer)
            }
        } catch {
            NativeDiagnostics.warning("compression_checkpoint_restore_failed", category: "chat")
        }
        for entry in Array(pending.values) where entry.captured == captured && !entry.writer.isPersisted {
            guard await isCurrent(entry, socket: socket, transport: transport),
                  let key = ChatKeyManager.shared.key(for: entry.chatID), let prepared = entry.writer.prepared else { continue }
            do {
                try await entry.writer.retry(request: { payload, matches in
                    let receipt = try await socket.sendAndWait(
                        WSOutboundMessage(type: "store_chat_compression_checkpoint", payload: payload),
                        responseTypes: ["chat_compression_checkpoint_stored"], matching: matches,
                        beforeSend: {
                            guard await isCurrent(entry, socket: socket, transport: transport) else { throw MessageContextActionError.staleContext }
                        })
                    return receipt.fields
                }, validate: {
                    guard await isCurrent(entry, socket: socket, transport: transport) else { throw MessageContextActionError.staleContext }
                }, retain: { try retain($0, entry: entry, key: key) }, persist: {
                    try OfflineStore.shared.storeCompressionCheckpoint($0, chatID: entry.chatID, scope: captured.scope,
                        clearingPendingCheckpointID: prepared.checkpointID)
                    notifyPersisted($0, chatID: entry.chatID, scope: captured.scope, transport: transport)
                })
            } catch MessageCompressionCheckpointError.writeInProgress {
            } catch {
                NativeDiagnostics.warning("compression_checkpoint_retry_failed", category: "chat")
            }
        }
    }

    private static func notifyPersisted(_ row: [String: Any], chatID: String, scope: UUID, transport: Int) {
        NotificationCenter.default.post(name: .compressionCheckpointPersisted, object: nil,
            userInfo: ["accountScope": scope, "transportGeneration": transport,
                       "decoded": WebSocketResponse(fields: ["chat_id": chatID, "checkpoint": row])])
    }
}
