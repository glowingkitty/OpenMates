// Account/profile-scoped ciphertext retention for the standalone Watch call owner.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy, video-call.chat.transcripts
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
import Foundation
import CryptoKit

/// The disk actor checks this lease synchronously immediately before every file
/// operation. Revocation cannot interleave a check and atomic file write.
final class WatchVoiceCallStorageLease: @unchecked Sendable {
    let accountID: String
    let profileID: String
    private let lock = NSLock()
    private var valid = true
    init(accountID: String, profileID: String) { self.accountID = accountID; self.profileID = profileID }
    func revoke() { lock.lock(); valid = false; lock.unlock() }
    func access<T>(scope: NativeVoiceCallScope, _ body: () throws -> T) throws -> T {
        lock.lock(); defer { lock.unlock() }
        guard valid, scope.accountID == accountID, scope.profileID == profileID else {
            throw NativeVoiceCallError.scopeChanged
        }
        return try body()
    }
}

actor WatchVoiceCallScopedDisk {
    static let shared = WatchVoiceCallScopedDisk()
    private let directory: URL
    init(directory: URL? = nil) {
        self.directory = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenMatesWatch/voice-call-v2", isDirectory: true)
    }
    private func digest(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    private func path(_ scope: NativeVoiceCallScope, auxiliary: Bool) -> URL {
        directory.appendingPathComponent(digest(scope.accountID), isDirectory: true)
            .appendingPathComponent(digest(scope.profileID), isDirectory: true)
            .appendingPathComponent(digest(scope.chatID) + (auxiliary ? ".aux.json" : ".json"))
    }
    func load<T: Decodable & Sendable>(_ type: T.Type, scope: NativeVoiceCallScope,
                                      lease: WatchVoiceCallStorageLease, auxiliary: Bool) throws -> T? {
        try lease.access(scope: scope) {
            let file = path(scope, auxiliary: auxiliary)
            guard FileManager.default.fileExists(atPath: file.path) else { return nil }
            let data = try Data(contentsOf: file)
            guard data.count <= 16 * 1_024 * 1_024 else { throw NativeVoiceCallError.persistenceFailed }
            return try JSONDecoder().decode(T.self, from: data)
        }
    }
    func save<T: Encodable & Sendable>(_ value: T, scope: NativeVoiceCallScope,
                                      lease: WatchVoiceCallStorageLease, auxiliary: Bool) throws {
        try lease.access(scope: scope) {
            let data = try JSONEncoder().encode(value)
            guard data.count <= 16 * 1_024 * 1_024 else { throw NativeVoiceCallError.persistenceFailed }
            let file = path(scope, auxiliary: auxiliary)
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            try data.write(to: file, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        }
    }
    func erase(accountID: String) throws {
        let account = directory.appendingPathComponent(digest(accountID), isDirectory: true)
        if FileManager.default.fileExists(atPath: account.path) { try FileManager.default.removeItem(at: account) }
    }
}

@MainActor
enum WatchVoiceCallStorageOwners {
    private final class WeakLease {
        weak var value: WatchVoiceCallStorageLease?
        init(_ value: WatchVoiceCallStorageLease) { self.value = value }
    }
    private static var owners: [WeakLease] = []
    private static var erasingAccounts: [String: Int] = [:]
    static func lease(accountID: String, profileID: String) -> WatchVoiceCallStorageLease {
        owners.removeAll { $0.value == nil }
        let lease = WatchVoiceCallStorageLease(accountID: accountID, profileID: profileID)
        if erasingAccounts[accountID, default: 0] > 0 { lease.revoke() }
        owners.append(WeakLease(lease)); return lease
    }
    /// Call after account generation invalidation and before deleting its keys.
    /// Existing saves drain under their lease lock; later queued saves fail.
    static func erase(accountID: String) async throws {
        erasingAccounts[accountID, default: 0] += 1
        defer {
            let remaining = erasingAccounts[accountID, default: 1] - 1
            erasingAccounts[accountID] = remaining > 0 ? remaining : nil
        }
        for owner in owners where owner.value?.accountID == accountID { owner.value?.revoke() }
        try await WatchVoiceCallScopedDisk.shared.erase(accountID: accountID)
        owners.removeAll { $0.value == nil || $0.value?.accountID == accountID }
    }
}
struct WatchVoiceCallOutboxStorage: NativeVoiceCallOutboxStorage {
    let disk: WatchVoiceCallScopedDisk
    let lease: WatchVoiceCallStorageLease
    func load(scope: NativeVoiceCallScope) async throws -> [NativeVoiceCallStoredRow] {
        try await disk.load([NativeVoiceCallStoredRow].self, scope: scope, lease: lease, auxiliary: false) ?? []
    }
    func save(_ rows: [NativeVoiceCallStoredRow], scope: NativeVoiceCallScope) async throws {
        try await disk.save(rows, scope: scope, lease: lease, auxiliary: false)
    }
}
struct WatchVoiceCallAuxiliaryStorage: NativeVoiceCallAuxiliaryStorage {
    let disk: WatchVoiceCallScopedDisk
    let lease: WatchVoiceCallStorageLease
    func load(scope: NativeVoiceCallScope) async throws -> [String: NativeVoiceCallAuxiliaryRecord] {
        try await disk.load([String: NativeVoiceCallAuxiliaryRecord].self, scope: scope, lease: lease, auxiliary: true) ?? [:]
    }
    func save(_ rows: [String: NativeVoiceCallAuxiliaryRecord], scope: NativeVoiceCallScope) async throws {
        try await disk.save(rows, scope: scope, lease: lease, auxiliary: true)
    }
}
