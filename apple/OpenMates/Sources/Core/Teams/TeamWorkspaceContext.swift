import Combine
import CryptoKit
import Foundation

enum TeamWorkspaceRole: String, Decodable {
    case owner, admin, member, viewer
}

struct TeamWorkspaceProfileImageMetadata: Decodable {
    let version: Int
    let mode: String
    let iconName: String
    let iconColor: String
    let backgroundColor: String

    static let generated = Self(version: 1, mode: "generated", iconName: "team",
                                iconColor: "#ffffff", backgroundColor: "#4d73ff")

    private enum CodingKeys: String, CodingKey {
        case version, mode
        case iconName = "icon_name"
        case iconColor = "icon_color"
        case backgroundColor = "background_color"
    }
}

struct TeamWorkspaceTeam: Identifiable {
    let id: String
    let name: String
    let description: String
    let role: TeamWorkspaceRole
    let status: String
    let profileImageMetadata: TeamWorkspaceProfileImageMetadata
    let zeroBalance: Int
    let createdAt: Int
    let updatedAt: Int
    // Never serialize a decrypted team key or place it in UserDefaults.
    let key: SymmetricKey

    var isActive: Bool { status == "active" }
    var canRead: Bool { isActive }
    var canContribute: Bool { isActive && role != .viewer }
    var canManage: Bool { isActive && (role == .owner || role == .admin) }
    var canViewBilling: Bool { canManage }
}

struct TeamWorkspaceSnapshot {
    let accountID: String?
    let server: ServerProfile?
    let scope: UUID?
    let teamID: String?
    let epoch: UInt64
}

enum TeamWorkspaceError: Error {
    case staleContext
    case missingMasterKey
    case missingTeamKey
    case invalidResponse
    case unavailableTeam
}

@MainActor
struct TeamWorkspaceEnvironment {
    var currentAccountID: () async -> String?
    var scopeGeneration: () -> UUID
    var serverProfile: () -> ServerProfile

    static let live = Self(currentAccountID: { await AuthManager.currentUserId() },
                           scopeGeneration: { OfflineStore.shared.scopeGeneration },
                           serverProfile: { ServerProfile.current() })
}

@MainActor
struct TeamWorkspaceFence {
    let accountID: String
    let scope: UUID
    let server: ServerProfile
    private let environment: TeamWorkspaceEnvironment

    init(accountID: String, environment: TeamWorkspaceEnvironment = .live) {
        self.accountID = accountID
        self.environment = environment
        scope = environment.scopeGeneration()
        server = environment.serverProfile()
    }

    func check() async throws {
        guard environment.scopeGeneration() == scope,
              environment.serverProfile() == server,
              await environment.currentAccountID() == accountID,
              environment.scopeGeneration() == scope,
              environment.serverProfile() == server else {
            throw TeamWorkspaceError.staleContext
        }
    }
}

@MainActor
protocol TeamWorkspaceServing {
    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam]
    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
}

@MainActor
final class TeamWorkspaceService: TeamWorkspaceServing {
    private struct TeamRecord: Decodable {
        let teamId: String?
        let encryptedName: String?
        let encryptedDescription: String?
        let encryptedProfileImageMetadata: String?
        let encryptedTeamKey: String?
        let encryptedZeroBalance: String?
        let role: TeamWorkspaceRole?
        let status: String?
        let createdAt: Int?
        let updatedAt: Int?
    }
    private struct ListResponse: Decodable { let teams: [TeamRecord] }
    private struct DetailResponse: Decodable { let team: TeamRecord }

    private func request<T: Decodable>(_ path: String, fence: TeamWorkspaceFence) async throws -> T {
        try await fence.check()
        let data = try await APIClient.shared.request(.get, path: path, serverProfile: fence.server)
        try await fence.check()
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    private func optionalText(_ ciphertext: String?, key: SymmetricKey) async throws -> String {
        guard let ciphertext, !ciphertext.isEmpty else { return "" }
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
    }

    private func open(_ record: TeamRecord, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam? {
        guard let id = record.teamId, !id.isEmpty,
              let wrappedKey = record.encryptedTeamKey, !wrappedKey.isEmpty else { return nil }
        try await fence.check()
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else {
            throw TeamWorkspaceError.missingMasterKey
        }
        try await fence.check()
        let rawKey = try await CryptoManager.shared.decryptBlob(base64String: wrappedKey, key: masterKey)
        guard rawKey.count == 32 else { throw TeamWorkspaceError.missingTeamKey }
        let key = SymmetricKey(data: rawKey)
        let name = try await optionalText(record.encryptedName, key: key)
        let description = try await optionalText(record.encryptedDescription, key: key)
        let profileText = try await optionalText(record.encryptedProfileImageMetadata, key: key)
        let balanceText = try await optionalText(record.encryptedZeroBalance, key: key)
        try await fence.check()
        let metadata = profileText.data(using: .utf8)
            .flatMap { try? JSONDecoder().decode(TeamWorkspaceProfileImageMetadata.self, from: $0) }
            ?? .generated
        return TeamWorkspaceTeam(id: id, name: name.isEmpty ? "Untitled team" : name,
                                 description: description, role: record.role ?? .viewer,
                                 status: record.status ?? "active", profileImageMetadata: metadata,
                                 zeroBalance: Int(balanceText) ?? 0, createdAt: record.createdAt ?? 0,
                                 updatedAt: record.updatedAt ?? 0, key: key)
    }

    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        let response: ListResponse = try await request("/v1/teams", fence: fence)
        try await fence.check()
        var teams: [TeamWorkspaceTeam] = []
        for record in response.teams {
            if let team = try await open(record, fence: fence) { teams.append(team) }
        }
        try await fence.check()
        return teams
    }

    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        guard !id.isEmpty else { throw TeamWorkspaceError.invalidResponse }
        let escaped = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/?#"))) ?? ""
        let response: DetailResponse = try await request("/v1/teams/\(escaped)", fence: fence)
        try await fence.check()
        guard let team = try await open(response.team, fence: fence), team.id == id else {
            throw TeamWorkspaceError.invalidResponse
        }
        try await fence.check()
        return team
    }
}

@MainActor
final class TeamWorkspaceContext: ObservableObject {
    static let shared = TeamWorkspaceContext()

    @Published private(set) var teams: [TeamWorkspaceTeam] = []
    @Published private(set) var selectedTeam: TeamWorkspaceTeam?
    @Published private(set) var teamID: String?
    @Published private(set) var contextEpoch: UInt64 = 0
    @Published private(set) var isLoading = false
    @Published private(set) var error: TeamWorkspaceError?

    private let service: any TeamWorkspaceServing
    private let environment: TeamWorkspaceEnvironment
    private let defaults: UserDefaults
    private var accountID: String?
    private var server: ServerProfile?
    private var scope: UUID?
    private var generation = UUID()

    init(service: any TeamWorkspaceServing = TeamWorkspaceService(),
         environment: TeamWorkspaceEnvironment = .live,
         defaults: UserDefaults = .standard) {
        self.service = service
        self.environment = environment
        self.defaults = defaults
    }

    var loadedAccountID: String? { accountID }

    var snapshot: TeamWorkspaceSnapshot {
        TeamWorkspaceSnapshot(accountID: accountID, server: server, scope: scope,
                              teamID: teamID, epoch: contextEpoch)
    }

    func isCurrent(_ snapshot: TeamWorkspaceSnapshot) -> Bool {
        snapshot.accountID == accountID && snapshot.server == server &&
        snapshot.scope == scope && snapshot.scope == environment.scopeGeneration() &&
        snapshot.teamID == teamID && snapshot.epoch == contextEpoch
    }

    private func storageKey(accountID: String, server: ServerProfile) -> String {
        let scope = Data("\(accountID)\u{0}\(server.apiBaseURL.absoluteString)".utf8)
        return "openmates:active-team-id:" + SHA256.hash(data: scope).map { String(format: "%02x", $0) }.joined()
    }

    private func setContext(_ team: TeamWorkspaceTeam?) {
        let nextID = team?.id
        if nextID != teamID { contextEpoch &+= 1 }
        selectedTeam = team
        teamID = nextID
        if let accountID, let server {
            let key = storageKey(accountID: accountID, server: server)
            if let nextID { defaults.set(nextID, forKey: key) }
            else { defaults.removeObject(forKey: key) }
        }
    }

    private func isCurrent(_ operation: UUID, fence: TeamWorkspaceFence) async -> Bool {
        guard generation == operation, accountID == fence.accountID,
              server == fence.server, scope == fence.scope else { return false }
        guard (try? await fence.check()) != nil else { return false }
        return generation == operation && accountID == fence.accountID &&
            server == fence.server && scope == fence.scope
    }

    func reset(accountID: String?) {
        generation = UUID()
        let nextServer = accountID == nil ? nil : environment.serverProfile()
        let nextScope = accountID == nil ? nil : environment.scopeGeneration()
        if teamID != nil || self.accountID != accountID || server != nextServer || scope != nextScope {
            contextEpoch &+= 1
        }
        teams = []
        selectedTeam = nil
        teamID = nil
        isLoading = false
        error = nil
        self.accountID = accountID
        server = nextServer
        scope = nextScope
        // A reset clears decrypted keys, but retains this account's selected ID for reload.
    }

    func load(accountID: String) async {
        let currentServer = environment.serverProfile()
        if self.accountID != accountID || server != currentServer || scope != environment.scopeGeneration() {
            reset(accountID: accountID)
        }
        generation = UUID()
        let operation = generation
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        isLoading = true
        error = nil
        do {
            try await fence.check()
            guard await isCurrent(operation, fence: fence) else { return }
            let values = try await service.listTeams(fence: fence)
            guard await isCurrent(operation, fence: fence) else { return }
            teams = values.filter(\.canRead)
            let retainedID = teamID ?? defaults.string(forKey: storageKey(accountID: accountID, server: currentServer))
            if let retainedID, let team = teams.first(where: { $0.id == retainedID }) {
                setContext(team)
            } else {
                setContext(nil)
            }
        } catch {
            guard await isCurrent(operation, fence: fence) else { return }
            self.error = error as? TeamWorkspaceError ?? .invalidResponse
        }
        if await isCurrent(operation, fence: fence) { isLoading = false }
    }

    func selectTeam(_ id: String?) async {
        generation = UUID()
        let operation = generation
        guard let accountID, let server else { return }
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        guard fence.server == server, await isCurrent(operation, fence: fence) else { return }
        error = nil
        guard let id else { setContext(nil); return }
        guard let listedTeam = teams.first(where: { $0.id == id && $0.canRead }) else {
            error = .unavailableTeam
            return
        }
        // Switch routing immediately; the detail request may be slow. Its result only
        // refreshes this same selection after all account, server, and operation checks.
        setContext(listedTeam)
        isLoading = true
        do {
            let team = try await service.getTeam(id, fence: fence)
            guard await isCurrent(operation, fence: fence) else { return }
            guard team.canRead else {
                setContext(nil)
                throw TeamWorkspaceError.unavailableTeam
            }
            if let index = teams.firstIndex(where: { $0.id == team.id }) { teams[index] = team }
            setContext(team)
        } catch {
            guard await isCurrent(operation, fence: fence) else { return }
            self.error = error as? TeamWorkspaceError ?? .invalidResponse
        }
        if await isCurrent(operation, fence: fence) { isLoading = false }
    }
}
