// Full storage management — overview with breakdown and per-category file list.
// Mirrors the web app's SettingsStorage.svelte + SettingsStorageFiles.svelte.

import SwiftUI

struct SettingsStorageFullView: View {
    @State private var overview: StorageOverview?
    @State private var isLoading = true
    @State private var selectedCategory: StorageCategory?
    @State private var showFiles = false

    struct StorageOverview: Decodable {
        let totalBytes: Int
        let totalFiles: Int
        let freeBytes: Int?
        let billableGb: Double?
        let weeklyCostCredits: Double?
        let breakdown: [StorageCategory]
    }

    struct StorageCategory: Identifiable, Decodable {
        let category: String
        let bytesUsed: Int
        let fileCount: Int

        var id: String { category }

        var icon: String {
            switch category {
            case "images": return "photo"
            case "videos": return "video"
            case "audio": return "waveform"
            case "pdf": return "doc.richtext"
            case "code": return "chevron.left.forwardslash.chevron.right"
            case "docs": return "doc.text"
            case "sheets": return "tablecells"
            case "archives": return "archivebox"
            default: return "doc"
            }
        }

        var formattedSize: String {
            ByteCountFormatter.string(fromByteCount: Int64(bytesUsed), countStyle: .file)
        }
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if let overview {
                Section(LocalizationManager.shared.text("settings.storage.overview")) {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        ProgressView(
                            value: Double(overview.totalBytes),
                            total: Double(max(overview.totalBytes, overview.freeBytes ?? 1_073_741_824))
                        )
                        .tint(Color.buttonPrimary)
                        .accessibilityHidden(true)

                        HStack {
                            Text("\(LocalizationManager.shared.text("settings.storage.used")): \(ByteCountFormatter.string(fromByteCount: Int64(overview.totalBytes), countStyle: .file))")
                                .font(.omSmall)
                            Spacer()
                            Text("\(overview.totalFiles) \(LocalizationManager.shared.text("settings.storage.files"))")
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                        .accessibilityElement(children: .combine)

                        if let cost = overview.weeklyCostCredits, cost > 0 {
                            Text("\(LocalizationManager.shared.text("settings.storage.weekly_cost")): \(String(format: "%.4f", cost)) \(LocalizationManager.shared.text("common.credits"))")
                                .font(.omXs).foregroundStyle(Color.fontTertiary)
                        }
                    }
                }

                Section(LocalizationManager.shared.text("settings.storage.by_category")) {
                    ForEach(overview.breakdown.sorted(by: { $0.bytesUsed > $1.bytesUsed })) { cat in
                        Button {
                            selectedCategory = cat
                            showFiles = true
                        } label: {
                            HStack {
                                Image(systemName: cat.icon)
                                    .frame(width: 24)
                                    .foregroundStyle(Color.fontSecondary)
                                    .accessibilityHidden(true)
                                Text(cat.category.capitalized)
                                    .font(.omSmall)
                                    .foregroundStyle(Color.fontPrimary)
                                Spacer()
                                VStack(alignment: .trailing) {
                                    Text(cat.formattedSize)
                                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                                    Text("\(cat.fileCount) files")
                                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                }
                                Image(systemName: "chevron.right")
                                    .font(.caption).foregroundStyle(Color.fontTertiary)
                                    .accessibilityHidden(true)
                            }
                        }
                        .accessibleButton(
                            "\(cat.category.capitalized), \(cat.formattedSize), \(cat.fileCount) files",
                            hint: LocalizationManager.shared.text("settings.storage.view_files_hint")
                        )
                    }
                }
            }
        }
        .navigationTitle(AppStrings.storage)
        .task { await loadOverview() }
        .sheet(isPresented: $showFiles) {
            if let cat = selectedCategory {
                StorageFilesView(category: cat.category)
            }
        }
    }

    private func loadOverview() async {
        do {
            overview = try await APIClient.shared.request(.get, path: "/v1/settings/storage")
        } catch {
            print("[Settings] Failed to load storage: \(error)")
        }
        isLoading = false
    }
}

struct StorageFilesView: View {
    let category: String
    @State private var files: [StorageFile] = []
    @State private var isLoading = true
    @Environment(\.dismiss) var dismiss

    struct StorageFile: Identifiable, Decodable {
        let id: String
        let filename: String?
        let size: Int
        let createdAt: String?
        let embedId: String?

        var formattedSize: String {
            ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)
        }
    }

    var body: some View {
        NavigationStack {
            List {
                if isLoading {
                    ProgressView()
                } else if files.isEmpty {
                    Text(LocalizationManager.shared.text("settings.storage.no_files"))
                        .foregroundStyle(Color.fontSecondary)
                } else {
                    ForEach(files) { file in
                        HStack {
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(file.filename ?? "Unnamed")
                                    .font(.omSmall).fontWeight(.medium)
                                    .lineLimit(1)
                                HStack(spacing: .spacing3) {
                                    Text(file.formattedSize)
                                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                                    if let date = file.createdAt {
                                        Text(date)
                                            .font(.omXs).foregroundStyle(Color.fontTertiary)
                                    }
                                }
                            }
                            Spacer()
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel("\(file.filename ?? "Unnamed"), \(file.formattedSize)")
                        .accessibilityHint(LocalizationManager.shared.text("settings.swipe_left_to_delete"))
                        .swipeActions {
                            Button(role: .destructive) {
                                deleteFile(file.id)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }
                }
            }
            .navigationTitle(category.capitalized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppStrings.done) { dismiss() }
                        .accessibleButton(AppStrings.done)
                }
            }
            .task { await loadFiles() }
        }
    }

    private func loadFiles() async {
        do {
            files = try await APIClient.shared.request(
                .get, path: "/v1/settings/storage/files?category=\(category)"
            )
        } catch {
            print("[Settings] Failed to load files: \(error)")
        }
        isLoading = false
    }

    private func deleteFile(_ id: String) {
        Task {
            try? await APIClient.shared.request(
                .delete, path: "/v1/settings/storage/files",
                body: ["file_ids": [id]]
            ) as Data
            files.removeAll { $0.id == id }
        }
    }
}
