// Encrypted per-chat model preferences using the connection-bound socket lane.
// Account/server ownership and optimistic versions match the web preference flow.
import Foundation
import CryptoKit

struct ModelPreferenceConnection: Equatable {
    let server: String
    let userID: String
    let socketGeneration: Int
}
// Wire dictionaries are created and read only by the main-actor socket lane.
// Retain that isolation when the lane awaits its cancellable Task result.
@MainActor struct ModelPreferenceWireResponse {
    let type: String
    let fields: [String: Any]
}

@MainActor final class ModelPreferenceEncryptedRepository {
    private let directory: URL
    init(directory: URL) { self.directory = directory }
    private func url(_ scope: ModelPreferenceScope) throws -> URL {
        let data = try JSONEncoder().encode(scope)
        // JSON property ordering must be deterministic for a stable path.
        let object = try JSONSerialization.jsonObject(with: data)
        let canonical = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        let digest = SHA256.hash(data: canonical).map { String(format: "%02x", $0) }.joined()
        return directory.appendingPathComponent(digest).appendingPathExtension("json")
    }
    func read(_ scope: ModelPreferenceScope) throws -> EncryptedModelPreference? {
        let url = try url(scope)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try JSONDecoder().decode(EncryptedModelPreference.self, from: Data(contentsOf: url))
    }
    func write(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) throws {
        guard record.version >= 0, !record.ciphertext.isEmpty,
              record.pendingExpectedVersion.map({ $0 >= 0 && $0 < Int.max && record.version == $0 + 1 }) ?? true else {
            throw ModelPreferenceFailure.invalidPayload
        }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try JSONEncoder().encode(record).write(to: url(scope), options: [.atomic])
    }
    func writeIfNewer(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) throws -> EncryptedModelPreference {
        // One MainActor repository instance serializes the read/replace pair.
        // This file store must not be shared with another writing process.
        if let current = try read(scope), current.version >= record.version { return current }
        try write(record, scope: scope)
        return record
    }
}

@MainActor final class ModelPreferenceNativeAdapters: ModelPreferenceAdapters {
    typealias BoundRequest = @MainActor (ModelPreferenceConnection, String, [String: Any], Set<String>, Duration) async throws -> ModelPreferenceWireResponse
    typealias Mutation = (ModelPreferenceScope, @escaping @MainActor () async throws -> String) async throws -> String
    private let mutation: Mutation
    private let repository: ModelPreferenceEncryptedRepository
    private let currentConnection: () -> ModelPreferenceConnection?
    private let request: BoundRequest
    private let masterKey: (ModelPreferenceScope) async throws -> SymmetricKey
    init(repository: ModelPreferenceEncryptedRepository,
         mutation: @escaping Mutation = { _, operation in try await operation() },
         currentConnection: @escaping () -> ModelPreferenceConnection?,
         request: @escaping BoundRequest,
         masterKey: @escaping (ModelPreferenceScope) async throws -> SymmetricKey) {
        self.repository = repository; self.mutation = mutation; self.currentConnection = currentConnection
        self.request = request; self.masterKey = masterKey
    }
    func withMutationLease(_ scope: ModelPreferenceScope, operation: @escaping @MainActor () async throws -> String) async throws -> String {
        try await mutation(scope, operation)
    }
    // The injected provider obtains the master key for the supplied account/API
    // scope, never an unscoped currently-selected key. Format D matches web.
    func encryptFormatD(_ plaintext: String, scope: ModelPreferenceScope) async throws -> String {
        let key = try await masterKey(scope)
        return try await CryptoManager.shared.encryptWithMasterKey(plaintext, masterKey: key)
    }
    func decryptFormatD(_ ciphertext: String, scope: ModelPreferenceScope) async throws -> String {
        let key = try await masterKey(scope)
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
    }
    func localRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? { try repository.read(scope) }
    func localWrite(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws { try repository.write(record, scope: scope) }
    func localWriteIfNewer(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference {
        try repository.writeIfNewer(record, scope: scope)
    }
    func remoteRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? {
        try await exchange(type: "get_chat_model_preference", payload: ["chat_id": scope.chatID], scope: scope)
    }
    func compareAndSet(_ record: EncryptedModelPreference, expected: Int, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? {
        try await exchange(type: "update_chat_model_preference", payload: [
            "chat_id": scope.chatID,
            "encrypted_selected_ai_model": record.ciphertext,
            "expected_preference_v": expected,
        ], scope: scope)
    }
    private func exchange(type: String, payload: [String: Any], scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? {
        guard let connection = currentConnection(), connection.server == scope.server, connection.userID == scope.userID else {
            throw ModelPreferenceFailure.staleContext
        }
        let expectedEvents: Set<String> = type == "get_chat_model_preference"
            ? ["chat_model_preference"] : ["chat_model_preference_updated", "chat_model_preference_conflict"]
        let result = try await request(connection, type, payload, expectedEvents, .seconds(10))
        guard currentConnection() == connection else { throw ModelPreferenceFailure.staleContext }
        guard result.fields["chat_id"] as? String == scope.chatID else { throw ModelPreferenceFailure.invalidAcknowledgement }
        guard expectedEvents.contains(result.type) else { throw ModelPreferenceFailure.invalidAcknowledgement }
        if result.type == "chat_model_preference_conflict" { return nil }
        guard ["chat_model_preference", "chat_model_preference_updated"].contains(result.type) else {
            throw ModelPreferenceFailure.invalidAcknowledgement
        }
        guard let value = result.fields["preference"], !(value is NSNull) else { return nil }
        guard let record = value as? [String: Any],
              let ciphertext = record["encrypted_selected_ai_model"] as? String, !ciphertext.isEmpty,
              let version = record["preference_v"] as? Int, version >= 0 else {
            throw ModelPreferenceFailure.invalidPayload
        }
        if type == "update_chat_model_preference" {
            guard ciphertext == payload["encrypted_selected_ai_model"] as? String,
                  let expected = payload["expected_preference_v"] as? Int, expected < Int.max,
                  version == expected + 1 else { throw ModelPreferenceFailure.invalidAcknowledgement }
        }
        return EncryptedModelPreference(ciphertext: ciphertext, version: version)
    }
}
