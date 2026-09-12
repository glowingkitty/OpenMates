// Coordinates the Apple client's saved-chat completion recovery protocol.
// Sealed recovery content is re-encrypted with the normal chat key before
// crossing the WebSocket persistence boundary; queued metadata has no content.
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

    typealias RetryScheduler = (TimeInterval, @escaping @MainActor () async -> Void) -> (() -> Void)
    private struct AttemptContext {
        let ownerId: String
        let generation: Int
    }
    // Retry beyond the server's 60-second lease without spinning or depending
    // on a new broadcast. A reconnect starts a fresh bounded retry window.
    static let retryDelays: [TimeInterval] = [1, 3, 10, 20, 30, 60]
    private let currentOwnerSnapshot: () -> String?
    private let recoveryQueue: (String) -> PendingAssistantResponseQueue?
    private let schedule: RetryScheduler
    private let now: () -> Date
    private var activeOwnerId: String?
    private var generation = 0
    private var isTransportConnected = true
    private var scheduledRetries: [String: () -> Void] = [:]
    private var retryAttempts: [String: Int] = [:]
    private var versionRefreshJobs = Set<String>()
    private let transport: ChatWebSocketTransport
    private let authenticatedOwnerId: () async -> String?
    private let isDeviceEligible: () async -> Bool
    private let chatKey: (String) -> SymmetricKey?
    private let isChatKeyReady: () -> Bool
    private let chatVersion: (String) -> Int?
    // Streamed plaintext can already be in the chat store or on disk while the
    // terminal write is still awaiting its acknowledgement. It must not suppress
    // a cold-launch recovery attempt.
    private let containsPersistedMessage: (String, String) -> Bool
    private let persistMessage: (Message) -> Void
    private let persistSnapshot: (String, [Message]) -> Void
    private let applyCommittedMessagesVersion: (String, Int) -> Void
    private var jobsInProgress = Set<String>()
    private var persistedJobIds = Set<String>()
    private var pendingJobs: [String: AvailableJob] = [:]
    private var pendingLocalMessages: [String: Message] = [:]
    private var pendingStreamMessages: [String: Message] = [:]
    private var terminalJobIdsByMessageId: [String: String] = [:]
    private var pendingTerminalJobs: [String: PendingAssistantResponseQueue.Entry] = [:]
    private var isInitialSyncReady = false

    init(
        transport: ChatWebSocketTransport,
        authenticatedOwnerId: @escaping () async -> String?,
        isDeviceEligible: @escaping () async -> Bool,
        chatKey: @escaping (String) -> SymmetricKey?,
        isChatKeyReady: @escaping () -> Bool,
        chatVersion: @escaping (String) -> Int?,
        containsPersistedMessage: @escaping (String, String) -> Bool,
        persistMessage: @escaping (Message) -> Void,
        applyCommittedMessagesVersion: @escaping (String, Int) -> Void,
        currentOwnerSnapshot: @escaping () -> String? = { nil },
        recoveryQueue: @escaping (String) -> PendingAssistantResponseQueue? = { _ in nil },
        now: @escaping () -> Date = Date.init,
        scheduleRetry: RetryScheduler? = nil,
        persistSnapshot: ((String, [Message]) -> Void)? = nil
    ) {
        self.currentOwnerSnapshot = currentOwnerSnapshot
        self.recoveryQueue = recoveryQueue
        self.now = now
        self.schedule = scheduleRetry ?? Self.scheduleRetryTask
        self.transport = transport
        self.authenticatedOwnerId = authenticatedOwnerId
        self.isDeviceEligible = isDeviceEligible
        self.chatKey = chatKey
        self.isChatKeyReady = isChatKeyReady
        self.chatVersion = chatVersion
        self.containsPersistedMessage = containsPersistedMessage
        self.persistMessage = persistMessage
        self.persistSnapshot = persistSnapshot ?? { _, messages in messages.forEach(persistMessage) }
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
            containsPersistedMessage: { chatId, messageId in
                chatStore.messages(for: chatId).contains {
                    $0.id == messageId && !($0.encryptedContent?.isEmpty ?? true)
                }
            },
            persistMessage: { message in
                let existing = chatStore.messages(for: message.chatId).first { $0.id == message.id }
                chatStore.appendMessage(Self.mergingRecoveredMessage(message, preserving: existing), to: message.chatId)
            },
            applyCommittedMessagesVersion: { chatId, version in
                chatStore.advanceMessagesVersion(chatId: chatId, to: version)
            },
            currentOwnerSnapshot: {
                guard let owner = AuthManager.notificationAccountId,
                      OfflineStore.shared.activeScopeId == OfflineStore.scopeId(
                        userId: owner, apiBaseURL: ServerConfiguration.current.apiBaseURL) else { return nil }
                return owner
            },
            recoveryQueue: {
                PendingAssistantResponseQueue.recovery(ownerId: $0, apiBaseURL: ServerConfiguration.current.apiBaseURL)
            },
            persistSnapshot: { chatId, messages in
                let existing = Dictionary(uniqueKeysWithValues: chatStore.messages(for: chatId).map { ($0.id, $0) })
                let merged = messages.map { Self.mergingRecoveredMessage($0, preserving: existing[$0.id]) }
                chatStore.applySyncedContent(messagesByChat: [chatId: merged], embedsByChat: [:])
            }
        )
        chatStore.setPendingAssistantRecoveryLookup { [weak self] chatId in
            self?.pendingAssistantMessageIds(in: chatId) ?? []
        }
    }

    /// Read before initial sync can replace a cached transcript. The active
    /// offline scope validates the synchronous owner in the production closure.
    func pendingAssistantMessageIds(in chatId: String) -> Set<String> {
        guard let owner = currentOwnerSnapshot() else { return [] }
        bindOwner(owner)
        restorePendingJobs(ownerId: owner)
        return Set(pendingTerminalJobs.values.filter {
            $0.chatId == chatId && !persistedJobIds.contains($0.recoveryJobId ?? "")
        }.map(\.messageId))
    }

    private static func scheduleRetryTask(
        after delay: TimeInterval, operation: @escaping @MainActor () async -> Void
    ) -> () -> Void {
        let task = Task { @MainActor in
            do { try await Task.sleep(for: .seconds(delay)) } catch { return }
            guard !Task.isCancelled else { return }
            await operation()
        }
        return { task.cancel() }
    }

    private func bindOwner(_ ownerId: String) {
        if let activeOwnerId, activeOwnerId != ownerId { reset() }
        activeOwnerId = ownerId
    }

    private func restorePendingJobs(ownerId: String) {
        guard let queue = recoveryQueue(ownerId) else { return }
        let entries = queue.all()
        for entry in entries {
            guard let jobId = entry.recoveryJobId, !persistedJobIds.contains(jobId),
                  !IncognitoChatSession.isIncognitoChatId(entry.chatId) else { continue }
            pendingTerminalJobs[jobId] = entry
            terminalJobIdsByMessageId[entry.messageId] = jobId
        }
        prunePendingJobs()
    }

    private func prunePendingJobs() {
        let ordered = pendingTerminalJobs.sorted { ($0.value.queuedAt ?? .distantPast) < ($1.value.queuedAt ?? .distantPast) }
        let overflow = max(0, ordered.count - PendingAssistantResponseQueue.recoveryCapacity)
        for (index, pair) in ordered.enumerated() {
            let age = now().timeIntervalSince(pair.value.queuedAt ?? now())
            guard index < overflow || age >= PendingAssistantResponseQueue.recoveryLifetime || age < 0 else { continue }
            NativeDiagnostics.warning("completion_recovery_metadata_retired reason=\(index < overflow ? "capacity" : "expired") job=\(pair.key.prefix(8))")
            pendingTerminalJobs.removeValue(forKey: pair.key)
            pendingJobs.removeValue(forKey: pair.key)
            pendingLocalMessages.removeValue(forKey: pair.key)
            pendingStreamMessages.removeValue(forKey: pair.key)
            terminalJobIdsByMessageId.removeValue(forKey: pair.value.messageId)
            scheduledRetries.removeValue(forKey: pair.key)?()
        }
    }

    private func context() async throws -> AttemptContext {
        let expectedGeneration = generation
        guard await isDeviceEligible(), let owner = await authenticatedOwnerId(),
              generation == expectedGeneration, isTransportConnected else { throw RecoveryError.notReady }
        bindOwner(owner)
        restorePendingJobs(ownerId: owner)
        return AttemptContext(ownerId: owner, generation: generation)
    }

    private func validate(_ context: AttemptContext) async throws {
        guard generation == context.generation, activeOwnerId == context.ownerId,
              isTransportConnected, !Task.isCancelled,
              await isDeviceEligible(), await authenticatedOwnerId() == context.ownerId,
              generation == context.generation else { throw RecoveryError.staleContext }
    }

    private func remember(_ entry: PendingAssistantResponseQueue.Entry, ownerId: String) {
        guard let jobId = entry.recoveryJobId else { return }
        pendingTerminalJobs[jobId] = entry
        terminalJobIdsByMessageId[entry.messageId] = jobId
        recoveryQueue(ownerId)?.addRecovery(jobId: jobId, messageId: entry.messageId, chatId: entry.chatId)
        prunePendingJobs()
    }

    func handleAvailableJobs(_ payload: [String: Any]) async {
        guard let attempt = try? await context(),
              let jobs = payload["jobs"] as? [[String: Any]] else { return }
        for rawJob in jobs {
            guard let job = Self.availableJob(from: rawJob),
                  !IncognitoChatSession.isIncognitoChatId(job.chatId),
                  !persistedJobIds.contains(job.jobId),
                  pendingTerminalJobs[job.jobId] != nil || !containsPersistedMessage(job.chatId, job.assistantMessageId) else { continue }
            pendingJobs[job.jobId] = job
            remember(.init(messageId: job.assistantMessageId, chatId: job.chatId,
                           recoveryJobId: job.jobId, queuedAt: now()), ownerId: attempt.ownerId)
        }
        await flushPendingJobs()
    }

    func markInitialSyncReady() async {
        // Bind the owner before setting readiness, so an account change cannot
        // carry the old account's initial-sync signal into this one.
        guard (try? await context()) != nil else { return }
        isInitialSyncReady = true
        await flushPendingJobs()
    }

    func handleChatKeyAvailabilityChanged() async { await flushPendingJobs() }

    private func cancelRetries() {
        for cancel in scheduledRetries.values { cancel() }
        scheduledRetries.removeAll()
    }

    func handleTransportDisconnected() {
        generation += 1
        isTransportConnected = false
        cancelRetries()
        jobsInProgress.removeAll()
    }

    func handleTransportConnected() async {
        isTransportConnected = true
        retryAttempts.removeAll()
        await flushPendingJobs()
    }

    func reset() {
        generation += 1
        cancelRetries()
        retryAttempts.removeAll()
        versionRefreshJobs.removeAll()
        jobsInProgress.removeAll()
        persistedJobIds.removeAll()
        pendingJobs.removeAll()
        pendingLocalMessages.removeAll()
        pendingStreamMessages.removeAll()
        terminalJobIdsByMessageId.removeAll()
        pendingTerminalJobs.removeAll()
        activeOwnerId = nil
        isInitialSyncReady = false
    }

    func handleTerminalStream(_ payload: [String: Any]) {
        guard payload["is_final_chunk"] as? Bool == true,
              Self.intValue(payload["recovery_protocol_version"]) == Self.protocolVersion,
              let jobId = payload["recovery_job_id"] as? String, !jobId.isEmpty,
              let chatId = payload["chat_id"] as? String, !chatId.isEmpty,
              !IncognitoChatSession.isIncognitoChatId(chatId),
              let messageId = payload["message_id"] as? String, !messageId.isEmpty else { return }
        guard let owner = currentOwnerSnapshot() else { return }
        bindOwner(owner)
        guard !persistedJobIds.contains(jobId) else { return }
        let entry = PendingAssistantResponseQueue.Entry(messageId: messageId, chatId: chatId,
                                                        recoveryJobId: jobId, queuedAt: now())
        terminalJobIdsByMessageId[messageId] = jobId
        pendingTerminalJobs[jobId] = entry
        if let owner = activeOwnerId {
            remember(entry, ownerId: owner)
            // Preserve this final payload until the normal Format A encryption
            // call completes. Lease ownership never gates the stream dispatcher.
            if let content = payload["full_content_so_far"] as? String {
                pendingStreamMessages[jobId] = Message(id: messageId, chatId: chatId, role: .assistant,
                    content: content, encryptedContent: nil,
                    createdAt: ChatSendPipeline.isoString(from: now()), updatedAt: nil,
                    appId: payload["category"] as? String, isStreaming: false, embedRefs: nil,
                    modelName: payload["model_name"] as? String)
            }
        }
        let expectedGeneration = generation
        Task { [weak self] in
            guard let self, self.generation == expectedGeneration else { return }
            await self.flushPendingJobs()
        }
    }

    func ownsRecoveryPersistence(messageId: String) -> Bool {
        terminalJobIdsByMessageId[messageId] != nil
    }

    private func flushPendingJobs() async {
        guard isInitialSyncReady, isChatKeyReady(), let attempt = try? await context(), isInitialSyncReady else { return }
        for entry in Array(pendingTerminalJobs.values) where chatKey(entry.chatId) != nil {
            guard (try? await validate(attempt)) != nil else { return }
            guard let jobId = entry.recoveryJobId, pendingTerminalJobs[jobId] != nil,
                  !persistedJobIds.contains(jobId) else { continue }
            remember(entry, ownerId: attempt.ownerId)
            await recoverPending(jobId: jobId, context: attempt)
        }
    }

    private func recoverPending(jobId: String, context: AttemptContext) async {
        guard generation == context.generation, activeOwnerId == context.ownerId, isTransportConnected,
              scheduledRetries[jobId] == nil, jobsInProgress.insert(jobId).inserted else { return }
        defer { if generation == context.generation { jobsInProgress.remove(jobId) } }
        do {
            try await validate(context)
            guard let entry = pendingTerminalJobs[jobId] else { return }
            if let streamed = pendingStreamMessages[jobId], let content = streamed.content,
               let key = chatKey(entry.chatId) {
                let encrypted = try await CryptoManager.shared.encryptContent(content, key: key)
                try await validate(context)
                let message = Message(id: streamed.id, chatId: streamed.chatId, role: .assistant,
                    content: content, encryptedContent: encrypted, createdAt: streamed.createdAt,
                    updatedAt: nil, appId: streamed.appId, isStreaming: false, embedRefs: nil,
                    modelName: streamed.modelName)
                persistMessage(message)
                pendingStreamMessages.removeValue(forKey: jobId)
            }
            if versionRefreshJobs.contains(jobId) {
                let (messages, version) = try await fetchChatSnapshot(chatId: entry.chatId, context: context)
                try await validate(context)
                persistSnapshot(entry.chatId, messages)
                applyCommittedMessagesVersion(entry.chatId, version)
                versionRefreshJobs.remove(jobId)
            }
            let claim = try await claim(jobId: jobId, context: context)
            guard let job = Self.availableJob(from: claim), job.jobId == jobId,
                  job.chatId == entry.chatId, job.assistantMessageId == entry.messageId,
                  pendingJobs[jobId] == nil || pendingJobs[jobId] == job else { throw RecoveryError.invalidClaim }
            try await recover(job, claim: claim, context: context)
            try await validate(context)
            pendingTerminalJobs.removeValue(forKey: jobId)
            pendingJobs.removeValue(forKey: jobId)
            recoveryQueue(context.ownerId)?.removeRecovery(jobId: jobId)
            retryAttempts.removeValue(forKey: jobId)
        } catch {
            guard generation == context.generation else { return }
            NativeDiagnostics.warning("completion_recovery_failed source=queued reason=\(Self.failureCategory(error)) job=\(jobId.prefix(8))")
            scheduleRetryIfNeeded(jobId: jobId, context: context, error: error)
        }
    }

    private func scheduleRetryIfNeeded(jobId: String, context: AttemptContext, error: Error) {
        guard isTransportConnected, scheduledRetries[jobId] == nil,
              Self.isRetryable(error) else { return }
        if let socketError = error as? WebSocketError, case .remote(let code) = socketError,
           code == "version_conflict" || code == "messages_version_conflict" {
            versionRefreshJobs.insert(jobId)
        }
        let attempt = retryAttempts[jobId, default: 0]
        guard attempt < Self.retryDelays.count else {
            NativeDiagnostics.warning("completion_recovery_retry_exhausted job=\(jobId.prefix(8))")
            return
        }
        retryAttempts[jobId] = attempt + 1
        scheduledRetries[jobId] = schedule(Self.retryDelays[attempt]) { [weak self] in
            guard let self, self.generation == context.generation else { return }
            self.scheduledRetries.removeValue(forKey: jobId)
            guard (try? await self.validate(context)) != nil else { return }
            await self.recoverPending(jobId: jobId, context: context)
        }
    }

    private static func isRetryable(_ error: Error) -> Bool {
        if let error = error as? WebSocketError {
            switch error {
            case .messageTimeout: return true
            case .remote(let code): return ["lease_conflict", "lease_tenure_exhausted", "stale_lease",
                                           "version_conflict", "messages_version_conflict"].contains(code)
            default: return false
            }
        }
        return (error as? RecoveryError) == .missingCommittedMessage
    }

    private func claim(jobId: String, context: AttemptContext) async throws -> [String: Any] {
        try await validate(context)
        NativeDiagnostics.info("completion_recovery_claim_started job=\(jobId.prefix(8))")
        let response = try await transport.sendAndWait(
            WSOutboundMessage(type: "recovery_job_claim", payload: [
                "protocol_version": Self.protocolVersion, "job_id": jobId,
            ]), responseType: "recovery_job_claimed"
        ) { $0["job_id"] as? String == jobId }
        try await validate(context)
        return response.fields
    }

    private func recover(_ job: AvailableJob, claim: [String: Any], context: AttemptContext) async throws {
        if claim["state"] as? String == "TERMINAL" {
            try await reconcileTerminal(job, acknowledgement: claim, context: context, requiresCommittedFetch: true)
            return
        }
        try await validate(context)
        let ownerId = context.ownerId
        guard let key = chatKey(job.chatId) else { throw RecoveryError.notReady }
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
        try await validate(context)
        let now = Int(self.now().timeIntervalSince1970)
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
            modelName: recovered.modelName,
            encryptedSenderName: encryptedSenderName,
            encryptedCategory: encryptedCategory,
            encryptedModelName: encryptedModelName
        )
        pendingLocalMessages[job.jobId] = localMessage
        NativeDiagnostics.info("completion_recovery_persist_started job=\(job.jobId.prefix(8))")
        let acknowledgement = (try await transport.sendAndWait(
            WSOutboundMessage(type: "recovery_job_persist", payload: [
                "protocol_version": Self.protocolVersion,
                "job_id": job.jobId,
                "lease_token": leaseToken,
                "lease_generation": leaseGeneration,
                "expected_messages_v": chatVersion(job.chatId) ?? 0,
                "encrypted_assistant_message": encryptedMessage,
            ]),
            responseType: "recovery_job_persisted"
        ) {
                $0["job_id"] as? String == job.jobId
        }).fields
        try await validate(context)
        // Directus validates the lease in the persist request. Its committed
        // response does not include lease_generation; reject a conflicting value
        // if a future server supplies one, rather than requiring an absent field.
        if let acknowledgedGeneration = acknowledgement["lease_generation"],
           Self.intValue(acknowledgedGeneration) != leaseGeneration {
            throw RecoveryError.invalidAcknowledgement
        }
        // The idempotent TERMINAL response can omit the current message version.
        // Read the same job's terminal state once to reconcile its committed
        // version; do not repeat the encrypted write or start another inference.
        if acknowledgement["state"] as? String == "TERMINAL",
           acknowledgement["job_id"] as? String == job.jobId,
           Self.intValue(acknowledgement["committed_messages_v"]) == nil {
            guard acknowledgement["idempotent"] as? Bool == true,
                  acknowledgement["chat_id"] as? String == job.chatId || acknowledgement["chat_id"] == nil,
                  acknowledgement["assistant_message_id"] as? String == job.assistantMessageId || acknowledgement["assistant_message_id"] == nil else {
                throw RecoveryError.invalidAcknowledgement
            }
            let terminal = try await self.claim(jobId: job.jobId, context: context)
            try await reconcileTerminal(job, acknowledgement: terminal, context: context, requiresCommittedFetch: true)
            return
        }
        try await reconcileTerminal(job, acknowledgement: acknowledgement, context: context,
                                    requiresCommittedFetch: acknowledgement["idempotent"] as? Bool == true)
    }

    private func reconcileTerminal(
        _ job: AvailableJob, acknowledgement: [String: Any], context: AttemptContext,
        requiresCommittedFetch: Bool = false
    ) async throws {
        guard acknowledgement["state"] as? String == "TERMINAL",
              acknowledgement["job_id"] as? String == job.jobId,
              acknowledgement["chat_id"] as? String == job.chatId || acknowledgement["chat_id"] == nil,
              acknowledgement["assistant_message_id"] as? String == job.assistantMessageId || acknowledgement["assistant_message_id"] == nil,
              let committedMessagesVersion = Self.intValue(acknowledgement["committed_messages_v"]),
              committedMessagesVersion >= 0 else {
            throw RecoveryError.invalidAcknowledgement
        }
        // A locally encrypted stream is still provisional while this job is
        // queued. A terminal claim from another saver must fetch its committed
        // ciphertext; merely possessing our own ciphertext is not proof of sync.
        let localVersion: Int
        if requiresCommittedFetch || pendingLocalMessages[job.jobId] == nil {
            localVersion = try await fetchCommittedChat(job, minimumVersion: committedMessagesVersion, context: context)
            pendingLocalMessages.removeValue(forKey: job.jobId)
        } else {
            localVersion = committedMessagesVersion
        }
        try await validate(context)
        guard persistedJobIds.insert(job.jobId).inserted else { return }
        // Upsert the encrypted copy even when this device already rendered the
        // plaintext final chunk. Otherwise it remains permanently unencrypted.
        if let message = pendingLocalMessages[job.jobId] {
            persistMessage(message)
        }
        // Persist the row before advertising the committed version; a process
        // termination between these writes must leave sync able to fetch it.
        applyCommittedMessagesVersion(job.chatId, localVersion)
        pendingLocalMessages.removeValue(forKey: job.jobId)
        NativeDiagnostics.info("completion_recovery_committed job=\(job.jobId.prefix(8))")
    }

    private func fetchChatSnapshot(chatId: String, context: AttemptContext) async throws -> ([Message], Int) {
        try await validate(context)
        let response = try await transport.sendAndWait(
            WSOutboundMessage(type: "request_chat_content_batch", payload: ["chat_ids": [chatId]]),
            responseType: "chat_content_batch_response"
        ) { fields in
            (fields["messages_by_chat_id"] as? [String: Any])?[chatId] != nil
        }
        try await validate(context)
        let batch = try ChatContentBatchPayload.decode(response.fields)
        let messages = try batch.messages(for: chatId)
        guard let version = batch.messagesVersion(for: chatId), version >= 0,
              version == 0 || !messages.isEmpty,
              messages.allSatisfy({ $0.chatId == chatId && !($0.encryptedContent?.isEmpty ?? true) }) else {
            throw RecoveryError.missingCommittedMessage
        }
        return (messages, version)
    }

    private func fetchCommittedChat(_ job: AvailableJob, minimumVersion: Int, context: AttemptContext) async throws -> Int {
        let (messages, version) = try await fetchChatSnapshot(chatId: job.chatId, context: context)
        guard version >= minimumVersion,
              let target = messages.first(where: { $0.id == job.assistantMessageId && $0.role == .assistant }),
              let ciphertext = target.encryptedContent, !ciphertext.isEmpty,
              let key = chatKey(job.chatId) else { throw RecoveryError.missingCommittedMessage }
        // Authenticate the exact assistant ciphertext before acknowledging local
        // convergence. Other rows remain encrypted and hydrate on normal display.
        let content = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
        try await validate(context)
        let hydrated = messages.map { message in
            var message = message
            if message.id == target.id { message.content = content }
            return message
        }
        persistSnapshot(job.chatId, hydrated)
        // All rows from this authoritative snapshot precede its version update.
        return version
    }

    static func mergingRecoveredMessage(_ recovered: Message, preserving existing: Message?) -> Message {
        guard let existing, existing.id == recovered.id, existing.chatId == recovered.chatId else { return recovered }
        return Message(
            id: recovered.id, chatId: recovered.chatId, role: recovered.role,
            content: recovered.content ?? (recovered.encryptedContent == existing.encryptedContent ? existing.content : nil),
            encryptedContent: recovered.encryptedContent,
            createdAt: existing.createdAt, updatedAt: recovered.updatedAt ?? existing.updatedAt,
            appId: recovered.appId ?? existing.appId, isStreaming: false, embedRefs: existing.embedRefs,
            modelName: recovered.modelName ?? existing.modelName,
            senderName: existing.senderName, category: recovered.category ?? existing.category,
            encryptedSenderName: recovered.encryptedSenderName ?? existing.encryptedSenderName,
            encryptedCategory: recovered.encryptedCategory ?? existing.encryptedCategory,
            encryptedModelName: recovered.encryptedModelName ?? existing.encryptedModelName,
            piiMappings: existing.piiMappings, encryptedPIIMappings: existing.encryptedPIIMappings,
            thinkingContent: existing.thinkingContent, encryptedThinkingContent: existing.encryptedThinkingContent,
            encryptedThinkingSignature: existing.encryptedThinkingSignature, thinkingTokenCount: existing.thinkingTokenCount
        )
    }

    private static func failureCategory(_ error: Error) -> String {
        if let recoveryError = error as? RecoveryError {
            // This private enum has no associated data or user-derived strings.
            return String(describing: recoveryError)
        }
        if let socketError = error as? WebSocketError {
            switch socketError {
            case .notConnected: return "disconnected"
            case .encodingFailed: return "encoding"
            case .messageTimeout: return "timeout"
            case .remote(let code):
                // Only fixed protocol codes are logged; arbitrary response
                // strings and server error bodies remain excluded.
                switch code {
                case "lease_conflict", "lease_tenure_exhausted", "stale_lease",
                     "version_conflict", "messages_version_conflict",
                     "recovery_job_not_found", "recovery_job_expired": return code
                default: return "remote-rejection"
                }
            }
        }
        return "operation-failed"
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
              let version = intValue(value["chat_key_version"]), version >= 1, version <= Int(UInt32.max) else { return nil }
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

private enum RecoveryError: Error, Equatable {
    case staleContext
    case invalidAcknowledgement
    case invalidClaim
    case invalidEnvelope
    case invalidJSON
    case invalidPlaintext
    case missingCommittedMessage
    case notReady
}
