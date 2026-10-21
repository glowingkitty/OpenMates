// Web sources: frontend/packages/ui/src/services/voiceCallTools.ts, voiceCall.ts.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.skill-integration,
// video-call.privacy, video-call.lifecycle.recovery-and-billing
import Foundation

enum NativeVoiceCallArtifactDisposition: Sendable {
    /// An actual artifact or transient status was accepted by its authorized adapter.
    case presented
    /// Only an explicit memory permission action may produce this broker response.
    case response(NativeVoiceCallFrame)
    case unsupported
}

/// Shared bounded continuation policy. Neither a Watch event callback nor the
/// app controller waits for a permission decision. All asynchronous work carries
/// its original owner, scope and broker identity through every suspension.
@MainActor
final class NativeVoiceCallToolContinuation {
    typealias Validation = @MainActor @Sendable () async throws -> Void
    typealias Handler = @MainActor @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame, @escaping Validation) async throws -> NativeVoiceCallArtifactDisposition
    private let handler: Handler
    private let respond: @MainActor @Sendable (NativeVoiceCallFrame) async throws -> Void
    private let fail: @MainActor @Sendable (NativeVoiceCallError) -> Void
    private let hangup: @MainActor @Sendable () async -> Void
    private var state = NativeVoiceCallSnapshot()
    private var owner = UUID()
    private var pumpID: UUID?
    private var task: Task<Void, Never>?
    private var activeKind: String?
    private var queue: [(NativeVoiceCallScope, String, NativeVoiceCallFrame)] = []

    init(handler: @escaping Handler,
         respond: @escaping @MainActor @Sendable (NativeVoiceCallFrame) async throws -> Void,
         fail: @escaping @MainActor @Sendable (NativeVoiceCallError) -> Void,
         hangup: @escaping @MainActor @Sendable () async -> Void) {
        self.handler = handler; self.respond = respond; self.fail = fail; self.hangup = hangup
    }
    func update(_ snapshot: NativeVoiceCallSnapshot) {
        let replaced = state.scope != snapshot.scope || state.callID != snapshot.callID
        state = snapshot
        if replaced || snapshot.status == .failed { cancel() }
        else if snapshot.status != .live {
            queue.removeAll()
            // A broker artifact already admitted to encrypted canonical storage
            // may finish on normal hangup. Memory permission must end immediately.
            if snapshot.status != .ended || activeKind != "voice_embed" { cancel() }
        }
    }
    func invalidateOwner() { owner = UUID(); cancel(); state = NativeVoiceCallSnapshot() }
    func finishAdmittedArtifacts() async {
        guard activeKind == "voice_embed" else { return }
        await task?.value
    }
    private func cancel() {
        pumpID = nil; task?.cancel(); task = nil; activeKind = nil; queue.removeAll()
    }
    func receive(_ frame: NativeVoiceCallFrame) async {
        guard state.status == .live, let scope = state.scope, let callID = state.callID else { return }
        guard queue.count < 16 else {
            cancel(); fail(.unsupportedTransport); await hangup(); return
        }
        queue.append((scope, callID, frame)); start()
    }
    private func validate(scope: NativeVoiceCallScope, callID: String, owner admittedOwner: UUID,
                          allowEnded: Bool) throws {
        try Task.checkCancellation()
        guard owner == admittedOwner, state.scope == scope, state.callID == callID,
              state.status == .live || (allowEnded && state.status == .ended)
        else { throw NativeVoiceCallError.scopeChanged }
    }
    private func start() {
        guard task == nil else { return }
        let id = UUID(), admittedOwner = owner; pumpID = id
        task = Task { [weak self] in
            guard let self else { return }
            defer { if pumpID == id { task = nil; pumpID = nil; activeKind = nil } }
            while pumpID == id, !queue.isEmpty, !Task.isCancelled {
                let (scope, callID, frame) = queue.removeFirst()
                do {
                    try validate(scope: scope, callID: callID, owner: admittedOwner, allowEnded: false)
                    let kind = try Self.validateOrigin(frame, scope: scope, callID: callID)
                    activeKind = kind
                    let validation: Validation = { [weak self] in
                        guard let self else { throw NativeVoiceCallError.scopeChanged }
                        try self.validate(scope: scope, callID: callID, owner: admittedOwner, allowEnded: kind == "voice_embed")
                    }
                    let result = try await handler(scope, callID, frame, validation)
                    try await validation()
                    switch result {
                    case .presented:
                        guard kind != "voice_memory" else { throw NativeVoiceCallError.invalidResponse }
                    case .response(let response):
                        try Self.validateMemoryResponse(response, request: frame, callID: callID)
                        try validate(scope: scope, callID: callID, owner: admittedOwner, allowEnded: false)
                        try await respond(response)
                    case .unsupported: throw NativeVoiceCallError.unsupportedTransport
                    }
                } catch {
                    guard !Task.isCancelled, pumpID == id else { return }
                    queue.removeAll()
                    fail(error as? NativeVoiceCallError ?? .unsupportedTransport)
                    await hangup(); return
                }
                activeKind = nil
            }
        }
    }
    private static func validateOrigin(_ frame: NativeVoiceCallFrame, scope: NativeVoiceCallScope, callID: String) throws -> String {
        guard let kind = frame["type"]?.string,
              ["voice_memory", "voice_focus", "voice_embed", "voice_context", "voice_tool_status"].contains(kind),
              frame["call_id"]?.string == callID,
              let payload = frame["payload"]?.object,
              payload["chat_id"] == nil || payload["chat_id"]?.string == scope.chatID,
              payload["user_id"] == nil || payload["user_id"]?.string == scope.accountID,
              payload["team_id"] == nil || payload["team_id"] == .null else {
            throw NativeVoiceCallError.invalidResponse
        }
        if kind == "voice_memory" || kind == "voice_embed" {
            for key in ["function_call_id", "assistant_message_id", "user_message_id"] {
                guard let value = frame[key]?.string, !value.isEmpty, value.utf8.count <= 128,
                      !value.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains)
                else { throw NativeVoiceCallError.invalidResponse }
            }
            guard payload["message_id"] == nil || payload["message_id"] == frame["assistant_message_id"] else {
                throw NativeVoiceCallError.invalidResponse
            }
        }
        return kind
    }
    private static func validateMemoryResponse(_ response: NativeVoiceCallFrame, request: NativeVoiceCallFrame, callID: String) throws {
        guard request["type"]?.string == "voice_memory",
              let requestID = request["payload"]?.object?["request_id"]?.string, !requestID.isEmpty,
              response["request_id"]?.string == requestID,
              response["function_call_id"] == request["function_call_id"],
              response["call_id"]?.string == callID,
              response["type"]?.string == "voice_memory_response", response["approved"]?.bool != nil
        else { throw NativeVoiceCallError.invalidResponse }
    }
}
