// Encrypted native composer draft persistence and legacy migration.
// Canonical markdown and previews are encrypted with master-key Format D.
// Durable repositories store ciphertext metadata only, never editor state.
// Legacy UserDefaults plaintext is removed only after decrypt verification.
// Dependencies remain injectable for deterministic migration tests.

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
        syncCoordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: chatStore,
            transport: transport,
            offlineActions: offlineActions,
            onDraftChanged: { [weak self] chatId in
                Task { @MainActor in
                    await self?.refreshDraftState(chatId: chatId)
                }
            }
        )
        Task { [weak self] in
            guard let self else { return }
            do {
                let records = try await repository.allRecords()
                syncCoordinator?.restoreNewChatDraftId(from: records)
                for record in records {
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

    func saveDraft(
        canonicalMarkdown: String,
        preview: String,
        chatId: String,
        revision: Int,
        draftVersion: Int
    ) async throws {
        guard !canonicalMarkdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            try await clearDraft(chatId: chatId)
            return
        }
        let resolvedChatId = syncCoordinator?.resolveChatId(chatId, hasNonEmptyDraft: true) ?? chatId
        var effectiveDraftVersion = draftVersion
        do {
            if let existing = try await repository.record(chatId: resolvedChatId) {
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
        let masterKey = try await requireMasterKey()
        let record = try await encryptedRecord(
            canonicalMarkdown: canonicalMarkdown,
            preview: preview,
            chatId: resolvedChatId,
            revision: revision,
            draftVersion: effectiveDraftVersion,
            masterKey: masterKey
        )
        do {
            try await repository.upsert(record)
        } catch {
            throw ComposerDraftError.encryptedWriteFailed
        }
        try await syncCoordinator?.submitLocalUpdate(record, resolvedChatId: resolvedChatId)
        currentDraft = canonicalMarkdown
        draftPreviews[resolvedChatId] = preview
        postDraftChange(chatId: resolvedChatId)
    }

    func loadDraft(chatId: String) async throws -> ComposerDraft? {
        let record: ComposerDraftRecord
        do {
            let resolvedChatId = syncCoordinator?.resolveChatId(chatId, hasNonEmptyDraft: false) ?? chatId
            guard let stored = try await repository.record(chatId: resolvedChatId) else { return nil }
            record = stored
        } catch {
            throw ComposerDraftError.verificationFailed
        }
        let masterKey = try await requireMasterKey()
        do {
            let markdown = try await crypto.decryptContent(
                base64String: record.encryptedMarkdown,
                key: masterKey
            )
            let preview: String
            if record.encryptedPreview.isEmpty {
                preview = String(markdown.prefix(160))
                let encryptedPreview = try await crypto.encryptWithMasterKey(preview, masterKey: masterKey)
                try await repository.upsert(ComposerDraftRecord(
                    chatId: record.chatId,
                    encryptedMarkdown: record.encryptedMarkdown,
                    encryptedPreview: encryptedPreview,
                    revision: record.revision,
                    draftVersion: record.draftVersion
                ))
            } else {
                preview = try await crypto.decryptContent(
                    base64String: record.encryptedPreview,
                    key: masterKey
                )
            }
            currentDraft = markdown
            draftPreviews[record.chatId] = preview
            return ComposerDraft(
                canonicalMarkdown: markdown,
                preview: preview,
                revision: record.revision,
                draftVersion: record.draftVersion
            )
        } catch {
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
        await legacyStore.removeDraft(chatId: resolvedChatId)
        if let syncCoordinator, resolvedChatId != DraftSyncCoordinator.syntheticNewChatId {
            try await syncCoordinator.submitLocalDelete(chatId: resolvedChatId)
        } else {
            try await repository.remove(chatId: resolvedChatId)
        }
        if chatId == DraftSyncCoordinator.syntheticNewChatId {
            syncCoordinator?.resetNewChatDraftId()
        }
        currentDraft = ""
        draftPreviews.removeValue(forKey: resolvedChatId)
        postDraftChange(chatId: resolvedChatId)
    }

    func clearAll() async throws {
        await legacyStore.removeAllDrafts()
        try await repository.removeAll()
        syncCoordinator?.resetNewChatDraftId()
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

    private func postDraftChange(chatId: String) {
        NotificationCenter.default.post(
            name: .composerDraftDidChange,
            object: nil,
            userInfo: ["chatId": chatId]
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
        return ComposerDraftRecord(
            chatId: chatId,
            encryptedMarkdown: encryptedMarkdown,
            encryptedPreview: encryptedPreview,
            revision: revision,
            draftVersion: draftVersion
        )
    }
}
