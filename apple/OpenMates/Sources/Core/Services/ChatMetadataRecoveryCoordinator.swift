// Generated metadata uses a separate sealed purpose and atomic commit receipt.
// No plaintext or keys are queued on disk. The server retains uncommitted jobs;
// exact ciphertext is retained in memory while a commit acknowledgement retries.
import Combine
import CryptoKit
import Foundation

@MainActor
final class ChatMetadataRecoveryCoordinator {
    struct Job: Equatable {
        let id: String
        let chatId: String
        let taskId: String
        let stage: String
        let keyVersion: UInt32

        init(fields: [String: Any]) throws {
            guard let id = fields["job_id"] as? String,
                  let chatId = fields["chat_id"] as? String,
                  let taskId = fields["task_id"] as? String,
                  let stage = fields["stage"] as? String,
                  ["initial", "postprocessing"].contains(stage),
                  let version = fields["chat_key_version"] as? Int,
                  version > 0, version <= Int(UInt32.max),
                  [id, chatId, taskId].allSatisfy({ UUID(uuidString: $0)?.uuidString.lowercased() == $0 }) else {
                throw Failure.invalidPayload
            }
            self.id = id; self.chatId = chatId; self.taskId = taskId
            self.stage = stage; self.keyVersion = UInt32(version)
        }
    }

    enum Failure: Error { case invalidPayload, staleOwner, unavailableKey }
    static let encryptedFields = ["title": "encrypted_title", "summary": "encrypted_chat_summary",
                                  "category": "encrypted_category", "icon": "encrypted_icon"]
    private let transport: ChatWebSocketTransport
    private let owner: () -> String?
    private let eligible: () async -> Bool
    private let chatKey: (String) -> SymmetricKey?
    private let wrappedKey: (String) -> String?
    private let hasShell: (String) -> Bool
    private let apply: (String, [String: String], [String: String], Int, Int) -> Void
    private var activeOwner: String?
    private var generation = 0
    private var ready = false
    private var connected = true
    private var jobs: [String: Job] = [:]
    private var attempts: [String: Task<Void, Never>] = [:]
    private var retries: [String: Task<Void, Never>] = [:]
    private var retryCounts: [String: Int] = [:]
    private var readinessSubscriptions = Set<AnyCancellable>()
    private var pendingReadiness: [String: Readiness] = [:]
    private struct Readiness: Equatable { let shell: Bool; let key: Bool; let wrapper: String? }
    private var ciphertext: [String: [String: String]] = [:]

    init(transport: ChatWebSocketTransport, owner: @escaping () -> String?,
         eligible: @escaping () async -> Bool = { true },
         chatKey: @escaping (String) -> SymmetricKey?, wrappedKey: @escaping (String) -> String?,
         hasShell: @escaping (String) -> Bool,
         apply: @escaping (String, [String: String], [String: String], Int, Int) -> Void) {
        self.transport = transport; self.owner = owner; self.eligible = eligible
        self.chatKey = chatKey; self.wrappedKey = wrappedKey; self.hasShell = hasShell; self.apply = apply
    }

    convenience init(transport: ChatWebSocketTransport, chatStore: ChatStore) {
        self.init(transport: transport, owner: {
            guard let owner = AuthManager.notificationAccountId,
                  OfflineStore.shared.activeScopeId == OfflineStore.scopeId(
                    userId: owner, apiBaseURL: ServerConfiguration.current.apiBaseURL) else { return nil }
            return owner.lowercased()
        }, eligible: { await AuthManager.isRecoveryEligibleDevice() },
        chatKey: { ChatKeyManager.shared.key(for: $0) },
        wrappedKey: { chatStore.chat(for: $0)?.encryptedChatKey },
        hasShell: { chatStore.chat(for: $0) != nil },
        apply: { chatStore.applyRecoveredMetadata(chatId: $0, encrypted: $1, plaintext: $2,
                                                metadataVersion: $3, titleVersion: $4) })
        observeReadiness(chatStore: chatStore)
    }

    func reset() {
        generation += 1
        attempts.values.forEach { $0.cancel() }; retries.values.forEach { $0.cancel() }
        attempts.removeAll(); retries.removeAll(); retryCounts.removeAll()
        jobs.removeAll(); ciphertext.removeAll(); pendingReadiness.removeAll(); activeOwner = nil; ready = false
    }

    func disconnected() {
        generation += 1; connected = false
        attempts.values.forEach { $0.cancel() }; retries.values.forEach { $0.cancel() }
        attempts.removeAll(); retries.removeAll(); retryCounts.removeAll()
    }

    func connectedToTransport() async {
        connected = true
        guard bindOwner() else { return }
        await discover()
        drain()
    }

    func syncReady() async {
        guard bindOwner() else { return }
        ready = true
        await discover()
        drain()
    }

    // Readiness changes are projected onto pending job identities only. Ordinary
    // transcript/list updates do not restart requests or scan unrelated keys.
    func observeReadiness(chatStore: ChatStore) {
        readinessSubscriptions.removeAll()
        chatStore.$chats.sink { [weak self] chats in
            self?.readinessChanged(chats: chats)
        }.store(in: &readinessSubscriptions)
        NotificationCenter.default.publisher(for: .chatKeyMaterialAvailable).sink { [weak self] note in
            let scope = note.userInfo?["accountScope"] as? UUID
            Task { @MainActor [weak self] in
                guard scope == nil || scope == OfflineStore.shared.scopeGeneration else { return }
                self?.readinessChanged()
            }
        }.store(in: &readinessSubscriptions)
    }

    private func readinessChanged(chats: [Chat]? = nil) {
        guard !jobs.isEmpty else { return }
        let shells = chats.map { Dictionary($0.map { ($0.id, $0.encryptedChatKey) }, uniquingKeysWith: { _, last in last }) }
        let next = Dictionary(uniqueKeysWithValues: Set(jobs.values.map(\.chatId)).map { chatId in
            (chatId, Readiness(shell: shells.map { $0.keys.contains(chatId) } ?? hasShell(chatId),
                key: chatKey(chatId) != nil, wrapper: shells.map { $0[chatId] ?? nil } ?? wrappedKey(chatId)))
        })
        guard next != pendingReadiness else { return }
        pendingReadiness = next
        // Published emits before ChatStore assigns its property. Yield to the
        // accepted store snapshot, retaining the owner cancellation generation.
        let expectedGeneration = generation
        Task { @MainActor [weak self] in
            guard let self, self.generation == expectedGeneration else { return }
            self.drain()
        }
    }

    func keysChanged() { readinessChanged() }

    func available(_ fields: [String: Any]) {
        guard bindOwner(), let items = fields["jobs"] as? [[String: Any]] else { return }
        for item in items.prefix(100) {
            guard let job = try? Job(fields: item), jobs.count < 200 || jobs[job.id] != nil else { continue }
            jobs[job.id] = job
        }
        drain()
    }

    private func bindOwner() -> Bool {
        guard let current = owner() else { reset(); return false }
        if let activeOwner, activeOwner != current { reset() }
        activeOwner = current
        return true
    }

    private func discover() async {
        guard connected, activeOwner != nil else { return }
        try? await transport.send(WSOutboundMessage(type: "metadata_jobs_request", payload: ["protocol_version": 1]))
    }

    private func drain() {
        guard bindOwner(), ready, connected, let owner = activeOwner else { return }
        for job in jobs.values where attempts[job.id] == nil && retries[job.id] == nil {
            guard hasShell(job.chatId), chatKey(job.chatId) != nil, wrappedKey(job.chatId) != nil else { continue }
            let expectedGeneration = generation
            attempts[job.id] = Task { @MainActor [weak self] in
                guard let self else { return }
                await self.recover(job, ownerId: owner, expectedGeneration: expectedGeneration)
                guard self.generation == expectedGeneration else { return }
                self.attempts.removeValue(forKey: job.id)
            }
        }
    }

    private func check(ownerId: String, expectedGeneration: Int) throws {
        try Task.checkCancellation()
        guard connected, generation == expectedGeneration, owner() == ownerId else { throw Failure.staleOwner }
    }

    private func recover(_ job: Job, ownerId: String, expectedGeneration: Int) async {
        do {
            try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
            guard await eligible() else { return }
            try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
            guard hasShell(job.chatId), let key = chatKey(job.chatId), let wrapped = wrappedKey(job.chatId) else {
                throw Failure.unavailableKey
            }
            if ciphertext[job.id] == nil {
                let requestId = UUID().uuidString.lowercased()
                let claim = try await transport.sendAndWait(WSOutboundMessage(type: "metadata_job_claim", payload: [
                    "protocol_version": 1, "job_id": job.id, "request_id": requestId,
                ]), responseType: "metadata_job_claimed") { fields in
                    fields["job_id"] as? String == job.id && fields["request_id"] as? String == requestId
                }
                try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
                guard try Job(fields: claim.fields) == job else { throw Failure.invalidPayload }
                guard claim.fields["state"] as? String == "AVAILABLE" else {
                    finish(job.id); return // Initial sync supplies already committed ciphertext.
                }
                guard let sealed = claim.fields["sealed_payload"] as? String,
                      let expectedFields = claim.fields["encrypted_fields"] as? [String] else { throw Failure.invalidPayload }
                let metadata = try await Self.open(sealed: sealed, job: job, ownerId: ownerId, key: key)
                try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
                guard Set(expectedFields) == Set(metadata.keys.compactMap { Self.encryptedFields[$0] }) else {
                    throw Failure.invalidPayload
                }
                var encrypted: [String: String] = [:]
                for (field, value) in metadata {
                    encrypted[Self.encryptedFields[field]!] = try await CryptoManager.shared.encryptContent(value, key: key)
                }
                try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
                ciphertext[job.id] = encrypted
            }
            guard let encrypted = ciphertext[job.id] else { throw Failure.invalidPayload }
            let requestId = UUID().uuidString.lowercased()
            try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
            let receipt = try await transport.sendAndWait(WSOutboundMessage(type: "metadata_job_persist", payload: [
                "protocol_version": 1, "job_id": job.id, "request_id": requestId,
                "chat_key_version": Int(job.keyVersion), "wrapped_chat_key": wrapped,
                "encrypted_metadata": encrypted,
            ]), responseType: "metadata_job_persisted") { fields in
                fields["job_id"] as? String == job.id && fields["request_id"] as? String == requestId
            }
            try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
            guard try Job(fields: receipt.fields) == job,
                  let state = receipt.fields["state"] as? String,
                  ["TERMINAL", "SUPERSEDED"].contains(state),
                  let accepted = receipt.fields["encrypted_metadata"] as? [String: String],
                  Set(accepted.keys).isSubset(of: Set(Self.encryptedFields.values)),
                  let versions = receipt.fields["versions"] as? [String: Any],
                  let metadataVersion = versions["metadata_v"] as? Int, metadataVersion >= 0,
                  let titleVersion = versions["title_v"] as? Int, titleVersion >= 0 else { throw Failure.invalidPayload }
            // Apply only server-accepted ciphertext, including a retry receipt.
            // Superseded title fields must never apply the proposed plaintext.
            if state == "TERMINAL" {
                var plaintext: [String: String] = [:]
                for (field, value) in accepted {
                    plaintext[field] = try await CryptoManager.shared.decryptContent(base64String: value, key: key)
                }
                try check(ownerId: ownerId, expectedGeneration: expectedGeneration)
                apply(job.chatId, accepted, plaintext, metadataVersion, titleVersion)
            }
            finish(job.id)
        } catch {
            guard generation == expectedGeneration, owner() == ownerId, connected else { return }
            scheduleRetry(job.id)
        }
    }

    private func finish(_ id: String) {
        jobs.removeValue(forKey: id); ciphertext.removeValue(forKey: id); retryCounts.removeValue(forKey: id)
        retries.removeValue(forKey: id)?.cancel()
    }

    private func scheduleRetry(_ id: String) {
        let delays: [UInt64] = [1, 3, 10, 30, 60]
        let count = retryCounts[id, default: 0]
        guard count < delays.count else { return }
        retryCounts[id] = count + 1
        retries[id] = Task { @MainActor [weak self] in
            do { try await Task.sleep(for: .seconds(delays[count])) } catch { return }
            guard let self else { return }
            self.retries.removeValue(forKey: id)
            self.drain()
        }
    }

    static func associatedData(job: Job, ownerId: String) throws -> Data {
        var aad = Data("OMCM1".utf8)
        for value in [ownerId, job.chatId, job.taskId, job.id] {
            guard UUID(uuidString: value)?.uuidString.lowercased() == value else { throw Failure.invalidPayload }
            append(value, to: &aad)
        }
        append(job.stage, to: &aad)
        var version = job.keyVersion.bigEndian
        withUnsafeBytes(of: &version) { aad.append(contentsOf: $0) }
        return aad
    }

    private static func append(_ value: String, to data: inout Data) {
        let bytes = Data(value.utf8)
        var count = UInt32(bytes.count).bigEndian
        withUnsafeBytes(of: &count) { data.append(contentsOf: $0) }
        data.append(bytes)
    }

    private static func decode(_ value: String) throws -> Data {
        guard !value.isEmpty, !value.contains("=") else { throw Failure.invalidPayload }
        let base64 = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        guard let data = Data(base64Encoded: base64 + String(repeating: "=", count: (4 - base64.count % 4) % 4)),
              data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") == value else {
            throw Failure.invalidPayload
        }
        return data
    }

    static func open(sealed: String, job: Job, ownerId: String, key: SymmetricKey) async throws -> [String: String] {
        guard let serialized = sealed.data(using: .utf8), serialized.count <= 90 * 1024,
              let envelope = try JSONSerialization.jsonObject(with: serialized) as? [String: Any],
              Set(envelope.keys) == ["v", "epk", "nonce", "ciphertext"], envelope["v"] as? Int == 1,
              let ephemeralString = envelope["epk"] as? String,
              let nonceString = envelope["nonce"] as? String,
              let ciphertextString = envelope["ciphertext"] as? String else { throw Failure.invalidPayload }
        let pair = try await CryptoManager.shared.deriveRecoveryKeyPair(chatKey: key, chatId: job.chatId, keyVersion: job.keyVersion)
        let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: decode(pair.privateKey))
        let ephemeral = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: decode(ephemeralString))
        let aad = try associatedData(job: job, ownerId: ownerId)
        let secret = try privateKey.sharedSecretFromKeyAgreement(with: ephemeral)
        let envelopeKey = secret.hkdfDerivedSymmetricKey(using: SHA256.self,
            salt: Data(SHA256.hash(data: Data("openmates:chat-recovery-envelope:v1".utf8))),
            sharedInfo: Data(SHA256.hash(data: aad)), outputByteCount: 32)
        let nonce = try decode(nonceString)
        let ciphertext = try decode(ciphertextString)
        guard nonce.count == 12, ciphertext.count >= 16, ciphertext.count <= 64 * 1024 + 16 else { throw Failure.invalidPayload }
        let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: nonce),
            ciphertext: ciphertext.dropLast(16), tag: ciphertext.suffix(16))
        let opened = try AES.GCM.open(box, using: envelopeKey, authenticating: aad)
        guard let payload = try JSONSerialization.jsonObject(with: opened) as? [String: Any],
              Set(payload.keys) == ["owner_id", "chat_id", "task_id", "job_id", "stage", "key_version", "metadata"],
              payload["owner_id"] as? String == ownerId, payload["chat_id"] as? String == job.chatId,
              payload["task_id"] as? String == job.taskId, payload["job_id"] as? String == job.id,
              payload["stage"] as? String == job.stage, payload["key_version"] as? Int == Int(job.keyVersion),
              let metadata = payload["metadata"] as? [String: String], !metadata.isEmpty,
              Set(metadata.keys).isSubset(of: Set(encryptedFields.keys)), metadata.values.allSatisfy({ !$0.isEmpty }) else {
            throw Failure.invalidPayload
        }
        return metadata
    }
}
