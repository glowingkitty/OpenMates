// Memories hub — view and manage AI memories across all apps.
// Mirrors the web app's SettingsMemoriesHub.svelte.

import SwiftUI

struct SettingsMemoriesFullView: View {
    @State private var memoryGroups: [MemoryGroup] = []
    @State private var isLoading = true
    @State private var selectedGroup: MemoryGroup?
    @State private var showDetail = false

    struct MemoryGroup: Identifiable, Decodable {
        let id: String
        let appId: String
        let appName: String
        let category: String
        let entryCount: Int
        let lastUpdated: String?
    }

    struct MemoryEntry: Identifiable, Decodable {
        let id: String
        let key: String
        let value: String
        let createdAt: String?
        let updatedAt: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if memoryGroups.isEmpty {
                Section {
                    VStack(spacing: .spacing4) {
                        Image(systemName: "brain.head.profile")
                            .font(.system(size: 36))
                            .foregroundStyle(Color.fontTertiary)
                        Text("No memories yet")
                            .font(.omP).foregroundStyle(Color.fontSecondary)
                        Text("As you chat, the AI will remember important details about you.")
                            .font(.omXs).foregroundStyle(Color.fontTertiary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, .spacing8)
                }
            } else {
                let appIds = Array(Set(memoryGroups.map(\.appId))).sorted()
                ForEach(appIds, id: \.self) { appId in
                    Section {
                        let groups = memoryGroups.filter { $0.appId == appId }
                        ForEach(groups) { group in
                            Button {
                                selectedGroup = group
                                showDetail = true
                            } label: {
                                HStack {
                                    AppIconView(appId: appId, size: 28)
                                    VStack(alignment: .leading, spacing: .spacing1) {
                                        Text(group.category)
                                            .font(.omSmall).fontWeight(.medium)
                                            .foregroundStyle(Color.fontPrimary)
                                        Text("\(group.entryCount) entries")
                                            .font(.omXs).foregroundStyle(Color.fontTertiary)
                                    }
                                    Spacer()
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundStyle(Color.fontTertiary)
                                }
                            }
                        }
                    } header: {
                        Text(memoryGroups.first(where: { $0.appId == appId })?.appName ?? appId)
                    }
                }
            }
        }
        .navigationTitle("Memories")
        .task { await loadMemories() }
        .sheet(isPresented: $showDetail) {
            if let group = selectedGroup {
                MemoryDetailView(group: group)
            }
        }
    }

    private func loadMemories() async {
        do {
            memoryGroups = try await APIClient.shared.request(
                .get, path: "/v1/settings/memories"
            )
        } catch {
            print("[Settings] Failed to load memories: \(error)")
        }
        isLoading = false
    }
}

struct MemoryDetailView: View {
    let group: SettingsMemoriesFullView.MemoryGroup
    @State private var entries: [SettingsMemoriesFullView.MemoryEntry] = []
    @State private var isLoading = true
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            List {
                if isLoading {
                    ProgressView()
                } else {
                    ForEach(entries) { entry in
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(entry.key)
                                .font(.omSmall).fontWeight(.medium)
                                .foregroundStyle(Color.fontPrimary)
                            Text(entry.value)
                                .font(.omXs).foregroundStyle(Color.fontSecondary)
                        }
                        .swipeActions {
                            Button(role: .destructive) {
                                deleteEntry(entry.id)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }
                }
            }
            .navigationTitle(group.category)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .task { await loadEntries() }
        }
    }

    private func loadEntries() async {
        do {
            entries = try await APIClient.shared.request(
                .get, path: "/v1/settings/memories/\(group.appId)/\(group.category)"
            )
        } catch {
            print("[Settings] Failed to load memory entries: \(error)")
        }
        isLoading = false
    }

    private func deleteEntry(_ id: String) {
        Task {
            try? await APIClient.shared.request(
                .delete, path: "/v1/settings/memories/entry/\(id)"
            ) as Data
            entries.removeAll { $0.id == id }
        }
    }
}
