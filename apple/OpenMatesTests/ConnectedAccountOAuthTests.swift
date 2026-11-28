// Unit coverage for Apple connected-account OAuth return parsing, state check and connect/disconnect.
// Web source: connectedAccountOAuthReturn.ts, connectedAccountOAuthService.ts.
// Uses fake transport/authenticator/planner; no network or provider data.

import Foundation
import XCTest
@testable import OpenMates

private actor Recorder {
    var created: [[String: String]] = []
    var updated: [(String, [String: String])] = []
    func create(_ row: [String: String]) { created.append(row) }
    func update(_ id: String, _ patch: [String: String]) { updated.append((id, patch)) }
}

private struct FakeTransport: ConnectedAccountOAuthTransport {
    let recorder: Recorder
    func startAuthorization(_ request: ConnectedAccountOAuthRequest) async throws -> URL { URL(string: "https://example.org/auth")! }
    func claimHandoff(_ handoffId: String) async throws -> ConnectedAccountHandoff {
        ConnectedAccountHandoff(providerId: "my_provider", refreshTokenBundleJSON: "{}", accountHintJSON: "{}")
    }
    func createAccount(row: [String: String]) async throws { await recorder.create(row) }
    func updateAccount(id: String, patch: [String: String]) async throws { await recorder.update(id, patch) }
    func webHost() -> String { "app.example.org" }
}

private struct FakeAuthenticator: ConnectedAccountOAuthAuthenticating {
    let callback: URL
    func authenticate(url: URL, callbackHost: String) async throws -> URL { callback }
}

private struct FakePlanner: ConnectedAccountRowPlanning {
    func buildRow(accountId: String, handoff: ConnectedAccountHandoff, capabilities: [String]) async throws -> [String: String] {
        ["id": accountId, "provider": handoff.providerId]
    }
}

@MainActor
final class ConnectedAccountOAuthTests: XCTestCase {
    private func coordinator(callback: String, recorder: Recorder, planner: (any ConnectedAccountRowPlanning)? = FakePlanner()) -> ConnectedAccountOAuthCoordinator {
        ConnectedAccountOAuthCoordinator(
            transport: FakeTransport(recorder: recorder),
            authenticator: FakeAuthenticator(callback: URL(string: callback)!),
            planner: planner
        )
    }
    private let request = ConnectedAccountOAuthRequest(provider: .google, appId: "calendar", capabilities: ["read"])

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testParsesHandoffAndProviderErrorReturns() {
        XCTAssertEqual(ConnectedAccountOAuthReturn.parse(URL(string: "https://app.example.org/?oauth_handoff_id=h1#settings")!), .handoff("h1"))
        XCTAssertEqual(ConnectedAccountOAuthReturn.parse(URL(string: "https://app.example.org/?error=access_denied")!), .providerError("access_denied"))
        XCTAssertNil(ConnectedAccountOAuthReturn.parse(URL(string: "https://app.example.org/")!))
        XCTAssertTrue(ConnectedAccountOAuthReturn.isValidCallback(URL(string: "https://App.Example.org/")!, expectedHost: "app.example.org"))
        XCTAssertFalse(ConnectedAccountOAuthReturn.isValidCallback(URL(string: "https://evil.example.net/?oauth_handoff_id=h")!, expectedHost: "app.example.org"))
        XCTAssertFalse(ConnectedAccountOAuthReturn.isValidCallback(URL(string: "http://app.example.org/")!, expectedHost: "app.example.org"))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testConnectCreatesAccountAndReconnectUpdatesExisting() async throws {
        let recorder = Recorder()
        try await coordinator(callback: "https://app.example.org/?oauth_handoff_id=h1", recorder: recorder).connect(request)
        var created = await recorder.created
        XCTAssertEqual(created.count, 1)
        XCTAssertEqual(created.first?["provider"], "my_provider")

        var reconnect = request
        reconnect.connectedAccountId = "acct-1"
        try await coordinator(callback: "https://app.example.org/?oauth_handoff_id=h2", recorder: recorder).connect(reconnect)
        created = await recorder.created
        let updated = await recorder.updated
        XCTAssertEqual(created.count, 1)
        XCTAssertEqual(updated.first?.0, "acct-1")
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testRejectsWrongHostProviderErrorAndMissingPlanner() async {
        let recorder = Recorder()
        await assertThrows(ConnectedAccountOAuthError.invalidCallback) {
            try await self.coordinator(callback: "https://evil.example.net/?oauth_handoff_id=h", recorder: recorder).connect(self.request)
        }
        await assertThrows(ConnectedAccountOAuthError.providerDenied) {
            try await self.coordinator(callback: "https://app.example.org/?error=access_denied", recorder: recorder).connect(self.request)
        }
        await assertThrows(ConnectedAccountOAuthError.rowPlannerUnavailable) {
            try await self.coordinator(callback: "https://app.example.org/?oauth_handoff_id=h", recorder: recorder, planner: nil).connect(self.request)
        }
        let created = await recorder.created
        XCTAssertTrue(created.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testStalePendingIsRejected() async {
        let recorder = Recorder()
        let clock = ClockBox()
        let sut = ConnectedAccountOAuthCoordinator(
            transport: FakeTransport(recorder: recorder),
            authenticator: SlowAuthenticator(clock: clock),
            planner: FakePlanner(),
            now: { clock.now }
        )
        await assertThrows(ConnectedAccountOAuthError.staleOrMissingPending) { try await sut.connect(self.request) }
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testDisconnectMarksRowRevokedLikeWeb() async throws {
        let recorder = Recorder()
        try await coordinator(callback: "https://app.example.org/", recorder: recorder).disconnect(accountId: "acct-9")
        let updated = await recorder.updated
        XCTAssertEqual(updated.first?.0, "acct-9")
        XCTAssertEqual(updated.first?.1, ["connector_status": "revoked", "server_access_enabled": "false"])
    }

    private func assertThrows(_ expected: ConnectedAccountOAuthError, _ body: () async throws -> Void) async {
        do { try await body(); XCTFail("expected \(expected)") }
        catch { XCTAssertEqual(error as? ConnectedAccountOAuthError, expected) }
    }
}

private final class ClockBox: @unchecked Sendable {
    var now = Date(timeIntervalSince1970: 1_000)
}

private struct SlowAuthenticator: ConnectedAccountOAuthAuthenticating {
    let clock: ClockBox
    func authenticate(url: URL, callbackHost: String) async throws -> URL {
        clock.now = clock.now.addingTimeInterval(ConnectedAccountOAuthRequest.pendingMaxAge + 1)
        return URL(string: "https://app.example.org/?oauth_handoff_id=h")!
    }
}
