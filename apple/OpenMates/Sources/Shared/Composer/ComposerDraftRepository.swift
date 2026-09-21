// Shared encrypted composer draft persistence contract.
// Durable records contain Format D ciphertext and revision metadata only.
// The SwiftData model intentionally has no plaintext or editor-state fields.
// DraftService owns encryption while repositories own ciphertext persistence.
// This boundary remains injectable for production-container verification.

import Foundation
import SwiftData

struct ComposerDraftRecord: Sendable {
    let chatId: String
    var encryptedMarkdown: String
    var encryptedPreview: String
    let revision: Int
    let draftVersion: Int
    var clearedDraftVersion: Int = 0
    var isDeleted: Bool = false
}

struct ComposerDraft: Sendable {
    let canonicalMarkdown: String
    let preview: String
    let revision: Int
    let draftVersion: Int
}

protocol ComposerDraftRepository: Sendable {
    func upsert(_ record: ComposerDraftRecord) async throws
    func record(chatId: String) async throws -> ComposerDraftRecord?
    func remove(chatId: String) async throws
    func removeAll() async throws
    func allRecords() async throws -> [ComposerDraftRecord]
    func allDeletionVersions() async throws -> [String: Int]
    /// Atomically compare remote versions and write in the captured account cache.
    func apply(_ mutation: ComposerDraftMutation, knownVersion: Int, knownClearedVersion: Int,
               expectedScope: UUID?) async throws -> ComposerDraftApplication
}

/// The same monotonic draft/deletion decision is used for ciphertext and chat metadata.
/// A deletion is draft_v=0 plus a retained cleared_draft_v, never a reset of history.
enum ComposerDraftVersionPolicy {
    static func acceptsContent(version: Int, currentVersion: Int, hasDraft: Bool,
                               clearedVersion: Int) -> Bool {
        version >= currentVersion && !(currentVersion == 0 && !hasDraft
            && clearedVersion > 0 && clearedVersion >= version)
    }

    static func acceptsDeletion(version: Int?, currentVersion: Int) -> Bool {
        guard let version else { return currentVersion == 0 }
        return version >= currentVersion
    }
}

struct ComposerDraftApplication: Sendable {
    let record: ComposerDraftRecord?
    let applied: Bool
}

enum ComposerDraftMutation: Sendable {
    case content(ComposerDraftRecord)
    case previewRepair(ComposerDraftRecord)
    case acknowledgement(chatId: String, version: Int)
    case deletion(chatId: String, version: Int?)
    case localDeletion(chatId: String)
    case chatDeletion(chatId: String)

    var chatId: String {
        switch self {
        case .content(let record), .previewRepair(let record): return record.chatId
        case .acknowledgement(let id, _), .deletion(let id, _), .localDeletion(let id), .chatDeletion(let id): return id
        }
    }

    func applying(to local: ComposerDraftRecord?, knownVersion: Int = 0,
                  knownClearedVersion: Int = 0) -> ComposerDraftApplication {
        let currentVersion = max(local?.draftVersion ?? 0, knownVersion)
        let clearedVersion = max(local?.clearedDraftVersion ?? 0, knownClearedVersion)
        let hasDraft = local.map { !$0.isDeleted && !$0.encryptedMarkdown.isEmpty } ?? false
        let unchanged = ComposerDraftApplication(record: local, applied: false)
        switch self {
        case .content(var record):
            // Sync may already have recreated stale chat metadata before this
            // encrypted row is processed. That metadata cannot cancel a durable fence.
            guard !(local?.isDeleted == true && clearedVersion >= record.draftVersion),
                  record.draftVersion > 0,
                  ComposerDraftVersionPolicy.acceptsContent(version: record.draftVersion,
                    currentVersion: currentVersion, hasDraft: hasDraft, clearedVersion: clearedVersion)
            else { return unchanged }
            record.clearedDraftVersion = clearedVersion
            record.isDeleted = false
            return ComposerDraftApplication(record: record, applied: true)
        case .previewRepair(var record):
            // Preview derivation awaits decryption/encryption. It may only fill
            // the exact still-active row, never reopen a cleared/replaced draft.
            guard let local, !local.isDeleted, local.encryptedPreview.isEmpty,
                  local.draftVersion == record.draftVersion, local.revision == record.revision,
                  local.encryptedMarkdown == record.encryptedMarkdown else { return unchanged }
            record.clearedDraftVersion = clearedVersion
            return ComposerDraftApplication(record: record, applied: true)
        case .acknowledgement(_, let version):
            guard let local, !local.isDeleted, version >= currentVersion else { return unchanged }
            return ComposerDraftApplication(record: ComposerDraftRecord(chatId: local.chatId,
                encryptedMarkdown: local.encryptedMarkdown, encryptedPreview: local.encryptedPreview,
                revision: local.revision, draftVersion: version, clearedDraftVersion: clearedVersion), applied: true)
        case .deletion(_, let version):
            guard ComposerDraftVersionPolicy.acceptsDeletion(version: version, currentVersion: currentVersion)
            else { return unchanged }
            return deleted(version: max(clearedVersion, version ?? currentVersion), revision: local?.revision ?? 0)
        case .localDeletion:
            return deleted(version: max(clearedVersion, currentVersion), revision: local?.revision ?? 0)
        case .chatDeletion:
            return ComposerDraftApplication(record: nil, applied: true)
        }
    }

    private func deleted(version: Int, revision: Int) -> ComposerDraftApplication {
        ComposerDraftApplication(record: ComposerDraftRecord(chatId: chatId, encryptedMarkdown: "",
            encryptedPreview: "", revision: revision, draftVersion: 0,
            clearedDraftVersion: version, isDeleted: true), applied: true)
    }
}

protocol LegacyComposerDraftStore: Sendable {
    func drafts() async -> [String: String]
    func removeDraft(chatId: String) async
}

extension LegacyComposerDraftStore {
    func removeAllDrafts() async {
        for chatId in await drafts().keys {
            await removeDraft(chatId: chatId)
        }
    }
}

enum ComposerDraftError: Error, Equatable {
    case masterKeyUnavailable
    case encryptedWriteFailed
    case verificationFailed
    case migrationConflict
    case versionConflict
}

@Model
final class PersistedComposerDraft {
    @Attribute(.unique) var chatId: String
    var encryptedMarkdown: String
    var encryptedPreview: String
    var revision: Int
    var draftVersion: Int
    var clearedDraftVersion: Int?
    // Do not shadow PersistentModel.isDeleted (the framework object lifecycle).
    var isDraftTombstone: Bool?

    init(record: ComposerDraftRecord) {
        self.chatId = record.chatId
        self.encryptedMarkdown = record.encryptedMarkdown
        self.encryptedPreview = record.encryptedPreview
        self.revision = record.revision
        self.draftVersion = record.draftVersion
        self.clearedDraftVersion = record.clearedDraftVersion
        self.isDraftTombstone = record.isDeleted
    }

    func update(from record: ComposerDraftRecord) {
        encryptedMarkdown = record.encryptedMarkdown
        encryptedPreview = record.encryptedPreview
        revision = record.revision
        draftVersion = record.draftVersion
        clearedDraftVersion = record.clearedDraftVersion
        isDraftTombstone = record.isDeleted
    }

    func toRecord() -> ComposerDraftRecord {
        ComposerDraftRecord(
            chatId: chatId,
            encryptedMarkdown: encryptedMarkdown,
            encryptedPreview: encryptedPreview,
            revision: revision,
            draftVersion: draftVersion,
            clearedDraftVersion: clearedDraftVersion ?? 0,
            isDeleted: isDraftTombstone ?? false
        )
    }
}
