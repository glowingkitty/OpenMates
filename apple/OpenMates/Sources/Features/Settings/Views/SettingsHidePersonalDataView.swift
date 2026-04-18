// Hide personal data management — manage PII detection categories and custom entries.
// Mirrors the web app's privacy/SettingsHidePersonalData.svelte.
// Manages contacts (names, addresses, birthdays) and auto-detection category toggles.
// All user-defined entries are client-side encrypted.

import SwiftUI

struct SettingsHidePersonalDataView: View {
    @State private var isPIIEnabled = true
    @State private var autoDetectCategories: [PIICategory] = []
    @State private var contacts: [PersonalDataEntry] = []
    @State private var customEntries: [PersonalDataEntry] = []
    @State private var isLoading = true
    @State private var showAddSheet = false
    @State private var addEntryType: AddEntryType?
    @State private var error: String?

    struct PIICategory: Identifiable {
        let id: String
        let name: String
        let icon: String
        var isEnabled: Bool
    }

    struct PersonalDataEntry: Identifiable, Decodable {
        let id: String
        let type: String
        let label: String?
        let value: String?
        let createdAt: String?
    }

    enum AddEntryType: String, Identifiable {
        case name, address, birthday, custom
        var id: String { rawValue }
    }

    var body: some View {
        List {
            Section {
                Toggle("PII Detection", isOn: $isPIIEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: isPIIEnabled) { _, newValue in
                        savePIIEnabled(newValue)
                    }
                    .accessibleToggle("PII Detection", isOn: isPIIEnabled)

                Text(LocalizationManager.shared.text("settings.privacy.pii_description"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }

            if isPIIEnabled {
                Section("Auto-Detection") {
                    ForEach($autoDetectCategories) { $category in
                        Toggle(isOn: $category.isEnabled) {
                            Label(category.name, systemImage: category.icon)
                        }
                        .tint(Color.buttonPrimary)
                        .onChange(of: category.isEnabled) { _, _ in
                            saveCategories()
                        }
                        .accessibleToggle(category.name, isOn: category.isEnabled)
                    }
                }

                Section("Contacts") {
                    ForEach(contacts) { entry in
                        HStack {
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(entry.label ?? entry.type.capitalized)
                                    .font(.omSmall).fontWeight(.medium)
                                if let value = entry.value {
                                    Text(value)
                                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                                }
                            }
                            Spacer()
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityHint(LocalizationManager.shared.text("settings.swipe_left_to_delete"))
                        .swipeActions {
                            Button(role: .destructive) {
                                deleteEntry(entry.id)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }

                    Menu {
                        Button { addEntryType = .name } label: {
                            Label("Add Name", systemImage: "person")
                        }
                        .accessibleButton("Add Name")
                        Button { addEntryType = .address } label: {
                            Label("Add Address", systemImage: "mappin")
                        }
                        .accessibleButton("Add Address")
                        Button { addEntryType = .birthday } label: {
                            Label("Add Birthday", systemImage: "birthday.cake")
                        }
                        .accessibleButton("Add Birthday")
                    } label: {
                        Label("Add Contact Info", systemImage: "plus.circle")
                            .foregroundStyle(Color.buttonPrimary)
                    }
                    .accessibleButton("Add Contact Info")
                }

                Section("Custom Entries") {
                    ForEach(customEntries) { entry in
                        HStack {
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(entry.label ?? "Custom")
                                    .font(.omSmall).fontWeight(.medium)
                                if let value = entry.value {
                                    Text(value)
                                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                                }
                            }
                            Spacer()
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityHint(LocalizationManager.shared.text("settings.swipe_left_to_delete"))
                        .swipeActions {
                            Button(role: .destructive) {
                                deleteEntry(entry.id)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }

                    Button {
                        addEntryType = .custom
                    } label: {
                        Label("Add Custom Entry", systemImage: "plus.circle")
                            .foregroundStyle(Color.buttonPrimary)
                    }
                    .accessibleButton("Add Custom Entry")
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Hide Personal Data")
        .task { await loadData() }
        .sheet(item: $addEntryType) { type in
            AddPersonalDataEntryView(entryType: type) {
                Task { await loadData() }
            }
        }
    }

    private func loadData() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/privacy/personal-data"
            )

            isPIIEnabled = response["pii_enabled"]?.value as? Bool ?? true

            autoDetectCategories = [
                PIICategory(id: "email", name: "Email Addresses", icon: "envelope", isEnabled: true),
                PIICategory(id: "phone", name: "Phone Numbers", icon: "phone", isEnabled: true),
                PIICategory(id: "credit_card", name: "Credit Card Numbers", icon: "creditcard", isEnabled: true),
                PIICategory(id: "ssn", name: "Social Security Numbers", icon: "number", isEnabled: true),
                PIICategory(id: "ip_address", name: "IP Addresses", icon: "network", isEnabled: true),
            ]

            if let cats = response["auto_detect_categories"]?.value as? [String: Bool] {
                for i in autoDetectCategories.indices {
                    if let enabled = cats[autoDetectCategories[i].id] {
                        autoDetectCategories[i].isEnabled = enabled
                    }
                }
            }

            if let entries = response["entries"]?.value as? [[String: Any]] {
                let all = entries.compactMap { dict -> PersonalDataEntry? in
                    guard let id = dict["id"] as? String,
                          let type = dict["type"] as? String else { return nil }
                    return PersonalDataEntry(
                        id: id, type: type,
                        label: dict["label"] as? String,
                        value: dict["value"] as? String,
                        createdAt: dict["created_at"] as? String
                    )
                }
                contacts = all.filter { ["name", "address", "birthday"].contains($0.type) }
                customEntries = all.filter { $0.type == "custom" }
            }
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func savePIIEnabled(_ enabled: Bool) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/privacy/pii-toggle",
                body: ["enabled": enabled]
            ) as Data
        }
    }

    private func saveCategories() {
        var cats: [String: Bool] = [:]
        for cat in autoDetectCategories {
            cats[cat.id] = cat.isEnabled
        }
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/privacy/auto-detect-categories",
                body: ["categories": cats]
            ) as Data
        }
    }

    private func deleteEntry(_ id: String) {
        Task {
            try? await APIClient.shared.request(
                .delete, path: "/v1/settings/privacy/personal-data/\(id)"
            ) as Data
            contacts.removeAll { $0.id == id }
            customEntries.removeAll { $0.id == id }
        }
    }
}

// MARK: - Add personal data entry sheet

struct AddPersonalDataEntryView: View {
    let entryType: SettingsHidePersonalDataView.AddEntryType
    let onSaved: () -> Void
    @Environment(\.dismiss) var dismiss
    @State private var label = ""
    @State private var value = ""
    @State private var isSaving = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    switch entryType {
                    case .name:
                        TextField("Full name", text: $value)
                            .textContentType(.name)
                            .accessibleInput("Full name")
                    case .address:
                        TextField("Label (e.g. Home)", text: $label)
                            .accessibleInput("Label", hint: LocalizationManager.shared.text("settings.privacy.address_label_hint"))
                        TextEditor(text: $value)
                            .frame(minHeight: 80)
                            .textContentType(.fullStreetAddress)
                            .accessibilityLabel("Address")
                            .accessibilityHint(LocalizationManager.shared.text("settings.privacy.address_hint"))
                    case .birthday:
                        TextField("Date of birth", text: $value)
                            .accessibleInput("Date of birth")
                    case .custom:
                        TextField("Label", text: $label)
                            .accessibleInput("Label")
                        TextField("Value to hide", text: $value)
                            .accessibleInput("Value to hide", hint: LocalizationManager.shared.text("settings.privacy.custom_value_hint"))
                    }
                }

                Section {
                    Text(LocalizationManager.shared.text("settings.privacy.entry_encryption_description"))
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }
            .navigationTitle("Add \(entryType.rawValue.capitalized)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .accessibleButton(AppStrings.cancel)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }
                        .disabled(value.isEmpty || isSaving)
                        .accessibleButton(AppStrings.save)
                }
            }
        }
    }

    private func save() {
        isSaving = true
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/privacy/personal-data",
                    body: [
                        "type": entryType.rawValue,
                        "label": label,
                        "value": value
                    ]
                )
                onSaved()
                AccessibilityAnnouncement.announce(AppStrings.success)
                dismiss()
            } catch {
                AccessibilityAnnouncement.announce(error.localizedDescription)
                print("[Settings] Add personal data error: \(error)")
            }
            isSaving = false
        }
    }
}
