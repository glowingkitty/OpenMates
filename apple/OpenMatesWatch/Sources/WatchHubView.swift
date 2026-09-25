// Figma Watch hub and compact read-only Tasks and Workflows lists.
// Web source: frontend/packages/ui/src/components/tasks/TasksPage.svelte,
// frontend/packages/ui/src/components/tasks/TaskBoard.svelte,
// frontend/packages/ui/src/components/workflows/WorkflowDetailPage.svelte.
// Figma: Apple watch board, node 6073:63296 (184 × 224 frames).
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.hub.compact-navigation, apple-watch.lists.read-only-private,
//             apple-watch.handoff.exact-private.

import SwiftUI

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
    @StateObject private var dataService: WatchHubDataService
    @State private var selectedSection: WatchHubSection?
    @State private var showsSectionMenu = true
    @State private var isSearching = false
    @State private var searchText = ""
    @State private var popupMessage: String?

    private let currentUserId: String?
    private let currentUsername: String?
    private let webSocketToken: String?
    private let onOpenItem: (WatchItemOpenRequest) -> Void
    private let onOpenSettings: () -> Void
    private let onCreate: (WatchHubSection) -> Void

    init(
        currentUserId: String?,
        currentUsername: String? = nil,
        webSocketToken: String?,
        fixtureTasks: [WatchTaskListItem]? = nil,
        fixtureWorkflows: [WatchWorkflowListItem]? = nil,
        onOpenItem: @escaping (WatchItemOpenRequest) -> Void,
        onOpenSettings: @escaping () -> Void,
        onCreate: @escaping (WatchHubSection) -> Void
    ) {
        self.currentUserId = currentUserId
        self.currentUsername = currentUsername
        self.webSocketToken = webSocketToken
        self.onOpenItem = onOpenItem
        self.onOpenSettings = onOpenSettings
        self.onCreate = onCreate
        _dataService = StateObject(wrappedValue: WatchHubDataService(
            userId: currentUserId,
            fixtureTasks: fixtureTasks,
            fixtureWorkflows: fixtureWorkflows
        ))
    }

    var body: some View {
        ZStack {
            Group {
                switch selectedSection {
                case nil:
                    Color.black
                case .chat:
                    WatchChatShellView(
                        currentUserId: currentUserId,
                        currentUsername: currentUsername,
                        webSocketToken: webSocketToken,
                        onOpenHub: openSectionMenu,
                        onOpenSettings: showSettingsPopup
                    )
                case .tasks, .workflows:
                    listScreen
                }
            }
            .allowsHitTesting(!showsSectionMenu)
            if showsSectionMenu {
                if selectedSection != nil {
                    Color.black.opacity(0.72)
                        .ignoresSafeArea()
                        .onTapGesture { showsSectionMenu = false }
                        .transition(.opacity)
                }
                selector
                    .transition(.opacity)
                    .zIndex(1)
            }
            if let popupMessage {
                Color.black.opacity(0.65).ignoresSafeArea()
                VStack(spacing: 12) {
                    Text(popupMessage)
                        .font(.omXs)
                        .fontWeight(.semibold)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(Color.grey0)
                    Button { self.popupMessage = nil } label: {
                        Text(WatchHubCopy.done)
                            .font(.omXs)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.grey0)
                            .frame(maxWidth: .infinity, minHeight: 30)
                            .background(WatchHubPalette.blue, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-hub-popup-dismiss")
                }
                .padding(12)
                .frame(maxWidth: 158)
                .background(Color.grey90, in: RoundedRectangle(cornerRadius: 18))
                .accessibilityIdentifier("watch-hub-phone-popup")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black)
        .animation(.easeInOut(duration: 0.28), value: showsSectionMenu)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-hub")
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
                    .foregroundStyle(Color.grey0)
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
            header
                .zIndex(1)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    actions
                        .padding(.bottom, isSearching ? 8 : 26)
                    if isSearching {
                        TextField(WatchHubCopy.search, text: $searchText)
                            .font(.omXs)
                            .foregroundStyle(Color.grey0)
                            .tint(WatchHubPalette.blue)
                            .padding(.horizontal, 10)
                            .frame(height: 28)
                            .background(Color.grey90, in: Capsule())
                            .padding(.bottom, 12)
                            .accessibilityIdentifier("watch-hub-search-input")
                    }
                    if selectedSection == .tasks {
                        taskGroups
                    } else {
                        workflowRows
                            .padding(.top, 19)
                    }
                }
                .padding(.horizontal, 11)
                .padding(.top, 40)
            }
            .refreshable {
                if selectedSection == .tasks { await dataService.refreshTasks() }
                else { await dataService.refreshWorkflows() }
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
            .foregroundStyle(Color.grey0)
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

    private var taskGroups: some View {
        VStack(alignment: .leading, spacing: 13) {
            if dataService.isLoadingTasks && dataService.tasks.isEmpty { statusText(WatchHubCopy.loading) }
            else if dataService.tasksError && dataService.tasks.isEmpty { statusText(WatchStrings.offlineBanner) }
            else if filteredTasks.isEmpty { statusText(WatchHubCopy.emptyTasks) }
            ForEach(WatchTaskGroup.allCases) { group in
                let items = filteredTasks.filter { $0.group == group }
                if !items.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 4) {
                            Rectangle()
                                .fill(group == .inProgress ? WatchHubPalette.inProgress : WatchHubPalette.blue)
                                .frame(width: 4, height: 25)
                            Text(groupTitle(group))
                                .font(WatchHubType.heading)
                                .foregroundStyle(Color.grey0)
                        }
                        .accessibilityIdentifier("watch-task-group-\(group.id)")
                        ForEach(items) { item in
                            Button { onOpenItem(item.openRequest) } label: {
                                Text(item.title)
                                    .font(WatchHubType.row)
                                    .foregroundStyle(Color.grey0)
                                    .lineLimit(3)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.horizontal, 9)
                                    .padding(.vertical, 7)
                                    .background(Color.grey90, in: RoundedRectangle(cornerRadius: 16))
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("watch-task-row-\(item.id)")
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(.horizontal, 10)
    }

    private var workflowRows: some View {
        VStack(alignment: .leading, spacing: 12) {
            if dataService.isLoadingWorkflows && dataService.workflows.isEmpty { statusText(WatchHubCopy.loading) }
            else if dataService.workflowsError && dataService.workflows.isEmpty { statusText(WatchStrings.offlineBanner) }
            else if filteredWorkflows.isEmpty { statusText(WatchHubCopy.emptyWorkflows) }
            ForEach(filteredWorkflows) { workflow in
                Button { onOpenItem(workflow.openRequest) } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: WatchWorkflowBadge.symbol(for: workflow))
                            .font(.omXs)
                            .foregroundStyle(Color.grey0)
                            .frame(width: 30, height: 30)
                            .background(WatchWorkflowBadge.gradient(for: workflow), in: Circle())
                        Text(workflow.title)
                            .font(WatchHubType.workflow)
                            .foregroundStyle(Color.grey0)
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
            .foregroundStyle(Color.grey30)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.vertical, 12)
    }

    private func groupTitle(_ group: WatchTaskGroup) -> String {
        switch group {
        case .inProgress: return WatchHubCopy.inProgress
        case .todo: return WatchHubCopy.todo
        case .backlog: return WatchHubCopy.backlog
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
        showsSectionMenu = false
        isSearching = false
        searchText = ""
        if section == .tasks { Task { await dataService.refreshTasks() } }
        if section == .workflows { Task { await dataService.refreshWorkflows() } }
    }

    private func openSectionMenu() {
        showsSectionMenu = true
    }

    private func showSettingsPopup() {
        onOpenSettings()
        popupMessage = WatchHubCopy.settingsLinkSent
    }
}
