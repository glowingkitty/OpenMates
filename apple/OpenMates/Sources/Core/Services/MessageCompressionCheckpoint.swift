// Client-encrypted normal compression checkpoint preparation and exact receipt proof.
// Web: frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.privacy.ciphertext-boundary, storage.integrity.observable-reconcilable, storage.surface.semantic-parity

import Foundation
import CryptoKit

enum MessageCompressionCheckpointError: Error {
    case invalidEvent, invalidReceipt, changedBoundary, writeInProgress
}

/// Immutable proposal metadata. Never sorts or repairs a source manifest supplied
/// by the server: its order and complete membership are part of the save proof.
struct MessageCompressionCheckpointProposal: Equatable {
    let chatID: String
    let checkpointID: String
    let boundaryTimestamp: Int
    let boundaryMessageID: String?
    let coveredMessageIDs: [String]?
    let messageCount: Int
    let summaryTokenEstimate: Int?

    init(fields: [String: Any]) throws {
        guard fields["error"] == nil,
              let chatID = fields["chat_id"] as? String, !chatID.isEmpty,
              let checkpointID = fields["summary_message_id"] as? String, !checkpointID.isEmpty,
              let timestamp = fields["compressed_up_to_timestamp"] as? Int, timestamp >= 0,
              let count = fields["compressed_message_count"] as? Int, count > 0 else { throw MessageCompressionCheckpointError.invalidEvent }
        self.chatID = chatID
        self.checkpointID = checkpointID
        self.boundaryTimestamp = timestamp
        if let value = fields["compressed_up_to_message_id"], !(value is NSNull) {
            guard let boundary = value as? String, !boundary.isEmpty else { throw MessageCompressionCheckpointError.invalidEvent }
            boundaryMessageID = boundary
        } else { boundaryMessageID = nil }
        if let value = fields["covered_message_ids"], !(value is NSNull) {
            guard let manifest = value as? [String], Self.validManifest(manifest),
                  boundaryMessageID.map(manifest.contains) ?? true else { throw MessageCompressionCheckpointError.invalidEvent }
            coveredMessageIDs = manifest
        } else { coveredMessageIDs = nil }
        self.messageCount = count
        if let value = fields["summary_token_estimate"], !(value is NSNull) {
            guard let estimate = value as? Int, estimate >= 0 else { throw MessageCompressionCheckpointError.invalidEvent }
            summaryTokenEstimate = estimate
        } else { summaryTokenEstimate = nil }
    }

    static func validManifest(_ ids: [String]) -> Bool {
        guard !ids.isEmpty, ids.count <= 20_000,
              ids.allSatisfy({ !$0.isEmpty && $0.count <= 255 }),
              ids == Array(Set(ids)).sorted(),
              let bytes = try? JSONSerialization.data(withJSONObject: ids, options: [.withoutEscapingSlashes]),
              bytes.count <= 1_048_576 else { return false }
        return true
    }
}

/// Contains ciphertext and opaque routing/coverage metadata only. Keeping this
/// value pending preserves request identity and randomized ciphertext on retry.
struct MessageCompressionCheckpointPrepared: Codable, Equatable {
    let requestID: String
    let chatID: String
    let checkpointID: String
    let encryptedSummary: String
    let boundaryTimestamp: Int
    let boundaryMessageID: String?
    let coveredMessageIDs: [String]?
    let messageCount: Int
    let summaryTokenEstimate: Int?
    let keyVersion: Int?
    let createdAt: Int

    init(proposal: MessageCompressionCheckpointProposal, encryptedSummary: String,
         requestID: String, keyVersion: Int?, createdAt: Int) throws {
        guard !encryptedSummary.isEmpty, !requestID.isEmpty else { throw MessageCompressionCheckpointError.invalidEvent }
        self.requestID = requestID
        self.chatID = proposal.chatID
        self.checkpointID = proposal.checkpointID
        self.encryptedSummary = encryptedSummary
        self.boundaryTimestamp = proposal.boundaryTimestamp
        self.boundaryMessageID = proposal.boundaryMessageID
        self.coveredMessageIDs = proposal.coveredMessageIDs
        self.messageCount = proposal.messageCount
        self.summaryTokenEstimate = proposal.summaryTokenEstimate
        self.keyVersion = keyVersion
        self.createdAt = createdAt
    }

    var payload: [String: Any] {
        var fields: [String: Any] = ["request_id": requestID, "chat_id": chatID,
            "checkpoint_id": checkpointID, "encrypted_summary": encryptedSummary,
            "compressed_up_to_timestamp": boundaryTimestamp,
            "compressed_up_to_message_id": boundaryMessageID as Any? ?? NSNull(), "covered_message_ids": coveredMessageIDs as Any? ?? NSNull(),
            "compressed_message_count": messageCount, "created_at": createdAt]
        if let summaryTokenEstimate { fields["summary_token_estimate"] = summaryTokenEstimate }
        if let keyVersion { fields["key_version"] = keyVersion }
        return fields
    }

    private static func matchesOptional<T: Equatable>(_ value: Any?, expected: T?) -> Bool {
        if let expected { return value as? T == expected }
        return value == nil || value is NSNull
    }

    func validatedReceipt(_ fields: [String: Any]) throws -> [String: Any] {
        // Current backend receipts omit request_id. The registered waiter owns
        // correlation, and all canonical candidate fields must match. A future
        // echoed request ID, when supplied, must also match the retained request.
        guard fields["request_id"] == nil || fields["request_id"] as? String == requestID,
              fields["chat_id"] as? String == chatID,
              let checkpoint = fields["checkpoint"] as? [String: Any],
              checkpoint["chat_id"] as? String == chatID,
              checkpoint["id"] as? String == checkpointID,
              checkpoint["encrypted_summary"] as? String == encryptedSummary,
              checkpoint["compressed_up_to_timestamp"] as? Int == boundaryTimestamp,
              Self.matchesOptional(checkpoint["compressed_up_to_message_id"], expected: boundaryMessageID),
              Self.matchesOptional(checkpoint["covered_message_ids"], expected: coveredMessageIDs),
              checkpoint["compressed_message_count"] as? Int == messageCount,
              Self.matchesOptional(checkpoint["key_version"], expected: keyVersion) else { throw MessageCompressionCheckpointError.invalidReceipt }
        return try MessageCompressionCheckpointDiskRow.encryptedFields(checkpoint, chatID: chatID)
    }
}

struct MessageCompressionCheckpointJournalBinding: Codable, Equatable {
    let accountID: String
    let server: String
    let teamID: String?
}

/// The complete pending candidate and ownership binding are sealed with the
/// chat key before local persistence, following the retained-send journal pattern.
struct MessageCompressionCheckpointJournal: Codable, Equatable {
    let version: Int
    let binding: MessageCompressionCheckpointJournalBinding
    let prepared: MessageCompressionCheckpointPrepared

    init(binding: MessageCompressionCheckpointJournalBinding, prepared: MessageCompressionCheckpointPrepared) {
        version = 1; self.binding = binding; self.prepared = prepared
    }

    func sealed(using key: SymmetricKey) throws -> String {
        try ComposerEmbedCrypto.encryptContent(String(decoding: JSONEncoder().encode(self), as: UTF8.self), using: key)
    }

    static func open(_ sealed: String, using key: SymmetricKey,
                     binding: MessageCompressionCheckpointJournalBinding, chatID: String, checkpointID: String) throws -> Self {
        let plaintext = try ComposerEmbedCrypto.decryptContent(sealed, using: key)
        let journal = try JSONDecoder().decode(Self.self, from: Data(plaintext.utf8))
        guard journal.version == 1, journal.binding == binding,
              journal.prepared.chatID == chatID, journal.prepared.checkpointID == checkpointID,
              !journal.prepared.encryptedSummary.isEmpty, !journal.prepared.requestID.isEmpty else {
            throw MessageCompressionCheckpointError.invalidEvent
        }
        // Validate the same source metadata constraints as a live event before
        // accepting even an authenticated stored candidate for automatic retry.
        var event = journal.prepared.payload
        event["summary_message_id"] = checkpointID
        _ = try MessageCompressionCheckpointProposal(fields: event)
        return journal
    }
}

struct MessageCompressionCheckpointJournalRecord {
    let chatID: String
    let checkpointID: String
    let encryptedJournal: String
}

/// Shared by the writer and actual SwiftData supplemental-content serialization.
/// Historical rows may omit the additive fields, but supplied fields must retain
/// their exact values. Plain summary content is never admitted to this disk row.
enum MessageCompressionCheckpointDiskRow {
    static func encryptedFields(_ checkpoint: [String: Any], chatID: String) throws -> [String: Any] {
        guard let id = checkpoint["id"] as? String, !id.isEmpty,
              let ciphertext = checkpoint["encrypted_summary"] as? String, !ciphertext.isEmpty,
              let boundary = checkpoint["compressed_up_to_timestamp"] as? Int,
              checkpoint["chat_id"] == nil || checkpoint["chat_id"] as? String == chatID else {
            throw MessageCompressionCheckpointError.invalidReceipt
        }
        var row: [String: Any] = ["id": id, "chat_id": chatID, "encrypted_summary": ciphertext,
                                 "compressed_up_to_timestamp": boundary]
        if let value = checkpoint["compressed_up_to_message_id"], !(value is NSNull) {
            guard let stableBoundary = value as? String, !stableBoundary.isEmpty else { throw MessageCompressionCheckpointError.invalidReceipt }
            row["compressed_up_to_message_id"] = stableBoundary
        }
        if let value = checkpoint["covered_message_ids"], !(value is NSNull) {
            guard let ids = value as? [String], MessageCompressionCheckpointProposal.validManifest(ids) else {
                throw MessageCompressionCheckpointError.invalidReceipt
            }
            row["covered_message_ids"] = ids
        }
        for key in ["compressed_message_count", "summary_token_estimate", "key_version", "created_at", "updated_at"] {
            if let value = checkpoint[key] { row[key] = value }
        }
        return row
    }
}

/// One instance per scoped checkpoint. The pending value is set before sending
/// and is retired only after exact canonical proof and successful local save.
@MainActor
final class MessageCompressionCheckpointWriter {
    private(set) var prepared: MessageCompressionCheckpointPrepared?
    private(set) var isPersisted = false
    private var isWriting = false

    init(prepared: MessageCompressionCheckpointPrepared? = nil) { self.prepared = prepared }

    func save(proposal: MessageCompressionCheckpointProposal, summary: String, keyVersion: Int? = nil,
              requestID: String = UUID().uuidString.lowercased(), createdAt: Int = Int(Date().timeIntervalSince1970),
              encrypt: (String) async throws -> String,
              request: @MainActor ([String: Any], @escaping ([String: Any]) -> Bool) async throws -> [String: Any],
              validate: () async throws -> Void,
              retain: (MessageCompressionCheckpointPrepared) throws -> Void = { _ in },
              persist: ([String: Any]) throws -> Void) async throws {
        guard !isWriting else { throw MessageCompressionCheckpointError.writeInProgress }
        isWriting = true
        defer { isWriting = false }
        try await validate()
        if let prepared {
            guard prepared.chatID == proposal.chatID, prepared.checkpointID == proposal.checkpointID,
                  prepared.boundaryTimestamp == proposal.boundaryTimestamp,
                  prepared.boundaryMessageID == proposal.boundaryMessageID,
                  prepared.coveredMessageIDs == proposal.coveredMessageIDs,
                  prepared.messageCount == proposal.messageCount,
                  prepared.summaryTokenEstimate == proposal.summaryTokenEstimate,
                  prepared.keyVersion == keyVersion else { throw MessageCompressionCheckpointError.changedBoundary }
        } else {
            guard !summary.isEmpty else { throw MessageCompressionCheckpointError.invalidEvent }
            let encrypted = try await encrypt(summary)
            try await validate()
            prepared = try .init(proposal: proposal, encryptedSummary: encrypted,
                                 requestID: requestID, keyVersion: keyVersion, createdAt: createdAt)
        }
        if isPersisted { return }
        try await writePrepared(request: request, validate: validate, retain: retain, persist: persist)
    }

    func retry(request: @MainActor ([String: Any], @escaping ([String: Any]) -> Bool) async throws -> [String: Any],
               validate: () async throws -> Void,
               retain: (MessageCompressionCheckpointPrepared) throws -> Void = { _ in },
               persist: ([String: Any]) throws -> Void) async throws {
        guard prepared != nil, !isPersisted else { return }
        guard !isWriting else { throw MessageCompressionCheckpointError.writeInProgress }
        isWriting = true
        defer { isWriting = false }
        try await writePrepared(request: request, validate: validate, retain: retain, persist: persist)
    }

    private func writePrepared(request: @MainActor ([String: Any], @escaping ([String: Any]) -> Bool) async throws -> [String: Any],
                               validate: () async throws -> Void,
                               retain: (MessageCompressionCheckpointPrepared) throws -> Void,
                               persist: ([String: Any]) throws -> Void) async throws {
        guard let prepared else { return }
        try await validate()
        try retain(prepared)
        let receipt = try await request(prepared.payload, { (try? prepared.validatedReceipt($0)) != nil })
        let diskRow = try prepared.validatedReceipt(receipt)
        try await validate()
        try persist(diskRow)
        isPersisted = true
    }
}
