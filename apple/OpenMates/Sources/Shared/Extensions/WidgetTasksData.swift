// Minimal encrypted Tasks widget snapshot shared by the app and its extension.
// Specification: specifications/features/apple-tasks-widget/specification.yml
// Assertions: apple-tasks-widget.status-filter, apple-tasks-widget.links, apple-tasks-widget.private-cache

// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.lifecycle.isolation
// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.private-cache

import CryptoKit
import Foundation
import LocalAuthentication
import Security
import WidgetKit

enum WidgetTaskFilter: String, Codable, CaseIterable, Sendable {
    case all, todo, inProgress = "in_progress", blocked, backlog, done
}

struct WidgetTaskSummary: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let status: WidgetTaskFilter
}

/// Keep representatives of every status even when one board column is huge.
/// The widget displays at most seven rows, so twelve per status leaves room for
/// a recent mutation without retaining an unbounded decrypted title inventory.
struct WidgetTasksSnapshotBuilder {
    static let perStatusLimit = 12
    static let totalLimit = perStatusLimit * (WidgetTaskFilter.allCases.count - 1)
    private(set) var tasks: [WidgetTaskSummary] = []
    private var counts: [WidgetTaskFilter: Int] = [:]

    var isFull: Bool { tasks.count == Self.totalLimit }

    func hasCapacity(for status: WidgetTaskFilter) -> Bool {
        status != .all && counts[status, default: 0] < Self.perStatusLimit
    }

    mutating func append(_ task: WidgetTaskSummary) {
        guard hasCapacity(for: task.status) else { return }
        tasks.append(task)
        counts[task.status, default: 0] += 1
    }

    static func bounded(_ tasks: [WidgetTaskSummary]) -> [WidgetTaskSummary] {
        var builder = Self()
        for task in tasks {
            builder.append(task)
            if builder.isFull { break }
        }
        return builder.tasks
    }
}

struct WidgetTasksSnapshot: Codable, Equatable, Sendable {
    let owner: String
    let updatedAt: Date
    let tasks: [WidgetTaskSummary]

    /// Count the accepted filtered inventory before a layout truncates visible rows.
    func taskCount(matching filter: WidgetTaskFilter) -> Int {
        tasks.reduce(0) { $0 + (filter == .all || $1.status == filter ? 1 : 0) }
    }

    func tasks(matching filter: WidgetTaskFilter, limit: Int) -> [WidgetTaskSummary] {
        Array(tasks.lazy.filter { filter == .all || $0.status == filter }.prefix(max(0, limit)))
    }
}

/// The same filtered inventory drives home-screen and tiny Lock Screen layouts.
enum WidgetTasksLayout {
    static func rowLimit(for family: WidgetFamily) -> Int {
        switch family {
        case .systemLarge: return 7
        #if os(iOS)
        case .accessoryCircular: return 0
        case .accessoryRectangular: return 1
        #endif
        default: return 3
        }
    }
    static func primaryURL(for family: WidgetFamily, tasks: [WidgetTaskSummary]) -> URL {
        #if os(iOS)
        if family == .accessoryCircular { return WidgetTasksLinks.newTask }
        if family == .accessoryRectangular {
            return tasks.first.flatMap { WidgetTasksLinks.task($0.id) } ?? WidgetTasksLinks.workspace
        }
        #endif
        return WidgetTasksLinks.workspace
    }
}

enum WidgetTasksSnapshotCodec {
    static func seal(_ snapshot: WidgetTasksSnapshot, key: SymmetricKey) throws -> Data {
        let box = try AES.GCM.seal(JSONEncoder().encode(snapshot), using: key,
            authenticating: Data(snapshot.owner.utf8))
        guard let data = box.combined else { throw CodecError.invalidData }
        return data
    }

    static func open(_ data: Data, owner: String, key: SymmetricKey) throws -> WidgetTasksSnapshot {
        let box = try AES.GCM.SealedBox(combined: data)
        let plaintext = try AES.GCM.open(box, using: key, authenticating: Data(owner.utf8))
        let snapshot = try JSONDecoder().decode(WidgetTasksSnapshot.self, from: plaintext)
        guard snapshot.owner == owner else { throw CodecError.invalidOwner }
        return snapshot
    }

    private enum CodecError: Error { case invalidData, invalidOwner }
}

enum WidgetTasksLinks {
    static let newTask = URL(string: "openmates://new-task")!
    static let workspace = URL(string: "openmates://tasks")!

    static func task(_ id: String) -> URL? {
        guard let uuid = UUID(uuidString: id) else { return nil }
        return URL(string: "openmates://task/\(uuid.uuidString.lowercased())")
    }
}

/// App Group contains ciphertext only. This key is dedicated to the widget,
/// never an account master key, task key, auth credential or cloud-synced item.
/// WhenUnlocked prevents reading task titles while the device is locked.
/// The widget's rendered title views also declare privacySensitive().
@MainActor
enum WidgetTasksStorage {
    static let suiteName = "group.org.openmates.app.shared"
    static let kind = "TasksWidget"
    static let languageKey = "widget_tasks_language"
    private static let ownerKey = "widget_tasks_owner"
    private static let snapshotKey = "widget_tasks_encrypted_snapshot_v1"
    private static let keyAccount = "tasks-widget-snapshot-v1"

    static func activate(owner: String?) {
        let defaults = UserDefaults(suiteName: suiteName)
        guard defaults?.string(forKey: ownerKey) != owner else { return }
        clear()
        if let owner { defaults?.set(owner, forKey: ownerKey) }
    }

    static func save(_ snapshot: WidgetTasksSnapshot) throws {
        guard let defaults = UserDefaults(suiteName: suiteName),
              defaults.string(forKey: ownerKey) == snapshot.owner else { return }
        let key = try loadKey(create: true)
        let data = try WidgetTasksSnapshotCodec.seal(snapshot, key: key)
        defaults.set(data, forKey: snapshotKey)
    }

    static func load() -> WidgetTasksSnapshot? {
        guard let defaults = UserDefaults(suiteName: suiteName),
              let owner = defaults.string(forKey: ownerKey),
              let data = defaults.data(forKey: snapshotKey),
              let key = try? loadKey(create: false),
              let snapshot = try? WidgetTasksSnapshotCodec.open(data, owner: owner, key: key) else { return nil }
        return snapshot
    }

    static func clear() {
        let defaults = UserDefaults(suiteName: suiteName)
        defaults?.removeObject(forKey: ownerKey)
        defaults?.removeObject(forKey: snapshotKey)
        WidgetSnapshotKeychain(baseQuery: keyQuery()).clear()
    }

    private static func keyQuery() -> [CFString: Any] {
        var query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: "org.openmates.app.tasks-widget",
            kSecAttrAccount: keyAccount,
            kSecAttrSynchronizable: false,
        ]
        if let group = Bundle.main.object(forInfoDictionaryKey: "OpenMatesKeychainAccessGroup") as? String,
           !group.isEmpty, !group.contains("$(") {
            query[kSecAttrAccessGroup] = group
        }
        return query
    }

    private static func loadKey(create: Bool) throws -> SymmetricKey {
        try WidgetSnapshotKeychain(baseQuery: keyQuery()).load(create: create)
    }

    private enum StorageError: Error { case keyUnavailable, invalidData }
}

/// Dedicated snapshot keys only. Never replace unreadable or malformed keys:
/// existing App Group ciphertext must remain decryptable by the same key.
/// Security's SecItem.h documents the macOS Data Protection selector and the
/// default UI-allow policy. Explicit UI-fail also fences legacy ACL prompts.
@MainActor
struct WidgetSnapshotKeychain {
    @MainActor
    struct Operations {
        let copy: ([CFString: Any]) -> (OSStatus, Data?)
        let add: ([CFString: Any]) -> OSStatus
        let delete: ([CFString: Any]) -> OSStatus

        static let live = Operations(copy: { query in
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            return (status, result as? Data)
        }, add: { SecItemAdd($0 as CFDictionary, nil) },
           delete: { SecItemDelete($0 as CFDictionary) })
    }

    // Internal policy seam lets injected Security operations exercise both
    // namespace policies on any unit-test platform. Production uses this default.
    static var platformUsesMacOSNamespaces: Bool {
        #if os(macOS)
        true
        #else
        false
        #endif
    }

    let baseQuery: [CFString: Any]
    var usesMacOSNamespaces: Bool = WidgetSnapshotKeychain.platformUsesMacOSNamespaces
    var operations: Operations = .live
    var makeKey: () -> Data = { SymmetricKey(size: .bits256).withUnsafeBytes { Data($0) } }
    private enum KeyError: Error { case unavailable }

    private func query(legacy: Bool = false) -> [CFString: Any] {
        var query = baseQuery
        // LAContext is the modern Data Protection no-interaction policy;
        // UI-fail explicitly preserves no-interaction behavior for legacy ACLs.
        let context = LAContext()
        context.interactionNotAllowed = true
        query[kSecUseAuthenticationContext] = context
        query[kSecUseAuthenticationUI] = kSecUseAuthenticationUIFail
        if usesMacOSNamespaces && !legacy { query[kSecUseDataProtectionKeychain] = true }
        return query
    }

    private func read(legacy: Bool = false) -> (OSStatus, Data?) {
        var query = query(legacy: legacy)
        query[kSecReturnData] = true
        query[kSecMatchLimit] = kSecMatchLimitOne
        return operations.copy(query)
    }

    private func valid(_ bytes: Data?) throws -> Data {
        guard let bytes, bytes.count == 32 else { throw KeyError.unavailable }
        return bytes
    }

    private func insert(_ bytes: Data) throws -> SymmetricKey {
        _ = try valid(bytes)
        var insertion = query()
        insertion[kSecValueData] = bytes
        insertion[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        switch operations.add(insertion) {
        case errSecSuccess: return SymmetricKey(data: bytes)
        case errSecDuplicateItem:
            // A concurrent writer can win. Accept only the identical key, never
            // overwrite ciphertext using a different key after a migration race.
            let (status, winner) = read()
            guard status == errSecSuccess, try valid(winner) == bytes else { throw KeyError.unavailable }
            return SymmetricKey(data: bytes)
        default: throw KeyError.unavailable
        }
    }

    func load(create: Bool) throws -> SymmetricKey {
        let (status, bytes) = read()
        if status == errSecSuccess { return SymmetricKey(data: try valid(bytes)) }
        guard status == errSecItemNotFound else { throw KeyError.unavailable }
        if usesMacOSNamespaces {
            let (legacyStatus, legacyBytes) = read(legacy: true)
            if legacyStatus == errSecSuccess {
                // Preserve legacy ciphertext continuity. Never delete the legacy key.
                return try insert(valid(legacyBytes))
            }
            guard legacyStatus == errSecItemNotFound else { throw KeyError.unavailable }
        }
        guard create else { throw KeyError.unavailable }
        return try insert(makeKey())
    }

    /// Called only by the existing logout/account-switch storage clear hooks.
    func clear() {
        _ = operations.delete(query())
        if usesMacOSNamespaces { _ = operations.delete(query(legacy: true)) }
    }
}
