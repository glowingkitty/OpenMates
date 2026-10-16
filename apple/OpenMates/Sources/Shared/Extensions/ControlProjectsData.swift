// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability, apple-controls.quick-actions, apple-controls.workflow, apple-controls.project, apple-controls.private-cache
// Native system Controls. No product screen counterpart; routes to existing Projects workspace.
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context
import AppIntents
import CryptoKit
import Foundation
import Security

struct ControlProjectSummary: Codable, Equatable, Sendable { let id: String; let title: String }
struct ControlProjectsSnapshot: Codable, Equatable, Sendable {
    let owner: String
    let teamID: String?
    let projects: [ControlProjectSummary]
}
struct ControlProjectRoute: Equatable {
    let identifier: String
    static func parse(_ url: URL) -> Self? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme == "openmates", parts.host == "control-project",
              parts.user == nil, parts.password == nil, parts.port == nil, parts.fragment == nil,
              parts.path.isEmpty, let items = parts.queryItems, items.count == 1,
              items[0].name == "target", let id = items[0].value, valid(id) else { return nil }
        return .init(identifier: id)
    }
    static func valid(_ identifier: String) -> Bool {
        let parts = identifier.split(separator: ":", omittingEmptySubsequences: false)
        return parts.count == 2 && parts[0].utf8.count == 64 && parts[0].utf8.allSatisfy {
            (48...57).contains($0) || (97...102).contains($0)
        } && WidgetWorkflowsLinks.safeID(String(parts[1]))
    }
    var url: URL? {
        guard Self.valid(identifier) else { return nil }
        var parts = URLComponents(); parts.scheme = "openmates"; parts.host = "control-project"
        parts.queryItems = [.init(name: "target", value: identifier)]
        return parts.url
    }
    func project(in snapshot: ControlProjectsSnapshot) -> ControlProjectSummary? {
        snapshot.projects.first { snapshot.owner + ":" + $0.id == identifier }
    }
}
enum ControlProjectsSnapshotCodec {
    static func seal(_ snapshot: ControlProjectsSnapshot, key: SymmetricKey) throws -> Data {
        let box = try AES.GCM.seal(JSONEncoder().encode(snapshot), using: key, authenticating: Data(snapshot.owner.utf8))
        guard let bytes = box.combined else { throw CodecError.invalid }
        return bytes
    }
    static func open(_ bytes: Data, owner: String, key: SymmetricKey) throws -> ControlProjectsSnapshot {
        let data = try AES.GCM.open(AES.GCM.SealedBox(combined: bytes), using: key, authenticating: Data(owner.utf8))
        let snapshot = try JSONDecoder().decode(ControlProjectsSnapshot.self, from: data)
        guard snapshot.owner == owner else { throw CodecError.invalid }
        return snapshot
    }
    private enum CodecError: Error { case invalid }
}


@MainActor
final class ControlProjectsStorage {
    static let shared = ControlProjectsStorage()
    private let defaults: UserDefaults?
    private let loadKey: @MainActor (Bool) throws -> SymmetricKey
    private let deleteKey: @MainActor () -> Void
    init(defaults: UserDefaults? = UserDefaults(suiteName: WidgetWorkflowsStorage.suiteName),
         loadKey: @escaping @MainActor (Bool) throws -> SymmetricKey = ControlProjectsKeychain.load,
         deleteKey: @escaping @MainActor () -> Void = ControlProjectsKeychain.clear) {
        self.defaults = defaults; self.loadKey = loadKey; self.deleteKey = deleteKey
    }
    func activate(owner: String?) {
        guard defaults?.string(forKey: "control_projects_owner") != owner else { return }
        clear(); defaults?.set(owner, forKey: "control_projects_owner")
    }
    func save(_ snapshot: ControlProjectsSnapshot) throws {
        guard defaults?.string(forKey: "control_projects_owner") == snapshot.owner else { return }
        defaults?.set(try ControlProjectsSnapshotCodec.seal(snapshot, key: loadKey(true)), forKey: "control_projects_ciphertext")
    }
    func load() -> ControlProjectsSnapshot? {
        guard let owner = defaults?.string(forKey: "control_projects_owner"),
              let bytes = defaults?.data(forKey: "control_projects_ciphertext"), let key = try? loadKey(false) else { return nil }
        return try? ControlProjectsSnapshotCodec.open(bytes, owner: owner, key: key)
    }
    func clear() {
        defaults?.removeObject(forKey: "control_projects_owner")
        defaults?.removeObject(forKey: "control_projects_ciphertext"); deleteKey()
    }
}
@MainActor
private enum ControlProjectsKeychain {
    static func query() -> [CFString: Any] {
        var query: [CFString: Any] = [kSecClass: kSecClassGenericPassword,
            kSecAttrService: "org.openmates.app.projects-control", kSecAttrAccount: "projects-snapshot-v1",
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


struct ControlProjectEntity: AppEntity {
    static var typeDisplayRepresentation: TypeDisplayRepresentation { .init(name: "navigation.projects") }
    static var defaultQuery: ControlProjectQuery { .init() }
    let id: String
    let title: String
    var displayRepresentation: DisplayRepresentation { .init(title: "\(title)") }
}
struct ControlProjectQuery: EntityQuery {
    func suggestedEntities() async throws -> [ControlProjectEntity] {
        await MainActor.run {
            guard let snapshot = ControlProjectsStorage.shared.load() else { return [] }
            return snapshot.projects.map { .init(id: snapshot.owner + ":" + $0.id, title: $0.title) }
        }
    }
    func entities(for identifiers: [String]) async throws -> [ControlProjectEntity] {
        try await suggestedEntities().filter { identifiers.contains($0.id) }
    }
}

@MainActor
enum ControlProjectNavigation {
    /// Completion mutates the SwiftUI task identity only after selected detail loading finishes.
    static func selectAndComplete(isCurrent: () -> Bool, select: () async -> Void, complete: () -> Void) async {
        guard !Task.isCancelled, isCurrent() else { return }
        await select()
        guard !Task.isCancelled, isCurrent() else { return }
        complete()
    }
}
