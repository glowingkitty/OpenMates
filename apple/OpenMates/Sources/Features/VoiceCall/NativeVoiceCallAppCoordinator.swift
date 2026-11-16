// Web sources: services/voiceCall.ts, voiceCallMessages.ts, voiceCallPrivacy.ts.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.typed-input, video-call.chat.fixed-binding,
// video-call.lifecycle.recovery-and-billing, video-call.privacy.first-call-warning,
// video-call.chat.skill-integration, video-call.privacy, video-call.video.input-and-output,
// video-call.video.apple-screen-share, video-call.apple.live-activity,
// video-call.audio.confirmation-sounds, video-call.chat.activity-status
#if !os(watchOS)
import AVFoundation
import Combine
import Foundation

/// Root snapshots the full original composer state, including attachments, in
/// memory. Acceptance/restoration must compare this identity AND revision before
/// editing its current draft. A returned wire UUID alone never clears a draft.
struct NativeVoiceCallDraftTicket: Identifiable, Equatable, Sendable {
    let id: UUID
    let revision: UInt64
    let scope: NativeVoiceCallScope
    let text: String
    let originalComposerState: Data
}

@MainActor
final class NativeVoiceCallAppCoordinator: ObservableObject {
    @Published private(set) var state = NativeVoiceCallSnapshot()
    @Published private(set) var consentRequestID: UUID?
    @Published private(set) var integrationError: NativeVoiceCallError?
    @Published private(set) var recoverableDrafts: [NativeVoiceCallDraftTicket] = []
    /// Camera of the running call; stopped on hangup, owner invalidation and call end.
    let camera: NativeVoiceCallCameraModel
    /// Generated images/videos of this call's assistant answers (video-call.video.generated-media-stage).
    let media = NativeVoiceCallMediaModel()
    /// User turn ids of the running call; assistant answers to them feed the media stage.
    private var callTurnIDs: Set<String> = []
    #if os(iOS)
    /// Latest frame of the iOS broadcast extension while the user shares the screen.
    let screenShare = NativeVoiceCallScreenShareReader()
    private let liveActivity = NativeVoiceCallLiveActivity()
    private var liveActivityKey: String?
    private var screenShareSink: AnyCancellable?
    /// True after `camera_state` on was sent for the screen (camera off meanwhile).
    private var screenStateSent = false
    private var lastScreenFrameAt: UInt64?
    #endif
    /// Real audio meter data only. Empty means the audio adapter supplies no
    /// meter; the controls then render a static activity glyph, not fake speech.
    @Published private(set) var meterLevels: [Float] = []
    private let driver: any NativeVoiceCallAppDriving
    private let cuePlayer: any NativeVoiceCallCuePlaying
    private var cuePlan = NativeVoiceCallCuePlan()
    private let accepted: @MainActor (NativeVoiceCallDraftTicket, String) -> Void
    private let restore: @MainActor (NativeVoiceCallDraftTicket) -> Bool
    private let artifacts: @MainActor @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame) async throws -> NativeVoiceCallArtifactDisposition
    private let usage: @MainActor @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame) async -> Void
    private var consentContinuation: CheckedContinuation<Bool, Never>?
    private var pending: [String: NativeVoiceCallDraftTicket] = [:]
    private var submitting: NativeVoiceCallDraftTicket?
    private var earlyAccepted: [String: NativeVoiceCallTranscript] = [:]
    private var earlyRejected: Set<String> = []
    private var recovered: Set<String> = []
    private var generation = UUID()
    private var ownerGeneration = UUID()
    private var ticker: Task<Void, Never>?
    private var starting = false
    private lazy var tools = NativeVoiceCallToolContinuation(handler: { [weak self] scope, callID, frame, _ in
        guard let self else { throw NativeVoiceCallError.scopeChanged }
        return try await artifacts(scope, callID, frame)
    }, respond: { [weak self] response in
        guard let self else { throw NativeVoiceCallError.scopeChanged }
        try await driver.respondToTool(response)
    }, fail: { [weak self] error in self?.integrationError = error }, hangup: { [weak self] in
        await self?.driver.hangup()
    })

    init(driver: any NativeVoiceCallAppDriving,
         accepted: @escaping @MainActor (NativeVoiceCallDraftTicket, String) -> Void,
         restore: @escaping @MainActor (NativeVoiceCallDraftTicket) -> Bool,
         artifacts: @escaping @MainActor @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame) async throws -> NativeVoiceCallArtifactDisposition,
         usage: @escaping @MainActor @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame) async -> Void,
         cuePlayer: any NativeVoiceCallCuePlaying = NativeVoiceCallCuePlayer()) {
        self.cuePlayer = cuePlayer
        camera = NativeVoiceCallCameraModel(
            sendState: { [weak driver] enabled in await driver?.sendCameraState(enabled) },
            sendFrame: { [weak driver] frame in await driver?.sendCameraFrame(frame) })
        self.driver = driver; self.accepted = accepted; self.restore = restore
        self.artifacts = artifacts; self.usage = usage
        media.expand = { [weak camera = self.camera] in camera?.setStageExpanded(true) }
        camera.keepsStageExpanded = { [weak media = self.media] in media?.displayed != nil }
        driver.bind(consent: { [weak self] in await self?.requestConsent() ?? false },
                    event: { [weak self] event in await self?.receive(event) })
        driver.bindMeter { [weak self] levels in
            guard let self, let scope = self.state.scope, let callID = self.state.callID else { return }
            self.updateMeter(levels, scope: scope, callID: callID)
        }
        #if os(iOS)
        NativeVoiceCallLiveActivityHangUp.shared.handler = { [weak self] callID in
            guard let self, self.state.callID == callID else { return }
            await self.hangup()
        }
        screenShareSink = screenShare.$latestFrame.combineLatest(screenShare.$isBroadcasting, camera.$enabled)
            .sink { [weak self] _, _, _ in
                // @Published fires before the new value is stored; read it on the next turn.
                Task { @MainActor [weak self] in await self?.forwardScreen() }
            }
        #endif
    }
    var isActive: Bool { starting || state.status == .connecting || state.status == .live }
    var boundChatID: String? { state.scope?.chatID }
    /// Web `voiceCallActivityActive`: only server-confirmed idle (input and
    /// processing) dims the counter. Policy lives in the core call clock.
    var activityActive: Bool { !state.activityDimmed }
    var formattedDuration: String {
        let seconds = Int(max(0, min(state.activeSeconds, 99 * 3600)))
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }
    func start(_ destination: NativeVoiceCallAppDestination) async {
        guard !isActive, submitting == nil else { return }
        starting = true; integrationError = nil
        generation = UUID(); earlyAccepted.removeAll(); earlyRejected.removeAll()
        recovered = Set(recoverableDrafts.map { "\($0.id):\($0.revision)" })
        defer { starting = false }
        do { try await driver.start(destination) }
        catch { integrationError = error as? NativeVoiceCallError ?? .callUnavailable; finishDrafts() }
    }
    private func requestConsent() async -> Bool {
        guard consentContinuation == nil else { return false }
        let id = UUID(); consentRequestID = id
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                // Cancellation may arrive before installing the continuation.
                guard !Task.isCancelled, consentRequestID == id else { continuation.resume(returning: false); return }
                consentContinuation = continuation
            }
        } onCancel: { [weak self] in Task { @MainActor [weak self] in self?.decideConsent(id: id, accepted: false) } }
    }
    func decideConsent(id: UUID, accepted: Bool) {
        guard consentRequestID == id else { return }
        consentRequestID = nil
        let continuation = consentContinuation; consentContinuation = nil
        continuation?.resume(returning: accepted)
        // AppleEnvironment persists the actual profile acknowledgement next;
        // choosing Continue does not itself authorize microphone capture.
    }
    func send(_ ticket: NativeVoiceCallDraftTicket) async throws {
        guard state.status == .live, ticket.scope == state.scope, submitting == nil, pending.count < 32,
              !pending.values.contains(where: { $0.id == ticket.id && $0.revision == ticket.revision })
        else { throw NativeVoiceCallError.invalidState }
        recovered.remove("\(ticket.id):\(ticket.revision)")
        submitting = ticket
        let admittedGeneration = generation
        let admittedOwner = ownerGeneration
        do {
            let messageID = try await driver.sendText(ticket.text)
            submitting = nil
            guard ownerGeneration == admittedOwner, UUID(uuidString: messageID) != nil else {
                retainForRecovery(ticket); throw NativeVoiceCallError.scopeChanged
            }
            if let transcript = earlyAccepted.removeValue(forKey: messageID) {
                guard transcript.text == ticket.text else { retainForRecovery(ticket); throw NativeVoiceCallError.invalidResponse }
                accepted(ticket, messageID); return
            }
            guard generation == admittedGeneration, state.status == .live else {
                retainForRecovery(ticket); throw NativeVoiceCallError.connectionLost
            }
            if earlyRejected.remove(messageID) != nil { retainForRecovery(ticket); throw NativeVoiceCallError.textRejected }
            pending[messageID] = ticket
        } catch { submitting = nil; retainForRecovery(ticket); throw error }
    }
    private func retainForRecovery(_ ticket: NativeVoiceCallDraftTicket) {
        let identity = "\(ticket.id):\(ticket.revision)"
        guard recovered.insert(identity).inserted else { return }
        if !restore(ticket) { recoverableDrafts.append(ticket) }
    }
    func retryRestore(_ id: UUID) {
        guard let ticket = recoverableDrafts.first(where: { $0.id == id }), restore(ticket) else { return }
        recoverableDrafts.removeAll { $0.id == ticket.id && $0.revision == ticket.revision }
    }
    private func finishDrafts() {
        generation = UUID()
        for ticket in pending.values { retainForRecovery(ticket) }; pending.removeAll()
        // A final echo can arrive before sendText returns. Keep its UUID until
        // that suspended submission resolves, even if the call then ends.
        if submitting == nil { earlyAccepted.removeAll(); earlyRejected.removeAll() }
    }
    func setMuted(_ muted: Bool) async { await driver.setMuted(muted) }
    func dismissError() {
        guard !isActive else { return }
        integrationError = nil; state.error = nil; state.status = .ended
    }
    func hangup() async {
        if let id = consentRequestID { decideConsent(id: id, accepted: false) }
        camera.shutdown()
        endCallMedia()
        await endPlatformCallSurfaces()
        await driver.hangup()
    }
    /// Root calls before logout/profile/team/key changes. Navigation does not.
    func invalidateOwner() async {
        ownerGeneration = UUID()
        if let id = consentRequestID { decideConsent(id: id, accepted: false) }
        tools.invalidateOwner(); ticker?.cancel(); ticker = nil
        camera.shutdown()
        endCallMedia()
        await endPlatformCallSurfaces()
        await driver.invalidate(); finishDrafts(); meterLevels = []
    }
    /// The bound chat's window reports its messages and decrypted embeds; answers to this
    /// call's turns name the candidate artifacts, newest first (web refreshCallMedia).
    func considerChatMedia(chatID: String, messages: [Message], embeds: [String: EmbedRecord]) {
        guard state.status == .live, state.scope?.chatID == chatID, !callTurnIDs.isEmpty else { return }
        var candidates: [String] = []
        for message in messages.reversed() where message.role == .assistant {
            guard let turn = message.userMessageId, callTurnIDs.contains(turn) else { continue }
            for ref in (message.embedRefs ?? []).reversed() where !candidates.contains(ref.id) { candidates.append(ref.id) }
        }
        media.update(candidates: candidates, embeds: embeds)
    }

    private func endCallMedia() {
        media.reset()
        callTurnIDs = []
    }

    func updateMeter(_ levels: [Float], scope: NativeVoiceCallScope, callID: String) {
        guard state.status == .live, state.scope == scope, state.callID == callID else { return }
        meterLevels = Array(levels.suffix(48)).map { $0.isFinite ? min(1, max(0, $0)) : 0 }
    }
    private func receive(_ event: NativeVoiceCallEvent) async {
        switch event {
        case .state(let snapshot):
            if let cue = cuePlan.cue(for: snapshot) { cuePlayer.play(cue) }
            state = snapshot
            tools.update(snapshot)
            if snapshot.status == .live { startTicker() }
            else { ticker?.cancel(); ticker = nil; meterLevels = [] }
            if snapshot.status == .ended || snapshot.status == .failed {
                finishDrafts()
                camera.shutdown()
                endCallMedia()
            }
            await updatePlatformCallSurfaces(snapshot)
        case .transcript(let transcript):
            guard transcript.final, transcript.role == .user,
                  transcript.callID == state.callID else { return }
            if callTurnIDs.count < 512 { callTurnIDs.insert(transcript.messageID) }
            if let ticket = pending.removeValue(forKey: transcript.messageID) {
                guard ticket.text == transcript.text else { retainForRecovery(ticket); integrationError = .invalidResponse; return }
                accepted(ticket, transcript.messageID)
            } else if submitting != nil, earlyAccepted.count < 32 { earlyAccepted[transcript.messageID] = transcript }
        case .typedRejected(let messageID):
            if let ticket = pending.removeValue(forKey: messageID) { retainForRecovery(ticket) }
            else if submitting != nil, earlyRejected.count < 32 { earlyRejected.insert(messageID) }
        case .tool(let frame):
            await tools.receive(frame)
        case .usage(let frame):
            guard let scope = state.scope, let callID = state.callID, state.status == .live,
                  frame["call_id"] == nil || frame["call_id"]?.string == callID else { return }
            // The pinned broker usage frame omits call_id; bind to this exact
            // controller's current transport identity before crossing to root.
            await usage(scope, callID, frame)
        }
    }
    /// iOS Live Activity and screen-share reader follow the call (video-call.apple.live-activity,
    /// video-call.video.apple-screen-share); other platforms have neither.
    private func updatePlatformCallSurfaces(_ snapshot: NativeVoiceCallSnapshot) async {
        #if os(iOS)
        switch snapshot.status {
        case .connecting, .live:
            guard let callID = snapshot.callID else { return }
            let key = callID + (snapshot.status == .live ? ":live" : ":connecting")
            if liveActivityKey != key {
                liveActivityKey = key
                await liveActivity.start(callID: callID, mateName: "OpenMates", live: snapshot.status == .live)
            }
            if snapshot.status == .live { screenShare.start() }
        case .idle, .ended, .failed:
            await endPlatformCallSurfaces()
        }
        #endif
    }

    private func endPlatformCallSurfaces() async {
        #if os(iOS)
        liveActivityKey = nil
        screenShare.stop()
        screenStateSent = false
        lastScreenFrameAt = nil
        await liveActivity.end()
        #endif
    }

    #if os(iOS)
    /// Streams broadcast frames like camera frames (at most the extension's 1 Hz). The camera
    /// wins while it is on; the screen resumes visual input when the camera is turned off.
    private func forwardScreen() async {
        guard state.status == .live else { return }
        if camera.enabled || camera.pending { screenStateSent = false; return }
        guard screenShare.isBroadcasting else {
            if screenStateSent { screenStateSent = false; await driver.sendCameraState(false) }
            return
        }
        if !screenStateSent { screenStateSent = true; await driver.sendCameraState(true) }
        guard let frame = screenShare.freshFrame(), frame.capturedAtMilliseconds != lastScreenFrameAt else { return }
        lastScreenFrameAt = frame.capturedAtMilliseconds
        await driver.sendCameraFrame(NativeVoiceCallCameraFrame(
            frameID: UUID().uuidString.lowercased(), jpeg: frame.jpeg, capturedAt: Int64(frame.capturedAtMilliseconds),
            width: 0, height: 0, source: "screen"))
    }
    #endif

    private func startTicker() {
        guard ticker == nil else { return }
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(1)) } catch { return }
                guard let self, state.status == .live else { return }
                let snapshot = await driver.snapshot()
                guard snapshot.scope == state.scope, snapshot.callID == state.callID else { return }
                state = snapshot
            }
        }
    }
}

/// Confirmation cues (web `voiceCallCues.ts`): one per real transition. Manual mute is
/// the only `muted` source; automatic idle uses `inputIdle`, which never sounds.
enum NativeVoiceCallCue: Sendable { case connected, muted, unmuted, ended }

struct NativeVoiceCallCuePlan {
    private var liveCallID: String?
    private var muted = false
    /// Failed or never-connected attempts return nil and invent no sound.
    mutating func cue(for snapshot: NativeVoiceCallSnapshot) -> NativeVoiceCallCue? {
        switch snapshot.status {
        case .live:
            guard let id = snapshot.callID else { return nil }
            if liveCallID != id { liveCallID = id; muted = snapshot.muted; return .connected }
            guard snapshot.muted != muted else { return nil }
            muted = snapshot.muted
            return muted ? .muted : .unmuted
        case .ended:
            defer { liveCallID = nil; muted = false }
            return liveCallID == nil ? nil : .ended
        case .failed, .idle:
            liveCallID = nil; muted = false
            return nil
        case .connecting:
            return nil
        }
    }
}

@MainActor
protocol NativeVoiceCallCuePlaying: AnyObject { func play(_ cue: NativeVoiceCallCue) }

/// Same notes and 0.035 peak as web. Sine tones render into one local buffer on a
/// short-lived engine that shares the call's audio session (never configures it)
/// and is torn down when the cue ends; it never touches call PCM or playback.
@MainActor
final class NativeVoiceCallCuePlayer: NativeVoiceCallCuePlaying {
    static let notes: [NativeVoiceCallCue: [(frequency: Double, offset: Double, duration: Double)]] = [
        .connected: [(523.25, 0, 0.07), (783.99, 0.09, 0.09)],
        .muted: [(440, 0, 0.06), (329.63, 0.09, 0.06)],
        .unmuted: [(659.25, 0, 0.06), (880, 0.09, 0.06)],
        .ended: [(392, 0, 0.055), (293.66, 0.075, 0.055), (196, 0.15, 0.075)]]
    private var engine: AVAudioEngine?
    private var node: AVAudioPlayerNode?
    private var generation = 0

    func play(_ cue: NativeVoiceCallCue) {
        stop()
        generation += 1
        let token = generation
        let rate = 44_100.0
        let notes = Self.notes[cue] ?? []
        let total = (notes.map { $0.offset + $0.duration }.max() ?? 0) + 0.02
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(total * rate)),
              let samples = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = buffer.frameCapacity
        for i in 0..<Int(buffer.frameLength) { samples[i] = 0 }
        for note in notes {
            let start = Int(note.offset * rate), count = Int(note.duration * rate)
            let ramp = Int(0.012 * rate)
            for i in 0..<count where start + i < Int(buffer.frameLength) {
                let edge = min(1, Double(min(i, count - i)) / Double(max(1, ramp)))
                samples[start + i] = Float(0.035 * edge * sin(2 * .pi * note.frequency * Double(i) / rate))
            }
        }
        let engine = AVAudioEngine(), node = AVAudioPlayerNode()
        engine.attach(node)
        engine.connect(node, to: engine.mainMixerNode, format: format)
        do { try engine.start() } catch { return } // Blocked local audio never blocks the call.
        self.engine = engine; self.node = node
        node.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in if self?.generation == token { self?.stop() } }
        }
        node.play()
    }
    private func stop() {
        node?.stop(); engine?.stop(); node = nil; engine = nil
    }
}
#endif
