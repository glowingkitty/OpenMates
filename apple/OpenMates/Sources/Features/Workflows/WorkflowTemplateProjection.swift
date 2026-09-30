// Portable, client-encrypted Workflow template projection. The fragment key
// remains on the device; the API receives only ciphertext and its checksum.
// Web source: frontend/packages/ui/src/services/workflowTemplateService.ts
// Specification: specifications/features/workflows/specification.yml
// Supporting existing assertions: workflows.content.encrypted-retained,
// workflows.access.boundaries. Template behavior follows the deployed web contract.

import CryptoKit
import Foundation

enum WorkflowTemplateProjectionError: Error {
    case missingTrigger
    case emptyTitle
    case nonPortableField(String)
    case malformedCiphertext
    case invalidKey
    case integrityFailure
}

struct WorkflowTemplateNode: Codable, Sendable {
    let id: String
    let type: WorkflowNodeType
    let title: String?
    let config: [String: AnyCodable]
}

struct WorkflowTemplateBindingRequirement: Codable, Sendable {
    let type: String
    let nodeId: String
    let appId: String?
    let skillId: String?

    enum CodingKeys: String, CodingKey {
        case type
        case nodeId = "node_id"
        case appId = "app_id"
        case skillId = "skill_id"
    }
}

struct WorkflowTemplatePayload: Codable, Sendable {
    let templateVersion: Int
    let title: String
    let description: String?
    let triggerTemplate: WorkflowTemplateNode
    let nodeTemplates: [WorkflowTemplateNode]
    let edgeTemplates: [WorkflowEdge]
    let variablesSchema: [String: AnyCodable]
    let requiredCapabilities: [String]
    let bindingRequirements: [WorkflowTemplateBindingRequirement]

    enum CodingKeys: String, CodingKey {
        case title, description
        case templateVersion = "template_version"
        case triggerTemplate = "trigger_template"
        case nodeTemplates = "node_templates"
        case edgeTemplates = "edge_templates"
        case variablesSchema = "variables_schema"
        case requiredCapabilities = "required_capabilities"
        case bindingRequirements = "binding_requirements"
    }
}

enum WorkflowTemplateProjection {
    static let schemaVersion = 1
    private static let forbiddenParts: [String] = [
        "token", "secret", "credential", "accountid", "connectionid", "connectedaccountid",
        "provideruserid", "webhooksecret", "apikey", "password", "vault", "grant", "runid",
        "versionid", "workflowid", "nextrunat", "claim", "wait", "output", "providerresponse",
        "sourcechatid", "encryptedgraphblobref", "encryptedcontentref", "fragmentkey", "shortkey",
        "templatekey"
    ]

    static func buildPayload(from workflow: WorkflowDetail) throws -> WorkflowTemplatePayload {
        guard let trigger = workflow.graph.nodes.first(where: { $0.id == workflow.graph.triggerNodeId }) else {
            throw WorkflowTemplateProjectionError.missingTrigger
        }
        let title = workflow.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { throw WorkflowTemplateProjectionError.emptyTitle }
        let requirements = workflow.graph.nodes.flatMap(bindingRequirements(for:))
        var capabilities = Set<String>()
        for requirement in requirements where requirement.type == "app_skill" {
            if let appId = requirement.appId {
                capabilities.insert(appId)
                if let skillId = requirement.skillId { capabilities.insert("\(appId).\(skillId)") }
            }
        }
        let payload = WorkflowTemplatePayload(
            templateVersion: workflow.graph.version,
            title: title,
            description: workflow.description?.trimmingCharacters(in: .whitespacesAndNewlines),
            triggerTemplate: portable(trigger),
            nodeTemplates: workflow.graph.nodes.filter { $0.id != trigger.id }.map(portable),
            edgeTemplates: workflow.graph.edges,
            variablesSchema: [:],
            requiredCapabilities: capabilities.sorted(),
            bindingRequirements: requirements
        )
        try validate(payload)
        return payload
    }

    static func validate(_ payload: WorkflowTemplatePayload) throws {
        guard payload.templateVersion >= 1, !payload.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !payload.triggerTemplate.id.isEmpty else {
            throw WorkflowTemplateProjectionError.malformedCiphertext
        }
        let encoded = try JSONEncoder().encode(payload)
        let object = try JSONSerialization.jsonObject(with: encoded)
        try validatePortable(object, path: "$")
    }

    static func encrypt(_ payload: WorkflowTemplatePayload, key: SymmetricKey) throws -> (ciphertext: String, checksum: String) {
        try validate(payload)
        let plaintext = try JSONEncoder().encode(payload)
        let sealed = try AES.GCM.seal(plaintext, using: key)
        guard let combined = sealed.combined else { throw WorkflowTemplateProjectionError.malformedCiphertext }
        let ciphertext = base64URL(combined)
        return (ciphertext, checksum(ciphertext))
    }

    static func decrypt(ciphertext: String, checksum expectedChecksum: String, fragmentKey: String) throws -> WorkflowTemplatePayload {
        guard checksum(ciphertext) == expectedChecksum else { throw WorkflowTemplateProjectionError.integrityFailure }
        guard let rawKey = Data(base64URLEncoded: fragmentKey), rawKey.count == 32 else {
            throw WorkflowTemplateProjectionError.invalidKey
        }
        guard let combined = Data(base64URLEncoded: ciphertext), combined.count > 12 + 16 else {
            throw WorkflowTemplateProjectionError.malformedCiphertext
        }
        let box = try AES.GCM.SealedBox(combined: combined)
        let decrypted = try AES.GCM.open(box, using: SymmetricKey(data: rawKey))
        let payload = try JSONDecoder().decode(WorkflowTemplatePayload.self, from: decrypted)
        try validate(payload)
        return payload
    }

    static func fragmentKey(_ key: SymmetricKey) -> String {
        key.withUnsafeBytes { base64URL(Data($0)) }
    }

    static func checksum(_ ciphertext: String) -> String {
        "sha256:\(base64URL(Data(SHA256.hash(data: Data(ciphertext.utf8)))))"
    }

    private static func portable(_ node: WorkflowNode) -> WorkflowTemplateNode {
        WorkflowTemplateNode(id: node.id, type: node.type, title: node.title, config: node.config)
    }

    private static func bindingRequirements(for node: WorkflowNode) -> [WorkflowTemplateBindingRequirement] {
        switch node.type {
        case .scheduleTrigger:
            return [WorkflowTemplateBindingRequirement(type: "schedule", nodeId: node.id, appId: nil, skillId: nil)]
        case .appSkillAction:
            return [WorkflowTemplateBindingRequirement(
                type: "app_skill", nodeId: node.id,
                appId: node.config["app_id"]?.value as? String,
                skillId: node.config["skill_id"]?.value as? String
            )]
        case .sendNotification, .sendEmailNotification:
            return [WorkflowTemplateBindingRequirement(type: "notification_preferences", nodeId: node.id, appId: nil, skillId: nil)]
        default:
            return []
        }
    }

    private static func validatePortable(_ value: Any, path: String) throws {
        if let items = value as? [Any] {
            for (index, item) in items.enumerated() { try validatePortable(item, path: "\(path)[\(index)]") }
            return
        }
        guard let fields = value as? [String: Any] else { return }
        for (key, child) in fields {
            let ascii = key.lowercased().utf8.filter { (48...57).contains(Int($0)) || (97...122).contains(Int($0)) }
            let normalized = String(bytes: ascii, encoding: .utf8) ?? ""
            if forbiddenParts.contains(where: normalized.contains) {
                throw WorkflowTemplateProjectionError.nonPortableField("\(path).\(key)")
            }
            try validatePortable(child, path: "\(path).\(key)")
        }
    }

    private static func base64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
