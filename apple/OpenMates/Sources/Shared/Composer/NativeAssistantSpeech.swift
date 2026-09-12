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
}
struct AssistantSpeechStatus: Decodable {
    let chat_id: String?
    let message_id: String?
    let status: String?
    let segment_id: String?
    let sequence: Int?
    let generated_asset_id: String?
    var retryable: Bool? = nil
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
        var canPlay: @MainActor (AssistantSpeechScope) -> Bool = { _ in true }
    }
    @Published private(set) var enabled = false
    @Published private(set) var ready = false
    @Published private(set) var feedback: Bool?
    @Published private(set) var error: String?
    private(set) var scope: AssistantSpeechScope?
    private let dependencies: Dependencies
    private var generation = UUID()
    private var preferenceRevision = UUID()
    private var feedbackTask: Task<Void, Never>?
    private var playbackTask: Task<Void, Never>?
    private var playbackGeneration = UUID()
    private var messageID: String?
    private var segments: [String: AssistantSpeechSegment] = [:]
    private var played = Set<String>()
    private var nextSequence = 0
    private enum FailedOperation: Equatable { case load, write(Bool), audio, provider }
    private var failedOperation: FailedOperation?
    var canRetry: Bool {
        guard let failedOperation else { return false }
        if case .provider = failedOperation { return false }
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

    func refreshPreference() async {
        guard ready, let scope else { return }
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
        guard ready else { return }
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
        playbackGeneration = UUID()
        playbackTask?.cancel(); playbackTask = nil; dependencies.stopPlayback()
        messageID = id; segments.removeAll(); played.removeAll(); nextSequence = 0
        if failedOperation == .audio || failedOperation == .provider { failedOperation = nil; error = nil }
    }

    func receive(_ event: AssistantSpeechStatus, in eventScope: AssistantSpeechScope) {
        guard enabled, eventScope == scope, event.chat_id == eventScope.chatID,
              event.message_id == messageID else { return }
        if event.status == "error", event.segment_id == nil {
            failProvider(); return
        }
        let incoming = event.segments ?? [AssistantSpeechSegment(segment_id: event.segment_id,
            sequence: event.sequence, status: event.status, generated_asset_id: event.generated_asset_id)]
        for segment in incoming {
            guard let id = segment.segment_id, let sequence = segment.sequence, sequence >= 0 else { continue }
            if segments[id]?.status == "ready", ["queued", "generating"].contains(segment.status ?? "") { continue }
            // A duplicate sequence cannot randomly replace an already queued
            // provider asset. Provider retries require an explicit manual request.
            if let other = segments.values.first(where: { $0.sequence == sequence }), other.segment_id != id { continue }
            segments[id] = segment
            if ["error", "cancelled", "deleted"].contains(segment.status ?? "") { failProvider() }
        }
        drain()
    }

    func resumePlaybackIfReady() { drain() }

    private func drain() {
        guard enabled, failedOperation == nil, playbackTask == nil, let scope,
              dependencies.canPlay(scope), let messageID,
              let item = segments.values.first(where: { $0.sequence == nextSequence }),
              let id = item.segment_id, !played.contains(id) else { return }
        guard item.status == "ready", let assetID = item.generated_asset_id else { return }
        let token = generation
        let playbackToken = playbackGeneration
        playbackTask = Task { [weak self] in
            guard let self else { return }
            do {
                let bytes = try await dependencies.resolveAudio(scope, assetID)
                try Task.checkCancellation()
                guard generation == token, playbackGeneration == playbackToken, self.scope == scope, self.messageID == messageID else { return }
                try await dependencies.play(bytes)
                try Task.checkCancellation()
                guard generation == token, playbackGeneration == playbackToken, self.messageID == messageID else { return }
                played.insert(id); nextSequence += 1; playbackTask = nil; drain()
            } catch {
                guard generation == token, playbackGeneration == playbackToken, self.messageID == messageID else { return }
                playbackTask = nil
                if !(error is CancellationError) { self.error = error.localizedDescription; failedOperation = .audio }
            }
        }
    }

    private func failProvider() {
        playbackGeneration = UUID(); playbackTask?.cancel(); playbackTask = nil
        dependencies.stopPlayback()
        error = "Speech generation is unavailable for this response. You can continue chatting."
        failedOperation = .provider
    }
    func retry() async {
        guard let operation = failedOperation else { return }
        switch operation {
        case .load: ready = false; await activate(scope)
        case .write(let desired): await setEnabled(desired)
        case .audio: error = nil; failedOperation = nil; drain()
        case .provider: break // No fake retry; server requires canonical source segments.
        }
    }
    func retryPlayback() { if failedOperation == .audio { error = nil; failedOperation = nil; drain() } }
    private func stopLocally() -> (AssistantSpeechScope, String)? {
        let oldScope = scope, oldMessage = messageID
        playbackGeneration = UUID()
        playbackTask?.cancel(); playbackTask = nil; dependencies.stopPlayback()
        messageID = nil; segments.removeAll(); played.removeAll()
        if let oldScope, let oldMessage { return (oldScope, oldMessage) }
        return nil
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
        generation = UUID(); playbackGeneration = UUID(); feedbackTask?.cancel(); feedbackTask = nil
        playbackTask?.cancel(); playbackTask = nil; dependencies.stopPlayback()
        scope = nil; messageID = nil; segments.removeAll(); played.removeAll()
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
