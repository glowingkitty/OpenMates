// Minimal encrypted Active chats snapshot shared by app and WidgetKit extension.
// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.activity.global-running, apple-live-activities.processing.widget
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.lifecycle.isolation
import CryptoKit
import Foundation
import Security
import WidgetKit

struct WidgetActiveChatSummary: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let expiresAt: Date
    var staleAt: Date { expiresAt.addingTimeInterval(-15 * 60 + 90) }
}
struct WidgetActiveChatsSnapshot: Codable, Equatable, Sendable {
    let owner: String
    let teamID: String?
    let updatedAt: Date
    let chats: [WidgetActiveChatSummary]
    func active(at date: Date) -> [WidgetActiveChatSummary] { chats.filter { $0.expiresAt > date } }
}

struct WidgetActiveChatsProjection: Equatable, Sendable {
    let rows: [WidgetActiveChatSummary]
    let total: Int
    var overflow: Int { max(0, total - rows.count) }
    init(snapshot: WidgetActiveChatsSnapshot?, date: Date, limit: Int) {
        let chats = snapshot?.active(at: date) ?? []
        rows = Array(chats.prefix(max(0, limit)))
        total = chats.count
    }
    static func rowLimit(for family: WidgetFamily) -> Int {
        switch family {
        case .systemLarge: return largeLimit
        #if os(iOS)
        case .accessoryCircular: return 0
        case .accessoryRectangular: return 1
        #endif
        default: return mediumLimit
        }
    }
    /// Rectangular opens its visible first chat; circular opens the full census.
    static func primaryURL(for family: WidgetFamily, snapshot: WidgetActiveChatsSnapshot?, date: Date) -> URL {
        guard let snapshot else { return WidgetActiveChatsLinks.openApp }
        #if os(iOS)
        if family == .accessoryRectangular, let chat = snapshot.active(at: date).first,
           let url = WidgetActiveChatsLinks.chat(chat.id, owner: snapshot.owner, teamID: snapshot.teamID) { return url }
        #endif
        return WidgetActiveChatsLinks.all(owner: snapshot.owner, teamID: snapshot.teamID) ?? WidgetActiveChatsLinks.openApp
    }
    static let mediumLimit = 3
    static let largeLimit = 7
}

enum WidgetActiveChatsOwner {
    // Stable across relaunch; runtime scope/team epoch separately fence publication.
    static func identity(accountID: String, apiBaseURL: URL, teamID: String?) -> String {
        let encoded = (try? JSONEncoder().encode([accountID, apiBaseURL.absoluteString, teamID ?? ""])) ?? Data()
        return SHA256.hash(data: encoded).map { String(format: "%02x", $0) }.joined()
    }
}

struct WidgetActiveChatsRoute: Equatable, Sendable {
    enum Destination: Equatable, Sendable { case chat(String), all }
    let destination: Destination
    let owner: String
    let teamID: String?
    func belongsTo(accountID: String, apiBaseURL: URL, teamID: String?) -> Bool {
        self.teamID == teamID && owner == WidgetActiveChatsOwner.identity(accountID: accountID, apiBaseURL: apiBaseURL, teamID: teamID)
    }
}
enum WidgetActiveChatsLinks {
    static let openApp = URL(string: "openmates://")!
    static func chat(_ id: String, owner: String, teamID: String?) -> URL? {
        guard safeID(id) else { return nil }
        return make(host: "chat", path: "/" + id, owner: owner, teamID: teamID)
    }
    static func all(owner: String, teamID: String?) -> URL? { make(host: "active-chats", path: "", owner: owner, teamID: teamID) }
    static func route(_ url: URL) -> WidgetActiveChatsRoute? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme == "openmates", parts.user == nil, parts.password == nil,
              parts.port == nil, parts.fragment == nil else { return nil }
        let query = parts.queryItems ?? []
        guard query.count == (query.contains { $0.name == "team" } ? 2 : 1),
              query.filter({ $0.name == "owner" }).count == 1,
              let owner = query.first(where: { $0.name == "owner" })?.value, validOwner(owner),
              query.allSatisfy({ ["owner", "team"].contains($0.name) }) else { return nil }
        let team = query.first(where: { $0.name == "team" })?.value
        if query.contains(where: { $0.name == "team" }), team.map(safeID) != true { return nil }
        let destination: WidgetActiveChatsRoute.Destination
        if parts.host == "active-chats", parts.path.isEmpty || parts.path == "/" { destination = .all }
        else if parts.host == "chat", parts.path.hasPrefix("/"), safeID(String(parts.path.dropFirst())) {
            destination = .chat(String(parts.path.dropFirst()))
        } else { return nil }
        return WidgetActiveChatsRoute(destination: destination, owner: owner, teamID: team)
    }
    static func safeID(_ id: String) -> Bool {
        !id.isEmpty && id.utf8.count <= 128 && id.unicodeScalars.allSatisfy { scalar in
            (scalar.value >= 48 && scalar.value <= 57) || (scalar.value >= 65 && scalar.value <= 90)
                || (scalar.value >= 97 && scalar.value <= 122) || scalar.value == 45 || scalar.value == 95
        }
    }
    private static func validOwner(_ owner: String) -> Bool {
        owner.utf8.count == 64 && owner.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    private static func make(host: String, path: String, owner: String, teamID: String?) -> URL? {
        guard validOwner(owner), teamID.map(safeID) ?? true else { return nil }
        var url = URLComponents(); url.scheme = "openmates"; url.host = host; url.path = path
        url.queryItems = [URLQueryItem(name: "owner", value: owner)]
        if let teamID { url.queryItems?.append(URLQueryItem(name: "team", value: teamID)) }
        return url.url
    }
}

enum WidgetActiveChatsSnapshotCodec {
    static func seal(_ snapshot: WidgetActiveChatsSnapshot, key: SymmetricKey) throws -> Data {
        let box = try AES.GCM.seal(JSONEncoder().encode(snapshot), using: key, authenticating: Data(snapshot.owner.utf8))
        guard let bytes = box.combined else { throw CodecError.invalid }
        return bytes
    }
    static func open(_ bytes: Data, owner: String, key: SymmetricKey) throws -> WidgetActiveChatsSnapshot {
        let data = try AES.GCM.open(AES.GCM.SealedBox(combined: bytes), using: key, authenticating: Data(owner.utf8))
        let snapshot = try JSONDecoder().decode(WidgetActiveChatsSnapshot.self, from: data)
        guard snapshot.owner == owner else { throw CodecError.invalid }
        return snapshot
    }
    private enum CodecError: Error { case invalid }
}

/// Dedicated WhenUnlocked device-only key. App Group defaults contain ciphertext
/// and an opaque owner, never account IDs, plaintext titles, session or chat keys.
@MainActor
final class WidgetActiveChatsStorage {
    static let shared = WidgetActiveChatsStorage()
    static let suiteName = "group.org.openmates.app.shared"
    static let kind = "ActiveChatsWidget"
    static let languageKey = "widget_active_chats_language"
    static let ownerKey = "widget_active_chats_owner"
    static let snapshotKey = "widget_active_chats_encrypted_snapshot_v1"
    private let defaults: UserDefaults?
    private let loadKey: @MainActor (Bool) throws -> SymmetricKey
    private let deleteKey: @MainActor () -> Void

    init(defaults: UserDefaults? = UserDefaults(suiteName: suiteName),
         loadKey: @escaping @MainActor (Bool) throws -> SymmetricKey = WidgetActiveChatsKeychain.load,
         deleteKey: @escaping @MainActor () -> Void = WidgetActiveChatsKeychain.clear) {
        self.defaults = defaults; self.loadKey = loadKey; self.deleteKey = deleteKey
    }
    func activate(owner: String?) {
        guard defaults?.string(forKey: Self.ownerKey) != owner else { return }
        clear()
        if let owner { defaults?.set(owner, forKey: Self.ownerKey) }
    }
    func save(_ snapshot: WidgetActiveChatsSnapshot) throws {
        guard defaults?.string(forKey: Self.ownerKey) == snapshot.owner else { return }
        defaults?.set(try WidgetActiveChatsSnapshotCodec.seal(snapshot, key: loadKey(true)), forKey: Self.snapshotKey)
    }
    func load() -> WidgetActiveChatsSnapshot? {
        guard let owner = defaults?.string(forKey: Self.ownerKey), let bytes = defaults?.data(forKey: Self.snapshotKey),
              let key = try? loadKey(false) else { return nil }
        return try? WidgetActiveChatsSnapshotCodec.open(bytes, owner: owner, key: key)
    }
    func setLanguage(_ language: String) { defaults?.set(language, forKey: Self.languageKey) }
    func clear() {
        defaults?.removeObject(forKey: Self.ownerKey); defaults?.removeObject(forKey: Self.snapshotKey); deleteKey()
    }
}
@MainActor
private enum WidgetActiveChatsKeychain {
    static func query() -> [CFString: Any] {
        var query: [CFString: Any] = [kSecClass: kSecClassGenericPassword,
            kSecAttrService: "org.openmates.app.active-chats-widget", kSecAttrAccount: "active-chats-snapshot-v1",
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
