// Message ids of server-started interpreting turns inside one live voice call.
// Web source: frontend/packages/ui/src/services/voiceCall.ts (`orchestration_turn`, callTurnIds).
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.orchestration-continuity
import Foundation

/// Turn ids the server announced with `orchestration_turn`. A frame for another
/// call or with an empty/oversized id is ignored, never an error.
struct NativeVoiceCallOrchestrationTurns: Equatable, Sendable {
    private(set) var messageIDs = Set<String>()

    mutating func accept(callID: String, frameCallID: String?, messageID: String?) {
        guard frameCallID == callID, let messageID, !messageID.isEmpty, messageID.utf8.count <= 128 else { return }
        messageIDs.insert(messageID)
    }

    func contains(_ messageID: String) -> Bool { messageIDs.contains(messageID) }

    mutating func removeAll() { messageIDs.removeAll() }
}
