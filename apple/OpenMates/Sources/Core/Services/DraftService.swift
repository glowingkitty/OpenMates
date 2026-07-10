// Encrypted native composer draft persistence and legacy migration.
// Canonical markdown and previews are encrypted with master-key Format D.
// Durable repositories store ciphertext metadata only, never editor state.
// Legacy UserDefaults plaintext is removed only after decrypt verification.
// Dependencies remain injectable for deterministic migration tests.

import Combine
import CryptoKit
import Foundation

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

    private let repository: any ComposerDraftRepository
    private let legacyStore: any LegacyComposerDraftStore
    private let masterKeyProvider: @Sendable () async throws -> SymmetricKey?
    private let crypto: CryptoManager

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
        let masterKey = try await requireMasterKey()
        let record = try await encryptedRecord(
            canonicalMarkdown: canonicalMarkdown,
            preview: preview,
            chatId: chatId,
            revision: revision,
            draftVersion: draftVersion,
            masterKey: masterKey
        )
        do {
            try await repository.upsert(record)
        } catch {
            throw ComposerDraftError.encryptedWriteFailed
        }
        currentDraft = canonicalMarkdown
    }

    func loadDraft(chatId: String) async throws -> ComposerDraft? {
        let record: ComposerDraftRecord
        do {
            guard let stored = try await repository.record(chatId: chatId) else { return nil }
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
            let preview = try await crypto.decryptContent(
                base64String: record.encryptedPreview,
                key: masterKey
            )
            currentDraft = markdown
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
        await legacyStore.removeDraft(chatId: chatId)
        try await repository.remove(chatId: chatId)
        currentDraft = ""
    }

    func clearAll() async throws {
        await legacyStore.removeAllDrafts()
        try await repository.removeAll()
        currentDraft = ""
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
