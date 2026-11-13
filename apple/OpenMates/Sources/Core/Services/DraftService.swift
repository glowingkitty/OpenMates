// Native composer drafts: the server copy goes through the Rust core, the
// device keeps an encrypted read-back copy for the composer.
// Saving and clearing a draft is sent to the core (`CoreDrafts`: encryption,
// sync, versions, tombstones and the sidebar row with its preview live there).
// The composer's own copy (markdown, preview and the embed companion,
// master-key Format D ciphertext in `OfflineStore`) restores the composer at
// once when a chat opens; `refreshFromCore` then reads the core's draft and
// adopts it unless the local copy holds edits the core has not received
// (a save of this device the core has not completed, or a local version at
// or above the core's with other text, or a never-synced copy against no core
// draft): then the local copy wins and is sent again. A draft saved or cleared
// on another device (`CoreDrafts.remoteChanges`) replaces or removes the local
// copy under the same "unsent local edits win" rule and asks an open composer
// to reload; the composer skips the reload while its own typing is unsaved.
// The local encrypted copy stays because the core has no offline draft outbox yet.
// The new-chat composer's selected draft-only chat id (an alias) is view state
// kept here. Old plaintext drafts of earlier installs are dropped, not migrated.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.drafts.preview-persistence, message-input.recording.lifecycle
// Specification: specifications/architecture/drafts/specification.yml
// Assertions: drafts.persistence.local-first-encrypted, drafts.draft-only.lifecycle
// Assertions: drafts.draft-only.presentation, drafts.sync.version-authoritative

import Combine
import CryptoKit
import Foundation

extension Notification.Name {
    static let composerDraftDidChange = Notification.Name("openmates.composerDraftDidChange")
}

/// Local cleanup of a draft-only chat whose draft was cleared (no keys,
/// messages or billing entries of a real chat are touched).
@MainActor
protocol DraftOnlyChatCleanup: AnyObject {
    func cascadeDeleteDraftOnlyChat(chatId: String)
}

@MainActor
final class DraftService: ObservableObject {
    /// The new-chat composer's draft before it has a chat id.
    static let syntheticNewChatId = "composer:new-chat"
    /// UserDefaults key of plaintext drafts written by old installs.
    private static let legacyPlaintextDraftsKey = "openmates.drafts"

    static let shared = DraftService(
        repository: OfflineStore.shared,
        masterKeyProvider: {
            guard let userId = await AuthManager.currentUserId() else { return nil }
            return try await CryptoManager.shared.loadMasterKey(for: userId)
        }
    )

    @Published private(set) var currentDraft = ""
    @Published private(set) var draftPreviews: [String: String] = [:] {
        didSet {
            // Cache display text when a draft changes, never from a SwiftUI body.
            displayDraftPreviews = displayDraftPreviews.filter { draftPreviews[$0.key] != nil }
            for (chatID, preview) in draftPreviews where oldValue[chatID] != preview {
                displayDraftPreviews[chatID] = ChatDraftPreviewFormatter.format(preview)
            }
        }
    }
    @Published private(set) var displayDraftPreviews: [String: String] = [:]
    private var displayLocaleSubscription: AnyCancellable?
    private var remoteDraftSubscription: AnyCancellable?

    private let repository: any ComposerDraftRepository
    private let masterKeyProvider: @Sendable () async throws -> SymmetricKey?
    private let crypto: CryptoManager
    private let coreDrafts: CoreDrafts
    private weak var chatStore: ChatStore?
    private weak var draftOnlyCleanup: (any DraftOnlyChatCleanup)?
    private var newChatDraftId: String?
    private var draftLifecycleGeneration = UUID()
    private var draftGenerationByChatId: [String: UUID] = [:]
    private var draftReadGenerationByChatId: [String: UUID] = [:]

    private var newChatSelectionStorageKey: String? {
        guard let scopeId = OfflineStore.shared.activeScopeId else { return nil }
        let digest = SHA256.hash(data: Data(scopeId.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return "openmates.active-new-chat-draft.\(digest)"
    }

    private var storedNewChatDraftId: String? {
        guard let key = newChatSelectionStorageKey else { return nil }
        return UserDefaults.standard.string(forKey: key)
    }

    private func persistNewChatDraftId(_ id: String?) {
        guard let key = newChatSelectionStorageKey else { return }
        if let id {
            UserDefaults.standard.set(id, forKey: key)
        } else {
            UserDefaults.standard.removeObject(forKey: key)
        }
    }

    /// `coreDrafts` defaults to the app's `CoreDrafts.shared`; tests pass their own.
    init(
        repository: any ComposerDraftRepository,
        masterKeyProvider: @escaping @Sendable () async throws -> SymmetricKey?,
        coreDrafts: CoreDrafts? = nil
    ) {
        self.repository = repository
        self.masterKeyProvider = masterKeyProvider
        self.crypto = CryptoManager.shared
        self.coreDrafts = coreDrafts ?? .shared
        displayLocaleSubscription = LocalizationManager.shared.$currentLanguage.dropFirst().sink { [weak self] _ in
            guard let self else { return }
            self.displayDraftPreviews = self.draftPreviews.mapValues { ChatDraftPreviewFormatter.format($0) }
        }
        remoteDraftSubscription = self.coreDrafts.remoteChanges.sink { [weak self] change in
            Task { @MainActor [weak self] in
                await self?.applyRemoteDraft(change)
            }
        }
    }

    /// Binds the account's chat store and restores the composer copies'
    /// previews and draft presence into it after sign-in.
    func configure(chatStore: ChatStore, draftOnlyCleanup: any DraftOnlyChatCleanup) {
        UserDefaults.standard.removeObject(forKey: Self.legacyPlaintextDraftsKey)
        let lifecycle = draftLifecycleGeneration
        let scope = OfflineStore.shared.scopeGeneration
        self.chatStore = chatStore
        self.draftOnlyCleanup = draftOnlyCleanup
        Task { [weak self] in
            guard let self else { return }
            do {
                let records = try await repository.allRecords()
                guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
                      scope == OfflineStore.shared.scopeGeneration else { return }
                restoreNewChatDraftId(
                    from: records,
                    cachedChats: records.compactMap { OfflineStore.shared.loadChat(id: $0.chatId) },
                    preferredId: storedNewChatDraftId
                )
                persistNewChatDraftId(newChatDraftId)
                for record in records {
                    guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
                          scope == OfflineStore.shared.scopeGeneration else { return }
                    // A local draft supplies local presence and can bring its
                    // older cached chat metadata into this session.
                    if chatStore.chat(for: record.chatId) == nil,
                       let cached = OfflineStore.shared.loadChat(id: record.chatId) {
                        chatStore.performWithoutPersistence { chatStore.upsertChat(cached) }
                    }
                    chatStore.updateDraftVersion(chatId: record.chatId, draftVersion: record.draftVersion,
                                                 hasNonEmptyDraft: !record.encryptedMarkdown.isEmpty)
                    await refreshDraftState(chatId: record.chatId)
                }
            } catch {
                NativeDiagnostics.warning(
                    "Draft preview hydration failed errorType=\(type(of: error))",
                    category: "composer_drafts"
                )
            }
        }
    }

    var activeNewChatDraftId: String? {
        newChatDraftId
    }

    func reserveNewChatDraftId(preferredId: String) -> String {
        let resolved = newChatDraftId ?? preferredId
        newChatDraftId = resolved
        persistNewChatDraftId(resolved)
        return resolved
    }

    /// Starts another new-chat composer without deleting the previous draft.
    /// The old id stays a draft-only chat that can be resumed from the chat
    /// list; only the new-chat alias moves forward.
    func beginFreshNewChatDraft(preferredId: String) -> String {
        newChatDraftId = preferredId
        persistNewChatDraftId(preferredId)
        return preferredId
    }

    /// A window may finish its own new-chat draft after another window has
    /// moved the alias. Release only the matching selection.
    func releaseNewChatDraftId(ifMatches chatId: String) {
        guard newChatDraftId == chatId else { return }
        newChatDraftId = nil
        persistNewChatDraftId(nil)
    }

    /// Saves the composer copy of `chatId`, then sends the draft to the core.
    /// Throws only for the local copy; a failed core call is logged by
    /// `CoreDrafts` and repeated by the next save.
    func saveDraft(
        canonicalMarkdown: String,
        preview: String,
        chatId: String,
        revision: Int,
        draftVersion: Int,
        useStoredDraftVersion: Bool = false,
        recordings: [EmbedRecord]? = nil,
        attachments: [ComposerDraftAttachment]? = nil
    ) async throws {
        guard ComposerDraftContentPolicy.hasContent(canonicalMarkdown) else {
            try await clearDraft(chatId: chatId)
            return
        }
        let resolvedChatId = resolveChatId(chatId, hasNonEmptyDraft: true)
        if chatId == Self.syntheticNewChatId {
            persistNewChatDraftId(resolvedChatId)
        }
        let lifecycle = draftLifecycleGeneration
        let draftGeneration = draftGenerationByChatId[resolvedChatId]
        let scopeGeneration = OfflineStore.shared.scopeGeneration
        func requireCurrentSave() throws {
            guard !Task.isCancelled,
                  lifecycle == draftLifecycleGeneration,
                  draftGeneration == draftGenerationByChatId[resolvedChatId],
                  scopeGeneration == OfflineStore.shared.scopeGeneration else {
                throw CancellationError()
            }
        }
        // The server version is the core's; the composer copy keeps the
        // highest version it was given only for the local chat row.
        var effectiveDraftVersion = draftVersion
        var existingRecord: ComposerDraftRecord?
        do {
            if let existing = try await repository.record(chatId: resolvedChatId) {
                existingRecord = existing
                effectiveDraftVersion = chatId == Self.syntheticNewChatId || useStoredDraftVersion
                    ? existing.draftVersion : max(existing.draftVersion, draftVersion)
            }
        } catch {
            throw ComposerDraftError.verificationFailed
        }
        try requireCurrentSave()
        let masterKey = try await requireMasterKey()
        try requireCurrentSave()
        let record = try await encryptedRecord(
            canonicalMarkdown: canonicalMarkdown,
            preview: preview,
            chatId: resolvedChatId,
            revision: revision,
            draftVersion: effectiveDraftVersion,
            recordings: recordings,
            attachments: attachments,
            existingEncryptedRecordingPayload: existingRecord?.encryptedRecordingPayload,
            masterKey: masterKey
        )
        try requireCurrentSave()
        do {
            try await repository.upsert(record)
            if newChatDraftId == resolvedChatId {
                try await repository.remove(chatId: Self.syntheticNewChatId)
            }
        } catch {
            throw ComposerDraftError.encryptedWriteFailed
        }
        try requireCurrentSave()
        upsertLocalDraftChatIfNeeded(record)
        coreDrafts.save(chatId: resolvedChatId, markdown: canonicalMarkdown)
        draftReadGenerationByChatId[resolvedChatId] = UUID()
        currentDraft = canonicalMarkdown
        draftPreviews[resolvedChatId] = preview
        postDraftChange(chatId: resolvedChatId, reloadComposer: false)
    }

    /// Reads the composer copy of `chatId` (`nil`: none on this device).
    func loadDraft(chatId: String) async throws -> ComposerDraft? {
        if chatId == Self.syntheticNewChatId, newChatDraftId == nil {
            let records = try await repository.allRecords()
            restoreNewChatDraftId(
                from: records,
                cachedChats: records.compactMap { OfflineStore.shared.loadChat(id: $0.chatId) },
                preferredId: storedNewChatDraftId
            )
            persistNewChatDraftId(newChatDraftId)
        }
        let resolvedChatId = resolveChatId(chatId, hasNonEmptyDraft: false)
        let draftGeneration = draftGenerationByChatId[resolvedChatId]
        let readGeneration = draftReadGenerationByChatId[resolvedChatId]
        let lifecycle = draftLifecycleGeneration
        let scope = OfflineStore.shared.scopeGeneration
        func requireCurrentLoad() throws {
            guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
                  draftGeneration == draftGenerationByChatId[resolvedChatId],
                  readGeneration == draftReadGenerationByChatId[resolvedChatId],
                  scope == OfflineStore.shared.scopeGeneration else { throw CancellationError() }
        }
        let record: ComposerDraftRecord
        do {
            guard let stored = try await repository.record(chatId: resolvedChatId) else { return nil }
            record = stored
        } catch {
            NativeDiagnostics.warning(
                "Draft load failed phase=record errorType=\(type(of: error)) synthetic=\(chatId == Self.syntheticNewChatId)",
                category: "composer_drafts"
            )
            throw ComposerDraftError.verificationFailed
        }
        let masterKey = try await requireMasterKey()
        var loadPhase = "markdownDecrypt"
        do {
            let markdown = try await crypto.decryptContent(
                base64String: record.encryptedMarkdown,
                key: masterKey
            )
            // Ciphertext presence says nothing about meaningful editor content.
            // Serialized embed/mention/code markers remain nonempty markdown, even
            // when their human-readable preview is empty. Preserve an opaque local
            // companion conservatively until its content can be recovered.
            if !ComposerDraftContentPolicy.hasContent(markdown),
               record.encryptedRecordingPayload == nil {
                try requireCurrentLoad()
                let applied = try await repository.apply(.verifiedEmptyDeletion(record),
                    knownVersion: 0, knownClearedVersion: 0, expectedScope: scope).applied
                try requireCurrentLoad()
                guard applied else { throw ComposerDraftError.versionConflict }
                draftGenerationByChatId[resolvedChatId] = UUID()
                // The chat itself stays; only its empty draft goes.
                chatStore?.updateDraftVersion(chatId: record.chatId, draftVersion: 0, hasNonEmptyDraft: false)
                if newChatDraftId == record.chatId { newChatDraftId = nil }
                if record.chatId != Self.syntheticNewChatId { coreDrafts.clear(chatId: record.chatId) }
                currentDraft = ""
                draftPreviews.removeValue(forKey: record.chatId)
                if newChatDraftId == nil { persistNewChatDraftId(nil) }
                postDraftChange(chatId: record.chatId, reloadComposer: false)
                return nil
            }
            var preview: String
            let attachments: [ComposerDraftAttachment]
            var expectedEncryptedPreview = record.encryptedPreview
            if record.encryptedPreview.isEmpty {
                loadPhase = "previewRepair"
                preview = String(ChatDraftPreviewFormatter.format(markdown).prefix(160))
                let encryptedPreview = try await crypto.encryptWithMasterKey(preview, masterKey: masterKey)
                try requireCurrentLoad()
                let repaired = try await repository.apply(.previewRepair(ComposerDraftRecord(
                    chatId: record.chatId, encryptedMarkdown: record.encryptedMarkdown,
                    encryptedPreview: encryptedPreview, revision: record.revision,
                    draftVersion: record.draftVersion)), knownVersion: 0, knownClearedVersion: 0,
                    expectedScope: scope)
                guard repaired.applied else { throw ComposerDraftError.versionConflict }
                expectedEncryptedPreview = encryptedPreview
            } else {
                loadPhase = "previewDecrypt"
                let decryptedPreview = try await crypto.decryptContent(
                    base64String: record.encryptedPreview,
                    key: masterKey
                )
                // A missing display preview must not discard serialized attachments.
                preview = ChatDraftPreviewFormatter.format(decryptedPreview).isEmpty
                    ? String(ChatDraftPreviewFormatter.format(markdown).prefix(160)) : decryptedPreview
            }
            if let encryptedPayload = record.encryptedRecordingPayload {
                loadPhase = "recordingPayloadDecrypt"
                let plaintext = try await crypto.decryptContent(
                    base64String: encryptedPayload,
                    key: masterKey
                )
                attachments = try Self.decodeAttachmentPayload(
                    plaintext,
                    referencedBy: markdown
                )
            } else {
                attachments = []
            }
            if ChatDraftPreviewFormatter.format(preview).isEmpty, let attachment = attachments.first {
                preview = AppStrings.draftEmbedPreviewLabel(type: attachment.embedRecord.type)
            }
            loadPhase = "recordRecheck"
            guard let latest = try await repository.record(chatId: record.chatId),
                  latest.revision == record.revision, latest.draftVersion == record.draftVersion,
                  latest.encryptedMarkdown == record.encryptedMarkdown,
                  latest.encryptedPreview == expectedEncryptedPreview,
                  latest.encryptedRecordingPayload == record.encryptedRecordingPayload else {
                throw ComposerDraftError.versionConflict
            }
            loadPhase = "generationCheck"
            try requireCurrentLoad()
            currentDraft = markdown
            draftPreviews[record.chatId] = preview
            return ComposerDraft(
                canonicalMarkdown: markdown,
                preview: preview,
                attachments: attachments,
                revision: record.revision,
                draftVersion: record.draftVersion
            )
        } catch {
            NativeDiagnostics.warning(
                "Draft load failed phase=\(loadPhase) errorType=\(type(of: error)) synthetic=\(chatId == Self.syntheticNewChatId)",
                category: "composer_drafts"
            )
            throw ComposerDraftError.verificationFailed
        }
    }

    /// Removes the composer copy of `chatId` and clears the draft in the core
    /// (a draft-only chat disappears there and here).
    func clearDraft(chatId: String) async throws {
        let lifecycle = draftLifecycleGeneration
        let scope = OfflineStore.shared.scopeGeneration
        func requireCurrentDeletion() throws {
            guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
                  scope == OfflineStore.shared.scopeGeneration else { throw CancellationError() }
        }
        try requireCurrentDeletion()
        let resolvedChatId = resolveChatId(chatId, hasNonEmptyDraft: false)
        // Invalidate pending encryption before the first deletion await.
        draftGenerationByChatId[resolvedChatId] = UUID()
        try await repository.remove(chatId: resolvedChatId)
        try requireCurrentDeletion()
        if resolvedChatId != Self.syntheticNewChatId {
            coreDrafts.clear(chatId: resolvedChatId)
            chatStore?.updateDraftVersion(chatId: resolvedChatId, draftVersion: 0, hasNonEmptyDraft: false)
            removeDraftOnlyChatIfNeeded(resolvedChatId)
        }
        if chatId == Self.syntheticNewChatId || newChatDraftId == resolvedChatId {
            newChatDraftId = nil
            persistNewChatDraftId(nil)
        }
        currentDraft = ""
        draftPreviews.removeValue(forKey: resolvedChatId)
        postDraftChange(chatId: resolvedChatId, reloadComposer: false)
    }

    /// After the local copy was shown: reads the core's draft of `chatId` and
    /// adopts it into the local copy unless local edits the core lacks win
    /// (then they are sent again). An adopted change reloads the open composer.
    func refreshFromCore(chatId: String) async {
        let resolvedChatId = resolveChatId(chatId, hasNonEmptyDraft: false)
        guard resolvedChatId != Self.syntheticNewChatId else { return }
        let lifecycle = draftLifecycleGeneration
        let scope = OfflineStore.shared.scopeGeneration
        let remote: DraftViewRecord?
        do {
            remote = try await coreDrafts.read(chatId: resolvedChatId)
        } catch {
            // `CoreDrafts` logged the typed error; the local copy stays shown.
            return
        }
        guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
              scope == OfflineStore.shared.scopeGeneration else { return }
        await reconcile(chatId: resolvedChatId, remote: remote, onOpen: true, lifecycle: lifecycle, scope: scope)
    }

    /// A draft saved or cleared on another device.
    private func applyRemoteDraft(_ change: CoreDraftChange) async {
        await reconcile(chatId: change.chatId, remote: change.draft, onOpen: false,
                        lifecycle: draftLifecycleGeneration, scope: OfflineStore.shared.scopeGeneration)
    }

    /// Adopts the core's draft into the local copy unless the local copy holds
    /// edits the core has not received. `onOpen` also compares the local copy's
    /// version with the core's (a remote event is newer by definition).
    private func reconcile(chatId: String, remote: DraftViewRecord?, onOpen: Bool,
                           lifecycle: UUID, scope: UUID) async {
        func isCurrent() -> Bool {
            !Task.isCancelled && lifecycle == draftLifecycleGeneration
                && scope == OfflineStore.shared.scopeGeneration
        }
        guard isCurrent() else { return }
        if coreDrafts.hasUnsyncedChanges(chatId: chatId) {
            // A save or clear of this device is queued or failed: local wins.
            if !coreDrafts.isBusy(chatId: chatId) { await resendLocal(chatId: chatId, lifecycle: lifecycle, scope: scope) }
            return
        }
        let local: ComposerDraftRecord?
        let localMarkdown: String?
        do {
            local = try await repository.record(chatId: chatId).flatMap { $0.isDeleted || $0.encryptedMarkdown.isEmpty ? nil : $0 }
            if let local {
                let masterKey = try await requireMasterKey()
                localMarkdown = try await crypto.decryptContent(base64String: local.encryptedMarkdown, key: masterKey)
            } else {
                localMarkdown = nil
            }
        } catch {
            NativeDiagnostics.warning("Core draft reconcile failed phase=local errorType=\(type(of: error))",
                                      category: "composer_drafts")
            return
        }
        guard isCurrent() else { return }
        if let local, let localMarkdown {
            if let remote {
                let remoteVersion = Int(clamping: remote.draftV)
                if remote.markdown == localMarkdown {
                    // Same text: only remember the core's version for the next comparison.
                    if remoteVersion > local.draftVersion {
                        await writeLocal(ComposerDraftRecord(chatId: local.chatId, encryptedMarkdown: local.encryptedMarkdown,
                            encryptedPreview: local.encryptedPreview, encryptedRecordingPayload: local.encryptedRecordingPayload,
                            revision: local.revision, draftVersion: remoteVersion), replacing: local, isCurrent: isCurrent)
                    }
                    return
                }
                if onOpen, local.draftVersion >= remoteVersion {
                    coreDrafts.save(chatId: chatId, markdown: localMarkdown)
                    return
                }
            } else if onOpen, local.draftVersion == 0 {
                // The local copy never had a core version: it never reached the core.
                coreDrafts.save(chatId: chatId, markdown: localMarkdown)
                return
            }
        } else if remote == nil {
            return
        }
        await adopt(remote, chatId: chatId, replacing: local, isCurrent: isCurrent)
    }

    /// Writes the core's draft (or its clear) into the local copy and asks an open composer to reload.
    private func adopt(_ remote: DraftViewRecord?, chatId: String, replacing local: ComposerDraftRecord?,
                       isCurrent: () -> Bool) async {
        guard let remote else {
            do {
                guard try await repository.record(chatId: chatId) == local, isCurrent(),
                      !coreDrafts.hasUnsyncedChanges(chatId: chatId) else { return }
                try await repository.remove(chatId: chatId)
            } catch {
                NativeDiagnostics.warning("Core draft adopt failed phase=remove errorType=\(type(of: error))",
                                          category: "composer_drafts")
                return
            }
            guard isCurrent() else { return }
            draftReadGenerationByChatId[chatId] = UUID()
            chatStore?.updateDraftVersion(chatId: chatId, draftVersion: 0, hasNonEmptyDraft: false)
            if newChatDraftId == chatId {
                newChatDraftId = nil
                persistNewChatDraftId(nil)
            }
            draftPreviews.removeValue(forKey: chatId)
            postDraftChange(chatId: chatId, reloadComposer: true)
            return
        }
        let preview = remote.preview ?? String(remote.markdown.prefix(160))
        let record: ComposerDraftRecord
        do {
            let masterKey = try await requireMasterKey()
            record = ComposerDraftRecord(
                chatId: chatId,
                encryptedMarkdown: try await crypto.encryptWithMasterKey(remote.markdown, masterKey: masterKey),
                encryptedPreview: try await crypto.encryptWithMasterKey(preview, masterKey: masterKey),
                // Embed snapshots are local only; the restore keeps those the markdown still references.
                encryptedRecordingPayload: local?.encryptedRecordingPayload,
                revision: local?.revision ?? 0,
                draftVersion: Int(clamping: remote.draftV)
            )
        } catch {
            NativeDiagnostics.warning("Core draft adopt failed phase=encrypt errorType=\(type(of: error))",
                                      category: "composer_drafts")
            return
        }
        guard await writeLocal(record, replacing: local, isCurrent: isCurrent) else { return }
        chatStore?.updateDraftVersion(chatId: chatId, draftVersion: record.draftVersion, hasNonEmptyDraft: true)
        draftPreviews[chatId] = preview
        postDraftChange(chatId: chatId, reloadComposer: true)
    }

    /// Replaces the local copy when it is still `local` and no save of this device is pending.
    @discardableResult
    private func writeLocal(_ record: ComposerDraftRecord, replacing local: ComposerDraftRecord?,
                            isCurrent: () -> Bool) async -> Bool {
        do {
            let latest = try await repository.record(chatId: record.chatId)
            let unchanged = latest == local || (local == nil && (latest?.isDeleted ?? true))
            guard unchanged, isCurrent(), !coreDrafts.hasUnsyncedChanges(chatId: record.chatId) else { return false }
            try await repository.upsert(record)
        } catch {
            NativeDiagnostics.warning("Core draft adopt failed phase=write errorType=\(type(of: error))",
                                      category: "composer_drafts")
            return false
        }
        guard isCurrent() else { return false }
        draftReadGenerationByChatId[record.chatId] = UUID()
        return true
    }

    /// Local wins: sends the local copy (or its absence) to the core again.
    private func resendLocal(chatId: String, lifecycle: UUID, scope: UUID) async {
        do {
            guard let draft = try await loadDraft(chatId: chatId) else {
                guard lifecycle == draftLifecycleGeneration, scope == OfflineStore.shared.scopeGeneration else { return }
                coreDrafts.clear(chatId: chatId)
                return
            }
            guard lifecycle == draftLifecycleGeneration, scope == OfflineStore.shared.scopeGeneration else { return }
            coreDrafts.save(chatId: chatId, markdown: draft.canonicalMarkdown)
        } catch {
            NativeDiagnostics.warning("Core draft resend failed errorType=\(type(of: error))",
                                      category: "composer_drafts")
        }
    }

    /// Sign-out: forgets every composer copy of the account.
    func clearAll() async throws {
        draftLifecycleGeneration = UUID()
        draftGenerationByChatId.removeAll()
        draftReadGenerationByChatId.removeAll()
        UserDefaults.standard.removeObject(forKey: Self.legacyPlaintextDraftsKey)
        newChatDraftId = nil
        persistNewChatDraftId(nil)
        currentDraft = ""
        draftPreviews.removeAll()
        try await repository.removeAll()
    }

    /// Re-reads the previews of the composer copies, e.g. after a reconnect
    /// when the master key became available after the first hydration.
    func refreshLocalPreviews() async {
        let lifecycle = draftLifecycleGeneration
        let scope = OfflineStore.shared.scopeGeneration
        do {
            let records = try await repository.allRecords()
            for record in records {
                guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
                      scope == OfflineStore.shared.scopeGeneration else { return }
                await refreshDraftState(chatId: record.chatId)
            }
        } catch {
            NativeDiagnostics.warning(
                "Draft preview refresh failed errorType=\(type(of: error))",
                category: "composer_drafts"
            )
        }
    }

    func draftPreview(chatId: String) -> String? {
        draftPreviews[chatId]
    }

    #if DEBUG
    func seedUITestDraftPreview(chatId: String, preview: String) {
        draftPreviews[chatId] = preview
        postDraftChange(chatId: chatId)
    }
    #endif

    private func resolveChatId(_ chatId: String, hasNonEmptyDraft: Bool) -> String {
        guard chatId == Self.syntheticNewChatId else { return chatId }
        guard hasNonEmptyDraft else { return newChatDraftId ?? chatId }
        if let newChatDraftId { return newChatDraftId }
        let allocated = UUID().uuidString.lowercased()
        newChatDraftId = allocated
        return allocated
    }

    private func restoreNewChatDraftId(from records: [ComposerDraftRecord], cachedChats: [Chat], preferredId: String?) {
        guard newChatDraftId == nil else { return }
        let recordIds = Set(records.map(\.chatId))
        let knownChats = (chatStore?.chats ?? []) + cachedChats
        if let preferredId, recordIds.contains(preferredId),
           knownChats.first(where: { $0.id == preferredId }).map({ isDraftOnlyChat($0) }) != false {
            newChatDraftId = preferredId
            return
        }
        newChatDraftId = knownChats.first(where: { chat in
            recordIds.contains(chat.id) && isDraftOnlyChat(chat)
        })?.id
    }

    private func isDraftOnlyChat(_ chat: Chat) -> Bool {
        (chat.messagesV ?? 0) == 0
            && (chatStore?.messages(for: chat.id).isEmpty ?? true)
    }

    /// The local chat row of a new-chat draft, so the composer and the
    /// welcome screen find the chat before the core's list names it.
    private func upsertLocalDraftChatIfNeeded(_ record: ComposerDraftRecord) {
        guard let chatStore else { return }
        guard chatStore.chat(for: record.chatId) == nil else {
            chatStore.updateDraftVersion(chatId: record.chatId, draftVersion: record.draftVersion,
                                         hasNonEmptyDraft: !record.encryptedMarkdown.isEmpty)
            return
        }
        let date = ISO8601DateFormatter().string(from: Date())
        chatStore.upsertChat(Chat(
            id: record.chatId,
            title: nil,
            lastMessageAt: nil,
            createdAt: date,
            updatedAt: date,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0,
            draftV: record.draftVersion,
            hasNonEmptyDraft: !record.encryptedMarkdown.isEmpty
        ))
    }

    private func removeDraftOnlyChatIfNeeded(_ chatId: String) {
        guard let chatStore, let chat = chatStore.chat(for: chatId), isDraftOnlyChat(chat) else { return }
        chatStore.performWithoutPersistence { chatStore.removeChat(chatId) }
        draftOnlyCleanup?.cascadeDeleteDraftOnlyChat(chatId: chatId)
    }

    private func refreshDraftState(chatId: String) async {
        do {
            if let draft = try await loadDraft(chatId: chatId) {
                draftPreviews[chatId] = draft.preview
            } else {
                draftPreviews.removeValue(forKey: chatId)
            }
            postDraftChange(chatId: chatId)
        } catch ComposerDraftError.masterKeyUnavailable {
            return
        } catch {
            NativeDiagnostics.warning(
                "Draft UI refresh failed errorType=\(type(of: error))",
                category: "composer_drafts"
            )
        }
    }

    private func postDraftChange(chatId: String, reloadComposer: Bool = true) {
        NotificationCenter.default.post(
            name: .composerDraftDidChange,
            object: nil,
            userInfo: ["chatId": chatId, "reloadComposer": reloadComposer,
                       "scopeGeneration": OfflineStore.shared.scopeGeneration,
                       "chatRemoved": chatStore != nil && chatStore?.chat(for: chatId) == nil]
        )
    }

    private func requireMasterKey() async throws -> SymmetricKey {
        do {
            guard let masterKey = try await masterKeyProvider() else {
                throw ComposerDraftError.masterKeyUnavailable
            }
            return masterKey
        } catch let error as ComposerDraftError {
            throw error
        } catch {
            throw ComposerDraftError.masterKeyUnavailable
        }
    }

    private func encryptedRecord(
        canonicalMarkdown: String,
        preview: String,
        chatId: String,
        revision: Int,
        draftVersion: Int,
        recordings: [EmbedRecord]?,
        attachments: [ComposerDraftAttachment]?,
        existingEncryptedRecordingPayload: String?,
        masterKey: SymmetricKey
    ) async throws -> ComposerDraftRecord {
        let encryptedMarkdown = try await crypto.encryptWithMasterKey(
            canonicalMarkdown,
            masterKey: masterKey
        )
        let encryptedPreview = try await crypto.encryptWithMasterKey(
            preview,
            masterKey: masterKey
        )
        let encryptedRecordingPayload: String?
        if attachments != nil || recordings != nil {
            let sourceAttachments = attachments
                ?? recordings?.map { ComposerDraftAttachment(embedRecord: $0, localData: nil) }
                ?? []
            let referencedIDs = Self.embedIDs(referencedBy: canonicalMarkdown)
            let payload = ComposerDraftRecordingPayload(
                version: 2,
                recordings: nil,
                attachments: sourceAttachments
                    .filter { referencedIDs.contains($0.embedRecord.id) }
                    .compactMap(ComposerDraftRecordingSnapshot.init)
            )
            if payload.attachments?.isEmpty != false {
                encryptedRecordingPayload = nil
            } else {
                let encoder = JSONEncoder()
                encoder.outputFormatting = [.sortedKeys]
                let data = try encoder.encode(payload)
                guard let plaintext = String(data: data, encoding: .utf8) else {
                    throw ComposerDraftError.verificationFailed
                }
                encryptedRecordingPayload = try await crypto.encryptWithMasterKey(
                    plaintext,
                    masterKey: masterKey
                )
            }
        } else {
            encryptedRecordingPayload = existingEncryptedRecordingPayload
        }
        return ComposerDraftRecord(
            chatId: chatId,
            encryptedMarkdown: encryptedMarkdown,
            encryptedPreview: encryptedPreview,
            encryptedRecordingPayload: encryptedRecordingPayload,
            revision: revision,
            draftVersion: draftVersion
        )
    }

    private static func decodeAttachmentPayload(
        _ plaintext: String,
        referencedBy markdown: String
    ) throws -> [ComposerDraftAttachment] {
        guard let data = plaintext.data(using: .utf8) else {
            throw ComposerDraftError.verificationFailed
        }
        let payload = try JSONDecoder().decode(ComposerDraftRecordingPayload.self, from: data)
        guard payload.version == 1 || payload.version == 2 else { throw ComposerDraftError.verificationFailed }
        let referencedIDs = embedIDs(referencedBy: markdown)
        let snapshots = payload.attachments ?? payload.recordings ?? []
        return snapshots
            .filter { referencedIDs.contains($0.id) }
            .map(\.draftAttachment)
    }

    private static func embedIDs(referencedBy markdown: String) -> Set<String> {
        let nodes = (try? ComposerMarkdownAdapter.parse(markdown).nodes) ?? []
        return Set(nodes
            .compactMap { $0.contentRef?.replacingOccurrences(of: "embed:", with: "") })
    }
}

private struct ComposerDraftRecordingPayload: Codable, Sendable {
    let version: Int
    let recordings: [ComposerDraftRecordingSnapshot]?
    let attachments: [ComposerDraftRecordingSnapshot]?
}

private struct ComposerDraftRecordingSnapshot: Codable, Sendable {
    let id: String
    let type: String
    let status: EmbedStatus
    let rawData: [String: AnyCodable]
    let encryptedContent: String?
    let encryptedType: String?
    let encryptedTextPreview: String?
    let parentEmbedId: String?
    let appId: String?
    let skillId: String?
    let embedIds: String?
    let hashedChatId: String?
    let hashedUserId: String?
    let versionNumber: Int?
    let contentHash: String?
    let versionHistory: [EmbedVersionMetadata]
    let versionHistoryReadonly: Bool
    let createdAt: String?
    let localDataBase64: String?

    init?(_ attachment: ComposerDraftAttachment) {
        let record = attachment.embedRecord
        guard let rawData = record.rawData else { return nil }
        self.id = record.id
        self.type = record.type
        self.status = record.status
        self.rawData = rawData
        self.encryptedContent = record.encryptedContent
        self.encryptedType = record.encryptedType
        self.encryptedTextPreview = record.encryptedTextPreview
        self.parentEmbedId = record.parentEmbedId
        self.appId = record.appId
        self.skillId = record.skillId
        self.embedIds = record.embedIds
        self.hashedChatId = record.hashedChatId
        self.hashedUserId = record.hashedUserId
        self.versionNumber = record.versionNumber
        self.contentHash = record.contentHash
        self.versionHistory = record.versionHistory
        self.versionHistoryReadonly = record.versionHistoryReadonly
        self.createdAt = record.createdAt
        self.localDataBase64 = attachment.localData?.base64EncodedString()
    }

    var embedRecord: EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: status,
            data: .raw(rawData),
            encryptedContent: encryptedContent,
            encryptedType: encryptedType,
            encryptedTextPreview: encryptedTextPreview,
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            hashedChatId: hashedChatId,
            hashedUserId: hashedUserId,
            versionNumber: versionNumber,
            contentHash: contentHash,
            versionHistory: versionHistory,
            versionHistoryReadonly: versionHistoryReadonly,
            createdAt: createdAt
        )
    }

    var draftAttachment: ComposerDraftAttachment {
        ComposerDraftAttachment(
            embedRecord: embedRecord,
            localData: localDataBase64.flatMap { Data(base64Encoded: $0) }
        )
    }
}
