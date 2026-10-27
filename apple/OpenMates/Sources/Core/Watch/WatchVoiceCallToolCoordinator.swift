// Web sources: frontend/packages/ui/src/services/voiceCallTools.ts, voiceCall.ts.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.skill-integration, video-call.chat.transcripts,
// video-call.privacy, video-call.lifecycle.recovery-and-billing
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
import Foundation
import Combine

/// The Watch consumes every controller tool event using explicit injected
/// adapters. Focus/context actions remain unavailable until an adapter exists.
@MainActor
final class WatchVoiceCallToolCoordinator: ObservableObject {
    @Published private(set) var integrationError: NativeVoiceCallError?
    @Published private(set) var toolWorking = false
    private var continuation: NativeVoiceCallToolContinuation?
    private var state = NativeVoiceCallSnapshot()
    private var invalidateMemory: (@MainActor () -> Void)?

    func bind(artifacts: @escaping NativeVoiceCallToolContinuation.Handler,
              memory: @escaping NativeVoiceCallToolContinuation.Handler,
              respond: @escaping @MainActor @Sendable (NativeVoiceCallFrame) async throws -> Void,
              hangup: @escaping @MainActor @Sendable () async -> Void,
              invalidateMemory: @escaping @MainActor () -> Void) {
        invalidateOwner()
        self.invalidateMemory = invalidateMemory
        continuation = NativeVoiceCallToolContinuation(handler: { [weak self] scope, callID, frame, validate in
            switch frame["type"]?.string {
            case "voice_memory": return try await memory(scope, callID, frame, validate)
            case "voice_embed": return try await artifacts(scope, callID, frame, validate)
            case "voice_tool_status":
                self?.toolWorking = true
                return .presented
            default: return .unsupported
            }
        }, respond: respond, fail: { [weak self] error in
            self?.integrationError = error; self?.toolWorking = false
        }, hangup: hangup)
    }
    func receive(_ event: NativeVoiceCallEvent) async {
        switch event {
        case .state(let snapshot):
            state = snapshot
            continuation?.update(snapshot)
            if snapshot.status != .live { invalidateMemory?(); toolWorking = false }
            if snapshot.status == .connecting { integrationError = nil }
            if let error = snapshot.error { integrationError = error }
        case .tool(let frame): await continuation?.receive(frame)
        case .usage(let frame):
            guard state.status == .live, let callID = state.callID,
                  frame["call_id"] == nil || frame["call_id"]?.string == callID else { return }
            toolWorking = false
        default: break
        }
    }
    func invalidateOwner() {
        continuation?.invalidateOwner(); continuation = nil
        invalidateMemory?(); invalidateMemory = nil
        toolWorking = false; integrationError = nil; state = NativeVoiceCallSnapshot()
    }
    func finishAdmittedArtifacts() async { await continuation?.finishAdmittedArtifacts() }
    func dismissError() { integrationError = nil }
}

/// Projection ownership grants no audio or start authority. A genuine evaluation
/// lease may replace an idle root projection; stale events/teardown cannot then
/// overwrite that evaluation's exact controller state.
struct WatchVoiceCallProjectionOwnership {
    private(set) var owner: UUID?
    mutating func claim(_ candidate: UUID, replacingIdle: Bool, audioOwned: Bool) -> Bool {
        guard owner == nil || owner == candidate || (replacingIdle && !audioOwned) else { return false }
        owner = candidate; return true
    }
    func isCurrent(_ candidate: UUID) -> Bool { owner == candidate }
    mutating func release(_ candidate: UUID) -> Bool {
        guard owner == candidate else { return false }
        owner = nil; return true
    }
}

/// Publication authority comes only from a completed encrypted commit. Several
/// functions may contribute artifacts to the same assistant message; processing
/// admissions never replace another artifact's committed publication token.
struct WatchVoiceCallCommittedArtifacts {
    private struct Entry {
        let commit: WatchVoiceCallArtifactCommit
        let embedID: String
    }
    private var entries: [Entry] = []

    mutating func record(_ commit: WatchVoiceCallArtifactCommit) throws {
        let reference = try NativeVoiceCallArtifactReference(validating: commit.reference)
        let admission = commit.admission
        if let index = entries.firstIndex(where: {
            let existing = $0.commit.admission
            return existing.scope == admission.scope && existing.callID == admission.callID
                && existing.functionCallID == admission.functionCallID
                && existing.assistantMessageID == admission.assistantMessageID
                && existing.userMessageID == admission.userMessageID && $0.embedID == reference.embedID
        }) {
            entries.remove(at: index)
        }
        guard entries.count < 128 else { throw NativeVoiceCallError.contextTooLarge }
        entries.append(Entry(commit: commit, embedID: reference.embedID))
    }
    func admission(for transcript: NativeVoiceCallTranscript, scope: NativeVoiceCallScope) -> WatchVoiceCallArtifactAdmission? {
        guard transcript.role == .assistant else { return nil }
        return entries.reversed().first(where: { entry in
            let admission = entry.commit.admission
            return admission.scope == scope && admission.callID == transcript.callID
                && admission.assistantMessageID == transcript.messageID
                && admission.userMessageID == transcript.userMessageID
                && transcript.embedReferences.contains(where: { $0.fields == entry.commit.reference })
        })?.commit.admission
    }
    mutating func removeAll() { entries.removeAll() }
}
