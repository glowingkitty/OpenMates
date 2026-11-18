// Saves the camera frames the server asks for as encrypted image embeds.
// Logic:   frontend/packages/ui/src/services/voiceCall.ts (`voice_source_frame` case) and
//          voiceCallVisuals.ts persistCallSourceFrame; the encryption/upload lives in the Rust core.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.video.source-frame-provenance
#if !os(watchOS)
import Foundation

/// A `voice_source_frame` request. The server sends the exact frame it selected in `data`
/// (base64, passed to the core exactly as received), so the app persists that and never
/// substitutes a newer camera frame. The core validates the image; Swift only extracts ids.
struct NativeVoiceCallSourceFrameRequest: Equatable, Sendable {
    enum Source: String, Sendable { case camera, screen }
    let callID: String
    let userMessageID: String
    let frameID: String
    let data: String
    let capturedAt: Double
    let createdAt: Int64
    let source: Source

    /// Same id/length bounds as the controller guard: ids <= 128 bytes, base64 <= 350k chars.
    /// Returns `nil` for anything malformed (the caller answers with `source_frame_failed`
    /// only when ids are valid, see `failureMessage`).
    init?(frame: NativeVoiceCallFrame, expectedCallID: String) {
        guard frame["call_id"]?.string == expectedCallID,
              let userID = frame["user_message_id"]?.string, !userID.isEmpty, userID.utf8.count <= 128,
              let frameID = frame["frame_id"]?.string, !frameID.isEmpty, frameID.utf8.count <= 128,
              let encoded = frame["data"]?.string, encoded.utf8.count <= NativeVoiceCallWire.maximumSourceFrameCharacters,
              let captured = frame["captured_at"]?.number, captured.isFinite,
              let created = frame["created_at"]?.number, created.isFinite else { return nil }
        self.callID = expectedCallID
        self.userMessageID = userID
        self.frameID = frameID
        self.data = encoded
        self.capturedAt = captured
        self.createdAt = Int64(created.rounded())
        self.source = frame["source"]?.string == "screen" ? .screen : .camera
    }

    /// `source_frame_failed` for a request whose ids are valid but whose content is not.
    static func failureMessage(frame: NativeVoiceCallFrame, expectedCallID: String) -> NativeVoiceCallFrame? {
        NativeVoiceCallWire.sourceFrameFailure(frame: frame, callID: expectedCallID)
    }
}

/// The saved embed, as the broker expects it in `embed_reference` (web `VoiceArtifactReference`).
struct NativeVoiceCallSourceReference: Equatable, Sendable {
    let embedID: String
    let sourceFrameID: String
    let capturedAt: Double
    let sourceCallID: String
    let source: NativeVoiceCallSourceFrameRequest.Source

    var json: NativeVoiceCallJSON {
        .object(["type": .string("image"), "embed_id": .string(embedID),
                 "source_frame_id": .string(sourceFrameID), "captured_at": .number(capturedAt),
                 "source_call_id": .string(sourceCallID), "source": .string(source.rawValue)])
    }

    func savedMessage(request: NativeVoiceCallSourceFrameRequest) -> NativeVoiceCallFrame {
        ["type": .string("source_frame_saved"), "call_id": .string(request.callID),
         "user_message_id": .string(request.userMessageID), "frame_id": .string(request.frameID),
         "embed_reference": json]
    }
}

/// Persists one request and returns the wire answer. At most `limit` saves run at once,
/// like web (`sourceFrames.size >= 8` answers with failure).
@MainActor
final class NativeVoiceCallSourceFrames {
    typealias Persist = @Sendable (NativeVoiceCallSourceFrameRequest, String) async throws -> NativeVoiceCallSourceReference
    static let limit = 8
    private var pending: Set<String> = []
    private let persist: Persist

    /// `persist` calls the core: the app wires it to `ViewModelCore.persistCallSourceFrame`.
    init(persist: @escaping Persist) { self.persist = persist }

    /// The wire answer for `frame`, or `nil` when it is a duplicate or not for this call.
    /// `chatID` is the chat bound to the call.
    func answer(frame: NativeVoiceCallFrame, callID: String, chatID: String) async -> NativeVoiceCallFrame? {
        guard let request = NativeVoiceCallSourceFrameRequest(frame: frame, expectedCallID: callID) else {
            return NativeVoiceCallSourceFrameRequest.failureMessage(frame: frame, expectedCallID: callID)
        }
        let key = request.userMessageID + ":" + request.frameID
        guard !pending.contains(key) else { return nil }
        let failed = NativeVoiceCallSourceFrameRequest.failureMessage(frame: frame, expectedCallID: callID)
        guard pending.count < Self.limit else { return failed }
        pending.insert(key)
        defer { pending.remove(key) }
        do { return try await persist(request, chatID).savedMessage(request: request) }
        catch { return failed }
    }
}

extension NativeVoiceCallSourceFrames {
    /// Production answerer: persists through the app's core session, resolved per request;
    /// without a core session the frame is answered with `source_frame_failed`.
    static func live() -> NativeVoiceCallSourceFrames {
        NativeVoiceCallSourceFrames { request, chatID in
            #if canImport(OpenMatesCore)
            guard let session = await MainActor.run(body: { CoreSession.shared }) else { throw NativeVoiceCallError.callUnavailable }
            return try await CoreSession.callSourcePersist(session)(request, chatID)
            #else
            throw NativeVoiceCallError.callUnavailable
            #endif
        }
    }
}

#if canImport(OpenMatesCore)
import OpenMatesCore

extension CoreSession {
    /// Production `Persist`: encrypts and saves the frame through the Rust client core.
    nonisolated static func callSourcePersist(_ session: CoreSession) -> NativeVoiceCallSourceFrames.Persist {
        { request, chatID in
            let record = try await session.perform { core, cancellation in
                try await core.persistCallSourceFrame(
                    callId: request.callID, chatId: chatID, userMessageId: request.userMessageID,
                    frameId: request.frameID, data: request.data, capturedAt: request.capturedAt,
                    createdAt: request.createdAt, source: request.source == .screen ? .screen : .camera,
                    cancellation: cancellation)
            }
            return NativeVoiceCallSourceReference(
                embedID: record.embedId, sourceFrameID: record.sourceFrameId, capturedAt: record.capturedAt,
                sourceCallID: record.sourceCallId, source: record.source == .screen ? .screen : .camera)
        }
    }
}
#endif
#endif
