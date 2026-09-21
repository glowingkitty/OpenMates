// PRIVATE deterministic tests; register alongside proposed source only after review.
import XCTest
@testable import OpenMates

@MainActor final class ChatModelPreferenceServiceTests: XCTestCase {
    let a = ModelPreferenceScope(server: "dev", userID: "a", chatID: "chat")
    let b = ModelPreferenceScope(server: "dev", userID: "b", chatID: "chat")
    func catalog() -> ModelRoutingCatalog {
        ModelRoutingCatalog(entries: [.init(provider: "owner", modelID: "family/model", skill: "ai.ask", servers: ["host"])])
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testCanonicalProviderAndExplicitMentionPrecedence() {
        let c = catalog()
        XCTAssertEqual(c.canonical("host/family/model"), "owner/family/model")
        XCTAssertEqual(c.prefix(selection: "host/family/model", text: "Hello"), "@ai-model:family/model:owner Hello")
        XCTAssertEqual(c.prefix(selection: "owner/family/model", text: "@best-model:fast Hello"), "@best-model:fast Hello")
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testNoHealthyEnabledServerMakesSelectionUnavailable() {
        var c = catalog(); c.unhealthyServers = ["host"]
        XCTAssertFalse(c.usable("owner/family/model"))
        c.unhealthyServers = []; c.disabledServers = ["family/model": ["host"]]
        XCTAssertFalse(c.usable("owner/family/model"))
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testConflictRetriesAgainstRemoteVersionAndPersistsOnlyCiphertext() async throws {
        let fake = Fake(); fake.remote = .init(ciphertext: "D:{\"mode\":\"auto\"}", version: 8); fake.conflicts = 1
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        service.activate(a)
        let selected = try await service.select("host/family/model")
        XCTAssertEqual(selected, "owner/family/model")
        XCTAssertEqual(fake.expected, [0, 8])
        XCTAssertEqual(fake.local[a]?.version, 9)
        XCTAssertTrue(fake.local[a]?.ciphertext.hasPrefix("D:") == true)
        XCTAssertEqual(fake.events.prefix(3), ["localRead", "encrypt", "localWrite"])
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testContextSwitchDuringEncryptionRejectsOldWriteAndRouting() async throws {
        let fake = Fake()
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        service.activate(a)
        // Deterministic suspension seam: context changes inside the awaited adapter,
        // before its result is delivered to service. No timers or live cryptography.
        fake.onEncrypt = { service.activate(self.b) }
        do { _ = try await service.select("owner/family/model"); XCTFail("Expected stale context") }
        catch { XCTAssertEqual(error as? ModelPreferenceFailure, .staleContext) }
        XCTAssertTrue(fake.local.isEmpty)
        XCTAssertTrue(fake.expected.isEmpty)
        XCTAssertEqual(service.selection, "auto")
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testUnavailableRestoreNotifiesBeforeEncryptedAutoPersistence() async throws {
        let fake = Fake(); fake.local[a] = .init(ciphertext: "D:{\"mode\":\"exact\",\"model\":\"gone/model\"}", version: 2)
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in fake.events.append("notify") })
        service.activate(a)
        let restored = try await service.restore()
        XCTAssertEqual(restored, "auto")
        XCTAssertLessThan(try XCTUnwrap(fake.events.firstIndex(of: "notify")), try XCTUnwrap(fake.events.firstIndex(of: "encrypt")))
        XCTAssertEqual(fake.local[a]?.version, 3)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testOlderRemoteEventCannotReplaceNewerLocalSelection() async throws {
        let fake = Fake(); fake.local[a] = .init(ciphertext: "D:{\"mode\":\"auto\"}", version: 4)
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        service.activate(a)
        let selection = try await service.receiveRemote(.init(ciphertext: "D:{\"mode\":\"exact\",\"model\":\"owner/family/model\"}", version: 3), for: a)
        XCTAssertEqual(selection, "auto")
        XCTAssertEqual(fake.local[a]?.version, 4)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testActivationBlocksRoutingUntilRestored() async throws {
        let service = ChatModelPreferenceService(adapters: Fake(), catalog: catalog, notify: { _ in })
        service.activate(a)
        XCTAssertFalse(service.isReady)
        do { _ = try await service.textForSend("Hello"); XCTFail("Must restore the saved chat preference first") }
        catch { XCTAssertEqual(error as? ModelPreferenceFailure, .notRestored) }
        _ = try await service.restore()
        XCTAssertTrue(service.isReady)
        let text = try await service.textForSend("Hello")
        XCTAssertEqual(text, "Hello")
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testFailedSyncRetainsExactCiphertextAndExpectedVersionForRestart() async throws {
        let fake = Fake(); fake.compareError = TestFailure.disconnected
        let first = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        first.activate(a)
        do { _ = try await first.select("owner/family/model"); XCTFail("Expected disconnect") } catch { }
        let staged = try XCTUnwrap(fake.local[a])
        XCTAssertEqual(staged.pendingExpectedVersion, 0)
        XCTAssertFalse(first.isReady)
        fake.compareError = nil
        let restarted = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        restarted.activate(a)
        let restored = try await restarted.restore()
        XCTAssertEqual(restored, "owner/family/model")
        XCTAssertEqual(fake.local[a]?.ciphertext, staged.ciphertext)
        XCTAssertEqual(fake.expected, [0, 0])
        XCTAssertNil(fake.local[a]?.pendingExpectedVersion)
        XCTAssertEqual(fake.events.filter { $0 == "encrypt" }.count, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testLostAckReplayRecognizesCommittedCiphertextWithoutAnotherVersion() async throws {
        let fake = Fake(); fake.loseAcknowledgement = true
        let first = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        first.activate(a)
        do { _ = try await first.select("owner/family/model"); XCTFail("Expected lost ack") } catch { }
        XCTAssertEqual(fake.remote?.version, 1)
        fake.conflicts = 1
        let restarted = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        restarted.activate(a)
        _ = try await restarted.restore()
        XCTAssertEqual(fake.expected, [0, 0])
        XCTAssertEqual(fake.local[a]?.version, 1)
        XCTAssertNil(fake.local[a]?.pendingExpectedVersion)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testRepeatedConflictRestoresLatestRemoteAndSurfacesFailure() async throws {
        let fake = Fake(); fake.conflicts = 2
        fake.remote = .init(ciphertext: "D:{\"mode\":\"auto\"}", version: 8)
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        service.activate(a)
        do { _ = try await service.select("owner/family/model"); XCTFail("Expected conflict") }
        catch { XCTAssertEqual(error as? ModelPreferenceFailure, .repeatedConflict) }
        XCTAssertEqual(service.selection, "auto")
        XCTAssertEqual(fake.local[a]?.version, 8)
        XCTAssertNil(fake.local[a]?.pendingExpectedVersion)
        XCTAssertTrue(service.isReady)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testFailedUnavailableResetCannotRouteAutoOnTheNextSend() async throws {
        let fake = Fake()
        var routing = catalog()
        let service = ChatModelPreferenceService(adapters: fake, catalog: { routing }, notify: { _ in })
        service.activate(a)
        _ = try await service.select("owner/family/model")
        routing.unhealthyServers = ["host"]
        fake.compareError = TestFailure.disconnected
        do { _ = try await service.textForSend("Hello"); XCTFail("Expected failed Auto sync") } catch { }
        XCTAssertFalse(service.isReady)
        do { _ = try await service.textForSend("Hello"); XCTFail("Must surface pending recovery, not silently route Auto") }
        catch { XCTAssertEqual(error as? ModelPreferenceFailure, .notRestored) }
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testTwoWindowsSerializeLocalStageThroughAcknowledgementWithoutLosingPendingIntent() async throws {
        let fake = Fake(); fake.mutationCoordinator = ModelPreferenceMutationCoordinator()
        let first = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        let second = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        first.activate(a); second.activate(a)
        let started = expectation(description: "first CAS suspended")
        var release: CheckedContinuation<Void, Never>?
        fake.onCompare = {
            if fake.expected.count == 1 { await withCheckedContinuation { release = $0; started.fulfill() } }
        }
        let firstTask = Task { try await first.select("owner/family/model") }
        await fulfillment(of: [started], timeout: 2)
        let firstPending = try XCTUnwrap(fake.local[a])
        let secondTask = Task { try await second.select("auto") }
        _ = try await fake.mutationCoordinator?.perform(b) { "independent account" }
        XCTAssertEqual(fake.local[a], firstPending, "The second window must not overwrite the first staged/ACK cycle")
        release?.resume()
        _ = try await firstTask.value; _ = try await secondTask.value
        XCTAssertEqual(fake.expected, [0, 1])
        XCTAssertEqual(fake.local[a]?.version, 2)
        XCTAssertEqual(fake.local[a]?.ciphertext, "D:{\"mode\":\"auto\"}")
        XCTAssertNil(fake.local[a]?.pendingExpectedVersion)
    }
    private enum TestFailure: Error { case disconnected }
    @MainActor final class Fake: ModelPreferenceAdapters {
        var local: [ModelPreferenceScope: EncryptedModelPreference] = [:]
        var remote: EncryptedModelPreference?
        var conflicts = 0
        var expected: [Int] = []
        var events: [String] = []
        var onEncrypt: (() -> Void)?
        var compareError: Error?
        var loseAcknowledgement = false
        var mutationCoordinator: ModelPreferenceMutationCoordinator?
        var onCompare: (() async -> Void)?
        func withMutationLease(_ scope: ModelPreferenceScope, operation: @escaping @MainActor () async throws -> String) async throws -> String {
            if let mutationCoordinator { return try await mutationCoordinator.perform(scope, operation: operation) }
            return try await operation()
        }
        func encryptFormatD(_ plaintext: String, scope: ModelPreferenceScope) async throws -> String { events.append("encrypt"); onEncrypt?(); return "D:" + plaintext }
        func decryptFormatD(_ ciphertext: String, scope: ModelPreferenceScope) async throws -> String { String(ciphertext.dropFirst(2)) }
        func localRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? { events.append("localRead"); return local[scope] }
        func localWrite(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws { events.append("localWrite"); local[scope] = record }
        func localWriteIfNewer(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference {
            if let current = local[scope], current.version >= record.version { return current }
            local[scope] = record; return record
        }
        func remoteRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? { remote }
        func compareAndSet(_ record: EncryptedModelPreference, expected: Int, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference? {
            self.expected.append(expected)
            await onCompare?()
            if let compareError { throw compareError }
            if conflicts > 0 { conflicts -= 1; return nil }
            let accepted = EncryptedModelPreference(ciphertext: record.ciphertext, version: expected + 1)
            remote = accepted
            if loseAcknowledgement { loseAcknowledgement = false; throw TestFailure.disconnected }
            return accepted
        }
    }
}
