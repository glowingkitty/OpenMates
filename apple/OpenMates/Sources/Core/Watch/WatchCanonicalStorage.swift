// Canonical Watch user-turn storage and leased assistant completion recovery.
// Plaintext exists only in transient request/encryption closures.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.new-text-reply, apple-watch.chats.audio-reply
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.completion.recovery-takeover

import CryptoKit
import Foundation

struct WatchRecoveryJob: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let chatId: String
    let messageId: String
    let turnId: String?
    let keyVersion: UInt32
}

struct WatchPendingCompletion: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let chatId: String
    let eventType: String
    let encryptedPayload: Data
}

struct WatchRecoveredCompletion {
    let content: String
    let category: String?
    let modelName: String?
}

@MainActor
enum WatchCanonicalStorage {
    typealias Request = @MainActor (String, [String: Any], Set<String>, @escaping @MainActor ([String: Any]) -> Bool) async throws -> [String: Any]

    static func sendTurn(_ pending: WatchPendingTextSend, request: Request,
                         encryptMetadata: @MainActor (String) async throws -> String,
                         validate: @MainActor () throws -> Void) async throws {
        let preflight = try object(pending.preflightJSON)
        let inference = try object(pending.inferenceJSON)
        guard preflight["turn_id"] as? String == pending.id,
              preflight["chat_id"] as? String == pending.chatId,
              let prepared = preflight["inference_request"] as? [String: Any],
              NSDictionary(dictionary: prepared).isEqual(to: inference) else { throw WatchChatRuntimeError.invalidPendingTurn }
        try validate()
        let ack = try await request("chat_turn_preflight", preflight, ["chat_turn_preflight_ack"],
                                    { $0["turn_id"] as? String == pending.id })
        try validate()
        guard let state = ack["state"] as? String else {
            throw WatchTurnAdmissionDiagnostic.invalidAcknowledgement(stage: .preflight, issue: .missingState)
        }
        guard let preflightID = ack["preflight_id"] as? String, !preflightID.isEmpty else {
            throw WatchTurnAdmissionDiagnostic.invalidAcknowledgement(stage: .preflight, issue: .missingPreflightID)
        }
        if ["ENQUEUED", "RUNNING", "TERMINAL"].contains(state) {
            NativeDiagnostics.event("inference_accepted", category: "watch_chat_socket", flags: ["replayed": true])
            return
        }
        guard state == "PREPARED" || state == "LEGACY" else {
            throw WatchTurnAdmissionDiagnostic.invalidAcknowledgement(stage: .preflight, issue: .unexpectedState)
        }
        var commit = inference
        commit["protocol_version"] = 1
        commit["preflight_id"] = preflightID
        let receipt = try await request("chat_message_added", commit, ["ai_task_initiated"], {
            $0["turn_id"] as? String == pending.id ||
            ($0["chat_id"] as? String == pending.chatId &&
             ($0["user_message_id"] ?? $0["message_id"]) as? String == pending.messageId)
        })
        try validate()
        guard receipt["code"] == nil else {
            throw WatchTurnAdmissionDiagnostic.serverRejection(stage: .commit, code: receipt["code"])
        }
        guard let taskID = (receipt["ai_task_id"] ?? receipt["task_id"]) as? String, !taskID.isEmpty else {
            throw WatchTurnAdmissionDiagnostic.invalidAcknowledgement(stage: .commit, issue: .missingTaskID)
        }
        NativeDiagnostics.event("inference_accepted", category: "watch_chat_socket", flags: ["replayed": false])
        // LEGACY acknowledges admission but has not persisted the encrypted user
        // message. Complete its canonical storage package before retiring the turn.
        if state == "LEGACY" {
            // A replayed legacy admission may not emit typing again. A bounded
            // metadata wait must never prevent storage of the already encrypted user.
            let metadata: [String: Any]
            do {
                metadata = try await request("", [:], ["ai_typing_started"], {
                    $0["chat_id"] as? String == pending.chatId && $0["user_message_id"] as? String == pending.messageId
                })
            } catch {
                try validate()
                metadata = [:]
            }
            try validate()
            guard let encryptedUser = preflight["encrypted_user_message"] as? [String: Any],
                  let encryptedContent = encryptedUser["encrypted_content"] as? String else { throw WatchChatRuntimeError.invalidPendingTurn }
            let timestamp = encryptedUser["created_at"] as? Int ?? Int(Date().timeIntervalSince1970)
            var storage = preflight["encrypted_chat_metadata"] as? [String: Any] ?? [:]
            let category = metadata["category"] as? String ?? "ai"
            storage["encrypted_category"] = try await encryptMetadata(category)
            storage["encrypted_sender_name"] = try await encryptMetadata("user")
            storage.removeValue(forKey: "encrypted_title")
            if let title = metadata["title"] as? String, !title.isEmpty {
                storage["encrypted_title"] = try await encryptMetadata(title)
                storage["encrypted_icon"] = try await encryptMetadata((metadata["icon_names"] as? [String])?.first ?? iconFallback(category))
                storage["encrypted_chat_category"] = try await encryptMetadata(category)
            }
            try validate()
            storage["chat_id"] = pending.chatId
            storage["message_id"] = pending.messageId
            storage["encrypted_content"] = encryptedContent
            storage["encrypted_chat_key"] = pending.encryptedChatKey
            storage["created_at"] = timestamp
            storage["task_id"] = taskID
            storage["versions"] = ["messages_v": (preflight["expected_messages_v"] as? Int ?? 0) + 1,
                                    "title_v": storage["encrypted_title"] == nil ? 0 : 1,
                                    "last_edited_overall_timestamp": timestamp]
            let stored = try await request("encrypted_chat_metadata", storage,
                ["encrypted_metadata_stored", "incomplete_chat_metadata", "chat_key_mismatch"], {
                    $0["chat_id"] as? String == pending.chatId && $0["message_id"] as? String == pending.messageId
                })
            try validate()
            guard stored["code"] == nil else {
                throw WatchTurnAdmissionDiagnostic.serverRejection(stage: .legacyStorage, code: stored["code"])
            }
            guard let versions = stored["versions"] as? [String: Any],
                  let version = versions["messages_v"] as? Int, version > 0 else {
                throw WatchTurnAdmissionDiagnostic.invalidAcknowledgement(stage: .legacyStorage, issue: .missingStoredVersion)
            }
        }
    }

    static func validateEmbedStorageAcknowledgement(type: String, payload: [String: Any],
        acknowledgement: [String: Any], requestID: String,
        policy: CanonicalEmbedReceiptPolicy = .requireCanonicalDigest) throws {
        switch type {
        case "store_embed":
            try CanonicalEmbedStorageReceipts.validateHead(payload: payload, receipt: acknowledgement, requestID: requestID, policy: policy)
        case "store_embed_keys":
            try CanonicalEmbedStorageReceipts.validateKeys(payload: payload, receipt: acknowledgement, requestID: requestID, policy: policy)
        default: throw WatchChatRuntimeError.invalidPendingTurn
        }
    }

    static func embedBundle(chatID: String, head: [String: Any], keys: [String: Any]) throws -> WatchPendingCompletion {
        guard let requestID = head["request_id"] as? String, !requestID.isEmpty,
              let keyRequestID = keys["request_id"] as? String, !keyRequestID.isEmpty,
              let embedID = head["embed_id"] as? String, !embedID.isEmpty,
              head["encrypted_content"] as? String != nil,
              let wrappers = keys["keys"] as? [[String: Any]], !wrappers.isEmpty else { throw WatchChatRuntimeError.invalidPendingTurn }
        let data = try JSONSerialization.data(withJSONObject: ["head": head, "keys": keys], options: [.sortedKeys])
        return WatchPendingCompletion(id: requestID, chatId: chatID, eventType: "store_embed_bundle", encryptedPayload: data)
    }

    /// One retained ciphertext bundle is the retry authority, including both
    /// original request IDs. No wrapper can run before its exact head receipt.
    static func persistEmbedBundle(_ entry: WatchPendingCompletion, policy: CanonicalEmbedReceiptPolicy,
                                   request: Request, validate: @MainActor () throws -> Void) async throws {
        let bundle = try object(entry.encryptedPayload)
        guard let head = bundle["head"] as? [String: Any], let keys = bundle["keys"] as? [String: Any],
              let headID = head["request_id"] as? String, headID == entry.id,
              let embedID = head["embed_id"] as? String,
              let keyID = keys["request_id"] as? String,
              let wrappers = keys["keys"] as? [[String: Any]], !wrappers.isEmpty else {
            throw WatchChatRuntimeError.invalidPendingTurn
        }
        try validate()
        let headReceipt = try await request("store_embed", head, ["store_embed_confirmed"], {
            $0["request_id"] as? String == headID && ($0["embed_id"] as? String == embedID || $0["code"] != nil)
        })
        try validate()
        try validateEmbedStorageAcknowledgement(type: "store_embed", payload: head,
            acknowledgement: headReceipt, requestID: headID, policy: policy)
        let keyReceipt = try await request("store_embed_keys", keys, ["store_embed_keys_confirmed"], { $0["request_id"] as? String == keyID })
        try validate()
        try validateEmbedStorageAcknowledgement(type: "store_embed_keys", payload: keys,
            acknowledgement: keyReceipt, requestID: keyID, policy: policy)
    }

    /// Upgrade old pending keys-first entries without regenerating ciphertext.
    /// An orphan wrapper is retained and blocked until its head is available.
    static func migratedEmbedBundles(_ entries: [WatchPendingCompletion]) throws -> [WatchPendingCompletion] {
        var consumed = Set<String>()
        var bundles: [String: WatchPendingCompletion] = [:]
        for headEntry in entries where headEntry.eventType == "store_embed" {
            guard let head = try? object(headEntry.encryptedPayload),
                  let embedID = head["embed_id"] as? String else { continue }
            let hash = CanonicalEmbedStorageReceipts.digest(embedID)
            if let keyEntry = entries.first(where: { candidate in
                guard candidate.eventType == "store_embed_keys", candidate.chatId == headEntry.chatId,
                      !consumed.contains(candidate.id),
                      let payload = try? object(candidate.encryptedPayload),
                      let keys = payload["keys"] as? [[String: Any]] else { return false }
                return !keys.isEmpty && keys.allSatisfy { $0["hashed_embed_id"] as? String == hash }
            }) {
                guard let keys = try? object(keyEntry.encryptedPayload),
                      let bundle = try? embedBundle(chatID: headEntry.chatId, head: head, keys: keys) else { continue }
                bundles[headEntry.id] = bundle
                consumed.insert(keyEntry.id)
            }
        }
        return entries.compactMap { entry in consumed.contains(entry.id) ? nil : bundles[entry.id] ?? entry }
    }

    /// Retain ambiguous legacy embed entries without stalling encrypted message
    /// or metadata completions. Embed writes for that chat wait so a newer head
    /// cannot race an unresolved older ciphertext package.
    static func completionDrainCandidates(_ entries: [WatchPendingCompletion]) -> [WatchPendingCompletion] {
        let blockedChats = Set(entries.filter {
            $0.eventType == "store_embed" || $0.eventType == "store_embed_keys"
        }.map(\.chatId))
        return entries.filter {
            $0.eventType != "store_embed" && $0.eventType != "store_embed_keys"
                && ($0.eventType != "store_embed_bundle" || !blockedChats.contains($0.chatId))
        }
    }

    static func iconFallback(_ category: String) -> String {
        switch category {
        case "web": "search"
        case "travel": "plane"
        case "videos": "video"
        case "nutrition": "utensils"
        case "code": "code"
        default: "sparkles"
        }
    }

    struct RecoveryResult {
        let message: WatchChatMessage?
        let version: Int
        let requiresHydration: Bool
    }

    static func recover(_ job: WatchRecoveryJob, chat: WatchChatSummary, ownerID: String,
                        request: Request,
                        open: @MainActor (String, WatchRecoveryJob, String) async throws -> WatchRecoveredCompletion,
                        encrypt: @MainActor (String) async throws -> String,
                        validate: @MainActor () throws -> Void) async throws -> RecoveryResult {
        try validate()
        let claim = try await request("recovery_job_claim", ["protocol_version": 1, "job_id": job.id],
                                      ["recovery_job_claimed"], { $0["job_id"] as? String == job.id })
        try validate()
        guard claim["code"] == nil, claim["job_id"] as? String == job.id else { throw WatchChatRuntimeError.preflightRejected }
        if claim["state"] as? String == "TERMINAL" { return try terminal(claim, job: job, message: nil) }
        guard claim["state"] as? String == "LEASED", claim["chat_id"] as? String == job.chatId,
              claim["assistant_message_id"] as? String == job.messageId,
              let turnID = claim["turn_id"] as? String, !turnID.isEmpty,
              job.turnId == nil || job.turnId == turnID,
              (claim["chat_key_version"] as? Int) == Int(job.keyVersion),
              let token = claim["lease_token"] as? String, !token.isEmpty,
              let lease = claim["lease_generation"] as? Int, lease > 0,
              let sealed = claim["sealed_payload"] as? String else { throw WatchChatRuntimeError.preflightRejected }
        let boundJob = WatchRecoveryJob(id: job.id, chatId: job.chatId, messageId: job.messageId,
                                       turnId: turnID, keyVersion: job.keyVersion)
        let recovered = try await open(sealed, boundJob, ownerID)
        try validate()
        let ciphertext = try await encrypt(recovered.content)
        let sender = try await encrypt("Assistant")
        let timestamp = Int(Date().timeIntervalSince1970)
        var message: [String: Any] = ["client_message_id": job.messageId, "chat_id": job.chatId,
            "role": "assistant", "encrypted_content": ciphertext, "encrypted_sender_name": sender,
            "created_at": timestamp, "updated_at": timestamp]
        if let category = recovered.category { message["encrypted_category"] = try await encrypt(category) }
        if let model = recovered.modelName { message["encrypted_model_name"] = try await encrypt(model) }
        try validate()
        var acknowledgement = try await request("recovery_job_persist", ["protocol_version": 1, "job_id": job.id,
            "lease_token": token, "lease_generation": lease, "expected_messages_v": chat.messagesV,
            "encrypted_assistant_message": message], ["recovery_job_persisted"], { $0["job_id"] as? String == job.id })
        try validate()
        if let returnedLease = acknowledgement["lease_generation"] as? Int, returnedLease != lease { throw WatchChatRuntimeError.preflightRejected }
        let idempotent = acknowledgement["idempotent"] as? Bool == true
        if acknowledgement["state"] as? String == "TERMINAL", acknowledgement["committed_messages_v"] == nil, idempotent {
            acknowledgement = try await request("recovery_job_claim", ["protocol_version": 1, "job_id": job.id],
                ["recovery_job_claimed"], { $0["job_id"] as? String == job.id })
            try validate()
        }
        let local = WatchChatMessage(id: job.messageId, chatId: job.chatId, role: .assistant,
            content: recovered.content, encryptedContent: ciphertext,
            createdAt: ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(timestamp))), isPending: false)
        let result = try terminal(acknowledgement, job: job, message: local)
        return RecoveryResult(message: result.message, version: result.version,
                              requiresHydration: idempotent || result.requiresHydration)
    }

    private static func terminal(_ payload: [String: Any], job: WatchRecoveryJob, message: WatchChatMessage?) throws -> RecoveryResult {
        guard payload["code"] == nil, payload["state"] as? String == "TERMINAL", payload["job_id"] as? String == job.id,
              payload["chat_id"] == nil || payload["chat_id"] as? String == job.chatId,
              payload["assistant_message_id"] == nil || payload["assistant_message_id"] as? String == job.messageId,
              let version = payload["committed_messages_v"] as? Int, version >= 0 else { throw WatchChatRuntimeError.preflightRejected }
        return RecoveryResult(message: message, version: version, requiresHydration: message == nil)
    }

    static func openRecovery(_ sealed: String, job: WatchRecoveryJob, ownerID: String, key: SymmetricKey) async throws -> WatchRecoveredCompletion {
        guard let turnID = job.turnId else { throw WatchChatRuntimeError.invalidPendingTurn }
        let raw = try object(Data(sealed.utf8))
        guard Set(raw.keys) == ["v", "epk", "nonce", "ciphertext"], let version = raw["v"] as? Int,
              let epk = raw["epk"] as? String, let nonce = raw["nonce"] as? String,
              let ciphertext = raw["ciphertext"] as? String else { throw WatchChatRuntimeError.invalidPendingTurn }
        let pair = try await CryptoManager.shared.deriveRecoveryKeyPair(chatKey: key, chatId: job.chatId, keyVersion: job.keyVersion)
        let plaintext = try await CryptoManager.shared.openRecoveryEnvelope(.init(v: version, epk: epk, nonce: nonce, ciphertext: ciphertext),
            recoveryPrivateKey: pair.privateKey, ownerId: ownerID, chatId: job.chatId, turnId: turnID,
            jobId: job.id, assistantMessageId: job.messageId, keyVersion: job.keyVersion)
        let value = try object(plaintext)
        let required: Set<String> = ["job_id", "chat_id", "turn_id", "assistant_message_id", "key_version", "content"]
        guard required.isSubset(of: Set(value.keys)), Set(value.keys).isSubset(of: required.union(["category", "model_name"])),
              value["job_id"] as? String == job.id, value["chat_id"] as? String == job.chatId,
              value["turn_id"] as? String == turnID, value["assistant_message_id"] as? String == job.messageId,
              value["key_version"] as? Int == Int(job.keyVersion), let content = value["content"] as? String,
              value["category"] == nil || value["category"] is NSNull || value["category"] is String,
              value["model_name"] == nil || value["model_name"] is NSNull || value["model_name"] is String else { throw WatchChatRuntimeError.invalidPendingTurn }
        return WatchRecoveredCompletion(content: content, category: value["category"] as? String, modelName: value["model_name"] as? String)
    }

    static func object(_ data: Data) throws -> [String: Any] {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw WatchChatRuntimeError.invalidPendingTurn }
        return object
    }
}
