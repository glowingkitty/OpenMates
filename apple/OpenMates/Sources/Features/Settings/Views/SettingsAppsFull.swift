// App store settings — browse, enable, and configure apps with category sections.
// Mirrors the web app's SettingsAppStore.svelte with categorized browsing,
// install/uninstall toggles, and app detail navigation.
// All strings use AppStrings (i18n).

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsAppStore.svelte
//          frontend/packages/ui/src/components/settings/SettingsAllApps.svelte
//          frontend/packages/ui/src/components/settings/AppDetails.svelte
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

    struct AppInfo: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        var category: String?
        var isInstalled: Bool?
        let iconName: String?
        let providers: [String]?
        let lastUpdated: String?
        let skills: [AppSkill]?
        var focusModes: [AppSkill]?
        var settingsAndMemories: [AppSkill]?
    }

    struct AppSkill: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        let pricing: [String: AnyCodable]?
        let providers: [String]?

        enum CodingKeys: String, CodingKey {
            case id
            case name
            case description
            case pricing
            case providers
        }

        init(
            id: String,
            name: String,
            description: String?,
            pricing: [String: AnyCodable]? = nil,
            providers: [String]? = nil
        ) {
            self.id = id
            self.name = name
            self.description = description
            self.pricing = pricing
            self.providers = providers
        }
    }

    static let appStoreExcludedAppIDs: Set<String> = ["ai"]

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

    static let allAppsSortKeys: [String] = ["newest", "name"]

    private var filteredApps: [AppInfo] {
        guard !searchText.isEmpty else { return apps }
        return apps.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            ($0.description?.localizedCaseInsensitiveContains(searchText) ?? false)
        }
    }

    private var categories: [String] {
        Array(Set(filteredApps.map { $0.category ?? "apps" })).sorted()
    }

    var body: some View {
        Group {
            if let selectedApp {
                AppDetailView(app: selectedApp, onToggle: {
                    toggleApp(selectedApp)
                }) {
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
                            OMSettingsRow(title: AppStrings.showAllApps, icon: "app_store") {
                                withAnimation(.easeOut(duration: 0.2)) {
                                    isShowingAllApps = true
                                }
                            }
                            .accessibilityIdentifier("settings-show-all-apps-row")

                            appStoreCategories
                        }
                        .accessibilityIdentifier("settings-app-store-page")
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
            print("[Settings] Failed to load apps: \(error)")
        }
        isLoading = false
    }

    private var appStoreCategories: some View {
        ForEach(categories, id: \.self) { category in
            let categoryApps = filteredApps.filter { ($0.category ?? "top_picks") == category }
            OMSettingsSection(categoryTitle(category), icon: categoryIcon(category)) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: .spacing6) {
                        ForEach(categoryApps) { app in
                            AppStoreCardNative(app: app) {
                                withAnimation(.easeOut(duration: 0.2)) {
                                    selectedApp = app
                                }
                            }
                        }
                    }
                    .padding(.horizontal, .spacing5)
                    .padding(.bottom, .spacing4)
                }
                .accessibilityIdentifier("settings-app-category-\(category)-scroll")
            }
        }
    }

    struct AppsMetadataResponse: Decodable {
        let apps: [String: AppMetadataItem]
    }

    struct AppMetadataItem: Decodable {
        let id: String
        let name: String
        let description: String?
        let category: String?
        let providers: [String]?
        let lastUpdated: String?
        let skills: [AppSkill]
        let focusModes: [AppSkill]
        let settingsAndMemories: [AppSkill]

        enum CodingKeys: String, CodingKey {
            case id
            case name
            case description
            case category
            case providers
            case lastUpdated = "last_updated"
            case skills
            case focusModes = "focus_modes"
            case settingsAndMemories = "settings_and_memories"
        }
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
            isInstalled: nil,
            iconName: nil,
            providers: app.providers,
            lastUpdated: app.lastUpdated,
            skills: app.skills,
            focusModes: app.focusModes,
            settingsAndMemories: app.settingsAndMemories
        )
    }

    private static let uiTestApps: [AppInfo] = [
        appInfo(from: AppMetadataItem(
            id: "weather",
            name: "Weather",
            description: "Forecasts and weather alerts",
            category: "personal",
            providers: ["OpenWeather"],
            lastUpdated: "2026-05-01",
            skills: [AppSkill(id: "forecast", name: "Weather Forecast", description: "Get a forecast")],
            focusModes: [AppSkill(id: "travel_weather", name: "Travel Weather", description: "Plan around weather")],
            settingsAndMemories: [AppSkill(id: "home_location", name: "Home Location", description: "Remember a location")]
        )),
        appInfo(from: AppMetadataItem(
            id: "docs",
            name: "Docs",
            description: "Document work",
            category: "work",
            providers: [],
            lastUpdated: "2026-03-01",
            skills: [AppSkill(id: "summarize", name: "Summarize", description: "Summarize documents")],
            focusModes: [],
            settingsAndMemories: []
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

    private func toggleApp(_ app: AppInfo) {
        Task {
            let enabled = !(app.isInstalled ?? false)
            try? await APIClient.shared.request(
                .post, path: "/v1/apps/\(app.id)/toggle",
                body: ["enabled": enabled]
            ) as Data
            await loadApps()
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
            VStack(alignment: .leading, spacing: .spacing5) {
                AppIconView(appId: app.id, size: 44)

                Text(app.name)
                    .font(.omH4.weight(.bold))
                    .foregroundStyle(Color.fontButton)
                    .lineLimit(1)

                if let description = app.description {
                    Text(description)
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontButton)
                        .lineLimit(3)
                        .multilineTextAlignment(.leading)
                }
            }
            .padding(.spacing8)
            .frame(width: 210, height: 150, alignment: .topLeading)
            .background(AppIconView.gradient(forAppId: app.id))
            .clipShape(RoundedRectangle(cornerRadius: .radius6))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("app-card-\(app.id)")
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
    case name

    var title: String {
        switch self {
        case .newest: return AppStrings.allAppsSortNewest
        case .name: return AppStrings.allAppsSortName
        }
    }

    var accessibilityIdentifier: String {
        switch self {
        case .newest: return "settings-all-apps-sort-newest"
        case .name: return "settings-all-apps-sort-name"
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
            }
            .sorted { lhs, rhs in
                switch sortMode {
                case .newest:
                    return (lhs.lastUpdated ?? "") > (rhs.lastUpdated ?? "")
                case .name:
                    return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
                }
            }
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.showAllApps, showsHeader: false) {
            VStack(alignment: .leading, spacing: .spacing5) {
                backButton
                searchField
                filterRow
                sortRow

                OMSettingsSection {
                    ForEach(displayedApps) { app in
                        AppRow(app: app, onToggle: {}, onTap: { onSelect(app) })
                            .accessibilityIdentifier("settings-all-app-row-\(app.id)")
                    }
                }
            }
            .accessibilityIdentifier("settings-all-apps-page")
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
        TextField(AppStrings.searchApps, text: $query)
            .textFieldStyle(.plain)
            .font(.omP)
            .foregroundStyle(Color.fontPrimary)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing4)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .padding(.horizontal, .spacing5)
            .accessibilityIdentifier("settings-all-apps-search")
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
                            .background(option == selected ? Color.buttonPrimary : Color.grey0)
                            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
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
    let onToggle: () -> Void
    let onBack: () -> Void

    var body: some View {
        OMSettingsPage(title: app.name, showsHeader: false) {
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
                        skillRow(skill)
                    }
                }
            }

            if let focusModes = app.focusModes, !focusModes.isEmpty {
                OMSettingsSection(AppStrings.appStoreFocusModes, icon: "focus") {
                    ForEach(focusModes) { focus in
                        skillRow(focus)
                    }
                }
            }
        }
        .accessibilityIdentifier("settings-app-detail-page")
    }

    private func skillRow(_ item: SettingsAppsFullView.AppSkill) -> some View {
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
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing3)
    }
}
