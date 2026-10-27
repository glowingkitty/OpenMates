// Web source: frontend/packages/ui/src/services/voiceCall.ts, voiceCallOwnership.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.typed-input,
// video-call.chat.transcripts, video-call.audio.single-owner,
// video-call.audio.startup-buffer, video-call.audio.automatic-idle,
// video-call.lifecycle.recovery-and-billing, video-call.privacy.first-call-warning,
// video-call.audio.intentional-interruption, video-call.audio.spoken-rich-response,
// video-call.audio.complete-turn-admission, video-call.chat.activity-status, video-call.usage.provider-metering, video-call.chat.skill-integration

import Foundation

actor NativeVoiceCallController {
    typealias Handler = @Sendable (NativeVoiceCallEvent) async -> Void
    typealias TransportFactory = @Sendable () -> any NativeVoiceCallTransport
    private let environment: NativeVoiceCallEnvironment
    private let audio: any NativeVoiceCallAudio
    private let persistence: any NativeVoiceCallPersistence
    private let makeTransport: TransportFactory
    private let event: Handler
    private var state = NativeVoiceCallSnapshot()
    private var generation = UUID()
    private var writer: NativeVoiceCallOrderedWriter?
    private var receiver: Task<Void, Never>?
    private var deadline: Task<Void, Never>?
    private var scopeMonitor: Task<Void, Never>?
    private var startup: [NativeVoiceCallFrame] = []
    private var startupBytes = 0
    private var startupSpentBytes = 0
    private var drainingStartup = false
    private var streamOpen = false
    private var assistantTaskID: String?
    private var assistantMessageID: String?
    private var assistantActive = false
    private var providerProcessing = false
    private var pausedInputs: [NativeVoiceCallFrame] = []
    private var pausedBytes = 0
    private var checkpointID: String?
    private var modelName: String?
    private var mateName: String?
    private var terminalInProgress = false
    private var startInProgress = false
    private var activityUpdatedAt: Date?
    private var submittedTurns = Set<String>()
    private var pendingTyped: [String: (text: String, createdAt: Int)] = [:]
    private struct ArtifactOrigin {
        let assistantID: String
        let userID: String
        let type: String
        let createdAt: Int
    }
    private var issuedArtifacts: [String: ArtifactOrigin] = [:]

    init(environment: NativeVoiceCallEnvironment, audio: any NativeVoiceCallAudio,
         persistence: any NativeVoiceCallPersistence,
         transportFactory: @escaping TransportFactory, eventHandler: @escaping Handler) {
        self.environment = environment; self.audio = audio; self.persistence = persistence
        makeTransport = transportFactory; event = eventHandler
    }

    func snapshot() -> NativeVoiceCallSnapshot {
        if state.status == .live { updateActivity() }
        return state
    }

    private func current(_ token: UUID, _ scope: NativeVoiceCallScope) async -> Bool {
        guard generation == token, state.scope == scope,
              state.status == .connecting || state.status == .live else { return false }
        let ownerCurrent = await environment.isCurrent(scope)
        return ownerCurrent && generation == token && state.scope == scope &&
            (state.status == .connecting || state.status == .live)
    }
    private func requireCurrent(_ token: UUID, _ scope: NativeVoiceCallScope) async throws {
        try Task.checkCancellation()
        guard await current(token, scope) else { throw NativeVoiceCallError.scopeChanged }
    }
    private func publish() async { await event(.state(state)) }

    /// Returns after the start frame is ordered; .live is published only after
    /// strict ready validation. One app-scoped instance is retained across views.
    func start(scope: NativeVoiceCallScope) async throws {
        guard !terminalInProgress, !startInProgress, state.status != .connecting, state.status != .live,
              !scope.accountID.isEmpty, !scope.profileID.isEmpty, !scope.chatID.isEmpty,
              !scope.mateCategory.isEmpty, UUID(uuidString: scope.chatID) != nil else { throw NativeVoiceCallError.invalidState }
        startInProgress = true
        defer { startInProgress = false }
        let token = UUID()
        generation = token
        state = .init(status: .connecting, scope: scope)
        startup.removeAll(); startupBytes = 0; startupSpentBytes = 0
        pausedInputs.removeAll(); pausedBytes = 0; checkpointID = nil
        submittedTurns.removeAll(); pendingTyped.removeAll(); issuedArtifacts.removeAll(); streamOpen = false; drainingStartup = false
        modelName = nil; mateName = nil; activityUpdatedAt = nil
        assistantTaskID = nil; assistantMessageID = nil; assistantActive = false; providerProcessing = false
        await publish()
        do {
            try await requireCurrent(token, scope)
            // Explicit saved-profile acknowledgment BEFORE permission/capture,
            // audio reservation or provider connection. Failed writes abort.
            try await environment.ensureConsent(scope)
            try await requireCurrent(token, scope)
            try await audio.reserve(scope: scope)
            try await requireCurrent(token, scope)
            let sleep = environment.sleep
            deadline = Task { [weak self] in
                do { try await sleep(.seconds(10)) } catch { return }
                await self?.timedOut(token: token)
            }
            scopeMonitor = Task { [weak self] in
                while !Task.isCancelled {
                    do { try await sleep(.milliseconds(250)) } catch { return }
                    guard let self else { return }
                    if !(await self.current(token, scope)) {
                        await self.fail(.scopeChanged, token: token)
                        return
                    }
                }
            }
            try await audio.start(input: { [weak self] pcm in
                await self?.appendPCM(pcm, token: token)
            }, failure: { [weak self] error in await self?.fail(error, token: token) })
            try await requireCurrent(token, scope)
            // Genuine capture now owns the route, with at most ten seconds of
            // memory-only input. Canonical preparation may use the existing
            // Watch socket; no provider socket/start is admitted before it.
            try await environment.prepare(scope)
            try await requireCurrent(token, scope)
            let context = try await environment.context(scope)
            try await requireCurrent(token, scope)
            guard context.fields["mate_category"]?.string == scope.mateCategory
            else { throw NativeVoiceCallError.contextUnavailable }
            let startFrame: NativeVoiceCallFrame = ["type": .string("start"), "chat_id": .string(scope.chatID),
                "startup_audio_allowance_ms": .number(10_000), "context": .object(context.fields)]
            guard try NativeVoiceCallWire.encode(startFrame).utf8.count <= 256_000
            else { throw NativeVoiceCallError.contextTooLarge }
            let auth = try await environment.authentication(scope)
            try await requireCurrent(token, scope)
            let transport = makeTransport()
            let scopeCurrent = environment.isCurrent
            let ordered = NativeVoiceCallOrderedWriter(transport: transport, isCurrent: { await scopeCurrent(scope) })
            writer = ordered
            try await transport.connect(auth.request())
            try await requireCurrent(token, scope)
            try await ordered.send(startFrame)
            try await requireCurrent(token, scope)
            receiver = Task { [weak self] in
                do {
                    while !Task.isCancelled {
                        let text = try await transport.receive()
                        try Task.checkCancellation()
                        guard let self else { return }
                        try await self.receive(text, token: token)
                    }
                } catch is CancellationError { }
                catch { await self?.fail((error as? NativeVoiceCallError) ?? .connectionLost, token: token) }
            }
        } catch {
            let failure = (error as? NativeVoiceCallError) ?? .callUnavailable
            if generation != token {
                // A permission/audio-reservation suspension can complete after
                // hangup. New starts remain fenced until this cleanup returns.
                await audio.stop()
            } else { await fail(failure, token: token) }
            throw failure
        }
    }

    private func timedOut(token: UUID) async {
        guard token == generation, state.status == .connecting else { return }
        await fail(.startupTimedOut, token: token)
    }
    private func fail(_ error: NativeVoiceCallError, token: UUID) async {
        guard generation == token else { return }
        await finish(error: error)
    }

    private func appendPCM(_ pcm: Data, token: UUID) async {
        guard let scope = state.scope, await current(token, scope), !state.muted, !state.inputIdle else { return }
        do {
            let frame = try NativeVoiceCallWire.audio(pcm)
            if state.status == .connecting || drainingStartup {
                guard startupSpentBytes + pcm.count <= NativeVoiceCallWire.startupByteLimit else {
                    throw NativeVoiceCallError.audioQueueFull
                }
                startup.append(frame); startupBytes += pcm.count; startupSpentBytes += pcm.count
                streamOpen = true
                return
            }
            guard state.status == .live else { return }
            streamOpen = true
            try await input(frame, token: token, scope: scope)
        } catch { await fail((error as? NativeVoiceCallError) ?? .connectionLost, token: token) }
    }

    /// Only a verified/warmed detector may assert idle. Detector failure must
    /// resume continuous streaming and disclose listening via billing_activity.
    func setVerifiedInputIdle(_ idle: Bool) async {
        guard state.status == .connecting || state.status == .live, idle != state.inputIdle else { return }
        state.inputIdle = idle
        await updateMicrophoneGate()
    }
    func setMuted(_ muted: Bool) async {
        guard state.status == .connecting || state.status == .live, muted != state.muted else { return }
        state.muted = muted
        if muted { state.inputIdle = false }
        await updateMicrophoneGate()
    }
    private func updateMicrophoneGate() async {
        guard let scope = state.scope else { return }
        let token = generation
        let enabled = !state.muted && !state.inputIdle
        // Queue the end boundary before suspending on the hardware gate. A
        // rapid unmute cannot place a new PCM packet ahead of this end marker.
        if !enabled && streamOpen {
            streamOpen = false
            let marker: NativeVoiceCallFrame = ["type": .string("audio_stream_end")]
            do {
                if state.status == .connecting || drainingStartup { startup.append(marker) }
                else { try await input(marker, token: token, scope: scope) }
            } catch { await fail(.connectionLost, token: token); return }
        }
        await audio.setMicrophoneEnabled(!state.muted)
        await audio.setInputIdle(state.inputIdle)
        guard await current(token, scope) else { await fail(.scopeChanged, token: token); return }
        // Re-apply the latest state after a rapid mute/idle transition.
        await audio.setMicrophoneEnabled(!state.muted)
        await audio.setInputIdle(state.inputIdle)
        guard await current(token, scope) else { await fail(.scopeChanged, token: token); return }
        await publish()
    }

    /// The returned UUIDv7 is retained by the composer until its matching final
    /// user echo after canonical ordinary encrypted-send admission.
    func sendText(_ text: String) async throws -> String {
        guard state.status == .live, let scope = state.scope, let callID = state.callID,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.utf16.count <= 8_000,
              pendingTyped.count < 32 else { throw NativeVoiceCallError.invalidState }
        let token = generation
        try await requireCurrent(token, scope)
        let id = NativeVoiceCallMessageID.make(now: environment.now())
        let created = Int(environment.now().timeIntervalSince1970)
        // Reserve immediately across persistence await to enforce the bound.
        pendingTyped[id] = (text, created)
        do {
            try await persistence.stageTyped(scope: scope, callID: callID, messageID: id, text: text, createdAt: created)
            try await requireCurrent(token, scope)
            try await input(["type": .string("text_input"), "message_id": .string(id),
                "text": .string(text), "created_at": .number(Double(created))], token: token, scope: scope)
            return id
        } catch {
            if generation == token { await fail((error as? NativeVoiceCallError) ?? .persistenceFailed, token: token) }
            throw error
        }
    }

    /// Tools return only to the same live broker, with initiating IDs intact.
    /// Caller must perform the existing permission/focus/action flow first.
    func sendToolResponse(_ frame: NativeVoiceCallFrame) async throws {
        guard state.status == .live, let scope = state.scope, let callID = state.callID,
              frame["call_id"]?.string == callID, frame["request_id"]?.string != nil,
              frame["function_call_id"]?.string != nil, frame["approved"]?.bool != nil,
              frame["type"]?.string == "voice_memory_response" else { throw NativeVoiceCallError.invalidState }
        let token = generation
        try await requireCurrent(token, scope)
        guard let writer else { throw NativeVoiceCallError.connectionLost }
        try await writer.send(frame)
        try await requireCurrent(token, scope)
    }

    /// Call only after the existing shared embed path confirms genuine durable
    /// encrypted parent persistence. Issued broker identity is checked separately;
    /// a merely parsed reference or volatile processing card grants no authority.
    func associateCommittedArtifact(scope: NativeVoiceCallScope, callID: String, functionCallID: String,
                                    assistantMessageID: String, userMessageID: String,
                                    reference: NativeVoiceCallFrame) async throws {
        let parsed = try NativeVoiceCallArtifactReference(validating: reference)
        let key = functionCallID + "\u{0}" + parsed.embedID
        guard state.scope == scope, state.callID == callID,
              let origin = issuedArtifacts[key], origin.assistantID == assistantMessageID,
              origin.userID == userMessageID, origin.type == parsed.type,
              let artifacts = persistence as? any NativeVoiceCallArtifactPersistence,
              await environment.isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        guard state.scope == scope, state.callID == callID else { throw NativeVoiceCallError.scopeChanged }
        let value = NativeVoiceCallArtifactAssociation(callID: callID, assistantMessageID: assistantMessageID,
            userMessageID: userMessageID, reference: parsed, createdAt: origin.createdAt,
            modelName: modelName, mateCategory: scope.mateCategory, mateName: mateName)
        let published = try await artifacts.associateArtifact(scope: scope, value: value)
        // A result admitted before hangup may still finish its original durable
        // association. A replacement call must never publish it as its response.
        guard state.scope == scope, state.callID == callID,
              await environment.isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
        await event(.transcript(published))
    }

    private func rememberArtifact(_ frame: NativeVoiceCallFrame, scope: NativeVoiceCallScope) throws {
        guard let function = frame["function_call_id"]?.string,
              let assistant = frame["assistant_message_id"]?.string,
              let user = frame["user_message_id"]?.string,
              [function, assistant, user].allSatisfy({ !$0.isEmpty && $0.utf8.count <= 128 && !$0.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) }),
              let payload = frame["payload"]?.object,
              payload["chat_id"] == nil || payload["chat_id"]?.string == scope.chatID,
              payload["message_id"] == nil || payload["message_id"]?.string == assistant else { throw NativeVoiceCallError.invalidResponse }
        guard let reference = try NativeVoiceCallArtifactReference.fromPayload(payload) else { return }
        let key = function + "\u{0}" + reference.embedID
        if let old = issuedArtifacts[key] {
            guard old.assistantID == assistant, old.userID == user, old.type == reference.type else { throw NativeVoiceCallError.invalidResponse }
            return
        }
        guard issuedArtifacts.count < 128 else { throw NativeVoiceCallError.contextTooLarge }
        let created = frame["created_at"]?.number
        let timestamp = created.flatMap { value -> Int? in
            guard value.isFinite, value > 0, value <= 9_007_199_254_740_991, value.rounded(.down) == value else { return nil }
            return Int(value)
        } ?? Int(environment.now().timeIntervalSince1970)
        issuedArtifacts[key] = ArtifactOrigin(assistantID: assistant, userID: user, type: reference.type, createdAt: timestamp)
    }

    private func input(_ frame: NativeVoiceCallFrame, token: UUID, scope: NativeVoiceCallScope) async throws {
        // Queue in controller arrival order before any suspension. The writer
        // revalidates authenticated scope immediately before the actual write.
        guard token == generation, state.scope == scope, state.status == .live
        else { throw NativeVoiceCallError.scopeChanged }
        if checkpointID != nil {
            let bytes = try NativeVoiceCallWire.encode(frame).utf8.count
            guard pausedBytes + bytes <= 512 * 1_024 else { throw NativeVoiceCallError.audioQueueFull }
            pausedInputs.append(frame); pausedBytes += bytes
        } else {
            guard let writer else { throw NativeVoiceCallError.connectionLost }
            try await writer.send(frame)
            try await requireCurrent(token, scope)
        }
    }

    private func receive(_ text: String, token: UUID) async throws {
        guard let scope = state.scope else { return }
        try await requireCurrent(token, scope)
        let frame = try NativeVoiceCallWire.decode(text)
        let kind = frame["type"]?.string ?? ""
        if let callID = frame["call_id"]?.string, let expected = state.callID, callID != expected { return }
        switch kind {
        case "ready":
            guard state.status == .connecting, let callID = frame["call_id"]?.string, !callID.isEmpty,
                  frame["input_sample_rate"]?.number == 16_000,
                  frame["output_sample_rate"]?.number == 24_000,
                  frame["provider"]?.string == "mistral",
                  frame["model"]?.string == "voxtral-mini-transcribe-realtime-3-0",
                  frame["billing_basis"]?.string == "speech_duration_and_chat_usage",
                  let rate = frame["rates"]?.object?["stt_credits_per_started_minute"]?.number, rate.isFinite, rate > 0,
                  frame["mate_category"]?.string == scope.mateCategory else { throw NativeVoiceCallError.invalidResponse }
            deadline?.cancel(); deadline = nil
            state.callID = callID; state.status = .live
            modelName = frame["model"]?.string; mateName = frame["mate_name"]?.string
            drainingStartup = true
            try await persistence.lifecycle(scope: scope, callID: callID, started: true,
                createdAt: Int(environment.now().timeIntervalSince1970), activeSeconds: 0)
            try await requireCurrent(token, scope)
            while !startup.isEmpty {
                let queued = startup.removeFirst()
                try await input(queued, token: token, scope: scope)
            }
            startupBytes = 0; drainingStartup = false
            await publish()
        case "audio.interrupted":
            // Only server-confirmed intentional interruption reaches this path.
            // Backchannels keep both generation and encrypted speech playing.
            let interruptedID = frame["assistant_message_id"]?.string
            let interruptedTask = frame["assistant_task_id"]?.string
            guard interruptedID == assistantMessageID,
                  interruptedID != nil || (interruptedTask != nil && interruptedTask == assistantTaskID) else { return }
            try await environment.interruptAssistant(scope, interruptedID, interruptedTask)
            try await requireCurrent(token, scope)
        case "transcript":
            guard state.status == .live, let callID = state.callID,
                  frame["call_id"]?.string == callID,
                  let id = frame["message_id"]?.string, !id.isEmpty, id.utf8.count <= 128,
                  let roleText = frame["role"]?.string, let role = NativeVoiceCallTranscript.Role(rawValue: roleText),
                  let text = frame["text"]?.string, text.utf16.count <= 64_000,
                  let final = frame["final"]?.bool,
                  let created = frame["created_at"]?.number, created > 0, created <= 9_007_199_254_740_991, created.rounded(.down) == created
            else { throw NativeVoiceCallError.invalidResponse }
            if let pending = pendingTyped[id] {
                guard role == .user, final, text == pending.text, Int(created) == pending.createdAt
                else { throw NativeVoiceCallError.textRejected }
            }
            let value = NativeVoiceCallTranscript(callID: callID, messageID: id, role: role,
                text: text, final: final, interrupted: frame["interrupted"]?.bool == true,
                userMessageID: frame["user_message_id"]?.string, createdAt: Int(created),
                modelName: role == .assistant ? modelName : nil,
                mateCategory: role == .assistant ? scope.mateCategory : nil,
                mateName: role == .assistant ? mateName : nil)
            // STT drafts are ephemeral. Never persist an assistant spoken-only
            // projection over the authoritative rich assistant message.
            guard role == .user, final, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            guard submittedTurns.insert(id).inserted else { return }
            try await environment.submitTurn(scope, value)
            try await requireCurrent(token, scope)
            pendingTyped.removeValue(forKey: id)
            await event(.transcript(value))
        case "text_input.accepted", "transcript.discarded", "source", "waiting", "progress": break
        case "text_input_rejected":
            guard let id = frame["message_id"]?.string, pendingTyped.removeValue(forKey: id) != nil else { return }
            await event(.typedRejected(messageID: id))
        case "voice_context_pause":
            guard state.status == .live, let id = frame["checkpoint_id"]?.string,
                  checkpointID == nil || checkpointID == id, let writer, let callID = state.callID
            else { throw NativeVoiceCallError.invalidResponse }
            checkpointID = id; state.contextPaused = true
            try await writer.send(["type": .string("voice_context_paused"), "call_id": .string(callID), "checkpoint_id": .string(id)])
            try await requireCurrent(token, scope)
            await publish()
        case "voice_context_resumed":
            guard let id = checkpointID, frame["checkpoint_id"]?.string == id, let writer else { return }
            // Keep queueing during drain so resumed PCM/text cannot overtake.
            while !pausedInputs.isEmpty {
                let queued = pausedInputs.removeFirst()
                try await writer.send(queued)
                try await requireCurrent(token, scope)
            }
            checkpointID = nil; pausedBytes = 0; state.contextPaused = false
            await publish()
        case "voice_compression":
            guard let callID = state.callID, let writer else { throw NativeVoiceCallError.invalidResponse }
            let ack = try await persistence.compression(scope: scope, callID: callID, frame: frame)
            try await requireCurrent(token, scope)
            try await writer.send(ack)
        case "voice_memory", "voice_focus", "voice_embed", "voice_context", "voice_tool_status":
            guard frame["call_id"]?.string == state.callID, state.status == .live else { return }
            if kind == "voice_embed" { try rememberArtifact(frame, scope: scope) }
            await event(.tool(frame))
        case "billing_activity":
            guard state.status == .live, frame["call_id"]?.string == state.callID,
                  frame["input_listening"]?.bool != nil, frame["processing"]?.bool != nil else { return }
            updateActivity()
            state.inputListening = frame["input_listening"]?.bool ?? false
            providerProcessing = frame["processing"]?.bool ?? false
            state.processing = providerProcessing || assistantActive
            activityUpdatedAt = environment.now()
            await publish()
        case "usage": await event(.usage(frame))
        case "voice_compression_started": break
        case "ended": await finish(error: nil)
        case "error":
            let code = frame["code"]?.string
            await finish(error: code == "context_too_large" ? .contextTooLarge : .callUnavailable)
        default: throw NativeVoiceCallError.invalidResponse
        }
    }

    func updateAssistantState(speaking: Bool, generating: Bool = false, messageID: String?, taskID: String? = nil, text: String, language: String? = nil) async {
        guard state.status == .live, let scope = state.scope else { return }
        let token = generation
        updateActivity()
        assistantTaskID = taskID
        assistantMessageID = messageID
        assistantActive = speaking || generating
        state.processing = providerProcessing || assistantActive
        await publish()
        var frame: NativeVoiceCallFrame = ["type": .string("assistant_state"), "speaking": .bool(speaking),
            "generating": .bool(generating),
            "assistant_task_id": taskID.map(NativeVoiceCallJSON.string) ?? .null,
            "assistant_message_id": messageID.map(NativeVoiceCallJSON.string) ?? .null,
            "text": .string(String(text.suffix(4_000)))]
        if let language { frame["language"] = .string(language) }
        do { try await input(frame, token: token, scope: scope) }
        catch { await fail((error as? NativeVoiceCallError) ?? .connectionLost, token: token) }
    }

    private func updateActivity() {
        let now = environment.now()
        if let previous = activityUpdatedAt, state.inputListening || state.processing {
            state.activeSeconds += max(0, now.timeIntervalSince(previous))
        }
        activityUpdatedAt = now
    }
    func hangup() async {
        guard state.status == .connecting || state.status == .live else { return }
        // Teardown has precedence over network delivery; close is deterministic
        // even if the best-effort hangup write cannot complete.
        await finish(error: nil, sendHangup: true)
    }
    func persistenceFailed() async {
        guard state.status == .connecting || state.status == .live else { return }
        await finish(error: .persistenceFailed)
    }
    func invalidateScope() async {
        guard state.status == .connecting || state.status == .live else { return }
        await finish(error: .scopeChanged)
    }
    private func finish(error: NativeVoiceCallError?, sendHangup: Bool = false) async {
        guard !terminalInProgress, state.status == .connecting || state.status == .live else { return }
        terminalInProgress = true
        let scope = state.scope, callID = state.callID
        let oldWriter = writer
        updateActivity()
        let activeSeconds = state.activeSeconds
        // Revoke callbacks before any await. No late PCM/transcript/ready admits.
        generation = UUID(); writer = nil
        let oldReceiver = receiver; receiver = nil
        let oldDeadline = deadline; deadline = nil
        let oldMonitor = scopeMonitor; scopeMonitor = nil
        startup.removeAll(); startupBytes = 0; startupSpentBytes = 0
        pausedInputs.removeAll(); pausedBytes = 0; checkpointID = nil
        drainingStartup = false; streamOpen = false
        state.status = error == nil ? .ended : .failed; state.error = error
        state.inputListening = false; state.processing = false; state.contextPaused = false
        assistantTaskID = nil; assistantMessageID = nil; assistantActive = false; providerProcessing = false
        // Keep unresolved typed ciphertext/drafts. Caller explicitly chooses retry.
        pendingTyped.removeAll()
        await audio.stop()
        if sendHangup, let oldWriter {
            // Race a bounded graceful notice with close; never reconnect.
            let sleep = environment.sleep
            let notice = Task { try? await oldWriter.send(["type": .string("hangup")]) }
            try? await sleep(.milliseconds(250))
            await oldWriter.close()
            notice.cancel()
        } else { await oldWriter?.close() }
        if let scope, let callID, await environment.isCurrent(scope) {
            do {
                try await persistence.lifecycle(scope: scope, callID: callID, started: false,
                    createdAt: Int(environment.now().timeIntervalSince1970), activeSeconds: activeSeconds)
            } catch { if state.error == nil { state.error = .persistenceFailed; state.status = .failed } }
        }
        terminalInProgress = false
        await publish()
        // Cancellation occurs after durable terminal work, including when the
        // current task is the receiver/deadline/monitor initiating this finish.
        oldReceiver?.cancel(); oldDeadline?.cancel(); oldMonitor?.cancel()
    }
}
