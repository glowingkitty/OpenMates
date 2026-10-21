// Web source: frontend/packages/ui/src/services/voiceCallMessages.ts, voiceCallContext.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.compressed-context, video-call.chat.project-context,
// video-call.chat.memories-and-focus, video-call.chat.assistant-identity

import Foundation

struct NativeVoiceCallContext: Sendable {
    let fields: NativeVoiceCallFrame

    /// Inputs are decrypted, canonical history/checkpoints, never overview text.
    /// The adapter asserts completeness before calling this; missing pages fail.
    init(messages: [Message], summary: String? = nil,
         activeFocus: NativeVoiceCallJSON? = nil,
         projectFields: NativeVoiceCallFrame = [:], mateCategory: String,
         canonicalRangeComplete: Bool) throws {
        guard canonicalRangeComplete, !mateCategory.isEmpty,
              Set(messages.map(\.id)).count == messages.count,
              messages.allSatisfy({ !$0.id.isEmpty && !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0.createdAt > 0 }) else { throw NativeVoiceCallError.contextUnavailable }
        guard messages.count <= 30, (summary?.utf16.count ?? 0) <= 48_000,
              (summary?.utf16.count ?? 0) + messages.reduce(0, { $0 + $1.text.utf16.count }) <= 64_000
        else { throw NativeVoiceCallError.contextTooLarge }
        let allowed = Set(["project_focus_candidates", "client_capabilities", "project_focus_documents",
                           "app_settings_memories_metadata"])
        guard Set(projectFields.keys).isSubset(of: allowed) else { throw NativeVoiceCallError.contextUnavailable }
        var fields = projectFields
        fields["messages"] = .array(messages.map { .object([
            "role": .string($0.role.rawValue), "text": .string($0.text),
            "message_id": .string($0.id), "created_at": .number(Double($0.createdAt))
        ]) })
        fields["mate_category"] = .string(mateCategory)
        if let summary { fields["summary"] = .string(summary) }
        if let activeFocus { fields["active_focus"] = activeFocus }
        guard try JSONEncoder().encode(fields).count <= 255_000 else { throw NativeVoiceCallError.contextTooLarge }
        self.fields = fields
    }

    struct Message: Sendable {
        let id: String
        let role: NativeVoiceCallTranscript.Role
        let text: String
        let createdAt: Int
    }
}

/// A canonical history adapter can use this boundary helper for checkpoint
/// coverage. Late corrected call revisions replay even with older original time.
enum NativeVoiceCallHistory {
    struct Boundary: Sendable {
        let timestamp: Int
        let messageID: String
        let coveredMessageIDs: Set<String>
    }
    static func isUncovered(id: String, createdAt: Int, callRevision: Int?, boundary: Boundary?) -> Bool {
        if let callRevision, callRevision > 1 { return true }
        guard let boundary else { return true }
        return !boundary.coveredMessageIDs.contains(id) &&
            (createdAt > boundary.timestamp || (createdAt == boundary.timestamp && id > boundary.messageID))
    }
}

protocol NativeVoiceCallPersistence: Sendable {
    func stageTyped(scope: NativeVoiceCallScope, callID: String, messageID: String,
                    text: String, createdAt: Int) async throws
    func transcript(scope: NativeVoiceCallScope, value: NativeVoiceCallTranscript) async throws
    func lifecycle(scope: NativeVoiceCallScope, callID: String, started: Bool,
                   createdAt: Int, activeSeconds: TimeInterval) async throws
    /// Return the broker ACK frame only after client-encrypted checkpoint storage
    /// and its canonical server receipt. It is never acknowledged speculatively.
    func compression(scope: NativeVoiceCallScope, callID: String,
                     frame: NativeVoiceCallFrame) async throws -> NativeVoiceCallFrame
}
