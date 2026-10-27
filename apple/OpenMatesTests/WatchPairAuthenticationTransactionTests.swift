// Injected-storage regression through the production Watch receiver transaction
// and queue. Uses isolated defaults/cookies and synthetic in-memory key bytes.
import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class WatchPairAuthenticationTransactionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testBackAfterKeySaveRestoresRetainedKeyMetadataDeadlineAndCookies() async throws {
        let fixture = try WatchPairStorageFixture()
        defer { fixture.cleanup() }
        let before = fixture.snapshot()
        let reached = expectation(description: "Saved pair key before return")
        let gate = WatchPairStorageGate()
        fixture.afterSave = { bytes in if bytes == fixture.pairKey { await gate.hold(reached) } }
        var published = false
        let task = Task { @MainActor in
            try await fixture.transaction.run(serverProfile: fixture.profile, isCurrent: { true },
                complete: { try fixture.complete() }, unregisterPush: {}, acknowledge: {}, publish: { _ in published = true })
        }
        await fulfillment(of: [reached], timeout: 3)
        task.cancel(); gate.release()
        do { try await task.value; XCTFail("Back must cancel") } catch is CancellationError {} catch { XCTFail("Unexpected failure: \(error)") }
        XCTAssertFalse(published)
        fixture.assertMatches(before)
        XCTAssertEqual(fixture.keyDeletes, 0, "A retained key must be restored, never removed")
        XCTAssertFalse(fixture.transaction.isRunning)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testThrowingKeySaveDoesNotDeleteUntouchedRetainedKeyOrDefaults() async throws {
        let fixture = try WatchPairStorageFixture()
        defer { fixture.cleanup() }
        let before = fixture.snapshot()
        fixture.failPairKeySave = true
        do {
            try await fixture.transaction.run(serverProfile: fixture.profile, isCurrent: { true },
                complete: { try fixture.complete() }, unregisterPush: {}, acknowledge: { XCTFail("No ack after failed key save") },
                publish: { _ in XCTFail("No identity after failed key save") })
            XCTFail("Expected key save failure")
        } catch WatchPairStorageFixture.Failure.keySave {} catch { XCTFail("Unexpected failure: \(error)") }
        fixture.assertMatches(before)
        XCTAssertEqual(fixture.keyDeletes, 0)
        XCTAssertEqual(fixture.successfulKeyWrites, 0, "A failed save must not become an owned key mutation")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testAcknowledgementFailureRestoresExactPreexistingMetadataAndDeadline() async throws {
        let fixture = try WatchPairStorageFixture()
        defer { fixture.cleanup() }
        let before = fixture.snapshot()
        do {
            try await fixture.transaction.run(serverProfile: fixture.profile, isCurrent: { true },
                complete: { try fixture.complete() }, unregisterPush: {}, acknowledge: { throw WatchPairStorageFixture.Failure.ack },
                publish: { _ in XCTFail("No identity after failed acknowledgement") })
            XCTFail("Expected acknowledgement failure")
        } catch WatchPairStorageFixture.Failure.ack {} catch { XCTFail("Unexpected failure: \(error)") }
        fixture.assertMatches(before)
        XCTAssertEqual(fixture.keyDeletes, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testNewReceiverWaitsForOldCleanupAndCancelledQueuedReceiverDrains() async throws {
        let fixture = try WatchPairStorageFixture()
        defer { fixture.cleanup() }
        let ackReached = expectation(description: "Departed acknowledgement pending")
        let cleanupReached = expectation(description: "Departed cleanup still owns lease")
        let ackGate = WatchPairStorageGate()
        let cleanupGate = WatchPairStorageGate()
        fixture.afterSave = { bytes in if bytes == fixture.retainedKey { await cleanupGate.hold(cleanupReached) } }
        let first = Task { @MainActor in
            try await fixture.transaction.run(serverProfile: fixture.profile, isCurrent: { true },
                complete: { try fixture.complete() }, unregisterPush: {}, acknowledge: { await ackGate.hold(ackReached) },
                publish: { _ in XCTFail("Departed identity cannot publish") })
        }
        await fulfillment(of: [ackReached], timeout: 3)
        first.cancel(); ackGate.release()
        await fulfillment(of: [cleanupReached], timeout: 3)
        let cancelledEnters = expectation(description: "Cancelled receiver calls real queue")
        let cancelled = Task { @MainActor in
            cancelledEnters.fulfill()
            try await fixture.transaction.run(serverProfile: fixture.profile, isCurrent: { true },
                complete: { XCTFail("Cancelled waiter cannot reach receiver completion"); return try fixture.complete() },
                unregisterPush: {}, acknowledge: {}, publish: { _ in XCTFail("Cancelled waiter cannot publish") })
        }
        await fulfillment(of: [cancelledEnters], timeout: 3)
        let successorEnters = expectation(description: "Successor calls real queue")
        var successorStarted = false
        var successorPublished = false
        let successor = Task { @MainActor in
            successorEnters.fulfill()
            try await fixture.transaction.run(serverProfile: fixture.profile, isCurrent: { true }, complete: {
                successorStarted = true
                return try fixture.complete(key: fixture.successorKey, cookie: "successor-fixture")
            }, unregisterPush: {}, acknowledge: {}, publish: { _ in successorPublished = true })
        }
        await fulfillment(of: [successorEnters], timeout: 3)
        cancelled.cancel()
        do { try await cancelled.value; XCTFail("Queued cancellation must finish before active cleanup") }
        catch is CancellationError {} catch { XCTFail("Unexpected failure: \(error)") }
        XCTAssertFalse(successorStarted)
        XCTAssertEqual(fixture.transaction.waitingCount, 1)
        cleanupGate.release()
        do { try await first.value; XCTFail("Departed receiver must fail") }
        catch is CancellationError {} catch { XCTFail("Unexpected failure: \(error)") }
        try await successor.value
        XCTAssertTrue(successorPublished)
        XCTAssertEqual(fixture.keys[fixture.userID], fixture.successorKey)
        XCTAssertEqual(fixture.cookieValue, "successor-fixture")
        XCTAssertNil(fixture.standard.object(forKey: PairPendingAckStore.key))
        XCTAssertEqual(fixture.standard.string(forKey: PairSessionDeadlineStore.userKey), fixture.userID)
        XCTAssertEqual(fixture.standard.integer(forKey: PairSessionDeadlineStore.deadlineKey), fixture.pairDeadline)
        XCTAssertFalse(fixture.transaction.isRunning)
        XCTAssertEqual(fixture.transaction.waitingCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testIndependentReplacementDuringReceiverOrKeyAwaitStopsForwardWritesWithSuccessfulAck() async throws {
        for boundary in ["receiver", "keyLoad", "keySave"] {
            let fixture = try WatchPairStorageFixture()
            defer { fixture.cleanup() }
            let target = fixture.profile
            let reached = expectation(description: "Suspended " + boundary)
            let gate = WatchPairStorageGate()
            if boundary == "keyLoad" { fixture.duringLoad = { await gate.hold(reached) } }
            if boundary == "keySave" {
                fixture.afterSave = { bytes in if bytes == fixture.pairKey { await gate.hold(reached) } }
            }
            var acknowledged = false
            var published = false
            let task = Task { @MainActor in
                try await fixture.transaction.run(serverProfile: target, isCurrent: { true }, complete: {
                    let result = try fixture.complete(serverProfile: target)
                    if boundary == "receiver" { await gate.hold(reached) }
                    return result
                }, unregisterPush: {}, acknowledge: { acknowledged = true }, publish: { _ in published = true })
            }
            await fulfillment(of: [reached], timeout: 3)
            let replacement = Data("independent-forward-metadata".utf8)
            fixture.keys[fixture.userID] = fixture.successorKey
            fixture.standard.set(replacement, forKey: WatchPairAuthenticationTransaction.cachedUserKey)
            fixture.shared.set(replacement, forKey: WatchPairAuthenticationTransaction.cachedUserKey)
            fixture.standard.set("independent-deadline-owner", forKey: PairSessionDeadlineStore.userKey)
            fixture.standard.set(1_999_999_999, forKey: PairSessionDeadlineStore.deadlineKey)
            fixture.standard.set(replacement, forKey: PairVerifiedAccountStore.key)
            fixture.setCookie("independent-forward-cookie", serverProfile: target)
            fixture.profile = .production
            fixture.epoch += 1
            gate.release()
            do { try await task.value; XCTFail("Changed authority must stop the pending receiver") }
            catch is CancellationError {} catch { XCTFail("Unexpected failure: \(error)") }
            XCTAssertFalse(acknowledged, boundary)
            XCTAssertFalse(published, boundary)
            XCTAssertEqual(fixture.keys[fixture.userID], fixture.successorKey, boundary)
            XCTAssertEqual(fixture.standard.data(forKey: WatchPairAuthenticationTransaction.cachedUserKey), replacement)
            XCTAssertEqual(fixture.shared.data(forKey: WatchPairAuthenticationTransaction.cachedUserKey), replacement)
            XCTAssertEqual(fixture.standard.string(forKey: PairSessionDeadlineStore.userKey), "independent-deadline-owner")
            XCTAssertEqual(fixture.standard.integer(forKey: PairSessionDeadlineStore.deadlineKey), 1_999_999_999)
            XCTAssertEqual(fixture.profile, .production)
            XCTAssertEqual(fixture.cookies.cookies(for: target.apiBaseURL)?.first { $0.name == "auth_refresh_token" }?.value,
                "independent-forward-cookie")
            if boundary != "keySave" { XCTAssertEqual(fixture.successfulKeyWrites, 0) }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testProfileSelectionDuringCleanupStillRemovesOnlyDepartedServerCookie() async throws {
        let fixture = try WatchPairStorageFixture()
        defer { fixture.cleanup() }
        let previous = ServerProfile.custom(domain: "pair-prior-a.example")
        let target = ServerProfile.custom(domain: "pair-departed-b.example")
        fixture.profile = previous
        fixture.setCookie("retained-A", serverProfile: previous)
        let ackReached = expectation(description: "Target B acknowledgement pending")
        let cleanupReached = expectation(description: "Target B key restoration suspended")
        let ackGate = WatchPairStorageGate()
        let cleanupGate = WatchPairStorageGate()
        fixture.afterSave = { bytes in if bytes == fixture.retainedKey { await cleanupGate.hold(cleanupReached) } }
        let task = Task { @MainActor in
            try await fixture.transaction.run(serverProfile: target, isCurrent: { true },
                complete: { try fixture.complete(serverProfile: target) }, unregisterPush: {},
                acknowledge: { await ackGate.hold(ackReached) }, publish: { _ in XCTFail("Departed B cannot publish") })
        }
        await fulfillment(of: [ackReached], timeout: 3)
        task.cancel(); ackGate.release()
        await fulfillment(of: [cleanupReached], timeout: 3)
        fixture.profile = .production
        cleanupGate.release()
        do { try await task.value; XCTFail("Back must cancel B") }
        catch is CancellationError {} catch { XCTFail("Unexpected failure: \(error)") }
        XCTAssertEqual(fixture.profile, .production, "A new explicit server selection must remain selected")
        XCTAssertFalse((fixture.cookies.cookies(for: target.apiBaseURL) ?? []).contains { $0.name == "auth_refresh_token" })
        XCTAssertEqual(fixture.cookies.cookies(for: previous.apiBaseURL)?.first { $0.name == "auth_refresh_token" }?.value, "retained-A")
        XCTAssertEqual(fixture.keys[fixture.userID], fixture.retainedKey)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testIndependentReplacementIsNeverOverwrittenByDepartedRollback() async throws {
        let fixture = try WatchPairStorageFixture()
        defer { fixture.cleanup() }
        let replacement = Data("independent-account-metadata".utf8)
        do {
            try await fixture.transaction.run(serverProfile: fixture.profile, isCurrent: { true },
                complete: { try fixture.complete() }, unregisterPush: {}, acknowledge: {
                    fixture.keys[fixture.userID] = fixture.successorKey
                    fixture.standard.set(replacement, forKey: WatchPairAuthenticationTransaction.cachedUserKey)
                    fixture.shared.set(replacement, forKey: WatchPairAuthenticationTransaction.cachedUserKey)
                    fixture.setCookie("independent-fixture")
                    fixture.epoch += 1
                    throw WatchPairStorageFixture.Failure.ack
                }, publish: { _ in XCTFail("Departed identity cannot publish") })
            XCTFail("Expected failed ack")
        } catch WatchPairStorageFixture.Failure.ack {} catch { XCTFail("Unexpected failure: \(error)") }
        XCTAssertEqual(fixture.keys[fixture.userID], fixture.successorKey)
        XCTAssertEqual(fixture.standard.data(forKey: WatchPairAuthenticationTransaction.cachedUserKey), replacement)
        XCTAssertEqual(fixture.shared.data(forKey: WatchPairAuthenticationTransaction.cachedUserKey), replacement)
        XCTAssertEqual(fixture.cookieValue, "independent-fixture")
    }
}

@MainActor
private final class WatchPairStorageGate {
    private var continuation: CheckedContinuation<Void, Never>?
    func hold(_ reached: XCTestExpectation) async {
        await withCheckedContinuation { continuation = $0; reached.fulfill() }
    }
    func release() { continuation?.resume(); continuation = nil }
}

@MainActor
private final class WatchPairStorageFixture {
    enum Failure: Error { case keySave, ack }
    let userID = "synthetic-pair-account"
    let retainedKey = Data(repeating: 0x11, count: 32)
    let pairKey = Data(repeating: 0x22, count: 32)
    let successorKey = Data(repeating: 0x33, count: 32)
    let pairDeadline = 2_100_000_000
    let standard: UserDefaults
    let shared: UserDefaults
    let cookies: HTTPCookieStorage
    private let standardName = "WatchPairStorage.standard.\(UUID())"
    private let sharedName = "WatchPairStorage.shared.\(UUID())"
    var keys: [String: Data] = [:]
    var profile = ServerProfile.custom(domain: "pair-transaction-fixture.example")
    var epoch: UInt64 = 1
    var failPairKeySave = false
    var afterSave: (@MainActor (Data) async -> Void)?
    var duringLoad: (@MainActor () async -> Void)?
    var keyDeletes = 0
    var successfulKeyWrites = 0
    lazy var transaction = WatchPairAuthenticationTransaction(storage: WatchPairAuthenticationStorage(
        standard: standard, shared: shared, cookies: cookies,
        loadKey: { [unowned self] id in
            let retained = self.keys[id].map { SymmetricKey(data: $0) }
            await self.duringLoad?()
            return retained
        },
        saveKey: { [unowned self] key, id in
            let bytes = key.withUnsafeBytes { Data($0) }
            if self.failPairKeySave && bytes == self.pairKey { throw Failure.keySave }
            self.keys[id] = bytes; self.successfulKeyWrites += 1
            await self.afterSave?(bytes)
        }, deleteKey: { [unowned self] id in self.keys[id] = nil; self.keyDeletes += 1 },
        profile: { [unowned self] in self.profile }, saveProfile: { [unowned self] in self.profile = $0 },
        generation: { [unowned self] in self.epoch }, invalidate: { [unowned self] in self.epoch += 1 }, flush: {}))

    init() throws {
        standard = try XCTUnwrap(UserDefaults(suiteName: standardName))
        shared = try XCTUnwrap(UserDefaults(suiteName: sharedName))
        cookies = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
        keys[userID] = retainedKey
        standard.set(Data("retained-standard-cache".utf8), forKey: WatchPairAuthenticationTransaction.cachedUserKey)
        shared.set(Data("retained-shared-cache".utf8), forKey: WatchPairAuthenticationTransaction.cachedUserKey)
        standard.set("retained-deadline-account", forKey: PairSessionDeadlineStore.userKey)
        standard.set(1_900_000_000, forKey: PairSessionDeadlineStore.deadlineKey)
        standard.set("retained-pending-account", forKey: PairPendingAckStore.key)
        standard.set(Data("retained-verified-account".utf8), forKey: PairVerifiedAccountStore.key)
        setCookie("retained-fixture")
    }
    func cleanup() { afterSave = nil; duringLoad = nil; standard.removePersistentDomain(forName: standardName); shared.removePersistentDomain(forName: sharedName) }
    var cookieValue: String? { cookies.cookies(for: profile.apiBaseURL)?.first { $0.name == "auth_refresh_token" }?.value }
    func setCookie(_ value: String, serverProfile: ServerProfile? = nil) {
        if let cookie = HTTPCookie(properties: [.domain: (serverProfile ?? profile).apiBaseURL.host!, .path: "/", .name: "auth_refresh_token", .value: value]) {
            cookies.setCookie(cookie)
        }
    }
    func complete(key: Data? = nil, cookie: String = "pair-fixture", serverProfile: ServerProfile? = nil) throws -> PairLoginResult {
        standard.set(Data("new-verified-account".utf8), forKey: PairVerifiedAccountStore.key)
        WatchPairReceiverAuthority.current?.verifiedDidPersist()
        setCookie(cookie, serverProfile: serverProfile)
        WatchPairReceiverAuthority.current?.cookiesDidPublish()
        let user = try JSONDecoder().decode(UserProfile.self, from: Data("{\"id\":\"\(userID)\",\"username\":\"fixture\"}".utf8))
        return PairLoginResult(loginResponse: LoginResponse(success: true, tfaRequired: false, user: user,
            needsDeviceVerification: false, deviceVerificationType: nil, wsToken: nil, pairExpiresAt: pairDeadline),
            masterKey: SymmetricKey(data: key ?? pairKey), serverProfile: serverProfile ?? profile)
    }
    struct Snapshot {
        let key: Data?
        let standard: NSDictionary
        let shared: NSDictionary
        let cookie: String?
        let profile: ServerProfile
    }
    func snapshot() -> Snapshot {
        Snapshot(key: keys[userID], standard: (standard.persistentDomain(forName: standardName) ?? [:]) as NSDictionary,
            shared: (shared.persistentDomain(forName: sharedName) ?? [:]) as NSDictionary, cookie: cookieValue, profile: profile)
    }
    func assertMatches(_ snapshot: Snapshot, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(keys[userID], snapshot.key, file: file, line: line)
        XCTAssertEqual((standard.persistentDomain(forName: standardName) ?? [:]) as NSDictionary, snapshot.standard, file: file, line: line)
        XCTAssertEqual((shared.persistentDomain(forName: sharedName) ?? [:]) as NSDictionary, snapshot.shared, file: file, line: line)
        XCTAssertEqual(cookieValue, snapshot.cookie, file: file, line: line)
        XCTAssertEqual(profile, snapshot.profile, file: file, line: line)
    }
}
