// Web service: frontend/packages/ui/src/services/teamService.ts
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.lifecycle.encrypted-profiled, teams.membership.role-gated, teams.invites.fragment-key-web-flow
// Team keys stay in memory. Metadata uses the web IV+ciphertext format; the account
// master key wraps the random team key. Every operation pins account/server/scope.

// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.cold.shared-team-authorized, storage.surface.semantic-parity

import CryptoKit
import Foundation
import CoreFoundation
import ImageIO
import UniformTypeIdentifiers

struct SettingsTeamDetails: Equatable {
    let credits: Int
    let memoryCount: Int
    var balanceVersion: Int? = nil
}

enum SettingsTeamsError: Error {
    case emptyName, emptyEmail, permissionDenied, invalidMember, imageRejected, imageRejectedFinalWarning, accountDeleted
}

struct SettingsTeamMember: Identifiable, Equatable {
    let id: String
    let userID: String?
    let name: String
    let role: TeamWorkspaceRole
    let status: String
    var avatarIcon = "user"
    var avatarColor = "#4d73ff"
    var profileImageURL: String? = nil
}

struct SettingsTeamInvite: Identifiable, Equatable {
    let id: String
    let recipient: String
    let status: String
}

struct SettingsTeamSecurity: Codable, Equatable {
    var restrictEmailDomains = false
    var allowedEmailDomains: [String] = []
    var requireInviteLinkApproval = true
    var requireStrongAuth = false
}

struct SettingsTeamManagement {
    let members: [SettingsTeamMember]
    let invites: [SettingsTeamInvite]
    let security: SettingsTeamSecurity
}

struct SettingsTeamInvitation {
    let url: URL?
    let delivered: Bool
}

@MainActor
protocol SettingsTeamsServing {
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam]
    func checkCreationName(_ name: String, fence: TeamWorkspaceFence) async throws
    func createProfiledAvatar(name: String, description: String, memberName: String?, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
    func memberAvatar(team: TeamWorkspaceTeam, member: SettingsTeamMember, fence: TeamWorkspaceFence) async throws -> Data?
    func createProfiled(name: String, description: String, memberName: String?, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool
    func management(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamManagement
    func uploadAvatar(team: TeamWorkspaceTeam, jpeg: Data, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
    func avatar(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> Data?
    func saveAvatar(team: TeamWorkspaceTeam, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
    func rename(team: TeamWorkspaceTeam, name: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
    func changeRole(team: TeamWorkspaceTeam, member: SettingsTeamMember, role: TeamWorkspaceRole, fence: TeamWorkspaceFence) async throws
    func removeMember(team: TeamWorkspaceTeam, member: SettingsTeamMember, fence: TeamWorkspaceFence) async throws
    func revokeInvite(team: TeamWorkspaceTeam, inviteID: String, fence: TeamWorkspaceFence) async throws
    func saveSecurity(team: TeamWorkspaceTeam, policy: SettingsTeamSecurity, fence: TeamWorkspaceFence) async throws -> SettingsTeamSecurity
    func invitation(team: TeamWorkspaceTeam, email: String?, fence: TeamWorkspaceFence) async throws -> SettingsTeamInvitation
    func delete(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws
    func storage(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> TeamStorageOverview
    func storageNotice(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence, after: String?) async throws -> StorageNotice
}

extension SettingsTeamsServing {
    func checkCreationName(_ name: String, fence: TeamWorkspaceFence) async throws { throw TeamWorkspaceError.invalidResponse }
    func createProfiledAvatar(name: String, description: String, memberName: String?, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        let team = try await createProfiled(name: name, description: description, memberName: memberName, fence: fence)
        if icon == "team", color == "#4d73ff" { return team }
        return try await saveAvatar(team: team, icon: icon, color: color, fence: fence)
    }
    func memberAvatar(team: TeamWorkspaceTeam, member: SettingsTeamMember, fence: TeamWorkspaceFence) async throws -> Data? { nil }
    func uploadAvatar(team: TeamWorkspaceTeam, jpeg: Data, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam { throw TeamWorkspaceError.invalidResponse }
    func avatar(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> Data? { nil }
    func createProfiled(name: String, description: String, memberName: String?, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await create(name: name, description: description, fence: fence)
    }
    func saveAvatar(team: TeamWorkspaceTeam, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam { throw TeamWorkspaceError.invalidResponse }
    func management(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamManagement {
        throw TeamWorkspaceError.invalidResponse
    }
    func rename(team: TeamWorkspaceTeam, name: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam { throw TeamWorkspaceError.invalidResponse }
    func changeRole(team: TeamWorkspaceTeam, member: SettingsTeamMember, role: TeamWorkspaceRole, fence: TeamWorkspaceFence) async throws { throw TeamWorkspaceError.invalidResponse }
    func removeMember(team: TeamWorkspaceTeam, member: SettingsTeamMember, fence: TeamWorkspaceFence) async throws { throw TeamWorkspaceError.invalidResponse }
    func revokeInvite(team: TeamWorkspaceTeam, inviteID: String, fence: TeamWorkspaceFence) async throws { throw TeamWorkspaceError.invalidResponse }
    func saveSecurity(team: TeamWorkspaceTeam, policy: SettingsTeamSecurity, fence: TeamWorkspaceFence) async throws -> SettingsTeamSecurity { throw TeamWorkspaceError.invalidResponse }
    func invitation(team: TeamWorkspaceTeam, email: String?, fence: TeamWorkspaceFence) async throws -> SettingsTeamInvitation {
        guard let email else { throw TeamWorkspaceError.invalidResponse }
        return SettingsTeamInvitation(url: nil, delivered: try await invite(team: team, email: email, fence: fence))
    }
    func delete(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws { throw TeamWorkspaceError.invalidResponse }

    func storage(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> TeamStorageOverview {
        throw TeamWorkspaceError.invalidResponse
    }
    func storageNotice(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence, after: String?) async throws -> StorageNotice {
        throw TeamWorkspaceError.invalidResponse
    }
}

@MainActor
final class SettingsTeamsService: SettingsTeamsServing {
    typealias Transport = @MainActor (HTTPMethod, String, Data?, TeamWorkspaceFence) async throws -> Data
    typealias AvatarUpload = @MainActor (Data, String, String, TeamWorkspaceFence, TeamWorkspaceSnapshot) async throws -> Data
    typealias MasterKeyLoader = @MainActor (String) async throws -> SymmetricKey?
    private let reader: any TeamWorkspaceServing
    private let transport: Transport
    private let contextSnapshot: @MainActor () -> TeamWorkspaceSnapshot
    private let contextIsCurrent: @MainActor (TeamWorkspaceSnapshot) -> Bool
    private let avatarUpload: AvatarUpload
    private let masterKey: MasterKeyLoader
    private let responseCache: NativeWorkspaceOfflineCache
    private var walletScope: String?
    private var walletVersions: [String: Int] = [:]

    private func recordWalletVersion(_ version: Int?, teamID: String, fence: TeamWorkspaceFence) throws {
        let scope = "\(fence.accountID)|\(fence.scope.uuidString)|\(fence.server.apiBaseURL.absoluteString)"
        if walletScope != scope { walletScope = scope; walletVersions = [:] }
        if let previous = walletVersions[teamID], version == nil || version! < previous {
            throw StorageStatusError.staleWallet
        }
        if let version { walletVersions[teamID] = version }
    }

    init(reader: any TeamWorkspaceServing = TeamWorkspaceService(),
         transport: Transport? = nil, masterKey: MasterKeyLoader? = nil, avatarUpload: AvatarUpload? = nil,
         contextSnapshot: @escaping @MainActor () -> TeamWorkspaceSnapshot = { TeamWorkspaceContext.shared.snapshot },
         contextIsCurrent: @escaping @MainActor (TeamWorkspaceSnapshot) -> Bool = { TeamWorkspaceContext.shared.isCurrent($0) },
         responseCache: NativeWorkspaceOfflineCache? = nil) {
        self.reader = reader
        self.responseCache = responseCache ?? NativeWorkspaceOfflineCache()
        self.contextSnapshot = contextSnapshot
        self.contextIsCurrent = contextIsCurrent
        self.transport = transport ?? { method, path, data, fence in
             let body: JSONRawBody? = data.map { JSONRawBody(data: $0) }
             return try await APIClient.shared.request(method, path: path, serverProfile: fence.server,
                 body: body,
                 expectedAccountID: fence.accountID, expectedScope: fence.scope)
        }
        self.avatarUpload = avatarUpload ?? { jpeg, encrypted, teamID, fence, context in
            try await APIClient.shared.uploadTeamProfileImage(data: jpeg, encryptedMetadata: encrypted, teamID: teamID,
                serverProfile: fence.server, expectedAccountID: fence.accountID, expectedScope: fence.scope,
                expectedTeamContext: .init(epoch: context.epoch, teamID: context.teamID))
        }
        self.masterKey = masterKey ?? { try await CryptoManager.shared.loadMasterKey(for: $0) }
    }

    static func path(_ teamID: String, suffix: String) -> String {
        let escaped = teamID.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
        return "/v1/teams/\(escaped)/\(suffix)"
    }

    private func request(_ method: HTTPMethod, _ path: String, body: [String: Any]? = nil,
                         fence: TeamWorkspaceFence) async throws -> [String: Any] {
        try await fence.check()
        let bytes = try body.map { try JSONSerialization.data(withJSONObject: $0) }
        var response: Data
        if method == .get, path.hasPrefix("/v1/teams/"),
           let teamID = path.dropFirst("/v1/teams/".count).split(separator: "/").first.map(String.init)?.removingPercentEncoding,
           let key = try await masterKey(fence.accountID) {
            let scope = NativeWorkspaceOfflineScope(accountID: fence.accountID, server: fence.server.apiBaseURL.absoluteString,
                teamID: teamID, accountGeneration: fence.scope, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
            await responseCache.configure(scope: scope, masterKey: key)
            let namespace = path.hasSuffix("/billing") || path.hasSuffix("/memories") ? "team-summary" : "team-management"
            do {
                response = try await transport(method, path, bytes, fence)
                try await fence.check()
                try? await responseCache.retain(namespace: namespace, path: path, data: response, scope: scope)
            } catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(error.code) {
                try await fence.check()
                guard let cached = try await responseCache.read(namespace: namespace, path: path, scope: scope) else { throw error }
                response = cached
            }
        } else { response = try await transport(method, path, bytes, fence) }
        try await fence.check()
        guard let object = try JSONSerialization.jsonObject(with: response) as? [String: Any] else {
            throw TeamWorkspaceError.invalidResponse
        }
        return object
    }

    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        try await fence.check()
        let teams: [TeamWorkspaceTeam]
        do { teams = try await reader.listTeams(fence: fence) }
        catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(error.code) {
            teams = try await reader.cachedTeams(fence: fence)
        }
        try await fence.check()
        return teams.sorted { $0.createdAt > $1.createdAt }
    }

    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await createProfiled(name: name, description: description, memberName: nil, fence: fence)
    }
    func checkCreationName(_ name: String, fence: TeamWorkspaceFence) async throws {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw SettingsTeamsError.emptyName }
        _ = try await approveName(name, fence: fence)
    }

    func createProfiled(name: String, description: String, memberName: String?, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await createProfiledAvatar(name: name, description: description, memberName: memberName, icon: "team", color: "#4d73ff", fence: fence)
    }

    func createProfiledAvatar(name: String, description: String, memberName: String?, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw SettingsTeamsError.emptyName }
        try await fence.check()
        guard let masterKey = try await masterKey(fence.accountID) else { throw TeamWorkspaceError.missingMasterKey }
        try await fence.check()
        let approval = try await approveName(name, fence: fence)
        let teamKey = SymmetricKey(size: .bits256)
        let id = UUID().uuidString.lowercased()
        let now = Int(Date().timeIntervalSince1970)
        let profile: [String: Any] = ["version": 1, "mode": "generated", "icon_name": icon,
                                     "icon_color": "#ffffff", "background_color": color]
        let profileData = try JSONSerialization.data(withJSONObject: profile)
        guard let profileText = String(data: profileData, encoding: .utf8) else { throw TeamWorkspaceError.invalidResponse }
        let memberDisplay = memberName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let memberProfile: [String: Any] = ["display_name": memberDisplay.isEmpty ? AppStrings.teamsMemberFallback : memberDisplay,
            "avatar": ["mode": "generated", "icon_name": "user", "background_color": "#4d73ff"]]
        let memberText = String(decoding: try JSONSerialization.data(withJSONObject: memberProfile), as: UTF8.self)
        // encryptWithMasterKey produces the same unprefixed AES-GCM format as encryptWithEmbedKey.
        var payload: [String: Any] = [
            "team_id": id, "name_approval_token": approval,
            "encrypted_member_profile": try await CryptoManager.shared.encryptWithMasterKey(memberText, masterKey: teamKey),
            "encrypted_name": try await CryptoManager.shared.encryptWithMasterKey(name, masterKey: teamKey),
            "encrypted_profile_image_metadata": try await CryptoManager.shared.encryptWithMasterKey(profileText, masterKey: teamKey),
            "encrypted_team_key": try await CryptoManager.shared.wrapChatKey(teamKey, masterKey: masterKey),
            "encrypted_zero_balance": try await CryptoManager.shared.encryptWithMasterKey("0", masterKey: teamKey),
            "created_at": now, "updated_at": now,
        ]
        if !description.isEmpty {
            payload["encrypted_description"] = try await CryptoManager.shared.encryptWithMasterKey(description, masterKey: teamKey)
        }
        let response = try await request(.post, "/v1/teams", body: payload, fence: fence)
        guard let record = response["team"] as? [String: Any],
              (record["team_id"] as? String ?? id) == id else { throw TeamWorkspaceError.invalidResponse }
        try await fence.check()
        // The successful create response is authoritative. Match web's local
        // reconstruction, so a follow-up connectivity failure cannot duplicate
        // a Team whose create POST already succeeded.
        return TeamWorkspaceTeam(id: id, name: name, description: description,
            role: (record["role"] as? String).flatMap(TeamWorkspaceRole.init(rawValue:)) ?? .owner,
            status: record["status"] as? String ?? "active",
            profileImageMetadata: .init(version: 1, mode: "generated", iconName: icon, iconColor: "#ffffff", backgroundColor: color),
            zeroBalance: 0, createdAt: record["created_at"] as? Int ?? now, updatedAt: record["updated_at"] as? Int ?? now, key: teamKey)
    }

    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails {
        guard team.canRead else { throw SettingsTeamsError.permissionDenied }
        var credits = team.zeroBalance
        var balanceVersion: Int?
        // Versioned numeric wallets are authoritative, including zero. A malformed
        // modern response must never fall back to an encrypted advisory snapshot.
        if team.canViewBilling {
            let response = try await request(.get, Self.path(team.id, suffix: "billing"), fence: fence)
            guard let billing = response["billing"] as? [String: Any] else { throw TeamWorkspaceError.invalidResponse }
            let version = billing["version"] ?? billing["balance_version"]
            if version != nil {
                guard let number = version as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                      number.doubleValue >= 0, number.doubleValue == Double(number.intValue),
                      let balance = billing["balance_credits"] as? NSNumber, CFGetTypeID(balance) != CFBooleanGetTypeID(),
                      balance.doubleValue >= 0, balance.doubleValue == Double(balance.intValue) else {
                    throw TeamWorkspaceError.invalidResponse
                }
                balanceVersion = number.intValue
                credits = balance.intValue
            } else {
                let raw = billing["balance_credits"] ?? billing["credits"] ?? billing["balance"]
                var balance = (raw as? NSNumber)?.intValue ?? (raw as? String).flatMap(Int.init)
                if ((balance ?? -1) < 0), let encrypted = billing["encrypted_balance"] as? String {
                    let value = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: team.key)
                    try await fence.check()
                    balance = Int(value)
                }
                credits = (balance ?? -1) < 0 ? team.zeroBalance : (balance ?? team.zeroBalance)
            }
            try recordWalletVersion(balanceVersion, teamID: team.id, fence: fence)
        }
        let memories = try await request(.get, Self.path(team.id, suffix: "memories"), fence: fence)
        try await fence.check()
        if team.canViewBilling { try recordWalletVersion(balanceVersion, teamID: team.id, fence: fence) }
        return SettingsTeamDetails(credits: credits,
                                   memoryCount: (memories["memories"] as? [Any])?.count ?? 0,
                                   balanceVersion: balanceVersion)
    }

    // Revalidate live membership and role both before and after metadata reads.
    // A selection generation in the controller also fences the displayed Team.
    private func checkStorageTeam(_ team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws {
        guard team.canViewBilling else { throw SettingsTeamsError.permissionDenied }
        let current: TeamWorkspaceTeam
        do { current = try await reader.getTeam(team.id, fence: fence) }
        catch APIError.httpError(let status, _) where [401, 403, 404].contains(status) { throw TeamWorkspaceError.staleContext }
        try await fence.check()
        guard current.id == team.id, current.canViewBilling,
              current.role == team.role, current.updatedAt == team.updatedAt else {
            throw TeamWorkspaceError.staleContext
        }
    }

    private func storageRequest<T: Decodable>(_ path: String, team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> T {
        try await checkStorageTeam(team, fence: fence)
        let bytes: Data
        do { bytes = try await transport(.get, path, nil, fence) }
        catch APIError.httpError(let status, _) where [401, 403, 404].contains(status) { throw TeamWorkspaceError.staleContext }
        try await checkStorageTeam(team, fence: fence)
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: bytes)
    }

    func storage(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> TeamStorageOverview {
        let response: TeamStorageResponse = try await storageRequest(Self.path(team.id, suffix: "storage"), team: team, fence: fence)
        return response.storage
    }

    func storageNotice(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence, after: String? = nil) async throws -> StorageNotice {
        let path = try StorageNoticePaging.path(base: Self.path(team.id, suffix: "storage/notice"), limit: 50, after: after)
        return try await storageRequest(path, team: team, fence: fence)
    }

    private func approveName(_ name: String, fence: TeamWorkspaceFence) async throws -> String {
        let result = try await request(.post, "/v1/teams/name-approval",
            body: ["name": name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()], fence: fence)
        guard let token = result["approval_token"] as? String, !token.isEmpty else { throw TeamWorkspaceError.invalidResponse }
        return token
    }

    private func checkManager(_ team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws {
        guard team.canManage else { throw SettingsTeamsError.permissionDenied }
        let current = try await reader.getTeam(team.id, fence: fence)
        try await fence.check()
        guard current.canManage, current.id == team.id, current.role == team.role else {
            throw SettingsTeamsError.permissionDenied
        }
    }

    func uploadAvatar(team: TeamWorkspaceTeam, jpeg: Data, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await checkManager(team, fence: fence)
        let context = contextSnapshot()
        let metadata: [String: Any] = ["version": 1, "mode": "uploaded", "image_url": Self.path(team.id, suffix: "profile-image"),
            "content_safety_status": "accepted", "updated_at": Int(Date().timeIntervalSince1970), "team_id": team.id]
        let text = String(decoding: try JSONSerialization.data(withJSONObject: metadata), as: UTF8.self)
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: team.key)
        let response = try await avatarUpload(jpeg, encrypted, team.id, fence, context)
        try await fence.check()
        guard contextIsCurrent(context),
              let raw = try JSONSerialization.jsonObject(with: response) as? [String: Any] else { throw TeamWorkspaceError.staleContext }
        switch raw["status"] as? String {
        case "account_deleted": throw SettingsTeamsError.accountDeleted
        case "rejected":
            if raw["reject_count"] as? Int == 3 { throw SettingsTeamsError.imageRejectedFinalWarning }
            throw SettingsTeamsError.imageRejected
        case "ok": break
        default: throw TeamWorkspaceError.invalidResponse
        }
        try await checkManager(team, fence: fence)
        return try await reader.getTeam(team.id, fence: fence)
    }

    func avatar(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> Data? {
        guard team.canRead, team.profileImageMetadata.mode == "uploaded",
              team.profileImageMetadata.imageURL == Self.path(team.id, suffix: "profile-image") else { return nil }
        try await fence.check()
        let scope = NativeWorkspaceOfflineScope(accountID: fence.accountID, server: fence.server.apiBaseURL.absoluteString,
            teamID: team.id, accountGeneration: fence.scope, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
        guard let key = try await masterKey(fence.accountID) else { throw TeamWorkspaceError.missingMasterKey }
        await responseCache.configure(scope: scope, masterKey: key)
        let path = Self.path(team.id, suffix: "profile-image")
        do {
            let data = try await transport(.get, path, nil, fence)
            try await fence.check()
            guard data.count <= 5 * 1_024 * 1_024, NativeImageRaster.uprightImage(from: data) != nil else { throw TeamWorkspaceError.invalidResponse }
            try await responseCache.retain(namespace: "team-images", path: path, data: data, scope: scope)
            return data
        } catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(error.code) {
            try await fence.check()
            return try await responseCache.read(namespace: "team-images", path: path, scope: scope)
        }
    }

    private func readableAvatarTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        do { return try await reader.getTeam(id, fence: fence) }
        catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(error.code) {
            let cached = try await reader.cachedTeams(fence: fence)
            try await fence.check()
            guard let team = cached.first(where: { $0.id == id && $0.canRead }) else { throw SettingsTeamsError.permissionDenied }
            return team
        }
    }

    func memberAvatar(team: TeamWorkspaceTeam, member: SettingsTeamMember, fence: TeamWorkspaceFence) async throws -> Data? {
        guard team.canRead, member.status == "active", let userID = member.userID else { return nil }
        let path = Self.path(team.id, suffix: "members/" + UserTasksPaths.escaped(userID) + "/profile-image")
        // Match the server-provided relative route exactly; never follow profile URLs.
        guard member.profileImageURL == path else { return nil }
        let current = try await readableAvatarTeam(team.id, fence: fence)
        try await fence.check()
        guard current.canRead, current.role == team.role, current.updatedAt == team.updatedAt else { throw SettingsTeamsError.permissionDenied }
        let scope = NativeWorkspaceOfflineScope(accountID: fence.accountID, server: fence.server.apiBaseURL.absoluteString,
            teamID: team.id, accountGeneration: fence.scope, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
        guard let key = try await masterKey(fence.accountID) else { throw TeamWorkspaceError.missingMasterKey }
        await responseCache.configure(scope: scope, masterKey: key)
        var data: Data?
        do {
            let pixels = try await transport(.get, path, nil, fence)
            try await fence.check()
            guard pixels.count <= 5 * 1_024 * 1_024, NativeImageRaster.uprightImage(from: pixels) != nil else { throw TeamWorkspaceError.invalidResponse }
            data = pixels
        } catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(error.code) {
            data = try await responseCache.read(namespace: "team-member-images", path: path, scope: scope)
        }
        let refreshed = try await readableAvatarTeam(team.id, fence: fence)
        try await fence.check()
        guard refreshed.canRead, refreshed.role == team.role, refreshed.updatedAt == team.updatedAt else { throw SettingsTeamsError.permissionDenied }
        if let data { try await responseCache.retain(namespace: "team-member-images", path: path, data: data, scope: scope) }
        return data
    }

    nonisolated static func avatarJPEG(_ data: Data) throws -> Data {
        guard data.count <= 20 * 1_024 * 1_024,
              let image = NativeImageRaster.uprightImage(from: data) else { throw NativeImageRaster.ProcessingError.invalidImage }
        let side = min(image.width, image.height)
        guard let cropped = image.cropping(to: CGRect(x: (image.width - side) / 2, y: (image.height - side) / 2, width: side, height: side)),
              let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: 340, height: 340, bitsPerComponent: 8, bytesPerRow: 0,
                  space: colorSpace, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { throw NativeImageRaster.ProcessingError.invalidImage }
        context.interpolationQuality = .high
        context.draw(cropped, in: CGRect(x: 0, y: 0, width: 340, height: 340))
        guard let pixels = context.makeImage() else { throw NativeImageRaster.ProcessingError.encodingFailed }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, UTType.jpeg.identifier as CFString, 1, nil) else { throw NativeImageRaster.ProcessingError.encodingFailed }
        CGImageDestinationAddImage(destination, pixels, [kCGImagePropertyOrientation: 1, kCGImageDestinationLossyCompressionQuality: 0.9] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw NativeImageRaster.ProcessingError.encodingFailed }
        return try NativeImageRaster.prepareUpload(data: output as Data, filename: "team-profile.jpg", contentType: "image/jpeg").data
    }

    func saveAvatar(team: TeamWorkspaceTeam, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await checkManager(team, fence: fence)
        let metadata: [String: Any] = ["version": 1, "mode": "generated", "icon_name": icon, "icon_color": "#ffffff", "background_color": color]
        let text = String(decoding: try JSONSerialization.data(withJSONObject: metadata), as: UTF8.self)
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: team.key)
        _ = try await request(.patch, Self.path(team.id, suffix: "").dropLast().description,
            body: ["encrypted_profile_image_metadata": encrypted, "updated_at": Int(Date().timeIntervalSince1970)], fence: fence)
        return try await reader.getTeam(team.id, fence: fence)
    }

    func rename(team: TeamWorkspaceTeam, name: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw SettingsTeamsError.emptyName }
        try await checkManager(team, fence: fence)
        let token = try await approveName(name, fence: fence)
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(name, masterKey: team.key)
        _ = try await request(.patch, Self.path(team.id, suffix: "").dropLast().description,
            body: ["encrypted_name": encrypted, "name_approval_token": token, "updated_at": Int(Date().timeIntervalSince1970)], fence: fence)
        return try await reader.getTeam(team.id, fence: fence)
    }

    func management(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamManagement {
        guard team.canRead else { throw SettingsTeamsError.permissionDenied }
        let data = try await request(.get, Self.path(team.id, suffix: "members"), fence: fence)
        guard let rows = data["members"] as? [[String: Any]] else { throw TeamWorkspaceError.invalidResponse }
        var members: [SettingsTeamMember] = []
        for row in rows {
            guard let role = (row["role"] as? String).flatMap(TeamWorkspaceRole.init(rawValue:)),
                  let status = row["status"] as? String,
                  let id = row["user_id"] as? String ?? row["hashed_user_id"] as? String else { throw TeamWorkspaceError.invalidResponse }
            var name = teamsMemberFallback, icon = "user", color = "#4d73ff"
            if let encrypted = row["encrypted_member_profile"] as? String,
               let text = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: team.key),
               let profile = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] {
                if let display = profile["display_name"] as? String, !display.isEmpty { name = display }
                if let avatar = profile["avatar"] as? [String: Any] {
                    icon = avatar["icon_name"] as? String ?? icon
                    color = avatar["background_color"] as? String ?? color
                }
            }
            members.append(.init(id: id, userID: row["user_id"] as? String, name: name, role: role, status: status,
                avatarIcon: icon, avatarColor: color, profileImageURL: row["profile_image_url"] as? String))
        }
        var invites: [SettingsTeamInvite] = []
        var security = SettingsTeamSecurity()
        if team.canManage {
            let data = try await request(.get, Self.path(team.id, suffix: "invites"), fence: fence)
            guard let rows = data["invites"] as? [[String: Any]] else { throw TeamWorkspaceError.invalidResponse }
            for row in rows {
                guard let id = row["invite_id"] as? String, let status = row["status"] as? String else { throw TeamWorkspaceError.invalidResponse }
                var recipient = ""
                if let encrypted = row["encrypted_recipient_hint"] as? String,
                   let text = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: team.key),
                   let hint = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] { recipient = hint["recipient_email"] as? String ?? "" }
                invites.append(.init(id: id, recipient: recipient, status: status))
            }
            let raw = try await request(.get, Self.path(team.id, suffix: "" ).dropLast().description, fence: fence)
            if let record = raw["team"] as? [String: Any], let policy = record["security_policy"] as? [String: Any] {
                let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
                security = try decoder.decode(SettingsTeamSecurity.self, from: JSONSerialization.data(withJSONObject: policy))
            }
        }
        try await fence.check()
        return .init(members: members, invites: invites, security: security)
    }

    private var teamsMemberFallback: String {
        AppStrings.teamsMemberFallback
    }

    func changeRole(team: TeamWorkspaceTeam, member: SettingsTeamMember, role: TeamWorkspaceRole, fence: TeamWorkspaceFence) async throws {
        try await checkManager(team, fence: fence)
        guard member.role != .owner, role != .owner, member.status == "active", let userID = member.userID else { throw SettingsTeamsError.invalidMember }
        _ = try await request(.patch, Self.path(team.id, suffix: "members/" + UserTasksPaths.escaped(userID)),
            body: ["role": role.rawValue, "updated_at": Int(Date().timeIntervalSince1970)], fence: fence)
    }

    func removeMember(team: TeamWorkspaceTeam, member: SettingsTeamMember, fence: TeamWorkspaceFence) async throws {
        try await checkManager(team, fence: fence)
        guard member.role != .owner, let userID = member.userID else { throw SettingsTeamsError.invalidMember }
        _ = try await request(.post, Self.path(team.id, suffix: "members/" + UserTasksPaths.escaped(userID) + "/remove"),
            body: ["removed_at": Int(Date().timeIntervalSince1970)], fence: fence)
    }

    func revokeInvite(team: TeamWorkspaceTeam, inviteID: String, fence: TeamWorkspaceFence) async throws {
        try await checkManager(team, fence: fence)
        _ = try await request(.post, Self.path(team.id, suffix: "invites/" + UserTasksPaths.escaped(inviteID) + "/revoke"), fence: fence)
    }

    func saveSecurity(team: TeamWorkspaceTeam, policy: SettingsTeamSecurity, fence: TeamWorkspaceFence) async throws -> SettingsTeamSecurity {
        try await checkManager(team, fence: fence)
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        guard let body = try JSONSerialization.jsonObject(with: encoder.encode(policy)) as? [String: Any] else { throw TeamWorkspaceError.invalidResponse }
        let response = try await request(.patch, Self.path(team.id, suffix: "security"), body: body, fence: fence)
        guard let result = response["security_policy"] as? [String: Any] else { throw TeamWorkspaceError.invalidResponse }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SettingsTeamSecurity.self, from: JSONSerialization.data(withJSONObject: result))
    }

    func delete(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws {
        try await checkManager(team, fence: fence)
        guard team.role == .owner else { throw SettingsTeamsError.permissionDenied }
        _ = try await request(.delete, Self.path(team.id, suffix: "").dropLast().description, fence: fence)
    }

    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool {
        try await invitation(team: team, email: email, fence: fence).delivered
    }

    static func inviteKey(secret: Data, email: String, inviteID: String, teamID: String, origin: String) -> SymmetricKey {
        var info = Data()
        for value in [email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(), inviteID, teamID, origin.trimmingCharacters(in: CharacterSet(charactersIn: "/"))] {
            let bytes = Data(value.utf8)
            var length = UInt32(bytes.count).bigEndian
            withUnsafeBytes(of: &length) { info.append(contentsOf: $0) }
            info.append(bytes)
        }
        return HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: secret),
            salt: Data(SHA256.hash(data: Data("openmates:team-invite:v1".utf8))), info: info, outputByteCount: 32)
    }

    func invitation(team: TeamWorkspaceTeam, email: String?, fence: TeamWorkspaceFence) async throws -> SettingsTeamInvitation {
        guard team.canManage else { throw SettingsTeamsError.permissionDenied }
        let recipient = email?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        if email != nil, recipient.isEmpty { throw SettingsTeamsError.emptyEmail }
        try await fence.check()
        let id = UUID().uuidString.lowercased()
        let secret = SymmetricKey(size: .bits256).withUnsafeBytes { Data($0) }
        let encodedSecret = secret.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        let origin = fence.server.webBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let key = Self.inviteKey(secret: secret, email: recipient, inviteID: id, teamID: team.id, origin: origin)
        let wrapped = try AES.GCM.seal(team.key.withUnsafeBytes { Data($0) }, using: key).combined!
        let now = Int(Date().timeIntervalSince1970)
        var payload: [String: Any] = ["invite_id": id, "role": "member",
            "encrypted_invite_team_key": wrapped.base64EncodedString(),
            "invite_key_kdf_context": ["v": 1, "kdf": "HKDF-SHA256", "cipher": "AES-256-GCM", "team_id": team.id, "invite_id": id, "origin": origin],
            "created_at": now, "expires_at": now + (email == nil ? 24 * 60 * 60 : 7 * 24 * 60 * 60)]
        if email != nil {
            payload["recipient_email"] = recipient
            let hint = try JSONSerialization.data(withJSONObject: ["recipient_email": recipient, "role": "member"])
            payload["encrypted_recipient_hint"] = try await CryptoManager.shared.encryptWithMasterKey(String(decoding: hint, as: UTF8.self), masterKey: team.key)
        }
        let response = try await request(.post, Self.path(team.id, suffix: "invites"), body: payload, fence: fence)
        guard let invite = response["invite"] as? [String: Any], (invite["invite_id"] as? String ?? id) == id else { throw TeamWorkspaceError.invalidResponse }
        return .init(url: URL(string: origin + "/teams/invites/" + id + "#key=" + encodedSecret), delivered: invite["delivery_status"] as? String == "sent")
    }
}
