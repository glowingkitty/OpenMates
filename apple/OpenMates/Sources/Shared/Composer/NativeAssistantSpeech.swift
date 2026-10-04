// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
import Foundation
import Combine

// Web sources: assistantSpeechPreference.ts, sendersChatMessages.ts and
// assistantSpeechController.ts. Generated provider audio, never OS TTS.
struct AssistantSpeechScope: Hashable, Sendable {
    let accountID: String
    let serverID: String
    let chatID: String
    var sessionID: UUID? = nil
}

struct AssistantSpeechSegment: Decodable, Equatable {
    let segment_id: String?
    let sequence: Int?
    let status: String?
    let generated_asset_id: String?
    var request_sequence: Int? = nil
    var kind: String? = nil
    var audio_url: String? = nil
}
struct AssistantSpeechStatus: Decodable {
    let chat_id: String?
    let message_id: String?
    let status: String?
    let segment_id: String?
    let sequence: Int?
    let generated_asset_id: String?
    var retryable: Bool? = nil
    var request_sequence: Int? = nil
    var kind: String? = nil
    let segments: [AssistantSpeechSegment]?
}

enum AssistantSpeechFailure: LocalizedError {
    case preferenceBusy, invalidAcknowledgement, preferenceChangedElsewhere
    var errorDescription: String? {
        switch self {
        case .preferenceBusy: return "Speech preference is still being saved. Try again."
        case .invalidAcknowledgement: return "Speech preference could not be confirmed. Try again."
        case .preferenceChangedElsewhere: return "Speech preference changed on another device. Try again."
        }
    }
}

@MainActor
final class NativeAssistantSpeech: ObservableObject {
    struct Dependencies {
        // Persistence must encrypt the boolean with this chat's key; see adapter.
        var readPreference: @MainActor (AssistantSpeechScope) async throws -> Bool
        var writePreference: @MainActor (AssistantSpeechScope, Bool) async throws -> Void
        // Resolves provider generated_asset_id, decrypts its embed/media and returns
        // audio bytes. This is NOT a public unauthenticated asset URL assumption.
        var resolveAudio: @MainActor (AssistantSpeechScope, String) async throws -> Data
        // Completes only after playback ends; cancellation must stop the player.
        var play: @MainActor (Data) async throws -> Void
        var stopPlayback: @MainActor () -> Void
        var cancelResponse: @MainActor (AssistantSpeechScope, String) async throws -> Void
        var sleep: @MainActor (UInt64) async throws -> Void = { try await Task.sleep(nanoseconds: $0) }
        var resolveAcknowledgement: @MainActor (AssistantSpeechScope, String) async throws -> Data = { _, _ in throw CocoaError(.fileReadNoSuchFile) }
        var resolvePublicAudio: @MainActor (PublicAssistantSpeechSegment) async throws -> Data = { try await PublicAssistantSpeechMedia.fetch($0) }
        var startPendingCue: @MainActor () -> Void = {}
        var stopPendingCue: @MainActor () -> Void = {}
        var pausePlayback: @MainActor () -> Void = {}
        var resumePlayback: @MainActor () -> Void = {}
        var requestSpeech: @MainActor (AssistantSpeechScope, String, String, [[String: Any]]) async throws -> Void = { _, _, _, _ in throw WebSocketError.notConnected }
        var waveformSamples: @MainActor (Data) -> [Double] = { AssistantSpeechWaveform.samples($0) }
        var canPlay: @MainActor (AssistantSpeechScope) -> Bool = { _ in true }
    }
    @Published private(set) var enabled = false
    @Published private(set) var ready = false
    @Published private(set) var feedback: Bool?
    @Published private(set) var error: String?
    enum PlaybackStatus: String { case idle, waitingForSegment = "waiting_for_segment", playing, paused, completed, failed, stopped }
    @Published private(set) var playbackStatus: PlaybackStatus = .idle
    @Published private(set) var playbackSegments: [AssistantSpeechSegment] = []
    @Published private(set) var activeSequence = 0
    @Published private(set) var waveforms: [String: [Double]] = [:]
    @Published private(set) var waveform: [Double] = []
    @Published private(set) var mateName = "OpenMates"
    @Published private(set) var mateCategory = "default"
    private var paused = false
    private var manual = false
    private var publicContext = false
    private var publicPlayback = false
    private var publicAssets: [String: PublicAssistantSpeechSegment] = [:]
    private var publicAudio: [String: Data] = [:]
    private var awaitingAcceptance = false
    private var responseComplete = false
    private var sequenceOffset = 0
    private var explicitSelection = false
    private var projected: [AssistantSpeechProjection.Part] = []
    private var generationRequested = Set<String>()
    var playerVisible: Bool { messageID != nil && playbackStatus != .idle && playbackStatus != .stopped }
    var canPause: Bool { playbackStatus == .playing || playbackStatus == .waitingForSegment }
    private var responseDrained: Bool {
        if publicPlayback { return responseComplete && played.count == playbackSegments.count }
        let offset = manual ? sequenceOffset : (playbackSegments.contains { $0.kind == "app_use_announcement" } ? 1 : 0)
        return responseComplete && !projected.isEmpty && nextSequence >= projected.count + offset
    }
    var hasPrevious: Bool { playbackSegments.contains { $0.kind != "app_use_announcement" && ($0.sequence ?? -1) >= 0 && ($0.sequence ?? -1) < activeSequence } }
    var hasNext: Bool { playbackSegments.contains { $0.kind != "app_use_announcement" && ($0.sequence ?? -1) > activeSequence } }
    func chapter(for segment: AssistantSpeechSegment?) -> String {
        guard let segment else { return AppStrings.loading }
        if segment.kind == "app_use_announcement" { return LocalizationManager.shared.text("chat.assistant_speech.using_apps") }
        if segment.kind == "acknowledgement" { return LocalizationManager.shared.text("chat.assistant_speech.confirmation") }
        let offset = !manual && playbackSegments.contains(where: { $0.kind == "app_use_announcement" }) ? 1 : 0
        let index = segment.request_sequence ?? ((segment.sequence ?? 0) - offset)
        if let part = projected.first(where: { $0.sequence == index }) { return part.chapter }
        return LocalizationManager.shared.text("chat.assistant_speech.part").replacingOccurrences(of: "{number}", with: String(index + 1))
    }
    var activeSegment: AssistantSpeechSegment? { playbackSegments.first { $0.sequence == activeSequence } }
    private(set) var scope: AssistantSpeechScope?
    private let dependencies: Dependencies
    private var generation = UUID()
    private var preferenceRevision = UUID()
    private var feedbackTask: Task<Void, Never>?
    private var playbackTask: Task<Void, Never>?
    private var playbackGeneration = UUID()
    private var responseGeneration = UUID()
    private var messageID: String?
    private var segments: [String: AssistantSpeechSegment] = [:]
    private var played = Set<String>()
    private var nextSequence = 0
    private enum FailedOperation: Equatable { case load, write(Bool), audio, provider }
    private var failedOperation: FailedOperation?
    var canRetry: Bool {
        guard let failedOperation else { return false }
        if case .provider = failedOperation { return manual }
        return true
    }

    init(dependencies: Dependencies) { self.dependencies = dependencies }

    // Caller supplies nil for incognito, public and unauthenticated contexts.
    // No network or playback is allowed before a supported scoped load succeeds.
    func activate(_ newScope: AssistantSpeechScope?) async {
        if scope == newScope, ready { return }
        reset()
        scope = newScope
        guard let newScope else { return }
        let token = generation
        do {
            let value = try await dependencies.readPreference(newScope)
            guard generation == token, scope == newScope, !Task.isCancelled else { return }
            enabled = value; ready = true
        } catch {
            guard generation == token else { return }
            failedOperation = .load
            self.error = error.localizedDescription
        }
    }

    // Anonymous public playback has no chat-key, preference or socket dependency.
    func activatePublic(_ newScope: AssistantSpeechScope) {
        reset(); scope = newScope; publicContext = true; ready = true
    }
    func playPublicExample(messageID id: String, fixtures: [PublicAssistantSpeechSegment]) async {
        guard publicContext, ready, let scope, dependencies.canPlay(scope), !fixtures.isEmpty,
              fixtures.allSatisfy(\.valid), Set(fixtures.map(\.segmentId)).count == fixtures.count,
              Set(fixtures.map(\.sequence)).count == fixtures.count else { return }
        guard await stopForReplacement(in: scope), publicContext else { return }
        error = nil; failedOperation = nil
        publicPlayback = true; responseComplete = true; messageID = id; paused = false
        publicAssets = Dictionary(uniqueKeysWithValues: fixtures.map { ($0.segmentId, $0) })
        playbackSegments = fixtures.sorted { $0.sequence < $1.sequence }.map {
            .init(segment_id: $0.segmentId, sequence: $0.sequence, status: "ready", generated_asset_id: nil)
        }
        segments = Dictionary(uniqueKeysWithValues: playbackSegments.compactMap { item in item.segment_id.map { ($0, item) } })
        for fixture in fixtures {
            if let waveform = fixture.waveform, !waveform.isEmpty { waveforms[fixture.segmentId] = waveform }
        }
        nextSequence = playbackSegments.first?.sequence ?? 0; activeSequence = nextSequence
        playbackStatus = .waitingForSegment; drain()
    }
    func refreshPreference() async {
        guard ready, !publicContext, let scope else { return }
        let token = generation, revision = preferenceRevision
        do {
            let value = try await dependencies.readPreference(scope)
            guard generation == token, preferenceRevision == revision, ready else { return }
            if value != enabled {
                enabled = value; showFeedback(value)
                if !value { await stop() }
            }
        } catch {
            guard generation == token, preferenceRevision == revision else { return }
            failedOperation = .load
            self.error = error.localizedDescription
        }
    }

    func toggle() async {
        guard ready, !publicContext else { return }
        await setEnabled(!enabled)
    }

    private func setEnabled(_ desired: Bool) async {
        guard let scope else { return }
        let token = generation
        let previous = enabled
        preferenceRevision = UUID()
        enabled = desired; ready = false; showFeedback(desired)
        // Muting is immediate, even if the metadata ACK is slow or fails.
        if !desired { await stop() }
        guard generation == token, self.scope == scope else { return }
        do {
            try await dependencies.writePreference(scope, desired)
            guard generation == token, self.scope == scope else { return }
            ready = true; error = nil; failedOperation = nil
            await refreshPreference()
        } catch {
            guard generation == token else { return }
            enabled = previous; ready = true; showFeedback(previous)
            failedOperation = .write(desired)
            self.error = error.localizedDescription
        }
    }

    func reportPromotionFailure(_ failure: Error) {
        error = failure.localizedDescription; failedOperation = .write(enabled)
    }

    // Merge into the existing preflight `message`, not at the envelope top level.
    // Snapshot only after the scoped preference write has completed.
    func messageFields(for requestedScope: AssistantSpeechScope) -> [String: Any] {
        guard requestedScope == scope, ready, enabled else { return [:] }
        return ["auto_speak_response": true, "assistant_response_source_revision": 1]
    }

    // Bind to the exact outgoing turn's eventual assistant ID. Never allow an
    // unrelated chat's broadcast to commandeer playback on another window.
    func expectResponse(_ id: String, in requestedScope: AssistantSpeechScope) {
        guard requestedScope == scope, enabled else { return }
        responseGeneration = UUID(); playbackGeneration = UUID()
        playbackTask?.cancel(); playbackTask = nil; dependencies.stopPendingCue(); dependencies.stopPlayback()
        messageID = id; segments.removeAll(); played.removeAll(); nextSequence = 0
        activeSequence = 0; paused = false; explicitSelection = false; manual = false; responseComplete = false; sequenceOffset = 0; projected = []; waveform = []; generationRequested.removeAll()
        playbackSegments = []; playbackStatus = .waitingForSegment
        if failedOperation == .audio || failedOperation == .provider { failedOperation = nil; error = nil }
    }

    func receive(_ event: AssistantSpeechStatus, in eventScope: AssistantSpeechScope) {
        guard !publicContext, (enabled || manual), eventScope == scope, event.chat_id == eventScope.chatID,
              event.message_id == messageID else { return }
        if event.status == "error", event.segment_id == nil {
            failProvider(); return
        }
        let incoming = event.segments ?? [AssistantSpeechSegment(segment_id: event.segment_id,
            sequence: event.sequence, status: event.status, generated_asset_id: event.generated_asset_id, request_sequence: event.request_sequence, kind: event.kind)]
        for segment in incoming {
            guard let id = segment.segment_id, let sequence = segment.sequence, (sequence >= 0 || (sequence == -1 && segment.kind == "acknowledgement")) else { continue }
            if segments[id]?.status == "ready", ["queued", "generating", "registered"].contains(segment.status ?? "") { continue }
            // A duplicate sequence cannot randomly replace an already queued
            // provider asset. Provider retries require an explicit manual request.
            if let other = segments.values.first(where: { $0.sequence == sequence }), other.segment_id != id { continue }
            if sequence == -1, segments.isEmpty, playbackTask == nil { nextSequence = -1; activeSequence = -1 }
            // Preserve the accepted source mapping when later worker events omit it.
            var merged = segment
            merged.request_sequence = segment.request_sequence ?? segments[id]?.request_sequence
            merged.kind = segment.kind ?? segments[id]?.kind
            segments[id] = merged
            if ["error", "cancelled", "deleted"].contains(segment.status ?? ""), sequence == nextSequence { failProvider() }
        }
        if manual, awaitingAcceptance, event.status == "accepted", let accepted = event.segments {
            let offset = accepted.compactMap(\.sequence).min() ?? 0
            for item in accepted {
                if let id = item.segment_id, var value = segments[id] {
                    value.request_sequence = item.request_sequence ?? ((item.sequence ?? 0) - offset)
                    segments[id] = value
                }
            }
            if awaitingAcceptance { sequenceOffset = offset; nextSequence = offset; activeSequence = offset }
            awaitingAcceptance = false
        }
        playbackSegments = segments.values.sorted { ($0.sequence ?? 0) < ($1.sequence ?? 0) }
        drain()
    }

    func request(messageID id: String, markdown: String, mateName: String = "OpenMates", mateCategory: String = "default") async {
        guard ready, !publicContext, let scope, dependencies.canPlay(scope) else { return }
        let parts = AssistantSpeechProjection.project(markdown, language: LocalizationManager.shared.currentLanguage.code)
        guard !parts.isEmpty else { return }
        guard await stopForReplacement(in: scope), !publicContext else { return }
        // Manual playback does not change the encrypted auto-speak preference.
        manual = true; responseComplete = true; awaitingAcceptance = true; paused = false; messageID = id; projected = parts
        self.mateName = mateName; self.mateCategory = mateCategory
        activeSequence = 0; nextSequence = 0; playbackStatus = .waitingForSegment
        error = nil; failedOperation = nil
        let token = playbackGeneration
        do { try await dependencies.requestSpeech(scope, id, "request", parts.map(\.wire)) }
        catch {
            guard playbackGeneration == token, messageID == id else { return }
            self.error = "Speech is temporarily unavailable."; failedOperation = .audio; playbackStatus = .failed
        }
    }
    func pause() {
        guard playerVisible else { return }
        paused = true; dependencies.stopPendingCue(); dependencies.pausePlayback(); playbackStatus = .paused
    }
    func play() {
        guard playerVisible else { return }
        paused = false
        if playbackStatus == .failed { retryPlayback() }
        if playbackStatus == .completed { select(sequence: playbackSegments.first?.sequence ?? 0); return }
        if playbackTask != nil { dependencies.resumePlayback(); playbackStatus = .playing }
        else { playbackStatus = .waitingForSegment; drain() }
    }
    func previous() { if let sequence = playbackSegments.last(where: { $0.kind != "app_use_announcement" && ($0.sequence ?? -1) >= 0 && ($0.sequence ?? -1) < activeSequence })?.sequence { select(sequence: sequence) } }
    func next() { if let sequence = playbackSegments.first(where: { $0.kind != "app_use_announcement" && ($0.sequence ?? -1) > activeSequence })?.sequence { select(sequence: sequence) } }
    func select(sequence: Int) {
        guard playerVisible else { return }
        playbackGeneration = UUID(); playbackTask?.cancel(); playbackTask = nil; dependencies.stopPendingCue(); dependencies.stopPlayback()
        paused = false; explicitSelection = true; nextSequence = sequence; activeSequence = sequence; waveform = []
        played = Set(playbackSegments.filter { ($0.sequence ?? 0) < sequence }.compactMap(\.segment_id))
        failedOperation = nil; error = nil; drain()
    }
    private func sourcePart(for item: AssistantSpeechSegment) -> AssistantSpeechProjection.Part? {
        let offset = !manual && playbackSegments.contains { $0.kind == "app_use_announcement" } ? 1 : 0
        let sequence = item.request_sequence ?? ((item.sequence ?? 0) - offset)
        return projected.first { $0.sequence == sequence }
    }
    func prefetchNextChapter() {
        guard !publicContext, !paused, let scope, dependencies.canPlay(scope),
              let item = playbackSegments.first(where: { ($0.sequence ?? -1) > activeSequence }) else { return }
        requestGeneration(for: item)
    }
    private func requestGeneration(for item: AssistantSpeechSegment) {
        guard !publicContext, !paused, let scope, dependencies.canPlay(scope), let messageID,
              item.status == "registered", let id = item.segment_id,
              !generationRequested.contains(id), let part = sourcePart(for: item) else { return }
        generationRequested.insert(id)
        // Chapter selection changes playbackGeneration, but a prefetched chapter
        // still belongs to the same response. Closing/replacing fences dispatch.
        let token = generation, responseToken = responseGeneration
        Task { [weak self] in
            guard let self, generation == token, responseGeneration == responseToken,
                  self.scope == scope, self.messageID == messageID, dependencies.canPlay(scope),
                  !Task.isCancelled else { return }
            do { try await dependencies.requestSpeech(scope, messageID, "generate", [part.wire]) }
            catch {
                guard generation == token, responseGeneration == responseToken,
                      self.scope == scope, self.messageID == messageID, dependencies.canPlay(scope) else { return }
                generationRequested.remove(id)
                // Readiness may have arrived while the transport was suspended.
                guard segments[id]?.status != "ready" else { return }
                segments[id] = .init(segment_id: id, sequence: item.sequence, status: "error", generated_asset_id: nil,
                    request_sequence: item.request_sequence, kind: item.kind)
                playbackSegments = segments.values.sorted { ($0.sequence ?? 0) < ($1.sequence ?? 0) }
                if activeSequence == item.sequence { failProvider() }
            }
        }
    }
    func updateSource(from messages: [Message]) {
        guard !manual, !publicContext, let scope, let messageID,
              let message = messages.first(where: { $0.id == messageID && $0.chatId == scope.chatID && $0.role == .assistant }),
              let content = message.content else { return }
        projected = AssistantSpeechProjection.project(content, language: LocalizationManager.shared.currentLanguage.code)
        mateName = message.senderName ?? "OpenMates"; mateCategory = message.category ?? "default"
        responseComplete = message.isStreaming != true
        if responseDrained, playbackTask == nil, !paused {
            playbackStatus = .completed
        } else {
            // Status can precede decrypted streaming text. Revisit a registered
            // chapter as soon as its canonical safe source becomes available.
            drain()
        }
    }
    func resumePlaybackIfReady() { drain() }

    private func drain() {
        guard (enabled || manual || publicPlayback), !paused, !awaitingAcceptance, failedOperation == nil, playbackTask == nil, let scope,
              dependencies.canPlay(scope), let messageID,
              let item = segments.values.first(where: { $0.sequence == nextSequence }),
              let id = item.segment_id, !played.contains(id) else { return }
        activeSequence = nextSequence
        if ["error", "cancelled", "deleted"].contains(item.status ?? "") { failProvider(); return }
        guard item.status == "ready", item.generated_asset_id != nil || item.audio_url != nil || publicAssets[id] != nil else {
            playbackStatus = .waitingForSegment; waveform = []
            if explicitSelection { dependencies.startPendingCue() }
            requestGeneration(for: item)
            return
        }
        dependencies.stopPendingCue()
        explicitSelection = false
        let token = generation
        let playbackToken = playbackGeneration
        playbackTask = Task { [weak self] in
            guard let self else { return }
            do {
                let bytes: Data
                if let fixture = publicAssets[id] {
                    if let cached = publicAudio[id] { bytes = cached }
                    else {
                        let resolved = try await dependencies.resolvePublicAudio(fixture)
                        try Task.checkCancellation()
                        guard generation == token, playbackGeneration == playbackToken, self.scope == scope, dependencies.canPlay(scope) else { return }
                        if publicAudio.values.reduce(0, { $0 + $1.count }) + resolved.count > 33_554_432 { publicAudio.removeAll() }
                        publicAudio[id] = resolved; bytes = resolved
                    }
                } else if let path = item.audio_url { bytes = try await dependencies.resolveAcknowledgement(scope, path) }
                else if let asset = item.generated_asset_id { bytes = try await dependencies.resolveAudio(scope, asset) }
                else { throw CocoaError(.fileReadNoSuchFile) }
                try Task.checkCancellation()
                guard generation == token, playbackGeneration == playbackToken, self.scope == scope, self.messageID == messageID, dependencies.canPlay(scope) else { return }
                while paused {
                    try await Task.sleep(nanoseconds: 50_000_000)
                    try Task.checkCancellation()
                }
                guard dependencies.canPlay(scope) else { throw CancellationError() }
                waveform = waveforms[id] ?? dependencies.waveformSamples(bytes)
                waveforms[id] = waveform
                playbackStatus = paused ? .paused : .playing
                try await dependencies.play(bytes)
                try Task.checkCancellation()
                guard generation == token, playbackGeneration == playbackToken, self.messageID == messageID else { return }
                played.insert(id)
                nextSequence = publicPlayback ? (playbackSegments.first(where: { ($0.sequence ?? -1) > activeSequence })?.sequence ?? activeSequence + 1) : nextSequence + 1; playbackTask = nil
                playbackStatus = responseDrained ? .completed : .waitingForSegment
                drain()
            } catch {
                guard generation == token, playbackGeneration == playbackToken, self.messageID == messageID else { return }
                playbackTask = nil
                if !(error is CancellationError) { self.error = "Speech audio could not be loaded."; failedOperation = .audio; playbackStatus = .failed }
            }
        }
    }

    private func failProvider() {
        playbackGeneration = UUID(); playbackTask?.cancel(); playbackTask = nil
        dependencies.stopPendingCue(); dependencies.stopPlayback()
        error = "Speech generation is unavailable for this response. You can continue chatting."
        failedOperation = .provider; playbackStatus = .failed
    }
    func retry() async {
        guard let operation = failedOperation else { return }
        switch operation {
        case .load: ready = false; await activate(scope)
        case .write(let desired): await setEnabled(desired)
        case .audio: retryPlayback()
        case .provider: if manual { retryPlayback() } // Retry only with canonical projected source.
        }
    }
    func retryPlayback() {
        guard failedOperation == .audio || (failedOperation == .provider && manual),
              ready, let scope, dependencies.canPlay(scope), let messageID else { return }
        error = nil; failedOperation = nil; playbackStatus = .waitingForSegment
        if manual, awaitingAcceptance || segments.isEmpty {
            awaitingAcceptance = true
            let token = generation, responseToken = responseGeneration
            Task { [weak self] in
                guard let self, generation == token, responseGeneration == responseToken,
                      self.scope == scope, self.messageID == messageID, dependencies.canPlay(scope),
                      !Task.isCancelled else { return }
                do { try await dependencies.requestSpeech(scope, messageID, "request", projected.map(\.wire)) }
                catch {
                    guard generation == token, responseGeneration == responseToken,
                          self.scope == scope, self.messageID == messageID, dependencies.canPlay(scope) else { return }
                    failedOperation = .audio; self.error = "Speech is temporarily unavailable."; playbackStatus = .failed
                }
            }
        } else {
            if manual, let item = activeSegment, let id = item.segment_id, item.status != "ready" {
                segments[id] = .init(segment_id: id, sequence: item.sequence, status: "registered", generated_asset_id: nil,
                    request_sequence: item.request_sequence, kind: item.kind)
                generationRequested.remove(id)
                playbackSegments = segments.values.sorted { ($0.sequence ?? 0) < ($1.sequence ?? 0) }
            }
            drain()
        }
    }
    private func stopLocally() -> (AssistantSpeechScope, String)? {
        let oldScope = scope, oldMessage = messageID, wasPublic = publicPlayback
        responseGeneration = UUID(); playbackGeneration = UUID()
        playbackTask?.cancel(); playbackTask = nil; dependencies.stopPendingCue(); dependencies.stopPlayback()
        messageID = nil; segments.removeAll(); played.removeAll()
        playbackSegments = []; waveform = []; waveforms = [:]; projected = []; generationRequested.removeAll(); manual = false; awaitingAcceptance = false; explicitSelection = false; paused = false; playbackStatus = .stopped
        publicPlayback = false; publicAssets = [:]; publicAudio = [:]
        if !wasPublic, let oldScope, let oldMessage { return (oldScope, oldMessage) }
        return nil
    }
    private func stopForReplacement(in expectedScope: AssistantSpeechScope) async -> Bool {
        let token = generation
        let cancelled = stopLocally()
        let replacement = playbackGeneration
        if let (oldScope, oldMessage) = cancelled {
            try? await dependencies.cancelResponse(oldScope, oldMessage)
        }
        return generation == token && playbackGeneration == replacement && scope == expectedScope &&
            ready && dependencies.canPlay(expectedScope) && !Task.isCancelled
    }
    func stop() async {
        if let (oldScope, oldMessage) = stopLocally() {
            try? await dependencies.cancelResponse(oldScope, oldMessage)
        }
    }
    func detach() {
        guard let (oldScope, oldMessage) = stopLocally() else { return }
        let token = generation
        Task { [weak self] in
            guard let self, generation == token else { return }
            try? await dependencies.cancelResponse(oldScope, oldMessage)
        }
    }
    func reset() {
        generation = UUID(); responseGeneration = UUID(); playbackGeneration = UUID(); feedbackTask?.cancel(); feedbackTask = nil
        playbackTask?.cancel(); playbackTask = nil; dependencies.stopPendingCue(); dependencies.stopPlayback()
        publicContext = false; publicPlayback = false; publicAssets = [:]; publicAudio = [:]
        scope = nil; messageID = nil; segments.removeAll(); played.removeAll()
        playbackSegments = []; waveform = []; waveforms = [:]; projected = []; generationRequested.removeAll(); manual = false; awaitingAcceptance = false; explicitSelection = false; paused = false; playbackStatus = .stopped
        mateName = "OpenMates"; mateCategory = "default"
        enabled = false; ready = false; feedback = nil; error = nil; failedOperation = nil
    }
    private func showFeedback(_ value: Bool) {
        feedbackTask?.cancel(); feedback = value
        let token = generation
        feedbackTask = Task { [weak self] in
            guard let self else { return }
            do { try await dependencies.sleep(1_800_000_000) } catch { return }
            guard generation == token, !Task.isCancelled else { return }
            feedback = nil
        }
    }
}
