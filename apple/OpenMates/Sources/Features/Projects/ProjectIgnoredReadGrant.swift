import CryptoKit
import Foundation

/// One request, one exact ignored path. A private path remains forbidden by
/// the source host's path policy even when this signature is valid.
enum ProjectIgnoredReadGrant {
    static func make(projectID: String, sourceID: String, requestID: String,
                     chatID: String, operationID: String, path: String,
                     projectKey: SymmetricKey,
                     now: Date = Date()) throws -> [String: Any] {
        let identifiers = [projectID, sourceID, requestID, chatID, operationID]
        guard identifiers.allSatisfy({ !$0.isEmpty && $0.count <= 128 }),
              path.utf8.count <= 4096,
              ProjectWorkspacePath.normalized(path) != nil,
              !path.contains(":/") else { throw ProjectsWorkspaceError.invalidContext }
        let expiresAt = Int(now.timeIntervalSince1970 * 1_000) + 5 * 60 * 1_000
        let message: [Any] = ["openmates-ignored-read-v1", projectID, sourceID,
                              requestID, chatID, operationID, path, expiresAt]
        let data = try JSONSerialization.data(withJSONObject: message, options: [.withoutEscapingSlashes])
        let signature = HMAC<SHA256>.authenticationCode(for: data, using: projectKey)
            .map { String(format: "%02x", $0) }.joined()
        return ["projectId": projectID, "sourceId": sourceID, "requestId": requestID,
                "chatId": chatID, "operationId": operationID, "path": path,
                "version": 1, "expiresAt": expiresAt, "signature": signature]
    }
}
