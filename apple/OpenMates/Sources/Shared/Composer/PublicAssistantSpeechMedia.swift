import Foundation
import CryptoKit

// Web: assistantSpeechController.ts playPublicExample. Published immutable audio
// is public; preserve signed/proxy URL queries and never attach account cookies.
@MainActor
enum PublicAssistantSpeechMedia {
    static func fetch(_ segment: PublicAssistantSpeechSegment) async throws -> Data {
        guard segment.valid, let url = PublicAssistantSpeechSegment.url(segment.publicUrl) else {
            throw CocoaError(.fileReadNoPermission)
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        request.httpShouldHandleCookies = false
        let (bytes, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              response.url?.scheme == "https", !bytes.isEmpty, bytes.count <= 67_108_864 else {
            throw CocoaError(.fileReadNoSuchFile)
        }
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        guard digest == segment.sha256.lowercased() else { throw CocoaError(.fileReadCorruptFile) }
        return bytes
    }
}
