// Shared encrypted composer draft persistence contract.
// Durable records contain Format D ciphertext and revision metadata only.
// The SwiftData model intentionally has no plaintext or editor-state fields.
// DraftService owns encryption while repositories own ciphertext persistence.
// This boundary remains injectable for production-container verification.

import SwiftData

struct ComposerDraftRecord: Sendable {
    let chatId: String
    var encryptedMarkdown: String
    var encryptedPreview: String
    let revision: Int
    let draftVersion: Int
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

    init(record: ComposerDraftRecord) {
        self.chatId = record.chatId
        self.encryptedMarkdown = record.encryptedMarkdown
        self.encryptedPreview = record.encryptedPreview
        self.revision = record.revision
        self.draftVersion = record.draftVersion
    }

    func update(from record: ComposerDraftRecord) {
        encryptedMarkdown = record.encryptedMarkdown
        encryptedPreview = record.encryptedPreview
        revision = record.revision
        draftVersion = record.draftVersion
    }

    func toRecord() -> ComposerDraftRecord {
        ComposerDraftRecord(
            chatId: chatId,
            encryptedMarkdown: encryptedMarkdown,
            encryptedPreview: encryptedPreview,
            revision: revision,
            draftVersion: draftVersion
        )
    }
}
