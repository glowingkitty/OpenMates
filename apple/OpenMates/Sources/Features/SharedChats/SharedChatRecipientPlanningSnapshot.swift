// Read-only settings data decrypted from an already authenticated recipient
// manifest. No owner keys, task services, account state or persistence involved.
// Web: frontend/packages/ui/src/services/sharedChatDetailsService.ts
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open, chat-share-settings.readonly-viewer-controls

import CryptoKit
import Foundation

struct SharedChatRecipientPlanningSnapshot {
    let tasks: [ChatSettingsPlanningRow]
    let plans: [ChatSettingsPlanningRow]
    static let empty = Self(tasks: [], plans: [])

    @MainActor static func load(context: SharedChatRecipientContext) async throws -> Self {
        try Task.checkCancellation()
        guard let manifest = try JSONSerialization.jsonObject(with: context.encryptedManifest) as? [String: Any] else {
            throw SharedChatRecipientError.invalidResponse
        }
        func hash(_ value: String) -> String {
            SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
        }
        func rows(kind: String) async throws -> [ChatSettingsPlanningRow] {
            let records = manifest["\(kind)s"] as? [[String: Any]] ?? []
            let wrappers = manifest["\(kind)_key_wrappers"] as? [[String: Any]] ?? []
            var result: [ChatSettingsPlanningRow] = []
            var seen = Set<String>()
            for row in records {
                try Task.checkCancellation()
                guard let id = row["\(kind)_id"] as? String, !id.isEmpty, seen.insert(id).inserted,
                      let wrapper = wrappers.first(where: {
                          $0["key_type"] as? String == "chat" && $0["hashed_\(kind)_id"] as? String == hash(id)
                      }), let encryptedKey = wrapper["encrypted_\(kind)_key"] as? String,
                      let bytes = try? await CryptoManager.shared.decryptBlob(base64String: encryptedKey, key: context.chatKey),
                      bytes.count == 32 else { continue }
                let rowKey = SymmetricKey(data: bytes)
                func field(_ name: String) async -> String {
                    guard let encrypted = row[name] as? String, !encrypted.isEmpty else { return "" }
                    return (try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: rowKey)) ?? ""
                }
                let status = row["status"] as? String ?? ""
                if kind == "plan", ["completed", "archived"].contains(status) { continue }
                let title = await field("encrypted_title")
                let detail: String
                if kind == "plan" { detail = await field("encrypted_goal") }
                else {
                    let description = await field("encrypted_description")
                    detail = description.isEmpty ? await field("encrypted_latest_instruction") : description
                }
                // task remains nil: these display rows cannot become writable owner items.
                result.append(.init(id: id, title: title, detail: detail, status: status))
            }
            return kind == "plan" ? Array(result.prefix(6)) : result
        }
        let tasks = try await rows(kind: "task")
        let plans = try await rows(kind: "plan")
        try Task.checkCancellation()
        return .init(tasks: tasks, plans: plans)
    }
}
