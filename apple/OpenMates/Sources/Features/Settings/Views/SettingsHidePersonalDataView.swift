// Hide personal data settings — manages PII category toggles and custom entries.
// Mirrors the web SettingsHidePersonalData.svelte privacy surface while using
// native OpenMates primitives instead of stock List/Form/Toggle/Menu chrome.
// Privacy data uses the same encrypted user_app_settings_and_memories contract
// as web: app_id=privacy, personal_data_entry, and pii_detection_settings.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/privacy/SettingsHidePersonalData.svelte
// Store:   frontend/packages/ui/src/stores/personalDataStore.ts
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import CryptoKit

private enum ApplePrivacySettingsContract {
    static let appId = "privacy"
    static let personalDataItemType = "personal_data_entry"
    static let piiSettingsItemType = "pii_detection_settings"
    static let settingsItemKey = "pii_detection_settings"

    static let defaultCategories: [String: Bool] = [
        "email_addresses": true, "phone_numbers": true,
        "credit_card_numbers": true, "iban_bank_account": true,
        "tax_id_vat": true, "crypto_wallets": true,
        "social_security_numbers": true, "passport_numbers": true,
        "api_keys": true, "jwt_tokens": true,
        "private_keys": true, "generic_secrets": true,
        "ip_addresses": true, "mac_addresses": true,
        "user_at_hostname": true, "home_folder": true,
    ]
}

struct ApplePrivacyAddressFields: Codable, Equatable, Sendable {
    var street: String?
    var city: String?
    var state: String?
    var zip: String?
    var country: String?

    var detectionTexts: [String] {
        [street, city, state, zip, country]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }
}

enum ApplePersonalDataType: String, CaseIterable, Codable, Identifiable, Sendable {
    case name
    case address
    case birthday
    case custom

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .name: return "user"
        case .address: return "maps"
        case .birthday: return "gift"
        case .custom: return "create"
        }
    }

    @MainActor var addTitle: String {
        switch self {
        case .name: return AppStrings.privacyAddName
        case .address: return AppStrings.privacyAddAddress
        case .birthday: return AppStrings.privacyAddBirthday
        case .custom: return AppStrings.privacyAddCustomEntry
        }
    }

    var defaultReplacement: String {
        switch self {
        case .name: return "ME"
        case .address: return "MY_ADDRESS"
        case .birthday: return "MY_BIRTHDAY"
        case .custom: return "CUSTOM"
        }
    }

    var detectorType: PIIType {
        switch self {
        case .address: return .address
        case .name, .birthday, .custom: return .genericSecret
        }
    }
}

struct ApplePIIDetectionSettings: Codable, Equatable, Sendable {
    var masterEnabled: Bool = true
    var categories: [String: Bool] = ApplePrivacySettingsContract.defaultCategories

    init(masterEnabled: Bool = true, categories: [String: Bool] = ApplePrivacySettingsContract.defaultCategories) {
        self.masterEnabled = masterEnabled
        self.categories = ApplePrivacySettingsContract.defaultCategories.merging(categories) { _, new in new }
    }

    var disabledCategories: Set<String> {
        Set(categories.compactMap { key, enabled in enabled ? nil : key })
    }
}

struct ApplePrivacyPersonalDataEntry: Identifiable, Codable, Equatable, Sendable {
    let id: String
    var type: ApplePersonalDataType
    var title: String
    var textToHide: String
    var replaceWith: String
    var enabled: Bool
    var addressLines: ApplePrivacyAddressFields?
    var createdAt: Int
    var updatedAt: Int

    @MainActor var displayTitle: String {
        title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? type.addTitle : title
    }

    func detectionEntry() -> PersonalDataForDetection? {
        guard enabled else { return nil }
        let primary = textToHide.trimmingCharacters(in: .whitespacesAndNewlines)
        let additionalTexts = addressLines?.detectionTexts ?? []
        guard !primary.isEmpty || !additionalTexts.isEmpty else { return nil }
        return PersonalDataForDetection(
            id: id,
            textToHide: primary,
            replaceWith: replaceWith,
            additionalTexts: additionalTexts,
            type: type.detectorType
        )
    }
}

struct ApplePrivacySettingsState: Equatable, Sendable {
    var detectionSettings = ApplePIIDetectionSettings()
    var entries: [ApplePrivacyPersonalDataEntry] = []

    var contactEntries: [ApplePrivacyPersonalDataEntry] {
        entries.filter { $0.type == .name || $0.type == .address || $0.type == .birthday }
    }

    var customEntries: [ApplePrivacyPersonalDataEntry] {
        entries.filter { $0.type == .custom }
    }

    var detectorSettings: PIIPrivacySettings {
        PIIPrivacySettings(
            masterEnabled: detectionSettings.masterEnabled,
            disabledCategories: detectionSettings.disabledCategories,
            personalDataEntries: entries.compactMap { $0.detectionEntry() }
        )
    }

    func isCategoryEnabled(_ category: String) -> Bool {
        detectionSettings.categories[category] ?? true
    }
}

private struct PrivacyMemoriesResponse: Decodable {
    let memories: [PrivacyMemoryRecord]
}

private struct PrivacyMemoryRecord: Decodable, Equatable {
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

    init(
        id: String,
        appId: String,
        itemKey: String,
        itemType: String,
        encryptedItemJson: String,
        encryptedAppKey: String = "",
        createdAt: Int,
        updatedAt: Int,
        itemVersion: Int
    ) {
        self.id = id
        self.appId = appId
        self.itemKey = itemKey
        self.itemType = itemType
        self.encryptedItemJson = encryptedItemJson
        self.encryptedAppKey = encryptedAppKey
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.itemVersion = itemVersion
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        appId = try container.decodeIfPresent(String.self, forKey: .appId) ?? ApplePrivacySettingsContract.appId
        itemKey = try container.decode(String.self, forKey: .itemKey)
        itemType = try container.decode(String.self, forKey: .itemType)
        encryptedItemJson = try container.decode(String.self, forKey: .encryptedItemJson)
        encryptedAppKey = try container.decodeIfPresent(String.self, forKey: .encryptedAppKey) ?? ""
        createdAt = container.decodeFlexibleInt(forKey: .createdAt) ?? Self.nowSeconds
        updatedAt = container.decodeFlexibleInt(forKey: .updatedAt) ?? createdAt
        itemVersion = container.decodeFlexibleInt(forKey: .itemVersion) ?? 1
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

    static var nowSeconds: Int { Int(Date().timeIntervalSince1970) }
}

private struct PrivacySettingsPayload: Codable {
    let masterEnabled: Bool
    let categories: [String: Bool]
    let originalItemKey: String?
    let settingsGroup: String?

    enum CodingKeys: String, CodingKey {
        case masterEnabled
        case categories
        case originalItemKey = "_original_item_key"
        case settingsGroup = "settings_group"
    }
}

private struct PrivacyPersonalDataPayload: Codable {
    let type: ApplePersonalDataType
    let title: String
    let textToHide: String
    let replaceWith: String
    let enabled: Bool
    let addressLines: ApplePrivacyAddressFields?
    let originalItemKey: String?
    let settingsGroup: String?

    enum CodingKeys: String, CodingKey {
        case type
        case title
        case textToHide
        case replaceWith
        case enabled
        case addressLines
        case originalItemKey = "_original_item_key"
        case settingsGroup = "settings_group"
    }
}

@MainActor
final class ApplePrivacySettingsService: ObservableObject {
    static let shared = ApplePrivacySettingsService()

    @Published private(set) var state = ApplePrivacySettingsState()
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    private let api = APIClient.shared
    private let crypto = CryptoManager.shared
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()
    private var settingsRecord: PrivacyMemoryRecord?
    private var entryRecords: [String: PrivacyMemoryRecord] = [:]

    init() {}

    func load() async {
        guard !isLoading else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            guard let masterKey = try await currentMasterKey() else {
                publish(ApplePrivacySettingsState())
                return
            }
            let responseData: Data = try await api.request(
                .get,
                path: "/v1/sdk/memories?app_id=\(ApplePrivacySettingsContract.appId)"
            )
            let response = try decoder.decode(PrivacyMemoriesResponse.self, from: responseData)

            var nextSettings = ApplePIIDetectionSettings()
            var nextEntries: [ApplePrivacyPersonalDataEntry] = []
            var nextEntryRecords: [String: PrivacyMemoryRecord] = [:]
            var nextSettingsRecord: PrivacyMemoryRecord?

            for record in response.memories where record.appId == ApplePrivacySettingsContract.appId {
                do {
                    let decrypted = try await crypto.decryptContent(base64String: record.encryptedItemJson, key: masterKey)
                    let data = Data(decrypted.utf8)
                    switch record.itemType {
                    case ApplePrivacySettingsContract.piiSettingsItemType:
                        let payload = try decoder.decode(PrivacySettingsPayload.self, from: data)
                        nextSettings = ApplePIIDetectionSettings(
                            masterEnabled: payload.masterEnabled,
                            categories: ApplePrivacySettingsContract.defaultCategories.merging(payload.categories) { _, new in new }
                        )
                        nextSettingsRecord = record
                    case ApplePrivacySettingsContract.personalDataItemType:
                        let payload = try decoder.decode(PrivacyPersonalDataPayload.self, from: data)
                        let entry = ApplePrivacyPersonalDataEntry(
                            id: record.id,
                            type: payload.type,
                            title: payload.title,
                            textToHide: payload.textToHide,
                            replaceWith: payload.replaceWith,
                            enabled: payload.enabled,
                            addressLines: payload.addressLines,
                            createdAt: record.createdAt,
                            updatedAt: record.updatedAt
                        )
                        nextEntries.append(entry)
                        nextEntryRecords[entry.id] = record
                    default:
                        continue
                    }
                } catch {
                    errorMessage = error.localizedDescription
                }
            }

            settingsRecord = nextSettingsRecord
            entryRecords = nextEntryRecords
            publish(ApplePrivacySettingsState(detectionSettings: nextSettings, entries: nextEntries.sorted { $0.updatedAt > $1.updatedAt }))
        } catch {
            errorMessage = error.localizedDescription
            publish(state)
        }
    }

    func setMasterEnabled(_ enabled: Bool) async {
        var settings = state.detectionSettings
        settings.masterEnabled = enabled
        await save(settings: settings)
    }

    func setCategory(_ category: String, enabled: Bool) async {
        var settings = state.detectionSettings
        settings.categories[category] = enabled
        await save(settings: settings)
    }

    func setEntryEnabled(_ entry: ApplePrivacyPersonalDataEntry, enabled: Bool) async {
        var updated = entry
        updated.enabled = enabled
        updated.updatedAt = PrivacyMemoryRecord.nowSeconds
        await save(entry: updated)
    }

    func addEntry(type: ApplePersonalDataType, title: String, textToHide: String, replaceWith: String) async {
        let now = PrivacyMemoryRecord.nowSeconds
        let entry = ApplePrivacyPersonalDataEntry(
            id: UUID().uuidString,
            type: type,
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            textToHide: textToHide.trimmingCharacters(in: .whitespacesAndNewlines),
            replaceWith: replaceWith.trimmingCharacters(in: .whitespacesAndNewlines),
            enabled: true,
            addressLines: nil,
            createdAt: now,
            updatedAt: now
        )
        await save(entry: entry)
    }

    func deleteEntry(_ entry: ApplePrivacyPersonalDataEntry) async {
        errorMessage = nil
        do {
            let _: Data = try await api.request(.delete, path: "/v1/sdk/memories/\(Self.pathComponent(entry.id))")
            entryRecords[entry.id] = nil
            publish(ApplePrivacySettingsState(
                detectionSettings: state.detectionSettings,
                entries: state.entries.filter { $0.id != entry.id }
            ))
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func save(settings: ApplePIIDetectionSettings) async {
        errorMessage = nil
        do {
            guard let masterKey = try await currentMasterKey() else { return }
            let now = PrivacyMemoryRecord.nowSeconds
            let existing = settingsRecord
            let payload = PrivacySettingsPayload(
                masterEnabled: settings.masterEnabled,
                categories: settings.categories,
                originalItemKey: ApplePrivacySettingsContract.settingsItemKey,
                settingsGroup: ApplePrivacySettingsContract.piiSettingsItemType
            )
            let encrypted = try await encrypt(payload, masterKey: masterKey)
            let record = PrivacyMemoryRecord(
                id: existing?.id ?? UUID().uuidString,
                appId: ApplePrivacySettingsContract.appId,
                itemKey: existing?.itemKey ?? Self.hashString("\(ApplePrivacySettingsContract.appId)-\(ApplePrivacySettingsContract.settingsItemKey)-\(now)").prefixString(32),
                itemType: ApplePrivacySettingsContract.piiSettingsItemType,
                encryptedItemJson: encrypted,
                createdAt: existing?.createdAt ?? now,
                updatedAt: now,
                itemVersion: (existing?.itemVersion ?? 0) + 1
            )
            try await store(record)
            settingsRecord = record
            publish(ApplePrivacySettingsState(detectionSettings: settings, entries: state.entries))
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func save(entry: ApplePrivacyPersonalDataEntry) async {
        errorMessage = nil
        do {
            guard let masterKey = try await currentMasterKey() else { return }
            let now = PrivacyMemoryRecord.nowSeconds
            let existing = entryRecords[entry.id]
            let payload = PrivacyPersonalDataPayload(
                type: entry.type,
                title: entry.title,
                textToHide: entry.textToHide,
                replaceWith: entry.replaceWith,
                enabled: entry.enabled,
                addressLines: entry.addressLines,
                originalItemKey: entry.id,
                settingsGroup: ApplePrivacySettingsContract.personalDataItemType
            )
            let encrypted = try await encrypt(payload, masterKey: masterKey)
            let record = PrivacyMemoryRecord(
                id: entry.id,
                appId: ApplePrivacySettingsContract.appId,
                itemKey: existing?.itemKey ?? Self.hashString("\(ApplePrivacySettingsContract.appId)-\(entry.id)-\(now)").prefixString(32),
                itemType: ApplePrivacySettingsContract.personalDataItemType,
                encryptedItemJson: encrypted,
                createdAt: existing?.createdAt ?? entry.createdAt,
                updatedAt: now,
                itemVersion: (existing?.itemVersion ?? 0) + 1
            )
            try await store(record)
            entryRecords[entry.id] = record
            var savedEntry = entry
            savedEntry.createdAt = record.createdAt
            savedEntry.updatedAt = record.updatedAt
            var entries = state.entries.filter { $0.id != entry.id }
            entries.append(savedEntry)
            publish(ApplePrivacySettingsState(detectionSettings: state.detectionSettings, entries: entries.sorted { $0.updatedAt > $1.updatedAt }))
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func store(_ record: PrivacyMemoryRecord) async throws {
        let _: Data = try await api.request(
            .post,
            path: "/v1/sdk/memories",
            body: ["entry": record.apiDictionary]
        )
    }

    private func encrypt<T: Encodable>(_ payload: T, masterKey: SymmetricKey) async throws -> String {
        let data = try encoder.encode(payload)
        guard let json = String(data: data, encoding: .utf8) else {
            throw CryptoManager.CryptoError.invalidUTF8
        }
        return try await crypto.encryptWithMasterKey(json, masterKey: masterKey)
    }

    private func currentMasterKey() async throws -> SymmetricKey? {
        guard let userId = await AuthManager.currentUserId() else { return nil }
        return try await crypto.loadMasterKey(for: userId)
    }

    private func publish(_ state: ApplePrivacySettingsState) {
        self.state = state
        PIIPrivacySettingsStore.shared.update(state.detectorSettings)
    }

    private static func hashString(_ input: String) -> String {
        let digest = SHA256.hash(data: Data(input.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private static func pathComponent(_ value: String) -> String { value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? value }
}

struct SettingsHidePersonalDataView: View {
    @StateObject private var privacyService = ApplePrivacySettingsService.shared
    @StateObject private var enhancedPIIModelController = EnhancedPIIModelDownloadController.shared
    @State private var addEntryType: ApplePersonalDataType = .custom
    @State private var showAddEntrySheet = false
    @State private var pendingDeleteEntry: ApplePrivacyPersonalDataEntry?

    var body: some View {
        ZStack {
            OMSettingsPage(
                title: AppStrings.hidePersonalData,
                subtitle: AppStrings.privacyHidePersonalDataChats,
                showsHeader: false
            ) {
                if privacyService.isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, .spacing12)
                }

                OMSettingsSection {
                    OMSettingsToggleRow(
                        title: AppStrings.privacyHidePersonalData,
                        subtitle: AppStrings.privacyHidePersonalDataChats,
                        icon: "anonym",
                        isOn: masterBinding
                    )
                    .accessibilityIdentifier("settings-hide-personal-data-toggle")

                    Text(AppStrings.privacyHidePersonalDataDescription)
                        .font(.omP)
                        .foregroundStyle(Color.grey100)
                        .lineSpacing(3)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing4)
                }

                enhancedPIIModelSection

                if privacyService.state.detectionSettings.masterEnabled {
                    contactsSection
                    categorySection(title: AppStrings.privacyForEveryone, icon: "user", rows: Self.everyoneCategories)
                    categorySection(title: AppStrings.privacyForDevelopers, icon: "coding", rows: Self.developerCategories)
                    customSection
                    encryptionNote
                }

                if let error = privacyService.errorMessage {
                    OMSettingsSection(AppStrings.error, icon: "report_issue") {
                        Text(error)
                            .font(.omSmall)
                            .foregroundStyle(Color.error)
                            .padding(.horizontal, .spacing8)
                            .padding(.vertical, .spacing4)
                    }
                }
            }
            .task { await privacyService.load() }

            OMSheet(isPresented: $showAddEntrySheet, title: addEntryType.addTitle) {
                AddPersonalDataEntryForm(entryType: addEntryType) { title, textToHide, replaceWith in
                    Task {
                        await privacyService.addEntry(
                            type: addEntryType,
                            title: title,
                            textToHide: textToHide,
                            replaceWith: replaceWith
                        )
                        showAddEntrySheet = false
                    }
                }
            }

            if let pendingDeleteEntry {
                OMConfirmDialog(
                    title: AppStrings.delete,
                    message: AppStrings.confirmDeleteMemory,
                    confirmTitle: AppStrings.delete,
                    isDestructive: true,
                    onConfirm: {
                        Task {
                            await privacyService.deleteEntry(pendingDeleteEntry)
                            self.pendingDeleteEntry = nil
                        }
                    },
                    onCancel: { self.pendingDeleteEntry = nil }
                )
            }
        }
    }

    private var masterBinding: Binding<Bool> {
        Binding(
            get: { privacyService.state.detectionSettings.masterEnabled },
            set: { enabled in Task { await privacyService.setMasterEnabled(enabled) } }
        )
    }

    private var contactsSection: some View {
        OMSettingsSection(AppStrings.privacyContacts, icon: "contact") {
            ForEach(privacyService.state.contactEntries) { entry in
                entryRow(entry)
            }
            addEntryRow(type: .name)
            addEntryRow(type: .address)
            addEntryRow(type: .birthday)
        }
    }

    private var customSection: some View {
        OMSettingsSection(AppStrings.privacyCustom, icon: "create") {
            ForEach(privacyService.state.customEntries) { entry in
                entryRow(entry)
            }
            addEntryRow(type: .custom)
        }
    }

    private var encryptionNote: some View {
        Text(AppStrings.privacyEncryptionNote)
            .font(.omSmall.weight(.medium))
            .foregroundStyle(Color.grey60)
            .lineSpacing(3)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing5)
    }

    private var enhancedPIIModelSection: some View {
        OMSettingsSection(AppStrings.enhancedPIIModelTitle, icon: "shield") {
            VStack(alignment: .leading, spacing: .spacing4) {
                Text(AppStrings.enhancedPIIModelDescription)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .lineSpacing(3)

                if !enhancedPIIModelController.sizeCopy.isEmpty {
                    Text(enhancedPIIModelController.sizeCopy)
                        .font(.omXs.weight(.semibold))
                        .foregroundStyle(Color.grey60)
                }

                Text(enhancedPIIModelController.statusCopy)
                    .font(.omXs)
                    .foregroundStyle(Color.grey60)
                    .lineSpacing(2)

                Button {
                    Task { await enhancedPIIModelController.performPrimaryAction() }
                } label: {
                    Text(enhancedPIIModelController.actionTitle)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(enhancedPIIModelController.isActionDisabled)
                .accessibilityIdentifier("settings-enhanced-pii-model-action")
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing5)
        }
    }

    private func categorySection(title: String, icon: String, rows: [PrivacyCategoryRow]) -> some View {
        OMSettingsSection(title, icon: icon) {
            ForEach(rows) { row in
                OMSettingsToggleRow(
                    title: row.title,
                    icon: row.icon,
                    isOn: categoryBinding(row.id)
                )
                .accessibilityIdentifier("settings-pii-category-\(row.id)")
            }
        }
    }

    private func entryRow(_ entry: ApplePrivacyPersonalDataEntry) -> some View {
        HStack(spacing: 0) {
            Icon(entry.type.icon, size: 22)
                .foregroundStyle(Color.fontSecondary)
                .frame(width: 44, height: 44)
                .background(
                    LinearGradient(
                        colors: [Color.grey20, Color.grey30],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
                .padding(.trailing, .spacing6)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(entry.displayTitle)
                    .font(.omP.weight(.medium))
                    .foregroundStyle(LinearGradient.primary)
                Text(entry.replaceWith)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            }

            Spacer(minLength: .spacing4)

            OMIconButton(icon: "trash", label: AppStrings.delete, size: 32, iconSize: 16) {
                pendingDeleteEntry = entry
            }
            .padding(.trailing, .spacing3)

            OMToggle(isOn: entryBinding(entry))
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing2)
        .frame(minHeight: 40)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("settings-personal-data-entry-\(entry.id)")
    }

    private func addEntryRow(type: ApplePersonalDataType) -> some View {
        OMSettingsRow(
            title: type.addTitle,
            icon: "create",
            showsChevron: false,
            accessibilityIdentifier: "settings-add-personal-data-\(type.rawValue)"
        ) {
            addEntryType = type
            showAddEntrySheet = true
        }
    }

    private func categoryBinding(_ category: String) -> Binding<Bool> {
        Binding(
            get: { privacyService.state.isCategoryEnabled(category) },
            set: { enabled in Task { await privacyService.setCategory(category, enabled: enabled) } }
        )
    }

    private func entryBinding(_ entry: ApplePrivacyPersonalDataEntry) -> Binding<Bool> {
        Binding(
            get: { privacyService.state.entries.first(where: { $0.id == entry.id })?.enabled ?? entry.enabled },
            set: { enabled in Task { await privacyService.setEntryEnabled(entry, enabled: enabled) } }
        )
    }

    private struct PrivacyCategoryRow: Identifiable { let id: String; let title: String; let icon: String }

    @MainActor private static var everyoneCategories: [PrivacyCategoryRow] { [
        .init(id: "email_addresses", title: AppStrings.privacyEmailAddresses, icon: "mail"), .init(id: "phone_numbers", title: AppStrings.privacyPhoneNumbers, icon: "phone"),
        .init(id: "credit_card_numbers", title: AppStrings.privacyCreditCardNumbers, icon: "billing"), .init(id: "iban_bank_account", title: AppStrings.privacyIbanBankAccount, icon: "money"),
        .init(id: "tax_id_vat", title: AppStrings.privacyTaxIdVat, icon: "billing"), .init(id: "crypto_wallets", title: AppStrings.privacyCryptoWallets, icon: "coins"),
        .init(id: "social_security_numbers", title: AppStrings.privacySocialSecurityNumbers, icon: "lock"), .init(id: "passport_numbers", title: AppStrings.privacyPassportNumbers, icon: "lock"),
    ] }

    @MainActor private static var developerCategories: [PrivacyCategoryRow] { [
        .init(id: "api_keys", title: AppStrings.privacyApiKeys, icon: "secret"), .init(id: "jwt_tokens", title: AppStrings.privacyJwtTokens, icon: "secret"),
        .init(id: "private_keys", title: AppStrings.privacyPrivateKeys, icon: "lock"), .init(id: "generic_secrets", title: AppStrings.privacyGenericSecrets, icon: "secret"),
        .init(id: "ip_addresses", title: AppStrings.privacyIpAddresses, icon: "server"), .init(id: "mac_addresses", title: AppStrings.privacyMacAddresses, icon: "server"),
        .init(id: "user_at_hostname", title: AppStrings.privacyUserAtHostname, icon: "laptop"), .init(id: "home_folder", title: AppStrings.privacyHomeFolder, icon: "home"),
    ] }
}

private struct AddPersonalDataEntryForm: View {
    let entryType: ApplePersonalDataType
    let onSave: (String, String, String) -> Void

    @State private var title = ""
    @State private var textToHide = ""
    @State private var replaceWith = ""

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            labeledField(AppStrings.privacyFormTitle, text: $title)
            labeledField(AppStrings.privacyFormTextToHide, text: $textToHide)
            labeledField(AppStrings.privacyFormReplaceWith, text: $replaceWith)

            Text(AppStrings.privacyEncryptionNote)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .lineSpacing(3)

            Button {
                onSave(title, textToHide, replacementValue)
            } label: {
                Text(AppStrings.save)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || textToHide.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .onAppear {
            if replaceWith.isEmpty {
                replaceWith = entryType.defaultReplacement
            }
        }
    }

    private var replacementValue: String {
        let trimmed = replaceWith.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? entryType.defaultReplacement : trimmed
    }

    private func labeledField(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(label)
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
            TextField(label, text: text)
                .textFieldStyle(OMTextFieldStyle())
                .accessibilityLabel(label)
        }
    }
}

private extension KeyedDecodingContainer {
    func decodeFlexibleInt(forKey key: Key) -> Int? {
        if let value = try? decode(Int.self, forKey: key) { return value }
        if let value = try? decode(Double.self, forKey: key) { return Int(value) }
        if let value = try? decode(String.self, forKey: key) { return Int(value) }
        return nil
    }
}

private extension String { func prefixString(_ length: Int) -> String { String(prefix(length)) } }
