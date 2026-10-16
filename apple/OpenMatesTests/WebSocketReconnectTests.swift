// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.session.authoritative-enforcement, auth.session.isolation
// Specification: specifications/architecture/sync/specification.yml
// Assertions: sync.surface.semantic-parity
import XCTest
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif
@testable import OpenMates

@MainActor
final class WebSocketReconnectTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
    func testBlockedCachedIdentityCannotReconnectOnRepeatedForegroundAttempts() async throws {
        let auth = AuthManager(sessionValidator: { _, _ in
            throw APIError.httpError(status: 401, message: "Expired")
        })
        auth.currentUser = try JSONDecoder().decode(UserProfile.self,
            from: Data(#"{"id":"cached-account","username":"Fixture"}"#.utf8))
        auth.state = .authenticated
        await auth.validateSessionAfterOfflineBootstrap()
        let manager = WebSocketManager()
        let generation = manager.transportGeneration
        for _ in 0..<20 { manager.connect(sessionId: AuthManager.nativeSessionId, token: "stale-token") }
        XCTAssertEqual(manager.connectionState, .disconnected)
        XCTAssertEqual(manager.transportGeneration, generation, "Blocked attempts must preserve pending ciphertext ownership")
        XCTAssertFalse(auth.hasNetworkAuthority)
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testCacheStatusAndCorrelatedReceiptsNeverReloadTheChatCatalog() {
        for type in ["cache_primed", "cache_status_response", "sync_status_response", "offline_sync_complete",
                     "chat_content_batch_response", "load_more_chats_response", "future_status_notice"] {
            XCTAssertEqual(NativeSyncCatalogWork.classify(type), .control, type)
        }
        for type in ["phase_1_last_chat_ready", "phase_1b_chat_content_ready", "background_message_sync",
                     "phase_2_last_20_chats_ready", "phase_3_last_100_chats_ready", "sync_metadata_chats_response",
                     "code_run_outputs_sync_ready", "phased_sync_complete"] {
            XCTAssertEqual(NativeSyncCatalogWork.classify(type), .content, type)
        }
        XCTAssertEqual(NativeSyncCatalogWork.classify("initial_sync_response"), .legacyFallback)
        XCTAssertEqual(NativeSyncCatalogWork.classify("initial_sync_error"), .legacyFallback)
        XCTAssertEqual(NativeSyncCatalogWork.fallbackLimit, 20)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testTypedBulkSyncDecodeLeavesUIExecutorAndPreservesSnakeCaseMetadata() async throws {
        let payload: [String: Any] = ["total_chat_count": 20,
            "deleted_chat_ids": ["deleted-synthetic"],
            "chats": (0..<20).map { ["chat_details": ["id": "synthetic-\($0)",
                "encrypted_title": String(repeating: "ciphertext", count: 2_000)]] }]
        let raw = try JSONSerialization.data(withJSONObject: payload)
        let decoded = try await NativeSyncPayloadDecoder.shared.decode(PhaseBulkSyncPayload.self, from: raw)
        XCTAssertFalse(decoded.decodedOnMainThread)
        XCTAssertEqual(decoded.value.totalChatCount, 20)
        XCTAssertEqual(decoded.value.deletedChatIds, ["deleted-synthetic"])
        XCTAssertEqual(decoded.value.chats?.count, 20)
        XCTAssertEqual(decoded.value.chats?.first?.chatDetails?.id, "synthetic-0")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testCheckpointReceiptPreservesStoredBoundaryAndRejectsOldAccountAndConnection() async throws {
        let scope = UUID()
        let fields: [String: Any] = ["chat_id": "synthetic-A", "compression_checkpoints": [
            ["encrypted_summary": "ciphertext", "created_at": 2, "compressed_up_to_timestamp": 100],
            ["encrypted_summary": "", "created_at": 3, "compressed_up_to_timestamp": 300]]]
        let receipt = try XCTUnwrap(ChatCompressionNotificationReceipt(Notification(name: .wsSyncEvent,
            userInfo: ["accountScope": scope, "transportGeneration": 7,
                "decoded": WebSocketResponse(fields: fields), "raw": Data("malformed unused raw".utf8)])))
        let decoded = try await receipt.fields()
        XCTAssertEqual(RememberMessageDraft.latestBoundary(decoded.fields, chatID: "synthetic-A"), 100)
        XCTAssertNil(RememberMessageDraft.latestBoundary(decoded.fields, chatID: "synthetic-B"))
        XCTAssertTrue(receipt.matches(scope: scope, transport: 7))
        XCTAssertFalse(receipt.matches(scope: UUID(), transport: 7))
        XCTAssertFalse(receipt.matches(scope: scope, transport: 8))

        let raw = try JSONSerialization.data(withJSONObject: ["payload": fields])
        let legacy = try XCTUnwrap(ChatCompressionNotificationReceipt(Notification(name: .wsSyncEvent,
            userInfo: ["accountScope": scope, "raw": raw])))
        let legacyDecoded = try await legacy.fields()
        XCTAssertEqual(RememberMessageDraft.latestBoundary(legacyDecoded.fields, chatID: "synthetic-A"), 100)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testInterruptedPresentationAToBToACannotLeaveHistoryWaitingForOldCompletion() {
        var pending: String? = "A"
        var generation = UUID()
        let oldCompletionGeneration = generation
        ChatHistoryPresentationInterruption.invalidate(pendingChatID: &pending, generation: &generation, selectedChatID: "A")
        XCTAssertEqual(pending, "A", "Selection belonging to the current animation must retain its gate")
        ChatHistoryPresentationInterruption.invalidate(pendingChatID: &pending, generation: &generation, selectedChatID: "B")
        XCTAssertNil(pending)
        XCTAssertNotEqual(generation, oldCompletionGeneration, "The interrupted animation completion is obsolete")
        ChatHistoryPresentationInterruption.invalidate(pendingChatID: &pending, generation: &generation, selectedChatID: "A")
        XCTAssertNotEqual(pending, "A", "Returning directly to A can load history immediately")
        XCTAssertNotEqual(generation, oldCompletionGeneration)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testLargeInboundSyncFrameDecodesAwayFromUIExecutorAndPreservesRawBytes() async throws {
        let contents = String(repeating: "synthetic encrypted history ", count: 8_000)
        let raw = try JSONSerialization.data(withJSONObject: [
            "type": "chat_content_batch", "payload": ["chat_id": "decode-fixture", "encrypted_content": contents]
        ])
        let frame = try await WebSocketInboundDecoder().decode(.data(raw))
        XCTAssertFalse(frame.decodedOnMainThread)
        XCTAssertEqual(frame.raw, raw)
        XCTAssertEqual(frame.parsed.type, "chat_content_batch")
        XCTAssertEqual(frame.parsed.stringField("chat_id"), "decode-fixture")
        XCTAssertEqual(frame.parsed.stringField("encrypted_content"), contents)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testMalformedInboundFrameDoesNotPoisonNextOrderedDecode() async throws {
        let decoder = WebSocketInboundDecoder()
        do {
            _ = try await decoder.decode(.string("{broken"))
            XCTFail("Malformed JSON must not become a routed message")
        } catch {}
        let first = try await decoder.decode(.string("{\"type\":\"ai_typing\",\"payload\":{\"sequence\":1}}"))
        let second = try await decoder.decode(.string("{\"event\":\"ai_message_ready\",\"sequence\":2}"))
        XCTAssertEqual(first.parsed.intField("sequence"), 1)
        XCTAssertEqual(second.parsed.intField("sequence"), 2)
        XCTAssertEqual(second.parsed.type, "ai_message_ready")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFailedHandshakesExhaustTenRetriesInsteadOfResettingDuringConnecting() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var count = 0
        var nextAttempt: XCTestExpectation?
        manager.debugConnectionAttempt = {
            count += 1
            nextAttempt?.fulfill()
        }
        manager.connect(sessionId: "synthetic-session", token: nil)
        XCTAssertEqual(count, 1)
        for attempt in 1...10 {
            nextAttempt = expectation(description: "retry \(attempt) starts")
            manager.debugFailCurrentConnection()
            XCTAssertEqual(manager.connectionState, .reconnecting(attempt: attempt))
            await fulfillment(of: [nextAttempt!], timeout: 1)
            XCTAssertEqual(manager.connectionState, .connecting)
        }
        nextAttempt = expectation(description: "no eleventh retry")
        nextAttempt!.isInverted = true
        manager.debugFailCurrentConnection()
        XCTAssertEqual(manager.connectionState, .disconnected)
        await fulfillment(of: [nextAttempt!], timeout: 0.05)
        XCTAssertEqual(count, 11)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,sync.surface.semantic-parity
    func testFreshRecoveryTokensDoNotResetFailedHandshakeRetryBudget() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var validations = 0
        var attempts = 0
        var nextAttempt: XCTestExpectation?
        manager.debugConnectionAttempt = { attempts += 1; nextAttempt?.fulfill() }
        manager.configureSessionRecovery {
            validations += 1
            return .authenticated(sessionID: "synthetic-session", token: "rotated-token-\(validations)")
        }
        manager.connect(sessionId: "synthetic-session", token: "initial-token")
        for attempt in 1...10 {
            nextAttempt = expectation(description: "retry \(attempt) with a fresh token")
            manager.debugFailCurrentConnection(authenticationRejected: true)
            XCTAssertEqual(manager.connectionState, .reconnecting(attempt: attempt))
            await fulfillment(of: [nextAttempt!], timeout: 1)
            XCTAssertEqual(manager.debugCurrentAuthToken, "rotated-token-\(attempt)")
        }
        nextAttempt = expectation(description: "no retry after ten freshly authenticated failures")
        nextAttempt!.isInverted = true
        manager.debugFailCurrentConnection(authenticationRejected: true)
        XCTAssertEqual(manager.connectionState, .disconnected)
        await fulfillment(of: [nextAttempt!], timeout: 0.05)
        XCTAssertEqual(validations, 10)
        XCTAssertEqual(attempts, 11)
        let exhaustedGeneration = manager.transportGeneration
        for token in ["rotated-token-10", "externally-rotated-token-11", "externally-rotated-token-12"] {
            manager.connect(sessionId: "synthetic-session", token: token)
            XCTAssertEqual(manager.connectionState, .disconnected,
                "Validation/foreground callbacks must not rearm an exhausted logical session")
        }
        XCTAssertEqual(manager.transportGeneration, exhaustedGeneration,
            "Suppressed attempts must not invalidate pending recovery or ciphertext ownership")
        XCTAssertEqual(manager.debugCurrentAuthToken, "rotated-token-10")
        XCTAssertEqual(validations, 10)
        XCTAssertEqual(attempts, 11)
        nextAttempt = nil
        manager.disconnect()
        manager.connect(sessionId: "synthetic-session", token: "fresh-login-token")
        XCTAssertEqual(manager.connectionState, .connecting,
            "Explicit reconnect after sign-in must admit a fresh budget")
        XCTAssertEqual(attempts, 12)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.isolation
    func testNewLogicalSessionCanConnectAfterPreviousSessionExhaustsRetries() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var attempts = 0
        var nextAttempt: XCTestExpectation?
        manager.debugConnectionAttempt = { attempts += 1; nextAttempt?.fulfill() }
        manager.connect(sessionId: "exhausted-session", token: "initial-token")
        for attempt in 1...10 {
            nextAttempt = expectation(description: "bounded retry \(attempt)")
            manager.debugFailCurrentConnection(authenticationRejected: true)
            await fulfillment(of: [nextAttempt!], timeout: 1)
        }
        nextAttempt = nil
        manager.debugFailCurrentConnection(authenticationRejected: true)
        XCTAssertEqual(manager.connectionState, .disconnected)
        XCTAssertEqual(attempts, 11)
        manager.connect(sessionId: "replacement-session", token: "new-session-token")
        XCTAssertEqual(manager.connectionState, .connecting)
        XCTAssertEqual(manager.debugCurrentAuthToken, "new-session-token")
        XCTAssertEqual(attempts, 12, "A sibling/replacement native session must not inherit the old exhaustion")
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testExplicitDisconnectCancelsDelayedRetry() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0.03
        let cancelled = expectation(description: "cancelled retry never starts")
        cancelled.isInverted = true
        var attempts = 0
        manager.debugConnectionAttempt = {
            attempts += 1
            if attempts > 1 { cancelled.fulfill() }
        }
        manager.connect(sessionId: "synthetic-session", token: nil)
        manager.debugFailCurrentConnection()
        manager.disconnect()
        await fulfillment(of: [cancelled], timeout: 0.08)
        XCTAssertEqual(manager.connectionState, .disconnected)
        XCTAssertEqual(attempts, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
    func testRejectedTransportWaitsForValidationThenUsesRotatedCredentials() async throws {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var pending: CheckedContinuation<WebSocketManager.SessionRecoveryResult, Never>?
        var attempts = 0
        let recovered = expectation(description: "rotated connection starts")
        manager.debugConnectionAttempt = {
            attempts += 1
            if attempts == 2 { recovered.fulfill() }
        }
        manager.configureSessionRecovery {
            await withCheckedContinuation { pending = $0 }
        }
        manager.connect(sessionId: "synthetic-session", token: "old-token")
        try assertSignedTokenRequest(manager, sessionID: "synthetic-session", token: manager.debugCurrentAuthToken)
        manager.debugFailCurrentConnection(authenticationRejected: true)
        while pending == nil { await Task.yield() }
        XCTAssertEqual(attempts, 1, "Rejected credentials must not be retried during validation")
        pending?.resume(returning: .authenticated(sessionID: "synthetic-session", token: "rotated-token"))
        await fulfillment(of: [recovered], timeout: 1)
        XCTAssertEqual(manager.debugCurrentAuthToken, "rotated-token")
        try assertSignedTokenRequest(manager, sessionID: "synthetic-session", token: manager.debugCurrentAuthToken)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
    func testAbsentSignedTokenRetainsCookieTransportWithoutInventingQueryCredentials() throws {
        let manager = WebSocketManager()
        let profile = ServerProfile.current()
        let tokens: [String?] = [nil, ""]
        for token in tokens {
            let request = try XCTUnwrap(manager.connectionRequest(profile: profile,
                sessionID: "synthetic-session", token: token, origin: profile.webBaseURL.absoluteString))
            XCTAssertTrue(request.httpShouldHandleCookies)
            let query = try XCTUnwrap(URLComponents(url: XCTUnwrap(request.url), resolvingAgainstBaseURL: false))
            XCTAssertFalse(query.queryItems?.contains { $0.name == "token" } ?? false)
        }
    }

    private func assertSignedTokenRequest(_ manager: WebSocketManager, sessionID: String, token: String?,
        file: StaticString = #filePath, line: UInt = #line) throws {
        let profile = ServerProfile.current()
        let request = try XCTUnwrap(manager.connectionRequest(profile: profile, sessionID: sessionID,
            token: token, origin: profile.webBaseURL.absoluteString), file: file, line: line)
        XCTAssertFalse(request.httpShouldHandleCookies,
            "Fresh query credentials must not be shadowed by automatic cookie aliases", file: file, line: line)
        XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"), file: file, line: line)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), profile.webBaseURL.absoluteString, file: file, line: line)
        for (header, value) in APIClient.nativeClientHeaders {
            XCTAssertEqual(request.value(forHTTPHeaderField: header), value, file: file, line: line)
        }
        let query = try XCTUnwrap(URLComponents(url: XCTUnwrap(request.url), resolvingAgainstBaseURL: false),
            file: file, line: line)
        XCTAssertTrue(query.queryItems?.first { $0.name == "token" }?.value == token, file: file, line: line)
        XCTAssertTrue(query.queryItems?.first { $0.name == "sessionId" }?.value == sessionID, file: file, line: line)
        XCTAssertFalse(query.queryItems?.first { $0.name == "client_capabilities" }?.value?
            .split(separator: ",").contains("typed_recovery_outputs_v2") ?? false, file: file, line: line)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testGenuinelyRejectedSessionStopsSocketRetries() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        let validated = expectation(description: "session rejection handled")
        var attempts = 0
        manager.debugConnectionAttempt = { attempts += 1 }
        manager.configureSessionRecovery { validated.fulfill(); return .rejected }
        manager.connect(sessionId: "synthetic-session", token: "expired-token")
        manager.debugFailCurrentConnection(authenticationRejected: true)
        await fulfillment(of: [validated], timeout: 1)
        await Task.yield()
        XCTAssertEqual(manager.connectionState, .disconnected)
        XCTAssertEqual(attempts, 1)
        XCTAssertNil(manager.debugCurrentAuthToken)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testDisconnectFencesLateSuccessfulRecovery() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var pending: CheckedContinuation<WebSocketManager.SessionRecoveryResult, Never>?
        var attempts = 0
        manager.debugConnectionAttempt = { attempts += 1 }
        manager.configureSessionRecovery { await withCheckedContinuation { pending = $0 } }
        manager.connect(sessionId: "old-session", token: "old-token")
        manager.debugFailCurrentConnection(authenticationRejected: true)
        while pending == nil { await Task.yield() }
        manager.disconnect()
        manager.connect(sessionId: "replacement-session", token: "replacement-token")
        pending?.resume(returning: .authenticated(sessionID: "old-session", token: "late-old-token"))
        await Task.yield()
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(manager.debugCurrentAuthToken, "replacement-token")
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testTemporaryValidationFailureRetriesValidationWithoutReusingRejectedToken() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var validations = 0
        var attempts = 0
        let recovered = expectation(description: "retry after transient validation failure")
        manager.debugConnectionAttempt = { attempts += 1; if attempts == 2 { recovered.fulfill() } }
        manager.configureSessionRecovery {
            validations += 1
            return validations == 1 ? .unavailable : .authenticated(sessionID: "synthetic-session", token: "new-token")
        }
        manager.connect(sessionId: "synthetic-session", token: "rejected-token")
        manager.debugFailCurrentConnection(authenticationRejected: true)
        await fulfillment(of: [recovered], timeout: 1)
        XCTAssertEqual(validations, 2)
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(manager.debugCurrentAuthToken, "new-token")
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.isolation
    func testReceiveFirstPolicyCloseRecoversOnceAndIgnoresLateClose() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var validations = 0
        var attempts = 0
        let recovered = expectation(description: "receive-first recovery uses rotated token")
        manager.debugConnectionAttempt = { attempts += 1; if attempts == 2 { recovered.fulfill() } }
        manager.configureSessionRecovery {
            validations += 1
            return .authenticated(sessionID: "synthetic-session", token: "rotated-token")
        }
        let session = URLSession(configuration: .ephemeral)
        let task = session.webSocketTask(with: URL(string: "wss://invalid.example")!)
        manager.connect(sessionId: "synthetic-session", token: "old-token")
        manager.debugBindCurrentSocket(task)
        let generation = manager.transportGeneration
        manager.debugReceiveFailure(NSError(domain: NSPOSIXErrorDomain, code: 57), from: task,
            generation: generation, closeCode: .policyViolation, httpStatus: nil)
        manager.urlSession(session, webSocketTask: task, didCloseWith: .policyViolation, reason: nil)
        await fulfillment(of: [recovered], timeout: 1)
        await Task.yield()
        XCTAssertEqual(validations, 1)
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(manager.debugCurrentAuthToken, "rotated-token")
        manager.disconnect()
        session.invalidateAndCancel()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testReceiveFirstHTTPAuthenticationFailuresUseSessionRecovery() async {
        for status in [401, 403] {
            NativeClientLogCollector.shared.resetForTests()
            let manager = WebSocketManager()
            manager.debugReconnectDelay = 0
            var validations = 0
            let recovered = expectation(description: "HTTP \(status) recovery")
            var attempts = 0
            manager.debugConnectionAttempt = { attempts += 1; if attempts == 2 { recovered.fulfill() } }
            manager.configureSessionRecovery {
                validations += 1
                return .authenticated(sessionID: "synthetic-session", token: "rotated-token")
            }
            let session = URLSession(configuration: .ephemeral)
            let task = session.webSocketTask(with: URL(string: "wss://invalid.example")!)
            manager.connect(sessionId: "synthetic-session", token: "old-token")
            manager.debugBindCurrentSocket(task)
            manager.debugReceiveFailure(NSError(domain: NSPOSIXErrorDomain, code: 57), from: task,
                generation: manager.transportGeneration, closeCode: .invalid, httpStatus: status)
            await fulfillment(of: [recovered], timeout: 1)
            XCTAssertEqual(validations, 1)
            XCTAssertEqual(manager.debugCurrentAuthToken, "rotated-token")
            let logs = NativeClientLogCollector.shared.entriesSnapshot(limit: 200).map(\.message)
            XCTAssertTrue(logs.contains { $0.contains("event=socket_receive_failed") && $0.contains("http_status=\(status)") })
            XCTAssertTrue(logs.contains { $0.contains("event=socket_connection_lost") && $0.contains("authentication_rejected=true") })
            manager.disconnect()
            session.invalidateAndCancel()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,sync.surface.semantic-parity
    func testUnitHostStartupDoesNotRestoreAProductSessionWhileUIAppRemainsEnabled() {
        XCTAssertTrue(NativeUnitTestHostPolicy.suppressAutomaticStartup(environment: [:],
            loadedBundlePaths: ["/synthetic/OpenMatesTests.xctest"], hasXCTestCase: false))
        XCTAssertTrue(NativeUnitTestHostPolicy.suppressAutomaticStartup(
            environment: ["XCTestConfigurationFilePath": "/synthetic/unit.xctestconfiguration"],
            loadedBundlePaths: [], hasXCTestCase: true))
        XCTAssertFalse(NativeUnitTestHostPolicy.suppressAutomaticStartup(
            environment: ["XCTestConfigurationFilePath": "/synthetic/ui.xctestconfiguration"],
            loadedBundlePaths: ["/synthetic/OpenMatesUITests.xctest"], hasXCTestCase: false))
        XCTAssertFalse(NativeUnitTestHostPolicy.suppressAutomaticStartup(environment: [:],
            loadedBundlePaths: [], hasXCTestCase: false))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testUnknownAndGenericReceiveFailuresKeepOrdinaryRetryAndScalarDiagnostics() async {
        for closeCode: URLSessionWebSocketTask.CloseCode? in [nil, .invalid, .goingAway] {
            NativeClientLogCollector.shared.resetForTests()
            let manager = WebSocketManager()
            manager.debugReconnectDelay = 0
            var attempts = 0
            let retried = expectation(description: "ordinary transport retry")
            manager.debugConnectionAttempt = { attempts += 1; if attempts == 2 { retried.fulfill() } }
            let session = URLSession(configuration: .ephemeral)
            let task = session.webSocketTask(with: URL(string: "wss://invalid.example")!)
            let canary = "PRIVATE_RECEIVE_DETAIL_CANARY"
            manager.connect(sessionId: canary, token: canary)
            manager.debugBindCurrentSocket(task)
            manager.debugReceiveFailure(NSError(domain: canary, code: 57,
                userInfo: [NSLocalizedDescriptionKey: canary]), from: task,
                generation: manager.transportGeneration, closeCode: closeCode, httpStatus: nil)
            await fulfillment(of: [retried], timeout: 1)
            XCTAssertEqual(manager.debugCurrentAuthToken, canary)
            let logs = NativeClientLogCollector.shared.entriesSnapshot(limit: 200).map(\.message)
            XCTAssertTrue(logs.contains { $0.contains("event=socket_receive_failed") && $0.contains("close_code=\(closeCode?.rawValue ?? 0)") && $0.contains("http_status=0") })
            XCTAssertTrue(logs.contains { $0.contains("event=socket_connection_lost") && $0.contains("authentication_rejected=false") })
            XCTAssertFalse(logs.contains { $0.contains(canary) })
            manager.disconnect()
            session.invalidateAndCancel()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testStaleReceiveAndCloseCallbacksCannotAffectReplacementAccount() async {
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        var validations = 0
        manager.configureSessionRecovery { validations += 1; return .rejected }
        let session = URLSession(configuration: .ephemeral)
        let oldTask = session.webSocketTask(with: URL(string: "wss://invalid.example")!)
        let replacementTask = session.webSocketTask(with: URL(string: "wss://invalid.example")!)
        manager.connect(sessionId: "old-session", token: "old-token")
        manager.debugBindCurrentSocket(oldTask)
        let oldGeneration = manager.transportGeneration
        manager.disconnect()
        manager.connect(sessionId: "replacement-session", token: "replacement-token")
        manager.debugBindCurrentSocket(replacementTask)
        let failure = NSError(domain: NSPOSIXErrorDomain, code: 57)
        manager.debugReceiveFailure(failure, from: oldTask, generation: manager.transportGeneration,
            closeCode: .policyViolation, httpStatus: 401)
        manager.debugReceiveFailure(failure, from: replacementTask, generation: oldGeneration,
            closeCode: .policyViolation, httpStatus: 403)
        manager.urlSession(session, webSocketTask: oldTask, didCloseWith: .policyViolation, reason: nil)
        await Task.yield()
        XCTAssertEqual(validations, 0)
        XCTAssertEqual(manager.connectionState, .connecting)
        XCTAssertEqual(manager.debugCurrentAuthToken, "replacement-token")
        manager.disconnect()
        session.invalidateAndCancel()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPingTimerFiresDuringUITracking() async {
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        let sent = expectation(description: "ping fires during UI tracking")
        var sentCount = 0
        manager.debugPingSender = { completion in
            sentCount += 1
            if sentCount == 1 { sent.fulfill() }
            completion(nil)
        }
        manager.connect(sessionId: "synthetic-session", token: nil)
        manager.debugStartPingTimer(interval: 0.005)
        runTrackingLoop(for: 0.03)
        manager.debugPingTimer?.invalidate()
        // Delivery may need its MainActor hop after tracking ends, but the timer
        // must have queued it without a pass through the default run-loop mode.
        await fulfillment(of: [sent], timeout: 1)
        manager.disconnect()
        XCTAssertGreaterThan(sentCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,sync.surface.semantic-parity
    func testQueuedTimerFireCannotPingAReplacementConnection() async {
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        var sentCount = 0
        manager.debugPingSender = { completion in sentCount += 1; completion(nil) }
        manager.connect(sessionId: "old-session", token: nil)
        manager.debugStartPingTimer(interval: 25)
        manager.debugPingTimer?.fire()
        // The old timer already queued its MainActor work when it is invalidated.
        manager.disconnect()
        manager.connect(sessionId: "replacement-session", token: nil)
        await Task.yield()
        XCTAssertEqual(sentCount, 0)
        XCTAssertEqual(manager.connectionState, .connecting)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,sync.surface.semantic-parity
    func testLatePingFailureCannotDisconnectAReplacementConnection() async {
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        let sent = expectation(description: "old socket ping sent")
        var completion: (@Sendable (Error?) -> Void)?
        manager.debugPingSender = { callback in completion = callback; sent.fulfill() }
        manager.connect(sessionId: "old-session", token: nil)
        manager.debugStartPingTimer(interval: 25)
        manager.debugPingTimer?.fire()
        await fulfillment(of: [sent], timeout: 1)
        manager.disconnect()
        manager.connect(sessionId: "replacement-session", token: nil)
        completion?(NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost))
        await Task.yield()
        XCTAssertEqual(manager.connectionState, .connecting)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPingDiagnosticsReportOnlyScalarsFromPrivateError() async {
        NativeClientLogCollector.shared.resetForTests()
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        manager.debugReconnectDelay = 30
        let sent = expectation(description: "ping completion delivered")
        let privateValue = "PRIVATE_SOCKET_DETAIL_CANARY"
        manager.debugPingSender = { completion in
            completion(NSError(domain: privateValue, code: 73,
                               userInfo: [NSLocalizedDescriptionKey: privateValue]))
            sent.fulfill()
        }
        manager.connect(sessionId: privateValue, token: privateValue)
        manager.debugStartPingTimer(interval: 25)
        manager.debugPingTimer?.fire()
        await fulfillment(of: [sent], timeout: 1)
        await Task.yield()
        let messages = NativeClientLogCollector.shared.entriesSnapshot(limit: 200).map(\.message)
        XCTAssertTrue(messages.contains { $0.contains("event=socket_ping_failed") && $0.contains("error_code=73") && $0.contains("error_domain_class=0") })
        XCTAssertFalse(messages.contains { $0.contains(privateValue) })
        XCTAssertEqual(manager.connectionState, .reconnecting(attempt: 1))
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testMonotonicDiagnosticsKeepCadenceAndDrainBoundedSamples() {
        var timings = WebSocketTimingWindow()
        timings.startPingSchedule(at: 100, interval: 25)
        XCTAssertEqual(timings.pingScheduleDrift(at: 180), 55_000)
        XCTAssertEqual(timings.pingScheduleDrift(at: 200.125), 125)
        timings.recordCallback(at: 210, deliveredAt: 210.02)
        timings.recordCallback(at: 211, deliveredAt: 211.09)
        timings.recordReceive(routingMilliseconds: 12)
        timings.recordReceive(routingMilliseconds: 3)
        timings.recordSyncEvent()
        let counts = timings.takeWindowCounts()
        XCTAssertEqual(counts["callback_count"], 2)
        XCTAssertEqual(counts["callback_main_delay_max_ms"], 90)
        XCTAssertEqual(counts["received_count"], 2)
        XCTAssertEqual(counts["receive_routing_total_ms"], 15)
        XCTAssertEqual(counts["sync_event_count"], 1)
        XCTAssertTrue(timings.takeWindowCounts().values.allSatisfy { $0 == 0 })
        XCTAssertEqual(WebSocketTimingWindow.errorDomainClass(NSURLErrorDomain), 1)
        XCTAssertEqual(WebSocketTimingWindow.errorDomainClass("private-domain"), 0)
    }

    private func runTrackingLoop(for duration: TimeInterval) {
        #if os(iOS)
        let mode = RunLoop.Mode.tracking
        #elseif os(macOS)
        let mode = RunLoop.Mode.eventTracking
        #else
        let mode = RunLoop.Mode.common
        #endif
        let deadline = Date(timeIntervalSinceNow: duration)
        while Date() < deadline {
            RunLoop.main.run(mode: mode, before: deadline)
        }
    }

}
