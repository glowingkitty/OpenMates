// Web source: frontend/packages/ui/src/services/voiceCallPrivacy.ts, voiceCall.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy.first-call-warning, video-call.chat.fixed-binding,
// video-call.provider.boundary, video-call.privacy

#if !os(watchOS)
import Foundation

/// Uses the existing authenticated Apple APIClient and token refresh. The UI
/// injects one explicit disclosure decision; returning false aborts before audio.
@MainActor
enum NativeVoiceCallAppleEnvironment {
    private struct Acknowledgment: Decodable {
        let version: Int
        let acknowledged: Bool
        let acknowledgedAt: Int?
    }
    private struct Accept: Encodable { let version = 2 }

    static func make(authManager: AuthManager, profile: ServerProfile,
        consentDecision: @escaping @MainActor @Sendable () async -> Bool,
        context: @escaping @Sendable (NativeVoiceCallScope) async throws -> NativeVoiceCallContext
    ) -> NativeVoiceCallEnvironment {
        let current: @Sendable (NativeVoiceCallScope) async -> Bool = { @MainActor [weak authManager] scope in
            guard let authManager else { return false }
            return authManager.currentUser?.id == scope.accountID && scope.profileID == profile.id &&
                OfflineStore.shared.scopeGeneration == scope.workspaceGeneration &&
                ServerProfile.current() == profile && authManager.state == .authenticated
        }
        return NativeVoiceCallEnvironment(isCurrent: current, ensureConsent: { scope in
            guard await current(scope) else { throw NativeVoiceCallError.scopeChanged }
            let data: Data
            do {
                data = try await APIClient.shared.request(.get, path: "/v1/settings/voice-processing-ack",
                    serverProfile: profile, expectedAccountID: scope.accountID,
                    expectedScope: scope.workspaceGeneration)
            } catch { throw NativeVoiceCallError.consentUnavailable }
            guard await current(scope) else { throw NativeVoiceCallError.scopeChanged }
            let ack: Acknowledgment
            do { ack = try JSONDecoder.snakeCase.decode(Acknowledgment.self, from: data) }
            catch { throw NativeVoiceCallError.consentUnavailable }
            guard ack.version == 2 else { throw NativeVoiceCallError.consentUnavailable }
            if ack.acknowledged, let timestamp = ack.acknowledgedAt, timestamp > 0 { return }
            guard !ack.acknowledged else { throw NativeVoiceCallError.consentUnavailable }
            guard await consentDecision() else { throw NativeVoiceCallError.consentRequired }
            guard await current(scope) else { throw NativeVoiceCallError.scopeChanged }
            let response: Data
            do {
                response = try await APIClient.shared.request(.post, path: "/v1/settings/voice-processing-ack",
                    serverProfile: profile, body: Accept(), expectedAccountID: scope.accountID,
                    expectedScope: scope.workspaceGeneration)
            } catch { throw NativeVoiceCallError.consentUnavailable }
            guard await current(scope) else { throw NativeVoiceCallError.scopeChanged }
            guard let written = try? JSONDecoder.snakeCase.decode(Acknowledgment.self, from: response),
                  written.version == 2, written.acknowledged, (written.acknowledgedAt ?? 0) > 0
            else { throw NativeVoiceCallError.consentUnavailable }
        }, authentication: { @MainActor [weak authManager] scope in
            guard let authManager, await current(scope) else { throw NativeVoiceCallError.scopeChanged }
            if AudioRealtimeTranscriptionClient.tokenNeedsRefresh(authManager.webSocketToken) ||
                authManager.sessionValidationState != .onlineAuthenticated {
                await authManager.validateSessionAfterOfflineBootstrap()
            }
            guard await current(scope), authManager.sessionValidationState == .onlineAuthenticated,
                  let token = authManager.webSocketToken,
                  !AudioRealtimeTranscriptionClient.tokenNeedsRefresh(token)
            else { throw NativeVoiceCallError.callUnavailable }
            return NativeVoiceCallAuthentication(apiBaseURL: profile.apiBaseURL,
                webOrigin: profile.webBaseURL.absoluteString, sessionID: AuthManager.nativeSessionId,
                webSocketToken: token, nativeHeaders: APIClient.nativeClientHeaders)
        }, context: context)
    }
}

private extension JSONDecoder {
    static var snakeCase: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
#endif
