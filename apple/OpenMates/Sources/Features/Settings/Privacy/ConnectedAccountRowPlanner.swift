// Runs the shared Rust core's connected-account row plan for Apple Settings.
// Web source: frontend/packages/ui/src/services/rustCore/connectedAccounts/rustConnectedAccountWrites.ts
// (`rustBuildEncryptedConnectedAccountRow`). The core (`connectedAccountOauthRowPlan`) decides every
// field, plaintext and failure; Swift only runs the master-key encryption and SHA-256 primitives,
// adds the user hash the web adds on create, and lets the core storage guard check the row.
// Specification: specifications/features/teams/specification.yml

import CryptoKit
import Foundation

enum ConnectedAccountRowPlanError: Error, Equatable {
    case invalidHandoff
    case plan(String)
    case encryptionFailed(String)
}

struct ConnectedAccountRowPlanner: ConnectedAccountRowPlanning {
    typealias Encrypt = @Sendable (String) async throws -> String
    typealias UserId = @Sendable () async -> String?

    let encrypt: Encrypt
    let userId: UserId

    static func live() -> ConnectedAccountRowPlanner {
        ConnectedAccountRowPlanner(
            encrypt: { plaintext in
                guard let userId = await AuthManager.currentUserId(),
                      let key = try await CryptoManager.shared.loadMasterKey(for: userId) else {
                    throw PrivacySettingsError.masterKeyUnavailable
                }
                return try await CryptoManager.shared.encryptWithMasterKey(plaintext, masterKey: key)
            },
            userId: { await AuthManager.currentUserId() }
        )
    }

    static func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func buildRow(accountId: String, handoff: ConnectedAccountHandoff, capabilities: [String]) async throws -> [String: String] {
        let hint = try JSONSerialization.jsonObject(with: Data(handoff.accountHintJSON.utf8), options: [.fragmentsAllowed])
        let bundle = try JSONSerialization.jsonObject(with: Data(handoff.refreshTokenBundleJSON.utf8), options: [.fragmentsAllowed])
        func scopesText(_ owner: Any) throws -> String? {
            guard let scopes = (owner as? [String: Any])?["scopes"] else { return nil }
            return String(decoding: try JSONSerialization.data(withJSONObject: scopes, options: [.fragmentsAllowed]), as: UTF8.self)
        }
        var input: [String: Any] = [
            "connectedAccountId": accountId,
            "providerId": handoff.providerId,
            "hint": hint,
            "bundleNullish": bundle is NSNull
        ]
        if !capabilities.isEmpty { input["capabilitiesOverride"] = capabilities }
        if let scopes = try scopesText(hint) { input["hintScopes"] = scopes }
        if let scopes = try scopesText(bundle) { input["bundleScopes"] = scopes }
        let inputJSON = String(decoding: try JSONSerialization.data(withJSONObject: input), as: UTF8.self)

        let planText: String
        do { planText = try connectedAccountOauthRowPlan(inputJson: inputJSON) } catch { throw ConnectedAccountRowPlanError.plan("protocol") }
        guard let plan = try JSONSerialization.jsonObject(with: Data(planText.utf8)) as? [String: Any] else {
            throw ConnectedAccountRowPlanError.plan("protocol")
        }
        guard plan["kind"] as? String == "ok", let steps = plan["steps"] as? [[String: Any]] else {
            throw ConnectedAccountRowPlanError.plan(plan["code"] as? String ?? "protocol")
        }
        var row: [String: String] = ["id": accountId]
        for step in steps {
            guard let field = step["field"] as? String else { throw ConnectedAccountRowPlanError.plan("protocol") }
            if let hashInput = step["hash"] as? String {
                row[field] = Self.sha256Hex(hashInput)
                continue
            }
            let failure = step["failure"] as? String ?? field
            let plaintext: String
            if step["bundle"] as? Bool == true {
                plaintext = handoff.refreshTokenBundleJSON
            } else if let text = step["encrypt"] as? String {
                plaintext = text
            } else {
                throw ConnectedAccountRowPlanError.plan("protocol")
            }
            let encrypted = try await encrypt(plaintext)
            guard !encrypted.isEmpty else { throw ConnectedAccountRowPlanError.encryptionFailed(failure) }
            row[field] = encrypted
        }
        if plan["malformed"] as? Bool == true { throw ConnectedAccountRowPlanError.plan("malformed") }
        let serialized = String(decoding: try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]), as: UTF8.self)
        let guardText: String
        do { guardText = try connectedAccountStorageGuard(serialized: serialized) } catch { throw ConnectedAccountRowPlanError.plan("storage_guard") }
        if let verdict = try JSONSerialization.jsonObject(with: Data(guardText.utf8)) as? [String: Any],
           verdict["kind"] as? String == "error" {
            throw ConnectedAccountRowPlanError.plan(verdict["code"] as? String ?? "storage_guard")
        }
        // Web adds the user hash on create (`createConnectedAccount`); the row itself never carries the raw id.
        guard let user = await userId(), !user.isEmpty else { throw ConnectedAccountRowPlanError.invalidHandoff }
        row["hashed_user_id"] = Self.sha256Hex(user)
        return row
    }
}
