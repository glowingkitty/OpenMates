// Minimal encrypted scheduled-workflow inventory shared by app and widget extension.
import AppIntents
import CryptoKit
import Foundation
import Security
import WidgetKit

struct WidgetWorkflowSummary: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let versionID: String
}
struct WidgetWorkflowsSnapshot: Codable, Equatable, Sendable {
    let owner: String
    let teamID: String?
    let updatedAt: Date
    let workflows: [WidgetWorkflowSummary]
}
enum WidgetWorkflowsOwner {
    static func identity(accountID: String, apiBaseURL: URL, teamID: String?) -> String {
        let encoded = (try? JSONEncoder().encode([accountID, apiBaseURL.absoluteString, teamID ?? ""])) ?? Data()
        return SHA256.hash(data: encoded).map { String(format: "%02x", $0) }.joined()
    }
}
struct WidgetWorkflowRunRoute: Codable, Equatable, Sendable {
    let workflowID: String
    let owner: String
    let teamID: String?
    let requestID: UUID
    func belongsTo(accountID: String, apiBaseURL: URL, teamID: String?) -> Bool {
        self.teamID == teamID && owner == WidgetWorkflowsOwner.identity(accountID: accountID, apiBaseURL: apiBaseURL, teamID: teamID)
    }
}
enum WidgetWorkflowsLinks {
    static let workspace = URL(string: "openmates://workflows")!
    static func run(_ id: String, owner: String, teamID: String?, requestID: UUID = UUID()) -> URL? {
        guard safeID(id), validOwner(owner), teamID.map(safeID) ?? true else { return nil }
        var parts = URLComponents(); parts.scheme = "openmates"; parts.host = "run-workflow"; parts.path = "/" + id
        parts.queryItems = [URLQueryItem(name: "owner", value: owner), URLQueryItem(name: "request", value: requestID.uuidString)]
        if let teamID { parts.queryItems?.append(URLQueryItem(name: "team", value: teamID)) }
        return parts.url
    }
    static func route(_ url: URL) -> WidgetWorkflowRunRoute? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false), parts.scheme == "openmates",
              parts.host == "run-workflow", parts.user == nil, parts.password == nil, parts.port == nil,
              parts.fragment == nil, parts.path.hasPrefix("/"), safeID(String(parts.path.dropFirst())) else { return nil }
        let query = parts.queryItems ?? []
        guard Set(query.map(\.name)).count == query.count, query.allSatisfy({ ["owner", "team", "request"].contains($0.name) }),
              let owner = query.first(where: { $0.name == "owner" })?.value, validOwner(owner),
              let request = query.first(where: { $0.name == "request" })?.value, let requestID = UUID(uuidString: request) else { return nil }
        let team = query.first(where: { $0.name == "team" })?.value
        guard !query.contains(where: { $0.name == "team" }) || team.map(safeID) == true else { return nil }
        return .init(workflowID: String(parts.path.dropFirst()), owner: owner, teamID: team, requestID: requestID)
    }
    static func safeID(_ id: String) -> Bool {
        !id.isEmpty && id.utf8.count <= 128 && id.utf8.allSatisfy { (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45 || $0 == 95 }
    }
    private static func validOwner(_ owner: String) -> Bool { owner.utf8.count == 64 && owner.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) } }
}

enum WidgetWorkflowsSnapshotCodec {
    static func seal(_ snapshot: WidgetWorkflowsSnapshot, key: SymmetricKey) throws -> Data {
        let box = try AES.GCM.seal(JSONEncoder().encode(snapshot), using: key, authenticating: Data(snapshot.owner.utf8))
        guard let bytes = box.combined else { throw CodecError.invalid }
        return bytes
    }
    static func open(_ bytes: Data, owner: String, key: SymmetricKey) throws -> WidgetWorkflowsSnapshot {
        let data = try AES.GCM.open(AES.GCM.SealedBox(combined: bytes), using: key, authenticating: Data(owner.utf8))
        let snapshot = try JSONDecoder().decode(WidgetWorkflowsSnapshot.self, from: data)
        guard snapshot.owner == owner else { throw CodecError.invalid }
        return snapshot
    }
    private enum CodecError: Error { case invalid }
}

/// Dedicated WhenUnlocked device-only key. App Group defaults contain ciphertext
/// and an opaque owner, never account IDs, plaintext titles, session or chat keys.
@MainActor
final class WidgetWorkflowsStorage {
    static let shared = WidgetWorkflowsStorage()
    nonisolated static let suiteName = "group.org.openmates.app.shared"
    nonisolated static let kind = "WorkflowsWidget"
    nonisolated static let languageKey = "widget_workflows_language"
    nonisolated static let ownerKey = "widget_workflows_owner"
    nonisolated static let snapshotKey = "widget_workflows_encrypted_snapshot_v1"
    private let defaults: UserDefaults?
    private let loadKey: @MainActor (Bool) throws -> SymmetricKey
    private let deleteKey: @MainActor () -> Void

    init(defaults: UserDefaults? = UserDefaults(suiteName: suiteName),
         loadKey: @escaping @MainActor (Bool) throws -> SymmetricKey = WidgetWorkflowsKeychain.load,
         deleteKey: @escaping @MainActor () -> Void = WidgetWorkflowsKeychain.clear) {
        self.defaults = defaults; self.loadKey = loadKey; self.deleteKey = deleteKey
    }
    func activate(owner: String?) {
        guard defaults?.string(forKey: Self.ownerKey) != owner else { return }
        clear()
        if let owner { defaults?.set(owner, forKey: Self.ownerKey) }
    }
    func save(_ snapshot: WidgetWorkflowsSnapshot) throws {
        guard defaults?.string(forKey: Self.ownerKey) == snapshot.owner else { return }
        defaults?.set(try WidgetWorkflowsSnapshotCodec.seal(snapshot, key: loadKey(true)), forKey: Self.snapshotKey)
    }
    func load() -> WidgetWorkflowsSnapshot? {
        guard let owner = defaults?.string(forKey: Self.ownerKey), let bytes = defaults?.data(forKey: Self.snapshotKey),
              let key = try? loadKey(false) else { return nil }
        return try? WidgetWorkflowsSnapshotCodec.open(bytes, owner: owner, key: key)
    }
    /// A Run tap creates an encrypted, short-lived capability. URL content alone
    /// never authorizes execution. Acceptance consumes the issued capability.
    @discardableResult
    func authorize(_ proposed: WidgetWorkflowRunRoute, now: Date = Date()) throws -> WidgetWorkflowRunRoute {
        guard let snapshot = load(), snapshot.owner == proposed.owner, snapshot.teamID == proposed.teamID,
              let item = snapshot.workflows.first(where: { $0.id == proposed.workflowID }) else { throw RequestError.unavailable }
        let secret = try loadKey(false)
        var retained: [RunTicket] = []
        for key in defaults?.dictionaryRepresentation().keys ?? Dictionary<String, Any>().keys {
            guard key.hasPrefix("widget_workflows_pending_") else { continue }
            guard let bytes = defaults?.data(forKey: key), let ticket = decodeTicket(bytes, owner: proposed.owner, key: secret) else { continue }
            if ticket.dispatched || ticket.expiresAt > now { retained.append(ticket) }
            else { defaults?.removeObject(forKey: key) }
        }
        if retained.contains(where: { $0.dispatched && $0.route.workflowID == proposed.workflowID && $0.versionID != item.versionID }) {
            throw RequestError.unavailable
        }
        var ticket: RunTicket
        if let previous = retained.first(where: { $0.route.workflowID == proposed.workflowID && $0.route.owner == proposed.owner && $0.route.teamID == proposed.teamID && $0.versionID == item.versionID }) {
            ticket = previous
            ticket.expiresAt = now.addingTimeInterval(120)
        } else {
            guard retained.count < 16 else { throw RequestError.unavailable }
            ticket = RunTicket(route: proposed, versionID: item.versionID, expiresAt: now.addingTimeInterval(120), dispatched: false)
        }
        try saveTicket(ticket, key: secret)
        return ticket.route
    }
    private func decodeTicket(_ bytes: Data, owner: String, key: SymmetricKey) -> RunTicket? {
        guard let box = try? AES.GCM.SealedBox(combined: bytes),
              let plaintext = try? AES.GCM.open(box, using: key, authenticating: Data(owner.utf8)) else { return nil }
        return try? JSONDecoder().decode(RunTicket.self, from: plaintext)
    }
    private func saveTicket(_ ticket: RunTicket, key: SymmetricKey) throws {
        let box = try AES.GCM.seal(JSONEncoder().encode(ticket), using: key, authenticating: Data(ticket.route.owner.utf8))
        guard let bytes = box.combined else { throw RequestError.unavailable }
        defaults?.set(bytes, forKey: "widget_workflows_pending_" + ticket.route.requestID.uuidString)
    }
    func markDispatched(_ route: WidgetWorkflowRunRoute) throws {
        let name = "widget_workflows_pending_" + route.requestID.uuidString
        let key = try loadKey(false)
        guard let bytes = defaults?.data(forKey: name), var ticket = decodeTicket(bytes, owner: route.owner, key: key), ticket.route == route else { throw RequestError.unavailable }
        ticket.dispatched = true
        try saveTicket(ticket, key: key)
    }
    func issuedVersion(_ route: WidgetWorkflowRunRoute, now: Date = Date()) -> String? {
        let key = "widget_workflows_pending_" + route.requestID.uuidString
        guard defaults?.string(forKey: Self.ownerKey) == route.owner, let bytes = defaults?.data(forKey: key) else { return nil }
        guard let secret = try? loadKey(false), let box = try? AES.GCM.SealedBox(combined: bytes),
              let plaintext = try? AES.GCM.open(box, using: secret, authenticating: Data(route.owner.utf8)),
              let ticket = try? JSONDecoder().decode(RunTicket.self, from: plaintext),
              ticket.route == route, ticket.expiresAt > now,
              let snapshot = load(), snapshot.owner == route.owner, snapshot.teamID == route.teamID,
              snapshot.workflows.contains(where: { $0.id == route.workflowID && $0.versionID == ticket.versionID }) else { return nil }
        return ticket.versionID
    }
    func consume(_ route: WidgetWorkflowRunRoute) {
        let name = "widget_workflows_pending_" + route.requestID.uuidString
        guard defaults?.string(forKey: Self.ownerKey) == route.owner,
              let bytes = defaults?.data(forKey: name), let key = try? loadKey(false),
              let ticket = decodeTicket(bytes, owner: route.owner, key: key), ticket.route == route else { return }
        defaults?.removeObject(forKey: name)
    }
    private struct RunTicket: Codable { let route: WidgetWorkflowRunRoute; let versionID: String; var expiresAt: Date; var dispatched: Bool }
    private enum RequestError: Error { case unavailable }
    @discardableResult
    func setLanguage(_ language: String) -> Bool {
        guard defaults?.string(forKey: Self.languageKey) != language else { return false }
        defaults?.set(language, forKey: Self.languageKey)
        return true
    }
    func clear() {
        for key in defaults?.dictionaryRepresentation().keys ?? Dictionary<String, Any>().keys {
            if key.hasPrefix("widget_workflows_pending_") { defaults?.removeObject(forKey: key) }
        }
        defaults?.removeObject(forKey: Self.ownerKey); defaults?.removeObject(forKey: Self.snapshotKey); deleteKey()
    }
}
@MainActor
private enum WidgetWorkflowsKeychain {
    static func query() -> [CFString: Any] {
        var query: [CFString: Any] = [kSecClass: kSecClassGenericPassword,
            kSecAttrService: "org.openmates.app.workflows-widget", kSecAttrAccount: "workflows-snapshot-v1",
            kSecAttrSynchronizable: false]
        if let group = Bundle.main.object(forInfoDictionaryKey: "OpenMatesKeychainAccessGroup") as? String,
           !group.isEmpty, !group.contains("$(") { query[kSecAttrAccessGroup] = group }
        return query
    }
    static func clear() { WidgetSnapshotKeychain(baseQuery: query()).clear() }
    static func load(_ create: Bool) throws -> SymmetricKey {
        try WidgetSnapshotKeychain(baseQuery: query()).load(create: create)
    }
}

/// Shared by app and extension so foreground execution runs in the containing
/// app on iOS 17/macOS 14. The existing delivery center queues cold-launch URLs
/// until the app's DeepLinkHandler observer is ready.
struct RunWidgetWorkflowIntent: AppIntent {
    static let title: LocalizedStringResource = "apple.workflows_widget.run"
    static let openAppWhenRun = true
    @Parameter(title: "apple.workflows_widget.workflow_parameter") var identifier: String
    init() {}
    init(identifier: String) { self.identifier = identifier }
    #if DEBUG && !OPENMATES_WIDGET_EXTENSION
    @MainActor static var fixtureActions: [String: @MainActor () throws -> Void] = [:]
    #endif
    @MainActor
    static func deliver(identifier: String, storage: WidgetWorkflowsStorage, receive: (URL) -> Void, openMainWindow: () -> Void = {}) throws {
        guard let snapshot = storage.load(),
              let workflow = snapshot.workflows.first(where: { snapshot.owner + ":" + $0.id == identifier }),
              let proposedURL = WidgetWorkflowsLinks.run(workflow.id, owner: snapshot.owner, teamID: snapshot.teamID),
              let proposed = WidgetWorkflowsLinks.route(proposedURL) else { throw CancellationError() }
        let issued = try storage.authorize(proposed)
        guard let url = WidgetWorkflowsLinks.run(issued.workflowID, owner: issued.owner, teamID: issued.teamID, requestID: issued.requestID) else { throw CancellationError() }
        receive(url)
        openMainWindow()
    }
    @MainActor
    func perform() async throws -> some IntentResult {
        #if !OPENMATES_WIDGET_EXTENSION
        #if DEBUG
        if let action = Self.fixtureActions[identifier] {
            try action()
            return .result()
        }
        #endif
        try Self.deliver(identifier: identifier, storage: .shared,
            receive: { ExternalLinkDeliveryCenter.shared.receive($0) }, openMainWindow: {
                #if os(macOS)
                if !AppWindowCommandCenter.shared.restoreMainWindow() { AppWindowCommandCenter.shared.openNewWindow() }
                #endif
            })
        #endif
        return .result()
    }
}
