// Web source: frontend/packages/ui/src/services/voiceCallMessages.ts, voiceCallLifecycleEvent.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.transcripts, video-call.chat.typed-input,
// video-call.chat.call-events, video-call.privacy, video-call.chat.compressed-context, video-call.chat.skill-integration

import Foundation
import CryptoKit

protocol NativeVoiceCallCryptography: Sendable {
    func encrypt(_ text: String, scope: NativeVoiceCallScope) async throws -> String
    func decrypt(_ ciphertext: String, scope: NativeVoiceCallScope) async throws -> String
}

/// Uses existing Format A chat encryption, including OM fingerprint, through
/// CryptoManager. Never substitute raw AES output or persist a plaintext model.
struct NativeVoiceCallChatCryptography: NativeVoiceCallCryptography {
    let key: @Sendable (NativeVoiceCallScope) async throws -> SymmetricKey
    let isCurrent: @Sendable (NativeVoiceCallScope) async -> Bool
    func encrypt(_ text: String, scope: NativeVoiceCallScope) async throws -> String {
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        let key = try await key(scope)
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        let value = try await CryptoManager.shared.encryptContent(text, key: key)
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        return value
    }
    func decrypt(_ ciphertext: String, scope: NativeVoiceCallScope) async throws -> String {
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        let key = try await key(scope)
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        let value = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        return value
    }
}

/// All content/attribution fields are ciphertext. Scope and protocol identifiers
/// are metadata; an unaccepted typed row survives disconnect for explicit retry.
struct NativeVoiceCallStoredRow: Codable, Equatable, Sendable {
    struct Revision: Codable, Equatable, Sendable {
        let requestID: String
        let revision: Int
        let ciphertext: String
        let ciphertextHash: String
        let encryptedCategory: String?
        let encryptedModelName: String?
        let encryptedSenderName: String?
    }
    let callID: String
    let messageID: String
    let role: String
    let createdAt: Int
    let userMessageID: String?
    var revision: Int
    var ciphertext: String
    var final: Bool
    var interrupted: Bool
    var typedPending: Bool
    var pending: [Revision]
    // Optional encrypted additions decode older outboxes without migration.
    // Provider text is separate so speech revisions cannot remove committed cards.
    var sourceCreatedAt: Int? = nil
    var providerFinal: Bool? = nil
    var lastFinalRevision: Int? = nil
    var providerTextCiphertext: String? = nil
    var encryptedArtifactReferences: String? = nil
    var encryptedCategory: String? = nil
    var encryptedModelName: String? = nil
    var encryptedSenderName: String? = nil
}

protocol NativeVoiceCallOutboxStorage: Sendable {
    func load(scope: NativeVoiceCallScope) async throws -> [NativeVoiceCallStoredRow]
    /// Atomic replacement, ciphertext only; caller serializes read-modify-write.
    func save(_ rows: [NativeVoiceCallStoredRow], scope: NativeVoiceCallScope) async throws
}

actor NativeVoiceCallFileOutboxStorage: NativeVoiceCallOutboxStorage {
    private let directory: URL
    init(directory: URL) { self.directory = directory }
    private func url(_ scope: NativeVoiceCallScope) throws -> URL {
        // Generation is a live callback fence; retained ciphertext is scoped to
        // stable account/profile/chat so relaunch can replay after fresh auth.
        let identity = [scope.accountID, scope.profileID, scope.chatID]
        let data = try JSONEncoder().encode(identity)
        let filename = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        return directory.appendingPathComponent(filename + ".json")
    }
    func load(scope: NativeVoiceCallScope) throws -> [NativeVoiceCallStoredRow] {
        let path = try url(scope)
        guard FileManager.default.fileExists(atPath: path.path) else { return [] }
        let data = try Data(contentsOf: path)
        guard data.count <= 16 * 1_024 * 1_024 else { throw NativeVoiceCallError.persistenceFailed }
        return try JSONDecoder().decode([NativeVoiceCallStoredRow].self, from: data)
    }
    func save(_ rows: [NativeVoiceCallStoredRow], scope: NativeVoiceCallScope) throws {
        let data = try JSONEncoder().encode(rows)
        guard data.count <= 16 * 1_024 * 1_024 else { throw NativeVoiceCallError.persistenceFailed }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let path = try url(scope)
        try data.write(to: path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
}

/// Revision updates and ACK removal are serialized even while crypto/storage
/// awaits. Outbound retries read retained ciphertext; randomized encryption runs
/// once for a new revision, never to retry an attempted revision.
actor NativeVoiceCallOutbox: NativeVoiceCallPersistence, NativeVoiceCallArtifactPersistence {
    typealias Current = @Sendable (NativeVoiceCallScope) async -> Bool
    typealias CanonicalCheckpoint = @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame) async throws -> NativeVoiceCallFrame
    private let crypto: any NativeVoiceCallCryptography
    private let storage: any NativeVoiceCallOutboxStorage
    private let isCurrent: Current
    private let checkpoint: CanonicalCheckpoint
    private var locked = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    init(crypto: any NativeVoiceCallCryptography, storage: any NativeVoiceCallOutboxStorage,
         isCurrent: @escaping Current, checkpoint: @escaping CanonicalCheckpoint) {
        self.crypto = crypto; self.storage = storage; self.isCurrent = isCurrent; self.checkpoint = checkpoint
    }
    private func acquire() async {
        if !locked { locked = true; return }
        await withCheckedContinuation { waiters.append($0) }
    }
    private func release() {
        if waiters.isEmpty { locked = false } else { waiters.removeFirst().resume() }
    }
    private func check(_ scope: NativeVoiceCallScope) async throws {
        try Task.checkCancellation()
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
    }
    private func save(_ rows: [NativeVoiceCallStoredRow], scope: NativeVoiceCallScope) async throws {
        try await check(scope)
        try await storage.save(rows, scope: scope)
        try await check(scope)
    }
    func stageTyped(scope: NativeVoiceCallScope, callID: String, messageID: String,
                    text: String, createdAt: Int) async throws {
        await acquire(); defer { release() }
        try await check(scope)
        var rows = try await storage.load(scope: scope)
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !rows.contains(where: { $0.messageID == messageID }) else { throw NativeVoiceCallError.persistenceFailed }
        let ciphertext = try await crypto.encrypt(text, scope: scope)
        rows.append(.init(callID: callID, messageID: messageID, role: "user", createdAt: createdAt,
                          userMessageID: messageID, revision: 1, ciphertext: ciphertext, final: false,
                          interrupted: false, typedPending: true, pending: []))
        try await save(rows, scope: scope)
    }
    func transcript(scope: NativeVoiceCallScope, value: NativeVoiceCallTranscript) async throws {
        await acquire(); defer { release() }
        try await check(scope)
        var rows = try await storage.load(scope: scope)
        let index = rows.firstIndex { $0.messageID == value.messageID }
        let previous = index.map { rows[$0] }
        if let previous {
            let artifactOnly = previous.encryptedArtifactReferences != nil && previous.sourceCreatedAt == nil
            guard previous.callID == value.callID, previous.role == value.role.rawValue,
                  previous.userMessageID == nil || value.userMessageID == nil || previous.userMessageID == value.userMessageID,
                  artifactOnly || (previous.sourceCreatedAt ?? previous.createdAt) == value.createdAt else { throw NativeVoiceCallError.persistenceFailed }
            if (previous.providerFinal ?? previous.final) && !value.final { return }
            let sameText = try await providerText(previous, scope: scope) == value.text
            if previous.typedPending && (!sameText || !value.final) { throw NativeVoiceCallError.textRejected }
            if (previous.providerFinal ?? previous.final) && value.final && sameText && previous.interrupted == value.interrupted { return }
        }
        let references: [NativeVoiceCallArtifactReference]
        if let previous { references = try await self.references(previous, scope: scope) } else { references = [] }
        guard value.role == .assistant || references.isEmpty else { throw NativeVoiceCallError.persistenceFailed }
        let content = try Self.content(value.text, references: references)
        let lastFinal = previous?.lastFinalRevision ?? (previous?.final == true ? previous?.revision ?? 0 : 0)
        guard lastFinal >= 0, lastFinal < Int.max else { throw NativeVoiceCallError.persistenceFailed }
        let revision = value.final ? max(1, lastFinal + 1, previous?.revision ?? 1) : max(1, previous?.revision ?? 1)
        let ciphertext = try await crypto.encrypt(content, scope: scope)
        let providerCiphertext: String
        if content == value.text { providerCiphertext = ciphertext }
        else { providerCiphertext = try await crypto.encrypt(value.text, scope: scope) }
        let category = try await encrypted(value.mateCategory, scope: scope) ?? previous?.encryptedCategory
        let model = try await encrypted(value.modelName, scope: scope) ?? previous?.encryptedModelName
        let sender = try await encrypted(value.mateName, scope: scope) ?? previous?.encryptedSenderName
        var pending = previous?.pending ?? []
        if value.final {
            pending.append(.init(requestID: UUID().uuidString.lowercased(), revision: revision,
                ciphertext: ciphertext, ciphertextHash: Self.hash(ciphertext), encryptedCategory: category,
                encryptedModelName: model, encryptedSenderName: sender))
        }
        var row = NativeVoiceCallStoredRow(callID: value.callID, messageID: value.messageID,
            role: value.role.rawValue, createdAt: previous?.createdAt ?? value.createdAt,
            userMessageID: previous?.userMessageID ?? value.userMessageID, revision: revision, ciphertext: ciphertext,
            final: value.final, interrupted: value.interrupted, typedPending: false, pending: pending)
        row.sourceCreatedAt = value.createdAt; row.providerFinal = value.final
        row.lastFinalRevision = value.final ? revision : lastFinal
        row.providerTextCiphertext = providerCiphertext; row.encryptedArtifactReferences = previous?.encryptedArtifactReferences
        row.encryptedCategory = category; row.encryptedModelName = model; row.encryptedSenderName = sender
        if let index { rows[index] = row } else { rows.append(row) }
        try await save(rows, scope: scope)
    }

    /// The caller has confirmed actual embed persistence and the controller has
    /// checked its issued broker tuple. No uncommitted reference is inferred from
    /// provider prose, an arbitrary ID, a processing card or an outbox ACK.
    func associateArtifact(scope: NativeVoiceCallScope, value: NativeVoiceCallArtifactAssociation) async throws -> NativeVoiceCallTranscript {
        await acquire(); defer { release() }
        try await check(scope)
        let reference = try NativeVoiceCallArtifactReference(validating: value.reference.fields)
        var rows = try await storage.load(scope: scope)
        let index = rows.firstIndex { $0.messageID == value.assistantMessageID }
        let previous = index.map { rows[$0] }
        guard !value.callID.isEmpty, !value.assistantMessageID.isEmpty, !value.userMessageID.isEmpty,
              value.assistantMessageID != value.userMessageID, value.createdAt > 0 else { throw NativeVoiceCallError.invalidResponse }
        if let previous {
            guard previous.callID == value.callID, previous.role == "assistant", !previous.typedPending,
                  previous.userMessageID == nil || previous.userMessageID == value.userMessageID else { throw NativeVoiceCallError.persistenceFailed }
        }
        var references: [NativeVoiceCallArtifactReference]
        if let previous { references = try await self.references(previous, scope: scope) } else { references = [] }
        if let existing = references.firstIndex(where: { $0.embedID == reference.embedID }) {
            guard references[existing].type == reference.type else { throw NativeVoiceCallError.invalidResponse }
            if references[existing] == reference, let previous { return try await projection(previous, scope: scope) }
            references[existing] = reference
        } else {
            guard references.count < 16 else { throw NativeVoiceCallError.contextTooLarge }
            references.append(reference)
        }
        let spoken: String
        if let previous { spoken = try await providerText(previous, scope: scope) } else { spoken = "" }
        let content = try Self.content(spoken, references: references)
        let lastFinal = previous?.lastFinalRevision ?? (previous?.final == true ? previous?.revision ?? 0 : 0)
        guard lastFinal >= 0, lastFinal < Int.max else { throw NativeVoiceCallError.persistenceFailed }
        let revision = max(1, lastFinal + 1, previous?.revision ?? 1)
        let ciphertext = try await crypto.encrypt(content, scope: scope)
        let encoded = try JSONEncoder().encode(references.map(\.fields))
        guard let text = String(data: encoded, encoding: .utf8) else { throw NativeVoiceCallError.persistenceFailed }
        let encryptedReferences = try await crypto.encrypt(text, scope: scope)
        let category = previous?.encryptedCategory ?? previous?.pending.last?.encryptedCategory
        let model = previous?.encryptedModelName ?? previous?.pending.last?.encryptedModelName
        let sender = previous?.encryptedSenderName ?? previous?.pending.last?.encryptedSenderName
        let finalCategory = try await encryptedIfMissing(category, plaintext: value.mateCategory, scope: scope)
        let finalModel = try await encryptedIfMissing(model, plaintext: value.modelName, scope: scope)
        let finalSender = try await encryptedIfMissing(sender, plaintext: value.mateName, scope: scope)
        var pending = previous?.pending ?? []
        pending.append(.init(requestID: UUID().uuidString.lowercased(), revision: revision,
            ciphertext: ciphertext, ciphertextHash: Self.hash(ciphertext), encryptedCategory: finalCategory,
            encryptedModelName: finalModel, encryptedSenderName: finalSender))
        var row = NativeVoiceCallStoredRow(callID: value.callID, messageID: value.assistantMessageID,
            role: "assistant", createdAt: previous?.createdAt ?? value.createdAt, userMessageID: value.userMessageID,
            revision: revision, ciphertext: ciphertext, final: true, interrupted: previous?.interrupted ?? false,
            typedPending: false, pending: pending)
        row.sourceCreatedAt = previous?.sourceCreatedAt ?? (previous?.encryptedArtifactReferences == nil ? previous?.createdAt : nil)
        row.providerFinal = previous?.providerFinal ?? (previous?.final ?? false)
        row.lastFinalRevision = revision
        // A pre-extension row's ciphertext contains its provider text only.
        row.providerTextCiphertext = previous?.providerTextCiphertext ?? (previous?.encryptedArtifactReferences == nil ? previous?.ciphertext : nil)
        row.encryptedArtifactReferences = encryptedReferences
        row.encryptedCategory = finalCategory; row.encryptedModelName = finalModel; row.encryptedSenderName = finalSender
        if let index { rows[index] = row } else { rows.append(row) }
        try await save(rows, scope: scope)
        return try await projection(row, scope: scope)
    }

    func publishedTranscript(scope: NativeVoiceCallScope, callID: String, messageID: String) async throws -> NativeVoiceCallTranscript {
        await acquire(); defer { release() }
        try await check(scope)
        let rows = try await storage.load(scope: scope)
        guard let row = rows.first(where: { $0.messageID == messageID }), row.callID == callID else { throw NativeVoiceCallError.persistenceFailed }
        return try await projection(row, scope: scope)
    }
    private func projection(_ row: NativeVoiceCallStoredRow, scope: NativeVoiceCallScope) async throws -> NativeVoiceCallTranscript {
        guard let role = NativeVoiceCallTranscript.Role(rawValue: row.role) else { throw NativeVoiceCallError.persistenceFailed }
        let content = try await crypto.decrypt(row.ciphertext, scope: scope)
        let category = try await decrypted(row.encryptedCategory ?? row.pending.last?.encryptedCategory, scope: scope)
        let model = try await decrypted(row.encryptedModelName ?? row.pending.last?.encryptedModelName, scope: scope)
        let sender = try await decrypted(row.encryptedSenderName ?? row.pending.last?.encryptedSenderName, scope: scope)
        let refs = try await references(row, scope: scope)
        guard role == .assistant || refs.isEmpty else { throw NativeVoiceCallError.persistenceFailed }
        try await check(scope)
        return .init(callID: row.callID, messageID: row.messageID, role: role, text: content,
            final: row.final, interrupted: row.interrupted, userMessageID: row.userMessageID, createdAt: row.createdAt,
            modelName: model, mateCategory: category, mateName: sender, embedReferences: refs)
    }
    private func providerText(_ row: NativeVoiceCallStoredRow, scope: NativeVoiceCallScope) async throws -> String {
        if let ciphertext = row.providerTextCiphertext { return try await crypto.decrypt(ciphertext, scope: scope) }
        if row.encryptedArtifactReferences != nil { return "" }
        return try await crypto.decrypt(row.ciphertext, scope: scope)
    }
    private func references(_ row: NativeVoiceCallStoredRow, scope: NativeVoiceCallScope) async throws -> [NativeVoiceCallArtifactReference] {
        guard let encrypted = row.encryptedArtifactReferences else { return [] }
        let text = try await crypto.decrypt(encrypted, scope: scope)
        guard text.utf8.count <= 256_000, let bytes = text.data(using: .utf8) else { throw NativeVoiceCallError.persistenceFailed }
        let fields = try JSONDecoder().decode([NativeVoiceCallFrame].self, from: bytes)
        guard fields.count <= 16 else { throw NativeVoiceCallError.persistenceFailed }
        let values = try fields.map { try NativeVoiceCallArtifactReference(validating: $0) }
        guard Set(values.map(\.embedID)).count == values.count else { throw NativeVoiceCallError.persistenceFailed }
        return values
    }
    private static func content(_ spoken: String, references: [NativeVoiceCallArtifactReference]) throws -> String {
        let content = try ([spoken] + references.map { try $0.markdown }).filter { !$0.isEmpty }.joined(separator: "\n\n")
        guard content.utf8.count <= 256_000 else { throw NativeVoiceCallError.contextTooLarge }
        return content
    }
    private func decrypted(_ text: String?, scope: NativeVoiceCallScope) async throws -> String? {
        guard let text else { return nil }; return try await crypto.decrypt(text, scope: scope)
    }
    private func encryptedIfMissing(_ current: String?, plaintext: String?, scope: NativeVoiceCallScope) async throws -> String? {
        if let current { return current }; return try await encrypted(plaintext, scope: scope)
    }
    private func encrypted(_ text: String?, scope: NativeVoiceCallScope) async throws -> String? {
        guard let text else { return nil }
        return try await crypto.encrypt(text, scope: scope)
    }
    private static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    /// Canonical socket adapter sends these frames as call_message_completed.
    /// Repeating pendingFrames returns byte-identical ciphertext/request/revision.
    func pendingFrames(scope: NativeVoiceCallScope) async throws -> [NativeVoiceCallFrame] {
        await acquire(); defer { release() }
        try await check(scope)
        let rows = try await storage.load(scope: scope)
        try await check(scope)
        return rows.flatMap { row in row.pending.map { entry in
            var frame: NativeVoiceCallFrame = ["type": .string("call_message_completed"),
                "request_id": .string(entry.requestID), "call_id": .string(row.callID),
                "chat_id": .string(scope.chatID), "message_id": .string(row.messageID),
                "role": .string(row.role), "encrypted_content": .string(entry.ciphertext),
                "created_at": .number(Double(row.createdAt)), "revision": .number(Double(entry.revision))]
            // The broker echoes a user's self ID for transcript identity, but
            // canonical persistence accepts this causal link on assistant rows only.
            if row.role == "assistant", let value = row.userMessageID {
                frame["user_message_id"] = .string(value)
            }
            if let value = entry.encryptedCategory { frame["encrypted_category"] = .string(value) }
            if let value = entry.encryptedModelName { frame["encrypted_model_name"] = .string(value) }
            if let value = entry.encryptedSenderName { frame["encrypted_sender_name"] = .string(value) }
            return frame
        } }
    }
    struct ConfirmedProof: Sendable {
        let revision: Int
        let ciphertext: String
        let ciphertextHash: String
    }
    /// Delayed voice_action_completed recovery may acknowledge only this exact
    /// final, fully ACKed row; it must not re-encrypt or dispatch text inference.
    func confirmedProof(scope: NativeVoiceCallScope, callID: String, messageID: String,
                        revision: Int) async throws -> ConfirmedProof? {
        await acquire(); defer { release() }
        try await check(scope)
        let rows = try await storage.load(scope: scope)
        try await check(scope)
        guard let row = rows.first(where: { $0.messageID == messageID }), row.callID == callID,
              row.role == "assistant", row.final, !row.typedPending, row.pending.isEmpty,
              row.revision == revision, revision > 0 else { return nil }
        return .init(revision: revision, ciphertext: row.ciphertext, ciphertextHash: Self.hash(row.ciphertext))
    }

    /// request_id binds the exact retained row/revision/ciphertext. Optional echoed
    /// identity/hash fields must also match; unknown/old ACKs remove nothing.
    func acknowledge(scope: NativeVoiceCallScope, frame: NativeVoiceCallFrame) async throws -> Bool {
        await acquire(); defer { release() }
        try await check(scope)
        guard frame["type"]?.string == "call_message_confirmed",
              let requestID = frame["request_id"]?.string,
              let revision = frame["revision"]?.number,
              ["created", "updated", "replayed"].contains(frame["outcome"]?.string ?? "") else { return false }
        var rows = try await storage.load(scope: scope)
        for index in rows.indices {
            guard let entry = rows[index].pending.first(where: { $0.requestID == requestID }),
                  Double(entry.revision) == revision else { continue }
            let expected = ["call_id": rows[index].callID, "chat_id": scope.chatID,
                            "message_id": rows[index].messageID, "ciphertext_hash": entry.ciphertextHash]
            guard expected.allSatisfy({ frame[$0.key] == nil || frame[$0.key]?.string == $0.value }) else { return false }
            rows[index].pending.removeAll { $0.requestID == requestID && $0.revision == entry.revision }
            try await save(rows, scope: scope)
            return true
        }
        return false
    }
    func lifecycle(scope: NativeVoiceCallScope, callID: String, started: Bool,
                   createdAt: Int, activeSeconds: TimeInterval) async throws {
        // Lifecycle uses a separate canonical system_message protocol. Keep it
        // under the same crypto/scope fence; adapter owns deterministic ID/ACK.
        let event: NativeVoiceCallFrame = ["type": .string("native_voice_lifecycle"),
            "call_id": .string(callID), "action": .string(started ? "started" : "ended"),
            "created_at": .number(Double(createdAt)), "active_elapsed_seconds": .number(floor(activeSeconds))]
        try await check(scope)
        _ = try await checkpoint(scope, callID, event)
        try await check(scope)
    }
    func compression(scope: NativeVoiceCallScope, callID: String,
                     frame: NativeVoiceCallFrame) async throws -> NativeVoiceCallFrame {
        await acquire(); defer { release() }
        try await check(scope)
        let result = try await checkpoint(scope, callID, frame)
        try await check(scope)
        guard result["type"]?.string == "voice_compression_confirmed", result["call_id"]?.string == callID
        else { throw NativeVoiceCallError.persistenceFailed }
        return result
    }
}
