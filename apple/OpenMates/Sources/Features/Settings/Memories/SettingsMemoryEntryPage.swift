// Create / edit page of one Memory (Settings > Memories > Create memory, or a
// tapped row): title, memory, when to use, app, load mode, start and expiry
// date, then Cancel / Delete / Save like the web. A document this client
// cannot parse shows its stored text read-only and can only be deleted.
// Values go to the core unchanged; the core validates and stores them.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/MemoryEntryPage.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsSectionHeading.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsInput.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsTextarea.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsDropdown.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsInfoBox.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsButtonGroup.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.lifecycle.encrypted-crud, app-memories.load-modes, app-memories.compatibility.legacy-documents, app-memories.surface.semantic-parity, app-memories.suggestions.post-processor, app-memories.references.embeds

import SwiftUI

struct SettingsMemoryEntryPage: View {
    /// `nil` on the create page.
    let row: SettingsMemoryRow?
    let saving: Bool
    let error: String?
    let onSave: (SettingsMemoryDraft) -> Void
    let onCancel: () -> Void
    let onDelete: () -> Void

    @State private var draft: SettingsMemoryDraft
    /// An unsaved suggestion from a chat Recommendation (web `isDraft`).
    private let isDraft: Bool

    init(row: SettingsMemoryRow?, saving: Bool, error: String?,
         initialDraft: SettingsMemoryDraft? = nil,
         onSave: @escaping (SettingsMemoryDraft) -> Void, onCancel: @escaping () -> Void, onDelete: @escaping () -> Void) {
        self.row = row; self.saving = saving; self.error = error
        self.onSave = onSave; self.onCancel = onCancel; self.onDelete = onDelete
        // `initialDraft`: an unsaved draft from a chat Recommendation replaces the stored fields.
        _draft = State(initialValue: initialDraft ?? row?.record.fields.map(SettingsMemoryDraft.init) ?? SettingsMemoryDraft())
        isDraft = initialDraft != nil
    }

    /// Fields the suggestion changes against the stored Memory, from the core.
    private var draftChanges: [MemoryFieldChangeRecord] {
        guard isDraft, let saved = row?.record.fields else { return [] }
        return diffMemoryDraftFields(saved: saved, draft: draft.fields)
    }

    private var isNew: Bool { row == nil }
    private var isReadable: Bool { row?.isReadable ?? true }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            if isReadable { editor } else { unreadable }
            if let error {
                OMSettingsInfoBox(kind: .warning, message: error, identifier: "memory-error")
            }
            buttons
        }
        .disabled(saving)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("memory-entry-page")
    }

    @ViewBuilder private var editor: some View {
        if isDraft {
            MemoryDraftBanner()
            MemoryDraftDiffView(changes: draftChanges)
        }
        OMSettingsSectionHeading(title: AppStrings.memoriesFieldTitle, icon: "text")
            .accessibilityIdentifier("memory-field-title")
        OMSettingsTextInput(label: AppStrings.memoriesFieldTitle, placeholder: "", value: $draft.title, identifier: "rule-title")

        OMSettingsSectionHeading(title: AppStrings.memoriesFieldBody, icon: "settings_memories")
            .accessibilityIdentifier("memory-field-memory")
        OMSettingsTextInput(label: AppStrings.memoriesFieldBody, placeholder: AppStrings.memoriesBodyPlaceholder,
                            value: $draft.body, identifier: "rule-body", multiline: true)
        MemoryReferencesHint()

        OMSettingsSectionHeading(title: AppStrings.memoriesWhenToUseOptional, icon: "focus")
            .accessibilityIdentifier("memory-field-when-to-use")
        OMSettingsTextInput(label: AppStrings.memoriesWhenToUse, placeholder: "", value: $draft.whenToUse,
                            identifier: "rule-when-to-use", multiline: true)
        OMSettingsInfoBox(message: AppStrings.memoriesWhenToUseHint, identifier: "memory-when-to-use-hint")

        OMSettingsSectionHeading(title: AppStrings.memoriesApp, icon: "app")
            .accessibilityIdentifier("memory-field-app")
        OMDropdown(title: AppStrings.memoriesApp, options: appOptions, selection: appSelection)
            .padding(.horizontal, .spacing5)
            .accessibilityIdentifier("memory-app")

        OMSettingsSectionHeading(title: AppStrings.memoriesLoadMode, icon: "settings")
            .accessibilityIdentifier("memory-field-load-mode")
        OMDropdown(title: AppStrings.memoriesLoadMode, options: loadModeOptions, selection: loadModeSelection)
            .padding(.horizontal, .spacing5)
            .accessibilityIdentifier("memory-load-mode")

        OMSettingsSectionHeading(title: AppStrings.memoriesValidFrom, icon: "calendar")
            .accessibilityIdentifier("memory-field-valid-from-heading")
        dateField($draft.validFrom, label: AppStrings.memoriesValidFrom, identifier: "memory-valid-from")
        OMSettingsSectionHeading(title: AppStrings.memoriesValidUntil, icon: "calendar")
            .accessibilityIdentifier("memory-field-valid-until-heading")
        dateField($draft.validUntil, label: AppStrings.memoriesValidUntil, identifier: "memory-valid-until")
    }

    /// The stored text of a document this client cannot parse (read-only).
    @ViewBuilder private var unreadable: some View {
        OMSettingsSectionHeading(title: AppStrings.memoriesFieldBody, icon: "document")
        Text(row?.record.document ?? "")
            .font(.omSmall)
            .foregroundStyle(Color.fontSecondary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.spacing8)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .padding(.horizontal, .spacing5)
            .accessibilityIdentifier("memory-unreadable-document")
    }

    /// Web SettingsButtonGroup align="space-between": Cancel, Delete, Save.
    private var buttons: some View {
        HStack(spacing: .spacing4) {
            Button(AppStrings.cancel, action: onCancel)
                .buttonStyle(OMSettingsButtonStyle(secondary: true))
                .accessibilityIdentifier("rule-cancel")
            Spacer(minLength: 0)
            if !isNew {
                Button(action: onDelete) {
                    Text(AppStrings.delete).foregroundStyle(Color.error)
                }
                .buttonStyle(OMSettingsButtonStyle(secondary: true))
                .accessibilityIdentifier("memory-delete")
            }
            if isReadable {
                Spacer(minLength: 0)
                Button {
                    onSave(draft)
                } label: {
                    if saving { ProgressView().controlSize(.small) } else { Text(AppStrings.save) }
                }
                .buttonStyle(OMSettingsButtonStyle())
                .accessibilityIdentifier("rule-save")
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.top, .spacing8)
    }

    // MARK: - Fields

    private var loadModeOptions: [OMDropdownOption] {
        [OMDropdownOption("auto_include", label: AppStrings.memoriesLoadModeAutoInclude),
         OMDropdownOption("ask_first", label: AppStrings.memoriesLoadModeAskFirst),
         OMDropdownOption("mention_only", label: AppStrings.memoriesLoadModeMentionOnly)]
    }

    private var loadModeSelection: Binding<String> {
        Binding(
            get: {
                switch draft.loadMode {
                case .autoInclude: return "auto_include"
                case .askFirst: return "ask_first"
                case .mentionOnly: return "mention_only"
                }
            },
            set: { value in
                switch value {
                case "ask_first": draft.loadMode = .askFirst
                case "mention_only": draft.loadMode = .mentionOnly
                default: draft.loadMode = .autoInclude
                }
            })
    }

    /// None plus the Memory's own app (kept as read). The web also offers
    /// every discoverable app from its app catalog store.
    private var appOptions: [OMDropdownOption] {
        var options = [OMDropdownOption("", label: AppStrings.memoriesAppNone)]
        if let appId = row?.record.fields?.appId, !appId.isEmpty {
            options.append(OMDropdownOption(appId, label: Self.appName(appId), iconAppId: appId))
        }
        return options
    }

    private var appSelection: Binding<String> {
        Binding(get: { draft.appId ?? "" }, set: { draft.appId = $0.isEmpty ? nil : $0 })
    }

    /// Translated app name (`apps.<id>`), the id when the app is unknown.
    static func appName(_ appId: String) -> String {
        let key = "apps.\(appId)"
        let name = AppStrings.localized(key)
        return name == key ? appId : name
    }

    /// Web `<input type="date">`: empty until set, clearable.
    private func dateField(_ value: Binding<String?>, label: String, identifier: String) -> some View {
        HStack(spacing: .spacing4) {
            if let day = value.wrappedValue {
                DatePicker(label, selection: Binding(
                    get: { SettingsMemoryDocumentsModel.day(day) ?? Date() },
                    set: { value.wrappedValue = SettingsMemoryDocumentsModel.dayString($0) }),
                    displayedComponents: .date)
                    .labelsHidden()
                    .datePickerStyle(.compact)
                    .accessibilityIdentifier(identifier)
                OMIconButton(icon: "close", label: AppStrings.delete) { value.wrappedValue = nil }
                    .accessibilityIdentifier("\(identifier)-clear")
            } else {
                Button(AppStrings.commonDate) { value.wrappedValue = SettingsMemoryDocumentsModel.dayString(Date()) }
                    .buttonStyle(OMSettingsButtonStyle(secondary: true))
                    .accessibilityIdentifier(identifier)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, .spacing5)
    }
}
