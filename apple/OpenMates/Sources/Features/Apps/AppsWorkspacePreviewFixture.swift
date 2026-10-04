// Web sources: components/apps/AppsWorkspace.preview.ts, AppsSkillForm.preview.ts
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.discovery.public-catalog, apps.forms.metadata-driven,
// apps.execution.direct-shared-contract, apps.presentation.shared-detail-and-recency
import Foundation

@MainActor
enum AppsWorkspacePreviewFixture {
    static var app: SettingsAppsFullView.AppInfo {
        SettingsAppsFullView.AppInfo(id: "web", name: "Web", description: "Search the web directly", category: "top_picks",
            rawCategory: "personal", isInstalled: nil, iconName: "web", providers: [], providerDisplayOrder: [],
            lastUpdated: nil, skills: [SettingsAppsFullView.AppSkill(id: "search", name: "Search", description: "Find websites")],
            focusModes: [], settingsAndMemories: [], contentTypes: [])
    }
    static var details: AppsSkillDetails {
        AppsSkillDetails(appID: "web", skillID: "search", slug: "search", name: "Search", description: "Find websites",
            inputSchema: schema.mapValues(AnyCodable.init), primaryFields: ["requests[].query"],
            defaults: ["requests": AnyCodable([["query": "", "count": 6]])], pricing: ["fixed": AnyCodable(2)],
            providers: [["name": AnyCodable("Brave")]], models: [], anonymousAllowed: true,
            executionAvailable: true, unavailableReason: nil, executionMode: "sync")
    }
    static let schema: [String: Any] = ["type": "object", "required": ["requests"], "properties": [
        "requests": ["type": "array", "minItems": 1, "items": ["type": "object", "required": ["query"], "properties": [
            "query": ["type": "string", "title": "Query", "minLength": 1],
            "count": ["type": "integer", "title": "Count", "minimum": 1, "maximum": 20],
            "relevance_criteria": ["type": "string", "title": "Requirements", "maxLength": 1000]
        ]]]
    ]]
    static let response: [String: Any] = ["success": true, "data": ["results": [
        ["title": "OpenMates", "url": "https://openmates.org", "description": "Useful tools and private AI conversations", "provider": "Brave"]
    ]]]
}
