// Encrypted composer read-back copy: persistence contract.
// Durable records contain Format D ciphertext and revision metadata only.
// The SwiftData model intentionally has no plaintext or editor-state fields.
// DraftService owns encryption while repositories own ciphertext persistence;
// the server draft, its versions and tombstones live in the Rust core.
// This boundary remains injectable for production-container verification.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.drafts.preview-persistence
// Specification: specifications/architecture/drafts/specification.yml
// Assertions: drafts.persistence.local-first-encrypted

import Foundation
import SwiftData

struct ComposerDraftRecord: Sendable, Equatable {
    let chatId: String
    var encryptedMarkdown: String
    var encryptedPreview: String
    /// Master-key Format D ciphertext for local-only composer embed snapshots.
    /// The persisted name is retained for migration compatibility.
    /// This field never participates in the draft sync wire contract.
    var encryptedRecordingPayload: String? = nil
    let revision: Int
    let draftVersion: Int
    var clearedDraftVersion: Int = 0
    var isDeleted: Bool = false
}

struct ComposerDraft: Sendable {
    let canonicalMarkdown: String
    let preview: String
    let attachments: [ComposerDraftAttachment]
    let revision: Int
    let draftVersion: Int

    var recordings: [EmbedRecord] {
        attachments.map(\.embedRecord).filter { $0.type == "audio-recording" }
    }
}

/// Embed metadata and optional local bytes stored inside the master-key encrypted
/// draft companion payload. No attachment plaintext is written to SwiftData.
struct ComposerDraftAttachment: Sendable {
    let embedRecord: EmbedRecord
    let localData: Data?
}

protocol ComposerDraftRepository: Sendable {
    func upsert(_ record: ComposerDraftRecord) async throws
    func record(chatId: String) async throws -> ComposerDraftRecord?
    func remove(chatId: String) async throws
    func removeAll() async throws
    func allRecords() async throws -> [ComposerDraftRecord]
    /// Atomically compare the stored copy and write in the captured account cache.
    func apply(_ mutation: ComposerDraftMutation, knownVersion: Int, knownClearedVersion: Int,
               expectedScope: UUID?) async throws -> ComposerDraftApplication
}

/// Reject known empty editor representations; unknown markup stays recoverable.
/// Embedded attachments and mentions are substantive content even without prose.
enum ComposerDraftContentPolicy {
    private static let emptyFences = try! NSRegularExpression(pattern: "```[^\\n`]*\\n\\s*```")
    static func hasContent(_ markdown: String) -> Bool {
        let trimmed = markdown.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        if let data = trimmed.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if object["type"] as? String == "doc" { return nodeHasContent(object) }
            if object["version"] as? Int == 1, let nodes = object["nodes"] as? [[String: Any]] {
                return nodes.contains { node in
                    switch node["kind"] as? String {
                    case "text": return !(node["source"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    case "hardBreak": return false
                    default: return true
                    }
                }
            }
        }
        let withoutEmptyCode = emptyFences.stringByReplacingMatches(in: trimmed,
            range: NSRange(trimmed.startIndex..., in: trimmed), withTemplate: "")
        return !withoutEmptyCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
    private static func nodeHasContent(_ node: [String: Any]) -> Bool {
        let type = node["type"] as? String ?? ""
        if type == "text" { return !(node["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        let containers: Set<String> = ["doc", "paragraph", "blockquote", "bulletList", "orderedList", "listItem", "heading", "codeBlock", "hardBreak"]
        guard containers.contains(type) else { return true }
        return (node["content"] as? [[String: Any]] ?? []).contains(where: nodeHasContent)
    }
}

/// The monotonic draft/deletion decision of the legacy chat-store metadata.
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

/// Local compare-and-write changes of the composer copy.
enum ComposerDraftMutation: Sendable {
    case previewRepair(ComposerDraftRecord)
    /// Cleanup may only clear the exact ciphertext snapshot verified empty after unlock.
    case verifiedEmptyDeletion(ComposerDraftRecord)
    case localDeletion(chatId: String)

    var chatId: String {
        switch self {
        case .previewRepair(let record), .verifiedEmptyDeletion(let record): return record.chatId
        case .localDeletion(let id): return id
        }
    }

    func applying(to local: ComposerDraftRecord?, knownVersion: Int = 0,
                  knownClearedVersion: Int = 0) -> ComposerDraftApplication {
        let currentVersion = max(local?.draftVersion ?? 0, knownVersion)
        let clearedVersion = max(local?.clearedDraftVersion ?? 0, knownClearedVersion)
        let unchanged = ComposerDraftApplication(record: local, applied: false)
        switch self {
        case .previewRepair(var record):
            // Preview derivation awaits decryption/encryption. It may only fill
            // the exact still-active row, never reopen a cleared/replaced draft.
            guard let local, !local.isDeleted, local.encryptedPreview.isEmpty,
                  local.draftVersion == record.draftVersion, local.revision == record.revision,
                  local.encryptedMarkdown == record.encryptedMarkdown else { return unchanged }
            record.clearedDraftVersion = clearedVersion
            record.encryptedRecordingPayload = local.encryptedRecordingPayload
            return ComposerDraftApplication(record: record, applied: true)
        case .verifiedEmptyDeletion(let record):
            guard let local, !local.isDeleted, local == record,
                  knownVersion <= record.draftVersion else { return unchanged }
            return deleted(version: max(clearedVersion, currentVersion), revision: local.revision)
        case .localDeletion:
            return deleted(version: max(clearedVersion, currentVersion), revision: local?.revision ?? 0)
        }
    }

    private func deleted(version: Int, revision: Int) -> ComposerDraftApplication {
        ComposerDraftApplication(record: ComposerDraftRecord(chatId: chatId, encryptedMarkdown: "",
            encryptedPreview: "", revision: revision, draftVersion: 0,
            clearedDraftVersion: version, isDeleted: true), applied: true)
    }
}

enum ComposerDraftError: Error, Equatable {
    case masterKeyUnavailable
    case encryptedWriteFailed
    case verificationFailed
    case versionConflict
}

@Model
final class PersistedComposerDraft {
    @Attribute(.unique) var chatId: String
    var encryptedMarkdown: String
    var encryptedPreview: String
    // Optional so existing SwiftData stores migrate without a mandatory value.
    // The persisted name is retained while the encrypted payload now also owns
    // image/file draft snapshots.
    var encryptedRecordingPayload: String? = nil
    var revision: Int
    var draftVersion: Int
    var clearedDraftVersion: Int?
    // Do not shadow PersistentModel.isDeleted (the framework object lifecycle).
    var isDraftTombstone: Bool?

    init(record: ComposerDraftRecord) {
        self.chatId = record.chatId
        self.encryptedMarkdown = record.encryptedMarkdown
        self.encryptedPreview = record.encryptedPreview
        self.encryptedRecordingPayload = record.encryptedRecordingPayload
        self.revision = record.revision
        self.draftVersion = record.draftVersion
        self.clearedDraftVersion = record.clearedDraftVersion
        self.isDraftTombstone = record.isDeleted
    }

    func update(from record: ComposerDraftRecord) {
        encryptedMarkdown = record.encryptedMarkdown
        encryptedPreview = record.encryptedPreview
        encryptedRecordingPayload = record.encryptedRecordingPayload
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
            encryptedRecordingPayload: encryptedRecordingPayload,
            revision: revision,
            draftVersion: draftVersion,
            clearedDraftVersion: clearedDraftVersion ?? 0,
            isDeleted: isDraftTombstone ?? false
        )
    }
}
