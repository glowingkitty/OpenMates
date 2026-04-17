// App store settings — browse, enable, and configure apps.
// Mirrors the web app's SettingsAppStore.svelte.

import SwiftUI

struct SettingsAppsFullView: View {
    @State private var apps: [AppInfo] = []
    @State private var isLoading = true
    @State private var searchText = ""

    struct AppInfo: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        let category: String?
        let isInstalled: Bool?
        let iconName: String?
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
            } else {
                ForEach(categories, id: \.self) { category in
                    Section(category.capitalized) {
                        ForEach(filteredApps.filter { $0.category == category }) { app in
                            AppRow(app: app, onToggle: { toggleApp(app) })
                        }
                    }
                }

                let uncategorized = filteredApps.filter { $0.category == nil }
                if !uncategorized.isEmpty {
                    Section("Other") {
                        ForEach(uncategorized) { app in
                            AppRow(app: app, onToggle: { toggleApp(app) })
                        }
                    }
                }
            }
        }
        .searchable(text: $searchText, prompt: "Search apps")
        .navigationTitle("Apps")
        .task { await loadApps() }
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

struct AppRow: View {
    let app: SettingsAppsFullView.AppInfo
    let onToggle: () -> Void

    var body: some View {
        HStack(spacing: .spacing4) {
            AppIconView(appId: app.id, size: 36)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(app.name)
                    .font(.omSmall).fontWeight(.medium)
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
                Text(app.isInstalled == true ? "Installed" : "Add")
                    .font(.omXs).fontWeight(.medium)
                    .foregroundStyle(app.isInstalled == true ? Color.fontTertiary : Color.buttonPrimary)
                    .padding(.horizontal, .spacing3)
                    .padding(.vertical, .spacing1)
                    .background(app.isInstalled == true ? Color.grey20 : Color.buttonPrimary.opacity(0.1))
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }
            .buttonStyle(.plain)
        }
    }
}
