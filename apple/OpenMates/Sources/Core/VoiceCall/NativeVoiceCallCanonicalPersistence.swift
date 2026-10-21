// Web source: voiceCallMessages.ts, voiceCallTools.ts, chatSyncServiceHandlersAI.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-events, video-call.chat.compressed-context,
// video-call.privacy, video-call.lifecycle.recovery-and-billing

import Foundation
import CryptoKit

struct NativeVoiceCallAuxiliaryRecord: Codable, Sendable {
    /// Ciphertext and metadata only, suitable for canonical socket replay.
    let frame: NativeVoiceCallFrame
    var confirmed: Bool
}
protocol NativeVoiceCallAuxiliaryStorage: Sendable {
    func load(scope: NativeVoiceCallScope) async throws -> [String: NativeVoiceCallAuxiliaryRecord]
    func save(_ records: [String: NativeVoiceCallAuxiliaryRecord], scope: NativeVoiceCallScope) async throws
}
actor NativeVoiceCallFileAuxiliaryStorage: NativeVoiceCallAuxiliaryStorage {
    private let directory: URL
    init(directory: URL) { self.directory = directory }
    private func url(_ scope: NativeVoiceCallScope) throws -> URL {
        let identity = try JSONEncoder().encode([scope.accountID, scope.profileID, scope.chatID])
        let name = SHA256.hash(data: identity).map { String(format: "%02x", $0) }.joined()
        return directory.appendingPathComponent(name + ".aux.json")
    }
    func load(scope: NativeVoiceCallScope) throws -> [String: NativeVoiceCallAuxiliaryRecord] {
        let path = try url(scope)
        guard FileManager.default.fileExists(atPath: path.path) else { return [:] }
        let data = try Data(contentsOf: path)
        guard data.count <= 16 * 1_024 * 1_024 else { throw NativeVoiceCallError.persistenceFailed }
        return try JSONDecoder().decode([String: NativeVoiceCallAuxiliaryRecord].self, from: data)
    }
    func save(_ records: [String: NativeVoiceCallAuxiliaryRecord], scope: NativeVoiceCallScope) throws {
        let data = try JSONEncoder().encode(records)
        guard data.count <= 16 * 1_024 * 1_024 else { throw NativeVoiceCallError.persistenceFailed }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let path = try url(scope)
        try data.write(to: path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
}

/// An app adapter wraps WebSocketManager.sendAndWait here. Register the canonical
/// receipt before sending, preserve transportGeneration, and use 15s/30s timeout.
/// This helper validates the returned receipt again before broker confirmation.
actor NativeVoiceCallCanonicalPersistence {
    typealias Request = @Sendable (NativeVoiceCallScope, NativeVoiceCallFrame, String) async throws -> NativeVoiceCallFrame
    private let crypto: any NativeVoiceCallCryptography
    private let storage: any NativeVoiceCallAuxiliaryStorage
    private let request: Request
    private let isCurrent: @Sendable (NativeVoiceCallScope) async -> Bool
    private let keyVersion: @Sendable (NativeVoiceCallScope) async throws -> Int?
    private let now: @Sendable () -> Date
    private var locked = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    init(crypto: any NativeVoiceCallCryptography, storage: any NativeVoiceCallAuxiliaryStorage,
         isCurrent: @escaping @Sendable (NativeVoiceCallScope) async -> Bool,
         keyVersion: @escaping @Sendable (NativeVoiceCallScope) async throws -> Int?,
         request: @escaping Request, now: @escaping @Sendable () -> Date = { Date() }) {
        self.crypto = crypto; self.storage = storage; self.isCurrent = isCurrent
        self.keyVersion = keyVersion; self.request = request; self.now = now
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
    /// Inject this into NativeVoiceCallOutbox.checkpoint. The lifecycle marker is
    /// an in-process instruction, never transmitted under that private name.
    func persist(scope: NativeVoiceCallScope, callID: String,
                 frame: NativeVoiceCallFrame) async throws -> NativeVoiceCallFrame {
        await acquire(); defer { release() }
        try await check(scope)
        guard frame["call_id"]?.string == callID else { throw NativeVoiceCallError.persistenceFailed }
        let lifecycle = frame["type"]?.string == "native_voice_lifecycle"
        var records = try await storage.load(scope: scope)
        try await check(scope)
        let identifier: String
        var draft: NativeVoiceCallFrame
        if lifecycle {
            guard let action = frame["action"]?.string, ["started", "ended"].contains(action),
                  let createdAt = frame["created_at"]?.number, createdAt > 0,
                  createdAt.rounded(.down) == createdAt,
                  let elapsed = frame["active_elapsed_seconds"]?.number, elapsed >= 0,
                  elapsed.rounded(.down) == elapsed else { throw NativeVoiceCallError.persistenceFailed }
            identifier = (action == "started" ? "00000000" : "ffffffff") + "-voice-call-" + callID + "-" + action
            let content: NativeVoiceCallFrame = ["schema_version": .number(1), "type": .string("voice_call"),
                "action": .string(action), "call_id": .string(callID), "created_at": .number(createdAt),
                "active_elapsed_seconds": .number(elapsed)]
            let ciphertext: String
            if let retained = records[identifier]?.frame["message"]?.object?["encrypted_content"]?.string { ciphertext = retained }
            else { ciphertext = try await crypto.encrypt(NativeVoiceCallWire.encode(content), scope: scope) }
            draft = ["type": .string("chat_system_message_added"), "chat_id": .string(scope.chatID),
                "message": .object(["message_id": .string(identifier), "role": .string("system"),
                    "created_at": .number(createdAt), "encrypted_content": .string(ciphertext)])]
        } else {
            guard frame["type"]?.string == "voice_compression", let payload = frame["payload"]?.object,
                  payload["chat_id"]?.string == scope.chatID,
                  payload["task_id"]?.string != nil, let id = payload["summary_message_id"]?.string,
                  !id.isEmpty, let summary = payload["summary_content"]?.string, !summary.isEmpty,
                  summary.utf16.count <= 48_000,
                  let timestamp = payload["compressed_up_to_timestamp"]?.number,
                  timestamp > 0, timestamp.rounded(.down) == timestamp,
                  payload["compressed_up_to_message_id"]?.string != nil,
                  case .array(let covered)? = payload["covered_message_ids"],
                  covered.allSatisfy({ $0.string != nil }), covered.count <= 10_000,
                  let count = payload["compressed_message_count"]?.number, count > 0,
                  count.rounded(.down) == count else { throw NativeVoiceCallError.persistenceFailed }
            identifier = id
            let ciphertext: String
            if let retained = records[identifier]?.frame["encrypted_summary"]?.string { ciphertext = retained }
            else { ciphertext = try await crypto.encrypt(summary, scope: scope) }
            let version = try await keyVersion(scope)
            draft = ["type": .string("store_chat_compression_checkpoint"), "chat_id": .string(scope.chatID),
                "checkpoint_id": .string(id), "encrypted_summary": .string(ciphertext),
                "compressed_up_to_timestamp": .number(timestamp),
                "compressed_up_to_message_id": payload["compressed_up_to_message_id"]!,
                "covered_message_ids": .array(covered), "compressed_message_count": .number(count),
                "created_at": .number(floor(now().timeIntervalSince1970)),
                "key_version": version.map { NativeVoiceCallJSON.number(Double($0)) } ?? .null]
            if let estimate = payload["summary_token_estimate"] { draft["summary_token_estimate"] = estimate }
        }
        try await check(scope)
        let record: NativeVoiceCallAuxiliaryRecord
        if let existing = records[identifier] {
            // Preserve the original randomized ciphertext for every retry.
            record = existing
            let old = existing.frame
            guard old["type"] == draft["type"], old["chat_id"] == draft["chat_id"]
            else { throw NativeVoiceCallError.persistenceFailed }
            if !lifecycle {
                guard old["compressed_up_to_timestamp"] == draft["compressed_up_to_timestamp"],
                      old["compressed_up_to_message_id"] == draft["compressed_up_to_message_id"],
                      old["compressed_message_count"] == draft["compressed_message_count"],
                      old["covered_message_ids"] == draft["covered_message_ids"],
                      let oldCiphertext = old["encrypted_summary"]?.string,
                      let summary = frame["payload"]?.object?["summary_content"]?.string,
                      try await crypto.decrypt(oldCiphertext, scope: scope) == summary
                else { throw NativeVoiceCallError.persistenceFailed }
            }
        } else {
            record = .init(frame: draft, confirmed: false)
            records[identifier] = record
            try await check(scope)
            try await storage.save(records, scope: scope) // ciphertext before wire
        }
        try await check(scope)
        if !record.confirmed {
            let response = try await request(scope, record.frame,
                lifecycle ? "system_message_confirmed" : "chat_compression_checkpoint_stored")
            try await check(scope)
            guard response["chat_id"]?.string == scope.chatID else { throw NativeVoiceCallError.persistenceFailed }
            if lifecycle {
                guard response["message_id"]?.string == identifier else { throw NativeVoiceCallError.persistenceFailed }
            } else {
                guard let checkpoint = response["checkpoint"]?.object,
                      checkpoint["id"]?.string == identifier,
                      checkpoint["encrypted_summary"] == record.frame["encrypted_summary"],
                      checkpoint["compressed_up_to_timestamp"] == record.frame["compressed_up_to_timestamp"],
                      checkpoint["compressed_up_to_message_id"] == record.frame["compressed_up_to_message_id"],
                      checkpoint["compressed_message_count"] == record.frame["compressed_message_count"]
                else { throw NativeVoiceCallError.persistenceFailed }
            }
            records[identifier]?.confirmed = true
            try await storage.save(records, scope: scope)
            try await check(scope)
        }
        return lifecycle ? [:] : ["type": .string("voice_compression_confirmed"),
            "call_id": .string(callID), "checkpoint_id": .string(identifier)]
    }
}
