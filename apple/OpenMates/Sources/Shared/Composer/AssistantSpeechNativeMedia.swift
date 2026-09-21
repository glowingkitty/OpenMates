import Foundation

@MainActor
struct AssistantSpeechNativeMedia {
    // Host's existing scoped embed sync/decryption service supplies the record.
    // Never reinterpret the asset ID as a public URL or bypass account ownership.
    var resolveEmbed: @MainActor (AssistantSpeechScope, String) async throws -> EmbedRecord
    var isCurrent: @MainActor (AssistantSpeechScope) -> Bool
    func audio(_ scope: AssistantSpeechScope, assetID: String) async throws -> Data {
        try Task.checkCancellation()
        guard isCurrent(scope) else { throw CancellationError() }
        let embed = try await resolveEmbed(scope, assetID)
        guard isCurrent(scope), let raw = embed.rawData,
              let key = EmbedMediaPayload.string(raw, keys: ["aes_key"]),
              let s3Key = EmbedMediaPayload.s3Key(from: raw) else {
            throw CocoaError(.fileReadNoSuchFile)
        }
        let data = try await S3MediaClient.shared.fetchAndDecrypt(
            s3Url: EmbedMediaPayload.s3URL(from: raw) ?? "", aesKeyHex: key,
            aesNonceHex: EmbedMediaPayload.string(raw, keys: ["aes_nonce"]),
            encryption: EmbedMediaPayload.encryption(from: raw), s3Key: s3Key,
            cacheNamespace: "assistant-speech:\(scope.accountID):\(scope.serverID):\(scope.sessionID?.uuidString ?? "")")
        try Task.checkCancellation()
        guard isCurrent(scope) else { throw CancellationError() }
        return data
    }
}
