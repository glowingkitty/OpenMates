// Encrypted native composer draft persistence and legacy migration.
// Canonical markdown and previews are encrypted with master-key Format D.
// Durable repositories store ciphertext metadata only, never editor state.
// Legacy UserDefaults plaintext is removed only after decrypt verification.
// Dependencies remain injectable for deterministic migration tests.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.drafts.preview-persistence, message-input.recording.lifecycle
// Specification: specifications/architecture/drafts/specification.yml
// Assertions: drafts.persistence.local-first-encrypted

import Combine
import CryptoKit
import Foundation

extension Notification.Name {
    static let composerDraftDidChange = Notification.Name("openmates.composerDraftDidChange")
}

actor UserDefaultsLegacyComposerDraftStore: LegacyComposerDraftStore {
    private let defaults: UserDefaults
    private let storageKey: String

    init(defaults: UserDefaults, storageKey: String) {
        self.defaults = defaults
        self.storageKey = storageKey
    }

    func drafts() -> [String: String] {
        defaults.dictionary(forKey: storageKey) as? [String: String] ?? [:]
    }

    func removeDraft(chatId: String) {
        var values = drafts()
        values.removeValue(forKey: chatId)
        if values.isEmpty {
            defaults.removeObject(forKey: storageKey)
        } else {
            defaults.set(values, forKey: storageKey)
        }
    }
}

@MainActor
final class DraftService: ObservableObject {
    static let shared = DraftService(
        repository: OfflineStore.shared,
        legacyStore: UserDefaultsLegacyComposerDraftStore(
            defaults: .standard,
            storageKey: "openmates.drafts"
        ),
        masterKeyProvider: {
            guard let userId = await AuthManager.currentUserId() else { return nil }
            return try await CryptoManager.shared.loadMasterKey(for: userId)
        }
    )

    @Published private(set) var currentDraft = ""
    @Published private(set) var draftPreviews: [String: String] = [:]

    private let repository: any ComposerDraftRepository
    private let legacyStore: any LegacyComposerDraftStore
    private let masterKeyProvider: @Sendable () async throws -> SymmetricKey?
    private let crypto: CryptoManager
    private var syncCoordinator: DraftSyncCoordinator?
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

    init(
        repository: any ComposerDraftRepository,
        legacyStore: any LegacyComposerDraftStore,
        masterKeyProvider: @escaping @Sendable () async throws -> SymmetricKey?
    ) {
        self.repository = repository
        self.legacyStore = legacyStore
        self.masterKeyProvider = masterKeyProvider
        self.crypto = CryptoManager.shared
    }

    func configureSync(
        chatStore: ChatStore,
        transport: any DraftSyncTransport,
        offlineActions: any DraftSyncOfflineActions
    ) {
        let lifecycle = draftLifecycleGeneration
        let scope = OfflineStore.shared.scopeGeneration
        syncCoordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: chatStore,
            transport: transport,
            offlineActions: offlineActions,
            onDraftChanged: { [weak self] chatId in
                guard let self, lifecycle == self.draftLifecycleGeneration,
                      scope == OfflineStore.shared.scopeGeneration else { return }
                // Invalidate the old read synchronously, before scheduling its replacement.
                self.draftReadGenerationByChatId[chatId] = UUID()
                Task { @MainActor [weak self] in
                    guard let self, lifecycle == self.draftLifecycleGeneration,
                          scope == OfflineStore.shared.scopeGeneration else { return }
                    await self.refreshDraftState(chatId: chatId)
                }
            },
            expectedScope: scope,
            isCurrentSession: { [weak self] in
                guard let self else { return false }
                return lifecycle == draftLifecycleGeneration && scope == OfflineStore.shared.scopeGeneration
            }
        )
        Task { [weak self] in
            guard let self else { return }
            do {
                let records = try await repository.allRecords()
                let deletionVersions = try await repository.allDeletionVersions()
                guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
                      scope == OfflineStore.shared.scopeGeneration else { return }
                syncCoordinator?.restoreDeletionMarkers(deletionVersions)
                syncCoordinator?.restoreNewChatDraftId(
                    from: records,
                    cachedChats: records.compactMap { OfflineStore.shared.loadChat(id: $0.chatId) },
                    preferredId: storedNewChatDraftId
                )
                persistNewChatDraftId(syncCoordinator?.activeNewChatDraftId)
                for record in records {
                    if let deletedVersion = deletionVersions[record.chatId], deletedVersion >= record.draftVersion { continue }
                    guard !Task.isCancelled, lifecycle == draftLifecycleGeneration,
                          scope == OfflineStore.shared.scopeGeneration else { return }
                    // Legacy caches predate the presence column. A durable
                    // encrypted draft supplies authoritative local presence and
                    // can bring its older cached chat metadata into this session.
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
                    category: "draft_sync"
                )
            }
        }
    }

    var activeNewChatDraftId: String? {
        syncCoordinator?.activeNewChatDraftId
    }

    func reserveNewChatDraftId(preferredId: String) -> String {
        let resolved = syncCoordinator?.reserveNewChatDraftId(preferredId: preferredId) ?? preferredId
        persistNewChatDraftId(resolved)
        return resolved
    }

    func beginFreshNewChatDraft(preferredId: String) -> String {
        let resolved = syncCoordinator?.beginFreshNewChatDraft(preferredId: preferredId) ?? preferredId
        persistNewChatDraftId(resolved)
        return resolved
    }

    func saveDraft(
        canonicalMarkdown: String,
        preview: String,
        chatId: String,
        revision: Int,
        draftVersion: Int,
        recordings: [EmbedRecord]? = nil,
        attachments: [ComposerDraftAttachment]? = nil
    ) async throws {
        guard !canonicalMarkdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            try await clearDraft(chatId: chatId)
            return
        }
        let resolvedChatId = syncCoordinator?.resolveChatId(chatId, hasNonEmptyDraft: true) ?? chatId
        if chatId == DraftSyncCoordinator.syntheticNewChatId {
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
        var effectiveDraftVersion = draftVersion
        var existingRecord: ComposerDraftRecord?
        do {
            if let existing = try await repository.record(chatId: resolvedChatId) {
                existingRecord = existing
                if chatId == DraftSyncCoordinator.syntheticNewChatId {
                    effectiveDraftVersion = existing.draftVersion
                } else if existing.draftVersion > draftVersion {
                    throw ComposerDraftError.versionConflict
                }
            }
        } catch let error as ComposerDraftError {
            throw error
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
        } catch {
            throw ComposerDraftError.encryptedWriteFailed
        }
        try requireCurrentSave()
        try await syncCoordinator?.submitLocalUpdate(record, resolvedChatId: resolvedChatId)
        try requireCurrentSave()
        draftReadGenerationByChatId[resolvedChatId] = UUID()
        currentDraft = canonicalMarkdown
        draftPreviews[resolvedChatId] = preview
        postDraftChange(chatId: resolvedChatId, reloadComposer: false)
    }

    func loadDraft(chatId: String) async throws -> ComposerDraft? {
        if chatId == DraftSyncCoordinator.syntheticNewChatId,
           syncCoordinator?.activeNewChatDraftId == nil {
            let records = try await repository.allRecords()
            syncCoordinator?.restoreNewChatDraftId(
                from: records,
                cachedChats: records.compactMap { OfflineStore.shared.loadChat(id: $0.chatId) },
                preferredId: storedNewChatDraftId
            )
            persistNewChatDraftId(syncCoordinator?.activeNewChatDraftId)
        }
        let resolvedChatId = syncCoordinator?.resolveChatId(chatId, hasNonEmptyDraft: false) ?? chatId
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
                "Draft load failed phase=record errorType=\(type(of: error)) synthetic=\(chatId == DraftSyncCoordinator.syntheticNewChatId)",
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
            let preview: String
            let attachments: [ComposerDraftAttachment]
            var expectedEncryptedPreview = record.encryptedPreview
            if record.encryptedPreview.isEmpty {
                loadPhase = "previewRepair"
                preview = String(markdown.prefix(160))
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
                preview = try await crypto.decryptContent(
                    base64String: record.encryptedPreview,
                    key: masterKey
                )
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
                "Draft load failed phase=\(loadPhase) errorType=\(type(of: error)) synthetic=\(chatId == DraftSyncCoordinator.syntheticNewChatId)",
                category: "composer_drafts"
            )
            throw ComposerDraftError.verificationFailed
        }
    }

    func migrateLegacyDraftsAfterUnlock() async throws {
        let legacyDrafts = await legacyStore.drafts()
        guard !legacyDrafts.isEmpty else { return }
        let masterKey = try await requireMasterKey()

        for (chatId, markdown) in legacyDrafts {
            do {
                if try await repository.record(chatId: chatId) != nil {
                    throw ComposerDraftError.migrationConflict
                }
            } catch let error as ComposerDraftError {
                throw error
            } catch {
                throw ComposerDraftError.verificationFailed
            }
            let preview = String(markdown.prefix(160))
            let record = try await encryptedRecord(
                canonicalMarkdown: markdown,
                preview: preview,
                chatId: chatId,
                revision: 13,
                draftVersion: 1,
                recordings: nil,
                attachments: nil,
                existingEncryptedRecordingPayload: nil,
                masterKey: masterKey
            )
            do {
                try await repository.upsert(record)
            } catch {
                throw ComposerDraftError.encryptedWriteFailed
            }

            do {
                guard let stored = try await repository.record(chatId: chatId) else {
                    throw ComposerDraftError.verificationFailed
                }
                let verifiedMarkdown = try await crypto.decryptContent(
                    base64String: stored.encryptedMarkdown,
                    key: masterKey
                )
                let verifiedPreview = try await crypto.decryptContent(
                    base64String: stored.encryptedPreview,
                    key: masterKey
                )
                guard verifiedMarkdown == markdown, verifiedPreview == preview else {
                    throw ComposerDraftError.verificationFailed
                }
            } catch {
                try? await repository.remove(chatId: chatId)
                throw ComposerDraftError.verificationFailed
            }
            await legacyStore.removeDraft(chatId: chatId)
        }
    }

    func clearDraft(chatId: String) async throws {
        let resolvedChatId = syncCoordinator?.resolveChatId(chatId, hasNonEmptyDraft: false) ?? chatId
        // Invalidate pending encryption before the first deletion await.
        draftGenerationByChatId[resolvedChatId] = UUID()
        await legacyStore.removeDraft(chatId: resolvedChatId)
        if let syncCoordinator, resolvedChatId != DraftSyncCoordinator.syntheticNewChatId {
            try await syncCoordinator.submitLocalDelete(chatId: resolvedChatId)
        } else {
            try await repository.remove(chatId: resolvedChatId)
        }
        if chatId == DraftSyncCoordinator.syntheticNewChatId {
            syncCoordinator?.resetNewChatDraftId()
            persistNewChatDraftId(nil)
        }
        currentDraft = ""
        draftPreviews.removeValue(forKey: resolvedChatId)
        postDraftChange(chatId: resolvedChatId, reloadComposer: false)
    }

    func clearAll() async throws {
        draftLifecycleGeneration = UUID()
        draftGenerationByChatId.removeAll()
        draftReadGenerationByChatId.removeAll()
        await legacyStore.removeAllDrafts()
        try await repository.removeAll()
        syncCoordinator?.resetNewChatDraftId()
        persistNewChatDraftId(nil)
        currentDraft = ""
        draftPreviews.removeAll()
    }

    func reconcileAfterReconnect() async {
        do {
            try await syncCoordinator?.reconcileAfterReconnect()
        } catch {
            NativeDiagnostics.warning(
                "Draft reconnect reconciliation failed errorType=\(type(of: error))",
                category: "draft_sync"
            )
        }
    }

    func handleSyncEvent(type: String, raw: Data) async {
        do {
            if type == "phase_2_last_20_chats_ready" || type == "phase_3_last_100_chats_ready" || type == "sync_metadata_chats_response" {
                try await syncCoordinator?.handleSyncEvent(raw: raw)
            } else {
                try await syncCoordinator?.handleEvent(type: type, raw: raw)
            }
        } catch {
            NativeDiagnostics.warning(
                "Draft sync event failed type=\(type) errorType=\(Swift.type(of: error))",
                category: "draft_sync"
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
                category: "draft_sync"
            )
        }
    }

    private func postDraftChange(chatId: String, reloadComposer: Bool = true) {
        NotificationCenter.default.post(
            name: .composerDraftDidChange,
            object: nil,
            userInfo: ["chatId": chatId, "reloadComposer": reloadComposer]
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
