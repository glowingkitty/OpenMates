// Coordinates the Apple client's saved-chat completion recovery protocol.
// Recovery plaintext exists only transiently in memory and is re-encrypted with
// the normal chat key before crossing the WebSocket persistence boundary.
// Injectable closures keep protocol behavior deterministic in unit tests.
// No UI state or user-visible strings are owned by this service.

import CryptoKit
import Foundation

@MainActor
final class ChatCompletionRecoveryCoordinator {
    static let protocolVersion = 1

    struct AvailableJob: Equatable {
        let jobId: String
        let chatId: String
        let turnId: String
        let assistantMessageId: String
        let chatKeyVersion: UInt32
    }

    private let transport: ChatWebSocketTransport
    private let authenticatedOwnerId: () async -> String?
    private let isDeviceEligible: () async -> Bool
    private let chatKey: (String) -> SymmetricKey?
    private let isChatKeyReady: () -> Bool
    private let chatVersion: (String) -> Int?
    private let containsMessage: (String, String) -> Bool
    private let persistMessage: (Message) -> Void
    private let applyCommittedMessagesVersion: (String, Int) -> Void
    private var jobsInProgress = Set<String>()
    private var persistedJobIds = Set<String>()
    private var pendingJobs: [String: AvailableJob] = [:]
    private var pendingLocalMessages: [String: Message] = [:]
    private var terminalJobIdsByMessageId: [String: String] = [:]
    private var pendingTerminalJobs: [String: String] = [:]
    private var isInitialSyncReady = false

    init(
        transport: ChatWebSocketTransport,
        authenticatedOwnerId: @escaping () async -> String?,
        isDeviceEligible: @escaping () async -> Bool,
        chatKey: @escaping (String) -> SymmetricKey?,
        isChatKeyReady: @escaping () -> Bool,
        chatVersion: @escaping (String) -> Int?,
        containsMessage: @escaping (String, String) -> Bool,
        persistMessage: @escaping (Message) -> Void,
        applyCommittedMessagesVersion: @escaping (String, Int) -> Void
    ) {
        self.transport = transport
        self.authenticatedOwnerId = authenticatedOwnerId
        self.isDeviceEligible = isDeviceEligible
        self.chatKey = chatKey
        self.isChatKeyReady = isChatKeyReady
        self.chatVersion = chatVersion
        self.containsMessage = containsMessage
        self.persistMessage = persistMessage
        self.applyCommittedMessagesVersion = applyCommittedMessagesVersion
    }

    convenience init(transport: ChatWebSocketTransport, chatStore: ChatStore) {
        self.init(
            transport: transport,
            authenticatedOwnerId: { await AuthManager.currentUserId() },
            isDeviceEligible: { await AuthManager.isRecoveryEligibleDevice() },
            chatKey: { ChatKeyManager.shared.key(for: $0) },
            isChatKeyReady: { ChatKeyManager.shared.isReady },
            chatVersion: { chatStore.chat(for: $0)?.messagesV },
            containsMessage: { chatId, messageId in
                chatStore.messages(for: chatId).contains { $0.id == messageId }
            },
            persistMessage: { message in chatStore.appendMessage(message, to: message.chatId) },
            applyCommittedMessagesVersion: { chatId, version in
                chatStore.advanceMessagesVersion(chatId: chatId, to: version)
            }
        )
    }

    func handleAvailableJobs(_ payload: [String: Any]) async {
        guard await isDeviceEligible(), await authenticatedOwnerId() != nil,
              let jobs = payload["jobs"] as? [[String: Any]] else { return }
        for rawJob in jobs {
            guard let job = Self.availableJob(from: rawJob),
                  !IncognitoChatSession.isIncognitoChatId(job.chatId),
                  !containsMessage(job.chatId, job.assistantMessageId),
                  !persistedJobIds.contains(job.jobId) else { continue }
            pendingJobs[job.jobId] = job
        }
        await flushPendingJobs()
    }

    func markInitialSyncReady() async {
        isInitialSyncReady = true
        await flushPendingJobs()
    }

    func handleChatKeyAvailabilityChanged() async {
        await flushPendingJobs()
    }

    func handleTransportDisconnected() {
        // A socket close invalidates local waits. Keep jobs queued so the next
        // authenticated connection can claim them again with a fresh lease.
        jobsInProgress.removeAll()
    }

    func handleTransportConnected() async {
        await flushPendingJobs()
    }

    func reset() {
        jobsInProgress.removeAll()
        persistedJobIds.removeAll()
        pendingJobs.removeAll()
        pendingLocalMessages.removeAll()
        terminalJobIdsByMessageId.removeAll()
        pendingTerminalJobs.removeAll()
        isInitialSyncReady = false
    }

    func handleTerminalStream(_ payload: [String: Any]) {
        guard payload["is_final_chunk"] as? Bool == true,
              Self.intValue(payload["recovery_protocol_version"]) == Self.protocolVersion,
              let jobId = payload["recovery_job_id"] as? String, !jobId.isEmpty,
              let chatId = payload["chat_id"] as? String, !chatId.isEmpty,
              let messageId = payload["message_id"] as? String, !messageId.isEmpty else { return }
        terminalJobIdsByMessageId[messageId] = jobId
        pendingTerminalJobs[jobId] = chatId
        Task { await flushPendingJobs() }
    }

    func ownsRecoveryPersistence(messageId: String) -> Bool {
        terminalJobIdsByMessageId[messageId] != nil
    }

    private func flushPendingJobs() async {
        guard isInitialSyncReady,
              isChatKeyReady(),
              await isDeviceEligible(),
              await authenticatedOwnerId() != nil else { return }

        for job in Array(pendingJobs.values) where chatKey(job.chatId) != nil {
            await recoverPending(job) { try await self.recover($0) }
        }
        for (jobId, chatId) in Array(pendingTerminalJobs) where chatKey(chatId) != nil {
            await recoverPendingTerminalJob(jobId)
        }
    }

    private func recoverPending(
        _ job: AvailableJob,
        operation: (AvailableJob) async throws -> Void
    ) async {
        guard jobsInProgress.insert(job.jobId).inserted else { return }
        defer { jobsInProgress.remove(job.jobId) }
        do {
            try await operation(job)
            pendingJobs.removeValue(forKey: job.jobId)
        } catch {
            NativeDiagnostics.warning("completion_recovery_failed job=\(job.jobId.prefix(8))")
        }
    }

    private func recoverPendingTerminalJob(_ jobId: String) async {
        guard jobsInProgress.insert(jobId).inserted else { return }
        defer { jobsInProgress.remove(jobId) }
        do {
            try await recoverOriginJob(jobId)
            pendingTerminalJobs.removeValue(forKey: jobId)
            pendingJobs.removeValue(forKey: jobId)
        } catch {
            NativeDiagnostics.warning("completion_recovery_failed job=\(jobId.prefix(8))")
        }
    }

    private func recover(_ job: AvailableJob) async throws {
        let claim = try await claim(jobId: job.jobId)
        try await recover(job, claim: claim)
    }

    private func recoverOriginJob(_ jobId: String) async throws {
        let claim = try await claim(jobId: jobId)
        guard let job = Self.availableJob(from: claim) else { throw RecoveryError.invalidClaim }
        try await recover(job, claim: claim)
    }

    private func claim(jobId: String) async throws -> [String: Any] {
        let claimWait = Task { @MainActor in
            try await transport.waitForMessage("recovery_job_claimed") {
                $0["job_id"] as? String == jobId
            }
        }
        try await transport.send(WSOutboundMessage(type: "recovery_job_claim", payload: [
            "protocol_version": Self.protocolVersion,
            "job_id": jobId,
        ]))
        return try await claimWait.value
    }

    private func recover(_ job: AvailableJob, claim: [String: Any]) async throws {
        if claim["state"] as? String == "TERMINAL" {
            try reconcileTerminal(job, acknowledgement: claim)
            return
        }
        guard let ownerId = await authenticatedOwnerId(), await isDeviceEligible(),
              let key = chatKey(job.chatId) else { throw RecoveryError.notReady }
        let leaseToken = try Self.requiredString("lease_token", in: claim)
        let leaseGeneration = try Self.requiredPositiveInt("lease_generation", in: claim)
        guard claim["state"] as? String == "LEASED",
              claim["chat_id"] as? String == job.chatId,
              claim["turn_id"] as? String == job.turnId,
              claim["assistant_message_id"] as? String == job.assistantMessageId,
              Self.intValue(claim["chat_key_version"]) == Int(job.chatKeyVersion),
              let sealedPayload = claim["sealed_payload"] as? String else {
            throw RecoveryError.invalidClaim
        }

        let recovered = try await openPayload(
            sealedPayload,
            job: job,
            ownerId: ownerId,
            chatKey: key
        )
        let encryptedContent = try await CryptoManager.shared.encryptContent(recovered.content, key: key)
        let encryptedSenderName = try await CryptoManager.shared.encryptContent("Assistant", key: key)
        let encryptedCategory: String?
        if let category = recovered.category {
            encryptedCategory = try await CryptoManager.shared.encryptContent(category, key: key)
        } else {
            encryptedCategory = nil
        }
        let encryptedModelName: String?
        if let modelName = recovered.modelName {
            encryptedModelName = try await CryptoManager.shared.encryptContent(modelName, key: key)
        } else {
            encryptedModelName = nil
        }
        let now = Int(Date().timeIntervalSince1970)
        var encryptedMessage: [String: Any] = [
            "client_message_id": job.assistantMessageId,
            "chat_id": job.chatId,
            "role": "assistant",
            "encrypted_content": encryptedContent,
            "encrypted_sender_name": encryptedSenderName,
            "created_at": now,
            "updated_at": now,
        ]
        if let encryptedCategory { encryptedMessage["encrypted_category"] = encryptedCategory }
        if let encryptedModelName { encryptedMessage["encrypted_model_name"] = encryptedModelName }

        let localMessage = Message(
            id: job.assistantMessageId,
            chatId: job.chatId,
            role: .assistant,
            content: recovered.content,
            encryptedContent: encryptedContent,
            createdAt: ChatSendPipeline.isoString(from: Date(timeIntervalSince1970: TimeInterval(now))),
            updatedAt: nil,
            appId: recovered.category,
            isStreaming: false,
            embedRefs: nil,
            modelName: recovered.modelName
        )
        pendingLocalMessages[job.jobId] = localMessage
        let persistedWait = Task { @MainActor in
            try await transport.waitForMessage("recovery_job_persisted") {
                $0["job_id"] as? String == job.jobId
            }
        }
        try await transport.send(WSOutboundMessage(type: "recovery_job_persist", payload: [
            "protocol_version": Self.protocolVersion,
            "job_id": job.jobId,
            "lease_token": leaseToken,
            "lease_generation": leaseGeneration,
            "expected_messages_v": chatVersion(job.chatId) ?? 0,
            "encrypted_assistant_message": encryptedMessage,
        ]))
        let acknowledgement = try await persistedWait.value
        guard Self.intValue(acknowledgement["lease_generation"]) == leaseGeneration else {
            throw RecoveryError.invalidAcknowledgement
        }
        try reconcileTerminal(job, acknowledgement: acknowledgement)
    }

    private func reconcileTerminal(_ job: AvailableJob, acknowledgement: [String: Any]) throws {
        guard acknowledgement["state"] as? String == "TERMINAL",
              acknowledgement["job_id"] as? String == job.jobId,
              acknowledgement["chat_id"] as? String == job.chatId || acknowledgement["chat_id"] == nil,
              acknowledgement["assistant_message_id"] as? String == job.assistantMessageId || acknowledgement["assistant_message_id"] == nil,
              let committedMessagesVersion = Self.intValue(acknowledgement["committed_messages_v"]),
              committedMessagesVersion >= 0 else {
            throw RecoveryError.invalidAcknowledgement
        }
        guard persistedJobIds.insert(job.jobId).inserted else { return }
        applyCommittedMessagesVersion(job.chatId, committedMessagesVersion)
        if !containsMessage(job.chatId, job.assistantMessageId), let message = pendingLocalMessages[job.jobId] {
            persistMessage(message)
        }
        pendingLocalMessages.removeValue(forKey: job.jobId)
    }

    private func openPayload(
        _ sealedPayload: String,
        job: AvailableJob,
        ownerId: String,
        chatKey: SymmetricKey
    ) async throws -> RecoveredCompletion {
        let envelopeData = try Self.jsonData(sealedPayload)
        let envelopeObject = try Self.jsonObject(envelopeData)
        guard Set(envelopeObject.keys) == Set(["v", "epk", "nonce", "ciphertext"]) else {
            throw RecoveryError.invalidEnvelope
        }
        let envelope = CryptoManager.RecoveryEnvelope(
            v: try Self.requiredInt("v", in: envelopeObject),
            epk: try Self.requiredString("epk", in: envelopeObject),
            nonce: try Self.requiredString("nonce", in: envelopeObject),
            ciphertext: try Self.requiredString("ciphertext", in: envelopeObject)
        )
        let keyPair = try await CryptoManager.shared.deriveRecoveryKeyPair(
            chatKey: chatKey,
            chatId: job.chatId,
            keyVersion: job.chatKeyVersion
        )
        let plaintext = try await CryptoManager.shared.openRecoveryEnvelope(
            envelope,
            recoveryPrivateKey: keyPair.privateKey,
            ownerId: ownerId,
            chatId: job.chatId,
            turnId: job.turnId,
            jobId: job.jobId,
            assistantMessageId: job.assistantMessageId,
            keyVersion: job.chatKeyVersion
        )
        let value = try Self.jsonObject(plaintext)
        let requiredFields: Set<String> = ["job_id", "chat_id", "turn_id", "assistant_message_id", "key_version", "content"]
        let optionalFields: Set<String> = ["category", "model_name"]
        let plaintextFields = Set(value.keys)
        guard requiredFields.isSubset(of: plaintextFields),
              plaintextFields.isSubset(of: requiredFields.union(optionalFields)),
              value["job_id"] as? String == job.jobId,
              value["chat_id"] as? String == job.chatId,
              value["turn_id"] as? String == job.turnId,
              value["assistant_message_id"] as? String == job.assistantMessageId,
              Self.intValue(value["key_version"]) == Int(job.chatKeyVersion),
              let content = value["content"] as? String,
              value["category"] == nil || value["category"] is NSNull || value["category"] is String,
              value["model_name"] == nil || value["model_name"] is NSNull || value["model_name"] is String else {
            throw RecoveryError.invalidPlaintext
        }
        return RecoveredCompletion(
            content: content,
            category: value["category"] as? String,
            modelName: value["model_name"] as? String
        )
    }

    static func availableJob(from value: [String: Any]) -> AvailableJob? {
        guard let jobId = value["job_id"] as? String,
              let chatId = value["chat_id"] as? String,
              let turnId = value["turn_id"] as? String,
              let assistantMessageId = value["assistant_message_id"] as? String,
              let version = intValue(value["chat_key_version"]), version >= 1 else { return nil }
        return AvailableJob(
            jobId: jobId,
            chatId: chatId,
            turnId: turnId,
            assistantMessageId: assistantMessageId,
            chatKeyVersion: UInt32(version)
        )
    }

    private static func jsonData(_ value: String) throws -> Data {
        guard let data = value.data(using: .utf8) else { throw RecoveryError.invalidJSON }
        return data
    }

    private static func jsonObject(_ data: Data) throws -> [String: Any] {
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw RecoveryError.invalidJSON
        }
        return value
    }

    private static func requiredString(_ key: String, in value: [String: Any]) throws -> String {
        guard let result = value[key] as? String, !result.isEmpty else { throw RecoveryError.invalidClaim }
        return result
    }

    private static func requiredInt(_ key: String, in value: [String: Any]) throws -> Int {
        guard let result = intValue(value[key]) else { throw RecoveryError.invalidClaim }
        return result
    }

    private static func requiredPositiveInt(_ key: String, in value: [String: Any]) throws -> Int {
        let value = try requiredInt(key, in: value)
        guard value > 0 else { throw RecoveryError.invalidClaim }
        return value
    }

    private static func intValue(_ value: Any?) -> Int? {
        if let value = value as? Int { return value }
        if let value = value as? NSNumber { return value.intValue }
        return nil
    }
}

private struct RecoveredCompletion {
    let content: String
    let category: String?
    let modelName: String?
}

private enum RecoveryError: Error {
    case invalidAcknowledgement
    case invalidClaim
    case invalidEnvelope
    case invalidJSON
    case invalidPlaintext
    case notReady
}
