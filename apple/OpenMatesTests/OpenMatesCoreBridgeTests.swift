// Bridge tests for the UniFFI OpenMatesCore bindings (plan apple-client-core-migration A1):
// async delivery and main-actor resumption, task cancellation reaching the Rust
// runtime, the credential snapshot round trip, OPAQUE pair login and the
// password-v2 vector, all through the generated Swift API. No network.
import Foundation
import XCTest
@testable import OpenMates

/// Records `credentialsChanged` calls, which arrive on core runtime threads.
private final class CredentialRecorder: CoreListener, @unchecked Sendable {
    private let lock = NSLock()
    private var revisions: [UInt64] = []

    func credentialsChanged(revision: UInt64) {
        lock.lock()
        revisions.append(revision)
        lock.unlock()
    }

    func seen() -> [UInt64] {
        lock.lock()
        defer { lock.unlock() }
        return revisions
    }
}

final class OpenMatesCoreBridgeTests: XCTestCase {
    private static let apiURL = "https://never-contact.example.invalid"
    private static let pin = "W7P3KQ"
    private static let ids = OpaqueIdentifiersRecord(
        client: "openmates-pair-v2/client/test", server: "openmates-pair-v2/server/test")

    private func makeCore() throws -> OpenMatesCore {
        try OpenMatesCore(config: CoreConfig(
            apiUrl: Self.apiURL, appUrl: "https://app.example.invalid"))
    }

    /// Polls `condition` for up to five seconds; Rust work ends asynchronously.
    @MainActor
    private func waitUntil(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async throws {
        for _ in 0..<500 {
            if condition() { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("condition not reached", file: file, line: line)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.apple.strangler-order
    func testCoreVersionIsNotEmpty() {
        XCTAssertFalse(coreVersion().isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.apple.strangler-order
    @MainActor
    func testProbeRunsOnCoreRuntimeAndResumesOnMainActor() async throws {
        let core = try makeCore()
        let probe = try await core.probe()
        // The continuation hops back to the caller's actor after Rust finishes.
        MainActor.assertIsolated()
        XCTAssertTrue(probe.ranOnCoreRuntime)
        XCTAssertEqual(probe.coreVersion, coreVersion())
        XCTAssertEqual(core.activeOperations(), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.apple.strangler-order
    @MainActor
    func testTaskCancellationStopsRustWorkWithTypedError() async throws {
        let core = try makeCore()
        let cancellation = CoreCancellation()
        let task = Task {
            try await withTaskCancellationHandler {
                try await core.sleepCancellable(milliseconds: 60_000, cancellation: cancellation)
            } onCancel: {
                cancellation.cancel()
            }
        }
        try await waitUntil { core.activeOperations() == 1 }
        task.cancel()
        do {
            try await task.value
            XCTFail("cancelled sleep returned normally")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Cancelled)
        }
        XCTAssertTrue(cancellation.isCancelled())
        try await waitUntil { core.activeOperations() == 0 }
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.credentials.snapshot-boundary
    @MainActor
    func testCredentialSnapshotRoundTripNotifiesAndRejectsStaleRevision() async throws {
        let core = try makeCore()
        let recorder = CredentialRecorder()
        core.setListener(listener: recorder)
        let empty = try await core.credentialSnapshot()
        XCTAssertNil(empty)

        let payload = try testSupportSyntheticCredentialsPayload(apiUrl: Self.apiURL)
        try await core.restoreCredentials(payload: payload)
        let restored = try await core.credentialSnapshot()
        let snapshot = try XCTUnwrap(restored)
        XCTAssertFalse(snapshot.payload.isEmpty)
        let revision = snapshot.revision
        try await waitUntil { recorder.seen().contains(revision) }

        do {
            try await core.acknowledgeCredentials(revision: revision - 1)
            XCTFail("stale revision was acknowledged")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Cancelled)
        }
        try await core.acknowledgeCredentials(revision: revision)

        // A second core restores the stored bytes (app relaunch).
        let relaunched = try makeCore()
        try await relaunched.restoreCredentials(payload: snapshot.payload)
        let again = try await relaunched.credentialSnapshot()
        XCTAssertNotNil(again)

        try await core.clearCredentials()
        try await waitUntil { recorder.seen().contains { $0 > revision } }
        let cleared = try await core.credentialSnapshot()
        XCTAssertNil(cleared)
        core.setListener(listener: nil)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.pair-login.single-use-zk
    func testOpaqueRegistrationAndLoginDeriveEqualSessionKeys() throws {
        let setup = createServerSetup()
        let registration = try startClientRegistration(password: Self.pin)
        let response = try createServerRegistrationResponse(
            serverSetup: setup, userIdentifier: "test",
            registrationRequest: registration.registrationRequest)
        let record = try finishClientRegistration(
            password: Self.pin, clientRegistrationState: registration.clientRegistrationState,
            registrationResponse: response, identifiers: Self.ids)
        let client = try startClientLogin(password: Self.pin)
        let server = try startServerLogin(
            serverSetup: setup, registrationRecord: record,
            startLoginRequest: client.startLoginRequest, userIdentifier: "test",
            identifiers: Self.ids)
        let clientFinish = try finishClientLogin(
            password: Self.pin, clientLoginState: client.clientLoginState,
            loginResponse: server.loginResponse, identifiers: Self.ids)
        let serverKey = try finishServerLogin(
            serverLoginState: server.serverLoginState,
            finishLoginRequest: clientFinish.finishLoginRequest, identifiers: Self.ids)
        XCTAssertFalse(serverKey.isEmpty)
        XCTAssertEqual(clientFinish.sessionKey, serverKey)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.pair-login.single-use-zk
    func testWrongPinFailsWithTypedCryptoError() throws {
        let setup = createServerSetup()
        let registration = try startClientRegistration(password: Self.pin)
        let response = try createServerRegistrationResponse(
            serverSetup: setup, userIdentifier: "test",
            registrationRequest: registration.registrationRequest)
        let record = try finishClientRegistration(
            password: Self.pin, clientRegistrationState: registration.clientRegistrationState,
            registrationResponse: response, identifiers: Self.ids)
        let client = try startClientLogin(password: "X9Z9Z9")
        let server = try startServerLogin(
            serverSetup: setup, registrationRecord: record,
            startLoginRequest: client.startLoginRequest, userIdentifier: "test",
            identifiers: Self.ids)
        XCTAssertThrowsError(try finishClientLogin(
            password: "X9Z9Z9", clientLoginState: client.clientLoginState,
            loginResponse: server.loginResponse, identifiers: Self.ids)) { error in
            XCTAssertEqual(error as? CoreError, .Crypto)
        }
        // The app wrapper keeps its existing error for the same failure.
        XCTAssertThrowsError(try PairOpaque.clientLoginFinish(
            pin: "X9Z9Z9", state: client.clientLoginState,
            loginResponse: server.loginResponse, identifiers: Self.ids)) { error in
            XCTAssertTrue(error is PairOpaqueError)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.keys.client-wrapped
    func testPasswordV2MatchesCrossPlatformVector() throws {
        let keys = try derivePasswordV2(
            password: "Correct Horse Battery Staple!", salt: Data((0..<16).map(UInt8.init)))
        XCTAssertEqual(keys.authKey.base64URLEncodedString(),
                       "vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o")
        XCTAssertEqual(keys.wrapKey.base64URLEncodedString(),
                       "d8EIpdqJ7JF5dhaA6xIcpQJTNu9kZGZimmu--sR-2Hc")
        XCTAssertThrowsError(try derivePasswordV2(password: "password", salt: Data(count: 8))) { error in
            guard case .Invalid = error as? CoreError else {
                return XCTFail("expected CoreError.Invalid, got \(error)")
            }
        }
    }
}
