// Bridge tests for the UniFFI OpenMatesCore bindings (plan apple-client-core-migration A1):
// async delivery and main-actor resumption, task cancellation reaching the Rust
// runtime, the credential snapshot round trip, OPAQUE pair login, the
// password-v2 vector and the batched chat decryption calls (A3a: chat-key
// unwrap, chat-list metadata, message window) against the cross-client
// fixtures, all through the generated Swift API. No network.
import CryptoKit
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

    // MARK: - Batched chat decryption (A3a)

    /// `encryption_compatibility/legacy_layouts.json`: wrapping key, content key
    /// and the Format C wrapper of the content key; Format A (OM framing) and
    /// Format B (legacy IV prefix) content under the content key.
    private static let wrappingKey = Data(base64Encoded: "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8=")!
    private static let contentKey = Data(base64Encoded: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")!
    private static let formatCWrapper = "AAECAwQFBgcICQoLXFNfpE4w7eu08MPNKn5QMwNh+3d+BLAGPBTJoaec1YdLiW2dQ1ioc3cx0QtglUzb"
    private static let formatA = "T00JE61lAAECAwQFBgcICQoLK2exeqac733iM/rqxcQZSY7t99Zeqi9ulRSoFUi09w=="
    private static let formatB = "AAECAwQFBgcICQoLK2exeqac733iM/rqxcQaX5E5OyfJaCVgpdr+Oa3Raw=="
    /// `ts_web_policy.json` `chat_content` vectors written by the web
    /// `MessageEncryptor` under key k1.
    private static let webKey = Data(base64Encoded: "IS47SFVib3yJlqOwvcrX5PH+CxglMj9MWWZzgI2ap7Q=")!
    private static let webMatching = "T00G2P2lFnECkEckLwOZMHNP4tpODUK3hdLt1JbM/oZ72nXbuemPNQG5TrmGvrbPcA=="
    private static let webOtherKey = "T0378jglg42GBdqnzRoqEsEEJPj2ezSzDVFR12VNPPM8b5mVceVYbLVAbW57deZ03w=="
    private static let webTampered = "T00G2P2lFnECkEckLwOZMHNP4tpODUK3hdLt1JbM/oZ72nXbuemPNQG5TrmGvrbPcQ=="

    // contract-test: supporting surface=gui.apple assertions=client-core.apple.strangler-order
    @MainActor
    func testBatchUnwrapChatKeysOpensCrossClientWrapperWithPerItemFailures() async throws {
        let results = try await batchUnwrapChatKeys(masterKey: Self.wrappingKey, wrapped: [
            WrappedChatKeyRecord(chatId: "good", encryptedChatKey: Self.formatCWrapper),
            WrappedChatKeyRecord(chatId: "garbage", encryptedChatKey: "not base64 !"),
        ])
        MainActor.assertIsolated()
        XCTAssertEqual(results.map(\.chatId), ["good", "garbage"])
        XCTAssertEqual(results[0].outcome, .unwrapped(chatKey: Self.contentKey))
        XCTAssertEqual(results[1].outcome, .failed(reason: .undecryptable))

        // A wrong master key fails each row; a short one rejects the batch.
        let wrong = try await batchUnwrapChatKeys(masterKey: Data(repeating: 9, count: 32), wrapped: [
            WrappedChatKeyRecord(chatId: "good", encryptedChatKey: Self.formatCWrapper),
        ])
        XCTAssertEqual(wrong[0].outcome, .failed(reason: .undecryptable))
        do {
            _ = try await batchUnwrapChatKeys(masterKey: Data(count: 31), wrapped: [])
            XCTFail("short master key was accepted")
        } catch let error as CoreError {
            guard case .Invalid = error else { return XCTFail("expected CoreError.Invalid, got \(error)") }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.apple.strangler-order
    @MainActor
    func testBatchChatMetadataDecryptsWebVectorsAndTypesFieldFailures() async throws {
        let results = try await batchDecryptChatMetadata(chats: [
            EncryptedChatMetadataRecord(
                chatId: "a", chatKey: Self.webKey, encryptedTitle: Self.webMatching,
                encryptedCategory: nil, encryptedIcon: Self.webOtherKey,
                encryptedChatSummary: Self.webTampered, encryptedActiveFocusId: nil),
            EncryptedChatMetadataRecord(
                chatId: "bad-key", chatKey: Data(count: 5), encryptedTitle: Self.webMatching,
                encryptedCategory: nil, encryptedIcon: nil,
                encryptedChatSummary: nil, encryptedActiveFocusId: nil),
        ])
        XCTAssertEqual(results, [
            ChatMetadataRecord(
                chatId: "a", title: .decrypted(value: "policy ✓ text"), category: nil,
                icon: .failed(reason: .keyMismatch), chatSummary: .failed(reason: .undecryptable),
                activeFocusId: nil),
            ChatMetadataRecord(
                chatId: "bad-key", title: .failed(reason: .invalidKey), category: nil,
                icon: nil, chatSummary: nil, activeFocusId: nil),
        ])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.apple.strangler-order
    @MainActor
    func testBatchMessageWindowReadsLegacyLayoutsAndSwiftWriterOutputInOrder() async throws {
        // The Swift writer still exists for sends; its output must open in the core.
        let key = SymmetricKey(data: Self.contentKey)
        var records = [
            EncryptedMessageRecord(
                messageId: "legacy", encryptedContent: Self.formatA, encryptedPiiMappings: Self.formatB,
                encryptedThinkingContent: nil, encryptedSenderName: nil, encryptedCategory: nil,
                encryptedModelName: "AAAA"),
        ]
        for index in 0..<50 {
            let ciphertext = try await CryptoManager.shared.encryptContent("message \(index)", key: key)
            records.append(EncryptedMessageRecord(
                messageId: "m\(index)", encryptedContent: ciphertext, encryptedPiiMappings: nil,
                encryptedThinkingContent: nil, encryptedSenderName: nil, encryptedCategory: nil,
                encryptedModelName: nil))
        }
        let results = try await batchDecryptMessages(chatKey: Self.contentKey, messages: records)
        MainActor.assertIsolated()
        XCTAssertEqual(results.map(\.messageId), records.map(\.messageId))
        XCTAssertEqual(results[0].content, .decrypted(value: "legacy-format-a"))
        XCTAssertEqual(results[0].piiMappings, .decrypted(value: "legacy-format-b"))
        XCTAssertNil(results[0].thinkingContent)
        XCTAssertEqual(results[0].modelName, .failed(reason: .undecryptable))
        for index in 0..<50 {
            XCTAssertEqual(results[index + 1].content, .decrypted(value: "message \(index)"))
        }
        do {
            _ = try await batchDecryptMessages(chatKey: Data(count: 16), messages: records)
            XCTFail("short chat key was accepted")
        } catch let error as CoreError {
            guard case .Invalid = error else { return XCTFail("expected CoreError.Invalid, got \(error)") }
        }
    }
}
