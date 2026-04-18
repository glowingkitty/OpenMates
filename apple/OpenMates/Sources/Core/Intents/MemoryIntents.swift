// Memory Shortcuts — list and manage app memories via REST API.
// Memories are encrypted and stored per-app, but we can list available
// memory fields and manage them through the apps metadata endpoint.

import AppIntents
import Foundation

// MARK: - List Memory Fields

struct ListMemoryFieldsIntent: AppIntent {
    static let title: LocalizedStringResource = "List Memory Fields"
    static let description: IntentDescription = "List all available memory fields across OpenMates apps."
    static let openAppWhenRun = false

    @Parameter(title: "App", description: "Specific app to list memories for (leave empty for all)", default: nil)
    var appId: String?

    static var parameterSummary: some ParameterSummary {
        Summary("List memory fields") {
            \.$appId
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        if let appId {
            // Single app
            let data: Data = try await APIClient.shared.request(
                .get, path: "/v1/apps/\(appId)"
            )
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .result(value: "Could not load app metadata.")
            }

            let memories = json["settings_and_memories"] as? [[String: Any]] ?? []
            if memories.isEmpty {
                return .result(value: "\(appId) has no memory fields.")
            }

            let lines = memories.map { field -> String in
                let name = field["name"] as? String ?? field["id"] as? String ?? "?"
                let desc = field["description"] as? String ?? ""
                return "• \(name)\(desc.isEmpty ? "" : " — \(desc)")"
            }

            return .result(value: "\(appId) memory fields:\n\(lines.joined(separator: "\n"))")

        } else {
            // All apps
            let data: Data = try await APIClient.shared.request(
                .get, path: "/v1/apps"
            )
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let apps = json["apps"] as? [[String: Any]] else {
                return .result(value: "Could not load apps.")
            }

            var output: [String] = []
            for app in apps {
                let appName = app["name"] as? String ?? app["id"] as? String ?? "?"
                let memories = app["settings_and_memories"] as? [[String: Any]] ?? []
                if !memories.isEmpty {
                    let names = memories.compactMap { $0["name"] as? String ?? $0["id"] as? String }
                    output.append("\(appName): \(names.joined(separator: ", "))")
                }
            }

            if output.isEmpty {
                return .result(value: "No apps have memory fields configured.")
            }

            return .result(value: "Apps with memories:\n\(output.joined(separator: "\n"))")
        }
    }
}

// MARK: - List Apps

struct ListAppsIntent: AppIntent {
    static let title: LocalizedStringResource = "List OpenMates Apps"
    static let description: IntentDescription = "List all available OpenMates apps and their skills."
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let data: Data = try await APIClient.shared.request(
            .get, path: "/v1/apps"
        )
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let apps = json["apps"] as? [[String: Any]] else {
            return .result(value: "Could not load apps.")
        }

        let lines = apps.map { app -> String in
            let name = app["name"] as? String ?? app["id"] as? String ?? "?"
            let skills = (app["skills"] as? [[String: Any]])?.compactMap { $0["name"] as? String } ?? []
            let skillList = skills.isEmpty ? "no skills" : skills.joined(separator: ", ")
            return "• \(name) (\(skillList))"
        }

        return .result(value: "\(apps.count) apps:\n\(lines.joined(separator: "\n"))")
    }
}
