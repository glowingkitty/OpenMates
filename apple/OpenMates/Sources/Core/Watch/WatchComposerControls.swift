// Watch composer action policy and local recording draft boundary.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.new-text-reply, apple-watch.chats.audio-reply, apple-watch.chats.input-actions, apple-watch.chats.local-transcription, apple-watch.chats.compact-layout
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle
import Foundation
import Combine

protocol WatchRecordingDraftTranscribing: Sendable {
    /// Local-only decode; implementations must never create a network fallback.
    func transcribe(fileURL: URL) async throws -> String
    func cancel() async
}

struct WatchUnavailableRecordingTranscriber: WatchRecordingDraftTranscribing {
    func transcribe(fileURL: URL) async throws -> String { throw WatchComposerActionError.localTranscriptionUnavailable }
    func cancel() async {}
}

enum WatchComposerActionError: Error {
    case localTranscriptionUnavailable, callUnavailable, busy, staleScope, invalidRecording
}

struct WatchEncryptedRecordingDraft: Codable, Equatable, Sendable {
    let id: UUID
    let chatID: String
    let encryptedPayload: String
}

struct WatchRecordingDraftPayload: Codable, Sendable {
    let audio: Data
    let filename: String
    let duration: TimeInterval
    let transcript: String
}

struct WatchCallActionProjection: Equatable, Sendable {
    enum Phase: Equatable, Sendable { case unavailable, ready, connecting, live, ended, failed }
    var phase: Phase = .unavailable
    var chatID: String?
    var callID: String?
    var scopeGeneration: UUID?
    var muted = false
    var activeSeconds: TimeInterval = 0
    var elapsedText: String {
        let seconds = max(0, Int(activeSeconds))
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }
    /// Becomes true only after the root-owned physical Watch eligibility harness
    /// proves the selected audio/network route. Simulator is never such proof.
    var physicalRouteVerified = false
    var ownsAudio: Bool { phase == .connecting || phase == .live }
    var canStart: Bool { physicalRouteVerified && (phase == .ready || phase == .ended || phase == .failed) }
}

@MainActor
final class WatchCallActionAdapter: ObservableObject {
    @Published private(set) var projection = WatchCallActionProjection()
    private var startAction: (@MainActor (WatchChatRequestContext, String) async throws -> Void)?
    private var textAction: (@MainActor (String) async throws -> String)?
    private var muteAction: (@MainActor (Bool) async -> Void)?
    private var invalidated = false
    private var activeContext: WatchChatRequestContext?
    var onStateChange: (@MainActor (WatchCallActionProjection) -> Void)?
    private var hangupAction: (@MainActor () async -> Void)?
    private var invalidateAction: (@MainActor () async -> Void)?

    func configure(projection: WatchCallActionProjection,
                   start: @escaping @MainActor (WatchChatRequestContext, String) async throws -> Void,
                   sendText: @escaping @MainActor (String) async throws -> String,
                   setMuted: @escaping @MainActor (Bool) async -> Void,
                   hangup: @escaping @MainActor () async -> Void,
                   invalidate: @escaping @MainActor () async -> Void) {
        invalidated = false
        self.projection = projection
        startAction = start; textAction = sendText; muteAction = setMuted
        hangupAction = hangup; invalidateAction = invalidate
    }

    func update(_ projection: WatchCallActionProjection) {
        guard !invalidated else { return }
        if let activeContext, (try? activeContext.check()) == nil {
            self.projection = WatchCallActionProjection()
            return
        }
        self.projection = projection
        onStateChange?(projection)
    }

    func activate(context: WatchChatRequestContext, chatID: String) async throws {
        try context.check()
        if projection.ownsAudio {
            guard let hangupAction else { throw WatchComposerActionError.callUnavailable }
            await hangupAction()
            return
        }
        guard projection.canStart, let startAction else { throw WatchComposerActionError.callUnavailable }
        activeContext = context
        projection.phase = .connecting
        projection.chatID = chatID
        do { try await startAction(context, chatID) }
        catch {
            if !invalidated { projection.phase = .failed }
            throw error
        }
    }

    func toggleMuted() async {
        guard !invalidated, projection.phase == .live else { return }
        await muteAction?(!projection.muted)
    }

    func sendText(_ text: String, chatID: String) async throws -> String? {
        guard !invalidated, projection.ownsAudio, projection.chatID == chatID else { return nil }
        try activeContext?.check()
        guard projection.phase == .live, let textAction else { throw WatchComposerActionError.busy }
        return try await textAction(text)
    }

    func invalidate() async {
        invalidated = true
        activeContext = nil
        projection = WatchCallActionProjection()
        onStateChange?(projection)
        await invalidateAction?()
    }
}

struct WatchComposerControlPolicy: Equatable {
    let busy: Bool
    let callOwnsAudio: Bool
    let hasRecordingDraft: Bool
    let hasText: Bool
    // The microphone remains mounted with typed text; Send is independent.
    var canRecord: Bool { !busy && !callOwnsAudio && !hasRecordingDraft }
    var canEdit: Bool { !busy }
    var canSend: Bool { !busy && (hasText || hasRecordingDraft) }
    var canActivateCall: Bool { !busy && !hasRecordingDraft }

    static func appendTranscript(_ transcript: String, to draft: String) -> String {
        guard !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return draft }
        return draft.isEmpty ? transcript : draft + "\n" + transcript
    }
}

struct WatchRecordingDraftCandidate: Sendable {
    let chat: WatchChatSummary
    let recording: WatchEncryptedRecordingDraft?
    let draft: WatchEncryptedDraft
}

/// Serializes file replacement against cache erase and superseded snapshots.
/// The lock covers synchronous file IO only, never an await.
final class WatchSnapshotCommitFence: @unchecked Sendable {
    private let lock = NSLock()
    private var generation: UInt64 = 0
    func claim() -> UInt64 {
        lock.lock(); defer { lock.unlock() }
        generation &+= 1
        return generation
    }
    func commit(token: UInt64, operation: () throws -> Void) throws {
        lock.lock(); defer { lock.unlock() }
        guard token == generation else { throw CancellationError() }
        try operation()
    }
    func erase(operation: () throws -> Void) throws {
        lock.lock(); defer { lock.unlock() }
        generation &+= 1
        try operation()
    }
}

struct WatchPreparedTurnCandidate: Sendable {
    let chat: WatchChatSummary
    let pending: WatchPendingTextSend
    let message: WatchChatMessage
}

/// UI-only progressive transcript. Ciphertext/retry authority stays in the
/// shared voice outbox; this projection never enters WatchChatSnapshot.
struct WatchCallTranscriptProjection: Sendable {
    let callID: String
    let scopeGeneration: UUID
    var message: WatchChatMessage
    var final: Bool
}

struct WatchPendingCallComposerDraft: Sendable {
    let operationID: UUID
    let chatID: String
    let callID: String
    let scopeGeneration: UUID
    let revision: UInt64
    let contentHash: String
    let encryptedSource: String
    var messageID: String?
    var accepted = false
}
