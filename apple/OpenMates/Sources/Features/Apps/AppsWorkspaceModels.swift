// Web sources: types/appsWorkspace.ts, components/apps/appsSkillFormUtils.ts,
// services/appsWorkspaceResultsService.ts
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.forms.metadata-driven, apps.execution.direct-shared-contract,
// apps.results.web-retained-graph, apps.library.embeds-account-paginated
import CryptoKit
import CoreFoundation
import Foundation

struct AppsSkillDetails: Decodable {
    let appID: String
    let skillID: String
    let slug: String
    let name: String
    let description: String
    let inputSchema: [String: AnyCodable]
    let primaryFields: [String]
    let defaults: [String: AnyCodable]
    let pricing: [String: AnyCodable]?
    let providers: [[String: AnyCodable]]
    let models: [[String: AnyCodable]]
    let anonymousAllowed: Bool
    let executionAvailable: Bool
    let unavailableReason: String?
    let executionMode: String?

    enum CodingKeys: String, CodingKey {
        case appID = "app_id", skillID = "skill_id", slug, name, description
        case inputSchema = "input_schema", primaryFields = "primary_fields", defaults, pricing, providers, models
        case anonymousAllowed = "anonymous_allowed", executionAvailable = "execution_available"
        case unavailableReason = "unavailable_reason", executionMode = "execution_mode"
    }
}

enum AppsWorkspaceTab: String, CaseIterable, Identifiable {
    case overview, focusModes = "focus_modes", memories = "settings_memories", embeds, workflows
    var id: String { rawValue }
}

struct AppsResultRow: Codable, Identifiable {
    let embedID: String
    let appID: String
    let skillID: String
    let status: EmbedStatus
    let createdAt: Int
    var id: String { embedID }
    enum CodingKeys: String, CodingKey {
        case embedID = "embed_id", appID = "app_id", skillID = "skill_id", status, createdAt = "created_at"
    }
}

struct AppsResultsPage: Decodable {
    let items: [AppsResultRow]
    let hasMore: Bool
    let offset: Int
    let limit: Int
    enum CodingKeys: String, CodingKey { case items, hasMore = "has_more", offset, limit }
}

struct AppsCipherRow: Codable {
    let embedID: String
    let encryptedType: String
    let encryptedContent: String
    let status: EmbedStatus
    let embedIDs: [String]?
    let parentEmbedID: String?
    var appID: String? = nil
    var skillID: String? = nil
    var hashedChatID: String? = nil
    enum CodingKeys: String, CodingKey {
        case embedID = "embed_id", encryptedType = "encrypted_type", encryptedContent = "encrypted_content"
        case status, embedIDs = "embed_ids", parentEmbedID = "parent_embed_id"
        case appID = "app_id", skillID = "skill_id", hashedChatID = "hashed_chat_id"
    }
}

struct AppsSavedGraph: Codable {
    let appID: String
    let skillID: String
    let teamID: String?
    let rootEmbedID: String
    let embeds: [AppsCipherRow]
    let linkedEmbedIDs: [String]
    let encryptedEmbedKey: String
    let expectedUserID: String
    enum CodingKeys: String, CodingKey {
        case appID = "app_id", skillID = "skill_id", teamID = "team_id", rootEmbedID = "root_embed_id"
        case embeds, linkedEmbedIDs = "linked_embed_ids", encryptedEmbedKey = "encrypted_embed_key"
        case expectedUserID = "expected_user_id"
    }
}

struct AppsResultDetail: Decodable {
    let root: AppsCipherRow
    let children: [AppsCipherRow]
    let linked: [AppsCipherRow]?
    let key: KeyWrapper?
    struct KeyWrapper: Decodable {
        let encryptedEmbedKey: String
        let keyType: String
        enum CodingKeys: String, CodingKey { case encryptedEmbedKey = "encrypted_embed_key", keyType = "key_type" }
    }
}

enum AppsWorkspaceError: Error, Equatable { case unavailable, invalidResponse, failed, missingKey, invalidInput, timedOut }

/// Projection and validation run when metadata or edits change, never in body.
enum AppsSkillInput {
    static func value(_ input: [String: Any], path: String) -> Any? {
        var cursor: Any? = input
        for part in path.split(separator: ".").map(String.init) {
            cursor = (cursor as? [String: Any])?[part.replacingOccurrences(of: "[]", with: "")]
            if part.hasSuffix("[]") { cursor = (cursor as? [Any])?.first }
        }
        return cursor
    }
    static func replacing(_ input: [String: Any], path: String, value: Any) -> [String: Any] {
        let parts = path.split(separator: ".").map(String.init)
        func walk(_ current: Any?, _ index: Int) -> Any {
            guard index < parts.count else { return value }
            let part = parts[index], key = part.replacingOccurrences(of: "[]", with: "")
            var object = current as? [String: Any] ?? [:]
            if part.hasSuffix("[]") {
                var items = object[key] as? [Any] ?? []
                let first = walk(items.first, index + 1)
                if items.isEmpty { items = [first] } else { items[0] = first }
                object[key] = items
            } else { object[key] = walk(object[key], index + 1) }
            return object
        }
        return walk(input, 0) as? [String: Any] ?? input
    }
    static func expandingComposite(_ paths: [String], schema: [String: Any]) -> [String] {
        var expanded = paths
        for path in paths {
            var parts = path.split(separator: ".").map(String.init)
            guard let field = parts.popLast() else { continue }
            var parent = schema
            for part in parts {
                parent = resolve(parent, root: schema)
                parent = (parent["properties"] as? [String: [String: Any]])?[part.replacingOccurrences(of: "[]", with: "")] ?? [:]
                if part.hasSuffix("[]") { parent = parent["items"] as? [String: Any] ?? [:] }
            }
            let ui = parent["x-ui"] as? [String: Any] ?? [:]
            guard ui["control"] as? String == "date-range" else { continue }
            let start = ui["start_field"] as? String ?? "start_date", end = ui["end_field"] as? String ?? "end_date"
            guard field == start || field == end else { continue }
            let partner = (parts + [field == start ? end : start]).joined(separator: ".")
            if !expanded.contains(partner) { expanded.append(partner) }
        }
        return expanded
    }
    static func resolve(_ schema: [String: Any], root: [String: Any], seen: Set<String> = []) -> [String: Any] {
        if let ref = schema["$ref"] as? String, ref.hasPrefix("#/"), !seen.contains(ref) {
            var value: Any = root
            for part in ref.dropFirst(2).split(separator: "/") {
                value = (value as? [String: Any])?[String(part).replacingOccurrences(of: "~1", with: "/").replacingOccurrences(of: "~0", with: "~")] ?? [:]
            }
            if var target = value as? [String: Any] {
                target.merge(schema) { _, new in new }; target.removeValue(forKey: "$ref")
                return resolve(target, root: root, seen: seen.union([ref]))
            }
        }
        let variants = (schema["anyOf"] ?? schema["oneOf"]) as? [[String: Any]] ?? []
        let nonNull = variants.filter { $0["type"] as? String != "null" }
        if nonNull.count == 1 {
            var result = resolve(nonNull[0], root: root, seen: seen)
            result.merge(schema) { _, new in new }; result.removeValue(forKey: "anyOf"); result.removeValue(forKey: "oneOf")
            return result
        }
        return schema
    }

    static func leaves(_ schema: [String: Any], root: [String: Any]? = nil, prefix: String = "") -> [String] {
        let root = root ?? schema, node = resolve(schema, root: root)
        if node["type"] as? String == "array" { return leaves(node["items"] as? [String: Any] ?? [:], root: root, prefix: prefix + "[]") }
        if let properties = node["properties"] as? [String: [String: Any]] {
            return properties.keys.sorted().flatMap { leaves(properties[$0]!, root: root, prefix: prefix.isEmpty ? $0 : prefix + "." + $0) }
        }
        return prefix.isEmpty ? [] : [prefix]
    }

    static func select(_ schema: [String: Any], paths: [String], root: [String: Any]? = nil, prefix: String = "") -> [String: Any]? {
        let root = root ?? schema
        var node = resolve(schema, root: root)
        if !prefix.isEmpty && paths.contains(prefix) { return showAll(node) }
        if node["type"] as? String == "array" {
            guard let items = select(node["items"] as? [String: Any] ?? [:], paths: paths, root: root, prefix: prefix + "[]") else { return nil }
            node["items"] = items; return node
        }
        guard let properties = node["properties"] as? [String: [String: Any]] else { return nil }
        var selected: [String: Any] = [:]
        for (key, child) in properties {
            if let value = select(child, paths: paths, root: root, prefix: prefix.isEmpty ? key : prefix + "." + key) { selected[key] = value }
        }
        guard !selected.isEmpty else { return nil }
        node["properties"] = selected
        node["required"] = (node["required"] as? [String] ?? []).filter { selected[$0] != nil }
        return showAll(node)
    }

    static func showAll(_ schema: [String: Any]) -> [String: Any] {
        var node = schema, ui = schema["x-ui"] as? [String: Any] ?? [:]
        ui["basic"] = true; node["x-ui"] = ui
        if let properties = node["properties"] as? [String: [String: Any]] { node["properties"] = properties.mapValues(showAll) }
        if let items = node["items"] as? [String: Any] { node["items"] = showAll(items) }
        return node
    }

    static func validation(_ schema: [String: Any], input: Any, root: [String: Any]? = nil, path: String = "", required: Bool = true) -> [String] {
        let root = root ?? schema, node = resolve(schema, root: root)
        if input is NSNull { return required ? [path] : [] }
        if let text = input as? String, text.isEmpty { return required ? [path] : [] }
        if let values = node["enum"] as? [Any], !values.contains(where: { String(describing: $0) == String(describing: input) }) { return [path] }
        switch node["type"] as? String {
        case "object", .none:
            if node["properties"] == nil { return [] }
            guard let value = input as? [String: Any] else { return [path] }
            let needed = Set(node["required"] as? [String] ?? [])
            return (node["properties"] as? [String: [String: Any]] ?? [:]).flatMap { key, child in
                let next = path.isEmpty ? key : path + "." + key
                guard let item = value[key] else { return needed.contains(key) ? [next] : [] }
                return validation(child, input: item, root: root, path: next, required: needed.contains(key))
            }
        case "array":
            guard let values = input as? [Any] else { return [path] }
            if values.count < (node["minItems"] as? Int ?? 0) || values.count > (node["maxItems"] as? Int ?? Int.max) { return [path] }
            return values.enumerated().flatMap { validation(node["items"] as? [String: Any] ?? [:], input: $0.element, root: root, path: "\(path)[\($0.offset)]") }
        case "integer", "number":
            guard let value = input as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite else { return [path] }
            if node["type"] as? String == "integer", value.doubleValue.rounded() != value.doubleValue { return [path] }
            // Metadata may arrive as JSON NSNumber or native Int/Double values.
            // Casting an Int bound directly to Double drops that constraint.
            let minimum = numericBound(node["minimum"]) ?? -.infinity
            let maximum = numericBound(node["maximum"]) ?? .infinity
            return value.doubleValue < minimum || value.doubleValue > maximum ? [path] : []
        case "boolean": return (input as? NSNumber).map { CFGetTypeID($0) == CFBooleanGetTypeID() } == true ? [] : [path]
        case "string":
            guard let text = input as? String else { return [path] }
            if text.count < (node["minLength"] as? Int ?? 0) || text.count > (node["maxLength"] as? Int ?? Int.max) { return [path] }
            if let pattern = node["pattern"] as? String, text.range(of: pattern, options: .regularExpression) == nil { return [path] }
            return []
        default: return []
        }
    }

    private static func numericBound(_ raw: Any?) -> Double? {
        guard let number = raw as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite else { return nil }
        return number.doubleValue
    }

    static func prepare(_ schema: [String: Any], input: [String: Any], now: Date = Date(), timezone: TimeZone = .current) -> [String: Any] {
        let rootSchema = schema
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = timezone; calendar.firstWeekday = 2
        let formatter = DateFormatter(); formatter.calendar = calendar; formatter.timeZone = timezone; formatter.dateFormat = "yyyy-MM-dd"
        let today = calendar.startOfDay(for: now)
        func walk(_ schema: [String: Any], _ value: Any) -> Any {
            let node = resolve(schema, root: rootSchema)
            if let token = value as? [String: Any], let name = token["$date"] as? String {
                let weekday = (calendar.component(.weekday, from: today) + 5) % 7
                let offsets = ["today": 0, "today_end": 0, "next_seven_days_start": 0, "next_seven_days_end": 6, "next_week_start": 7 - weekday, "next_week_end": 13 - weekday]
                guard let offset = offsets[name], let date = calendar.date(byAdding: .day, value: offset, to: today) else { return value }
                let day = formatter.string(from: date)
                return token["format"] as? String == "datetime" || node["format"] as? String == "date-time"
                    ? day + (name.hasSuffix("_end") ? "T23:59:59" : "T00:00:00") + "[\(timezone.identifier)]" : day
            }
            if let values = value as? [Any] { return values.map { walk(node["items"] as? [String: Any] ?? [:], $0) } }
            if var object = value as? [String: Any] {
                for (key, child) in node["properties"] as? [String: [String: Any]] ?? [:] { if let item = object[key] { object[key] = walk(child, item) } }
                return object
            }
            return value
        }
        return walk(schema, input) as? [String: Any] ?? input
    }
}
