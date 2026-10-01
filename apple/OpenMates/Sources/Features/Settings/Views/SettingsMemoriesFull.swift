// Web source: frontend/packages/ui/src/components/settings/SettingsMemoriesHub.svelte,
// AppStoreCard.svelte, AppSettingsMemoriesCategory.svelte, AppSettingsMemoriesEntryDetail.svelte,
// AppSettingsMemoriesCreateEntry.svelte and settings/elements/SettingsSectionHeading.svelte.
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.surface.semantic-parity
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.navigation.parent-return, settings-ui.parity.web-apple-shell

import Combine
import SwiftUI

struct SettingsMemoriesFullView: View {
    @Environment(\.omSettingsScrollOffsetHandler) private var scrollOffsetHandler
    @EnvironmentObject private var authManager: AuthManager
    @ObservedObject private var workspace = TeamWorkspaceContext.shared
    @ObservedObject private var offline = OfflineStore.shared
    @StateObject private var service: SettingsMemoryService
    @State private var route: SettingsMemoryRoute
    var onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)?
    var onDiscoverApps: (() -> Void)?
    var onOpenExampleChat: (String) -> Void
    var embedRecords: [String: EmbedRecord]
    var onOpenEmbed: ((EmbedRecord) -> Void)?

    init(deepLinkPath: String? = nil, onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)? = nil,
         onDiscoverApps: (() -> Void)? = nil, onOpenExampleChat: @escaping (String) -> Void = { id in
            guard let url = URL(string: "openmates://chat/\(id)") else { return }
            NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
         }, embedRecords: [String: EmbedRecord] = [:], onOpenEmbed: ((EmbedRecord) -> Void)? = nil, service: SettingsMemoryService = SettingsMemoryService()) {
        self.onChildNavigationChanged = onChildNavigationChanged; self.onDiscoverApps = onDiscoverApps
        self.onOpenExampleChat = onOpenExampleChat
        self.embedRecords = embedRecords; self.onOpenEmbed = onOpenEmbed
        #if DEBUG
        let fixturePath = ProcessInfo.processInfo.arguments.contains("--ui-test-memory-editor-fixture") ? "apps/travel/settings_memories/preferred_activities" : nil
        _route = State(initialValue: SettingsMemoryRoute(path: deepLinkPath ?? fixturePath))
        #else
        _route = State(initialValue: SettingsMemoryRoute(path: deepLinkPath))
        #endif
        _service = StateObject(wrappedValue: service)
    }
    private var contextIdentity: String {
        "\(authManager.currentUser?.id ?? "guest"):\(ServerProfile.current().id):\(offline.scopeGeneration):\(workspace.contextEpoch)"
    }
    private var selectedCategory: SettingsMemoryCategory? { service.categories.first { $0.id == route.categoryIdentity } }
    var body: some View {
        Group {
            if route == .hub { hub }
            else if let category = selectedCategory {
                switch route {
                case .hub: hub
                case .category: SettingsMemoryCategoryView(category: category, service: service, onNavigate: navigate, onOpenExampleChat: onOpenExampleChat, embedRecords: embedRecords, onOpenEmbed: onOpenEmbed).id(category.id)
                case .entry(_, _, let id):
                    if let entry = entry(id, category: category) {
                        SettingsMemoryEntryDetailView(category: category, entry: entry, service: service,
                            onEdit: { navigate(.editor(category.appId, category.categoryId, entry.id)) },
                            onDeleted: { navigate(.category(category.appId, category.categoryId)) }, embedRecords: embedRecords, onOpenEmbed: onOpenEmbed)
                    } else { stateText(AppStrings.localized("settings.app_settings_memories.entry_not_found")) }
                case .editor(_, _, let id):
                    if service.isAuthenticated, id == nil || entry(id!, category: category)?.isExample == false {
                        SettingsMemoryEditorView(category: category, entry: id.flatMap { entry($0, category: category) }, service: service,
                            onSaved: { navigate(id.map { .entry(category.appId, category.categoryId, $0) } ?? .category(category.appId, category.categoryId)) },
                            onCancel: { navigate(route.parent) })
                        .id("\(category.id):\(id ?? "create")")
                    } else { stateText(AppStrings.memoryAuthenticationRequired) }
                }
            } else { stateText(service.state == .loading ? AppStrings.loading : AppStrings.localized("settings.app_store.category_not_found")) }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-memories-page")
        .task(id: contextIdentity) { await service.load(); publishChildNavigation() }
        .onChange(of: authManager.currentUser?.id) { _, _ in service.cancel(); route = .hub; publishChildNavigation() }
        .onChange(of: workspace.contextEpoch) { _, _ in service.cancel(); route = .hub; publishChildNavigation() }
        .onReceive(NotificationCenter.default.publisher(for: ServerConfiguration.didChangeNotification)) { _ in
            service.cancel(); route = .hub; publishChildNavigation()
        }
        .onChange(of: route) { _, _ in scrollOffsetHandler.callback?(0); publishChildNavigation() }
        .onChange(of: service.state) { _, _ in publishChildNavigation() }
        .onDisappear { service.cancel(); onChildNavigationChanged?(nil) }
    }
    private func entry(_ id: String, category: SettingsMemoryCategory) -> SettingsMemoryEntry? {
        service.entries(in: category).first { $0.id == id } ?? category.examples.first { $0.id == id }
    }
    private func navigate(_ destination: SettingsMemoryRoute) { route = destination }
    private func publishChildNavigation() {
        guard route != .hub else { onChildNavigationChanged?(nil); return }
        let category = selectedCategory
        let title: String
        switch route {
        case .hub: return
        case .category: title = category?.categoryName ?? AppStrings.settingsMemories
        case .entry(_, _, let id): title = category.flatMap { entry(id, category: $0)?.title(in: $0) } ?? AppStrings.settingsMemories
        case .editor(_, _, let id): title = id == nil ? AppStrings.localized("common.add_entry") : AppStrings.edit
        }
        let siblings: (previous: SettingsMemoryCategory?, next: SettingsMemoryCategory?)
        if case .category = route, let category { siblings = SettingsMemoryCatalog.siblings(categories: service.categories, selected: category) }
        else { siblings = (nil, nil) }
        func navigation(_ category: SettingsMemoryCategory?) -> SettingsChildSiblingNavigation? {
            category.map { target in SettingsChildSiblingNavigation(title: target.categoryName, onSelect: {
                guard service.state != .pending else { return }
                navigate(.category(target.appId, target.categoryId))
            }) }
        }
        onChildNavigationChanged?(SettingsChildBannerNavigation(title: title, description: category?.description ?? "",
            allowsBack: service.state != .pending, icon: category?.iconName ?? "memory",
            breadcrumb: [AppStrings.settings, AppStrings.settingsMemories, route.parent == .hub ? nil : category?.categoryName].compactMap { $0 }.joined(separator: " / "),
            appColorID: category?.appId, typeLabel: AppStrings.settingsMemories,
            previous: navigation(siblings.previous), next: navigation(siblings.next),
            onBack: { guard service.state != .pending else { return }; navigate(route.parent) }))
    }
    private var hub: some View {
        OMSettingsPage(title: "", showsHeader: false, showsFooter: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                Text(AppStrings.localized("settings.app_settings_memories.encryption_notice"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary).lineSpacing(5)
                    .padding(.horizontal, .spacing4).padding(.bottom, .spacing8)
                if service.state == .loading { stateText(AppStrings.loading) }
                else if service.state == .missingKey { stateText(AppStrings.memoryAuthenticationRequired) }
                else {
                    let sections = service.sections
                    if sections.isEmpty { stateText(AppStrings.localized("settings.app_store.settings_memories.hub_no_entries")) }
                    ForEach(Array(sections.enumerated()), id: \.element.id) { index, section in
                        VStack(alignment: .leading, spacing: 0) {
                            if index > 0 { Divider().overlay(Color.grey20).padding(.top, .spacing12).padding(.bottom, .spacing4) }
                            SettingsMemoryAppHeading(section: section)
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: .spacing6) {
                                    ForEach(section.categories) { category in
                                        SettingsMemoryCategoryCard(category: category) { navigate(.category(category.appId, category.categoryId)) }
                                            .padding(.spacing5 / 2)
                                    }
                                }
                                .padding(.vertical, .spacing2)
                            }
                            .padding(.top, .spacing4)
                        }
                    }
                }
                Divider().overlay(Color.grey20).padding(.top, .spacing12).padding(.bottom, .spacing4)
                OMSettingsRow(title: AppStrings.localized("settings.app_store.settings_memories.discover_link"), icon: "app",
                    accessibilityIdentifier: "settings-memory-discover-apps") { onDiscoverApps?() }
            }
            .padding(.horizontal, .spacing6 + .spacing1).padding(.vertical, .spacing6 + .spacing1)
            .frame(maxWidth: 1400, alignment: .leading).frame(maxWidth: .infinity)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("settings-memories-hub")
        }
    }
    private func stateText(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(text).font(.omSmall).foregroundStyle(Color.fontSecondary)
            if case .error = service.state {
                Button(AppStrings.retry) { Task { await service.load() } }.buttonStyle(OMSecondaryButtonStyle())
            }
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.spacing6)
            .accessibilityIdentifier("settings-memories-state")
    }
}

private struct SettingsMemoryAppHeading: View {
    let section: SettingsMemoryAppSection
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack(spacing: .spacing6) {
                Icon(section.iconName.isEmpty ? AppIconView.iconName(forAppId: section.appId) : section.iconName, size: 22)
                    .foregroundStyle(Color.fontButton).frame(width: 44, height: 44)
                    .background(AppIconView.gradient(forAppId: section.appId), in: RoundedRectangle(cornerRadius: .radius4))
                Text(section.name).font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
            }
            RoundedRectangle(cornerRadius: .radiusFull).fill(LinearGradient.primary).frame(height: .spacing2)
        }.padding(.horizontal, .spacing5).padding(.top, .spacing6).padding(.bottom, .spacing6)
    }
}

private struct SettingsMemoryCategoryCard: View {
    let category: SettingsMemoryCategory
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack(spacing: .spacing5) {
                    SettingsMemoryIcon(name: category.iconName, size: .spacing20)
                    Text(category.categoryName).font(.omP.weight(.semibold)).foregroundStyle(Color.fontButton)
                        .lineLimit(2).frame(maxWidth: .infinity, alignment: .leading).padding(.top, .spacing1)
                }
                Text(category.description).font(.omSmall).foregroundStyle(Color.fontButton.opacity(0.9))
                    .lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing8).padding(.top, .spacing12 + .spacing1 / 2).padding(.bottom, .spacing8)
            .frame(width: 223, height: 129, alignment: .topLeading)
            .background(AppIconView.gradient(forAppId: category.appId))
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .shadow(color: Color.fontPrimary.opacity(0.1), radius: .spacing2, x: 0, y: .spacing1)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("settings-memory-category-\(category.appId)-\(category.categoryId)")
    }
}
