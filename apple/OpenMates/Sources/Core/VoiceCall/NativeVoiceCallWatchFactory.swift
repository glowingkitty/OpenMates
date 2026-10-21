// Web source: frontend/packages/ui/src/services/voiceCall.ts, voiceCallMessages.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.transcripts,
// video-call.chat.compressed-context, video-call.privacy.first-call-warning,
// video-call.chat.skill-integration, video-call.chat.memories-and-focus, video-call.privacy
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
#if os(watchOS)
import Foundation

/// Retain alongside WatchChatRuntime in WatchRootView. This constructs actual
/// audio/auth/context/crypto/socket adapters; product admission stays disabled
/// until source-bound physical route proof authorizes the installed route.
@MainActor
final class NativeVoiceCallWatchFactory {
    private let auth: WatchAuthStore
    private weak var chat: WatchChatRuntime?
    let physicalRouteVerified: Bool
    private let consent: @MainActor @Sendable () async -> Bool
    private let downstream: @MainActor @Sendable (NativeVoiceCallEvent) async -> Void
    private let storageLease: WatchVoiceCallStorageLease
    private var stopped = false
    private var evaluationLease: WatchVoiceEvaluationLease?
    private let generation = UUID()
    private var contexts: [String: WatchChatRequestContext] = [:]
    private var preparedChats: [String: (chat: WatchChatSummary, needsServerConfirmation: Bool)] = [:]
    private var metadataByChat: [String: NativeVoiceCallFrame] = [:]
    private var pumpTask: Task<Void, Never>?
    private var pumpDirty = false
    private var committedArtifacts = WatchVoiceCallCommittedArtifacts()
    private var artifactCallID: String?
    private var projectionClaimed = false
    private static var projectionOwners: [ObjectIdentifier: WatchVoiceCallProjectionOwnership] = [:]
    private func claimProjection(replacingIdle: Bool) -> Bool {
        guard let chat else { return false }
        let id = ObjectIdentifier(chat)
        var ownership = Self.projectionOwners[id] ?? WatchVoiceCallProjectionOwnership()
        guard ownership.claim(generation, replacingIdle: replacingIdle, audioOwned: chat.callActions.projection.ownsAudio) else { return false }
        Self.projectionOwners[id] = ownership; projectionClaimed = true; return true
    }
    private var ownsProjection: Bool {
        guard let chat else { return false }
        return Self.projectionOwners[ObjectIdentifier(chat)]?.isCurrent(generation) == true
    }
    private func releaseProjection() -> Bool {
        guard let chat else { return false }
        let id = ObjectIdentifier(chat)
        guard var ownership = Self.projectionOwners[id], ownership.release(generation) else { return false }
        Self.projectionOwners.removeValue(forKey: id); return true
    }

    init(auth: WatchAuthStore, runtime: WatchChatRuntime, physicalRouteVerified: Bool,
         consent: @escaping @MainActor @Sendable () async -> Bool,
         event: @escaping @MainActor @Sendable (NativeVoiceCallEvent) async -> Void) {
        self.auth = auth; chat = runtime; self.physicalRouteVerified = physicalRouteVerified
        self.consent = consent; downstream = event
        storageLease = WatchVoiceCallStorageOwners.lease(accountID: auth.currentUser?.id ?? "",
            profileID: ServerProfile.current().id)
    }
    private func context(_ scope: NativeVoiceCallScope) throws -> WatchChatRequestContext {
        guard !stopped, (!projectionClaimed || ownsProjection),
              scope.workspaceGeneration == generation, let request = contexts[scope.chatID],
              request.accountID == scope.accountID, request.profile.id == scope.profileID,
              auth.state == .authenticated, auth.currentUser?.id == scope.accountID else { throw NativeVoiceCallError.scopeChanged }
        try request.check()
        try evaluationLease?.checkExecution()
        return request
    }
    private func current(_ scope: NativeVoiceCallScope) -> Bool { (try? context(scope)) != nil }
    private lazy var crypto = NativeVoiceCallWatchCryptography(encrypt: { [weak self] text, scope in
        guard let self, let chat = self.chat else { throw NativeVoiceCallError.scopeChanged }
        return try await chat.voiceCallEncrypt(text, chatID: scope.chatID, context: context(scope))
    }, decrypt: { [weak self] text, scope in
        guard let self, let chat = self.chat else { throw NativeVoiceCallError.scopeChanged }
        return try await chat.voiceCallDecrypt(text, chatID: scope.chatID, context: context(scope))
    })
    private lazy var canonical = NativeVoiceCallCanonicalPersistence(crypto: crypto,
        storage: WatchVoiceCallAuxiliaryStorage(disk: .shared, lease: storageLease),
        isCurrent: { [weak self] scope in await self?.current(scope) == true }, keyVersion: { [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.keyVersion(scope)
        },
        request: { [weak self] scope, frame, response in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.request(scope: scope, frame: frame, response: response)
        })
    private lazy var outbox = NativeVoiceCallOutbox(crypto: crypto,
        storage: WatchVoiceCallOutboxStorage(disk: .shared, lease: storageLease),
        isCurrent: { [weak self] scope in await self?.current(scope) == true }, checkpoint: { [weak self] scope, callID, frame in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.canonical.persist(scope: scope, callID: callID, frame: frame)
        })
    private lazy var audio: NativeVoiceCallWatchAudio = NativeVoiceCallWatchAudio(ownership: .shared, eligible: { [weak self] in
            guard let self, !self.stopped else { return false }
            if let lease = self.evaluationLease { return lease.permitsCurrentCapture }
            return self.physicalRouteVerified
        },
        inputIdle: { [weak self] idle in await self?.inputIdleChanged(idle) })
    private func inputIdleChanged(_ idle: Bool) async {
        await controller.setVerifiedInputIdle(idle)
    }
    private lazy var environment: NativeVoiceCallEnvironment = {
        return NativeVoiceCallWatchEnvironment.make(auth: auth, context: { [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }; return try context(scope)
        }, consentDecision: consent, loadContext: { [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.loadContext(scope)
        }, prepare: { [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            try await self.confirmPreparedChat(scope)
        })
    }()
    lazy var controller: NativeVoiceCallController = NativeVoiceCallController(environment: environment, audio: audio, persistence: outbox,
        transportFactory: { NativeVoiceCallURLSessionTransport(cookieStorage: OpenMatesSharedEnvironment.cookieStorage) },
        eventHandler: { [weak self] event in await self?.receive(event) })

    /// Actual WatchRoot installation: call once after constructing the matching
    /// authenticated WatchChatRuntime; the root retains this factory per owner.
    func install() {
        // Diagnostic leases can never install the ordinary phone action.
        guard !stopped, evaluationLease == nil, let chat, claimProjection(replacingIdle: false) else { return }
        WatchNativeCallBinding.install(adapter: chat.callActions, controller: controller,
            physicalRouteVerified: physicalRouteVerified, prepareScope: { [weak self] request, chatID in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                return try await prepareScope(context: request, chatID: chatID)
            })
    }
    private func prepareScope(context request: WatchChatRequestContext, chatID: String) async throws -> NativeVoiceCallScope {
        guard physicalRouteVerified, evaluationLease == nil else { throw NativeVoiceCallError.unsupportedTransport }
        return try await prepareBoundScope(context: request, chatID: chatID)
    }
    /// Root-owned evaluation UI is the only issuer-facing entry. The private
    /// physical lease was obtained from genuine same-attempt hardware checks.
    /// No product adapter is installed and physicalRouteVerified stays false.
    static func developmentEvaluation(auth: WatchAuthStore, runtime: WatchChatRuntime,
        lease: WatchVoiceEvaluationLease, attemptID: UUID,
        event: @escaping @MainActor @Sendable (NativeVoiceCallEvent) async -> Void) throws -> NativeVoiceCallWatchFactory {
        try lease.checkOwner(auth: auth, runtime: runtime)
        try lease.consume(attemptID: attemptID)
        guard auth.state == .authenticated, auth.isVerifiedOnline,
              auth.currentUser?.id == lease.context.accountID,
              lease.context.profile == .development, ServerProfile.current() == .development else {
            lease.revoke(); throw NativeVoiceCallError.scopeChanged
        }
        let factory = NativeVoiceCallWatchFactory(auth: auth, runtime: runtime, physicalRouteVerified: false,
            consent: { false }, event: event)
        factory.evaluationLease = lease
        return factory
    }
    func startDevelopmentEvaluation() async throws {
        guard !stopped, !physicalRouteVerified, let lease = evaluationLease else {
            throw NativeVoiceCallError.unsupportedTransport
        }
        try lease.checkExecution()
        let scope = try await prepareBoundScope(context: lease.context, chatID: lease.chatID)
        try lease.checkExecution()
        guard claimProjection(replacingIdle: true) else { throw NativeVoiceCallError.invalidState }
        try await controller.start(scope: scope)
    }
    func evaluationAudioDiagnostics() -> NativeVoiceCallWatchAudio.Diagnostics? {
        guard evaluationLease != nil else { return nil }; return audio.diagnostics
    }
    private func prepareBoundScope(context request: WatchChatRequestContext, chatID: String) async throws -> NativeVoiceCallScope {
        guard !stopped, let chat, let owner = request.accountID,
              auth.currentUser?.id == owner else { throw NativeVoiceCallError.unsupportedTransport }
        if let lease = evaluationLease {
            try lease.checkExecution()
            guard request.accountID == lease.context.accountID, request.profile == lease.context.profile,
                  request.accountGeneration == lease.context.accountGeneration, chatID == lease.chatID else {
                throw NativeVoiceCallError.scopeChanged
            }
        }
        try request.check()
        let prepared = try await chat.prepareVoiceCallChat(context: request, chatID: chatID)
        try request.check()
        contexts[chatID] = request
        preparedChats[chatID] = prepared
        let scope = NativeVoiceCallScope(accountID: owner, profileID: request.profile.id,
            workspaceGeneration: generation, chatID: chatID,
            mateCategory: prepared.chat.category ?? "general_knowledge")
        _ = try context(scope)
        return scope
    }
    /// Runs inside controller admission AFTER saved consent and actual bounded
    /// capture. The existing Watch socket can now use genuine audio eligibility.
    private func confirmPreparedChat(_ scope: NativeVoiceCallScope) async throws {
        guard let chat, let prepared = preparedChats[scope.chatID] else { throw NativeVoiceCallError.contextUnavailable }
        let request = try context(scope), chatID = scope.chatID
        if !auth.isVerifiedOnline || NativeVoiceCallWatchEnvironment.tokenNeedsRefresh(auth.webSocketToken) {
            await auth.checkSession()
            _ = try context(scope)
        }
        guard auth.isVerifiedOnline, let token = auth.webSocketToken,
              !NativeVoiceCallWatchEnvironment.tokenNeedsRefresh(token) else { throw NativeVoiceCallError.callUnavailable }
        chat.updateWebSocketToken(token)
        try await chat.activateVoiceCallCanonicalTransport(context: request)
        _ = try context(scope)
        if prepared.needsServerConfirmation {
            guard let wrapper = prepared.chat.encryptedChatKey, !wrapper.isEmpty else { throw NativeVoiceCallError.contextUnavailable }
            let now = floor(Date().timeIntervalSince1970)
            let response = try await chat.voiceCallCanonicalRequest(context: request, chatID: chatID,
                frame: ["type": .string("encrypted_chat_metadata"), "chat_id": .string(chatID),
                    "encrypted_chat_key": .string(wrapper), "created_at": .number(now),
                    "versions": .object(["messages_v": .number(0), "title_v": .number(0),
                        "metadata_v": .number(0), "last_edited_overall_timestamp": .number(now)])],
                responseType: "encrypted_metadata_stored")
            let expected = NativeVoiceCallChatAdmissionProof.Expected(chatID: chatID,
                encryptedChatKey: wrapper, versions: .init(messages: prepared.chat.messagesV,
                    title: prepared.chat.titleV, metadata: prepared.chat.metadataV))
            let proof = NativeVoiceCallChatAdmissionProof(readAuthoritative: { [weak self] in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                return try await self.authoritativeAdmissionRows(scope)
            }, checkCurrent: { [weak self] in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                _ = try await self.context(scope)
            })
            // encrypted_metadata_stored is queued_for_storage in the current
            // handler. It never authorizes provider admission by itself.
            let durable = try await proof.confirm(queueReceipt: response, expected: expected)
            let refreshed = try await metadata(request: request, chatID: chatID)
            guard try NativeVoiceCallChatAdmissionProof.versions(refreshed) ==
                NativeVoiceCallChatAdmissionProof.versions(durable)
            else { throw NativeVoiceCallError.persistenceFailed }
            _ = try context(scope)
            preparedChats[chatID] = (prepared.chat, false)
        }
        _ = try context(scope)
    }
    /// HTTPS /chats reads durable Directus metadata, rather than the pending
    /// canonical-socket cache updated before async encrypted storage completes.
    /// A new chat belongs in this bounded recent page; absence fails closed.
    private func authoritativeAdmissionRows(_ scope: NativeVoiceCallScope) async throws -> [NativeVoiceCallFrame] {
        let request = try context(scope)
        let data = try await APIClient.shared.requestForVerifiedWatchSession(.get,
            path: "/v1/chats?limit=100&offset=0", serverProfile: request.profile,
            headers: ["Cache-Control": "no-cache", "Pragma": "no-cache"],
            validate: { try request.check() })
        _ = try context(scope)
        guard data.count <= 2 * 1_024 * 1_024,
              let payload = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: data),
              case .array(let rows)? = payload["chats"], rows.count <= 100,
              rows.allSatisfy({ $0.object != nil }) else { throw NativeVoiceCallError.persistenceFailed }
        return rows.compactMap(\.object)
    }
    private func metadata(request: WatchChatRequestContext, chatID: String) async throws -> NativeVoiceCallFrame {
        guard let chat else { throw NativeVoiceCallError.scopeChanged }
        let response = try await chat.voiceCallCanonicalRequest(context: request, chatID: chatID,
            frame: ["type": .string("phased_sync_request"), "phase": .string("phase2"),
                "refresh_chat_ids": .array([.string(chatID)]), "client_chat_ids": .array([.string(chatID)]),
                "client_chat_versions": .object([:]), "team_id": .null, "context_epoch": .number(0)],
            responseType: "phase_2_last_20_chats_ready")
        let details: [NativeVoiceCallFrame]
        if case .array(let rows)? = response["chats"] {
            details = rows.compactMap { $0.object?["chat_details"]?.object ?? $0.object }
        } else if case .array(let rows)? = response["recent_chat_metadata"] { details = rows.compactMap(\.object) }
        else { throw NativeVoiceCallError.contextUnavailable }
        let matches = details.filter { ($0["id"]?.string ?? $0["chat_id"]?.string) == chatID }
        guard matches.count == 1, let selected = matches.first,
              let prepared = preparedChats[chatID], let expectedKey = prepared.chat.encryptedChatKey,
              !expectedKey.isEmpty else { throw NativeVoiceCallError.contextUnavailable }
        let expected = NativeVoiceCallChatAdmissionProof.Expected(chatID: chatID,
            encryptedChatKey: expectedKey, versions: .init(messages: prepared.chat.messagesV,
                title: prepared.chat.titleV, metadata: prepared.chat.metadataV))
        // The key/version proof is mandatory for existing and new chats. A
        // missing field cannot silently turn an equality check into admission.
        _ = try NativeVoiceCallChatAdmissionProof.validate(selected, expected: expected, exactVersions: false)
        metadataByChat[chatID] = selected
        return selected
    }
    private func keyVersion(_ scope: NativeVoiceCallScope) throws -> Int? {
        _ = try context(scope)
        guard let value = metadataByChat[scope.chatID]?["key_version"]?.number else { return nil }
        guard value >= 1, value <= Double(UInt32.max), value.rounded(.down) == value
        else { throw NativeVoiceCallError.contextUnavailable }
        return Int(value)
    }
    private func request(scope: NativeVoiceCallScope, frame: NativeVoiceCallFrame,
                         response: String) async throws -> NativeVoiceCallFrame {
        guard let chat else { throw NativeVoiceCallError.scopeChanged }
        return try await chat.voiceCallCanonicalRequest(context: context(scope), chatID: scope.chatID,
            frame: frame, responseType: response)
    }
    private func loadContext(_ scope: NativeVoiceCallScope) async throws -> NativeVoiceCallContext {
        var loader = NativeVoiceCallCanonicalContextLoader(request: { [weak self] scope, path in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            let request = try await self.context(scope)
            return try await APIClient.shared.requestForVerifiedWatchSession(.get, path: path,
                serverProfile: request.profile, validate: { try request.check() })
        }, decrypt: { @MainActor [weak self] text, scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.crypto.decrypt(text, scope: scope)
        }, metadata: { @MainActor [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.metadata(request: context(scope), chatID: scope.chatID)
        }, isCurrent: { [weak self] scope in await self?.current(scope) == true })
        loader.memoryMetadata = { @MainActor [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            let request = try context(scope)
            let metadata = try await WatchVoiceCallMemoryLoader.live.availableMetadata(context: request)
            _ = try context(scope)
            return metadata
        }
        return try await loader.load(scope: scope)
    }
    private func receive(_ event: NativeVoiceCallEvent) async {
        guard let chat else { return }
        switch event {
        case .state(let snapshot):
            if ownsProjection, snapshot.scope == nil || snapshot.scope.map(current) == true {
                WatchNativeCallBinding.update(adapter: chat.callActions, snapshot: snapshot,
                    physicalRouteVerified: physicalRouteVerified)
            }
            if snapshot.status == .connecting || (snapshot.status == .live && artifactCallID != snapshot.callID) {
                committedArtifacts.removeAll(); artifactCallID = snapshot.callID
            }
        case .transcript(let transcript):
            let snapshot = await controller.snapshot()
            if let scope = snapshot.scope, let request = try? context(scope) {
                do {
                    let artifact = committedArtifacts.admission(for: transcript, scope: scope)
                    try chat.voiceCallPublishTranscript(transcript, scope: scope, context: request, admittedArtifact: artifact)
                    startPump(scope)
                } catch { await controller.persistenceFailed() }
            }
        case .typedRejected(let messageID):
            let snapshot = await controller.snapshot()
            if let scope = snapshot.scope, let request = try? context(scope) {
                try? chat.voiceCallRejectTyped(messageID: messageID, scope: scope, context: request)
            }
        default: break
        }
        await downstream(event)
    }
    private func startPump(_ scope: NativeVoiceCallScope) {
        guard pumpTask == nil else { pumpDirty = true; return }
        pumpDirty = false
        pumpTask = Task { [weak self] in
            guard let self else { return }
            defer {
                pumpTask = nil
                if pumpDirty, current(scope) { pumpDirty = false; startPump(scope) }
            }
            do {
                while current(scope) {
                    let frames = try await outbox.pendingFrames(scope: scope)
                    if frames.isEmpty { return }
                    for frame in frames {
                        var accepted = false
                        for attempt in 0..<3 {
                            do {
                                let response = try await request(scope: scope, frame: frame, response: "call_message_confirmed")
                                var ack = response; ack["type"] = .string("call_message_confirmed")
                                guard try await outbox.acknowledge(scope: scope, frame: ack)
                                else { throw NativeVoiceCallError.persistenceFailed }
                                accepted = true
                                break
                            } catch {
                                guard !Task.isCancelled, current(scope) else { throw CancellationError() }
                                if attempt < 2 { try await Task.sleep(for: .milliseconds(250 * (attempt + 1))) }
                            }
                        }
                        guard accepted else { throw NativeVoiceCallError.persistenceFailed }
                    }
                }
            } catch {
                // Retain exact ciphertext and end visibly after bounded retries;
                // no ordinary inference or provider reconnect is dispatched.
                pumpDirty = false
                if !Task.isCancelled, current(scope) { await controller.persistenceFailed() }
            }
        }
    }
    func bindTools(to coordinator: WatchVoiceCallToolCoordinator, memory: WatchVoiceCallMemoryPermission) {
        coordinator.bind(artifacts: { [weak self] scope, callID, frame, validate in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await commitArtifact(scope: scope, callID: callID, frame: frame, validate: validate)
        }, memory: { [weak self, weak memory] scope, callID, frame, validate in
            guard let self, let memory else { throw NativeVoiceCallError.scopeChanged }
            return try await memory.request(scope: scope, callID: callID, frame: frame,
                context: toolRequestContext(scope: scope), validate: validate)
        }, respond: { [weak self] frame in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            try await controller.sendToolResponse(frame)
        }, hangup: { [weak self] in await self?.controller.hangup() },
           invalidateMemory: { [weak memory] in memory?.invalidate() })
    }
    /// Tool adapters use this exact authenticated owner/key generation; they
    /// never construct a scope from a current navigation selection.
    func toolRequestContext(scope: NativeVoiceCallScope) throws -> WatchChatRequestContext {
        try context(scope)
    }
    /// Persist through the existing encrypted embed path, then associate only
    /// the broker-issued original assistant/user/function tuple. A processing
    /// update has no committed reference and cannot mint a transcript.
    func commitArtifact(scope: NativeVoiceCallScope, callID: String, frame: NativeVoiceCallFrame,
                        validate: @escaping NativeVoiceCallToolContinuation.Validation) async throws -> NativeVoiceCallArtifactDisposition {
        guard let chat else { throw NativeVoiceCallError.scopeChanged }
        try await validate()
        let request = try context(scope)
        guard frame["call_id"]?.string == callID else { throw NativeVoiceCallError.invalidResponse }
        let admission = try chat.voiceCallAdmitArtifact(frame: frame, scope: scope, context: request)
        guard let commit = try await chat.voiceCallPersistArtifact(admission, context: request) else { return .presented }
        try await validate(); _ = try context(scope)
        // Install only a durable token, before association publishes reentrantly.
        // Processing B cannot revoke committed A on their shared assistant row.
        try committedArtifacts.record(commit)
        try await associateCommittedArtifact(scope: scope, callID: commit.admission.callID,
            functionCallID: commit.admission.functionCallID, assistantMessageID: commit.admission.assistantMessageID,
            userMessageID: commit.admission.userMessageID, reference: commit.reference)
        try await validate()
        return .presented
    }
    /// Normal hangup retains the controller's issued origin. Replacement/owner
    /// loss revokes it. Completion waits for exact canonical outbox receipts.
    func associateCommittedArtifact(scope: NativeVoiceCallScope, callID: String, functionCallID: String,
        assistantMessageID: String, userMessageID: String, reference: NativeVoiceCallFrame
    ) async throws {
        _ = try context(scope)
        try await controller.associateCommittedArtifact(scope: scope, callID: callID, functionCallID: functionCallID,
            assistantMessageID: assistantMessageID, userMessageID: userMessageID, reference: reference)
        _ = try context(scope)
        startPump(scope); await pumpTask?.value
        _ = try context(scope)
        guard try await outbox.pendingFrames(scope: scope).isEmpty else { throw NativeVoiceCallError.persistenceFailed }
    }
    func retryPersistence() async {
        let state = await controller.snapshot()
        if let scope = state.scope, current(scope) { startPump(scope) }
    }
    func stop() async {
        guard !stopped else { return }
        stopped = true
        storageLease.revoke()
        pumpDirty = false
        let oldPump = pumpTask; oldPump?.cancel(); pumpTask = nil
        let releasedProjection = releaseProjection()
        if releasedProjection, evaluationLease == nil { await chat?.callActions.invalidate() }
        else if releasedProjection { chat?.callActions.update(.init(phase: .unavailable, physicalRouteVerified: false)) }
        await controller.invalidateScope()
        await audio.stop()
        evaluationLease?.revoke()
        _ = await oldPump?.value
        contexts.removeAll(); preparedChats.removeAll(); metadataByChat.removeAll(); committedArtifacts.removeAll()
        chat = nil
    }
}

private struct NativeVoiceCallWatchCryptography: NativeVoiceCallCryptography {
    let encryptBody: @MainActor @Sendable (String, NativeVoiceCallScope) async throws -> String
    let decryptBody: @MainActor @Sendable (String, NativeVoiceCallScope) async throws -> String
    init(encrypt: @escaping @MainActor @Sendable (String, NativeVoiceCallScope) async throws -> String,
         decrypt: @escaping @MainActor @Sendable (String, NativeVoiceCallScope) async throws -> String) {
        encryptBody = encrypt; decryptBody = decrypt
    }
    func encrypt(_ text: String, scope: NativeVoiceCallScope) async throws -> String { try await encryptBody(text, scope) }
    func decrypt(_ ciphertext: String, scope: NativeVoiceCallScope) async throws -> String { try await decryptBody(ciphertext, scope) }
}
#endif
