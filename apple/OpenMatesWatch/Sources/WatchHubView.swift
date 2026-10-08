// Figma Watch hub and compact private Tasks and Workflows.
// Web source: frontend/packages/ui/src/components/tasks/TasksPage.svelte,
// frontend/packages/ui/src/components/tasks/TaskBoard.svelte,
// frontend/packages/ui/src/components/tasks/TaskDetailContent.svelte,
// frontend/packages/ui/src/components/workflows/WorkflowDetailPage.svelte.
// Figma: Apple watch board, node 6073:63296 (184 × 224 frames).
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.hub.compact-navigation, apple-watch.lists.read-only-private,
//             apple-watch.handoff.exact-private, apple-watch.tasks.edit-private,
//             apple-watch.workflows.compact-editor.
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.action.routing-coherent, apple-notifications.delivery.idempotent-visible

// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.watch-tiny, apple-local-model-lab.isolated-scope

import SwiftUI

enum WatchWorkspacePalette {
    // Watch greys are generated in ascending brightness; workspace surfaces
    // have fixed dark roles independently of the system color scheme.
    static let foreground = Color.white
    static let background = Color.black
    static let surface = Color(red: 0.18, green: 0.19, blue: 0.20)
}

private enum WatchHubPalette {
    // The Watch artboard uses a fixed blue navigation accent across themes.
    static let blue = Color(red: 79.0 / 255, green: 117.0 / 255, blue: 216.0 / 255)
    // Figma's In progress category stripe is #FF9500.
    static let inProgress = Color(red: 1, green: 149.0 / 255, blue: 0)
    static let selectorGradient = LinearGradient(
        colors: [Color(red: 72.0 / 255, green: 104.0 / 255, blue: 205.0 / 255),
                 Color(red: 88.0 / 255, green: 130.0 / 255, blue: 231.0 / 255)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
}

private enum WatchHubType {
    static let label = Font.custom("LexendDeca-Bold", size: 17)
    static let heading = Font.custom("LexendDeca-Bold", size: 20)
    static let row = Font.custom("LexendDeca-Medium", size: 16)
    static let workflow = Font.custom("LexendDeca-Bold", size: 16)
}

private enum WatchWorkflowBadge {
    static func gradient(for workflow: WatchWorkflowListItem) -> LinearGradient {
        guard let category = workflow.category,
              CategoryMapping.isKnownCategory(category) else { return .primary }
        return CategoryMapping.gradient(for: category)
    }

    static func symbol(for workflow: WatchWorkflowListItem) -> String {
        let name = workflow.icon?.trimmingCharacters(in: .whitespacesAndNewlines)
        let icon: String
        if let name, !name.isEmpty {
            icon = name
        } else if let category = workflow.category, CategoryMapping.isKnownCategory(category) {
            icon = CategoryMapping.lucideIconName(for: category)
        } else {
            return "calendar"
        }
        switch icon {
        case "bell": return "bell"
        case "briefcase": return "briefcase"
        case "calendar": return "calendar"
        case "check-circle": return "checkmark.circle"
        case "clock": return "clock"
        case "cloud-rain": return "cloud.rain"
        case "code": return "chevron.left.forwardslash.chevron.right"
        case "compass": return "safari"
        case "dollar-sign": return "dollarsign.circle"
        case "file-text": return "doc.text"
        case "gavel": return "hammer"
        case "heart": return "heart"
        case "mail": return "envelope"
        case "megaphone": return "megaphone"
        case "microscope": return "scope"
        case "newspaper": return "newspaper"
        case "palette": return "paintpalette"
        case "search": return "magnifyingglass"
        case "shield-check": return "checkmark.shield"
        case "sparkles": return "sparkles"
        case "trending-up": return "chart.line.uptrend.xyaxis"
        case "tv": return "tv"
        case "users": return "person.2"
        case "utensils": return "fork.knife"
        case "workflow": return "arrow.triangle.branch"
        case "wrench": return "wrench"
        case "zap": return "bolt"
        default: return "questionmark.circle"
        }
    }
}

/// The web project-management and workflow glyphs rendered at Watch scale.
private struct WatchHubSectionGlyph: View {
    let section: WatchHubSection

    var body: some View {
        Group {
            switch section {
            case .chat:
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 20, weight: .medium))
            case .tasks:
                ZStack {
                    RoundedRectangle(cornerRadius: 2).stroke(lineWidth: 1.5)
                    HStack(alignment: .top, spacing: 2) {
                        Rectangle().frame(width: 4, height: 11)
                        Rectangle().frame(width: 4, height: 7)
                        Rectangle().frame(width: 4, height: 15)
                    }
                }
                .frame(width: 20, height: 20)
            case .workflows:
                WatchWorkflowGlyph()
                    .fill()
                    .frame(width: 21, height: 21)
            }
        }
        .frame(width: 24, height: 24)
        .accessibilityHidden(true)
    }
}

private struct WatchWorkflowGlyph: Shape {
    func path(in rect: CGRect) -> Path {
        let x = rect.width / 48
        let y = rect.height / 48
        var p = Path()
        p.addRoundedRect(in: CGRect(x: 2*x, y: 1*y, width: 14*x, height: 13*y), cornerSize: CGSize(width: 1*x, height: 1*y))
        p.addRoundedRect(in: CGRect(x: 2*x, y: 33*y, width: 14*x, height: 13*y), cornerSize: CGSize(width: 1*x, height: 1*y))
        p.addRoundedRect(in: CGRect(x: 33*x, y: 1*y, width: 13*x, height: 13*y), cornerSize: CGSize(width: 1*x, height: 1*y))
        p.addRect(CGRect(x: 15*x, y: 5*y, width: 18*x, height: 4*y))
        p.move(to: CGPoint(x: 35*x, y: 13*y))
        p.addLine(to: CGPoint(x: 12*x, y: 36*y))
        p.addLine(to: CGPoint(x: 17*x, y: 40*y))
        p.addLine(to: CGPoint(x: 40*x, y: 16*y))
        p.closeSubpath()
        p.addRect(CGRect(x: 15*x, y: 37*y, width: 22*x, height: 4*y))
        p.move(to: CGPoint(x: 36*x, y: 32*y))
        p.addLine(to: CGPoint(x: 47*x, y: 39*y))
        p.addLine(to: CGPoint(x: 36*x, y: 46*y))
        p.closeSubpath()
        return p
    }
}

private struct WatchDownTriangle: Shape {
    func path(in rect: CGRect) -> Path {
        Path { path in
            path.move(to: CGPoint(x: rect.minX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.midX, y: rect.maxY))
            path.closeSubpath()
        }
    }
}

/// The web create.svg mark: an open square with the plus outside its top edge.
private struct WatchCreateGlyph: Shape {
    func path(in rect: CGRect) -> Path {
        let x = rect.width / 48
        let y = rect.height / 48
        var path = Path()
        path.addRect(CGRect(x: 0, y: 5*y, width: 3*x, height: 38*y))
        path.addRect(CGRect(x: 3*x, y: 45*y, width: 40*x, height: 3*y))
        path.addRect(CGRect(x: 45*x, y: 29*y, width: 3*x, height: 14*y))
        path.addRect(CGRect(x: 3*x, y: 0, width: 16*x, height: 3*y))
        path.addRect(CGRect(x: 32*x, y: 0, width: 5*x, height: 26*y))
        path.addRect(CGRect(x: 22*x, y: 10*y, width: 26*x, height: 5*y))
        return path
    }
}

enum WatchHubSection: String, CaseIterable, Identifiable {
    case chat, tasks, workflows

    var id: String { rawValue }

    @MainActor var title: String {
        switch self {
        case .chat: return WatchLocalization.text("common.chat")
        case .tasks: return WatchLocalization.text("navigation.tasks")
        case .workflows: return WatchLocalization.text("navigation.workflows")
        }
    }

}

@MainActor
private enum WatchHubCopy {
    static var search: String { WatchLocalization.text("activity.search") }
    static var settings: String { WatchLocalization.text("common.settings") }
    static var developers: String { WatchLocalization.text("settings.developers") }
    static var done: String { WatchLocalization.text("watch.hub.done") }
    static var loading: String { WatchLocalization.text("activity.syncing") }
    static var settingsLinkSent: String { WatchLocalization.text("watch.hub.settings_link_sent") }
    static var newOnPhone: String { WatchLocalization.text("watch.hub.new_on_phone") }
    static var inProgress: String { WatchLocalization.text("watch.hub.in_progress") }
    static var todo: String { WatchLocalization.text("watch.hub.todo") }
    static var backlog: String { WatchLocalization.text("watch.hub.backlog") }
    static var emptyTasks: String { WatchLocalization.text("watch.hub.empty_tasks") }
    static var emptyWorkflows: String { WatchLocalization.text("watch.hub.empty_workflows") }
}

struct WatchHubView: View {
    @Environment(\.scenePhase) private var scenePhase
    @State private var backgroundSyncOwner: String?
    @StateObject private var dataService: WatchHubDataService
    @StateObject private var workflowService: WatchWorkflowDetailService
    private let chatRuntime: WatchChatRuntime
    @State private var selectedSection: WatchHubSection?
    @State private var showsSectionMenu = true
    @State private var isSearching = false
    @State private var searchText = ""
    @State private var popupMessage: String?
    @State private var showsSettingsDeveloperOptions = false
    @State private var showsWhisperLab = false
    @State private var selectedTaskGroup: WatchTaskGroup = .backlog
    @State private var selectedTask: WatchTaskListItem?
    @State private var selectedWorkflow: WatchWorkflowListItem?
    @State private var workflowScope: WatchWorkflowDetailScope?

    private let currentUserId: String?
    private let currentUsername: String?
    private let currentAccountID: @MainActor @Sendable () -> String?
    private let notificationRoute: WatchNotificationRoute?
    private let onOpenItem: (WatchItemOpenRequest) -> Void
    private let onOpenSettings: () -> Void
    private let onCreate: (WatchHubSection) -> Void
    private let onNavigationBusyChange: (Bool) -> Void

    init(
        chatRuntime: WatchChatRuntime,
        currentUserId: String?,
        currentUsername: String? = nil,
        currentAccountID: @escaping @MainActor @Sendable () -> String? = { nil },
        writesAllowed: @escaping @MainActor @Sendable () -> Bool = { true },
        notificationRoute: WatchNotificationRoute? = nil,
        fixtureTasks: [WatchTaskListItem]? = nil,
        fixtureTasksError: Bool = false,
        fixtureWorkflows: [WatchWorkflowListItem]? = nil,
        workflowDetailService: WatchWorkflowDetailService? = nil,
        onNavigationBusyChange: @escaping (Bool) -> Void = { _ in },
        onOpenItem: @escaping (WatchItemOpenRequest) -> Void,
        onOpenSettings: @escaping () -> Void,
        onCreate: @escaping (WatchHubSection) -> Void
    ) {
        self.chatRuntime = chatRuntime
        self.currentUserId = currentUserId
        self.currentUsername = currentUsername
        self.currentAccountID = currentAccountID
        self.notificationRoute = notificationRoute
        self.onOpenItem = onOpenItem
        self.onOpenSettings = onOpenSettings
        self.onCreate = onCreate
        self.onNavigationBusyChange = onNavigationBusyChange
        _dataService = StateObject(wrappedValue: WatchHubDataService(
            userId: currentUserId,
            fixtureTasks: fixtureTasks, fixtureTasksError: fixtureTasksError,
            fixtureWorkflows: fixtureWorkflows,
            currentAccountID: currentAccountID, writesAllowed: writesAllowed
        ))
        _workflowService = StateObject(wrappedValue: workflowDetailService ??
            WatchWorkflowDetailService(currentAccountID: currentAccountID, writesAllowed: writesAllowed))
    }

    var body: some View {
        ZStack {
            Group {
                switch selectedSection {
                case nil:
                    Color.black
                case .chat:
                    WatchChatShellView(
                        runtime: chatRuntime,
                        currentUsername: currentUsername,
                        notificationRoute: notificationRoute,
                        isVisible: !showsSectionMenu && popupMessage == nil && !showsWhisperLab,
                        onOpenHub: openSectionMenu,
                        onOpenSettings: showSettingsPopup
                    )
                case .tasks, .workflows:
                    if let selectedTask { taskDetail(selectedTask) }
                    else if let selectedWorkflow {
                        WatchWorkflowDetailView(item: selectedWorkflow, accountScope: workflowScope,
                            service: workflowService,
                            crownActive: !showsSectionMenu && popupMessage == nil && !isSearching,
                            onClose: closeWorkflow, onOpenOnPhone: onOpenItem)
                    }
                    else { listScreen }
                }
            }
            .allowsHitTesting(!showsSectionMenu && !showsWhisperLab)
            if showsSectionMenu && selectedSection != nil {
                Color.black.opacity(0.72)
                    .ignoresSafeArea()
                    .onTapGesture { showsSectionMenu = false }
                    .transition(.opacity)
            }
            // Keep the selector mounted so its hit testing changes immediately.
            // An outgoing conditional opacity transition can otherwise receive a
            // settings tap at the former Chat row while the list is already visible.
            selector
                .opacity(showsSectionMenu ? 1 : 0)
                .allowsHitTesting(showsSectionMenu)
                .accessibilityHidden(!showsSectionMenu)
                .zIndex(1)
            if let popupMessage {
                Color.black.opacity(0.65).ignoresSafeArea()
                VStack(spacing: 12) {
                    Text(popupMessage)
                        .font(.omXs)
                        .fontWeight(.semibold)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(WatchWorkspacePalette.foreground)
                    if showsSettingsDeveloperOptions {
                        Button {
                            self.popupMessage = nil
                            showsWhisperLab = true
                        } label: {
                            VStack(spacing: .spacing1) {
                                Text(WatchHubCopy.developers).font(.omMicro)
                                Text(WatchWhisperCopy.title).font(.omXs.weight(.semibold))
                            }
                            .foregroundStyle(WatchWorkspacePalette.foreground)
                            .padding(.vertical, .spacing2)
                            .frame(maxWidth: .infinity)
                            .background(WatchWorkspacePalette.surface, in: RoundedRectangle(cornerRadius: .radius4))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("watch-settings-developer-whisper")
                    }
                    Button { self.popupMessage = nil } label: {
                        Text(WatchHubCopy.done)
                            .font(.omXs)
                            .fontWeight(.bold)
                            .foregroundStyle(WatchWorkspacePalette.foreground)
                            .frame(maxWidth: .infinity, minHeight: 30)
                            .background(WatchHubPalette.blue, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-hub-popup-dismiss")
                }
                .padding(12)
                .frame(maxWidth: 158)
                .background(WatchWorkspacePalette.surface, in: RoundedRectangle(cornerRadius: 18))
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("watch-hub-phone-popup")
            }
            if showsWhisperLab {
                WatchWhisperLabView(onClose: { showsWhisperLab = false })
                    .zIndex(2)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black)
        .animation(.easeInOut(duration: 0.28), value: showsSectionMenu)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-hub")
        .onChange(of: foregroundNavigationBusy, initial: true) { _, busy in
            onNavigationBusyChange(busy)
            dataService.setBackgroundSyncAllowed(scenePhase == .active && !busy)
        }
        .onChange(of: scenePhase) { _, phase in
            dataService.setBackgroundSyncAllowed(phase == .active && !foregroundNavigationBusy)
            if phase == .active {
                Task {
                    guard scenePhase == .active, currentAccountID() == currentUserId else { return }
                    await chatRuntime.refresh()
                }
            }
        }
        .onDisappear {
            dataService.setBackgroundSyncAllowed(false)
            if let backgroundSyncOwner { WatchBackgroundOfflineSync.shared.unregister(.hub, owner: backgroundSyncOwner) }
            backgroundSyncOwner = nil
        }
        .task {
            if let account = currentAccountID() {
                let owner = "\(account):\(ServerProfile.current().apiBaseURL.absoluteString):\(WatchChatAccountLifecycle.generation)"
                backgroundSyncOwner = owner
                let service = dataService
                WatchBackgroundOfflineSync.shared.register(.hub, owner: owner) { [weak service] in
                    await service?.performBackgroundOfflineSync()
                }
            }
            await dataService.loadCachedTasks()
            await dataService.loadCachedWorkflows()
        }
        .task(id: notificationRoute?.id) {
            guard notificationRoute != nil else { return }
            showsWhisperLab = false
            selectedSection = .chat
            selectedTask = nil
            closeWorkflow()
            showsSectionMenu = false
            popupMessage = nil
            isSearching = false
        }
    }

    private var foregroundNavigationBusy: Bool {
        showsWhisperLab || selectedTask != nil || selectedWorkflow != nil || popupMessage != nil || isSearching

    }

    private var selector: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(WatchHubSection.allCases) { section in
                Button {
                    select(section)
                } label: {
                    HStack(spacing: 19) {
                        WatchHubSectionGlyph(section: section)
                        Text(section.title)
                            .font(WatchHubType.label)
                            .lineLimit(1)
                            .minimumScaleFactor(0.75)
                        Spacer(minLength: 0)
                    }
                    .foregroundStyle(WatchWorkspacePalette.foreground)
                    .padding(.leading, 27)
                    .padding(.trailing, 6)
                    .frame(height: 60)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("watch-hub-select-\(section.rawValue)")
            }
        }
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity)
        .background(WatchHubPalette.selectorGradient, in: RoundedRectangle(cornerRadius: 30))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        .ignoresSafeArea(edges: .bottom)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-hub-selector")
    }

    private var listScreen: some View {
        VStack(spacing: 0) {
            header.zIndex(1)
            actions.padding(.vertical, .spacing2)
            if isSearching {
                TextField(WatchHubCopy.search, text: $searchText)
                    .font(.omXs)
                    .foregroundStyle(WatchWorkspacePalette.foreground)
                    .tint(WatchHubPalette.blue)
                    .padding(.horizontal, .spacing3)
                    .frame(height: 28)
                    .background(WatchWorkspacePalette.surface, in: Capsule())
                    .padding(.horizontal, .spacing3)
                    .accessibilityIdentifier("watch-hub-search-input")
            }
            if selectedSection == .tasks {
                taskGroups
            } else {
                ScrollView {
                    workflowRows.padding(.horizontal, .spacing3).padding(.top, .spacing4)
                }
                .refreshable { await dataService.refreshWorkflows() }
            }
        }
        .ignoresSafeArea(edges: .top)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-hub-list")
    }

    private var header: some View {
        Button(action: openSectionMenu) {
            HStack(spacing: 0) {
                if let selectedSection {
                    WatchHubSectionGlyph(section: selectedSection)
                        .scaleEffect(0.82)
                }
                Spacer(minLength: 0)
                WatchDownTriangle()
                    .fill()
                    .frame(width: 24, height: 14)
            }
            .foregroundStyle(WatchWorkspacePalette.foreground)
            .padding(.horizontal, 13)
            .frame(width: 106, height: 42)
            .background(WatchHubPalette.blue, in: Capsule())
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(height: 49)
        .padding(.leading, 11)
        .background(Color.black)
        .accessibilityLabel(selectedSection?.title ?? "")
        .accessibilityIdentifier("watch-hub-section-selector")
    }

    private var actions: some View {
        HStack(spacing: 0) {
            action("magnifyingglass", label: WatchHubCopy.search, id: "watch-hub-search") {
                isSearching.toggle()
                if !isSearching { searchText = "" }
            }
            action("watch-create", label: selectedSection?.title ?? "", id: "watch-hub-new") {
                if let selectedSection {
                    onCreate(selectedSection)
                    showsSettingsDeveloperOptions = false
                    popupMessage = WatchHubCopy.newOnPhone
                }
            }
            action("gearshape.fill", label: WatchHubCopy.settings, id: "watch-hub-settings") {
                showSettingsPopup()
            }
        }
        .foregroundStyle(WatchHubPalette.blue)
        .padding(.horizontal, -11)
    }

    private func action(_ symbol: String, label: String, id: String, perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            Group {
                if symbol == "watch-create" {
                    WatchCreateGlyph().fill().frame(width: 24, height: 24)
                } else {
                    Image(systemName: symbol).font(.system(size: 24))
                }
            }
            .frame(maxWidth: .infinity, minHeight: 32)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier(id)
    }

    private var taskColumnFocusTarget: WatchTaskGroup? {
        guard selectedSection == .tasks, !showsSectionMenu, !isSearching,
              popupMessage == nil, selectedTask == nil, selectedWorkflow == nil else { return nil }
        return selectedTaskGroup
    }

    private var taskGroups: some View {
        TabView(selection: $selectedTaskGroup) {
            ForEach(WatchTaskGroup.allCases) { group in
                taskColumn(group).tag(group)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .automatic))
        .accessibilityIdentifier("watch-task-board")
    }

    private func taskColumn(_ group: WatchTaskGroup) -> some View {
        let items = filteredTasks.filter { $0.group == group }
        return WatchCrownScrollView(active: taskColumnFocusTarget == group, identity: group.status) {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack(spacing: .spacing2) {
                    RoundedRectangle(cornerRadius: .radius1)
                        .fill(taskAccent(group)).frame(width: 4, height: 25)
                    Text(groupTitle(group)).font(.omSmall.weight(.bold))
                    Text("(\(items.count))").font(.omMicro).foregroundStyle(WatchWorkspacePalette.foreground)
                }
                .foregroundStyle(WatchWorkspacePalette.foreground)
                .accessibilityIdentifier("watch-task-group-\(group.id)")
                if dataService.isLoadingTasks && dataService.tasks.isEmpty { statusText(WatchHubCopy.loading) }
                else if dataService.tasksError { statusText(WatchStrings.offlineBanner).accessibilityIdentifier("watch-task-offline") }
                if items.isEmpty && !dataService.isLoadingTasks { statusText(WatchHubCopy.emptyTasks) }
                ForEach(items) { item in
                    Button { selectedTask = item } label: {
                        Text(item.title)
                            .font(.omXs.weight(.medium))
                            .foregroundStyle(WatchWorkspacePalette.foreground)
                            .lineLimit(3)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.spacing3)
                            .background(WatchWorkspacePalette.surface, in: RoundedRectangle(cornerRadius: .radius4))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-task-row-\(item.id)")
                }
            }
            .padding(.horizontal, .spacing3)
            .padding(.top, .spacing2)
            .padding(.bottom, .spacing6)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .refreshable { await dataService.refreshTasks() }
        .accessibilityIdentifier("watch-task-column-\(group.status)")
    }

    private func taskDetail(_ item: WatchTaskListItem) -> some View {
        WatchTaskDetailView(service: dataService, item: item,
            onClose: { selectedTask = nil }, onOpenItem: onOpenItem,
            onSaved: { updated in
                selectedTask = updated
                selectedTaskGroup = updated.group
            }
        )
    }

    private func taskAccent(_ group: WatchTaskGroup) -> Color {
        switch group {
        case .backlog: .chatRainbowPurple
        case .todo: .chatRainbowCyan
        case .inProgress: .warning
        case .blocked: .error
        case .done: .chatRainbowGreen
        }
    }

    private var workflowRows: some View {
        VStack(alignment: .leading, spacing: 12) {
            if dataService.isLoadingWorkflows && dataService.workflows.isEmpty { statusText(WatchHubCopy.loading) }
            else if dataService.workflowsError && dataService.workflows.isEmpty { statusText(WatchStrings.offlineBanner) }
            else if filteredWorkflows.isEmpty { statusText(WatchHubCopy.emptyWorkflows) }
            ForEach(filteredWorkflows) { workflow in
                Button {
                    workflowScope = currentAccountID().map { WatchWorkflowDetailScope.capture(accountID: $0) }
                    selectedWorkflow = workflow
                } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: WatchWorkflowBadge.symbol(for: workflow))
                            .font(.omXs)
                            .foregroundStyle(WatchWorkspacePalette.foreground)
                            .frame(width: 30, height: 30)
                            .background(WatchWorkflowBadge.gradient(for: workflow), in: Circle())
                        Text(workflow.title)
                            .font(WatchHubType.workflow)
                            .foregroundStyle(WatchWorkspacePalette.foreground)
                            .lineLimit(2)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("watch-workflow-row-\(workflow.id)")
            }
        }
        .padding(.horizontal, 6)
    }

    private func statusText(_ value: String) -> some View {
        Text(value)
            .font(.omXs)
            .foregroundStyle(WatchWorkspacePalette.foreground)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.vertical, 12)
    }

    private func groupTitle(_ group: WatchTaskGroup) -> String {
        switch group {
        case .inProgress: return WatchHubCopy.inProgress
        case .todo: return WatchHubCopy.todo
        case .backlog: return WatchHubCopy.backlog
        case .blocked: return WatchLocalization.text("watch.hub.blocked")
        case .done: return WatchHubCopy.done
        }
    }

    private var filteredTasks: [WatchTaskListItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return dataService.tasks }
        return dataService.tasks.filter { $0.title.localizedCaseInsensitiveContains(query) }
    }

    private var filteredWorkflows: [WatchWorkflowListItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return dataService.workflows }
        return dataService.workflows.filter { $0.title.localizedCaseInsensitiveContains(query) }
    }

    private func select(_ section: WatchHubSection) {
        selectedSection = section
        selectedTask = nil
        closeWorkflow()
        showsSectionMenu = false
        isSearching = false
        searchText = ""
        if section == .tasks { Task { await dataService.refreshTasks() } }
        if section == .workflows { Task { await dataService.refreshWorkflows() } }
    }

    private func openSectionMenu() {
        showsSectionMenu = true
    }

    private func closeWorkflow() {
        selectedWorkflow = nil
        workflowScope = nil
        workflowService.clear()
    }

    private func showSettingsPopup() {
        onOpenSettings()
        showsSettingsDeveloperOptions = true
        popupMessage = WatchHubCopy.settingsLinkSent
    }
}

#if DEBUG
/// Diagnostic control for simulator Crown delivery, isolated from hub paging,
/// overlays, custom gestures, refresh controls and explicit focus modifiers.
struct WatchNativeCrownDiagnosticView: View {
    var body: some View {
        ScrollView(.vertical) {
            VStack(spacing: .spacing2) {
                ForEach(0..<12) { index in
                    Text("Crown row \(index + 1)")
                        .font(.omXs)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .accessibilityIdentifier("watch-native-crown-row-\(index)")
                }
            }
        }
        .accessibilityIdentifier("watch-native-crown-scroll")
    }
}
#endif
