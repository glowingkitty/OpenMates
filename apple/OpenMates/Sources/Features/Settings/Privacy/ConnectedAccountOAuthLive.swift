// Live transport and ASWebAuthenticationSession authenticator for connected-account OAuth.
// Web source: connectedAccountOAuthService.ts / connectedAccountStorageService.ts (same REST routes).
// Specification: specifications/features/teams/specification.yml

import AuthenticationServices
import Foundation

struct ConnectedAccountLiveTransport: ConnectedAccountOAuthTransport {
    private struct StartBody: Encodable {
        let capabilities: [String]
        let returnPath: String
        let appId: String?
        enum CodingKeys: String, CodingKey { case capabilities, returnPath = "return_path", appId = "app_id" }
    }
    private struct StartResponse: Decodable {
        let authorizationUrl: String
        enum CodingKeys: String, CodingKey { case authorizationUrl = "authorization_url" }
    }
    func startAuthorization(_ request: ConnectedAccountOAuthRequest) async throws -> URL {
        let body = StartBody(
            capabilities: request.capabilities,
            returnPath: ConnectedAccountOAuthRequest.returnPath,
            appId: request.provider == .google ? request.appId : nil
        )
        let response: StartResponse = try await APIClient.shared.request(.post, path: request.provider.startPath, body: body)
        guard let url = URL(string: response.authorizationUrl), url.scheme == "https" else { throw APIError.invalidResponse }
        return url
    }

    func claimHandoff(_ handoffId: String) async throws -> ConnectedAccountHandoff {
        let encoded = handoffId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? handoffId
        let data = try await APIClient.shared.request(
            .post, path: "/v1/connected-account-oauth/handoffs/\(encoded)/claim"
        )
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let providerId = object["provider_id"] as? String,
              let bundle = object["refresh_token_bundle"] as? [String: Any],
              bundle["refresh_token"] != nil,
              let hint = object["account_hint"] as? [String: Any] else { throw APIError.invalidResponse }
        return ConnectedAccountHandoff(
            providerId: providerId,
            refreshTokenBundleJSON: String(decoding: try JSONSerialization.data(withJSONObject: bundle), as: UTF8.self),
            accountHintJSON: String(decoding: try JSONSerialization.data(withJSONObject: hint), as: UTF8.self)
        )
    }

    func createAccount(row: [String: String]) async throws {
        _ = try await APIClient.shared.request(.post, path: PrivacyAPIContract.connectedAccountsPath, body: row)
    }

    func updateAccount(id: String, patch: [String: String]) async throws {
        let values: [String: Any] = patch.mapValues { value -> Any in
            switch value {
            case "false": return false
            case "true": return true
            default: return value
            }
        }
        let body = try JSONSerialization.data(withJSONObject: values)
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        _ = try await APIClient.shared.request(
            .patch, path: "\(PrivacyAPIContract.connectedAccountsPath)/\(encoded)", body: JSONRawBody(data: body)
        )
    }

    func webHost() -> String { ServerProfile.current().webBaseURL.host ?? "" }
}

@MainActor
final class ConnectedAccountWebAuthenticator: NSObject, ConnectedAccountOAuthAuthenticating, ASWebAuthenticationPresentationContextProviding, @unchecked Sendable {
    private var session: ASWebAuthenticationSession?

    func authenticate(url: URL, callbackHost: String) async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            let handler: ASWebAuthenticationSession.CompletionHandler = { callbackURL, error in
                if let callbackURL { continuation.resume(returning: callbackURL) }
                else { continuation.resume(throwing: error ?? ConnectedAccountOAuthError.invalidCallback) }
            }
            let session = ASWebAuthenticationSession(
                url: url, callback: .https(host: callbackHost, path: "/"), completionHandler: handler
            )
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = false
            self.session = session
            if !session.start() { continuation.resume(throwing: ConnectedAccountOAuthError.invalidCallback) }
        }
    }

    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        #if os(macOS)
        return MainActor.assumeIsolated { NSApplication.shared.keyWindow ?? ASPresentationAnchor() }
        #else
        return MainActor.assumeIsolated {
            UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.keyWindow }.first ?? ASPresentationAnchor()
        }
        #endif
    }
}
