// Tests of `CoreSession` (plan apple-client-core-migration A4 lane 1): the
// app's one view-model core over an in-memory credential store (the unsigned
// CI simulator has no Keychain entitlement) and a temporary cache container.
// They cover the signed-out start, the state transitions on start, logout
// wiping the stored payload, failing or cancelled calls settling with a typed
// error instead of hanging, and the profile, passkey and upload calls while
// signed out. No network: the API host never resolves.
import Foundation
import XCTest
@testable import OpenMates

/// In-memory credential store. The core calls it on its own threads, so it
/// is not main-actor isolated; acknowledgements go back to the attached core.
final class InMemoryCredentialStore: CoreAcknowledgingCredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var payload: Data?
    private var deletes = 0
    private weak var core: ViewModelCore?

    init(payload: Data? = nil) {
        self.payload = payload
    }

    func attach(core: ViewModelCore) {
        lock.lock()
        self.core = core
        lock.unlock()
    }

    func load() throws -> Data? {
        lock.lock()
        defer { lock.unlock() }
        return payload
    }

    func credentialsChanged(snapshot: CredentialSnapshotRecord) {
        lock.lock()
        payload = snapshot.payload
        let core = self.core
        lock.unlock()
        try? core?.acknowledgeCredentials(revision: snapshot.revision)
    }

    func delete() throws {
        lock.lock()
        payload = nil
        deletes += 1
        lock.unlock()
    }

    func stored() -> Data? {
        lock.lock()
        defer { lock.unlock() }
        return payload
    }

    func deleteCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return deletes
    }
}

final class CoreSessionTests: XCTestCase {
    private static let apiURL = "https://never-contact.example.invalid"

    @MainActor
    private func makeSession(store: InMemoryCredentialStore) throws -> CoreSession {
        let container = FileManager.default.temporaryDirectory.path
        let name = "core-session-\(UUID().uuidString)"
        let directory = (container as NSString).appendingPathComponent(name)
        addTeardownBlock { try? FileManager.default.removeItem(atPath: directory) }
        return try CoreSession(
            config: CoreConfig(
                apiUrl: Self.apiURL, appUrl: "https://app.example.invalid",
                cacheContainer: container, cacheDirectoryName: name),
            credentials: store)
    }

    /// Polls `condition` for up to five seconds; core events arrive asynchronously.
    @MainActor
    private func waitUntil(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async throws {
        for _ in 0..<500 {
            if condition() { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("condition not reached", file: file, line: line)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.credentials.snapshot-boundary
    @MainActor
    func testStartsSignedOutWithAnEmptyCredentialStore() async throws {
        let store = InMemoryCredentialStore()
        let session = try makeSession(store: store)
        XCTAssertEqual(session.state, .notStarted)

        try await session.start()
        try await waitUntil { session.state == .signedOut }
        XCTAssertNil(store.stored())
        XCTAssertNil(session.lastError)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testStartReportsEachSessionEventInCoreOrder() async throws {
        let session = try makeSession(store: InMemoryCredentialStore())
        var states: [CoreSessionState] = []
        let observation = session.$state.sink { states.append($0) }
        defer { observation.cancel() }
        var events: [ViewEventRecord] = []
        let forwarded = session.events.sink { events.append($0) }
        defer { forwarded.cancel() }

        try await session.start()
        try await waitUntil { states.last == .signedOut }
        XCTAssertEqual(states, [.notStarted, .starting, .signedOut])
        XCTAssertEqual(events, [.session(event: .signedOut)])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.credentials.snapshot-boundary
    @MainActor
    func testLogoutWipesTheStoredPayloadAndReportsSignedOut() async throws {
        let store = InMemoryCredentialStore(payload: Data("synthetic-stored-session".utf8))
        let session = try makeSession(store: store)

        try await session.logout()
        try await waitUntil { session.state == .signedOut }
        XCTAssertNil(store.stored())
        XCTAssertGreaterThanOrEqual(store.deleteCount(), 1)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testAFailingCallSurfacesTheCoreErrorAndDoesNotHang() async throws {
        let session = try makeSession(store: InMemoryCredentialStore())
        try await session.start()
        do {
            try await session.perform { core, cancellation in
                try await core.refreshChats(cancellation: cancellation)
            }
            XCTFail("refresh without a session succeeded")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Authentication)
        }
        XCTAssertEqual(session.lastError, .Authentication)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testACancelledCallSettlesWithAnErrorInsteadOfWaiting() async throws {
        let session = try makeSession(store: InMemoryCredentialStore())
        try await session.start()
        let task = Task { @MainActor in
            try await session.perform { core, cancellation in
                try await core.httpRequest(
                    request: HttpRequestRecord(
                        method: "GET", path: "/v1/settings/storage",
                        query: [], headers: [], body: nil),
                    cancellation: cancellation)
            }
        }
        task.cancel()
        let outcome = await task.result
        guard case .failure(let error) = outcome else {
            return XCTFail("cancelled request returned a response")
        }
        // Signed out the core refuses at once; either way the waiter settled.
        let coreError = try XCTUnwrap(error as? CoreError)
        XCTAssertTrue([CoreError.Cancelled, .Authentication].contains(coreError), "unexpected \(coreError)")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testTheProfileReadWhileSignedOutIsAnAuthenticationError() async throws {
        let session = try makeSession(store: InMemoryCredentialStore())
        try await session.start()
        do {
            _ = try await session.userProfile()
            XCTFail("a profile was read without a session")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Authentication)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testPasskeyCallsWithoutABegunRequestSettleTypedAndCancelIsANoOp() async throws {
        let store = InMemoryCredentialStore()
        let session = try makeSession(store: store)
        try await session.start()
        await session.cancelPasskeyLogin()
        do {
            _ = try await session.finishPasskeyLogin(assertionJson: Data("{}".utf8),
                prfOutput: Data(repeating: 1, count: 32), stayLoggedIn: false)
            XCTFail("a passkey finish without a begun login succeeded")
        } catch let error as CoreError {
            guard case .Invalid = error else { return XCTFail("expected CoreError.Invalid, got \(error)") }
        }
        do {
            // The API host never resolves: the core reports it, typed.
            _ = try await session.beginPasskeyLogin(email: nil)
            XCTFail("a passkey login began against an unreachable host")
        } catch let error as CoreError {
            XCTAssertNotEqual(error, .Cancelled)
        }
        XCTAssertEqual(session.state, .signedOut)
        XCTAssertNil(store.stored())
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testAnUploadWhileSignedOutIsRefusedByTheCore() async throws {
        let session = try makeSession(store: InMemoryCredentialStore())
        try await session.start()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("core-upload-\(UUID().uuidString)")
        try Data("synthetic upload".utf8).write(to: file)
        addTeardownBlock { try? FileManager.default.removeItem(at: file) }
        do {
            _ = try await session.uploadFile(UploadRequestRecord(
                url: Self.apiURL + "/v1/upload/file", filePath: file.path, filename: "notes.txt",
                contentType: "text/plain", fields: [HttpFieldRecord(name: "chat_id", value: "fixture-chat")]))
            XCTFail("an upload without a session succeeded")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Authentication)
        }
        XCTAssertEqual(session.lastError, .Authentication)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.credentials.snapshot-boundary
    @MainActor
    func testAnUnusableConfigFailsCreationWithATypedError() {
        XCTAssertThrowsError(try CoreSession(
            config: CoreConfig(
                apiUrl: Self.apiURL, appUrl: nil,
                cacheContainer: FileManager.default.temporaryDirectory.path,
                cacheDirectoryName: "nested/core-session"),
            credentials: InMemoryCredentialStore())) { error in
            guard case .Invalid = error as? CoreError else {
                return XCTFail("expected CoreError.Invalid, got \(error)")
            }
        }
    }
}
