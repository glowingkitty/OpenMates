// Shared skill execution helper for all AppIntent shortcuts.
// Calls POST /v1/apps/{appId}/skills/{skillId} with the standard
// requests-array body format. Handles auth via the shared APIClient.
//
// Also provides SkillFormatter for converting raw JSON responses
// into human-readable text for Siri and Shortcuts output.

import Foundation

enum SkillExecutor {
    /// Execute a skill via the REST API and return the raw JSON response.
    static func execute(appId: String, skillId: String, body: [String: Any]) async throws -> [String: Any] {
        let data: Data = try await APIClient.shared.request(
            .post, path: "/v1/apps/\(appId)/skills/\(skillId)", body: body
        )

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw SkillError.invalidResponse
        }

        return json
    }

    enum SkillError: LocalizedError {
        case invalidResponse
        case executionFailed(String)

        var errorDescription: String? {
            switch self {
            case .invalidResponse: return "Invalid response from OpenMates API"
            case .executionFailed(let msg): return msg
            }
        }
    }
}

enum SkillFormatter {
    /// Format raw skill JSON response into readable text for Shortcuts output.
    /// The `type` hint determines which fields to extract and how to present them.
    static func formatResults(_ json: [String: Any], type: String) -> String {
        // Check for error responses
        if let error = json["error"] as? String {
            return "Error: \(error)"
        }
        if let detail = json["detail"] as? String {
            return "Error: \(detail)"
        }

        // Most skill responses have a "results" array with per-request responses
        if let results = json["results"] as? [[String: Any]] {
            return results.map { formatSingleResult($0, type: type) }.joined(separator: "\n\n---\n\n")
        }

        // Some skills return data directly at the top level
        return formatSingleResult(json, type: type)
    }

    private static func formatSingleResult(_ result: [String: Any], type: String) -> String {
        // Extract items array (common pattern: result.items or result.data)
        let items = (result["items"] as? [[String: Any]])
            ?? (result["data"] as? [[String: Any]])
            ?? (result["results"] as? [[String: Any]])
            ?? []

        if items.isEmpty {
            // Try to format the result itself as a single item
            return formatItem(result, type: type)
        }

        let formatted = items.prefix(10).enumerated().map { index, item in
            "\(index + 1). \(formatItem(item, type: type))"
        }

        return formatted.joined(separator: "\n\n")
    }

    private static func formatItem(_ item: [String: Any], type: String) -> String {
        // Build output from common fields across different skill types
        var parts: [String] = []

        if let title = item["title"] as? String { parts.append(title) }
        if let name = item["name"] as? String, item["title"] == nil { parts.append(name) }
        if let description = item["description"] as? String { parts.append(description) }
        if let snippet = item["snippet"] as? String, item["description"] == nil { parts.append(snippet) }
        if let url = item["url"] as? String { parts.append(url) }
        if let content = item["content"] as? String, parts.isEmpty { parts.append(String(content.prefix(300))) }

        // Type-specific fields
        switch type {
        case "shopping":
            if let price = item["price"] as? String { parts.append("Price: \(price)") }
        case "travel", "stays":
            if let price = item["price"] as? String { parts.append("Price: \(price)") }
            if let duration = item["duration"] as? String { parts.append("Duration: \(duration)") }
        case "events":
            if let date = item["date"] as? String { parts.append("Date: \(date)") }
            if let venue = item["venue"] as? String { parts.append("Venue: \(venue)") }
        case "health":
            if let address = item["address"] as? String { parts.append("Address: \(address)") }
            if let phone = item["phone"] as? String { parts.append("Phone: \(phone)") }
        case "math":
            if let result = item["result"] { parts.append("= \(result)") }
        case "recipes":
            if let calories = item["calories"] { parts.append("Calories: \(calories)") }
            if let time = item["total_time"] as? String { parts.append("Time: \(time)") }
        default:
            break
        }

        return parts.isEmpty ? "No details available" : parts.joined(separator: "\n")
    }
}
