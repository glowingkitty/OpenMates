// UI-test fixtures of the chat sidebar on the Rust core (plan
// apple-client-core-migration A4 lane 2). The sidebar reads its rows only
// from the core (`CoreChatList`), so a launch-argument fixture that used to
// seed the Swift `ChatStore` also seeds the core: before the app core exists,
// its rows go through the core's test-only C seed
// (`openmates_test_support_seed_chat_list`, crate feature `test-support`),
// which writes them with the core's real cache write path into a fresh
// fixture cache and returns a synthetic account's credential payload. The app
// core is then created over that cache with an in-memory credential store and
// an unreachable API origin, and `start` emits the cached `ChatList` exactly
// like a restored session; admission then fails `Offline`, so the list stays.
// No Swift-side list, no bypass in `CoreChatList`.
//
// Compiled only with the Swift condition OPENMATES_CORE_TEST_SUPPORT, which
// the CI test lanes set together with OPENMATES_CORE_TEST_SUPPORT=YES for the
// OpenMatesCore phase (scripts/ci_apple.py). Release builds never set it; a
// non-Debug build that does fails below, and a library built without the
// feature fails the link on the missing symbol.
// Fixtures: --ui-test-authenticated-chat-navigation (MainAppView
// `seedChatNavigationUITestState`), --ui-test-shell-performance-fixture
// (`seedShellPerformanceUITestStateIfNeeded`); same ids, titles, times and pins.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract

#if OPENMATES_CORE_TEST_SUPPORT && !DEBUG
#error("OPENMATES_CORE_TEST_SUPPORT is for Debug test builds only; Release and archive builds never carry core test fixtures.")
#endif

#if (os(iOS) || os(macOS)) && !OPENMATES_SHARE_EXTENSION && OPENMATES_CORE_TEST_SUPPORT
import Foundation

/// The core's test-only seed entry (C ABI, `view_fixture_ffi.rs`). Pointer and
/// `Int`-sized integer arguments with an `Int32` result: the same registers
/// in the C and Swift calling conventions on the 64-bit Apple targets.
@_silgen_name("openmates_test_support_seed_chat_list")
private func openmatesTestSupportSeedChatList(
    _ request: UnsafePointer<UInt8>, _ requestLength: Int,
    _ out: UnsafeMutablePointer<UInt8>, _ outCapacity: Int,
    _ outLength: UnsafeMutablePointer<Int>) -> Int32

@MainActor
enum CoreUITestSeed {
    /// Nothing listens on the discard port: the synthetic account is never
    /// sent to a real server, and admission fails `Offline`.
    static let apiURL = "http://127.0.0.1:9"
    /// Fixture cache folder, separate from the product cache (`openmates-core`).
    static let cacheDirectoryName = "openmates-core-ui-test"
    private static var launched = false

    /// Seeds the requested fixture's chats and creates the app core over
    /// them. Returns `false` when no core-seeded fixture is requested. A
    /// failed seed stops the app: a fixture must never fall back to the
    /// product core.
    static func launchIfRequested() -> Bool {
        guard let chats = requestedChats() else { return false }
        do {
            let container = try FileManager.default.url(
                for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let directory = container.appendingPathComponent(cacheDirectoryName, isDirectory: true)
            if FileManager.default.fileExists(atPath: directory.path) {
                try FileManager.default.removeItem(at: directory)
            }
            let payload = try seed(chats: chats, cacheContainer: container.path)
            try CoreSession.launchSeededFixture(
                config: CoreConfig(apiUrl: apiURL, appUrl: ServerProfile.current().webBaseURL.absoluteString,
                    cacheContainer: container.path, cacheDirectoryName: cacheDirectoryName),
                credentials: CoreUITestCredentialStore(payload: payload))
        } catch {
            fatalError("UI-test core seed failed: \(CoreSession.errorClass(error))")
        }
        launched = true
        NativeDiagnostics.info("core_ui_test_seed rows=\(chats.count)", category: "core_bridge")
        return true
    }

    /// Runs `start` on the seeded core (after `CoreChatList.launch()`, so the
    /// cached `ChatList` reaches the list). `Offline` is the expected end.
    static func startIfLaunched() {
        guard launched, let session = CoreSession.shared else { return }
        Task { @MainActor in
            do {
                try await session.start()
            } catch CoreError.Offline {
                // Expected: the fixture account exists on no server.
            } catch {
                NativeDiagnostics.error(
                    "core_ui_test_seed_start_failed error=\(CoreSession.errorClass(error))", category: "core_bridge")
            }
        }
    }

    /// Calls the C seed; returns the credential payload or throws its reason.
    private static func seed(chats: [[String: Any]], cacheContainer: String) throws -> Data {
        let request = try JSONSerialization.data(withJSONObject: [
            "api_url": apiURL, "cache_container": cacheContainer,
            "cache_directory_name": cacheDirectoryName, "chats": chats,
        ])
        var out = [UInt8](repeating: 0, count: 64 * 1024)
        var length = 0
        let code: Int32 = request.withUnsafeBytes { raw in
            out.withUnsafeMutableBufferPointer { buffer in
                guard let requestBase = raw.bindMemory(to: UInt8.self).baseAddress,
                      let outBase = buffer.baseAddress else { return -1 }
                return openmatesTestSupportSeedChatList(requestBase, raw.count, outBase, buffer.count, &length)
            }
        }
        let bytes = Data(out.prefix(min(length, out.count)))
        guard code == 0 else {
            throw CoreError.Invalid(message: "seed code \(code): \(String(decoding: bytes, as: UTF8.self))")
        }
        return bytes
    }

    /// The core rows of the requested fixture (`nil`: none requested).
    private static func requestedChats() -> [[String: Any]]? {
        let arguments = ProcessInfo.processInfo.arguments
        let environment = ProcessInfo.processInfo.environment
        let now = Int64(Date().timeIntervalSince1970)
        if arguments.contains("--ui-test-authenticated-chat-navigation")
            || environment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] == "1" {
            return chatNavigationChats(now: now)
        }
        if arguments.contains("--ui-test-shell-performance-fixture")
            || environment["UI_TEST_SHELL_PERFORMANCE_FIXTURE"] == "1" {
            let count = min(max(environment["UI_TEST_SHELL_CHAT_COUNT"].flatMap(Int.init) ?? 600, 1), 2_000)
            return (0..<count).map { index in
                let time = now - Int64(index * 60)
                return ["id": "ui-test-shell-perf-chat-\(index)", "title": "Shell Perf Chat \(index + 1)",
                        "summary": "Seeded shell performance chat", "category": "productivity",
                        "icon": "message-square", "app_id": "openmates",
                        "created_at": time, "updated_at": time, "last_message_at": time, "pinned": index < 5]
            }
        }
        return nil
    }

    /// The draft-only chat, three titled chats with one message each and the
    /// empty shell chat of `seedChatNavigationUITestState`.
    private static func chatNavigationChats(now: Int64) -> [[String: Any]] {
        func titled(_ id: String, _ title: String, _ summary: String, age: Int64) -> [String: Any] {
            let time = now - age
            return ["id": id, "title": title, "summary": summary, "category": "general_knowledge",
                    "icon": "message-square", "app_id": "general_knowledge",
                    "created_at": time, "updated_at": time, "last_message_at": time,
                    "messages": [["role": "user", "content": title, "created_at": time]]]
        }
        return [
            ["id": "ui-test-draft-chat", "created_at": now - 30, "updated_at": now - 30,
             "draft": "Header navigation draft"],
            titled("ui-test-newer-chat", "Newer Chat", "Newer seeded chat", age: 60),
            titled("ui-test-current-chat", "Current Chat", "Selected seeded chat", age: 120),
            titled("ui-test-older-chat", "Older Chat", "Older seeded chat", age: 180),
            ["id": "ui-test-empty-shell-chat", "app_id": "general_knowledge",
             "created_at": now - 240, "updated_at": now - 240],
        ]
    }
}

/// In-memory credential store of the seeded fixture core: returns the seed's
/// payload and keeps and acknowledges what the core stores. Never the Keychain.
final class CoreUITestCredentialStore: CoreAcknowledgingCredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var payload: Data?
    private weak var core: ViewModelCore?

    init(payload: Data) {
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
        do {
            try core?.acknowledgeCredentials(revision: snapshot.revision)
        } catch {
            NativeDiagnostics.warning("core_ui_test_credentials_ack_failed", category: "core_bridge")
        }
    }

    func delete() throws {
        lock.lock()
        payload = nil
        lock.unlock()
    }
}
#endif
