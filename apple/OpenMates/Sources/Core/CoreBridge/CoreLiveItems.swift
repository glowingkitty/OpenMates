// Live collaboration on Docs, Sheets, Slides and code items from the Rust core
// (`LiveItemSession`, packages/openmates-apple-bindings view_live_item.rs).
//
// `CoreLiveItems` owns one core live session for the signed-in account. The
// core builds and parses every `live_item_*` payload, merges updates and keeps
// the sealed outbox queue; this shell only (1) forwards frames between the
// `/v1/ws` socket and the core (`LiveItemSender`, `receive`), (2) stores the
// core's opaque outbox records in files (`LiveOutboxFileStore`), (3) publishes
// the core's events on the main actor and (4) drives the core's 2 s tick and
// connection state. No protocol or merge logic lives here.
//
// Web source: frontend/packages/ui/src/services/rustCore/live
// Specification: specifications/features/live-collaboration/specification.yml
// Assertions: live-collab.core.one-shared-model, live-collab.sync.concurrent-convergence, live-collab.offline.merge-on-reconnect, live-collab.devices.same-account

import Combine
import Foundation

// MARK: - Outbox file store

/// Opaque outbox records, one file per key under `directory`. A lock makes
/// compare-and-put atomic within the process; writes are atomic on disk.
final class LiveOutboxFileStore: LiveOutboxStorage, @unchecked Sendable {
    private let directory: URL
    private let lock = NSLock()

    init(directory: URL) {
        self.directory = directory
    }

    /// The app's store under Application Support `live-outbox/`.
    static func appDefault() -> LiveOutboxFileStore {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return LiveOutboxFileStore(directory: base.appendingPathComponent("live-outbox", isDirectory: true))
    }

    /// File names are the hex of the key, so any key is a safe name.
    private func file(for key: String) -> URL {
        directory.appendingPathComponent(Data(key.utf8).map { String(format: "%02x", $0) }.joined())
    }

    private static func key(fromFileName name: String) -> String? {
        var bytes: [UInt8] = []
        var index = name.startIndex
        while index < name.endIndex {
            guard let next = name.index(index, offsetBy: 2, limitedBy: name.endIndex),
                  let byte = UInt8(name[index..<next], radix: 16) else { return nil }
            bytes.append(byte)
            index = next
        }
        return String(bytes: bytes, encoding: .utf8)
    }

    func keys(prefix: String) -> [String]? {
        lock.lock(); defer { lock.unlock() }
        guard FileManager.default.fileExists(atPath: directory.path) else { return [] }
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: directory.path) else { return nil }
        return names.compactMap { Self.key(fromFileName: $0) }.filter { $0.hasPrefix(prefix) }.sorted()
    }

    func read(key: String) -> LiveOutboxReadRecord {
        lock.lock(); defer { lock.unlock() }
        return readLocked(key)
    }

    private func readLocked(_ key: String) -> LiveOutboxReadRecord {
        let url = file(for: key)
        guard FileManager.default.fileExists(atPath: url.path) else { return .missing }
        guard let data = try? Data(contentsOf: url), let value = String(data: data, encoding: .utf8) else {
            return .unavailable
        }
        return .found(value: value)
    }

    func compareAndPut(key: String, expected: String?, next: String?) -> LiveOutboxWriteRecord {
        lock.lock(); defer { lock.unlock() }
        switch readLocked(key) {
        case .unavailable:
            return .unavailable
        case .missing:
            if expected != nil { return .conflict }
        case .found(let value):
            if expected != value { return .conflict }
        }
        let url = file(for: key)
        do {
            if let next {
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                try Data(next.utf8).write(to: url, options: .atomic)
            } else if FileManager.default.fileExists(atPath: url.path) {
                try FileManager.default.removeItem(at: url)
            }
            return .written
        } catch {
            NativeDiagnostics.error("core_live_outbox_write_failed", category: "core_bridge")
            return .unavailable
        }
    }
}

// MARK: - Socket and listener adapters

/// Sends the core's frames as `{type, payload}` on the app's socket.
private final class LiveSocketSender: LiveItemSender, @unchecked Sendable {
    private let owner: CoreLiveItems
    init(owner: CoreLiveItems) { self.owner = owner }

    func sendFrame(messageType: String, payloadJson: String) -> Bool {
        guard let object = try? JSONSerialization.jsonObject(with: Data(payloadJson.utf8)) as? [String: Any] else {
            return false
        }
        Task { @MainActor [owner] in await owner.transmit(type: messageType, payload: object) }
        return true
    }
}

/// Hops the core's events onto the main actor.
private final class LiveEventForwarder: LiveItemListener, @unchecked Sendable {
    private let owner: CoreLiveItems
    init(owner: CoreLiveItems) { self.owner = owner }

    func onLiveEvent(event: LiveItemEventRecord) {
        Task { @MainActor [owner] in owner.deliver(event) }
    }
}

// MARK: - CoreLiveItems

@MainActor
final class CoreLiveItems: ObservableObject {
    static let shared = CoreLiveItems()

    /// Text form of each open item as the core last reported it.
    @Published private(set) var texts: [String: String] = [:]
    /// Every core event in order (remote updates, view, presence, status, versions).
    let events = PassthroughSubject<LiveItemEventRecord, Never>()

    private let storage: LiveOutboxStorage
    private var session: LiveItemSession?
    private var sessionUserId: String?
    private weak var socket: WebSocketManager?
    private var connectionObserver: AnyCancellable?
    private var isConnected = false
    private var openItems: Set<String> = []
    private var tickTask: Task<Void, Never>?

    init(storage: LiveOutboxStorage = LiveOutboxFileStore.appDefault()) {
        self.storage = storage
    }

    /// True when the core owns a frame of this type (`live_item_*`).
    nonisolated static func routes(_ messageType: String) -> Bool {
        liveIsFrame(messageType: messageType)
    }

    /// The raw JSON text of the frame's `payload` object (`{}` when absent).
    nonisolated static func payloadJSON(fromFrame raw: Data) -> String {
        guard let object = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
              let payload = object["payload"],
              JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let text = String(data: data, encoding: .utf8) else { return "{}" }
        return text
    }

    /// Follows the socket's connection state; called when the socket connects.
    func attach(socket: WebSocketManager) {
        guard self.socket !== socket else { return }
        self.socket = socket
        connectionObserver = socket.$connectionState.sink { [weak self] state in
            Task { @MainActor in await self?.connectionChanged(connected: state == .connected) }
        }
    }

    /// Hands one incoming live frame to the core.
    func receive(type: String, raw: Data) {
        let payload = Self.payloadJSON(fromFrame: raw)
        Task { await forward(type: type, payload: payload) }
    }

    // MARK: Item calls

    func open(itemId: String, kind: String, projectId: String? = nil, teamId: String? = nil) async throws {
        let live = try await ensureSession()
        try await live.open(itemId: itemId, kind: kind, projectId: projectId, teamId: teamId)
        openItems.insert(itemId)
        startTicking()
        refreshTexts()
    }

    func applyUpdate(itemId: String, bytes: Data) async throws {
        try await requireSession().applyUpdate(itemId: itemId, bytes: bytes)
        refreshTexts()
    }

    func applyOp(itemId: String, opJson: String) async throws {
        try await requireSession().applyOp(itemId: itemId, opJson: opJson)
        refreshTexts()
    }

    func setPresence(itemId: String, presenceJson: String) async throws {
        try await requireSession().setPresence(itemId: itemId, presenceJson: presenceJson)
    }

    func close(itemId: String) async throws {
        try await requireSession().close(itemId: itemId)
        openItems.remove(itemId)
        texts[itemId] = nil
        if openItems.isEmpty { stopTicking() }
    }

    /// Drops the session (sign-out or account switch); the outbox files stay for the account.
    func reset() {
        stopTicking()
        session = nil
        sessionUserId = nil
        openItems = []
        texts = [:]
    }

    // MARK: Internals

    private func requireSession() throws -> LiveItemSession {
        guard let session else { throw CoreLiveItemsError.notOpen }
        return session
    }

    private func ensureSession() async throws -> LiveItemSession {
        guard let core = CoreSession.shared?.core, let userId = await AuthManager.currentUserId() else {
            throw CoreLiveItemsError.unavailable
        }
        if let session, sessionUserId == userId { return session }
        reset()
        let created = LiveItemSession(
            core: core, userId: userId, sender: LiveSocketSender(owner: self),
            storage: storage, listener: LiveEventForwarder(owner: self))
        session = created
        sessionUserId = userId
        try await created.setConnected(connected: isConnected)
        return created
    }

    fileprivate func transmit(type: String, payload: [String: Any]) async {
        guard let socket, socket.connectionState == .connected else { return }
        do {
            try await socket.send(WSOutboundMessage(type: type, payload: payload))
        } catch {
            NativeDiagnostics.error("core_live_send_failed class=\(CoreSession.errorClass(error))", category: "core_bridge")
        }
    }

    fileprivate func deliver(_ event: LiveItemEventRecord) {
        events.send(event)
        refreshTexts()
    }

    private func forward(type: String, payload: String) async {
        guard let session else { return }
        do {
            _ = try await session.onFrame(messageType: type, payloadJson: payload)
        } catch {
            NativeDiagnostics.error("core_live_frame_rejected class=\(CoreSession.errorClass(error))", category: "core_bridge")
        }
    }

    private func connectionChanged(connected: Bool) async {
        isConnected = connected
        guard let session else { return }
        do {
            try await session.setConnected(connected: connected)
        } catch {
            NativeDiagnostics.error("core_live_connection_failed class=\(CoreSession.errorClass(error))", category: "core_bridge")
        }
    }

    private func refreshTexts() {
        guard let session else { return }
        for id in openItems {
            if let text = session.textOf(itemId: id), texts[id] != text { texts[id] = text }
        }
    }

    private func startTicking() {
        guard tickTask == nil else { return }
        tickTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                guard let self, !Task.isCancelled else { return }
                await self.tick()
            }
        }
    }

    private func stopTicking() {
        tickTask?.cancel()
        tickTask = nil
    }

    private func tick() async {
        guard let session else { return }
        do {
            try await session.tick()
        } catch {
            NativeDiagnostics.error("core_live_tick_failed class=\(CoreSession.errorClass(error))", category: "core_bridge")
        }
    }
}

enum CoreLiveItemsError: Error, Equatable {
    /// No core or no signed-in account.
    case unavailable
    /// The item was not opened first.
    case notOpen
}
