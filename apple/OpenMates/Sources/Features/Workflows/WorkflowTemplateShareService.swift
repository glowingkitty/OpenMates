// Owner-scoped transport for encrypted Workflow template projections.
// Web source: frontend/packages/ui/src/services/workflowTemplateService.ts
// Specification: specifications/features/workflows/specification.yml
// Supporting existing assertions: workflows.content.encrypted-retained,
// workflows.access.boundaries. Template behavior follows the deployed web contract.

import CryptoKit
import Foundation

struct WorkflowTemplateShareResult: Sendable {
    let shortURL: URL
    let longURL: URL
    let templateId: String
    let shortToken: String
}

struct WorkflowTemplateOwnerStatus: Sendable {
    let exists: Bool
    let isRevoked: Bool
}

struct WorkflowTemplateImported: Decodable, Sendable {
    let workflow: WorkflowDetail
    let bindingRequirements: [WorkflowTemplateBindingRequirement]

    enum CodingKeys: String, CodingKey {
        case bindingRequirements = "binding_requirements"
    }

    init(from decoder: Decoder) throws {
        workflow = try WorkflowDetail(from: decoder)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        bindingRequirements = try container.decodeIfPresent(
            [WorkflowTemplateBindingRequirement].self, forKey: .bindingRequirements
        ) ?? []
    }
}

private struct WorkflowTemplateImportResponse: Decodable {
    let workflow: WorkflowTemplateImported
}

private struct WorkflowTemplateOwnerProjection: Decodable {
    let templateId: String
    let ownerWrappedKey: String
    let revokedAt: Int?

    enum CodingKeys: String, CodingKey {
        case templateId = "template_id"
        case ownerWrappedKey = "owner_wrapped_key"
        case revokedAt = "revoked_at"
    }
}

private struct WorkflowTemplatePublicProjection: Decodable {
    let templateId: String
    let ciphertext: String
    let ciphertextChecksum: String
    let projectionSchemaVersion: Int

    enum CodingKeys: String, CodingKey {
        case templateId = "template_id"
        case ciphertext
        case ciphertextChecksum = "ciphertext_checksum"
        case projectionSchemaVersion = "projection_schema_version"
    }
}

private struct WorkflowTemplateProjectionWrite: Encodable {
    let templateId: String
    let sourceVersion: Int
    let ciphertext: String
    let ciphertextChecksum: String
    let ownerWrappedKey: String
    let projectionSchemaVersion: Int

    enum CodingKeys: String, CodingKey {
        case templateId = "template_id"
        case sourceVersion = "source_version"
        case ciphertext
        case ciphertextChecksum = "ciphertext_checksum"
        case ownerWrappedKey = "owner_wrapped_key"
        case projectionSchemaVersion = "projection_schema_version"
    }
}

private struct WorkflowTemplateProjectionWriteResponse: Decodable {
    let templateId: String
    enum CodingKeys: String, CodingKey { case templateId = "template_id" }
}

enum WorkflowTemplateShareError: Error {
    case masterKeyUnavailable
    case incompatibleProjection
    case importedWorkflowEnabled
}

actor WorkflowTemplateShareService {
    private let client: APIClient
    private let crypto: CryptoManager

    init(client: APIClient = .shared, crypto: CryptoManager = .shared) {
        self.client = client
        self.crypto = crypto
    }

    nonisolated static func publicProjectionPath(templateId: String) -> String {
        let encoded = templateId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? templateId
        return "/v1/workflows/template-projections/\(encoded)"
    }

    func ownerStatus(workflowId: String, accountId: String) async throws -> WorkflowTemplateOwnerStatus {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        do {
            let projection: WorkflowTemplateOwnerProjection = try await client.request(
                .get, path: "/v1/workflows/\(encode(workflowId))/template-projection",
                serverProfile: scope.serverProfile,
                expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
            )
            return WorkflowTemplateOwnerStatus(exists: true, isRevoked: projection.revokedAt != nil)
        } catch APIError.httpError(let status, _) where status == 404 {
            return WorkflowTemplateOwnerStatus(exists: false, isRevoked: false)
        }
    }

    /// The projection key is wrapped with this account's master key and never
    /// sent in a URL request. Only the recipient's fragment carries raw key bytes.
    func createShare(workflow: WorkflowDetail, accountId: String) async throws -> WorkflowTemplateShareResult {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        let webURL = scope.serverProfile.webBaseURL
        guard let masterKey = try await crypto.loadMasterKey(for: accountId) else {
            throw WorkflowTemplateShareError.masterKeyUnavailable
        }
        let path = "/v1/workflows/\(encode(workflow.id))/template-projection"
        let existing: WorkflowTemplateOwnerProjection?
        do {
            existing = try await client.request(
                .get, path: path, serverProfile: scope.serverProfile,
                expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
            )
        } catch APIError.httpError(let status, _) where status == 404 {
            existing = nil
        }

        let templateId = existing?.templateId ?? "wt_\(UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased())"
        let key: SymmetricKey
        let wrappedKey: String
        if let existing {
            key = try await crypto.unwrapChatKey(encryptedChatKeyBase64: existing.ownerWrappedKey, masterKey: masterKey)
            wrappedKey = existing.ownerWrappedKey
        } else {
            key = SymmetricKey(size: .bits256)
            wrappedKey = try await crypto.wrapChatKey(key, masterKey: masterKey)
        }
        let payload = try WorkflowTemplateProjection.buildPayload(from: workflow)
        let encrypted = try WorkflowTemplateProjection.encrypt(payload, key: key)
        let body = WorkflowTemplateProjectionWrite(
            templateId: templateId,
            sourceVersion: workflow.version ?? 1,
            ciphertext: encrypted.ciphertext,
            ciphertextChecksum: encrypted.checksum,
            ownerWrappedKey: wrappedKey,
            projectionSchemaVersion: WorkflowTemplateProjection.schemaVersion
        )
        let written: WorkflowTemplateProjectionWriteResponse = try await client.request(
            .put, path: path, serverProfile: scope.serverProfile, body: body,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        guard written.templateId == templateId else { throw WorkflowTemplateShareError.incompatibleProjection }

        let longURL = try ShareLinkCrypto.urlWithFragment(
            webURL.appendingPathComponent("share")
                .appendingPathComponent("workflow-template")
                .appendingPathComponent(templateId),
            fragment: "key=\(WorkflowTemplateProjection.fragmentKey(key))"
        )
        let short = try await ShareLinkCrypto.encryptedShortURL(longURL)
        let shortBody: [String: Any] = [
            "token": short.token,
            "encrypted_url": short.encryptedURL,
            "content_type": "workflow_template",
            "content_id": templateId,
            "password_protected": false
        ]
        let _: Data = try await client.request(
            .post, path: "/v1/share/short-url", serverProfile: scope.serverProfile, body: shortBody,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        return WorkflowTemplateShareResult(
            shortURL: try ShareLinkCrypto.shortURL(webURL: webURL, token: short.token, shortKey: short.shortKey),
            longURL: longURL,
            templateId: templateId,
            shortToken: short.token
        )
    }

    func revoke(workflowId: String, accountId: String, shortToken: String? = nil) async throws {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        let _: Data = try await client.request(
            .post, path: "/v1/workflows/\(encode(workflowId))/template-projection/revoke",
            serverProfile: scope.serverProfile, body: [:] as [String: String],
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        if let shortToken {
            let _: Data = try await client.request(
                .delete, path: "/v1/share/short-url/\(encode(shortToken))",
                serverProfile: scope.serverProfile,
                expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
            )
        }
    }

    func unrevoke(workflowId: String, accountId: String) async throws {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        let _: Data = try await client.request(
            .post, path: "/v1/workflows/\(encode(workflowId))/template-projection/unrevoke",
            serverProfile: scope.serverProfile, body: [:] as [String: String],
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
    }

    func loadShared(templateId: String, fragmentKey: String, accountId: String) async throws -> WorkflowTemplatePayload {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        let projection: WorkflowTemplatePublicProjection = try await client.request(
            .get, path: Self.publicProjectionPath(templateId: templateId),
            serverProfile: scope.serverProfile,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        guard projection.templateId == templateId,
              projection.projectionSchemaVersion == WorkflowTemplateProjection.schemaVersion else {
            throw WorkflowTemplateShareError.incompatibleProjection
        }
        return try WorkflowTemplateProjection.decrypt(
            ciphertext: projection.ciphertext,
            checksum: projection.ciphertextChecksum,
            fragmentKey: fragmentKey
        )
    }

    func importTemplate(_ payload: WorkflowTemplatePayload, accountId: String) async throws -> WorkflowTemplateImported {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        try WorkflowTemplateProjection.validate(payload)
        let response: WorkflowTemplateImportResponse = try await client.request(
            .post, path: "/v1/workflows/template-import", serverProfile: scope.serverProfile,
            body: payload, expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        guard !response.workflow.workflow.enabled else { throw WorkflowTemplateShareError.importedWorkflowEnabled }
        return response.workflow
    }

    func completeBinding(workflowId: String, requirement: WorkflowTemplateBindingRequirement,
                         accountId: String) async throws {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        let body = ["type": requirement.type, "node_id": requirement.nodeId]
        let _: Data = try await client.request(
            .post, path: "/v1/workflows/\(encode(workflowId))/binding-requirements/complete",
            serverProfile: scope.serverProfile, body: body,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
    }

    func enableImported(workflowId: String, accountId: String) async throws -> WorkflowDetail {
        let scope = try await WorkflowRequestScope.capture(accountId: accountId)
        let response: WorkflowResponse = try await client.request(
            .post, path: WorkflowAPIRequestFactory.enablePath(workflowId),
            serverProfile: scope.serverProfile,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        return response.workflow
    }

    private func encode(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? value
    }
}
