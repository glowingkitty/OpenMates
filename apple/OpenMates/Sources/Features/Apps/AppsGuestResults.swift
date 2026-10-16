// Web sources: services/appsWorkspaceResultsService.ts, services/anonymousChatKeyWrapping.ts
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.anonymous.cli-equivalent-gate, apps.anonymous.local-results-and-promotion
import Foundation

struct AppsGuestReceipt: Codable {
    let graph: AppsSavedGraph
    let createdAt: Int
    let server: String
    let anonymousID: String
    func matches(server: String, anonymousID: String) -> Bool {
        self.server == server && self.anonymousID == anonymousID
    }
}

struct AppsGuestScope {
    let anonymousID: String
    let profile: ServerProfile
    let generation: UUID
    @MainActor static func capture() -> Self {
        Self(anonymousID: AnonymousFreeUsageService.shared.anonymousId,
             profile: ServerProfile.current(), generation: OfflineStore.shared.scopeGeneration)
    }
    @MainActor func check() async throws {
        guard await AuthManager.currentUserId() == nil, profile == ServerProfile.current(),
              generation == OfflineStore.shared.scopeGeneration,
              anonymousID == AnonymousFreeUsageService.shared.anonymousId else { throw CancellationError() }
    }
}

/// Only encrypted receipts reach disk; no requests, responses or unwrapped keys.
actor AppsGuestResults {
    static let shared = AppsGuestResults()
    private let directory: URL
    init(directory: URL? = nil) {
        self.directory = directory ?? FileManager.default.urls(for: .applicationSupportDirectory,
            in: .userDomainMask)[0].appendingPathComponent("OpenMates/apps-guest-ciphertext", isDirectory: true)
    }
    func save(id: String, ciphertext: Data) throws {
        guard UUID(uuidString: id) != nil else { throw AppsWorkspaceError.invalidResponse }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent(id + ".aesgcm")
        try ciphertext.write(to: url, options: .atomic)
        var excluded = url, values = URLResourceValues(); values.isExcludedFromBackup = true
        try? excluded.setResourceValues(values)
    }
    func receipt(id: String) throws -> Data? {
        guard UUID(uuidString: id) != nil else { throw AppsWorkspaceError.invalidResponse }
        let url = directory.appendingPathComponent(id + ".aesgcm")
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try Data(contentsOf: url)
    }
    func receipts() throws -> [(String, Data)] {
        guard FileManager.default.fileExists(atPath: directory.path) else { return [] }
        return try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "aesgcm" && UUID(uuidString: $0.deletingPathExtension().lastPathComponent) != nil }
            .map { ($0.deletingPathExtension().lastPathComponent, try Data(contentsOf: $0)) }
    }
    func remove(id: String) throws {
        guard UUID(uuidString: id) != nil else { throw AppsWorkspaceError.invalidResponse }
        let url = directory.appendingPathComponent(id + ".aesgcm")
        if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
    }
}
