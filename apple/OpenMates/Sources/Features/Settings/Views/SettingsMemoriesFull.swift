// Native Memories settings hub backed by the encrypted SDK memory contract.
// Plaintext exists only in this in-memory view model; persisted records remain encrypted.
// Guest examples come from app metadata and authenticated changes refresh on sync events.
// Composer actions hand canonical memory-entry mentions to the native new-chat composer.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsMemoriesHub.svelte
//          frontend/packages/ui/src/components/settings/AppSettingsMemoriesCategory.svelte
//          frontend/packages/ui/src/components/settings/AppSettingsMemoriesEntryDetail.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Combine
import CryptoKit
import Foundation
import SwiftUI

struct SettingsMemoryCategory: Identifiable, Equatable {
    let appId: String
    let appName: String
    let categoryId: String
    let categoryName: String
    let iconName: String
    let examples: [SettingsMemoryEntry]

    var id: String { "\(appId):\(categoryId)" }
}

struct SettingsMemoryEntry: Identifiable, Equatable {
    let id: String
    let appId: String
    let categoryId: String
    var key: String
    var value: String
    let createdAt: Int
    var updatedAt: Int
    var version: Int
    let isExample: Bool

    var mentionSyntax: String { "@memory-entry:\(appId):\(categoryId):\(id)" }
}

private struct SettingsEncryptedMemoryResponse: Decodable {
    let memories: [SettingsEncryptedMemoryRecord]
}

private struct SettingsEncryptedMemoryRecord: Decodable {
    let id: String
    let appId: String
    let itemKey: String
    let itemType: String
    let encryptedItemJson: String
    let encryptedAppKey: String
    let createdAt: Int
    let updatedAt: Int
    let itemVersion: Int

    enum CodingKeys: String, CodingKey {
        case id
        case appId = "app_id"
        case itemKey = "item_key"
        case itemType = "item_type"
        case encryptedItemJson = "encrypted_item_json"
        case encryptedAppKey = "encrypted_app_key"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case itemVersion = "item_version"
    }

    var apiDictionary: [String: Any] {
        [
            "id": id,
            "app_id": appId,
            "item_key": itemKey,
            "item_type": itemType,
            "encrypted_item_json": encryptedItemJson,
            "encrypted_app_key": encryptedAppKey,
            "created_at": createdAt,
            "updated_at": updatedAt,
            "item_version": itemVersion,
        ]
    }
}

@MainActor
final class SettingsMemoryService: ObservableObject {
    enum LoadState: Equatable {
        case loading
        case loaded
        case empty
        case missingKey
        case pending
        case conflict
        case error(String)
    }

    @Published private(set) var state: LoadState = .loading
    @Published private(set) var categories: [SettingsMemoryCategory] = []
    @Published private(set) var entries: [SettingsMemoryEntry] = []
    @Published private(set) var isAuthenticated = false

    private let api = APIClient.shared
    private let crypto = CryptoManager.shared
    private let decoder = JSONDecoder()
    private var recordsByID: [String: SettingsEncryptedMemoryRecord] = [:]
    private var syncObserver: AnyCancellable?

    init() {
        syncObserver = NotificationCenter.default.publisher(for: .wsSyncEvent)
            .sink { [weak self] _ in
                Task { @MainActor in await self?.load() }
            }
    }

    func load() async {
        state = .loading
        do {
            if ProcessInfo.processInfo.arguments.contains("--ui-test-memory-fixture") {
                categories = [Self.guestFixtureCategory]
                isAuthenticated = false
                entries = categories.flatMap(\.examples)
                state = .loaded
                return
            }
            categories = try await loadCatalog()
            guard let userId = await AuthManager.currentUserId() else {
                isAuthenticated = false
                entries = categories.flatMap(\.examples)
                state = entries.isEmpty ? .empty : .loaded
                return
            }
            isAuthenticated = true
            guard let masterKey = try await crypto.loadMasterKey(for: userId) else {
                entries = []
                state = .missingKey
                return
            }

            let data: Data = try await api.request(.get, path: "/v1/sdk/memories")
            let response = try decoder.decode(SettingsEncryptedMemoryResponse.self, from: data)
            recordsByID = Dictionary(uniqueKeysWithValues: response.memories.map { ($0.id, $0) })
            var decryptedEntries: [SettingsMemoryEntry] = []
            for record in response.memories {
                guard categories.contains(where: { $0.appId == record.appId && $0.categoryId == record.itemType }) else {
                    continue
                }
                let plaintext = try await crypto.decryptContent(
                    base64String: record.encryptedItemJson,
                    key: masterKey
                )
                let payload = try Self.decodePayload(plaintext, fallbackKey: record.itemKey)
                decryptedEntries.append(SettingsMemoryEntry(
                    id: record.id,
                    appId: record.appId,
                    categoryId: record.itemType,
                    key: payload.key,
                    value: payload.value,
                    createdAt: record.createdAt,
                    updatedAt: record.updatedAt,
                    version: record.itemVersion,
                    isExample: false
                ))
            }
            entries = decryptedEntries.sorted { $0.updatedAt > $1.updatedAt }
            state = entries.isEmpty ? .empty : .loaded
        } catch {
            NativeDiagnostics.warning(
                "Memory settings load failed errorType=\(type(of: error))",
                category: "settings_memories"
            )
            state = .error(error.localizedDescription)
        }
    }

    func entries(in category: SettingsMemoryCategory) -> [SettingsMemoryEntry] {
        entries.filter { $0.appId == category.appId && $0.categoryId == category.categoryId }
    }

    func save(entry: SettingsMemoryEntry?, category: SettingsMemoryCategory, key: String, value: String) async -> Bool {
        guard isAuthenticated else {
            state = .missingKey
            return false
        }
        let cleanKey = key.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanValue = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanKey.isEmpty, !cleanValue.isEmpty else { return false }

        let previousEntries = entries
        let now = Int(Date().timeIntervalSince1970)
        let draft = SettingsMemoryEntry(
            id: entry?.id ?? UUID().uuidString,
            appId: category.appId,
            categoryId: category.categoryId,
            key: cleanKey,
            value: cleanValue,
            createdAt: entry?.createdAt ?? now,
            updatedAt: now,
            version: (entry?.version ?? 0) + 1,
            isExample: false
        )
        entries.removeAll { $0.id == draft.id }
        entries.insert(draft, at: 0)
        state = .pending

        do {
            guard let userId = await AuthManager.currentUserId(),
                  let masterKey = try await crypto.loadMasterKey(for: userId) else {
                throw SettingsMemoryServiceError.missingKey
            }
            var payload = (try? JSONSerialization.jsonObject(with: Data(cleanValue.utf8))) as? [String: Any]
                ?? ["value": cleanValue]
            payload["_original_item_key"] = cleanKey
            payload["settings_group"] = category.categoryId
            let payloadData = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            guard let payloadJSON = String(data: payloadData, encoding: .utf8) else {
                throw CryptoManager.CryptoError.invalidUTF8
            }
            let encrypted = try await crypto.encryptWithMasterKey(payloadJSON, masterKey: masterKey)
            let existing = entry.flatMap { recordsByID[$0.id] }
            let record = SettingsEncryptedMemoryRecord(
                id: draft.id,
                appId: category.appId,
                itemKey: existing?.itemKey ?? Self.hash("\(category.appId)-\(cleanKey)-\(now)"),
                itemType: category.categoryId,
                encryptedItemJson: encrypted,
                encryptedAppKey: existing?.encryptedAppKey ?? "",
                createdAt: draft.createdAt,
                updatedAt: now,
                itemVersion: draft.version
            )
            let _: Data = try await api.request(
                .post,
                path: "/v1/sdk/memories",
                body: ["entry": record.apiDictionary]
            )
            recordsByID[record.id] = record
            state = .loaded
            return true
        } catch {
            entries = previousEntries
            state = Self.isConflict(error) ? .conflict : .error(error.localizedDescription)
            NativeDiagnostics.warning(
                "Memory settings save failed errorType=\(type(of: error))",
                category: "settings_memories"
            )
            return false
        }
    }

    func delete(_ entry: SettingsMemoryEntry) async {
        guard !entry.isExample else { return }
        let previousEntries = entries
        entries.removeAll { $0.id == entry.id }
        state = .pending
        do {
            let escapedID = entry.id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? entry.id
            let _: Data = try await api.request(.delete, path: "/v1/sdk/memories/\(escapedID)")
            recordsByID[entry.id] = nil
            state = entries.isEmpty ? .empty : .loaded
        } catch {
            entries = previousEntries
            state = Self.isConflict(error) ? .conflict : .error(error.localizedDescription)
            NativeDiagnostics.warning(
                "Memory settings delete failed errorType=\(type(of: error))",
                category: "settings_memories"
            )
        }
    }

    private func loadCatalog() async throws -> [SettingsMemoryCategory] {
        let data: Data = try await api.request(.get, path: "/v1/apps/metadata?include_unavailable=true")
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let apps = root["apps"] as? [String: [String: Any]] else {
            return []
        }
        return apps.values.flatMap { app -> [SettingsMemoryCategory] in
            guard let appId = app["id"] as? String,
                  let fields = app["settings_and_memories"] as? [[String: Any]] else { return [] }
            let appName = app["name"] as? String ?? appId
            return fields.compactMap { field in
                guard let categoryId = field["id"] as? String else { return nil }
                let categoryName = field["name"] as? String ?? categoryId
                let structuredExamples = (field["example_entries"] as? [Any]) ?? []
                let rawExamples: [Any] = structuredExamples.isEmpty
                    ? ((field["example_translation_keys"] as? [String]) ?? [])
                    : structuredExamples
                let examples = rawExamples.enumerated().map { index, rawValue in
                    let value = Self.exampleDisplayValue(rawValue)
                    return SettingsMemoryEntry(
                        id: "example-\(appId)-\(categoryId)-\(index)",
                        appId: appId,
                        categoryId: categoryId,
                        key: categoryName,
                        value: value,
                        createdAt: 0,
                        updatedAt: 0,
                        version: 0,
                        isExample: true
                    )
                }
                return SettingsMemoryCategory(
                    appId: appId,
                    appName: appName,
                    categoryId: categoryId,
                    categoryName: categoryName,
                    iconName: AppIconView.iconName(forAppId: appId),
                    examples: examples
                )
            }
        }.sorted { $0.id < $1.id }
    }

    private static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func exampleDisplayValue(_ rawValue: Any) -> String {
        if let translationKey = rawValue as? String {
            return AppStrings.localized(translationKey)
        }
        if let fields = rawValue as? [String: Any] {
            return fields.keys.sorted().compactMap { key in
                guard let rawField = fields[key] else { return nil }
                let value = rawField as? String ?? String(describing: rawField)
                let localizedValue = value.contains(".") ? AppStrings.localized(value) : value
                return "\(key): \(localizedValue)"
            }.joined(separator: "\n")
        }
        return String(describing: rawValue)
    }

    private static func decodePayload(_ plaintext: String, fallbackKey: String) throws -> (key: String, value: String) {
        let json = try JSONSerialization.jsonObject(with: Data(plaintext.utf8))
        guard var fields = json as? [String: Any] else {
            return (fallbackKey, String(describing: json))
        }
        let key = fields.removeValue(forKey: "_original_item_key") as? String ?? fallbackKey
        fields.removeValue(forKey: "settings_group")
        if fields.count == 1, let value = fields["value"] as? String {
            return (key, value)
        }
        let valueData = try JSONSerialization.data(withJSONObject: fields, options: [.prettyPrinted, .sortedKeys])
        return (key, String(data: valueData, encoding: .utf8) ?? String(describing: fields))
    }

    private static func isConflict(_ error: Error) -> Bool {
        let message = error.localizedDescription.lowercased()
        return message.contains("409") || message.contains("conflict") || message.contains("version")
    }

    private static let guestFixtureCategory = SettingsMemoryCategory(
        appId: "travel",
        appName: AppStrings.localized("apps.travel"),
        categoryId: "preferred_activities",
        categoryName: AppStrings.localized("app_settings_memories.travel.preferred_activities"),
        iconName: "travel",
        examples: [
            SettingsMemoryEntry(
                id: "example-travel-preferred-activities-0",
                appId: "travel",
                categoryId: "preferred_activities",
                key: AppStrings.localized("app_settings_memories.travel.preferred_activities"),
                value: AppStrings.localized("app_settings_memories.travel.preferred_activities.example_1.name"),
                createdAt: 0,
                updatedAt: 0,
                version: 0,
                isExample: true
            ),
        ]
    )
}

private enum SettingsMemoryServiceError: Error {
    case missingKey
}

struct SettingsMemoriesFullView: View {
    @StateObject private var service = SettingsMemoryService()
    @State private var selectedCategory: SettingsMemoryCategory?
    @State private var editingEntry: SettingsMemoryEntry?
    @State private var isEditorPresented = false
    @State private var deletingEntry: SettingsMemoryEntry?

    var body: some View {
        ZStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing8) {
                    Text(AppStrings.encryptionNotice)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.horizontal, .spacing5)

                    stateContent
                }
                .padding(.vertical, .spacing6)
            }
            .accessibilityIdentifier("settings-memories-page")

            OMSheet(
                isPresented: Binding(
                    get: { selectedCategory != nil },
                    set: { if !$0 { selectedCategory = nil } }
                ),
                title: selectedCategory?.categoryName
            ) {
                if let category = selectedCategory {
                    categoryDetail(category)
                }
            }

            OMSheet(isPresented: $isEditorPresented, title: editingEntry == nil ? AppStrings.add : AppStrings.edit) {
                if let category = selectedCategory {
                    SettingsMemoryEditor(
                        entry: editingEntry,
                        onSave: { key, value in
                            let saved = await service.save(
                                entry: editingEntry,
                                category: category,
                                key: key,
                                value: value
                            )
                            if saved { isEditorPresented = false }
                        }
                    )
                }
            }

            if let deletingEntry {
                OMConfirmDialog(
                    title: AppStrings.delete,
                    message: AppStrings.confirmDeleteMemory,
                    confirmTitle: AppStrings.delete,
                    isDestructive: true,
                    onConfirm: {
                        self.deletingEntry = nil
                        Task { await service.delete(deletingEntry) }
                    },
                    onCancel: { self.deletingEntry = nil }
                )
            }
        }
        .task { await service.load() }
    }

    @ViewBuilder
    private var stateContent: some View {
        switch service.state {
        case .loading:
            settingsState(icon: "loading", text: AppStrings.loading, showsRetry: false)
        case .missingKey:
            settingsState(icon: "lock", text: AppStrings.memoryAuthenticationRequired, showsRetry: true)
        case .error(let message):
            settingsState(icon: "warning", text: message, showsRetry: true)
        case .conflict:
            settingsState(icon: "warning", text: AppStrings.error, showsRetry: true)
        case .pending:
            settingsState(icon: "loading", text: AppStrings.memorySaving, showsRetry: false)
        case .empty:
            settingsState(icon: "memory", text: AppStrings.noMemoriesYet, showsRetry: false)
            if service.isAuthenticated {
                categoryRows
            }
        case .loaded:
            if visibleCategories.isEmpty {
                settingsState(icon: "memory", text: AppStrings.noMemoriesYet, showsRetry: false)
            } else {
                categoryRows
            }
        }
    }

    @ViewBuilder
    private var categoryRows: some View {
        ForEach(visibleCategories) { category in
            OMSettingsSection(category.appName, icon: category.iconName) {
                OMSettingsRow(
                    title: category.categoryName,
                    icon: category.iconName,
                    value: AppStrings.entriesCount(service.entries(in: category).count),
                    accessibilityIdentifier: "settings-memory-category-\(category.appId)-\(category.categoryId)"
                ) {
                    selectedCategory = category
                }
            }
        }
    }

    private var visibleCategories: [SettingsMemoryCategory] {
        if service.isAuthenticated { return service.categories }
        return service.categories.filter { !$0.examples.isEmpty }
    }

    private func settingsState(icon: String, text: String, showsRetry: Bool) -> some View {
        VStack(spacing: .spacing5) {
            Icon(icon, size: 28)
                .foregroundStyle(Color.fontSecondary)
            Text(text)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
            if showsRetry {
                Button(AppStrings.retry) { Task { await service.load() } }
                    .buttonStyle(OMSecondaryButtonStyle())
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.spacing8)
        .accessibilityIdentifier("settings-memories-state")
    }

    private func categoryDetail(_ category: SettingsMemoryCategory) -> some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .spacing5) {
                if service.isAuthenticated {
                    Button {
                        editingEntry = nil
                        isEditorPresented = true
                    } label: {
                        Text(AppStrings.add).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .accessibilityIdentifier("settings-memory-add")
                }

                ForEach(service.entries(in: category)) { entry in
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Text(entry.key)
                            .font(.omP.weight(.semibold))
                            .foregroundStyle(Color.fontPrimary)
                        Text(entry.value)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontSecondary)
                        if !entry.isExample {
                            HStack(spacing: .spacing4) {
                                Button(AppStrings.edit) {
                                    editingEntry = entry
                                    isEditorPresented = true
                                }
                                .buttonStyle(OMSecondaryButtonStyle())
                                Button(AppStrings.delete) { deletingEntry = entry }
                                    .buttonStyle(OMSecondaryButtonStyle())
                                Button(AppStrings.newChat) {
                                    SettingsComposerHandoff.request(mention: entry.mentionSyntax)
                                }
                                .buttonStyle(OMPrimaryButtonStyle())
                            }
                        }
                    }
                    .padding(.spacing6)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .accessibilityIdentifier("settings-memory-entry-\(entry.id)")
                }
            }
        }
        .frame(maxHeight: 520)
    }
}

private struct SettingsMemoryEditor: View {
    let entry: SettingsMemoryEntry?
    let onSave: (String, String) async -> Void
    @State private var key = ""
    @State private var value = ""
    @State private var isSaving = false

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            TextField(AppStrings.memoryKeyRequired, text: $key)
                .textFieldStyle(OMTextFieldStyle())
                .accessibilityIdentifier("settings-memory-key")
            TextField(AppStrings.memoryValueRequired, text: $value, axis: .vertical)
                .lineLimit(3...8)
                .textFieldStyle(OMTextFieldStyle())
                .accessibilityIdentifier("settings-memory-value")
            Button(isSaving ? AppStrings.memorySaving : AppStrings.save) {
                isSaving = true
                Task {
                    await onSave(key, value)
                    isSaving = false
                }
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                      value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
            .accessibilityIdentifier("settings-memory-save")
        }
        .onAppear {
            key = entry?.key ?? ""
            value = entry?.value ?? ""
        }
    }
}
