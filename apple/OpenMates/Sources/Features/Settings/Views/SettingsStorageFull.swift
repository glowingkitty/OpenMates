// Native account storage overview and per-category file management.
// Uses the same overview/list/delete endpoints and loaded, empty, error, and
// destructive confirmation states as the web account storage settings.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsStorage.svelte
//          frontend/packages/ui/src/components/settings/account/SettingsStorageFiles.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsStorageFullView: View {
    @State private var overview: StorageOverview?
    @State private var files: [StorageFileRecord] = []
    @State private var selectedCategory: StorageCategoryRecord?
    @State private var pendingDeletion: StorageFileRecord?
    @State private var isLoading = true
    @State private var errorMessage: String?

    var body: some View {
        OMSettingsPage(title: selectedCategory.map { AppStrings.storageCategory($0.category) } ?? AppStrings.storage) {
            if isLoading {
                HStack(spacing: .spacing3) {
                    ProgressView()
                    Text(AppStrings.storageLoading).font(.omSmall)
                }
                .padding(.spacing8)
            } else if let errorMessage {
                VStack(alignment: .leading, spacing: .spacing4) {
                    Text(errorMessage).font(.omSmall).foregroundStyle(Color.error)
                    Button(AppStrings.retry) { Task { await reload() } }
                        .buttonStyle(OMSecondaryButtonStyle())
                }
                .padding(.spacing6)
            } else if let selectedCategory {
                fileList(category: selectedCategory)
            } else if let overview {
                overviewContent(overview)
            }
        }
        .task { await loadOverview() }
        .overlay {
            if let pendingDeletion {
                OMConfirmDialog(
                    title: AppStrings.storageDeleteFile,
                    message: AppStrings.storageDeleteConfirm,
                    confirmTitle: AppStrings.delete,
                    isDestructive: true,
                    onConfirm: { self.pendingDeletion = nil; deleteFile(pendingDeletion) },
                    onCancel: { self.pendingDeletion = nil }
                )
            }
        }
        .accessibilityIdentifier("settings-storage-page")
    }

    private func overviewContent(_ value: StorageOverview) -> some View {
        Group {
            OMSettingsSection(AppStrings.storage, icon: "cloud") {
                VStack(alignment: .leading, spacing: .spacing4) {
                    ProgressView(value: Double(value.totalBytes), total: Double(max(value.freeBytes, 1)))
                        .tint(Color.buttonPrimary)
                    OMSettingsStaticRow(
                        title: AppStrings.storage,
                        value: ByteCountFormatter.string(fromByteCount: Int64(value.totalBytes), countStyle: .file)
                    )
                    OMSettingsStaticRow(title: AppStrings.credits, value: String(format: "%.4f", value.weeklyCostCredits))
                }
                .padding(.spacing6)
            }

            OMSettingsSection(AppStrings.storageBreakdown, icon: "cloud") {
                ForEach(value.breakdown.filter { $0.fileCount > 0 }) { category in
                    OMSettingsRow(
                        title: AppStrings.storageCategory(category.category),
                        icon: categoryIcon(category.category),
                        value: "\(AppStrings.storageFilesCount(category.fileCount)) · \(ByteCountFormatter.string(fromByteCount: Int64(category.bytesUsed), countStyle: .file))",
                        accessibilityIdentifier: "settings-storage-category-\(category.category)"
                    ) {
                        selectedCategory = category
                        Task { await loadFiles(category: category.category) }
                    }
                }
            }
        }
    }

    private func fileList(category: StorageCategoryRecord) -> some View {
        Group {
            OMSettingsSection {
                OMSettingsRow(title: AppStrings.back, icon: "back", showsChevron: false) {
                    selectedCategory = nil
                    files = []
                    Task { await loadOverview() }
                }
            }
            OMSettingsSection(AppStrings.storageCategory(category.category), icon: categoryIcon(category.category)) {
                if files.isEmpty {
                    Text(AppStrings.storageNoFiles)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.spacing6)
                } else {
                    ForEach(files) { file in
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(file.filename ?? AppStrings.untitled)
                                .font(.omP.weight(.medium))
                                .foregroundStyle(Color.fontPrimary)
                            Text(ByteCountFormatter.string(fromByteCount: Int64(file.sizeBytes), countStyle: .file))
                                .font(.omXs)
                                .foregroundStyle(Color.fontSecondary)
                            OMSettingsRow(
                                title: AppStrings.storageDeleteFile,
                                icon: "trash",
                                isDestructive: true,
                                showsChevron: false,
                                accessibilityIdentifier: "settings-storage-delete-\(file.id)"
                            ) { pendingDeletion = file }
                        }
                        .padding(.spacing6)
                    }
                }
            }
        }
    }

    private func reload() async {
        if let selectedCategory { await loadFiles(category: selectedCategory.category) }
        else { await loadOverview() }
    }

    private func loadOverview() async {
        isLoading = true
        errorMessage = nil
        do {
            overview = try await AccountSecurityService.shared.storageOverview()
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Storage overview request failed", category: "settings.account")
        }
        isLoading = false
    }

    private func loadFiles(category: String) async {
        isLoading = true
        errorMessage = nil
        do {
            files = try await AccountSecurityService.shared.storageFiles(category: category)
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Storage file request failed", category: "settings.account")
        }
        isLoading = false
    }

    private func deleteFile(_ file: StorageFileRecord) {
        Task {
            do {
                _ = try await AccountSecurityService.shared.deleteStorageFiles(ids: [file.id])
                files.removeAll { $0.id == file.id }
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Storage file deletion failed", category: "settings.account")
            }
        }
    }

    private func categoryIcon(_ category: String) -> String {
        switch category {
        case "images": "image"
        case "videos": "video"
        case "audio": "audio"
        case "code": "code"
        case "archives": "archive"
        default: "files"
        }
    }
}
