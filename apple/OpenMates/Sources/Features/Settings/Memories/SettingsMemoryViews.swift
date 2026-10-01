// Web source: frontend/packages/ui/src/components/settings/AppSettingsMemoriesCategory.svelte,
// AppSettingsMemoriesEntryDetail.svelte, AppSettingsMemoriesCreateEntry.svelte,
// ChatPreviewCard.svelte and settings/elements/SettingsSectionHeading.svelte.
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.surface.semantic-parity
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.navigation.parent-return, settings-ui.parity.web-apple-shell

import SwiftUI

struct SettingsMemoryIcon: View {
    let name: String
    var size: CGFloat = 44
    var body: some View {
        Icon(name, size: size / 2).foregroundStyle(Color.fontButton)
            .frame(width: size, height: size)
            .background(LinearGradient.iconMemory, in: RoundedRectangle(cornerRadius: .radius4))
            .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(Color.fontButton, lineWidth: 1))
    }
}

struct SettingsMemoryCategoryView: View {
    let category: SettingsMemoryCategory
    @ObservedObject var service: SettingsMemoryService
    let onNavigate: (SettingsMemoryRoute) -> Void
    let onOpenExampleChat: (String) -> Void
    var embedRecords: [String: EmbedRecord] = [:]
    var onOpenEmbed: ((EmbedRecord) -> Void)? = nil
    private var entries: [SettingsMemoryEntry] { service.isAuthenticated ? service.entries(in: category) : [] }
    private var chats: [SettingsMemoryChatExample] {
        #if DEBUG
        if category.examples.contains(where: { $0.id == "example-travel-preferred-activities-0" }) { return [] }
        #endif
        return SettingsMemoryChatExamples.examples(app: category.appId, category: category.categoryId)
    }
    var body: some View {
        OMSettingsPage(title: "", showsHeader: false, showsFooter: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                if service.isAuthenticated {
                    OMSettingsSectionHeading(title: AppStrings.localized("settings.app_settings_memories.settings_and_memories"), icon: "user")
                    if entries.isEmpty { Text(AppStrings.localized("settings.app_settings_memories.no_entries_yet")).font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.spacing4) }
                    ForEach(entries) { entry in
                        HStack(spacing: .spacing4) {
                            memoryRow(entry)
                            OMIconButton(icon: "edit", label: AppStrings.edit, iconSize: 18) {
                                onNavigate(.editor(category.appId, category.categoryId, entry.id))
                            }.accessibilityIdentifier("settings-memory-edit-\(entry.id)")
                        }
                        SettingsMemorySavedEmbedView(entry: entry, embedRecords: embedRecords, onOpen: onOpenEmbed)
                    }
                    OMSettingsRow(title: AppStrings.localized("common.add_entry"), icon: "create", accessibilityIdentifier: "settings-memory-add") {
                        onNavigate(.editor(category.appId, category.categoryId, nil))
                    }.padding(.top, .spacing2)
                }
                if !chats.isEmpty {
                    OMSettingsSectionHeading(title: AppStrings.localized("settings.app_settings_memories.examples"), icon: "chat")
                    Text(AppStrings.localized("settings.app_store.skills.examples_prefix"))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.bottom, .spacing10)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: .spacing6) {
                            ForEach(chats) { chat in
                                SettingsMemoryChatCard(example: chat, appID: category.appId) { onOpenExampleChat(chat.id) }
                            }
                        }.padding(.vertical, .spacing1)
                    }
                    .accessibilityIdentifier("app-store-memory-example-chats")
                } else if !category.examples.isEmpty && (!service.isAuthenticated || entries.isEmpty) {
                    OMSettingsSectionHeading(title: AppStrings.localized("settings.app_settings_memories.examples"), icon: "chat")
                    ForEach(category.examples) { example in memoryRow(example) }
                }
            }.padding(.spacing6 + .spacing1).frame(maxWidth: 1400, alignment: .leading).frame(maxWidth: .infinity)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("app-settings-memories-category")
        }
    }
    private func memoryRow(_ entry: SettingsMemoryEntry) -> some View {
        OMSettingsRow(title: entry.title(in: category), subtitleBottom: entry.isExample ? nil : subtitle(entry),
            icon: category.iconName, iconGradient: .iconMemory,
            accessibilityIdentifier: "settings-memory-entry-\(entry.id)") {
            onNavigate(.entry(category.appId, category.categoryId, entry.id))
        }
    }
    private func subtitle(_ entry: SettingsMemoryEntry) -> String {
        let age = max(0, Int(Date().timeIntervalSince1970) - entry.updatedAt)
        let time = age < 60 ? AppStrings.memoryJustNow : age < 3600 ? AppStrings.chatHeaderMinutesAgo(count: age / 60) : age < 86400 ? AppStrings.memoryRelativeTime(.hours, count: age / 3600) : AppStrings.memoryRelativeTime(.days, count: age / 86400)
        return [entry.subtitle(in: category), time].compactMap { $0 }.joined(separator: " • ")
    }
}

private struct SettingsMemoryChatCard: View {
    let example: SettingsMemoryChatExample
    let appID: String
    let onOpen: () -> Void
    var body: some View {
        Button(action: onOpen) {
            ZStack {
                AppIconView.gradient(forAppId: appID)
                Icon(example.icon, size: 80).foregroundStyle(Color.fontButton.opacity(0.14)).rotationEffect(.degrees(-20)).offset(x: -120, y: -70)
                Icon(example.icon, size: 80).foregroundStyle(Color.fontButton.opacity(0.14)).rotationEffect(.degrees(20)).offset(x: 120, y: 70)
                VStack(spacing: .spacing2) {
                    Icon(example.icon, size: 32).foregroundStyle(Color.fontButton)
                    Text(example.title).font(.omP.weight(.bold)).foregroundStyle(Color.fontButton).multilineTextAlignment(.center).lineLimit(2)
                    Text(example.summary).font(.omXs).foregroundStyle(Color.fontButton.opacity(0.85)).multilineTextAlignment(.center).lineLimit(4)
                }.padding(.horizontal, .spacing12).padding(.vertical, .spacing8)
            }.frame(width: 300, height: 200).clipShape(RoundedRectangle(cornerRadius: .spacing16 + .spacing1))
        }.buttonStyle(.plain).accessibilityIdentifier("app-store-example-chat-card-\(example.id)")
    }
}

struct SettingsMemoryEntryDetailView: View {
    let category: SettingsMemoryCategory
    let entry: SettingsMemoryEntry
    @ObservedObject var service: SettingsMemoryService
    let onEdit: () -> Void
    let onDeleted: () -> Void
    var embedRecords: [String: EmbedRecord] = [:]
    var onOpenEmbed: ((EmbedRecord) -> Void)? = nil
    @State private var confirmingDelete = false
    private var visibleFields: [String] {
        if let schema = category.schema, !schema.inputFields.isEmpty {
            return schema.inputFields.map(\.name).filter { !entry.isExample || entry.fields[$0] != nil }
        }
        return entry.fields.keys.filter { !SettingsMemorySchema.internalFields.contains($0) }.sorted()
    }
    var body: some View {
        ZStack {
            OMSettingsPage(title: "", showsHeader: false, showsFooter: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0) {
                VStack(alignment: .leading, spacing: 0) {
                    if visibleFields.isEmpty {
                        Text(entry.key).font(.omP).foregroundStyle(Color.fontPrimary).padding(.vertical, .spacing8)
                    } else {
                        ForEach(Array(visibleFields.enumerated()), id: \.element) { index, name in
                            VStack(alignment: .leading, spacing: .spacing2) {
                                OMSettingsSectionHeading(title: fieldLabel(name), icon: category.iconName)
                                Text(display(entry.fields[name])).font(.omP).foregroundStyle(entry.fields[name] == nil ? Color.fontTertiary : Color.fontPrimary)
                                    .frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                            }.padding(.top, index == 0 ? 0 : .spacing8).padding(.bottom, .spacing8)
                        }
                    }
                    SettingsMemorySavedEmbedView(entry: entry, embedRecords: embedRecords, onOpen: onOpenEmbed)
                    if !entry.isExample {
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text("Last updated: \(date(entry.updatedAt))")
                            Text("Created: \(date(entry.createdAt))")
                        }.font(.omXs).foregroundStyle(Color.fontTertiary).padding(.top, .spacing12).padding(.bottom, .spacing6)
                    }
                    if !entry.isExample && service.isAuthenticated {
                        HStack(spacing: .spacing8) {
                            Button(AppStrings.edit, action: onEdit).buttonStyle(OMPrimaryButtonStyle()).accessibilityIdentifier("settings-memory-edit")
                            OMIconButton(icon: "delete", label: AppStrings.delete, iconSize: 20) { confirmingDelete = true }
                                .accessibilityIdentifier("settings-memory-delete")
                        }.disabled(service.state == .pending).padding(.top, .spacing8)
                    }
                    SettingsMemoryEncryptionNotice().padding(.top, .spacing12)
                    if case .error = service.state { Text(AppStrings.error).font(.omSmall).foregroundStyle(Color.error) }
                    if service.state == .conflict { Text(AppStrings.error).font(.omSmall).foregroundStyle(Color.error) }
                }.padding(.spacing6 + .spacing1).frame(maxWidth: 1400, alignment: .leading).frame(maxWidth: .infinity)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("settings-memory-detail")
            }
            if confirmingDelete {
                OMConfirmDialog(title: AppStrings.delete, message: AppStrings.confirmDeleteMemory, confirmTitle: AppStrings.delete,
                    isDestructive: true, onConfirm: {
                        confirmingDelete = false
                        Task { if await service.delete(entry) { onDeleted() } }
                    }, onCancel: { confirmingDelete = false })
            }
        }
    }
    private func fieldLabel(_ key: String) -> String { category.schema?.fields.first { $0.name == key }?.label ?? key.replacingOccurrences(of: "_", with: " ").capitalized }
    private func display(_ value: SettingsMemoryValue?) -> String {
        guard let value, value != .null, value != .string("") else { return "Not set" }
        if case .bool(let enabled) = value { return enabled ? "Yes" : "No" }
        return value.display
    }
    private func date(_ timestamp: Int) -> String { Date(timeIntervalSince1970: Double(timestamp)).formatted(date: .abbreviated, time: .shortened) }
}

struct SettingsMemoryEncryptionNotice: View {
    var body: some View {
        HStack(spacing: .spacing2) {
            Icon("lock", size: 14)
            Text(AppStrings.encryptionNotice)
        }.font(.omXs).foregroundStyle(Color.fontSecondary).frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SettingsMemoryEditorView: View {
    let category: SettingsMemoryCategory
    let entry: SettingsMemoryEntry?
    @ObservedObject var service: SettingsMemoryService
    let onSaved: () -> Void
    let onCancel: () -> Void
    @State private var draft: SettingsMemoryDraft
    @State private var error: String?
    @State private var saving = false
    @State private var expandedEnum: String?

    init(category: SettingsMemoryCategory, entry: SettingsMemoryEntry?, service: SettingsMemoryService,
         onSaved: @escaping () -> Void, onCancel: @escaping () -> Void) {
        self.category = category; self.entry = entry; self.service = service; self.onSaved = onSaved; self.onCancel = onCancel
        _draft = State(initialValue: SettingsMemoryDraft(category: category, entry: entry))
    }
    var body: some View {
        OMSettingsPage(title: "", showsHeader: false, showsFooter: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0) {
            VStack(alignment: .leading, spacing: .spacing12) {
                if draft.usesSchema {
                    ForEach(category.schema?.inputFields ?? [], id: \.name) { field in fieldInput(field) }
                } else {
                    VStack(alignment: .leading, spacing: .spacing4) {
                        Text("Key").font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                        TextField(AppStrings.memoryKeyRequired, text: $draft.key).textFieldStyle(OMTextFieldStyle()).accessibilityIdentifier("settings-memory-key")
                    }
                    VStack(alignment: .leading, spacing: .spacing4) {
                        Text("Value").font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                        TextField(AppStrings.memoryValueRequired, text: $draft.genericValue, axis: .vertical).lineLimit(3...8)
                            .textFieldStyle(OMTextFieldStyle()).accessibilityIdentifier("settings-memory-value")
                    }
                }
                if let error { Text(error).font(.omSmall).foregroundStyle(Color.error).accessibilityIdentifier("settings-memory-editor-error") }
                HStack(spacing: .spacing4) {
                    Button(AppStrings.cancel, action: onCancel).buttonStyle(OMSecondaryButtonStyle()).disabled(saving)
                    Button(saving ? AppStrings.memorySaving : AppStrings.save) { save() }.buttonStyle(OMPrimaryButtonStyle())
                        .disabled(saving || !service.isAuthenticated || entry?.isExample == true || (entry != nil && !hasChanges))
                        .accessibilityIdentifier("settings-memory-save")
                }
                SettingsMemoryEncryptionNotice()
            }.padding(.spacing6 + .spacing1).frame(maxWidth: 1400, alignment: .leading).frame(maxWidth: .infinity)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("settings-memory-editor")
        }
    }
    private var hasChanges: Bool {
        let original = SettingsMemoryDraft(category: category, entry: entry)
        return draft.inputs != original.inputs || draft.key != original.key || draft.genericValue != original.genericValue
    }
    private func input(_ field: SettingsMemoryField) -> Binding<String> {
        Binding(get: { draft.inputs[field.name] ?? "" }, set: { draft.inputs[field.name] = $0; error = nil })
    }
    @ViewBuilder private func fieldInput(_ field: SettingsMemoryField) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing1) {
                Text(field.label).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                if category.schema?.required.contains(field.name) == true { Text("*").foregroundStyle(Color.error) }
            }
            if !field.enumValues.isEmpty {
                Button { expandedEnum = expandedEnum == field.name ? nil : field.name } label: {
                    HStack { Text(draft.inputs[field.name].flatMap { $0.isEmpty ? nil : $0 } ?? field.description); Spacer(); Icon("chevron-down", size: 16) }
                        .font(.omSmall).foregroundStyle(Color.fontPrimary).padding(.spacing6)
                        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius8))
                        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey30))
                }.buttonStyle(.plain).accessibilityIdentifier("settings-memory-field-\(field.name)")
                if expandedEnum == field.name {
                    VStack(spacing: 0) {
                        ForEach(field.enumValues, id: \.self) { value in
                            OMSettingsRow(title: value, showsChevron: false, accessibilityIdentifier: "settings-memory-option-\(field.name)-\(value)") {
                                draft.inputs[field.name] = value; expandedEnum = nil; error = nil
                            }
                        }
                    }.background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius5))
                }
            } else if field.type == "boolean" {
                OMToggle(isOn: Binding(get: { draft.inputs[field.name] == "true" }, set: { draft.inputs[field.name] = $0 ? "true" : "false" }))
                    .accessibilityIdentifier("settings-memory-field-\(field.name)")
            } else {
                TextField(field.description, text: input(field), axis: field.multiline || ["array", "object"].contains(field.type) ? .vertical : .horizontal)
                    .lineLimit(field.multiline || ["array", "object"].contains(field.type) ? 3...8 : 1...1)
                    .textFieldStyle(OMTextFieldStyle()).accessibilityIdentifier("settings-memory-field-\(field.name)")
                if ["array", "object"].contains(field.type) {
                    Text("JSON \(field.type)").font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }
        }
    }
    private func save() {
        guard !saving else { return }
        do {
            let payload = try draft.payload(); saving = true; error = nil
            Task {
                let saved = await service.save(entry: entry, category: category, key: payload.key, fields: payload.fields)
                saving = false
                if saved { onSaved() } else { error = AppStrings.error }
            }
        } catch { self.error = error.localizedDescription }
    }
}

// Reuse the resolved native embed and canonical preview/fullscreen flow. Unresolved
// IDs are omitted, matching the web memory embed preview's absent-content state.
struct SettingsMemorySavedEmbedView: View {
    let entry: SettingsMemoryEntry
    let embedRecords: [String: EmbedRecord]
    let onOpen: ((EmbedRecord) -> Void)?
    var body: some View {
        if !entry.isExample, let id = entry.fields["embed_id"]?.string,
           let embed = embedRecords[id], let onOpen {
            EmbedPreviewCard(embed: embed, allEmbedRecords: embedRecords, variant: .compact, onTap: { onOpen(embed) })
                .accessibilityIdentifier("memory-embed-preview")
                .padding(.leading, .spacing24 + .spacing6).padding(.bottom, .spacing6)
        }
    }
}

// Existing relative-time translations; counts retain the web's minute/hour/day thresholds.
extension AppStrings {
    enum MemoryRelativeTimeUnit: String { case hours, days }
    static var memoryJustNow: String { localized("common.just_now") }
    static func memoryRelativeTime(_ unit: MemoryRelativeTimeUnit, count: Int) -> String {
        LocalizationManager.shared.text("settings.sessions.\(unit.rawValue)_ago", replacements: ["n": String(count)])
    }
}
