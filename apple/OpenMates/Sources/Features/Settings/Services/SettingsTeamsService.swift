// Web service: frontend/packages/ui/src/services/teamService.ts
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.lifecycle.encrypted-profiled, teams.membership.role-gated, teams.invites.fragment-key-web-flow
// Team keys stay in memory. Metadata uses the web IV+ciphertext format; the account
// master key wraps the random team key. Every operation pins account/server/scope.

import CryptoKit
import Foundation

struct SettingsTeamDetails: Equatable {
    let credits: Int
    let memoryCount: Int
}

enum SettingsTeamsError: Error {
    case emptyName, emptyEmail, permissionDenied
}

@MainActor
protocol SettingsTeamsServing {
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam]
    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam
    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool
}

@MainActor
final class SettingsTeamsService: SettingsTeamsServing {
    typealias Transport = @MainActor (HTTPMethod, String, Data?, TeamWorkspaceFence) async throws -> Data
    typealias MasterKeyLoader = @MainActor (String) async throws -> SymmetricKey?
    private let reader: any TeamWorkspaceServing
    private let transport: Transport
    private let masterKey: MasterKeyLoader

    init(reader: any TeamWorkspaceServing = TeamWorkspaceService(),
         transport: Transport? = nil, masterKey: MasterKeyLoader? = nil) {
        self.reader = reader
        self.transport = transport ?? { method, path, data, fence in
             let body: JSONRawBody? = data.map { JSONRawBody(data: $0) }
             return try await APIClient.shared.request(method, path: path, serverProfile: fence.server,
                 body: body,
                 expectedAccountID: fence.accountID, expectedScope: fence.scope)
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
        let response = try await transport(method, path, bytes, fence)
        try await fence.check()
        guard let object = try JSONSerialization.jsonObject(with: response) as? [String: Any] else {
            throw TeamWorkspaceError.invalidResponse
        }
        return object
    }

    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        try await fence.check()
        let teams = try await reader.listTeams(fence: fence)
        try await fence.check()
        return teams.sorted { $0.createdAt > $1.createdAt }
    }

    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw SettingsTeamsError.emptyName }
        try await fence.check()
        guard let masterKey = try await masterKey(fence.accountID) else { throw TeamWorkspaceError.missingMasterKey }
        try await fence.check()
        let teamKey = SymmetricKey(size: .bits256)
        let id = UUID().uuidString.lowercased()
        let now = Int(Date().timeIntervalSince1970)
        let profile: [String: Any] = ["version": 1, "mode": "generated", "icon_name": "team",
                                     "icon_color": "#ffffff", "background_color": "#4d73ff"]
        let profileData = try JSONSerialization.data(withJSONObject: profile)
        guard let profileText = String(data: profileData, encoding: .utf8) else { throw TeamWorkspaceError.invalidResponse }
        // encryptWithMasterKey produces the same unprefixed AES-GCM format as encryptWithEmbedKey.
        var payload: [String: Any] = [
            "team_id": id,
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
        let created = try await reader.getTeam(id, fence: fence)
        try await fence.check()
        return created
    }

    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails {
        guard team.canRead else { throw SettingsTeamsError.permissionDenied }
        var credits = team.zeroBalance
        // Backend TEAM_BILLING_ROLES permits owner/admin; members/viewers keep the
        // decrypted zero-balance fallback and must not issue a forbidden billing read.
        if team.canViewBilling {
            let response = try await request(.get, Self.path(team.id, suffix: "billing"), fence: fence)
            guard let billing = response["billing"] as? [String: Any] else { throw TeamWorkspaceError.invalidResponse }
            let raw = billing["balance_credits"] ?? billing["credits"] ?? billing["balance"]
            var balance = (raw as? NSNumber)?.intValue ?? (raw as? String).flatMap(Int.init)
            if ((balance ?? -1) < 0), let encrypted = billing["encrypted_balance"] as? String {
                let value = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: team.key)
                balance = Int(value)
            }
            credits = (balance ?? -1) < 0 ? team.zeroBalance : (balance ?? team.zeroBalance)
        }
        let memories = try await request(.get, Self.path(team.id, suffix: "memories"), fence: fence)
        try await fence.check()
        return SettingsTeamDetails(credits: credits,
                                   memoryCount: (memories["memories"] as? [Any])?.count ?? 0)
    }

    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool {
        guard team.canManage else { throw SettingsTeamsError.permissionDenied }
        let email = email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !email.isEmpty else { throw SettingsTeamsError.emptyEmail }
        try await fence.check()
        let hint = try JSONSerialization.data(withJSONObject: ["recipient_email": email, "role": "member"])
        guard let hintText = String(data: hint, encoding: .utf8) else { throw TeamWorkspaceError.invalidResponse }
        let now = Int(Date().timeIntervalSince1970)
        let payload: [String: Any] = ["invite_id": UUID().uuidString.lowercased(), "role": "member",
            "recipient_email": email,
            "encrypted_recipient_hint": try await CryptoManager.shared.encryptWithMasterKey(hintText, masterKey: team.key),
            "created_at": now, "expires_at": now + 7 * 24 * 60 * 60]
        let response = try await request(.post, Self.path(team.id, suffix: "invites"), body: payload, fence: fence)
        guard let invite = response["invite"] as? [String: Any] else { throw TeamWorkspaceError.invalidResponse }
        return invite["delivery_status"] as? String == "sent"
    }
}
