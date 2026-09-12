import Foundation
import CryptoKit

// Narrow repository seam includes the actual backend field rather than an
// unencrypted UserDefaults surrogate. Native Chat/offline DTOs must roundtrip it.
struct AssistantSpeechMetadata {
    let encryptedPreference: String?
    let encryptedChatKey: String?
    let teamID: String?
    let messagesVersion: Int
    let titleVersion: Int
    let metadataVersion: Int
    let lastEditedTimestamp: Int
}
@MainActor
final class AssistantSpeechPreferenceAdapter {
    struct Dependencies {
        var isCurrent: @MainActor (AssistantSpeechScope) -> Bool
        var metadata: @MainActor (AssistantSpeechScope) async throws -> AssistantSpeechMetadata?
        var chatKey: @MainActor (AssistantSpeechScope) async throws -> SymmetricKey
        // Must register its encrypted_metadata_stored waiter BEFORE sending,
        // match chat_id + minimum metadata_v, pin socket, reject disconnect.
        var sendMetadataAndWait: @MainActor (AssistantSpeechScope, [String: Any], Int) async throws -> Int
        var storeCiphertext: @MainActor (AssistantSpeechScope, String, Int) async throws -> Void
    }
    private let dependencies: Dependencies
    private var intents: [AssistantSpeechScope: Bool] = [:]
    private var generation = UUID()
    private var writing = Set<AssistantSpeechScope>()
    init(dependencies: Dependencies) { self.dependencies = dependencies }
    func clear() { generation = UUID(); intents.removeAll(); writing.removeAll() }
    func hasIntent(_ scope: AssistantSpeechScope) -> Bool { intents[scope] != nil }
    func read(_ scope: AssistantSpeechScope) async throws -> Bool {
        let token = generation
        try check(scope, token)
        let row = try await dependencies.metadata(scope)
        try check(scope, token)
        guard let ciphertext = row?.encryptedPreference else { return intents[scope] ?? false }
        let key = try await dependencies.chatKey(scope)
        try check(scope, token)
        let value = try await Self.decrypt(ciphertext, key: key)
        try check(scope, token)
        guard value == "true" || value == "false" else { throw CocoaError(.coderReadCorrupt) }
        return value == "true"
    }
    func write(_ scope: AssistantSpeechScope, enabled: Bool) async throws {
        let token = generation
        try check(scope, token)
        guard writing.insert(scope).inserted else { throw AssistantSpeechFailure.preferenceBusy }
        defer { if generation == token { writing.remove(scope) } }
        let row = try await dependencies.metadata(scope)
        try check(scope, token)
        // Draft intent is memory only. A failed saved write must not leave a
        // hidden intent that is silently promoted after the UI rolled back.
        guard let row, row.messagesVersion > 0 else { intents[scope] = enabled; return }
        let key = try await dependencies.chatKey(scope)
        try check(scope, token)
        let ciphertext = try await Self.encrypt(enabled ? "true" : "false", key: key)
        try check(scope, token)
        var payload: [String: Any] = ["chat_id": scope.chatID,
            "encrypted_auto_speak_response": ciphertext,
            "versions": ["messages_v": row.messagesVersion, "title_v": row.titleVersion,
                "metadata_v": row.metadataVersion, "last_edited_overall_timestamp": row.lastEditedTimestamp]]
        if let value = row.encryptedChatKey { payload["encrypted_chat_key"] = value }
        if let value = row.teamID { payload["team_id"] = value }
        let version = try await dependencies.sendMetadataAndWait(scope, payload, row.metadataVersion + 1)
        try check(scope, token)
        guard version > row.metadataVersion else { throw AssistantSpeechFailure.invalidAcknowledgement }
        try await dependencies.storeCiphertext(scope, ciphertext, version)
        try check(scope, token)
        intents.removeValue(forKey: scope)
    }
    /// Resolve the source preference independently of a mounted speech control.
    /// Preserve draft intent and reject a concurrent toggle instead of guessing false.
    func transferDraft(from source: AssistantSpeechScope, to destination: AssistantSpeechScope) async throws {
        let token = generation
        try check(source, token); try check(destination, token)
        guard source != destination else { return }
        guard writing.insert(source).inserted else { throw AssistantSpeechFailure.preferenceBusy }
        defer { if generation == token { writing.remove(source) } }
        let enabled = try await read(source)
        try check(source, token); try check(destination, token)
        try await write(destination, enabled: enabled)
        try check(source, token); try check(destination, token)
        // Source intent remains available if the following message preparation fails.
    }
    func promote(_ scope: AssistantSpeechScope) async throws {
        let token = generation
        try check(scope, token)
        guard !writing.contains(scope), let value = intents[scope] else { return }
        let row = try await dependencies.metadata(scope)
        try check(scope, token)
        guard let row, row.messagesVersion > 0 else { return }
        // Existing authoritative preference wins over an old draft intent.
        guard row.encryptedPreference == nil else { intents.removeValue(forKey: scope); return }
        try await write(scope, enabled: value)
    }
    private func check(_ scope: AssistantSpeechScope, _ token: UUID) throws {
        try Task.checkCancellation()
        guard generation == token, dependencies.isCurrent(scope) else { throw CancellationError() }
    }
    // Use the same OM+fingerprint chat-key format as MessageEncryptor.ts.
    // CryptoManager also reads legacy nonce-prefixed records; no duplicate parser.
    static func encrypt(_ value: String, key: SymmetricKey) async throws -> String {
        try await CryptoManager.shared.encryptContent(value, key: key)
    }
    static func decrypt(_ value: String, key: SymmetricKey) async throws -> String {
        try await CryptoManager.shared.decryptContent(base64String: value, key: key)
    }
}
