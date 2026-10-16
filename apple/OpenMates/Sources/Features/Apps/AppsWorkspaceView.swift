// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/apps/AppsWorkspace.svelte
//         frontend/packages/ui/src/components/apps/AppsSkillForm.svelte
//         frontend/packages/ui/src/components/apps/AppsInlineResults.svelte
//         frontend/packages/ui/src/components/workspace/WorkspaceHomeShell.svelte
//         frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// Fallback: frontend/packages/workspaceInspirationDefaults.ts getWorkspaceInspirations("apps")
// CSS: AppsWorkspace.svelte .apps-detail-card/.results-grid, AppsSkillForm.svelte
// Tokens: ColorTokens, SpacingTokens, TypographyTokens, GradientTokens
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.discovery.public-catalog, apps.forms.metadata-driven,
// apps.execution.direct-shared-contract, apps.presentation.shared-detail-and-recency,
// apps.library.embeds-account-paginated, apps.library.workflows-account-related
import SwiftUI

struct AppsWorkspaceView: View {
    @ObservedObject var store: AppsWorkspaceStore
    var greetingName = ""
    var inspiration: DailyInspirationData? = nil
    var onOpenWorkflow: (String) -> Void = { _ in }
    var onOpenExampleChat: (String) -> Void = { _ in }
    var onOpenSettings: (String) -> Void = { _ in }
    var onReportIssue: () -> Void = {}
    var onSignup: () -> Void = {}
    @State private var inspirationIndex = 0
    @State private var settingsOpen = false
    @State private var contextOpen = false
    @State private var highlight = false
    @State private var secondaryDetailPath: [String]?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private func tr(_ key: String) -> String { AppStrings.localized("apps_workspace." + key) }
    private func form(_ key: String) -> String { AppStrings.localized("apps.skill_form." + key) }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                home(size: geometry.size)
                if let app = store.selectedApp {
                    detail(app: app, width: geometry.size.width)
                        .transition(.move(edge: .bottom))
                }
            }
            .background(Color.grey20.ignoresSafeArea())
            .overlay {
                if let result = store.selectedResult {
                    ZStack {
                        EmbedFullscreenContainer(embeds: [result], initialEmbedId: result.id,
                            allEmbedRecords: store.records, chatId: nil,
                            onOpenEmbed: { child, _ in store.selectedResult = child },
                            onClose: { store.selectedResult = nil })
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("apps-result-fullscreen")
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("apps-workspace")
        .onChange(of: store.selectedSkill?.id) { _, _ in settingsOpen = false; contextOpen = false; secondaryDetailPath = nil }
        .onChange(of: store.selectedApp?.id) { _, _ in secondaryDetailPath = nil }
    }

    private func home(size: CGSize) -> some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                if !store.showingAll {
                    inspirationBanner(size: size)
                        // Keep the card and navigation buttons independently
                        // accessible inside this identified banner container.
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("apps-daily-inspiration-area")
                }
                HStack {
                    Button(tr(store.showingAll ? "back_to_recent" : "show_all")) { store.showingAll.toggle() }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier(store.showingAll ? "apps-back-to-recent" : "apps-show-all")
                    Spacer()
                    OMIconButton(icon: "bug", label: AppStrings.reportIssue, action: onReportIssue)
                        .accessibilityIdentifier("apps-report-issue")
                }
                .padding(.horizontal, .spacing6)
                VStack(spacing: .spacing3) {
                    if !greetingName.isEmpty {
                        Text(tr("home_greeting").replacingOccurrences(of: "{name}", with: greetingName)).font(.omH3).foregroundStyle(Color.fontPrimary)
                    }
                    Text(tr("home_prompt")).font(.omH3.weight(.bold)).foregroundStyle(Color.fontPrimary)
                    Text(tr("description")).font(.omP).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)
                }
                .padding(.horizontal, .spacing6)
                if store.showingAll {
                    TextField(AppStrings.localized("common.search"), text: $store.search)
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("apps-catalog-search")
                        .padding(.horizontal, .spacing6)
                }
                if store.isLoading { ProgressView().accessibilityIdentifier("apps-loading") }
                if let key = store.errorKey, store.selectedApp == nil {
                    Text(tr(key)).font(.omSmall).foregroundStyle(Color.error)
                    Button(tr("retry")) { Task { await store.load() } }.buttonStyle(OMSecondaryButtonStyle())
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 223, maximum: 223), spacing: .spacing6)], spacing: .spacing6) {
                    ForEach(store.showingAll ? store.visibleApps : store.homeApps) { app in
                        AppStoreCardNative(app: app) { withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) { store.selectApp(app) } }
                            .omCardHoverFeedback()
                            .accessibilityIdentifier(store.showingAll ? "apps-all-item-\(app.id)" : "apps-app-card-\(app.id)")
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier(store.showingAll ? "apps-all-apps" : "apps-home-apps")
                .padding(.horizontal, .spacing6)
                .padding(.bottom, .spacing8)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("apps-home")
        .accessibilityHidden(store.selectedApp != nil)
        .allowsHitTesting(store.selectedApp == nil)
    }

    private var fallbackInspirations: [DailyInspirationData] {
        [DailyInspirationData(inspirationId: "hardcoded-apps-search",
            text: tr("inspiration_search_phrase"), title: tr("inspiration_search_title"), category: "general_knowledge",
            feature: DailyInspirationFeature(iconName: "search", title: tr("inspiration_search_feature_title"), description: tr("inspiration_search_feature_description"))),
         DailyInspirationData(inspirationId: "hardcoded-apps-weather",
            text: tr("inspiration_weather_phrase"), title: tr("inspiration_weather_title"), category: "travel",
            feature: DailyInspirationFeature(iconName: "cloud-sun", title: tr("inspiration_weather_feature_title"), description: tr("inspiration_weather_feature_description")))]
    }

    private func inspirationBanner(size: CGSize) -> some View {
        let entries = inspiration.map { [$0] } ?? fallbackInspirations
        let index = inspirationIndex % entries.count
        return ZStack {
            InspirationCard(inspiration: entries[index], containerSize: size,
                heightOverride: size.width < 730 ? 190 : max(240, min(420, size.height * 0.35)),
                ctaTitle: tr("inspiration_tap_to_use_skill"), tapHint: tr("quick_use_hint"),
                isInteractive: false) { }
            if entries.count > 1 {
                HStack {
                    Button { inspirationIndex = (index + entries.count - 1) % entries.count } label: {
                        Icon("back", size: 17).foregroundStyle(.white).frame(width: 36, height: 36)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.previousInspiration)
                    .accessibilityIdentifier("apps-inspiration-previous")
                    Spacer()
                    Button { inspirationIndex = (index + 1) % entries.count } label: {
                        Icon("back", size: 17).scaleEffect(x: -1).foregroundStyle(.white).frame(width: 36, height: 36)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.nextInspiration)
                    .accessibilityIdentifier("apps-inspiration-next")
                }
                .padding(.horizontal, 5)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func detail(app: SettingsAppsFullView.AppInfo, width: CGFloat) -> some View {
        ScrollViewReader { reader in
            ScrollView {
                VStack(spacing: .spacing6) {
                    ZStack(alignment: .topLeading) {
                        if let embed = store.headerEmbed {
                            EmbedFullscreenHeader(embed: embed,
                                headerCTA: store.selectedSkill == nil ? nil : EmbedHeaderCTA(title: tr("use_skill"), accessibilityIdentifier: "apps-use-skill") {
                                    withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) { reader.scrollTo("apps-input", anchor: .center); highlight = true }
                                    Task { try? await Task.sleep(for: .milliseconds(800)); highlight = false }
                                }, viewportWidth: width,
                                presentation: EmbedFullscreenHeaderPresentation(
                                    title: store.details?.name ?? store.selectedSkill?.name ?? app.name,
                                    subtitle: store.details?.description ?? store.selectedSkill?.description ?? app.description,
                                    icon: app.iconName ?? AppIconView.iconName(forAppId: app.id),
                                    eyebrow: tr(store.selectedSkill == nil ? "app_label" : "skill_label").replacingOccurrences(of: "{app}", with: app.name),
                                    providers: store.selectedSkill?.providerDisplayNames.joined(separator: ", "),
                                    footer: store.selectedSkill == nil ? tr("app_stats").replacingOccurrences(of: "{skills}", with: String(app.skills?.count ?? 0)).replacingOccurrences(of: "{focusModes}", with: String(app.focusModes?.count ?? 0)) : nil))
                        }
                        OMIconButton(icon: "close", label: AppStrings.localized("common.close")) { withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) { store.closeDetail() } }
                            .padding(.spacing4)
                            .accessibilityIdentifier("apps-detail-close")
                    }
                    VStack(spacing: .spacing6) {
                        tabs
                        if let secondaryDetailPath {
                            AppDetailView(app: app, onOpenExampleChat: onOpenExampleChat,
                                initialDetailPath: secondaryDetailPath, usesSharedBanner: true,
                                onMemoryCategory: { app, category in onOpenSettings("memories/\(app)/\(category)") }) { self.secondaryDetailPath = nil }
                        } else if store.tab == .embeds || store.tab == .workflows {
                            library
                        } else if store.selectedSkill != nil {
                            skillForm(app: app)
                        } else {
                            appEntries(app)
                        }
                    }
                    .padding(width <= 600 ? .spacing3 : .spacing6)
                    .padding(.bottom, .spacing8)
                    .frame(maxWidth: width <= 600 ? .infinity : min(1200, width) * 0.82)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .padding(.horizontal, width <= 600 ? .spacing3 : .spacing6)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("apps-detail-card")
                }
                .padding(.bottom, .spacing8)
            }
            .background(Color.grey20.ignoresSafeArea())
            .scrollDismissesKeyboard(.interactively)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("apps-detail-fullscreen")
        }
    }

    private var tabs: some View {
        let tabs: [AppsWorkspaceTab] = store.selectedSkill == nil ? AppsWorkspaceTab.allCases : [.overview, .embeds, .workflows]
        return ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing2) {
                ForEach(tabs) { tab in
                    Button { secondaryDetailPath = nil; store.selectTab(tab) } label: {
                        HStack(spacing: .spacing2) {
                            if tab == .embeds { Icon("files", size: 16) }
                            Text(tr(tab == .overview && store.selectedSkill == nil ? "skills" : tab.rawValue)).font(.omSmall)
                        }
                        .foregroundStyle(store.tab == tab ? Color.fontButton : Color.fontPrimary)
                        .padding(.horizontal, .spacing4).padding(.vertical, .spacing3)
                        .background(store.tab == tab ? Color.buttonPrimary : Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("apps-tab-\(tab.rawValue)")
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("apps-detail-tabs")
    }

    @ViewBuilder private func appEntries(_ app: SettingsAppsFullView.AppInfo) -> some View {
        let entries = store.tab == .focusModes ? app.focusModes ?? [] : store.tab == .memories ? app.settingsAndMemories ?? [] : app.skills ?? []
        VStack(spacing: .spacing4) {
            if store.tab == .overview { Text(tr("choose_skill")).font(.omH3).foregroundStyle(Color.fontPrimary) }
            ForEach(entries) { entry in
                Button {
                    if store.tab == .overview { store.selectSkill(entry) }
                    else { secondaryDetailPath = [store.tab == .focusModes ? "focus_mode" : "settings_memories", entry.id] }
                } label: {
                    HStack(spacing: .spacing4) {
                        Icon("skill", size: 20).foregroundStyle(Color.buttonPrimary)
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(entry.name).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                            Text(entry.description ?? "").font(.omSmall).foregroundStyle(Color.fontSecondary).lineLimit(3)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.spacing4).background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius5))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("apps-skill-card-\(entry.id)")
            }
        }
    }

    @ViewBuilder private func skillForm(app: SettingsAppsFullView.AppInfo) -> some View {
        if store.metadataLoading { ProgressView().accessibilityIdentifier("apps-skill-metadata-loading") }
        else if let details = store.details {
            VStack(spacing: .spacing8) {
                Button { contextOpen.toggle() } label: {
                    VStack(spacing: .spacing2) {
                        Icon("chat", size: 20)
                        Text(tr("skill_context_intro")); Text(tr("skill_context_chat"))
                        Text(tr(contextOpen ? "skill_context_collapse" : "skill_context_expand")).fontWeight(.bold)
                    }
                    .font(.omSmall).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)
                }
                .buttonStyle(.plain).accessibilityIdentifier("apps-skill-context-toggle")
                if contextOpen, let skill = store.selectedSkill {
                    AppDetailView(app: app, onOpenExampleChat: onOpenExampleChat,
                        initialDetailPath: ["skill", skill.id], usesSharedBanner: true) { contextOpen = false }
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("apps-skill-context-details")
                }
                if let schema = store.primarySchema {
                    WorkflowSchemaInputView(schema: schema, value: store.input, appId: app.id,
                        onChange: store.updateInput, path: "apps-primary", showAdvancedToggle: false)
                        .id("apps-input")
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("apps-skill-primary-fields")
                }
                if let path = store.requirementsPath {
                    VStack(alignment: .leading, spacing: .spacing2) {
                        Text(form("requirements") + " " + form("optional")).font(.omP)
                        TextField(form("requirements_placeholder"), text: Binding(
                            get: { AppsSkillInput.value(store.input, path: path) as? String ?? "" },
                            set: { store.updateInput(AppsSkillInput.replacing(store.input, path: path, value: $0)) }), axis: .vertical)
                            .lineLimit(4...6).textFieldStyle(OMTextFieldStyle())
                            .accessibilityIdentifier("apps-skill-relevance-criteria")
                    }
                }
                if !store.validationIssues.isEmpty {
                    Text(form("check_fields") + "\n" + store.validationIssues.joined(separator: ", "))
                        .font(.omSmall).foregroundStyle(Color.error).accessibilityIdentifier("apps-skill-validation-errors")
                }
                if !details.executionAvailable { Text(form("unavailable")).foregroundStyle(Color.fontSecondary) }
                if store.viewer { Text(tr("viewer_read_only")).font(.omSmall).foregroundStyle(Color.fontSecondary) }
                HStack(spacing: .spacing4) {
                    if store.advancedSchema != nil {
                        Button { settingsOpen.toggle() } label: {
                            HStack { Icon("settings", size: 16); Text(form(settingsOpen ? "hide_settings" : "show_settings")) }
                                .font(.omSmall).foregroundStyle(Color.buttonPrimary)
                        }
                        .buttonStyle(.plain).accessibilityIdentifier("apps-skill-settings-toggle")
                    }
                    Spacer(minLength: 0)
                    if store.guest && !store.guestAllowed && !store.checkingGuest && details.executionAvailable {
                        Button(form("signup"), action: onSignup).buttonStyle(OMPrimaryButtonStyle()).accessibilityIdentifier("apps-skill-signup")
                    } else {
                        Button(form(store.isSubmitting ? "running" : store.checkingGuest ? "checking" : "run")) {
                            store.submit(); if !store.validationIssues.isEmpty { settingsOpen = true }
                        }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(store.isSubmitting || store.checkingGuest || store.viewer || !details.executionAvailable || store.guest && !store.guestAllowed)
                        .accessibilityIdentifier("apps-skill-submit")
                    }
                    Spacer(minLength: 0)
                }
                if settingsOpen, let schema = store.advancedSchema {
                    WorkflowSchemaInputView(schema: schema, value: store.input, appId: app.id,
                        onChange: store.updateInput, path: "apps-settings", showAdvancedToggle: false)
                        .padding(.spacing8).background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius8))
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("apps-skill-settings")
                }
                ForEach(store.executionMetadata, id: \.self) { Text($0).font(.omSmall).foregroundStyle(Color.fontSecondary) }
                if let key = store.errorKey { Text(tr(key)).font(.omSmall).foregroundStyle(Color.error).accessibilityIdentifier("apps-request-error") }
                if let state = store.saveState {
                    HStack {
                        Text(tr(state == "error" ? "save_failed" : state == "saved" ? "saved" : "saving")).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        if state == "error" { Button(tr("retry_save")) { Task { await store.retrySave() } }.buttonStyle(OMSecondaryButtonStyle()).accessibilityIdentifier("apps-result-save-retry") }
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("apps-result-save-state")
                    .accessibilityValue(state)
                }
                if let result = store.inlineResult {
                    EmbedContentView(embed: result, mode: .fullscreen, allEmbedRecords: store.records,
                        onOpenEmbed: { store.selectedResult = $0 })
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("apps-inline-results")
                    Button(tr("results")) { store.selectedResult = result }.buttonStyle(OMSecondaryButtonStyle()).accessibilityIdentifier("apps-inline-result-open")
                }
            }
            .frame(maxWidth: 768)
            .padding(.spacing2)
            .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(highlight ? Color.buttonPrimary : Color.clear, lineWidth: 3))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("apps-skill-form")
        } else if let key = store.errorKey {
            Text(tr(key)).font(.omSmall).foregroundStyle(Color.error)
            if let skill = store.selectedSkill { Button(tr("retry")) { store.selectSkill(skill) }.buttonStyle(OMSecondaryButtonStyle()) }
        }
    }

    private var library: some View {
        VStack(spacing: .spacing6) {
            if store.libraryLoading { ProgressView() }
            if store.libraryError {
                Text(tr("library_error")).font(.omSmall).foregroundStyle(Color.error)
                Button(tr("retry")) { store.loadLibrary(offset: store.offset) }.buttonStyle(OMSecondaryButtonStyle())
            }
            if store.tab == .embeds {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: .spacing6)], spacing: .spacing6) {
                    ForEach(store.results) { row in
                        if let record = store.records[row.id] {
                            EmbedPreviewCard(embed: record, allEmbedRecords: store.records, variant: .large) { store.selectedResult = record }
                                .accessibilityIdentifier("apps-result-open-\(row.id)")
                        } else {
                        Button { Task { await store.openResult(row.id) } } label: {
                            VStack(alignment: .leading, spacing: .spacing3) {
                                AppIconView(appId: row.appID, size: 38)
                                Text(row.skillID.replacingOccurrences(of: "_", with: " ")).font(.omP.weight(.semibold))
                                Text(row.status.rawValue).font(.omSmall).foregroundStyle(Color.fontSecondary)
                            }
                            .frame(maxWidth: .infinity, minHeight: 160, alignment: .leading)
                            .padding(.spacing4).background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius5))
                        }
                        .buttonStyle(.plain).accessibilityIdentifier("apps-result-open-\(row.id)")
                        .task(id: row.id) { store.hydrateResult(row.id) }
                        }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("apps-results-list")
                if store.results.isEmpty && !store.libraryLoading { Text(tr("no_embeds")).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            } else {
                LazyVStack(spacing: .spacing4) {
                    ForEach(store.workflows) { workflow in
                        Button(workflow.title) { onOpenWorkflow(workflow.id) }.buttonStyle(OMSecondaryButtonStyle())
                            .accessibilityIdentifier("apps-workflow-open-\(workflow.id)")
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("apps-workflows-list")
                if store.workflows.isEmpty && !store.libraryLoading { Text(tr("no_workflows")).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            }
            HStack {
                Button(tr("previous")) { store.loadLibrary(offset: max(0, store.offset - 20)) }.buttonStyle(OMSecondaryButtonStyle())
                    .disabled(store.offset == 0 || store.libraryLoading).accessibilityIdentifier("apps-previous-page")
                Spacer()
                Button(tr("next")) { store.loadLibrary(offset: store.offset + 20) }.buttonStyle(OMSecondaryButtonStyle())
                    .disabled(!store.hasMore || store.libraryLoading).accessibilityIdentifier("apps-next-page")
            }
        }
    }
}

// Uses the production workspace sidebar header and search field.
struct AppsSidebarView: View {
    @ObservedObject var store: AppsWorkspaceStore
    var onClose: () -> Void
    var onSelect: (SettingsAppsFullView.AppInfo) -> Void
    @State private var showsSearch = false

    var body: some View {
        VStack(spacing: 0) {
            WorkspaceSidebarHeader(onSearch: { showsSearch.toggle(); if !showsSearch { store.search = "" } },
                onClose: onClose, searchIdentifier: "apps-sidebar-search",
                closeIdentifier: "apps-sidebar-close", topBarIdentifier: "apps-sidebar-topbar")
            if showsSearch { WorkspaceSidebarSearchField(query: $store.search, identifier: "apps-sidebar-search-input") }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing2) {
                    Text(AppStrings.localized("apps_workspace.title")).font(.omSmall.weight(.bold)).foregroundStyle(Color.fontSecondary)
                        .padding(.vertical, .spacing4)
                    ForEach(store.visibleApps) { app in
                        Button { onSelect(app) } label: {
                            HStack(spacing: .spacing3) {
                                AppIconView(appId: app.id, size: 36)
                                Text(app.name).font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontPrimary).lineLimit(1)
                                Spacer(minLength: 0)
                            }
                            .padding(.spacing3)
                            .background(store.selectedApp?.id == app.id ? Color.grey20 : Color.clear)
                            .clipShape(RoundedRectangle(cornerRadius: .radius5))
                        }
                        .buttonStyle(.plain).accessibilityIdentifier("apps-sidebar-app-\(app.id)")
                    }
                    if store.visibleApps.isEmpty && !store.isLoading {
                        Text(AppStrings.searchNoResults).font(.omSmall).foregroundStyle(Color.fontSecondary)
                            .accessibilityIdentifier("apps-sidebar-no-matches")
                    }
                }
                .padding(.horizontal, .spacing4)
            }
        }
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("apps-sidebar")
    }
}
