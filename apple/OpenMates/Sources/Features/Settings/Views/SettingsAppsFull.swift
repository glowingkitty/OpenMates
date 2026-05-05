// App store settings — browse, enable, and configure apps with category sections.
// Mirrors the web app's SettingsAppStore.svelte with categorized browsing,
// install/uninstall toggles, and app detail navigation.
// All strings use AppStrings (i18n).

import SwiftUI

struct SettingsAppsFullView: View {
    @State private var apps: [AppInfo] = []
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var selectedApp: AppInfo?

    struct AppInfo: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        var category: String?
        var isInstalled: Bool?
        let iconName: String?
        let skills: [AppSkill]?
        var focusModes: [AppSkill]?
        var settingsAndMemories: [AppSkill]?
    }

    struct AppSkill: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
    }

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
                        OMSettingsSection {
                            OMSettingsRow(title: AppStrings.showAllApps, icon: "app_store") {}
                        }

                        ForEach(categories, id: \.self) { category in
                            let categoryApps = filteredApps.filter { ($0.category ?? "apps") == category }
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
                            }
                        }
                    }
                }
            }
        }
        .task { await loadApps() }
    }

    private func loadApps() async {
        do {
            let response: AppsMetadataResponse = try await APIClient.shared.request(
                .get,
                path: "/v1/apps/metadata?include_unavailable=true"
            )
            apps = response.apps.values
                .map { app in
                    AppInfo(
                        id: app.id,
                        name: app.name,
                        description: app.description,
                        category: Self.category(for: app.id),
                        isInstalled: nil,
                        iconName: nil,
                        skills: app.skills,
                        focusModes: app.focusModes,
                        settingsAndMemories: app.settingsAndMemories
                    )
                }
                .filter { $0.id != "ai" }
                .sorted { $0.name < $1.name }
        } catch {
            print("[Settings] Failed to load apps: \(error)")
        }
        isLoading = false
    }

    private struct AppsMetadataResponse: Decodable {
        let apps: [String: AppMetadataItem]
    }

    private struct AppMetadataItem: Decodable {
        let id: String
        let name: String
        let description: String?
        let skills: [AppSkill]
        let focusModes: [AppSkill]
        let settingsAndMemories: [AppSkill]
    }

    private static func category(for appId: String) -> String {
        switch appId {
        case "docs", "sheets", "slides", "pdf", "notes", "code": return "explore"
        case "web", "videos", "images", "maps", "news": return "most_used"
        case "travel", "shopping", "events", "health", "nutrition": return "daily_life"
        default: return "apps"
        }
    }

    private func categoryTitle(_ category: String) -> String {
        switch category {
        case "explore": return LocalizationManager.shared.text("settings.app_store.categories.explore_discover")
        case "most_used": return LocalizationManager.shared.text("settings.app_store.categories.most_used")
        case "daily_life": return LocalizationManager.shared.text("settings.app_store.categories.for_everyday_life")
        default: return AppStrings.apps
        }
    }

    private func categoryIcon(_ category: String) -> String {
        switch category {
        case "explore": return "search"
        case "most_used": return "heart"
        case "daily_life": return "calendar"
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
    }
}

// MARK: - App detail view

struct AppDetailView: View {
    let app: SettingsAppsFullView.AppInfo
    let onToggle: () -> Void
    let onBack: () -> Void

    var body: some View {
        OMSettingsPage(title: app.name, showsHeader: false) {
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
                OMSettingsSection(LocalizationManager.shared.text("settings.app_store.skills"), icon: "skill") {
                    ForEach(skills) { skill in
                        skillRow(skill)
                    }
                }
            }

            if let focusModes = app.focusModes, !focusModes.isEmpty {
                OMSettingsSection(LocalizationManager.shared.text("settings.app_store.focus_modes"), icon: "focus") {
                    ForEach(focusModes) { focus in
                        skillRow(focus)
                    }
                }
            }
        }
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
