// Saved-item values (`app_id` + category + decrypted fields with `embed_id`
// and date fields) read by the Welcome Continue cards (`MainAppView`
// `WelcomeChatCardData.savedMemory`, `WelcomeContinueService`), the
// upcoming-item Live Activity and the voice-call permission prompt. The typed
// app-memory service that produced them was removed (the server answers
// typed writes with 410); Settings > Memories uses the core's Memory
// documents (`SettingsMemoryDocuments.swift`). The web now saves items as an
// encrypted saved flag on the embed itself, which this client cannot read yet.
// Web source: frontend/packages/ui/src/services/savedEmbedService.ts (SavedEmbed.itemValue)
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.typed.removed, app-memories.saved-items.not-memories

import Foundation

indirect enum SettingsMemoryValue: Equatable, Codable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: Self]), array([Self]), null

    init(from decoder: any Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([Self].self) { self = .array(v) }
        else { self = .object(try c.decode([String: Self].self)) }
    }
    func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    var object: [String: Self]? { if case .object(let v) = self { return v }; return nil }
    var string: String? { if case .string(let v) = self { return v }; return nil }
    var display: String {
        switch self {
        case .string(let v): return v
        case .bool(let v): return v ? "true" : "false"
        case .number(let v): return v.rounded() == v ? String(format: "%.0f", v) : String(v)
        case .null: return "null"
        default: return (try? json()) ?? ""
        }
    }
    func json() throws -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
        return String(decoding: try encoder.encode(self), as: UTF8.self)
    }
    static func parse(_ text: String) throws -> Self { try JSONDecoder().decode(Self.self, from: Data(text.utf8)) }
    static func from(_ raw: Any) -> Self? {
        guard let data = try? JSONSerialization.data(withJSONObject: raw, options: [.fragmentsAllowed]) else { return nil }
        return try? JSONDecoder().decode(Self.self, from: data)
    }
}

struct SettingsMemoryEntry: Identifiable, Equatable {
    let id: String
    let appId: String
    let categoryId: String
    var key: String
    var value: String
    let createdAt: Int
    var updatedAt: Int
    var version: Int
    let isExample: Bool
    var fields: [String: SettingsMemoryValue] = [:]
}
