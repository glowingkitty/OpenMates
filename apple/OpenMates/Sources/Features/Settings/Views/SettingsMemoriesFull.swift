// Settings > Memories: the list of the account's personal Memories (sorted by
// most recently modified, search, sort, Create memory, Renew for expired
// ones) and, as sub-pages, the create page and one Memory's page. Data comes
// from the Rust core (`CoreSession` memory documents); opening the screen runs
// the core's expiry sweep first. Signed out shows only the help text and the
// app discovery link, like the web.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsMemoriesHub.svelte
//          frontend/packages/ui/src/components/settings/MemoriesEditor.svelte
//          frontend/packages/ui/src/components/settings/MemoryList.svelte
//          frontend/packages/ui/src/components/settings/SearchSortBar.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsItem.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsSectionHeading.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsInfoBox.svelte
// CSS:     SettingsMemoriesHub.svelte <style>: .settings-memories-hub (padding 14px, max-width 1400px),
//          .encryption-notice, .discover-link-section (border-top grey-20)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.lifecycle.encrypted-crud, app-memories.expiry.client-enforced, app-memories.compatibility.legacy-documents, app-memories.surface.semantic-parity
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.navigation.parent-return, settings-ui.parity.web-apple-shell

import SwiftUI

struct SettingsMemoriesFullView: View {
    @Environment(\.omSettingsScrollOffsetHandler) private var scrollOffsetHandler
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var model: SettingsMemoryDocumentsModel
    @State private var page: SettingsMemoryPage
    var onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)?
    var onDiscoverApps: (() -> Void)?

    init(deepLinkPath: String? = nil,
         onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)? = nil,
         onDiscoverApps: (() -> Void)? = nil,
         model: SettingsMemoryDocumentsModel? = nil) {
        self.onChildNavigationChanged = onChildNavigationChanged
        self.onDiscoverApps = onDiscoverApps
        _page = State(initialValue: deepLinkPath.flatMap(SettingsMemoryPage.init(path:)) ?? .list)
        _model = StateObject(wrappedValue: model ?? SettingsMemoryDocumentsModel(store: CoreSession.shared))
    }

    private var isAuthenticated: Bool { authManager.currentUser != nil }
    private var accountIdentity: String { authManager.currentUser?.id ?? "guest" }

    var body: some View {
        OMSettingsPage(title: "", showsHeader: false, showsFooter: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0) {
            Group {
                switch page {
                case .list: listPage
                case .create: entryPage(row: nil)
                case .entry(let id):
                    if let row = model.row(for: id) { entryPage(row: row) }
                    else if model.state == .loading || model.state == .idle { stateText(AppStrings.loading) }
                    else { stateText(model.errorMessage ?? AppStrings.memoriesNotFound) }
                }
            }
            // Web .settings-memories-hub: 14px padding, max-width 1400px, centered.
            .padding(.spacing6 + .spacing1)
            .frame(maxWidth: 1400, alignment: .leading).frame(maxWidth: .infinity)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-memories-page")
        .task(id: accountIdentity) {
            guard isAuthenticated else { model.cancel(); return }
            await model.open()
            publishChildNavigation()
        }
        .onChange(of: page) { _, _ in scrollOffsetHandler.callback?(0); publishChildNavigation() }
        .onChange(of: model.saving) { _, _ in publishChildNavigation() }
        .onAppear { publishChildNavigation() }
        .onDisappear { model.cancel(); onChildNavigationChanged?(nil) }
    }

    // MARK: - List

    private var listPage: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(AppStrings.memoriesSourcesHelp)
                .font(.omSmall).foregroundStyle(Color.fontSecondary).lineSpacing(5)
                .padding(.horizontal, .spacing4).padding(.bottom, .spacing8)
                .accessibilityIdentifier("settings-memories-sources-help")
            if isAuthenticated {
                VStack(alignment: .leading, spacing: .spacing4) {
                    OMSettingsSectionHeading(title: AppStrings.memoriesPrivate, icon: "settings_memories")
                    memoryList
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("settings-memories-private")
            }
            Divider().overlay(Color.grey20).padding(.top, .spacing12).padding(.bottom, .spacing4)
            OMSettingsRow(title: AppStrings.memoriesDiscoverApps, icon: "app",
                          accessibilityIdentifier: "settings-memory-discover-apps") { onDiscoverApps?() }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-memories-hub")
    }

    /// Web MemoryList.svelte.
    private var memoryList: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack {
                Spacer(minLength: 0)
                Button(AppStrings.memoriesCreate) { open(.create) }
                    .buttonStyle(OMSettingsButtonStyle())
                    .disabled(model.saving || model.state == .loading)
                    .accessibilityIdentifier("memory-create")
            }
            .padding(.horizontal, .spacing5)

            if let notice = model.savedNotice {
                OMSettingsInfoBox(kind: .success, message: notice, identifier: "rule-saved-notice")
            }

            switch model.state {
            case .idle, .loading:
                stateText(AppStrings.loading)
            case .failed where model.rows.isEmpty:
                VStack(alignment: .leading, spacing: .spacing4) {
                    Button(AppStrings.retry) { Task { await model.reload() } }
                        .buttonStyle(OMSettingsButtonStyle(secondary: true))
                        .accessibilityIdentifier("memory-retry")
                }
                .padding(.horizontal, .spacing5)
            case .loaded where model.rows.isEmpty:
                stateText(AppStrings.memoriesEmpty).accessibilityIdentifier("memory-empty")
            default:
                searchSortBar
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(model.visibleRows) { row in
                        memoryRow(row)
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("memory-list")
            }

            if let error = model.errorMessage {
                OMSettingsInfoBox(kind: .warning, message: error, identifier: "memory-error")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("memory-list-page")
    }

    /// Web SearchSortBar.svelte: search field and sort dropdown.
    private var searchSortBar: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            OMSettingsTextInput(label: AppStrings.search, placeholder: AppStrings.search,
                                value: $model.query, identifier: "memory-search")
            OMDropdown(title: AppStrings.memoriesSortLabel, options: [
                OMDropdownOption(SettingsMemorySort.modified.rawValue, label: AppStrings.memoriesSortModified),
                OMDropdownOption(SettingsMemorySort.added.rawValue, label: AppStrings.memoriesSortAdded),
                OMDropdownOption(SettingsMemorySort.title.rawValue, label: AppStrings.memoriesSortTitle),
            ], selection: Binding(
                get: { model.sort.rawValue },
                set: { model.sort = SettingsMemorySort(rawValue: $0) ?? .modified }))
            .padding(.horizontal, .spacing5)
            .accessibilityIdentifier("memory-sort")
        }
    }

    @ViewBuilder private func memoryRow(_ row: SettingsMemoryRow) -> some View {
        let appId = row.record.fields?.appId.flatMap { $0.isEmpty ? nil : $0 }
        OMSettingsRow(title: row.title, subtitleTop: model.subtitle(for: row),
                      icon: appId.map(AppIconView.iconName(forAppId:)) ?? "settings_memories",
                      iconGradient: appId.map(AppIconView.gradient(forAppId:)),
                      accessibilityIdentifier: "memory-row") {
            open(.entry(row.id))
        }
        .disabled(model.saving)
        if row.record.expired, row.isReadable {
            HStack {
                Button(AppStrings.memoriesRenew) { Task { await model.renew(row) } }
                    .buttonStyle(OMSettingsButtonStyle(secondary: true))
                    .disabled(model.saving)
                    .accessibilityIdentifier("memory-renew")
                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing5)
        }
    }

    // MARK: - Create / entry page

    private func entryPage(row: SettingsMemoryRow?) -> some View {
        SettingsMemoryEntryPage(
            row: row, saving: model.saving, error: model.errorMessage,
            onSave: { draft in
                Task { if await model.save(draft, existingID: row?.id) { page = .list } }
            },
            onCancel: { open(.list) },
            onDelete: {
                guard let row else { return }
                Task { if await model.delete(id: row.id) { page = .list } }
            })
            .id(row?.id ?? "create")
    }

    private func open(_ next: SettingsMemoryPage) {
        if next != .list { model.clearMessages() }
        page = next
    }

    private func stateText(_ text: String) -> some View {
        Text(text).font(.omSmall).foregroundStyle(Color.fontSecondary)
            .frame(maxWidth: .infinity, alignment: .leading).padding(.spacing6)
            .accessibilityIdentifier("settings-memories-state")
    }

    /// Sub-pages publish the shared settings banner (title + Back to the list).
    private func publishChildNavigation() {
        let title: String
        switch page {
        case .list: onChildNavigationChanged?(nil); return
        case .create: title = AppStrings.memoriesCreateTitle
        case .entry(let id): title = model.row(for: id)?.title ?? AppStrings.settingsMemories
        }
        onChildNavigationChanged?(SettingsChildBannerNavigation(
            title: title, description: "", allowsBack: !model.saving, icon: "settings_memories",
            breadcrumb: [AppStrings.settings, AppStrings.settingsMemories].joined(separator: " / "),
            typeLabel: AppStrings.settingsMemories,
            onBack: { guard !model.saving else { return }; open(.list) }))
    }
}
