// Web source: frontend/packages/ui/src/components/chats/ChatSettingsPage.svelte,
// frontend/packages/ui/src/components/settings/ChatSettingsHeader.svelte,
// frontend/packages/ui/src/components/settings/elements/SettingsTabs.svelte.
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift.
import SwiftUI
import UniformTypeIdentifiers

private struct ChatSettingsCompactLayout: EnvironmentKey { static let defaultValue = true }
private extension EnvironmentValues {
    var chatSettingsCompact: Bool {
        get { self[ChatSettingsCompactLayout.self] }
        set { self[ChatSettingsCompactLayout.self] = newValue }
    }
}
struct ChatSettingsCard<Content: View>: View {
    @Environment(\.chatSettingsCompact) private var compact
    let spacing: CGFloat
    @ViewBuilder let content: Content
    init(spacing: CGFloat = .spacing6, @ViewBuilder content: () -> Content) {
        self.spacing = spacing; self.content = content()
    }
    var body: some View {
        OMSettingsCard(horizontalPadding: compact ? .spacing3 : .spacing10,
                       verticalPadding: .spacing10, horizontalMargin: compact ? .spacing1 : .spacing5) {
            VStack(alignment: .leading, spacing: spacing) { content }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
private struct ChatSettingsScrollOffset: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}
private struct ChatSettingsScrollTracking: ViewModifier {
    let onOffsetChange: (CGFloat) -> Void
    @ViewBuilder func body(content: Content) -> some View {
        if #available(iOS 18.0, macOS 15.0, *) {
            content.onScrollGeometryChange(for: CGFloat.self) { geometry in
                // The header is fully collapsed at 80pt. Scrolling farther
                // need not republish geometry or relayout the header.
                min(80, max(0, geometry.contentOffset.y + geometry.contentInsets.top))
            } action: { _, offset in onOffsetChange(offset) }
        } else {
            content.onPreferenceChange(ChatSettingsScrollOffset.self) {
                onOffsetChange(min(80, max(0, $0)))
            }
        }
    }
}

private enum ChatSettingsExportPhase: String { case idle, downloading, presenting, failed }

struct ChatSettingsView: View {
    let chat: Chat
    var messages: [Message] = []
    var embeds: [EmbedRecord] = []
    var accountID: String?
    var isSharedViewer = false
    var isExample = false
    var exampleUsageRows: [ChatSettingsUsageRow] = []
    var exampleFileLoader: (() -> [EmbedRecord])?
    var exampleUsageLoader: (() -> [ChatSettingsUsageRow])?
    var previewPlanCount = 1
    var originalShareURL: URL?
    var recipientPlanning: SharedChatRecipientPlanningSnapshot?
    var recipientMediaContext: RecipientMediaContext?
    var onBack: () -> Void = {}
    var onOpenFile: (EmbedRecord) -> Void = { _ in }
    var isPreview = false
    var initialTab: ChatSettingsTab = .plan
    // Web media queries use the window width even when Settings is a 323px
    // side panel. The panel's own width must not select the phone layout.
    var viewportWidth: CGFloat?
    @StateObject private var model = ChatSettingsModel()
    @StateObject private var usage = ChatSettingsUsageModel()
    @State private var activeTab: ChatSettingsTab = .plan
    @State private var taskTitle = ""
    @State private var taskDescription = ""
    @State private var scrollOffset: CGFloat = 0
    @State private var exportDocument: ChatSettingsExportDocument?
    @State private var exportType = UTType.data
    @State private var exportName = "chat.yaml"
    @State private var showExporter = false
    @State private var exporting = false
    @State private var exportError: String?
    @State private var exportPhase: ChatSettingsExportPhase = .idle
    #if DEBUG
    @State private var lastExportReceipt: String?
    #endif
    @State private var initialized = false
    @State private var refreshTask: Task<Void, Never>?
    @State private var fileRows: [EmbedRecord] = []
    @Namespace private var tabSelectionNamespace

    init(chat: Chat, messages: [Message] = [], embeds: [EmbedRecord] = [], accountID: String? = nil,
         isSharedViewer: Bool = false, isExample: Bool = false, exampleUsageRows: [ChatSettingsUsageRow] = [], exampleUsageLoader: (() -> [ChatSettingsUsageRow])? = nil, exampleFileLoader: (() -> [EmbedRecord])? = nil, previewPlanCount: Int = 1, originalShareURL: URL? = nil,
         recipientPlanning: SharedChatRecipientPlanningSnapshot? = nil,
         recipientMediaContext: RecipientMediaContext? = nil,
         onBack: @escaping () -> Void = {}, onOpenFile: @escaping (EmbedRecord) -> Void = { _ in },
         isPreview: Bool = false, initialTab: ChatSettingsTab = .plan, viewportWidth: CGFloat? = nil) {
        self.chat = chat; self.messages = messages; self.embeds = embeds; self.accountID = accountID
        self.isSharedViewer = isSharedViewer; self.isExample = isExample; self.originalShareURL = originalShareURL
        self.exampleFileLoader = exampleFileLoader; self.exampleUsageRows = exampleUsageRows; self.exampleUsageLoader = exampleUsageLoader; self.previewPlanCount = previewPlanCount
        self.recipientPlanning = recipientPlanning
        self.recipientMediaContext = recipientMediaContext
        self.onBack = onBack; self.onOpenFile = onOpenFile; self.isPreview = isPreview; self.initialTab = initialTab
        self.viewportWidth = viewportWidth
        _activeTab = State(initialValue: initialTab)
    }

    private var tabs: [ChatSettingsTab] { ChatSettingsProjection.visibleTabs(example: isExample, hasFiles: !fileRows.isEmpty, hasUsage: usage.hasKnownCredits) }
    var body: some View {
        GeometryReader { geometry in
            let layoutWidth = viewportWidth ?? geometry.size.width
            VStack(spacing: 0) {
                header(width: layoutWidth)
                ScrollView {
                    VStack(alignment: .leading, spacing: .spacing5) {
                        Text(chat.chatSummary.flatMap { summary in ChatSettingsProjection.summary(summary) == "No summary available yet." ? nil : summary } ?? AppStrings.chatSettingsSummaryEmpty)
                            .font(.omP).foregroundStyle(Color.fontPrimary).accessibilityIdentifier("chat-settings-summary")
                        if isSharedViewer { OMSettingsInfoBox(message: AppStrings.chatSettingsSharedReadonly, identifier: "chat-settings-readonly") }
                        tabBar
                        tabContent
                        if let error = model.error { Text(error).font(.omSmall).foregroundStyle(Color.error).accessibilityIdentifier("chat-settings-planning-error") }
                        if exporting { ProgressView(AppStrings.loading).accessibilityIdentifier("chat-settings-export-progress") }
                        if let exportError { Text(exportError).font(.omSmall).foregroundStyle(Color.error).accessibilityIdentifier("chat-settings-export-error") }
                    }.background {
                        GeometryReader { proxy in Color.clear.preference(key: ChatSettingsScrollOffset.self, value: max(0, -proxy.frame(in: .named("chat-settings-scroll")).minY)) }
                    }.padding(.horizontal, layoutWidth <= 730 ? CGFloat.spacing1 : CGFloat.spacing4).padding(.top, .spacing5).padding(.bottom, .spacing8)
                }
                #if os(iOS)
                // User scrolling can dismiss the keyboard while automatic field
                // positioning and header resizing preserve the editor's focus.
                .scrollDismissesKeyboard(.interactively)
                #endif
                .coordinateSpace(name: "chat-settings-scroll").background(Color.grey10)
                .modifier(ChatSettingsScrollTracking { scrollOffset = $0 })
                .accessibilityIdentifier("chat-settings-scroll")
            }.background(Color.grey10).environment(\.chatSettingsCompact, layoutWidth <= 730)
                .accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-page")
                .accessibilityValue(exportAccessibilityValue)
        }
        .fileExporter(isPresented: $showExporter, document: exportDocument, contentType: exportType, defaultFilename: exportName) { result in completeExport(result) }
        .onChange(of: showExporter) { wasPresented, isPresented in
            // FileExporter can dismiss without a completion result on cancel.
            if wasPresented && !isPresented && exportPhase == .presenting {
                exportDocument = nil; exportPhase = .idle
            }
        }
        .task(id: settingsLifecycleID) { await initializeSettings() }
        .onChange(of: ChatSettingsFileSnapshot(records: embeds)) { _, snapshot in updateFiles(snapshot.records) }
        .onChange(of: initialTab) { _, tab in selectInitialTab(tab) }
        .onDisappear { refreshTask?.cancel() }
        .onChange(of: activeTab) { _, tab in refreshTab(tab) }
    }
    private var settingsLifecycleID: String { chat.id + "|" + (accountID ?? "") }
    private func updateFiles(_ records: [EmbedRecord]) {
        var merged = records
        if isExample, let exampleFileLoader { merged.append(contentsOf: exampleFileLoader()) }
        fileRows = ChatSettingsProjection.files(merged)
    }
    private func selectInitialTab(_ tab: ChatSettingsTab) {
        activeTab = tabs.contains(tab) ? tab : .share
    }
    private func refreshTab(_ tab: ChatSettingsTab) {
        refreshTask?.cancel()
        let action = ChatSettingsRefreshPolicy.action(tab: tab, initialized: initialized, preview: isPreview, example: isExample, shared: isSharedViewer)
        switch action {
        case .planning: refreshTask = Task { await model.load(chatID: chat.id, accountID: accountID, shared: false) }
        case .usage: refreshTask = Task { await usage.load(chatID: chat.id, accountID: accountID, shared: false, messages: messages) }
        case .none: break
        }
    }
    private func initializeSettings() async {
        initialized = false
        refreshTask?.cancel()
        usage.loadStatic(rows: isExample ? (exampleUsageLoader?() ?? exampleUsageRows) : exampleUsageRows)
        activeTab = initialTab
        updateFiles(embeds)
        if isPreview {
            #if DEBUG
            model.tasks = [.init(id: "preview-task", title: "Review the release checklist", detail: "Verify the outcome before completion.", status: "todo")]
            model.plans = (0..<previewPlanCount).map { index in .init(id: "preview-plan-\(index)", title: index == 0 ? "Prepare the launch" : "Launch plan \(index + 1)", detail: "Coordinate the work and verify the outcome.", status: "active") }
            #endif
        } else if isSharedViewer {
            // Recipient rows use only the link's scoped key/manifest. Never
            // resolve keys or planning data through the owner's stores/API.
            model.tasks = recipientPlanning?.tasks ?? []
            model.plans = recipientPlanning?.plans ?? []
            await usage.load(chatID: chat.id, accountID: nil, shared: true, messages: messages)
        } else if !isExample {
            await model.load(chatID: chat.id, accountID: accountID, shared: isSharedViewer)
            await usage.load(chatID: chat.id, accountID: accountID, shared: isSharedViewer, messages: messages)
        }
        guard !Task.isCancelled else { return }
        if !tabs.contains(activeTab) { activeTab = .share }
        initialized = true
    }
    private var exportAccessibilityValue: String {
        var value = "export=\(exportPhase.rawValue)"
        #if DEBUG
        if let lastExportReceipt { value += ";" + lastExportReceipt }
        #endif
        return value
    }
    private func resetExportReceipt() {
        #if DEBUG
        lastExportReceipt = nil
        #endif
    }
    #if DEBUG
    private func recordExportReceipt(_ url: URL) {
        let accessing = url.startAccessingSecurityScopedResource()
        defer { if accessing { url.stopAccessingSecurityScopedResource() } }
        let attributes = try? FileManager.default.attributesOfItem(atPath: url.path)
        let bytes = (attributes?[.size] as? NSNumber).map { String($0.uint64Value) } ?? "unavailable"
        lastExportReceipt = "saved=\(url.lastPathComponent);bytes=\(bytes)"
    }
    #endif
    private var displayedCredits: Double { usage.total ?? chat.budgetSpent ?? usage.knownCredits }
    // Settings.svelte resolves known category colors, then general knowledge.
    // The account-free web harness intentionally uses the primary blue header.
    static func headerGradient(category: String?, preview: Bool) -> LinearGradient {
        if preview { return .primary }
        let resolved = category.flatMap { CategoryMapping.isKnownCategory($0) ? $0 : nil } ?? "general_knowledge"
        return CategoryMapping.gradient(for: resolved)
    }
    private func header(width: CGFloat) -> some View {
        let raw = min(1, max(0, scrollOffset / 80))
        let progress = raw < 0.5 ? 4 * raw * raw * raw : 1 - pow(-2 * raw + 2, 3) / 2
        let expanded: CGFloat = width <= 730 ? 220 : 250 // ChatSettingsHeader web breakpoints/heights.
        return VStack(spacing: 0) {
            Button(action: onBack) {
                HStack(spacing: .spacing3) { Icon("back", size: 24); Text(AppStrings.chats).font(.omSmall); Spacer() }
                    .foregroundStyle(Color.fontButton).padding(.horizontal, .spacing5).frame(minHeight: 48)
                    .contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityLabel(AppStrings.back).accessibilityIdentifier("banner-back-button")
            VStack(spacing: .spacing4) {
                Text(chat.title ?? AppStrings.chat).font(.omH3.weight(.bold)).foregroundStyle(Color.fontButton)
                    .multilineTextAlignment(.center).lineLimit(progress > 0.5 ? 1 : 3).accessibilityIdentifier("chat-settings-title")
                if progress < 0.5 {
                    HStack(spacing: .spacing2) { Text(String(Int(max(0, displayedCredits).rounded()))); Icon("coins", size: 22) }
                        .font(.omP.weight(.bold)).foregroundStyle(Color.fontButton).opacity(max(0, 1 - progress * 2)).accessibilityIdentifier("chat-settings-credits").accessibilityValue(String(Int(max(0, displayedCredits).rounded())))
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(.horizontal, .spacing5).padding(.bottom, .spacing5)
        }.frame(height: expanded - (expanded - 88) * progress).background(Self.headerGradient(category: chat.category, preview: isPreview))
            .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: .radius6, bottomTrailingRadius: .radius6))
            .accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-header")
    }
    private var tabBar: some View {
        HStack(spacing: 0) {
            ForEach(tabs, id: \.rawValue) { tab in
                Button {
                    withAnimation(.timingCurve(0.4, 0, 0.2, 1, duration: 0.3)) { activeTab = tab }
                } label: {
                    Icon(tab.icon, size: 18).foregroundStyle(activeTab == tab ? Color.fontButton : Color.grey70)
                        .frame(maxWidth: .infinity).frame(height: 45)
                        .background {
                            if activeTab == tab {
                                Capsule().fill(LinearGradient.primary)
                                    .matchedGeometryEffect(id: "chat-settings-selected-tab", in: tabSelectionNamespace)
                                    .allowsHitTesting(false)
                            }
                        }
                        .contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityLabel(tabLabel(tab)).accessibilityIdentifier("chat-settings-tab-\(tab.rawValue)")
                    .accessibilityAddTraits(activeTab == tab ? .isSelected : [])
            }
        }.background(Color.grey0).clipShape(Capsule())
            .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
            .accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-tabs")
            .padding(.horizontal, .spacing1).padding(.vertical, .spacing1)
    }
    private func tabLabel(_ tab: ChatSettingsTab) -> String {
        switch tab { case .tasks: AppStrings.tasks; case .plan: AppStrings.chatSettingsPlan; case .files: AppStrings.chatSettingsFiles; case .usage: AppStrings.usage; case .share: AppStrings.share }
    }
    @ViewBuilder private var tabContent: some View {
        switch activeTab {
        case .plan:
            VStack(alignment: .leading, spacing: .spacing4) {
                if model.loading { ProgressView(); Text(AppStrings.chatSettingsLoadingPlans).font(.omSmall) }
                else if model.plans.isEmpty { Text(isSharedViewer ? AppStrings.chatSettingsNoSharedPlan : AppStrings.chatSettingsNoPlan).font(.omSmall).foregroundStyle(Color.fontSecondary) }
                else { ForEach(model.plans) { row in ChatSettingsCard { planningRow(row) }.accessibilityIdentifier("chat-settings-plan-row") } }
            }.accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-tabpanel-plan")
        case .tasks:
            VStack(alignment: .leading, spacing: .spacing4) {
                if !isSharedViewer {
                    ChatSettingsCard {
                        Text(AppStrings.chatSettingsCreateTask).font(.omH3.weight(.bold))
                        OMSettingsTextInput(label: AppStrings.chatSettingsTaskTitle, placeholder: AppStrings.chatSettingsTaskTitle, value: $taskTitle, identifier: "chat-settings-task-title-input")
                        OMSettingsTextInput(label: AppStrings.tasksDescription, placeholder: AppStrings.chatSettingsTaskContext, value: $taskDescription, identifier: "chat-settings-task-description-input", multiline: true)
                        Button(action: createTask) {
                            Text(model.saving ? AppStrings.chatSettingsCreating : AppStrings.chatSettingsCreateTask)
                                .font(.omP.weight(.bold)).foregroundStyle(Color.fontButton)
                                .padding(.horizontal, .spacing12).frame(height: 41)
                                .background(LinearGradient.primary).clipShape(Capsule())
                                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                        }.buttonStyle(.plain).disabled(model.saving || taskTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            .opacity(model.saving || taskTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.5 : 1)
                            .accessibilityIdentifier("chat-settings-task-create-button")
                    }.accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-task-create-form")
                }
                ChatSettingsCard {
                    Text(AppStrings.tasks).font(.omH3.weight(.bold))
                    ChatSettingsTaskProgress(percent: ChatSettingsProjection.progress(model.tasks))
                    if model.loading { ProgressView(); Text(AppStrings.chatSettingsLoadingTasks).font(.omSmall) }
                    else if model.tasks.isEmpty { Text(isSharedViewer ? AppStrings.chatSettingsNoSharedTasks : AppStrings.chatSettingsNoTasks).font(.omSmall).foregroundStyle(Color.fontSecondary) }
                    else {
                        ForEach(model.tasks) { row in
                            VStack(alignment: .leading, spacing: .spacing2) {
                                planningRow(row)
                                if !isSharedViewer {
                                    ChatSettingsTaskCheckbox(checked: row.status == "done", action: { toggleTask(row) }).disabled(model.saving)
                                }
                            }.accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-task-row")
                        }
                    }
                }
            }.accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-tabpanel-tasks")
        case .files:
            VStack(alignment: .leading, spacing: .spacing4) {
                OMSettingsRow(title: AppStrings.chatSettingsDownloadFiles, subtitleBottom: AppStrings.chatSettingsDownloadableCount(fileRows.count), icon: "download", plainIcon: true, showsChevron: false, accessibilityIdentifier: "chat-settings-download-files") { exportChat(zip: true) }.disabled(fileRows.isEmpty || exporting)
                if fileRows.isEmpty { Text(AppStrings.chatSettingsNoFiles).font(.omSmall).foregroundStyle(Color.fontSecondary) }
                ForEach(fileRows) { file in
                    fileRow(file)
                }
            }.accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-tabpanel-files")
        case .usage:
            VStack(alignment: .leading, spacing: .spacing4) {
                OMSettingsRow(title: AppStrings.chatSettingsDownloadUsage, subtitleBottom: "CSV & YAML", icon: "download", plainIcon: true, showsChevron: false, accessibilityIdentifier: "chat-settings-download-usage") { exportUsage() }.disabled(usage.rows.isEmpty)
                ChatSettingsCard(spacing: 0) {
                    ChatSettingsUsageDisplayRow(title: AppStrings.usage, credits: displayedCredits, icon: "usage")
                        .accessibilityIdentifier("chat-settings-usage-total")
                        .accessibilityValue(String(Int((displayedCredits).rounded())))
                    if usage.rows.isEmpty { OMSettingsInfoBox(message: AppStrings.chatSettingsUsageEmpty, identifier: "chat-settings-usage-empty") }
                    ForEach(usage.rows) { row in
                        ChatSettingsUsageDisplayRow(title: row.label, subtitle: row.subtitle, credits: row.credits, icon: row.iconName, iconIdentifier: "chat-settings-usage-icon-\(row.id)")
                            .accessibilityIdentifier("chat-settings-usage-row")
                    }
                    if let error = usage.error { OMSettingsInfoBox(kind: .warning, message: error, identifier: "chat-settings-usage-error") }
                }
            }.accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-tabpanel-usage")
        case .share:
            ChatSettingsShareSection(chat: chat, accountID: accountID, shared: isSharedViewer, example: isExample, originalShareURL: originalShareURL, preview: isPreview, onDownload: exportChat)
                .accessibilityElement(children: .contain).accessibilityIdentifier("chat-settings-tabpanel-share")
        }
    }
    private func fileRow(_ file: EmbedRecord) -> some View {
        let metadata = EmbedMediaPayload.string(file.rawData, keys: ["file_metadata"]) ?? file.type
        let icon = EmbedMediaPayload.string(file.rawData, keys: ["file_icon"]) ?? "files"
        return OMSettingsRow(title: ChatSettingsExport.title(file), subtitleBottom: metadata, icon: icon, plainIcon: true,
                             iconAccessibilityIdentifier: "chat-settings-file-icon-\(file.id)", titleLineLimit: 1, showsChevron: false,
                             accessibilityIdentifier: "chat-settings-file-row") { exportFile(file) }.disabled(exporting)
    }
    private func planningRow(_ row: ChatSettingsPlanningRow) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack(spacing: .spacing2) {
                Text(row.title).font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                Spacer(minLength: .spacing2)
                ChatSettingsStatusBadge(status: row.status).fixedSize()
            }
            if !row.detail.isEmpty { Text(row.detail).font(.omP.weight(.medium)).foregroundStyle(Color.grey70).lineSpacing(2.4) }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private func createTask() {
        #if DEBUG
        if isPreview {
            model.tasks.insert(.init(id: UUID().uuidString, title: taskTitle.trimmingCharacters(in: .whitespacesAndNewlines), detail: taskDescription, status: "todo"), at: 0)
            taskTitle = ""; taskDescription = ""; return
        }
        #endif
        Task { if await model.create(title: taskTitle, description: taskDescription, chatID: chat.id, accountID: accountID, shared: isSharedViewer) { taskTitle = ""; taskDescription = "" } }
    }
    private func toggleTask(_ row: ChatSettingsPlanningRow) {
        #if DEBUG
        if isPreview, let index = model.tasks.firstIndex(where: { $0.id == row.id }) {
            model.tasks[index] = .init(id: row.id, title: row.title, detail: row.detail, status: row.status == "done" ? "todo" : "done"); return
        }
        #endif
        Task { await model.toggle(row, accountID: accountID, shared: isSharedViewer) }
    }
    private func exportChat(zip: Bool) {
        guard !exporting else { return }
        resetExportReceipt()
        exporting = true; exportError = nil; exportPhase = .downloading
        Task {
            defer { exporting = false }
            do {
                let session = try await exportSession()
                let data = zip ? try await ChatSettingsExport.zip(chat: chat, messages: messages, embeds: fileRows, scope: session.scope, recipientContext: session.recipient, check: session.check) : try ChatSettingsExport.yaml(chat: chat, messages: messages)
                try await session.check()
                exportDocument = .init(data: data); exportType = zip ? .zip : UTType(filenameExtension: "yaml") ?? .plainText
                exportName = zip ? "chat.zip" : "chat.yaml"; exportPhase = .presenting; showExporter = true
            } catch { failExport() }
        }
    }
    private func exportFile(_ file: EmbedRecord) {
        guard !exporting else { return }
        resetExportReceipt()
        exporting = true; exportError = nil; exportPhase = .downloading
        Task {
            defer { exporting = false }
            do {
                let session = try await exportSession()
                let exported = try await ChatSettingsExport.file(file, scope: session.scope, recipientContext: session.recipient)
                try await session.check()
                exportDocument = .init(data: exported.data); exportType = exported.contentType; exportName = exported.filename; exportPhase = .presenting; showExporter = true
            } catch { failExport() }
        }
    }
    private func exportUsage() {
        guard !exporting else { return }
        resetExportReceipt()
        exporting = true; exportError = nil; exportPhase = .downloading
        defer { exporting = false }
        do {
            exportDocument = .init(data: try usage.export()); exportType = .zip; exportName = "chat-usage.zip"
            exportPhase = .presenting; showExporter = true
        } catch { failExport() }
    }
    private func completeExport(_ result: Result<URL, Error>) {
        exportDocument = nil
        switch result {
        case .success(let url):
            #if DEBUG
            recordExportReceipt(url)
            #endif
            exportError = nil; exportPhase = .idle
        case .failure(let error):
            let cocoa = error as NSError
            if error is CancellationError || (cocoa.domain == NSCocoaErrorDomain && cocoa.code == CocoaError.Code.userCancelled.rawValue) {
                exportError = nil; exportPhase = .idle
            } else { failExport() }
        }
    }
    private func failExport() {
        exportDocument = nil; exportError = AppStrings.chatSettingsExportFailed; exportPhase = .failed
    }

    private func exportSession() async throws -> (scope: String?, recipient: RecipientMediaContext?, check: () async throws -> Void) {
        if isExample {
            let profile = ServerProfile.current()
            return (nil, nil, { guard profile == ServerProfile.current() else { throw UserTasksError.accountChanged } })
        }
        if isSharedViewer {
            guard let recipientMediaContext else { throw UserTasksError.accountChanged }
            try recipientMediaContext.checkCurrent()
            return (recipientMediaContext.namespace, recipientMediaContext, { try recipientMediaContext.checkCurrent() })
        }
        let generation = OfflineStore.shared.scopeGeneration
        let profile = ServerProfile.current()
        let owner = await AuthManager.currentUserId()
        let check: () async throws -> Void = {
            guard generation == OfflineStore.shared.scopeGeneration,
                  profile == ServerProfile.current(), owner == (await AuthManager.currentUserId()) else {
                throw UserTasksError.accountChanged
            }
        }
        return (OfflineStore.shared.activeScopeId, nil, check)
    }
    #if DEBUG
    static func preview(shared: Bool = false, example: Bool = false, populatedUsage: Bool = false, allPlans: Bool = false) -> ChatSettingsView {
        let chat = Chat(id: example ? "example-audio-speak-openmates-welcome-message" : "preview-chat-settings", title: "Launch preparation", lastMessageAt: nil, createdAt: "2026-10-01T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false, appId: nil,
            chatSummary: "Coordinate the work and verify the outcome before completion.", encryptedTitle: nil, encryptedChatKey: nil, budgetSpent: example ? nil : 24)
        let rows: [ChatSettingsUsageRow] = example ? PublicChatUsageCatalog.rows(chatID: chat.id) : populatedUsage ? [
            .init(id: "preview-usage-ai", label: "ai | ask", provider: "Google AI Studio / US", credits: 12, timestamp: "2026-10-01T12:00:00Z", appID: "ai"),
            .init(id: "preview-usage-web", label: "web | search", provider: "Brave / EU", credits: 12, timestamp: "2026-10-01T12:01:00Z", appID: "web")
        ] : []
        return ChatSettingsView(chat: chat, accountID: nil, isSharedViewer: shared, isExample: example, exampleUsageRows: rows, exampleFileLoader: example ? { PublicChatFileCatalog.rows(chatID: chat.id) } : nil, previewPlanCount: allPlans ? 8 : 1, isPreview: true, initialTab: populatedUsage ? .usage : .plan)
    }
    #endif
}

// SettingsItem usage headings/quickactions: icon tile, title and credits, with
// provider/date below. Web row padding is 4px vertical / 10px horizontal.
private struct ChatSettingsUsageDisplayRow: View {
    let title: String
    var subtitle: String? = nil
    let credits: Double?
    let icon: String
    var iconIdentifier: String = "chat-settings-usage-total-icon"
    var body: some View {
        HStack(spacing: .spacing6) {
            Icon(icon, size: 22).foregroundStyle(LinearGradient.primary).frame(width: 44, height: 44)
                .background(LinearGradient(colors: [Color.grey20, Color.grey30], startPoint: .topLeading, endPoint: .bottomTrailing)).clipShape(RoundedRectangle(cornerRadius: .radius4))
                .accessibilityLabel(icon).accessibilityIdentifier(iconIdentifier)
            VStack(alignment: .leading, spacing: .spacing1) {
                Text(title).font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                if let subtitle, !subtitle.isEmpty { Text(subtitle).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            }.frame(maxWidth: .infinity, alignment: .leading)
            HStack(spacing: .spacing1) {
                Text(credits.map { String(Int($0.rounded())) } ?? "—").font(.omXs.weight(.bold))
                Icon("coins", size: 18)
            }.foregroundStyle(Color.fontSecondary)
        }.padding(.horizontal, .spacing5).padding(.vertical, .spacing2).frame(minHeight: 52)
        .accessibilityElement(children: .contain)
    }
}

private struct ChatSettingsTaskCheckbox: View {
    let checked: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: .spacing4) {
                ZStack {
                    RoundedRectangle(cornerRadius: .radius1).fill(checked ? Color.settingsPrimaryStart : Color.grey0)
                    RoundedRectangle(cornerRadius: .radius1).stroke(Color.grey70, lineWidth: 1)
                    if checked { Icon("check", size: 11).foregroundStyle(Color.fontButton) }
                }.frame(width: 13, height: 13)
                Text(AppStrings.done).font(.omP.weight(.medium)).foregroundStyle(Color.grey70)
            }.contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityAddTraits(.isToggle).accessibilityValue(checked ? "On" : "Off")
            .accessibilityIdentifier("chat-settings-task-done-toggle")
    }
}
private struct ChatSettingsTaskProgress: View {
    let percent: Int
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.chatSettingsProgress(percent)).font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontPrimary)
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20)
                    RoundedRectangle(cornerRadius: .radius1).fill(Color.settingsPrimaryStart).frame(width: geometry.size.width * CGFloat(percent) / 100)
                }
            }.frame(height: 8)
        }.padding(.horizontal, .spacing5).accessibilityElement(children: .ignore)
            .accessibilityLabel(AppStrings.chatSettingsProgress(percent)).accessibilityValue("\(percent)%").accessibilityIdentifier("chat-settings-task-progress")
    }
}
private struct ChatSettingsStatusBadge: View {
    let status: String
    private var accent: Color {
        switch status {
        case "done", "completed", "in_progress", "executing", "active": .fontPrimary
        case "blocked": .settingsWarningIcon
        default: .fontSecondary
        }
    }
    private var background: Color {
        switch status {
        // SettingsBadge's info/success variables are undefined in the rendered
        // web theme, so these statuses inherit text color with no pill fill.
        case "done", "completed", "in_progress", "executing", "active": .clear
        case "blocked": .warning.opacity(0.12)
        default: .grey20
        }
    }
    var body: some View {
        Text(status.replacingOccurrences(of: "_", with: " ")).font(.omSmall.weight(.medium)).foregroundStyle(accent)
            .padding(.horizontal, .spacing5).padding(.vertical, .spacing1)
            .background(background)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
    }
}
