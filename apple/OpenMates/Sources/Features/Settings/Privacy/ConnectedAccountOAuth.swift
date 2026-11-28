// Connected accounts connect / OAuth return / disconnect for Apple Settings.
// Web source: frontend/packages/ui/src/services/connectedAccountOAuthService.ts,
// connectedAccountOAuthReturn.ts and components/settings/account/SettingsConnectedAccounts.svelte.
// The backend redirects the browser to the web app return path with `?oauth_handoff_id=` (or an
// error); `ASWebAuthenticationSession` with an https callback on the web host (applinks
// entitlement) intercepts that redirect. The refresh-token row is planned by the shared Rust core
// (`oauthRowPlan`) through `ConnectedAccountRowPlanning`; Swift only runs its steps.
// Specification: specifications/features/teams/specification.yml

import Foundation

enum ConnectedAccountOAuthProvider: String, Equatable, Sendable, CaseIterable {
    case google
    case figma  // figma-visual-proof: not-required (OAuth provider, not a design)

    var startPath: String {
        switch self {
        case .google: return "/v1/provider-oauth/google/calendar/start"
        case .figma: return "/v1/provider-oauth/figma/start"  // figma-visual-proof: not-required (OAuth provider, not a design)
        }
    }
}

struct ConnectedAccountOAuthRequest: Equatable, Sendable {
    let provider: ConnectedAccountOAuthProvider
    let appId: String
    let capabilities: [String]
    /// Set when reconnecting or adding an app to an existing account.
    var connectedAccountId: String?

    static let returnPath = "/#settings/account/connected-accounts"
    static let pendingMaxAge: TimeInterval = 15 * 60
}

enum ConnectedAccountOAuthReturn: Equatable, Sendable {
    case handoff(String)
    case providerError(String)

    /// Parses the redirect the backend sends after provider sign-in; nil when it is not an OAuth return.
    static func parse(_ url: URL) -> ConnectedAccountOAuthReturn? {
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? {
            items.first { $0.name == name }?.value.flatMap { $0.isEmpty ? nil : $0 }
        }
        if let handoff = value("oauth_handoff_id") { return .handoff(handoff) }
        if let error = value("oauth_error") ?? value("error") { return .providerError(error) }
        return nil
    }

    /// The return must be on the web host the sign-in was started for.
    static func isValidCallback(_ url: URL, expectedHost: String) -> Bool {
        url.scheme == "https" && url.host?.lowercased() == expectedHost.lowercased()
    }
}

struct ConnectedAccountHandoff: Equatable, Sendable {
    let providerId: String
    let refreshTokenBundleJSON: String
    let accountHintJSON: String
}

enum ConnectedAccountOAuthError: Error, Equatable {
    case staleOrMissingPending
    case invalidCallback
    case providerDenied
    case rowPlannerUnavailable
}

protocol ConnectedAccountOAuthTransport: Sendable {
    func startAuthorization(_ request: ConnectedAccountOAuthRequest) async throws -> URL
    func claimHandoff(_ handoffId: String) async throws -> ConnectedAccountHandoff
    func createAccount(row: [String: String]) async throws
    func updateAccount(id: String, patch: [String: String]) async throws
    func webHost() -> String
}

protocol ConnectedAccountOAuthAuthenticating: Sendable {
    func authenticate(url: URL, callbackHost: String) async throws -> URL
}

/// Builds the encrypted account row from a claimed handoff via the shared Rust core plan.
protocol ConnectedAccountRowPlanning: Sendable {
    func buildRow(accountId: String, handoff: ConnectedAccountHandoff, capabilities: [String]) async throws -> [String: String]
}

@MainActor
final class ConnectedAccountOAuthCoordinator {
    private let transport: any ConnectedAccountOAuthTransport
    private let authenticator: any ConnectedAccountOAuthAuthenticating
    private let planner: (any ConnectedAccountRowPlanning)?
    private let now: @Sendable () -> Date
    private var pending: (request: ConnectedAccountOAuthRequest, startedAt: Date)?

    init(
        transport: any ConnectedAccountOAuthTransport,
        authenticator: any ConnectedAccountOAuthAuthenticating,
        planner: (any ConnectedAccountRowPlanning)?,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.transport = transport
        self.authenticator = authenticator
        self.planner = planner
        self.now = now
    }

    var canConnect: Bool { planner != nil }

    /// Runs sign-in in the OS web-authentication sheet and stores the resulting account.
    func connect(_ request: ConnectedAccountOAuthRequest) async throws {
        guard let planner else { throw ConnectedAccountOAuthError.rowPlannerUnavailable }
        pending = (request, now())
        let authorizationURL = try await transport.startAuthorization(request)
        let host = transport.webHost()
        let callback = try await authenticator.authenticate(url: authorizationURL, callbackHost: host)
        guard ConnectedAccountOAuthReturn.isValidCallback(callback, expectedHost: host) else {
            pending = nil
            throw ConnectedAccountOAuthError.invalidCallback
        }
        guard let started = pending, now().timeIntervalSince(started.startedAt) <= ConnectedAccountOAuthRequest.pendingMaxAge else {
            pending = nil
            throw ConnectedAccountOAuthError.staleOrMissingPending
        }
        pending = nil
        switch ConnectedAccountOAuthReturn.parse(callback) {
        case .handoff(let handoffId):
            let handoff = try await transport.claimHandoff(handoffId)
            let accountId = request.connectedAccountId ?? UUID().uuidString.lowercased()
            let row = try await planner.buildRow(accountId: accountId, handoff: handoff, capabilities: request.capabilities)
            if request.connectedAccountId != nil {
                try await transport.updateAccount(id: accountId, patch: row)
            } else {
                try await transport.createAccount(row: row)
            }
        case .providerError, .none:
            throw ConnectedAccountOAuthError.providerDenied
        }
    }

    /// Revokes access the same way as web: the row is marked revoked and server access is turned off.
    func disconnect(accountId: String) async throws {
        try await transport.updateAccount(
            id: accountId,
            patch: ["connector_status": "revoked", "server_access_enabled": "false"]
        )
    }
}
