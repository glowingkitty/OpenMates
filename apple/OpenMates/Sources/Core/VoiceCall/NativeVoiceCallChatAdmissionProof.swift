// Web source: frontend/packages/ui/src/services/voiceCallMessages.ts
// Canonical backend: encrypted_chat_metadata_handler.py, chats.py list_chats
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.compressed-context,
// video-call.privacy, video-call.lifecycle.recovery-and-billing
import Foundation

/// A queue ACK proves receipt only. New-chat provider admission additionally
/// requires a fresh authenticated durable read with this exact wrapper/version
/// tuple. The read must bypass queued cache metadata (Watch uses HTTPS /chats).
struct NativeVoiceCallChatAdmissionProof: Sendable {
    struct Versions: Equatable, Sendable {
        let messages: Int
        let title: Int
        let metadata: Int
    }
    struct Expected: Sendable {
        let chatID: String
        let encryptedChatKey: String
        let versions: Versions
    }
    let readAuthoritative: @Sendable () async throws -> [NativeVoiceCallFrame]
    let checkCurrent: @Sendable () async throws -> Void
    let sleep: @Sendable (Duration) async throws -> Void

    init(readAuthoritative: @escaping @Sendable () async throws -> [NativeVoiceCallFrame],
         checkCurrent: @escaping @Sendable () async throws -> Void,
         sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }) {
        self.readAuthoritative = readAuthoritative; self.checkCurrent = checkCurrent; self.sleep = sleep
    }

    static func versions(_ frame: NativeVoiceCallFrame) throws -> Versions {
        func integer(_ name: String) throws -> Int {
            guard let value = frame[name]?.number, value >= 0,
                  value <= 9_007_199_254_740_991, value.rounded(.down) == value
            else { throw NativeVoiceCallError.persistenceFailed }
            return Int(value)
        }
        return try .init(messages: integer("messages_v"), title: integer("title_v"), metadata: integer("metadata_v"))
    }
    /// Also used for fresh focus/Mate metadata, where concurrent newer versions
    /// may be accepted only when they meet the known prepared-chat lower bound.
    static func validate(_ frame: NativeVoiceCallFrame, expected: Expected,
                         exactVersions: Bool) throws -> Versions {
        guard (frame["id"]?.string ?? frame["chat_id"]?.string) == expected.chatID,
              !expected.encryptedChatKey.isEmpty,
              frame["encrypted_chat_key"]?.string == expected.encryptedChatKey,
              frame["team_id"] == nil || frame["team_id"] == .null,
              frame["chat_visibility"]?.string != "direct"
        else { throw NativeVoiceCallError.persistenceFailed }
        let current = try versions(frame)
        if exactVersions {
            guard current == expected.versions else { throw NativeVoiceCallError.persistenceFailed }
        } else {
            guard current.messages >= expected.versions.messages, current.title >= expected.versions.title,
                  current.metadata >= expected.versions.metadata else { throw NativeVoiceCallError.persistenceFailed }
        }
        return current
    }
    /// At most four fresh reads under the controller's existing ten-second
    /// admission deadline. Missing rows may still be queued; malformed or stale
    /// rows fail immediately, and no result means no provider admission.
    func confirm(queueReceipt: NativeVoiceCallFrame, expected: Expected) async throws -> NativeVoiceCallFrame {
        try await checkCurrent()
        guard queueReceipt["type"]?.string == "encrypted_metadata_stored",
              queueReceipt["chat_id"]?.string == expected.chatID,
              queueReceipt["status"]?.string == "queued_for_storage",
              let accepted = queueReceipt["versions"]?.object,
              try Self.versions(accepted) == expected.versions
        else { throw NativeVoiceCallError.persistenceFailed }
        for attempt in 0..<4 {
            try await checkCurrent()
            let rows = try await readAuthoritative()
            try await checkCurrent()
            guard rows.count <= 100 else { throw NativeVoiceCallError.persistenceFailed }
            let matches = rows.filter { ($0["id"]?.string ?? $0["chat_id"]?.string) == expected.chatID }
            guard matches.count <= 1 else { throw NativeVoiceCallError.persistenceFailed }
            if let row = matches.first {
                _ = try Self.validate(row, expected: expected, exactVersions: true)
                return row
            }
            if attempt < 3 { try await sleep(.milliseconds(250)) }
        }
        throw NativeVoiceCallError.persistenceFailed
    }
}
