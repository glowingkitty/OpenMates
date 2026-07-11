// Standalone Watch authentication store.
// Persists only the authenticated user metadata and local master key needed to
// bootstrap later Watch chat/offline slices. It intentionally avoids importing
// the full iOS AuthManager dependency graph.
// Chat sync uses the restored WebSocket token from /v1/auth/session after
// cached user and local master-key checks pass.

import CryptoKit
import Foundation

@MainActor
final class WatchAuthStore: ObservableObject {
    enum State: Equatable {
        case initializing
        case unauthenticated
        case authenticated
    }

    @Published private(set) var state: State = .initializing
    @Published private(set) var currentUser: UserProfile?
    @Published private(set) var webSocketToken: String?
    @Published var errorMessage: String?

    private let api = APIClient.shared

    private static let cachedUserDefaultsKey = "openmates.apple.auth.cached_user"

    func checkSession() async {
        guard let user = Self.cachedUser(),
              (try? await CryptoManager.shared.loadMasterKey(for: user.id)) != nil else {
            state = .unauthenticated
            return
        }
        currentUser = user
        switch await refreshSessionToken() {
        case .authenticated, .transientFailure:
            state = .authenticated
        case .revoked:
            await clearRevokedSession(for: user.id)
        }
    }

    func completePairLogin(_ result: PairLoginResult) async throws {
        if result.loginResponse.needsDeviceVerification == true {
            throw AuthError.deviceVerificationRequired
        }
        guard result.loginResponse.success, let user = result.loginResponse.user else {
            throw AuthError.invalidCredentials
        }
        ServerConfiguration.current = result.serverProfile.endpointConfiguration
        WatchServerProfileStore().saveSuccessfulProfile(result.serverProfile)
        try await CryptoManager.shared.saveMasterKey(result.masterKey, for: user.id)
        currentUser = user
        webSocketToken = result.loginResponse.wsToken
        cacheAuthenticatedUser(user)
        state = .authenticated
    }

    private func refreshSessionToken() async -> WatchSessionRefreshDisposition {
        do {
            let response: SessionResponse = try await api.request(
                .post,
                path: "/v1/auth/session",
                body: SessionRequest(
                    sessionId: WatchCompatibleSession.nativeSessionId,
                    deviceInfo: WatchCompatibleSession.makeNativeDeviceInfo()
                )
            )
            guard response.isAuthenticated, let user = response.user else {
                webSocketToken = nil
                errorMessage = response.reAuthReason ?? response.reAuthRequired ?? response.message
                return .revoked
            }
            currentUser = user
            webSocketToken = response.wsToken
            cacheAuthenticatedUser(user)
            errorMessage = nil
            return .authenticated
        } catch {
            webSocketToken = nil
            errorMessage = error.localizedDescription
            return WatchSessionRefreshPolicy.disposition(for: error)
        }
    }

    private func clearRevokedSession(for userId: String) async {
        try? await CryptoManager.shared.deleteMasterKey(for: userId)
        try? await WatchChatOfflineCache().clearSnapshot()
        UserDefaults.standard.removeObject(forKey: Self.cachedUserDefaultsKey)
        OpenMatesSharedEnvironment.defaults.removeObject(forKey: Self.cachedUserDefaultsKey)
        OpenMatesSharedEnvironment.cookieStorage.removeCookies()
        WatchCompatibleSession.resetNativeSessionId()
        WatchServerProfileStore().resetToProduction()
        ServerConfiguration.current = ServerProfile.production.endpointConfiguration
        currentUser = nil
        webSocketToken = nil
        errorMessage = nil
        state = .unauthenticated
    }

    private func cacheAuthenticatedUser(_ user: UserProfile) {
        guard let data = try? JSONEncoder().encode(user) else { return }
        UserDefaults.standard.set(data, forKey: Self.cachedUserDefaultsKey)
        OpenMatesSharedEnvironment.defaults.set(data, forKey: Self.cachedUserDefaultsKey)
    }

    private static func cachedUser() -> UserProfile? {
        guard let data = OpenMatesSharedEnvironment.defaults.data(forKey: cachedUserDefaultsKey)
            ?? UserDefaults.standard.data(forKey: cachedUserDefaultsKey) else { return nil }
        return try? JSONDecoder().decode(UserProfile.self, from: data)
    }
}

private extension HTTPCookieStorage {
    func removeCookies() {
        for cookie in cookies ?? [] {
            deleteCookie(cookie)
        }
    }
}
