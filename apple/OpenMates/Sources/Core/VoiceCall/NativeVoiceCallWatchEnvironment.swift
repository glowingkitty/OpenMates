// Web source: frontend/packages/ui/src/services/voiceCallPrivacy.ts, voiceCall.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy.first-call-warning, video-call.chat.fixed-binding,
// video-call.provider.boundary, video-call.privacy
#if os(watchOS)
import Foundation

@MainActor
enum NativeVoiceCallWatchEnvironment {
    private struct Acknowledgment: Decodable {
        let version: Int
        let acknowledged: Bool
        let acknowledgedAt: Int?
    }
    private struct Accept: Codable, Sendable { let version = 1 }

    static func make(auth: WatchAuthStore,
        context: @escaping @MainActor @Sendable (NativeVoiceCallScope) throws -> WatchChatRequestContext,
        consentDecision: @escaping @MainActor @Sendable () async -> Bool,
        loadContext: @escaping @Sendable (NativeVoiceCallScope) async throws -> NativeVoiceCallContext,
        prepare: @escaping @Sendable (NativeVoiceCallScope) async throws -> Void
    ) -> NativeVoiceCallEnvironment {
        let current: @Sendable (NativeVoiceCallScope) async -> Bool = { @MainActor [weak auth] scope in
            guard let auth, auth.state == .authenticated, auth.currentUser?.id == scope.accountID,
                  let request = try? context(scope), request.profile.id == scope.profileID,
                  (try? request.check()) != nil else { return false }
            return true
        }
        return NativeVoiceCallEnvironment(isCurrent: current, ensureConsent: { @MainActor scope in
            guard await current(scope) else { throw NativeVoiceCallError.scopeChanged }
            let request = try context(scope)
            try await ensureSavedConsent(auth: auth, request: request, decision: consentDecision)
            guard await current(scope) else { throw NativeVoiceCallError.scopeChanged }
        }, authentication: { @MainActor [weak auth] scope in
            guard let auth, await current(scope) else { throw NativeVoiceCallError.scopeChanged }
            if !auth.isVerifiedOnline || tokenNeedsRefresh(auth.webSocketToken) { await auth.checkSession() }
            guard await current(scope), auth.isVerifiedOnline, let token = auth.webSocketToken,
                  !tokenNeedsRefresh(token) else { throw NativeVoiceCallError.callUnavailable }
            let request = try context(scope)
            return NativeVoiceCallAuthentication(apiBaseURL: request.profile.apiBaseURL,
                webOrigin: request.profile.webBaseURL.absoluteString,
                sessionID: WatchCompatibleSession.nativeSessionId, webSocketToken: token,
                nativeHeaders: APIClient.nativeClientHeaders)
        }, context: loadContext, prepare: prepare)
    }
    private static func checkConsentOwner(auth: WatchAuthStore, request: WatchChatRequestContext) throws {
        try request.check()
        guard auth.state == .authenticated, auth.currentUser?.id == request.accountID,
              auth.isVerifiedOnline else { throw NativeVoiceCallError.scopeChanged }
    }
    static func hasSavedConsent(auth: WatchAuthStore, request: WatchChatRequestContext) async throws -> Bool {
        try checkConsentOwner(auth: auth, request: request)
        let response: Data
        do {
            response = try await APIClient.shared.requestForVerifiedWatchSession(.get,
                path: "/v1/settings/voice-google-processing-ack", serverProfile: request.profile,
                validate: { try request.check() })
        } catch { throw NativeVoiceCallError.consentUnavailable }
        try checkConsentOwner(auth: auth, request: request)
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let ack = try? decoder.decode(Acknowledgment.self, from: response), ack.version == 1,
              !ack.acknowledged || (ack.acknowledgedAt ?? 0) > 0 else { throw NativeVoiceCallError.consentUnavailable }
        return ack.acknowledged
    }
    /// Shared saved-acknowledgement path for normal calls and the explicit
    /// development diagnostics consent action. This never activates audio.
    static func ensureSavedConsent(auth: WatchAuthStore, request: WatchChatRequestContext,
                                   decision: @escaping @MainActor @Sendable () async -> Bool) async throws {
        if try await hasSavedConsent(auth: auth, request: request) { return }
        guard await decision() else { throw NativeVoiceCallError.consentRequired }
        try Task.checkCancellation()
        try checkConsentOwner(auth: auth, request: request)
        let written: Data
        do {
            written = try await APIClient.shared.requestForVerifiedWatchSession(.post,
                path: "/v1/settings/voice-google-processing-ack", serverProfile: request.profile,
                body: Accept(), validate: { try request.check() })
        } catch { throw NativeVoiceCallError.consentUnavailable }
        try checkConsentOwner(auth: auth, request: request)
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let stored = try? decoder.decode(Acknowledgment.self, from: written),
              stored.version == 1, stored.acknowledged, (stored.acknowledgedAt ?? 0) > 0
        else { throw NativeVoiceCallError.consentUnavailable }
    }
    static func tokenNeedsRefresh(_ token: String?) -> Bool {
        guard let token, !token.isEmpty else { return true }
        let parts = token.split(separator: ":", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count == 3 else { return false }
        guard let expiry = TimeInterval(parts[1]) else { return true }
        return expiry <= Date().timeIntervalSince1970 + 30
    }
}
#endif
