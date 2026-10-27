// Web sources: services/voiceCall.ts, voiceCallMessages.ts, voiceCallPrivacy.ts.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.typed-input, video-call.chat.fixed-binding,
// video-call.lifecycle.recovery-and-billing, video-call.privacy.first-call-warning,
// video-call.chat.skill-integration, video-call.privacy
#if !os(watchOS)
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
    @Published var minimized = false
    /// Real audio meter data only. Empty means the audio adapter supplies no
    /// meter; the controls then render a static activity glyph, not fake speech.
    @Published private(set) var meterLevels: [Float] = []
    private let driver: any NativeVoiceCallAppDriving
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
         usage: @escaping @MainActor @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame) async -> Void) {
        self.driver = driver; self.accepted = accepted; self.restore = restore
        self.artifacts = artifacts; self.usage = usage
        driver.bind(consent: { [weak self] in await self?.requestConsent() ?? false },
                    event: { [weak self] event in await self?.receive(event) })
    }
    var isActive: Bool { starting || state.status == .connecting || state.status == .live }
    var boundChatID: String? { state.scope?.chatID }
    var formattedDuration: String {
        let seconds = Int(max(0, min(state.activeSeconds, 99 * 3600)))
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }
    func start(_ destination: NativeVoiceCallAppDestination) async {
        guard !isActive, submitting == nil else { return }
        starting = true; integrationError = nil; minimized = false
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
        await driver.hangup()
    }
    /// Root calls before logout/profile/team/key changes. Navigation does not.
    func invalidateOwner() async {
        ownerGeneration = UUID()
        if let id = consentRequestID { decideConsent(id: id, accepted: false) }
        tools.invalidateOwner(); ticker?.cancel(); ticker = nil
        await driver.invalidate(); finishDrafts(); meterLevels = []
    }
    func updateMeter(_ levels: [Float], scope: NativeVoiceCallScope, callID: String) {
        guard state.status == .live, state.scope == scope, state.callID == callID else { return }
        meterLevels = Array(levels.suffix(48)).map { $0.isFinite ? min(1, max(0, $0)) : 0 }
    }
    private func receive(_ event: NativeVoiceCallEvent) async {
        switch event {
        case .state(let snapshot):
            state = snapshot
            tools.update(snapshot)
            if snapshot.status == .live { startTicker() }
            else { ticker?.cancel(); ticker = nil; meterLevels = [] }
            if snapshot.status == .ended || snapshot.status == .failed {
                finishDrafts()
            }
        case .transcript(let transcript):
            guard transcript.final, transcript.role == .user,
                  transcript.callID == state.callID else { return }
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
#endif
