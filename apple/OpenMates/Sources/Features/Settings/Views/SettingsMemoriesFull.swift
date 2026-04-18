// Memories hub — view, create, edit, and delete AI memories across all apps.
// Mirrors the web app's SettingsMemoriesHub.svelte with full CRUD support.
// All strings use AppStrings (i18n).

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
            // Encryption notice banner
            Section {
                HStack(spacing: .spacing3) {
                    Image(systemName: "lock.shield.fill")
                        .foregroundStyle(Color.buttonPrimary)
                    Text(AppStrings.encryptionNotice)
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
                .padding(.vertical, .spacing2)
            }

            if isLoading {
                ProgressView()
            } else if memoryGroups.isEmpty {
                Section {
                    VStack(spacing: .spacing4) {
                        Image(systemName: "brain.head.profile")
                            .font(.system(size: 36))
                            .foregroundStyle(Color.fontTertiary)
                        Text(AppStrings.noMemoriesYet)
                            .font(.omP).foregroundStyle(Color.fontSecondary)
                        Text(AppStrings.memoriesDescription)
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
                                        .accessibilityHidden(true)
                                    VStack(alignment: .leading, spacing: .spacing1) {
                                        Text(group.category)
                                            .font(.omSmall).fontWeight(.medium)
                                            .foregroundStyle(Color.fontPrimary)
                                        Text(AppStrings.entriesCount(group.entryCount))
                                            .font(.omXs).foregroundStyle(Color.fontTertiary)
                                    }
                                    Spacer()
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundStyle(Color.fontTertiary)
                                        .accessibilityHidden(true)
                                }
                            }
                            .accessibilityElement(children: .combine)
                            .accessibleButton(
                                "\(group.category), \(AppStrings.entriesCount(group.entryCount))",
                                hint: LocalizationManager.shared.text("settings.memories.view_entries_hint")
                            )
                        }
                    } header: {
                        Text(memoryGroups.first(where: { $0.appId == appId })?.appName ?? appId)
                    }
                }
            }
        }
        .navigationTitle(AppStrings.settingsMemories)
        .task { await loadMemories() }
        .sheet(isPresented: $showDetail) {
            if let group = selectedGroup {
                MemoryDetailView(group: group, onChanged: {
                    Task { await loadMemories() }
                })
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

// MARK: - Memory detail with CRUD

struct MemoryDetailView: View {
    let group: SettingsMemoriesFullView.MemoryGroup
    let onChanged: () -> Void
    @State private var entries: [SettingsMemoriesFullView.MemoryEntry] = []
    @State private var isLoading = true
    @State private var showAddEntry = false
    @State private var editingEntry: SettingsMemoriesFullView.MemoryEntry?
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            List {
                if isLoading {
                    ProgressView()
                } else if entries.isEmpty {
                    Section {
                        Text(AppStrings.noMemoriesYet)
                            .foregroundStyle(Color.fontSecondary)
                    }
                } else {
                    ForEach(entries) { entry in
                        Button {
                            editingEntry = entry
                        } label: {
                            VStack(alignment: .leading, spacing: .spacing2) {
                                Text(entry.key)
                                    .font(.omSmall).fontWeight(.medium)
                                    .foregroundStyle(Color.fontPrimary)
                                Text(entry.value)
                                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                                    .lineLimit(3)
                                if let updated = entry.updatedAt {
                                    Text(String(updated.prefix(10)))
                                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                }
                            }
                        }
                        .swipeActions {
                            Button(role: .destructive) {
                                deleteEntry(entry.id)
                            } label: {
                                Label(AppStrings.delete, systemImage: "trash")
                            }
                        }
                    }
                }
            }
            .navigationTitle(group.category)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppStrings.done) { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        showAddEntry = true
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibleButton(AppStrings.add, hint: LocalizationManager.shared.text("settings.memories.add_entry_hint"))
                }
            }
            .task { await loadEntries() }
            .sheet(isPresented: $showAddEntry) {
                MemoryEntryEditView(
                    appId: group.appId,
                    category: group.category,
                    entry: nil,
                    onSaved: {
                        Task { await loadEntries() }
                        onChanged()
                    }
                )
            }
            .sheet(item: $editingEntry) { entry in
                MemoryEntryEditView(
                    appId: group.appId,
                    category: group.category,
                    entry: entry,
                    onSaved: {
                        Task { await loadEntries() }
                        onChanged()
                    }
                )
            }
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
            onChanged()
        }
    }
}

// MARK: - Create/Edit memory entry

struct MemoryEntryEditView: View {
    let appId: String
    let category: String
    let entry: SettingsMemoriesFullView.MemoryEntry?
    let onSaved: () -> Void

    @State private var key = ""
    @State private var value = ""
    @State private var isSaving = false
    @State private var error: String?
    @Environment(\.dismiss) var dismiss

    private var isEditing: Bool { entry != nil }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(LocalizationManager.shared.text("settings.app_settings_memories.item_key_required"), text: $key)
                        .autocorrectionDisabled()
                        .accessibleInput(
                            LocalizationManager.shared.text("settings.app_settings_memories.item_key_required"),
                            hint: LocalizationManager.shared.text("settings.memories.key_hint")
                        )
                    TextField(LocalizationManager.shared.text("settings.app_settings_memories.item_value_required"), text: $value, axis: .vertical)
                        .lineLimit(3...8)
                        .accessibleInput(
                            LocalizationManager.shared.text("settings.app_settings_memories.item_value_required"),
                            hint: LocalizationManager.shared.text("settings.memories.value_hint")
                        )
                }

                if let error {
                    Section {
                        Text(error).font(.omXs).foregroundStyle(Color.error)
                    }
                }
            }
            .navigationTitle(isEditing ? AppStrings.edit : AppStrings.add)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppStrings.cancel) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(AppStrings.save) { saveEntry() }
                        .disabled(key.isEmpty || value.isEmpty || isSaving)
                }
            }
            .onAppear {
                if let entry {
                    key = entry.key
                    value = entry.value
                }
            }
        }
    }

    private func saveEntry() {
        isSaving = true
        error = nil
        Task {
            do {
                if let entry {
                    // Update existing
                    let _: Data = try await APIClient.shared.request(
                        .patch, path: "/v1/settings/memories/entry/\(entry.id)",
                        body: ["key": key, "value": value]
                    )
                } else {
                    // Create new
                    let _: Data = try await APIClient.shared.request(
                        .post, path: "/v1/settings/memories/\(appId)/\(category)",
                        body: ["key": key, "value": value]
                    )
                }
                onSaved()
                dismiss()
                AccessibilityAnnouncement.announce(AppStrings.success)
            } catch {
                self.error = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isSaving = false
        }
    }
}
