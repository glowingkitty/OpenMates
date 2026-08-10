// App store settings — browse, enable, and configure apps with category sections.
// Mirrors the web app's SettingsAppStore.svelte with categorized browsing,
// install/uninstall toggles, and app detail navigation.
// All strings use AppStrings (i18n).

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsAppStore.svelte
//          frontend/packages/ui/src/components/settings/SettingsAllApps.svelte
//          frontend/packages/ui/src/components/settings/AppDetails.svelte
//          frontend/packages/ui/src/components/settings/SkillDetails.svelte
//          frontend/packages/ui/src/components/settings/FocusModeDetails.svelte
//          frontend/packages/ui/src/components/settings/ContentEmbedDetails.svelte
//          frontend/packages/ui/src/components/settings/SkillExamplesSection.svelte
// CSS:     frontend/packages/ui/src/components/settings/SettingsAppStore.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsAppsFullView: View {
    @State private var apps: [AppInfo] = []
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var selectedApp: AppInfo?
    @State private var isShowingAllApps = false
    @State private var mostUsedAppIDs: [String] = []
    let onOpenExampleChat: (String) -> Void

    init(onOpenExampleChat: @escaping (String) -> Void = { chatId in
        guard let url = URL(string: "openmates://chat/\(chatId)") else { return }
        NotificationCenter.default.post(
            name: .deepLinkReceived,
            object: nil,
            userInfo: ["url": url]
        )
    }) {
        self.onOpenExampleChat = onOpenExampleChat
    }

    struct AppInfo: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        var category: String?
        let rawCategory: String?
        var isInstalled: Bool?
        let iconName: String?
        let providers: [ProviderRef]?
        let providerDisplayOrder: [String]?
        let lastUpdated: String?
        let skills: [AppSkill]?
        var focusModes: [AppSkill]?
        var settingsAndMemories: [AppSkill]?
        let contentTypes: [ContentType]

        var providerDisplayNames: [String] {
            let appProviders = providers?.map(\.displayName) ?? []
            let skillProviders = (skills ?? []).flatMap { $0.providerDisplayNames }
            let names = appProviders.isEmpty ? skillProviders : appProviders
            guard let providerDisplayOrder, !providerDisplayOrder.isEmpty else {
                return uniqueStrings(names)
            }
            let ordered = providerDisplayOrder.filter { names.contains($0) }
            let remaining = names.filter { !providerDisplayOrder.contains($0) }
            return uniqueStrings(ordered + remaining)
        }
    }

    struct AppCategoryEntry: Identifiable {
        let key: String
        let apps: [AppInfo]

        var id: String { key }
    }

    struct ProviderRef: Decodable, Hashable {
        let name: String
        let displayNameRaw: String?
        let noApiKey: Bool?

        var displayName: String { displayNameRaw?.isEmpty == false ? displayNameRaw! : name }

        enum CodingKeys: String, CodingKey {
            case name
            case displayName
            case noApiKey
        }

        enum SnakeCodingKeys: String, CodingKey {
            case name
            case displayName = "display_name"
            case noApiKey = "no_api_key"
        }

        init(name: String, displayNameRaw: String? = nil, noApiKey: Bool? = nil) {
            self.name = name
            self.displayNameRaw = displayNameRaw
            self.noApiKey = noApiKey
        }

        init(from decoder: Decoder) throws {
            if let stringValue = try? decoder.singleValueContainer().decode(String.self) {
                self.init(name: stringValue)
                return
            }

            if let container = try? decoder.container(keyedBy: CodingKeys.self),
               let name = try? container.decode(String.self, forKey: .name) {
                self.init(
                    name: name,
                    displayNameRaw: try container.decodeIfPresent(String.self, forKey: .displayName),
                    noApiKey: try container.decodeIfPresent(Bool.self, forKey: .noApiKey)
                )
                return
            }

            let container = try decoder.container(keyedBy: SnakeCodingKeys.self)
            self.init(
                name: try container.decode(String.self, forKey: .name),
                displayNameRaw: try container.decodeIfPresent(String.self, forKey: .displayName),
                noApiKey: try container.decodeIfPresent(Bool.self, forKey: .noApiKey)
            )
        }
    }

    struct AppSkill: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        let pricing: [String: AnyCodable]?
        let providers: [ProviderRef]?
        let providerDetails: [ProviderDetail]?
        let howToUse: [String]?
        let exampleTitles: [String]?
        let exampleChatIds: [String]?
        let process: [String]?
        let systemPrompt: String?
        let models: [ModelDetail]?
        let iconImage: String?
        let type: String?

        var howToUseExamples: [String]? { howToUse }
        var processBullets: [String]? { process }
        var modelNames: [String]? { models?.map(\.name) }
        var valueType: String? { type }

        var providerDisplayNames: [String] {
            uniqueStrings((providers ?? []).map(\.displayName))
        }

        init(
            id: String,
            name: String,
            description: String?,
            pricing: [String: AnyCodable]? = nil,
            providers: [ProviderRef]? = nil,
            providerDetails: [ProviderDetail]? = nil,
            howToUseExamples: [String]? = nil,
            exampleTitles: [String]? = nil,
            exampleChatIds: [String]? = nil,
            processBullets: [String]? = nil,
            systemPrompt: String? = nil,
            modelNames: [String]? = nil,
            models: [ModelDetail]? = nil,
            iconImage: String? = nil,
            valueType: String? = nil
        ) {
            self.id = id
            self.name = name
            self.description = description
            self.pricing = pricing
            self.providers = providers
            self.providerDetails = providerDetails
            self.howToUse = howToUseExamples
            self.exampleTitles = exampleTitles
            self.exampleChatIds = exampleChatIds
            self.process = processBullets
            self.systemPrompt = systemPrompt
            self.models = models ?? modelNames?.map {
                ModelDetail(id: $0, name: $0, description: nil, providerId: "", providerName: "", pricing: nil)
            }
            self.iconImage = iconImage
            self.type = valueType
        }
    }

    struct ProviderDetail: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        let logoSvg: String?
        let country: String?
        let privacyPolicy: String?
    }

    struct ModelDetail: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        let providerId: String
        let providerName: String
        let pricing: [String: AnyCodable]?
    }

    struct ContentType: Identifiable, Decodable {
        let id: String
        let contentTypeId: String
        let frontendType: String
        let backendType: String
        let skillId: String?
        let name: String
        let description: String
        let icon: String?
        let exampleKey: String
        let order: Int
    }

    enum MentionKind {
        case skill
        case focus
    }

    static func mentionSyntax(appId: String, itemId: String, kind: MentionKind) -> String {
        switch kind {
        case .skill: return "@skill:\(appId):\(itemId)"
        case .focus: return "@focus:\(appId):\(itemId)"
        }
    }

    static let appStoreExcludedAppIDs: Set<String> = ["ai"]
    static let newChatDraftID = "composer:new-chat"

    static let webAppStoreCategoryKeys: [String] = [
        "top_picks",
        "most_used",
        "new_apps",
        "for_work",
        "for_everyday_life",
    ]

    static let allAppsFilterKeys: [String] = [
        "all",
        "settings_memories",
        "focus_modes",
        "skills",
    ]

    static let allAppsSortKeys: [String] = ["newest", "name_asc", "name_desc"]

    private var filteredApps: [AppInfo] {
        guard !searchText.isEmpty else { return apps }
        return apps.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            ($0.description?.localizedCaseInsensitiveContains(searchText) ?? false) ||
            $0.providerDisplayNames.contains { $0.localizedCaseInsensitiveContains(searchText) }
        }
    }

    private var categoryEntries: [AppCategoryEntry] {
        Self.categorizeApps(filteredApps, mostUsedAppIDs: mostUsedAppIDs).filter { !$0.apps.isEmpty }
    }

    var body: some View {
        Group {
            if let selectedApp {
                AppDetailView(app: selectedApp, onOpenExampleChat: onOpenExampleChat) {
                    withAnimation(.easeOut(duration: 0.2)) {
                        self.selectedApp = nil
                    }
                }
                .transition(.move(edge: .trailing))
            } else if isShowingAllApps {
                SettingsAllAppsNativeView(apps: apps, onSelect: { app in
                    withAnimation(.easeOut(duration: 0.2)) {
                        selectedApp = app
                    }
                }) {
                    withAnimation(.easeOut(duration: 0.2)) {
                        isShowingAllApps = false
                    }
                }
            } else {
                OMSettingsPage(title: AppStrings.settingsApps, showsHeader: false) {
                    if isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.spacing8)
                    } else if apps.isEmpty {
                        OMSettingsSection {
                            Text(AppStrings.noAppsAvailable)
                                .foregroundStyle(Color.fontSecondary)
                                .padding(.spacing5)
                        }
                    } else {
                        VStack(spacing: 0) {
                            Color.clear
                                .frame(height: 0)
                                .accessibilityIdentifier("settings-app-store-page")

                            OMSettingsRow(title: AppStrings.showAllApps, icon: "app_store") {
                                withAnimation(.easeOut(duration: 0.2)) {
                                    isShowingAllApps = true
                                }
                            }
                            .accessibilityIdentifier("settings-show-all-apps-row")

                            appStoreCategories
                        }
                    }
                }
            }
        }
        .task { await loadApps() }
    }

    private func loadApps() async {
        if ProcessInfo.processInfo.arguments.contains("--ui-test-app-store-fixture") {
            apps = Self.uiTestApps
            isLoading = false
            return
        }

        do {
            let response: AppsMetadataResponse = try await APIClient.shared.request(
                .get,
                path: "/v1/apps/metadata?include_unavailable=true"
            )
            apps = response.apps.values
                .map(Self.appInfo(from:))
                .filter { !Self.appStoreExcludedAppIDs.contains($0.id) }
                .sorted { $0.name < $1.name }
        } catch {
            NativeDiagnostics.warning(
                "Apps metadata load failed errorType=\(type(of: error))",
                category: "settings_apps"
            )
        }
        do {
            let response: MostUsedAppsResponse = try await APIClient.shared.request(
                .get,
                path: "/v1/apps/most-used?limit=5"
            )
            mostUsedAppIDs = response.apps.map(\.appId)
        } catch {
            NativeDiagnostics.warning(
                "Most-used Apps metadata load failed errorType=\(type(of: error))",
                category: "settings_apps"
            )
        }
        isLoading = false
    }

    private var appStoreCategories: some View {
        ForEach(categoryEntries) { entry in
            OMSettingsSection(categoryTitle(entry.key), icon: categoryIcon(entry.key)) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 16) {
                        ForEach(entry.apps) { app in
                            AppStoreCardNative(app: app) {
                                withAnimation(.easeOut(duration: 0.2)) {
                                    selectedApp = app
                                }
                            }
                        }
                    }
                    .padding(.horizontal, .spacing5)
                    .padding(.bottom, .spacing3)
                    .padding(.trailing, .spacing5)
                }
                .accessibilityIdentifier("settings-app-category-\(entry.key)-scroll")
            }
        }
    }

    struct AppsMetadataResponse: Decodable {
        let apps: [String: AppMetadataItem]
    }

    struct MostUsedAppsResponse: Decodable {
        let apps: [MostUsedApp]
    }

    struct MostUsedApp: Decodable {
        let appId: String
    }

    struct AppMetadataItem: Decodable {
        let id: String
        let name: String
        let description: String?
        let category: String?
        let iconImage: String?
        let providers: [ProviderRef]?
        let providerDisplayOrder: [String]?
        let lastUpdated: String?
        let skills: [AppSkill]
        let focusModes: [AppSkill]
        let settingsAndMemories: [AppSkill]
        let contentTypes: [ContentType]

    }

    static func appStoreCategory(for app: AppMetadataItem) -> String {
        switch app.category {
        case "work": return "for_work"
        case "personal": return "for_everyday_life"
        default:
            return app.lastUpdated == nil ? "top_picks" : "new_apps"
        }
    }

    static func appInfo(from app: AppMetadataItem) -> AppInfo {
        AppInfo(
            id: app.id,
            name: app.name,
            description: app.description,
            category: Self.appStoreCategory(for: app),
            rawCategory: app.category,
            isInstalled: nil,
            iconName: normalizedIconName(app.iconImage) ?? AppIconView.iconName(forAppId: app.id),
            providers: app.providers,
            providerDisplayOrder: app.providerDisplayOrder,
            lastUpdated: app.lastUpdated,
            skills: app.skills,
            focusModes: app.focusModes,
            settingsAndMemories: app.settingsAndMemories,
            contentTypes: app.contentTypes
        )
    }

    static func categorizeApps(_ apps: [AppInfo], mostUsedAppIDs: [String] = []) -> [AppCategoryEntry] {
        let sortedByName = apps.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        var buckets = Dictionary(uniqueKeysWithValues: webAppStoreCategoryKeys.map { ($0, [AppInfo]()) })

        func add(_ app: AppInfo, to key: String) {
            guard buckets[key]?.contains(where: { $0.id == app.id }) == false,
                  (buckets[key]?.count ?? 0) < 5 else {
                return
            }
            buckets[key, default: []].append(app)
        }

        for app in sortedByName.prefix(5) { add(app, to: "top_picks") }
        for appID in mostUsedAppIDs {
            if let app = apps.first(where: { $0.id == appID }) {
                add(app, to: "most_used")
            }
        }

        let newest = apps
            .filter { $0.lastUpdated?.isEmpty == false }
            .sorted { ($0.lastUpdated ?? "") > ($1.lastUpdated ?? "") }
        for app in newest.prefix(5) { add(app, to: "new_apps") }

        for app in sortedByName where app.rawCategory == "work" { add(app, to: "for_work") }
        for app in sortedByName where app.rawCategory == "personal" { add(app, to: "for_everyday_life") }

        return webAppStoreCategoryKeys.map { AppCategoryEntry(key: $0, apps: buckets[$0] ?? []) }
    }

    static func normalizedIconName(_ iconImage: String?) -> String? {
        guard var iconName = iconImage?.trimmingCharacters(in: .whitespacesAndNewlines), !iconName.isEmpty else {
            return nil
        }
        if iconName.hasSuffix(".svg") {
            iconName = String(iconName.dropLast(4))
        }
        switch iconName {
        case "email": return "mail"
        case "coding": return "code"
        case "heart": return "health"
        default: return iconName
        }
    }

    private static let uiTestApps: [AppInfo] = [
        appInfo(from: AppMetadataItem(
            id: "weather",
            name: "Weather",
            description: "Forecasts and weather alerts",
            category: "personal",
            iconImage: "weather.svg",
            providers: [ProviderRef(name: "OpenWeather")],
            providerDisplayOrder: ["OpenWeather"],
            lastUpdated: "2026-05-01",
            skills: [AppSkill(
                id: "forecast",
                name: "Weather Forecast",
                description: "Get a forecast",
                pricing: ["fixed": AnyCodable(2)],
                providers: [ProviderRef(name: "OpenWeather")],
                providerDetails: [ProviderDetail(
                    id: "openweather",
                    name: "OpenWeather",
                    description: "Weather data provider",
                    logoSvg: "icons/openweather.svg",
                    country: "US",
                    privacyPolicy: nil
                )],
                howToUseExamples: ["Will it rain in Berlin tomorrow?"],
                exampleTitles: ["Berlin forecast"],
                exampleChatIds: ["example-flights-berlin-bangkok"],
                models: [ModelDetail(
                    id: "forecast-v2",
                    name: "OpenWeather Forecast",
                    description: "Forecast model",
                    providerId: "openweather",
                    providerName: "OpenWeather",
                    pricing: nil
                )]
            )],
            focusModes: [AppSkill(
                id: "travel_weather",
                name: "Travel Weather",
                description: "Plan around weather",
                howToUseExamples: ["Plan a weekend trip around sunny weather"],
                exampleTitles: ["Weekend trip forecast"],
                exampleChatIds: ["example-flights-berlin-bangkok"],
                processBullets: ["Check the forecast", "Recommend timing around bad weather"],
                systemPrompt: "Prioritize weather-aware travel planning."
            )],
            settingsAndMemories: [AppSkill(
                id: "home_location",
                name: "Home Location",
                description: "Remember a location",
                iconImage: "home.svg",
                valueType: "single"
            )],
            contentTypes: [ContentType(
                id: "weather.weather_day",
                contentTypeId: "weather_day",
                frontendType: "weather-day",
                backendType: "weather_day",
                skillId: "forecast",
                name: "Weather day",
                description: "A daily weather forecast.",
                icon: "weather",
                exampleKey: "weather.weather_day",
                order: 10
            )]
        )),
        appInfo(from: AppMetadataItem(
            id: "docs",
            name: "Docs",
            description: "Document work",
            category: "work",
            iconImage: "docs.svg",
            providers: [],
            providerDisplayOrder: [],
            lastUpdated: "2026-03-01",
            skills: [AppSkill(id: "summarize", name: "Summarize", description: "Summarize documents")],
            focusModes: [],
            settingsAndMemories: [],
            contentTypes: []
        )),
    ]

    private func categoryTitle(_ category: String) -> String {
        switch category {
        case "top_picks": return LocalizationManager.shared.text("settings.app_store.categories.explore_discover")
        case "most_used": return LocalizationManager.shared.text("settings.app_store.categories.most_used")
        case "new_apps": return LocalizationManager.shared.text("settings.app_store.categories.new_apps")
        case "for_work": return LocalizationManager.shared.text("settings.app_store.categories.for_work")
        case "for_everyday_life": return LocalizationManager.shared.text("settings.app_store.categories.for_everyday_life")
        default: return AppStrings.apps
        }
    }

    private func categoryIcon(_ category: String) -> String {
        switch category {
        case "top_picks": return "reload"
        case "most_used": return "heart"
        case "new_apps": return "create"
        case "for_work": return "business"
        case "for_everyday_life": return "home"
        default: return "app_store"
        }
    }

}

// MARK: - App row

struct AppRow: View {
    let app: SettingsAppsFullView.AppInfo
    let onToggle: () -> Void
    let onTap: () -> Void

    var body: some View {
        Button {
            onTap()
        } label: {
            HStack(spacing: .spacing4) {
                AppIconView(appId: app.id, size: 36)
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(app.name)
                        .font(.omSmall).fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                    if let desc = app.description {
                        Text(desc)
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                            .lineLimit(2)
                    }
                }

                Spacer()

                Button {
                    onToggle()
                } label: {
                    Text(app.isInstalled == true ? AppStrings.installed : AppStrings.add)
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(app.isInstalled == true ? Color.fontTertiary : Color.buttonPrimary)
                        .padding(.horizontal, .spacing3)
                        .padding(.vertical, .spacing1)
                        .background(app.isInstalled == true ? Color.grey20 : Color.buttonPrimary.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                }
                .buttonStyle(.plain)
                .accessibleButton(
                    app.isInstalled == true ? AppStrings.installed : AppStrings.add,
                    hint: app.isInstalled == true
                        ? LocalizationManager.shared.text("settings.app_store.remove_hint")
                        : LocalizationManager.shared.text("settings.app_store.add_hint")
                )
            }
        }
        .accessibleButton(app.name, hint: LocalizationManager.shared.text("settings.app_store.view_details_hint"))
    }
}

struct AppStoreCardNative: View {
    let app: SettingsAppsFullView.AppInfo
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .center, spacing: 12) {
                    ZStack(alignment: .top) {
                        providerBadges
                            .offset(x: -14, y: -20)

                        RoundedRectangle(cornerRadius: .radius3)
                            .fill(AppIconView.gradient(forAppId: app.id))
                            .frame(width: 38, height: 38)
                            .overlay(
                                Icon(app.iconName ?? AppIconView.iconName(forAppId: app.id), size: 19)
                                    .foregroundStyle(Color.fontButton)
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: .radius3)
                                    .stroke(Color.grey0, lineWidth: 2)
                            )
                    }
                    .frame(width: 38, height: 38)
                    .accessibilityHidden(true)

                    Text(app.name)
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontButton)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.top, .spacing3)
                .padding(.bottom, .spacing3)

                Text(app.description ?? "")
                    .font(.omSmall.weight(.medium))
                    .foregroundStyle(Color.fontButton.opacity(0.9))
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, .spacing5)
            .padding(.bottom, .spacing5)
            .frame(width: 223, height: 129, alignment: .topLeading)
            .background(AppIconView.gradient(forAppId: app.id))
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .shadow(color: .black.opacity(0.1), radius: 8, x: 0, y: 2)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("app-card-\(app.id)")
    }

    private var providerBadges: some View {
        HStack(spacing: .spacing3) {
            ForEach(Array(app.providerDisplayNames.prefix(5)), id: \.self) { provider in
                ProviderBadge(name: provider)
                    .opacity(0.4)
            }
        }
    }
}

private struct ProviderBadge: View {
    let name: String

    var body: some View {
        RoundedRectangle(cornerRadius: .radius3)
            .fill(Color.grey0)
            .frame(width: 30, height: 30)
            .overlay(
                Text(initials)
                    .font(.omMicro.weight(.bold))
                    .foregroundStyle(Color.buttonPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            )
            .accessibilityHidden(true)
    }

    private var initials: String {
        let words = name.split(separator: " ")
        let letters = words.prefix(2).compactMap { $0.first }.map(String.init).joined()
        return letters.isEmpty ? String(name.prefix(2)).uppercased() : letters.uppercased()
    }
}

@MainActor
private protocol TitledChoice {
    var title: String { get }
    var accessibilityIdentifier: String { get }
}

@MainActor
private enum SettingsAllAppsFilter: String, CaseIterable, TitledChoice {
    case all
    case settingsMemories
    case focusModes
    case skills

    var title: String {
        switch self {
        case .all: return AppStrings.allAppsFilterAll
        case .settingsMemories: return AppStrings.allAppsFilterSettingsMemories
        case .focusModes: return AppStrings.allAppsFilterFocusModes
        case .skills: return AppStrings.allAppsFilterSkills
        }
    }

    var accessibilityIdentifier: String {
        switch self {
        case .all: return "settings-all-apps-filter-all"
        case .settingsMemories: return "settings-all-apps-filter-settings-memories"
        case .focusModes: return "settings-all-apps-filter-focus-modes"
        case .skills: return "settings-all-apps-filter-skills"
        }
    }

    func matches(_ app: SettingsAppsFullView.AppInfo) -> Bool {
        switch self {
        case .all: return true
        case .settingsMemories: return app.settingsAndMemories?.isEmpty == false
        case .focusModes: return app.focusModes?.isEmpty == false
        case .skills: return app.skills?.isEmpty == false
        }
    }
}

@MainActor
private enum SettingsAllAppsSortMode: String, CaseIterable, TitledChoice {
    case newest
    case nameAsc
    case nameDesc

    var title: String {
        switch self {
        case .newest: return AppStrings.allAppsSortNewest
        case .nameAsc: return AppStrings.allAppsSortName
        case .nameDesc: return AppStrings.allAppsSortNameDesc
        }
    }

    var accessibilityIdentifier: String {
        switch self {
        case .newest: return "settings-all-apps-sort-newest"
        case .nameAsc: return "settings-all-apps-sort-name"
        case .nameDesc: return "settings-all-apps-sort-name-desc"
        }
    }
}

@MainActor
private struct SettingsAllAppsNativeView: View {
    let apps: [SettingsAppsFullView.AppInfo]
    let onSelect: (SettingsAppsFullView.AppInfo) -> Void
    let onBack: () -> Void

    @State private var query = ""
    @State private var filter: SettingsAllAppsFilter = .all
    @State private var sortMode: SettingsAllAppsSortMode = .newest

    private var displayedApps: [SettingsAppsFullView.AppInfo] {
        apps
            .filter(filter.matches)
            .filter { app in
                query.isEmpty
                    || app.name.localizedCaseInsensitiveContains(query)
                    || (app.description?.localizedCaseInsensitiveContains(query) ?? false)
                    || app.providerDisplayNames.contains { $0.localizedCaseInsensitiveContains(query) }
            }
            .sorted { lhs, rhs in
                switch sortMode {
                case .newest:
                    return (lhs.lastUpdated ?? "") > (rhs.lastUpdated ?? "")
                case .nameAsc:
                    return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
                case .nameDesc:
                    return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedDescending
                }
            }
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.showAllApps, showsHeader: false) {
            VStack(alignment: .leading, spacing: .spacing5) {
                Color.clear
                    .frame(height: 0)
                    .accessibilityIdentifier("settings-all-apps-page")

                backButton
                searchField
                filterRow
                sortRow

                LazyVGrid(columns: [GridItem(.adaptive(minimum: 223), spacing: 16)], spacing: 16) {
                    ForEach(displayedApps) { app in
                        AppStoreCardNative(app: app) { onSelect(app) }
                            .accessibilityIdentifier("settings-all-app-row-\(app.id)")
                    }
                }
                .padding(.horizontal, .spacing5)
            }
        }
    }

    private var backButton: some View {
        Button(action: onBack) {
            HStack(spacing: .spacing3) {
                Icon("back", size: 20)
                Text(AppStrings.settingsApps)
                    .font(.omSmall.weight(.semibold))
            }
            .foregroundStyle(Color.buttonPrimary)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing3)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("settings-all-apps-back")
    }

    private var searchField: some View {
        HStack(spacing: .spacing4) {
            HStack(spacing: .spacing3) {
                Icon("search", size: 18)
                    .foregroundStyle(Color.grey50)
                TextField(AppStrings.searchApps, text: $query)
                    .textFieldStyle(.plain)
                    .font(.omP.weight(.medium))
                    .foregroundStyle(Color.fontPrimary)
                    .accessibilityIdentifier("settings-all-apps-search")
            }
            .padding(.leading, 14)
            .padding(.trailing, .spacing5)
            .padding(.vertical, 10)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
        }
        .padding(.horizontal, .spacing5)
    }

    private var filterRow: some View {
        horizontalChoiceRow(SettingsAllAppsFilter.allCases, selected: filter) { selected in
            filter = selected
        }
        .accessibilityIdentifier("settings-all-apps-filters")
    }

    private var sortRow: some View {
        horizontalChoiceRow(SettingsAllAppsSortMode.allCases, selected: sortMode) { selected in
            sortMode = selected
        }
        .accessibilityIdentifier("settings-all-apps-sort")
    }

    private func horizontalChoiceRow<Option: TitledChoice & Equatable>(
        _ options: [Option],
        selected: Option,
        onSelect: @escaping (Option) -> Void
    ) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing3) {
                ForEach(options, id: \.accessibilityIdentifier) { option in
                    Button {
                        onSelect(option)
                    } label: {
                        Text(option.title)
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(option == selected ? Color.fontButton : Color.fontPrimary)
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing2)
                            .background(
                                RoundedRectangle(cornerRadius: .radiusFull)
                                    .fill(option == selected ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.grey0))
                            )
                            .shadow(color: .black.opacity(option == selected ? 0 : 0.1), radius: 4, x: 0, y: 4)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier(option.accessibilityIdentifier)
                }
            }
            .padding(.horizontal, .spacing5)
        }
    }
}

// MARK: - App detail view

struct AppDetailView: View {
    let app: SettingsAppsFullView.AppInfo
    let onOpenExampleChat: (String) -> Void
    let onBack: () -> Void

    @State private var selectedSkill: SettingsAppsFullView.AppSkill?
    @State private var selectedFocusMode: SettingsAppsFullView.AppSkill?
    @State private var selectedMemory: SettingsAppsFullView.AppSkill?
    @State private var selectedContent: SettingsAppsFullView.ContentType?

    var body: some View {
        if let selectedSkill {
            AppSkillDetailNativeView(app: app, skill: selectedSkill, onOpenExampleChat: onOpenExampleChat) {
                withAnimation(.easeOut(duration: 0.2)) {
                    self.selectedSkill = nil
                }
            }
        } else if let selectedFocusMode {
            AppFocusModeDetailNativeView(app: app, focusMode: selectedFocusMode, onOpenExampleChat: onOpenExampleChat) {
                withAnimation(.easeOut(duration: 0.2)) {
                    self.selectedFocusMode = nil
                }
            }
        } else if let selectedMemory {
            AppMemoryDetailNativeView(app: app, memory: selectedMemory) {
                withAnimation(.easeOut(duration: 0.2)) {
                    self.selectedMemory = nil
                }
            }
        } else if let selectedContent {
            AppContentDetailNativeView(
                app: app,
                content: selectedContent,
                onOpenExampleChat: onOpenExampleChat
            ) {
                withAnimation(.easeOut(duration: 0.2)) {
                    self.selectedContent = nil
                }
            }
        } else {
            appDetailBody
        }
    }

    private var appDetailBody: some View {
        OMSettingsPage(title: app.name, showsHeader: false) {
            Color.clear
                .frame(height: 0)
                .accessibilityIdentifier("settings-app-detail-page")

            Button(action: onBack) {
                HStack(spacing: .spacing3) {
                    Icon("back", size: 20)
                    Text(AppStrings.settingsApps)
                        .font(.omSmall.weight(.semibold))
                }
                .foregroundStyle(Color.buttonPrimary)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing3)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("settings-app-detail-back")

            OMSettingsSection {
                VStack(spacing: .spacing4) {
                    AppIconView(appId: app.id, size: 64)
                    Text(app.name)
                        .font(.omH3.weight(.bold))
                        .foregroundStyle(Color.fontPrimary)
                    if let desc = app.description {
                        Text(desc)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontSecondary)
                            .multilineTextAlignment(.center)
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, .spacing8)
                .padding(.horizontal, .spacing5)
            }

            if let skills = app.skills, !skills.isEmpty {
                OMSettingsSection(AppStrings.appStoreSkills, icon: "skill") {
                    ForEach(skills) { skill in
                        detailRow(skill, identifier: "settings-app-skill-row-\(skill.id)") {
                            withAnimation(.easeOut(duration: 0.2)) {
                                selectedSkill = skill
                            }
                        }
                    }
                }
            }

            if let memories = app.settingsAndMemories, !memories.isEmpty {
                OMSettingsSection(AppStrings.appStoreMemories, icon: "settings") {
                    ForEach(memories) { memory in
                        detailRow(memory, identifier: "settings-app-memory-row-\(memory.id)") {
                            withAnimation(.easeOut(duration: 0.2)) {
                                selectedMemory = memory
                            }
                        }
                    }
                }
            }

            if !app.contentTypes.isEmpty {
                OMSettingsSection(AppStrings.localized("settings.app_store.content.title"), icon: "embed") {
                    ForEach(app.contentTypes) { content in
                        Button {
                            withAnimation(.easeOut(duration: 0.2)) {
                                selectedContent = content
                            }
                        } label: {
                            HStack(spacing: .spacing4) {
                                Icon(content.icon ?? "embed", size: 20)
                                    .foregroundStyle(Color.buttonPrimary)
                                VStack(alignment: .leading, spacing: .spacing1) {
                                    Text(content.name)
                                        .font(.omP.weight(.medium))
                                        .foregroundStyle(Color.fontPrimary)
                                    Text(content.description)
                                        .font(.omXs)
                                        .foregroundStyle(Color.fontSecondary)
                                        .lineLimit(2)
                                }
                                Spacer()
                            }
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing3)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("settings-app-content-row-\(content.contentTypeId)")
                    }
                }
            }

            if let focusModes = app.focusModes, !focusModes.isEmpty {
                OMSettingsSection(AppStrings.appStoreFocusModes, icon: "focus") {
                    ForEach(focusModes) { focus in
                        detailRow(focus, identifier: "settings-app-focus-row-\(focus.id)") {
                            withAnimation(.easeOut(duration: 0.2)) {
                                selectedFocusMode = focus
                            }
                        }
                    }
                }
            }
        }
    }

    private func detailRow(
        _ item: SettingsAppsFullView.AppSkill,
        identifier: String,
        onTap: @escaping () -> Void
    ) -> some View {
        Button(action: onTap) {
            HStack(spacing: .spacing4) {
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(item.name)
                        .font(.omP.weight(.medium))
                        .foregroundStyle(Color.fontPrimary)
                    if let desc = item.description {
                        Text(desc)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
                Spacer()
            }
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing3)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }
}

private struct AppMemoryDetailNativeView: View {
    let app: SettingsAppsFullView.AppInfo
    let memory: SettingsAppsFullView.AppSkill
    let onBack: () -> Void

    var body: some View {
        OMSettingsPage(title: memory.name, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-memory-detail-page")
            appsDetailBackButton(title: app.name, identifier: "settings-memory-detail-back", action: onBack)
            OMSettingsSection(AppStrings.localized("settings.app_store.settings_memories.title"), icon: "settings") {
                appsDetailText(memory.description ?? "")
                if let valueType = memory.valueType, !valueType.isEmpty {
                    appsDetailPill(valueType)
                }
            }
        }
    }
}

private struct AppContentDetailNativeView: View {
    let app: SettingsAppsFullView.AppInfo
    let content: SettingsAppsFullView.ContentType
    let onOpenExampleChat: (String) -> Void
    let onBack: () -> Void

    var body: some View {
        OMSettingsPage(title: content.name, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-content-detail-page")
            appsDetailBackButton(title: app.name, identifier: "settings-content-detail-back", action: onBack)
            OMSettingsSection(content.name, icon: content.icon ?? "embed") {
                appsDetailText(content.description)
                HStack(spacing: .spacing2) {
                    appsDetailPill(content.frontendType)
                    if let skillId = content.skillId {
                        appsDetailPill("\(app.id).\(skillId)")
                    }
                }
                .padding(.horizontal, .spacing5)
                .padding(.bottom, .spacing3)
            }
            if let chatIds = exampleChatIds(appId: app.id, itemId: content.contentTypeId, kind: .content),
               !chatIds.isEmpty {
                OMSettingsSection(AppStrings.appStoreExamples, icon: "chat") {
                    horizontalTextCards(
                        chatIds.map { _ in content.name },
                        identifierPrefix: "settings-content-example-card",
                        chatIds: chatIds,
                        onOpenExampleChat: onOpenExampleChat
                    )
                }
            }
        }
    }
}

private struct AppProviderDetailNativeView: View {
    let app: SettingsAppsFullView.AppInfo
    let provider: SettingsAppsFullView.ProviderDetail
    let onBack: () -> Void

    var body: some View {
        OMSettingsPage(title: provider.name, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-provider-detail-page")
            appsDetailBackButton(title: app.name, identifier: "settings-provider-detail-back", action: onBack)
            OMSettingsSection(AppStrings.appStoreProviders, icon: "provider") {
                appsDetailText(provider.description ?? "")
                if let country = provider.country, !country.isEmpty {
                    appsDetailPill(country)
                }
            }
        }
    }
}

private struct AppModelDetailNativeView: View {
    let app: SettingsAppsFullView.AppInfo
    let model: SettingsAppsFullView.ModelDetail
    let onBack: () -> Void

    var body: some View {
        OMSettingsPage(title: model.name, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-model-detail-page")
            appsDetailBackButton(title: app.name, identifier: "settings-model-detail-back", action: onBack)
            OMSettingsSection(AppStrings.appStoreModels, icon: "skill") {
                appsDetailText(model.description ?? "")
                appsDetailPill(model.providerName)
            }
            if let pricing = model.pricing, !pricing.isEmpty {
                OMSettingsSection(AppStrings.pricing, icon: "coins") {
                    appsDetailText(formatPricing(pricing))
                }
            }
        }
    }
}

private struct AppSkillDetailNativeView: View {
    let app: SettingsAppsFullView.AppInfo
    let skill: SettingsAppsFullView.AppSkill
    let onOpenExampleChat: (String) -> Void
    let onBack: () -> Void

    @State private var mentionInserted = false
    @State private var selectedProvider: SettingsAppsFullView.ProviderDetail?
    @State private var selectedModel: SettingsAppsFullView.ModelDetail?

    var body: some View {
        if let selectedProvider {
            AppProviderDetailNativeView(app: app, provider: selectedProvider) {
                self.selectedProvider = nil
            }
        } else if let selectedModel {
            AppModelDetailNativeView(app: app, model: selectedModel) {
                self.selectedModel = nil
            }
        } else {
            skillBody
        }
    }

    private var skillBody: some View {
        OMSettingsPage(title: skill.name, showsHeader: false) {
            Color.clear
                .frame(height: 0)
                .accessibilityIdentifier("settings-skill-detail-page")

            backButton

            OMSettingsSection(AppStrings.pricing, icon: "coins") {
                Color.clear
                    .frame(height: 0)
                    .accessibilityIdentifier("settings-skill-pricing-section")

                Text(pricingText)
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing3)
                    .accessibilityIdentifier("settings-skill-pricing-value")
            }

            let skillChatIds = skill.exampleChatIds ?? exampleChatIds(appId: app.id, itemId: skill.id, kind: .skill)
            if let skillChatIds, !skillChatIds.isEmpty {
                let examples = skill.exampleTitles ?? skillChatIds.map { _ in skill.name }
                OMSettingsSection(AppStrings.appStoreExamples, icon: "skill") {
                    horizontalTextCards(
                        examples,
                        identifierPrefix: "settings-skill-example-card",
                        chatIds: skillChatIds,
                        onOpenExampleChat: onOpenExampleChat
                    )
                }
            }

            if let howToUse = skill.howToUseExamples, !howToUse.isEmpty {
                OMSettingsSection(AppStrings.appStoreHowToUse, icon: "skill") {
                    horizontalTextCards(howToUse, identifierPrefix: "settings-skill-how-to-use-card")
                    mentionButton(title: "@\(mentionDisplayName)", identifier: "settings-skill-mention-button") {
                        mentionInserted = true
                        openComposerWithMention(kind: .skill)
                    }
                }
            }

            if let providers = skill.providerDetails, !providers.isEmpty {
                OMSettingsSection(AppStrings.appStoreProviders, icon: "provider") {
                    ForEach(providers) { provider in
                        Button {
                            selectedProvider = provider
                        } label: {
                            providerRow(provider.name)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("settings-skill-provider-item")
                    }
                }
            }

            if let models = skill.models, !models.isEmpty {
                OMSettingsSection(AppStrings.appStoreModels, icon: "skill") {
                    ForEach(models) { model in
                        Button {
                            selectedModel = model
                        } label: {
                            HStack(spacing: .spacing4) {
                                VStack(alignment: .leading, spacing: .spacing1) {
                                    Text(model.name)
                                        .font(.omP.weight(.medium))
                                        .foregroundStyle(Color.fontPrimary)
                                    Text(model.providerName)
                                        .font(.omXs)
                                        .foregroundStyle(Color.fontSecondary)
                                }
                                Spacer()
                            }
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing3)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("settings-skill-model-item")
                    }
                }
            }

            if mentionInserted {
                Text("@\(mentionDisplayName)")
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.buttonPrimary)
                    .padding(.horizontal, .spacing5)
                    .accessibilityIdentifier("settings-skill-mention-inserted")
            }
        }
    }

    private var backButton: some View {
        Button(action: onBack) {
            HStack(spacing: .spacing3) {
                Icon("back", size: 20)
                Text(app.name)
                    .font(.omSmall.weight(.semibold))
            }
            .foregroundStyle(Color.buttonPrimary)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing3)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("settings-skill-detail-back")
    }

    private var pricingText: String {
        guard let pricing = skill.pricing else { return "1 \(AppStrings.credits)" }
        return formatPricing(pricing)
    }

    private var mentionDisplayName: String {
        "\(titleCase(app.id))-\(titleCase(skill.id.replacingOccurrences(of: "_", with: "-")))"
    }

    private func openComposerWithMention(kind: SettingsAppsFullView.MentionKind) {
        let syntax = SettingsAppsFullView.mentionSyntax(appId: app.id, itemId: skill.id, kind: kind)
        Task {
            do {
                try await DraftService.shared.saveDraft(
                    canonicalMarkdown: syntax,
                    preview: syntax,
                    chatId: SettingsAppsFullView.newChatDraftID,
                    revision: 1,
                    draftVersion: 0
                )
                NotificationCenter.default.post(name: .newChat, object: nil)
            } catch {
                NativeDiagnostics.warning(
                    "Apps skill mention insertion failed errorType=\(type(of: error))",
                    category: "settings_apps"
                )
            }
        }
    }

    private func providerRow(_ provider: String) -> some View {
        HStack(spacing: .spacing4) {
            Circle()
                .fill(Color.grey20)
                .frame(width: 28, height: 28)
                .overlay(Icon("provider", size: 16).foregroundStyle(Color.fontSecondary))
                .accessibilityHidden(true)
            Text(provider)
                .font(.omP.weight(.medium))
                .foregroundStyle(Color.fontPrimary)
            Spacer()
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing3)
    }
}

private struct AppFocusModeDetailNativeView: View {
    let app: SettingsAppsFullView.AppInfo
    let focusMode: SettingsAppsFullView.AppSkill
    let onOpenExampleChat: (String) -> Void
    let onBack: () -> Void

    @State private var showFullPrompt = false
    @State private var mentionInserted = false

    var body: some View {
        OMSettingsPage(title: focusMode.name, showsHeader: false) {
            Color.clear
                .frame(height: 0)
                .accessibilityIdentifier("settings-focus-detail-page")

            backButton

            let focusChatIds = focusMode.exampleChatIds ?? exampleChatIds(appId: app.id, itemId: focusMode.id, kind: .focus)
            if let focusChatIds, !focusChatIds.isEmpty {
                let examples = focusMode.exampleTitles ?? focusChatIds.map { _ in focusMode.name }
                OMSettingsSection(AppStrings.appStoreExamples, icon: "skill") {
                    horizontalTextCards(
                        examples,
                        identifierPrefix: "settings-focus-example-card",
                        chatIds: focusChatIds,
                        onOpenExampleChat: onOpenExampleChat
                    )
                }
            }

            if let howToUse = focusMode.howToUseExamples, !howToUse.isEmpty {
                OMSettingsSection(AppStrings.appStoreHowToUse, icon: "skill") {
                    horizontalTextCards(howToUse, identifierPrefix: "settings-focus-how-to-use-card")
                    mentionButton(title: "@\(mentionDisplayName)", identifier: "settings-focus-mention-button") {
                        mentionInserted = true
                        openComposerWithMention()
                    }
                }
            }

            OMSettingsSection(AppStrings.appStoreSystemPrompt, icon: "systemprompt") {
                if let bullets = focusMode.processBullets, !bullets.isEmpty {
                    VStack(alignment: .leading, spacing: .spacing2) {
                        ForEach(bullets, id: \.self) { bullet in
                            Text("- \(bullet)")
                                .font(.omSmall)
                                .foregroundStyle(Color.fontPrimary)
                                .accessibilityIdentifier("settings-focus-process-bullet")
                        }
                    }
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing3)
                }

                if focusMode.systemPrompt?.isEmpty == false {
                    Button {
                        withAnimation(.easeOut(duration: 0.2)) {
                            showFullPrompt.toggle()
                        }
                    } label: {
                        Text(showFullPrompt ? AppStrings.showLess : AppStrings.appStoreShowFullInstruction)
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color.buttonPrimary)
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing3)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("settings-focus-instructions-toggle")

                    if showFullPrompt, let prompt = focusMode.systemPrompt {
                        Text(prompt)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                            .padding(.horizontal, .spacing5)
                            .padding(.bottom, .spacing3)
                            .accessibilityIdentifier("settings-focus-instructions-text")
                    }
                }
            }

            if mentionInserted {
                Text("@\(mentionDisplayName)")
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.buttonPrimary)
                    .padding(.horizontal, .spacing5)
                    .accessibilityIdentifier("settings-focus-mention-inserted")
            }
        }
    }

    private var backButton: some View {
        Button(action: onBack) {
            HStack(spacing: .spacing3) {
                Icon("back", size: 20)
                Text(app.name)
                    .font(.omSmall.weight(.semibold))
            }
            .foregroundStyle(Color.buttonPrimary)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing3)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("settings-focus-detail-back")
    }

    private var mentionDisplayName: String {
        "\(titleCase(app.id))-\(titleCase(focusMode.id.replacingOccurrences(of: "_", with: "-")))"
    }

    private func openComposerWithMention() {
        let syntax = SettingsAppsFullView.mentionSyntax(
            appId: app.id,
            itemId: focusMode.id,
            kind: .focus
        )
        Task {
            do {
                try await DraftService.shared.saveDraft(
                    canonicalMarkdown: syntax,
                    preview: syntax,
                    chatId: SettingsAppsFullView.newChatDraftID,
                    revision: 1,
                    draftVersion: 0
                )
                NotificationCenter.default.post(name: .newChat, object: nil)
            } catch {
                NativeDiagnostics.warning(
                    "Apps focus mention insertion failed errorType=\(type(of: error))",
                    category: "settings_apps"
                )
            }
        }
    }
}

@MainActor
private func horizontalTextCards(
    _ values: [String],
    identifierPrefix: String,
    chatIds: [String]? = nil,
    onOpenExampleChat: ((String) -> Void)? = nil
) -> some View {
    ScrollView(.horizontal, showsIndicators: false) {
        HStack(spacing: .spacing4) {
            ForEach(Array(values.enumerated()), id: \.offset) { index, value in
                let chatId = chatIds?.indices.contains(index) == true ? chatIds?[index] : nil
                if let chatId, let onOpenExampleChat {
                    Button {
                        onOpenExampleChat(chatId)
                    } label: {
                        textCard(value)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("\(identifierPrefix)-\(index)")
                } else {
                    textCard(value)
                        .accessibilityIdentifier("\(identifierPrefix)-\(index)")
                }
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.bottom, .spacing3)
    }
}

@MainActor
private func textCard(_ value: String) -> some View {
    Text(value)
        .font(.omSmall.weight(.semibold))
        .foregroundStyle(Color.fontPrimary)
        .frame(width: 230, alignment: .leading)
        .padding(.spacing5)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
}

private enum AppStoreExampleKind {
    case skill
    case focus
    case content
}

private func exampleChatIds(appId: String, itemId: String, kind: AppStoreExampleKind) -> [String]? {
    let key = "\(appId).\(itemId)"
    let mapping: [String: [String]]
    switch kind {
    case .skill:
        mapping = [
            "images.search": ["example-gigantic-airplanes", "example-artemis-ii-mission"],
            "travel.search_connections": ["example-flights-berlin-bangkok"],
            "web.search": ["example-eu-chat-control-law"],
        ]
    case .focus:
        mapping = [:]
    case .content:
        mapping = [
            "web.website": ["example-eu-chat-control-law"],
        ]
    }
    return mapping[key]
}

private func uniqueStrings(_ values: [String]) -> [String] {
    Array(NSOrderedSet(array: values)).compactMap { $0 as? String }
}

@MainActor
private func mentionButton(title: String, identifier: String, action: @escaping () -> Void) -> some View {
    Button(action: action) {
        Text(title)
            .font(.omSmall.weight(.semibold))
            .foregroundStyle(Color.buttonPrimary)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing3)
    }
    .buttonStyle(.plain)
    .accessibilityIdentifier(identifier)
}

private func titleCase(_ value: String) -> String {
    value.split(separator: "-")
        .map { part in
            guard let first = part.first else { return String(part) }
            return first.uppercased() + String(part.dropFirst())
        }
        .joined(separator: "-")
}

@MainActor
private func appsDetailBackButton(
    title: String,
    identifier: String,
    action: @escaping () -> Void
) -> some View {
    Button(action: action) {
        HStack(spacing: .spacing3) {
            Icon("back", size: 20)
            Text(title).font(.omSmall.weight(.semibold))
        }
        .foregroundStyle(Color.buttonPrimary)
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing3)
    }
    .buttonStyle(.plain)
    .accessibilityIdentifier(identifier)
}

@MainActor
private func appsDetailText(_ value: String) -> some View {
    Text(value)
        .font(.omP)
        .foregroundStyle(Color.fontPrimary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing3)
}

@MainActor
private func appsDetailPill(_ value: String) -> some View {
    Text(value)
        .font(.omXs.weight(.medium))
        .foregroundStyle(Color.fontSecondary)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        .padding(.horizontal, .spacing5)
        .padding(.bottom, .spacing3)
}

@MainActor
private func formatPricing(_ pricing: [String: AnyCodable]) -> String {
    if let fixed = pricing["fixed"]?.value as? Int {
        return "\(fixed) \(AppStrings.credits)"
    }
    if let perUnit = pricing["per_unit"]?.value as? [String: Any],
       let credits = perUnit["credits"] {
        return "\(credits) \(AppStrings.credits)"
    }
    if let perMinute = pricing["per_minute"]?.value as? Int {
        return "\(perMinute) \(AppStrings.credits)"
    }
    if let perSecond = pricing["per_second"]?.value as? Int {
        return "\(perSecond) \(AppStrings.credits)"
    }
    return AppStrings.credits
}
