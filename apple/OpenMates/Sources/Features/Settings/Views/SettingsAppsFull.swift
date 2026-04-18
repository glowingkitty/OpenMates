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
    @State private var showDetail = false

    struct AppInfo: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        let category: String?
        var isInstalled: Bool?
        let iconName: String?
        let skills: [AppSkill]?
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
        Array(Set(apps.compactMap(\.category))).sorted()
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if apps.isEmpty {
                Section {
                    Text(AppStrings.noAppsAvailable)
                        .foregroundStyle(Color.fontSecondary)
                }
            } else {
                ForEach(categories, id: \.self) { category in
                    Section(category.capitalized) {
                        ForEach(filteredApps.filter { $0.category == category }) { app in
                            AppRow(
                                app: app,
                                onToggle: { toggleApp(app) },
                                onTap: {
                                    selectedApp = app
                                    showDetail = true
                                }
                            )
                        }
                    }
                }

                let uncategorized = filteredApps.filter { $0.category == nil }
                if !uncategorized.isEmpty {
                    Section(LocalizationManager.shared.text("settings.app_store.categories.other")) {
                        ForEach(uncategorized) { app in
                            AppRow(
                                app: app,
                                onToggle: { toggleApp(app) },
                                onTap: {
                                    selectedApp = app
                                    showDetail = true
                                }
                            )
                        }
                    }
                }
            }
        }
        .searchable(text: $searchText, prompt: AppStrings.searchApps)
        .navigationTitle(AppStrings.settingsApps)
        .task { await loadApps() }
        .sheet(isPresented: $showDetail) {
            if let app = selectedApp {
                AppDetailView(app: app, onToggle: {
                    toggleApp(app)
                })
            }
        }
    }

    private func loadApps() async {
        do {
            apps = try await APIClient.shared.request(.get, path: "/v1/apps")
        } catch {
            print("[Settings] Failed to load apps: \(error)")
        }
        isLoading = false
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

// MARK: - App detail view

struct AppDetailView: View {
    let app: SettingsAppsFullView.AppInfo
    let onToggle: () -> Void
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            List {
                // App header
                Section {
                    VStack(spacing: .spacing4) {
                        AppIconView(appId: app.id, size: 64)
                        Text(app.name)
                            .font(.omH3).fontWeight(.bold)
                        if let desc = app.description {
                            Text(desc)
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                                .multilineTextAlignment(.center)
                        }
                        if let category = app.category {
                            Text(category.capitalized)
                                .font(.omXs).foregroundStyle(Color.fontTertiary)
                                .padding(.horizontal, .spacing3)
                                .padding(.vertical, .spacing1)
                                .background(Color.grey10)
                                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                        }

                        Button {
                            onToggle()
                            dismiss()
                        } label: {
                            Text(app.isInstalled == true ? AppStrings.remove : AppStrings.add)
                                .font(.omSmall).fontWeight(.medium)
                                .foregroundStyle(.white)
                                .padding(.horizontal, .spacing6)
                                .padding(.vertical, .spacing3)
                                .background(app.isInstalled == true ? Color.error : Color.buttonPrimary)
                                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                        }
                        .buttonStyle(.plain)
                        .accessibleButton(
                            app.isInstalled == true ? AppStrings.remove : AppStrings.add,
                            hint: app.isInstalled == true
                                ? LocalizationManager.shared.text("settings.app_store.remove_hint")
                                : LocalizationManager.shared.text("settings.app_store.add_hint")
                        )
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, .spacing4)
                }

                // Skills
                if let skills = app.skills, !skills.isEmpty {
                    Section(LocalizationManager.shared.text("settings.app_store.skills")) {
                        ForEach(skills) { skill in
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(skill.name)
                                    .font(.omSmall).fontWeight(.medium)
                                if let desc = skill.description {
                                    Text(desc)
                                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle(app.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppStrings.done) { dismiss() }
                }
            }
        }
    }
}
