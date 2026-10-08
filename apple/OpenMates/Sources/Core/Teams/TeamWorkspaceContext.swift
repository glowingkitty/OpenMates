// Web sources: services/teamService.ts, stores/teamContextStore.ts
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.context.full-switch-local, teams.membership.role-gated
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.isolation, apple-workspaces.local-first
import Combine
import CryptoKit
import Foundation

enum TeamWorkspaceRole: String, Codable {
    case owner, admin, member, viewer
}

struct TeamWorkspaceProfileImageMetadata: Decodable {
    let version: Int
    let mode: String
    let iconName: String
    let iconColor: String
    let backgroundColor: String
    let imageURL: String?

    static let generated = Self(version: 1, mode: "generated", iconName: "team",
                                iconColor: "#ffffff", backgroundColor: "#4d73ff")

    init(version: Int, mode: String, iconName: String, iconColor: String, backgroundColor: String, imageURL: String? = nil) {
        self.version = version; self.mode = mode; self.iconName = iconName
        self.iconColor = iconColor; self.backgroundColor = backgroundColor; self.imageURL = imageURL
    }
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        version = try values.decodeIfPresent(Int.self, forKey: .version) ?? 1
        mode = try values.decodeIfPresent(String.self, forKey: .mode) ?? "generated"
        imageURL = try values.decodeIfPresent(String.self, forKey: .imageURL)
        iconName = try values.decodeIfPresent(String.self, forKey: .iconName) ?? "team"
        iconColor = try values.decodeIfPresent(String.self, forKey: .iconColor) ?? "#ffffff"
        backgroundColor = try values.decodeIfPresent(String.self, forKey: .backgroundColor) ?? "#4d73ff"
    }
    private enum CodingKeys: String, CodingKey {
        case version, mode
        case iconName = "icon_name"
        case iconColor = "icon_color"
        case backgroundColor = "background_color"
        case imageURL = "image_url"
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
    func cachedTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam]
    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam]
    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
}

extension TeamWorkspaceServing {
    func cachedTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { [] }
}

/// Only encrypted server records and wrapped keys persist; neither a raw Team key
/// nor names/roles are visible in preferences. Account/server identity is AAD.
@MainActor
final class TeamWorkspaceRosterCache {
    private let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    private func identity(_ fence: TeamWorkspaceFence) -> Data {
        Data((fence.accountID + "\u{0}" + fence.server.apiBaseURL.absoluteString).utf8)
    }
    private func key(_ fence: TeamWorkspaceFence) -> String {
        "openmates:encrypted-team-roster:" + SHA256.hash(data: identity(fence)).map { String(format: "%02x", $0) }.joined()
    }
    func read(fence: TeamWorkspaceFence, masterKey: SymmetricKey) throws -> Data? {
        guard let data = defaults.data(forKey: key(fence)) else { return nil }
        return try AES.GCM.open(AES.GCM.SealedBox(combined: data), using: masterKey, authenticating: identity(fence))
    }
    func write(_ data: Data, fence: TeamWorkspaceFence, masterKey: SymmetricKey) throws {
        defaults.set(try AES.GCM.seal(data, using: masterKey, authenticating: identity(fence)).combined!, forKey: key(fence))
    }
    func remove(fence: TeamWorkspaceFence) { defaults.removeObject(forKey: key(fence)) }
    func removeTeam(_ id: String, fence: TeamWorkspaceFence, masterKey: SymmetricKey) throws {
        guard let data = try read(fence: fence, masterKey: masterKey),
              var raw = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let teams = raw["teams"] as? [[String: Any]] else { return }
        raw["teams"] = teams.filter { ($0["team_id"] as? String) != id }
        try write(JSONSerialization.data(withJSONObject: raw), fence: fence, masterKey: masterKey)
    }
}

@MainActor
final class TeamWorkspaceService: TeamWorkspaceServing {
    typealias Transport = @MainActor (String, TeamWorkspaceFence) async throws -> Data
    private let transport: Transport
    private let roster: TeamWorkspaceRosterCache
    init(transport: Transport? = nil, roster: TeamWorkspaceRosterCache = TeamWorkspaceRosterCache()) {
        self.roster = roster
        self.transport = transport ?? { path, fence in
            try await APIClient.shared.request(.get, path: path, serverProfile: fence.server,
                expectedAccountID: fence.accountID, expectedScope: fence.scope)
        }
    }

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
        let data = try await transport(path, fence)
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

    func cachedTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        try await fence.check()
        guard let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else { throw TeamWorkspaceError.missingMasterKey }
        try await fence.check()
        guard let data = try roster.read(fence: fence, masterKey: key) else { return [] }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(ListResponse.self, from: data)
        var teams: [TeamWorkspaceTeam] = []
        for record in response.teams { if let team = try await open(record, fence: fence) { teams.append(team) } }
        try await fence.check()
        return teams
    }

    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        try await fence.check()
        let data: Data
        do { data = try await transport("/v1/teams", fence) }
        catch APIError.httpError(let status, _) where [401, 403].contains(status) {
            try await fence.check(); roster.remove(fence: fence); throw TeamWorkspaceError.unavailableTeam
        }
        try await fence.check()
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(ListResponse.self, from: data)
        try await fence.check()
        var teams: [TeamWorkspaceTeam] = []
        for record in response.teams {
            if let team = try await open(record, fence: fence) { teams.append(team) }
        }
        try await fence.check()
        guard let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else { throw TeamWorkspaceError.missingMasterKey }
        try await fence.check()
        try roster.write(data, fence: fence, masterKey: key)
        return teams
    }

    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        guard !id.isEmpty else { throw TeamWorkspaceError.invalidResponse }
        let escaped = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/?#"))) ?? ""
        let response: DetailResponse
        do { response = try await request("/v1/teams/\(escaped)", fence: fence) }
        catch APIError.httpError(let status, _) where [401, 403, 404].contains(status) {
            try await fence.check()
            if status == 401 { roster.remove(fence: fence) }
            else if let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) {
                try await fence.check(); try roster.removeTeam(id, fence: fence, masterKey: key)
            }
            throw APIError.httpError(status: status, message: "Team unavailable")
        }
        try await fence.check()
        guard let team = try await open(response.team, fence: fence), team.id == id else {
            throw TeamWorkspaceError.invalidResponse
        }
        try await fence.check()
        if !team.canRead, let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) {
            try await fence.check(); try roster.removeTeam(id, fence: fence, masterKey: key)
        }
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
    @Published private(set) var rosterEpoch: UInt64 = 0
    @Published private(set) var isLoading = false
    @Published private(set) var error: TeamWorkspaceError?
    @Published private(set) var usingCachedRoster = false

    private let service: any TeamWorkspaceServing
    private let environment: TeamWorkspaceEnvironment
    private let defaults: UserDefaults
    private var accountID: String?
    private var server: ServerProfile?
    private var scope: UUID?
    typealias RevocationCleanup = @MainActor (String, TeamWorkspaceFence, UInt64) async -> Void
    private let revocationCleanup: RevocationCleanup
    private var rosterGeneration = UUID()
    private var selectionGeneration = UUID()
    private var rosterIsLoading = false
    private var selectionIsLoading = false

    init(service: any TeamWorkspaceServing = TeamWorkspaceService(),
         environment: TeamWorkspaceEnvironment = .live,
         defaults: UserDefaults = .standard, revocationCleanup: RevocationCleanup? = nil) {
        self.service = service
        self.environment = environment
        self.defaults = defaults
        self.revocationCleanup = revocationCleanup ?? { id, fence, epoch in
            try? await NativeWorkspaceOfflineCache().purge(scope: .init(accountID: fence.accountID,
                server: fence.server.apiBaseURL.absoluteString, teamID: id, accountGeneration: fence.scope, teamEpoch: epoch))
        }
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

    private func isCurrent(_ operation: UUID, fence: TeamWorkspaceFence, selection: Bool = false) async -> Bool {
        func matches() -> Bool {
            (selection ? selectionGeneration : rosterGeneration) == operation &&
                accountID == fence.accountID && server == fence.server && scope == fence.scope
        }
        guard matches(), (try? await fence.check()) != nil else { return false }
        return matches()
    }

    private func setRosterLoading(_ value: Bool) {
        rosterIsLoading = value; isLoading = rosterIsLoading || selectionIsLoading
    }
    private func setSelectionLoading(_ value: Bool) {
        selectionIsLoading = value; isLoading = rosterIsLoading || selectionIsLoading
    }

    func reset(accountID: String?) {
        rosterGeneration = UUID(); selectionGeneration = UUID()
        rosterIsLoading = false; selectionIsLoading = false
        let nextServer = accountID == nil ? nil : environment.serverProfile()
        let nextScope = accountID == nil ? nil : environment.scopeGeneration()
        if teamID != nil || self.accountID != accountID || server != nextServer || scope != nextScope {
            contextEpoch &+= 1
        }
        rosterEpoch &+= 1
        teams = []
        selectedTeam = nil
        teamID = nil
        isLoading = false
        error = nil
        usingCachedRoster = false
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
        rosterGeneration = UUID()
        let operation = rosterGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        setRosterLoading(true)
        error = nil
        do {
            try await fence.check()
            guard await isCurrent(operation, fence: fence) else { return }
            // Restore every joined context before waiting for network repair.
            if teams.isEmpty {
                let cached = (try? await service.cachedTeams(fence: fence)) ?? []
                guard await isCurrent(operation, fence: fence) else { return }
                if !cached.isEmpty {
                    teams = cached.filter(\.canRead); rosterEpoch &+= 1
                    usingCachedRoster = true
                    if let retainedID = defaults.string(forKey: storageKey(accountID: accountID, server: currentServer)),
                       let team = teams.first(where: { $0.id == retainedID }) { setContext(team) }
                }
            }
            let values = try await service.listTeams(fence: fence)
            guard await isCurrent(operation, fence: fence) else { return }
            let previous = Set(teams.map { "\($0.id)|\($0.role.rawValue)|\($0.updatedAt)" })
            let next = values.filter(\.canRead)
            if previous != Set(next.map { "\($0.id)|\($0.role.rawValue)|\($0.updatedAt)" }) {
                rosterEpoch &+= 1
                if let selectedTeam, let updated = next.first(where: { $0.id == selectedTeam.id }),
                   updated.role != selectedTeam.role || updated.updatedAt != selectedTeam.updatedAt { contextEpoch &+= 1 }
            }
            let removedIDs = Set(teams.map(\.id)).subtracting(next.map(\.id))
            for id in removedIDs {
                await revokeCachedTeam(id, fence: fence)
                guard await isCurrent(operation, fence: fence) else { return }
            }
            guard await isCurrent(operation, fence: fence) else { return }
            // A response from the authoritative roster supersedes an older detail
            // read, while preserving whichever readable context the user chose.
            selectionGeneration = UUID(); setSelectionLoading(false)
            teams = next
            usingCachedRoster = false
            TeamWorkspaceOfflineRetention.refresh(fence: fence, teams: next, removedIDs: removedIDs)
            let retainedID = teamID ?? defaults.string(forKey: storageKey(accountID: accountID, server: currentServer))
            if let retainedID, let team = teams.first(where: { $0.id == retainedID }) {
                setContext(team)
            } else {
                setContext(nil)
            }
        } catch {
            guard await isCurrent(operation, fence: fence) else { return }
            let denied: Bool
            if case TeamWorkspaceError.unavailableTeam = error { denied = true }
            else if case APIError.httpError(let status, _) = error { denied = [401, 403].contains(status) }
            else { denied = false }
            if denied {
                for id in teams.map(\.id) {
                    await revokeCachedTeam(id, fence: fence)
                    guard await isCurrent(operation, fence: fence) else { return }
                }
                guard await isCurrent(operation, fence: fence) else { return }
                selectionGeneration = UUID(); setSelectionLoading(false)
                teams = []; usingCachedRoster = false; setContext(nil)
            } else if let connectivity = error as? URLError,
                      [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(connectivity.code) {
                usingCachedRoster = !teams.isEmpty
            }
            guard await isCurrent(operation, fence: fence) else { return }
            self.error = error as? TeamWorkspaceError ?? .invalidResponse
        }
        if await isCurrent(operation, fence: fence) { setRosterLoading(false) }
    }

    func revokeCachedTeam(_ id: String, fence: TeamWorkspaceFence) async {
        let operation = rosterGeneration
        guard await isCurrent(operation, fence: fence) else { return }
        teams.removeAll { $0.id == id }; rosterEpoch &+= 1
        // Revoke selection and usable keys synchronously. Cleanup of the old
        // account/server directory may suspend but cannot publish state afterward.
        if teamID == id {
            selectionGeneration = UUID(); setSelectionLoading(false); setContext(nil)
        }
        let cleanupEpoch = contextEpoch
        for chat in OfflineStore.shared.loadChats().filter({ $0.teamId == id }) {
            ChatKeyManager.shared.removeKey(for: chat.id)
            EmbedKeyManager.shared.removeKeys(for: chat.id)
            OwnerEmbedPIIStore.shared.remove(chatId: chat.id)
            SpotlightIndexer.shared.removeChat(chat.id)
        }
        await revocationCleanup(id, fence, cleanupEpoch)
        // Callers must independently recheck their own operation after this await.
    }

    func selectTeam(_ id: String?) async {
        selectionGeneration = UUID()
        let operation = selectionGeneration
        // Cancelling an in-flight detail operation also clears its loading state.
        setSelectionLoading(false)
        guard let accountID, let server else { return }
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        guard fence.server == server, await isCurrent(operation, fence: fence, selection: true) else { return }
        error = nil
        guard let id else { setContext(nil); return }
        guard let listedTeam = teams.first(where: { $0.id == id && $0.canRead }) else {
            error = .unavailableTeam
            return
        }
        // Cached context switching is available while disconnected. Mutations still
        // require live server authorization; this only restores read scope.
        if usingCachedRoster { setContext(listedTeam); return }
        // Switch routing immediately; the detail request may be slow. Its result only
        // refreshes this same selection after all account, server, and operation checks.
        setContext(listedTeam)
        setSelectionLoading(true)
        do {
            let team = try await service.getTeam(id, fence: fence)
            guard await isCurrent(operation, fence: fence, selection: true) else { return }
            guard team.canRead else {
                await revokeCachedTeam(id, fence: fence)
                // revokeCachedTeam already invalidated this selection before purge.
                return
            }
            if let index = teams.firstIndex(where: { $0.id == team.id }) {
                if teams[index].role != team.role || teams[index].updatedAt != team.updatedAt { rosterEpoch &+= 1; contextEpoch &+= 1 }
                teams[index] = team
            }
            setContext(team)
        } catch {
            guard await isCurrent(operation, fence: fence, selection: true) else { return }
            if case APIError.httpError(let status, _) = error, [401, 403, 404].contains(status) {
                await revokeCachedTeam(id, fence: fence)
                return
            } else if let connectivity = error as? URLError,
                      [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(connectivity.code),
                      teams.contains(where: { $0.id == id && $0.canRead }) {
                usingCachedRoster = true; setContext(listedTeam)
            }
            self.error = error as? TeamWorkspaceError ?? .invalidResponse
        }
        if await isCurrent(operation, fence: fence, selection: true) { setSelectionLoading(false) }
    }
}
