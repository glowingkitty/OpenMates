import SwiftUI
import UniformTypeIdentifiers
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// The central Tasks surface follows TasksPage.svelte and TaskBoard.svelte. The
/// shell retains `store`; this view does not own account or team state.
// Web source: frontend/packages/ui/src/components/tasks/TasksPage.svelte
//             frontend/packages/ui/src/components/chats/Chats.svelte (.chats-topbar)
//             frontend/packages/ui/src/components/tasks/TaskBoard.svelte
//             frontend/packages/ui/src/components/workspace/WorkspaceHomeShell.svelte
// Specification: specifications/features/tasks/specification.yml
// Assertions: tasks.lifecycle.visible, tasks.detail.embed-responsive, tasks.surface.semantic-parity
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.context-menu, apple-task-board.drag-move, apple-task-board.workflow-run, apple-task-board.new-task-shortcuts
struct TasksWorkspaceView: View {
    @ObservedObject var store: TasksWorkspaceStore
    @Environment(\.isEnabled) private var workspaceIsEnabled
    var composerFocusRequestID: UUID? = nil
    var showPlansOnly = false
    var compactProjectBoard = false
    var showsComposer = true
    var presentsDetail = true
    var inspiration: DailyInspirationData? = nil
    var onStartInspiration: (String) -> Void = { _ in }
    var onOpenProject: (String) -> Void = { _ in }
    var onOpenChat: (String) -> Void = { _ in }
    var onOpenWorkflowRun: (String, String?) -> Void = { _, _ in }
    var onReportIssue: () -> Void = {}

    @State private var searchExpanded = false
    @State private var filtersExpanded = false
    @State private var desktopFiltersExpanded = true
    @State private var showingNewTask = false
    @State private var newTaskTitle = ""
    @State private var newPlanGoal = ""
    @State private var newPlanProjectID = ""
    @State private var visibleCounts: [UserTaskStatus: Int] = [:]
    @State private var pendingDelete: UserTaskItem?
    @State private var inspirationIndex = 0
    @State private var cardActionsID: String?
    @State private var hoveredCardID: String?
    @State private var draggedTaskID: String?
    @State private var dragToken: String?
    @State private var dragGeneration: UUID?
    @State private var targetedColumn: UserTaskStatus?
    @State private var cardFrames: [String: CGRect] = [:]
    @State private var keyboardFrame: CGRect?
    @State private var compactWidth: CGFloat = 370
    @State private var promptActive = false
    @State private var promptDismissID: UUID?
    @State private var promptAvailableHeight: CGFloat = 350
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var boardAnimation: Animation? { reduceMotion ? nil : .easeOut(duration: 0.18) }

    var body: some View {
        Group {
            if compactProjectBoard {
                VStack(spacing: 0) {
                    workspaceContent(narrow: compactWidth <= 900, workspaceWidth: compactWidth, height: 0)
                        .padding(.bottom, 12)
                    if showsComposer { composer }
                }
                .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { compactWidth = $0 }
            } else {
                GeometryReader { geometry in
                    let split = geometry.size.width >= 1100
                        && (store.selectedTaskID != nil || store.selectedWorkflowRunID != nil)
                    let workspaceWidth = split ? max(340, geometry.size.width * 0.32) : geometry.size.width
                    let keyboardOverlap = TasksWorkspaceLayoutPolicy.keyboardOverlap(
                        container: geometry.frame(in: .global), keyboard: keyboardFrame)
                    VStack(spacing: 0) {
                        ScrollView(.vertical) {
                            workspaceContent(narrow: workspaceWidth <= 900,
                                workspaceWidth: workspaceWidth, height: geometry.size.height)
                                .padding(.bottom, 12)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                        .accessibilityIdentifier("tasks-workspace-scroll")
                        .workspacePromptBackground(active: promptActive, identifier: "task-workspace-backdrop",
                onDismiss: { promptDismissID = UUID() })
                        if showsComposer {
                            if promptActive, let error = store.errorMessage ?? store.interactionErrorMessage {
                                Text(error).font(.omSmall).foregroundStyle(Color.error)
                                    .padding(.horizontal, .spacing6)
                                    .accessibilityIdentifier(store.errorMessage != nil ? "tasks-load-error" : "task-move-error")
                            }
                            composer
                        }
                    }
                    .frame(width: geometry.size.width,
                        height: max(0, geometry.size.height - keyboardOverlap), alignment: .top)
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { promptAvailableHeight = $0 }
                }
            }
        }
            .background(Color.grey20.ignoresSafeArea())
            .coordinateSpace(name: "tasks-workspace")
            .onPreferenceChange(TaskCardFramesKey.self) { cardFrames = $0 }
            #if os(iOS)
            .background {
                if !promptActive && workspaceIsEnabled {
                    TaskTouchBoardReader(taskAtPoint: { point in
                guard !promptActive, workspaceIsEnabled, !store.isSaving, pendingDelete == nil, !showingNewTask,
                      store.selectedTaskID == nil, store.selectedWorkflowRunID == nil,
                      let id = diagnosticCardID(at: point),
                      let item = store.boardItems.first(where: { $0.id == id }), case .task(let task) = item
                else { return nil }
                return task
            }, onBegin: beginDrag, onStationaryHold: { id in
                dragToken = nil; dragGeneration = nil; draggedTaskID = nil; targetedColumn = nil; hoveredCardID = nil
                cardActionsID = id
            }, onCancelledDrag: {
                dragToken = nil; dragGeneration = nil; draggedTaskID = nil; targetedColumn = nil; hoveredCardID = nil
                    })
                }
            }
            #endif
            #if os(macOS)
            .background {
                if !promptActive && workspaceIsEnabled {
                    TaskSecondaryClickReader { point in
                guard !promptActive, workspaceIsEnabled, pendingDelete == nil, !showingNewTask,
                      store.selectedTaskID == nil, store.selectedWorkflowRunID == nil,
                      let id = cardFrames.first(where: { $0.value.contains(point) })?.key,
                      store.boardItems.contains(where: { if case .task = $0 { return $0.id == id }; return false })
                else { return false }
                cardActionsID = id
                return true
                    }
                }
            }
            #endif
            .overlay { OMSheet(isPresented: $showingNewTask, title: showPlansOnly ? AppStrings.tasksNewPlan : AppStrings.tasksNew) { newTaskSheet } }
            .modifier(TasksDetailPresentation(selection: selectedDetailBinding,
                store: store, allowsSplit: !compactProjectBoard, isEnabled: presentsDetail,
                onOpenProject: onOpenProject, onOpenChat: onOpenChat,
                onReportIssue: onReportIssue))
            .overlay { taskActionsOverlay }
            #if DEBUG && os(iOS)
            .background(alignment: .topLeading) {
                if NativeDragDiagnostics.enabled { NativeDragDiagnosticProbe().frame(width: 1, height: 1) }
            }
            #endif
            #if DEBUG
            .task(id: store.boardItems.map(\.id)) { applyDropHoverFixture() }
            #endif
            .onDisappear { dragToken = nil; dragGeneration = nil; draggedTaskID = nil; targetedColumn = nil; hoveredCardID = nil; cardActionsID = nil }
            .onChange(of: promptActive) { _, active in if active { hoveredCardID = nil } }
            .onChange(of: workspaceIsEnabled) { _, enabled in if !enabled { hoveredCardID = nil } }
            .onChange(of: store.interactionGeneration) { _, _ in
                dragToken = nil; dragGeneration = nil; draggedTaskID = nil; targetedColumn = nil; hoveredCardID = nil; cardActionsID = nil
                #if DEBUG
                applyDropHoverFixture()
                #endif
            }
            .overlay {
                if let task = pendingDelete {
                    OMConfirmDialog(title: AppStrings.delete, message: AppStrings.tasksDeleteConfirmation,
                                    confirmTitle: AppStrings.delete, isDestructive: true,
                                    onConfirm: { pendingDelete = nil; Task { await store.deleteTask(task) } },
                                    onCancel: { pendingDelete = nil })
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("tasks-workspace")
            .task(id: showPlansOnly) {
                guard inspiration == nil, !showPlansOnly else { return }
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(11))
                    guard !Task.isCancelled else { return }
                    inspirationIndex = (inspirationIndex + 1) % 3
                }
            }
        #if os(iOS)
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)) { notification in
            guard let frame = notification.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
            let window = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
                .flatMap(\.windows).first(where: \.isKeyWindow)
            keyboardFrame = window?.convert(frame, from: nil) ?? frame
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            keyboardFrame = nil
        }
        #endif
    }

    #if DEBUG
    private func applyDropHoverFixture() {
        guard ProcessInfo.processInfo.arguments.contains("--ui-test-task-drop-hover"),
              let item = store.boardItems.first(where: {
                  if case .task(let task) = $0 { return task.status == .backlog }; return false
              }) else { return }
        draggedTaskID = item.id
        targetedColumn = .todo
    }
    #endif

    private func workspaceContent(narrow: Bool, workspaceWidth: CGFloat, height: CGFloat) -> some View {
        VStack(spacing: 0) {
            if compactProjectBoard {
                compactProjectToolbar
            } else {
                banner(width: workspaceWidth, height: height)
                toolbar(narrow: narrow)
                greeting
            }
            if store.isLoading && store.boardItems.isEmpty && store.plans.isEmpty {
                ProgressView(AppStrings.loading)
                    .frame(maxWidth: .infinity, minHeight: 180)
                    .accessibilityIdentifier("tasks-loading")
            } else if store.errorMessage != nil {
                VStack(spacing: 10) {
                    Text(AppStrings.tasksLoadError)
                    Text(store.errorMessage ?? "").font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                    Button(AppStrings.retry) { Task { await store.retryLoad() } }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("tasks-retry-load")
                }
                .frame(maxWidth: .infinity, minHeight: 160)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("tasks-load-error")
            } else {
                if let error = store.plansLoadErrorMessage {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .padding(.horizontal, .spacing6)
                        .accessibilityIdentifier("tasks-plans-load-error")
                }
                if let error = store.projectNamesLoadErrorMessage {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .padding(.horizontal, .spacing6)
                        .accessibilityIdentifier("tasks-project-names-load-error")
                }
                if (!promptActive || compactProjectBoard), let error = store.interactionErrorMessage {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .padding(.horizontal, .spacing6)
                        .accessibilityIdentifier("task-move-error")
                }
                board(narrow: narrow, width: workspaceWidth)
            }
        }

    }

    private var selectedDetailBinding: Binding<TasksDetailSelection?> {
        Binding(
            get: {
                if let id = store.selectedTaskID { return .task(id) }
                if let id = store.selectedPlanID { return .plan(id) }
                if let id = store.selectedWorkflowRunID { return .workflowRun(id) }
                return nil
            },
            set: { if $0 == nil { store.closeDetail() } }
        )
    }

    private func banner(width: CGFloat, height: CGFloat) -> some View {
        let choices = showPlansOnly ? planInspirations : taskInspirations
        let value = inspiration ?? choices[inspirationIndex % choices.count]
        return Group {
            ZStack {
                InspirationCard(inspiration: value,
                                containerSize: CGSize(width: width, height: height),
                                heightOverride: TasksWorkspaceLayoutPolicy.bannerHeight(width: width, height: height),
                                ctaTitle: showPlansOnly ? AppStrings.plansInspirationCTA : AppStrings.tasksInspirationCTA,
                                tapHint: showPlansOnly ? AppStrings.plansInspirationCTA : AppStrings.tasksInspirationCTA,
                                isInteractive: false) { }
                if inspiration == nil && choices.count > 1 {
                    HStack {
                        Button { inspirationIndex = (inspirationIndex - 1 + choices.count) % choices.count } label: {
                            Icon("back", size: 14).foregroundStyle(.white)
                                .frame(width: 28, height: 40)
                        }
                        .accessibilityLabel(AppStrings.previousInspiration)
                        Spacer()
                        Button { inspirationIndex = (inspirationIndex + 1) % choices.count } label: {
                            Icon("back", size: 14).foregroundStyle(.white)
                                .scaleEffect(x: -1)
                                .frame(width: 28, height: 40)
                        }
                        .accessibilityLabel(AppStrings.nextInspiration)
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 10)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: TasksWorkspaceLayoutPolicy.bannerHeight(width: width, height: height))
        .accessibilityIdentifier("tasks-daily-inspiration-area")
    }

    private var taskInspirations: [DailyInspirationData] {
        [DailyInspirationData(inspirationId: "hardcoded-task-next-action",
            text: AppStrings.tasksInspirationNextAction,
            title: AppStrings.tasksInspirationNextActionTitle, category: "productivity"),
         DailyInspirationData(inspirationId: "hardcoded-task-priorities",
            text: AppStrings.tasksInspirationPriorities,
            title: AppStrings.tasksInspirationPrioritiesTitle, category: "productivity"),
         DailyInspirationData(inspirationId: "hardcoded-task-finish-line",
            text: AppStrings.tasksInspirationFinishLine,
            title: AppStrings.tasksInspirationFinishLineTitle, category: "productivity")]
    }

    private var planInspirations: [DailyInspirationData] {
        [DailyInspirationData(inspirationId: "hardcoded-plan-timeline",
            text: AppStrings.plansInspirationTimeline,
            title: AppStrings.plansInspirationTimelineTitle, category: "productivity")]
    }

    private func toolbar(narrow: Bool) -> some View {
        VStack(alignment: .trailing, spacing: 10) {
            HStack(spacing: 14) {
                Button(action: onReportIssue) {
                    Icon("bug", size: 22)
                        // WorkspaceReportIssueButton uses --color-primary.
                        .foregroundStyle(LinearGradient.primary)
                        .frame(width: 42, height: 42)
                        .background(Color.grey0, in: Circle())
                        .shadow(color: .black.opacity(0.12), radius: 7, y: 3)
                }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.reportIssue)
                    .accessibilityIdentifier("tasks-report-issue-button")
                Spacer(minLength: 0)
                if !narrow {
                    if searchExpanded {
                        HStack(spacing: 6) {
                            Icon("search", size: 16)
                            TextField(AppStrings.tasksSearch, text: $store.searchText)
                                .font(.omP)
                                .accessibilityIdentifier("task-search-input")
                        }
                        .frame(width: 160)
                    } else {
                        Button {
                            searchExpanded = true
                        } label: {
                            HStack(spacing: .spacing3) {
                                Icon("search", size: 14)
                                Text(AppStrings.tasksSearch).font(.omP.weight(.bold))
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("task-search-link")
                    }
                    if desktopFiltersExpanded { filterChips }
                }
                Button { if narrow { filtersExpanded.toggle() } else { desktopFiltersExpanded.toggle() } } label: {
                    Icon("filter", size: 18)
                        // TasksPage .task-filter-button span uses --color-primary.
                        .foregroundStyle(LinearGradient.primary)
                        .frame(width: 40, height: 40)
                        .background(Color.grey0, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.tasksFilters)
                .accessibilityIdentifier("task-filter-button")
            }
            if narrow && filtersExpanded {
                HStack {
                    filterChips
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .padding(.horizontal, 16)
        .padding(.top, 10)
    }

    private var filterChips: some View {
        ScrollView(.horizontal) {
            HStack(spacing: .spacing3) {
                ForEach(store.filterTags, id: \.self) { tag in
                    Button("#\(tag)") {
                        store.searchText = store.searchText.replacingOccurrences(of: "^#", with: "", options: .regularExpression) == tag ? "" : tag
                    }
                    .font(.omXxs)
                    .buttonStyle(.plain)
                    // TasksPage.svelte .task-filter-chips: 20px height, 9px inline padding.
                    .padding(.horizontal, 9)
                    .frame(height: 20)
                    .background {
                        if store.searchText == tag { Capsule().fill(Color.buttonPrimary) }
                        else { Capsule().fill(LinearGradient.primary) }
                    }
                    .foregroundStyle(Color.fontButton)
                }
            }
        }
        .scrollIndicators(.hidden)
        .accessibilityIdentifier("task-filter-tags")
    }

    /// ProjectsPage embeds the filtered TasksPage board in its Tasks tab.
    /// The project shell owns the loaded store and its account/team lifecycle.
    private var compactProjectToolbar: some View {
        HStack(spacing: 10) {
            HStack(spacing: 6) {
                Icon("search", size: 16).foregroundStyle(Color.fontSecondary)
                TextField(AppStrings.tasksSearch, text: $store.searchText)
                    .font(.omP)
                    .accessibilityIdentifier("project-task-search-input")
            }
            .padding(10)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: 8))
            filterChips
            Button { filtersExpanded.toggle() } label: {
                Icon("filter", size: 18)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 40, height: 40)
                    .background(Color.grey0, in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.tasksFilters)
            .accessibilityIdentifier("project-task-filter-button")
        }
        .padding(.bottom, 16)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-task-toolbar")
    }

    private var greeting: some View {
        VStack(spacing: 8) {
            Text(showPlansOnly ? AppStrings.plans : AppStrings.tasksGreeting)
                .font(.omH2.weight(.semibold))
                .foregroundStyle(Color.grey80)
            if !showPlansOnly {
                Text(AppStrings.tasksNext)
                    .font(.omP.weight(.semibold))
                    .foregroundStyle(Color.grey60)
            }
        }
        .background {
            Icon("projectmanagement", size: 76)
                .foregroundStyle(Color.grey30)
                .accessibilityHidden(true)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 38)
        .padding(.bottom, 24)
        .accessibilityIdentifier("task-greeting")
    }

    private func board(narrow: Bool, width: CGFloat) -> some View {
        let tasks = showPlansOnly ? [] : store.visibleBoardItems
        let plans = store.visiblePlans
        return VStack(alignment: .leading, spacing: 12) {
            ScrollView(.horizontal) {
                HStack(alignment: .top, spacing: 14) {
                    ForEach(UserTaskStatus.allCases) { status in
                        column(status, tasks: tasks, plans: plans)
                            .frame(width: narrow ? 240 : max(230, (width - 104) / 5))
                    }
                }
                .padding(.leading, narrow ? (compactProjectBoard ? 0 : 14) : .spacing2)
                .padding(.top, .spacing2)
                .padding(.trailing, narrow ? 14 : .spacing2)
            }
            .scrollIndicators(.hidden)
            .fixedSize(horizontal: false, vertical: compactProjectBoard)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("task-board")
            if tasks.isEmpty && plans.isEmpty {
                Text(store.searchText.isEmpty ? AppStrings.tasksEmpty : AppStrings.tasksNoMatches)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(16)
                    .background(Color.grey0, in: RoundedRectangle(cornerRadius: 20))
                    .accessibilityIdentifier(store.searchText.isEmpty ? "tasks-empty" : "tasks-filter-empty")
            }
        }
        .padding(.horizontal, narrow ? 0 : .spacing12)
        .accessibilityElement(children: .contain)
    }

    private func column(_ status: UserTaskStatus, tasks: [TaskBoardItem], plans: [UserPlanItem]) -> some View {
        let columnTasks = tasks.filter { $0.status == status }.sorted { $0.position < $1.position }
        let columnPlans = plans.filter { $0.status.boardColumn == status }.sorted { $0.updatedAt > $1.updatedAt }
        let count = columnTasks.count + columnPlans.count
        let visible = visibleCounts[status] ?? TaskBoardRenderWindow.initial
        return VStack(alignment: .leading, spacing: .spacing8) {
            HStack(spacing: .spacing3) {
                RoundedRectangle(cornerRadius: 2).fill(status.accent).frame(width: 4, height: 28)
                Text(status.localizedTitle).font(.omH3).fontWeight(.bold)
                Text("(\(count))").font(.omXxs).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("task-column-count-\(status.rawValue)")
            }
            .frame(height: 28)
            if showsDropInsertion(in: status) {
                Text(AppStrings.tasksDropToMark(status: status.localizedTitle))
                    .font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                    .multilineTextAlignment(.center)
                    .padding(.spacing4)
                    .frame(maxWidth: .infinity, minHeight: 88)
                    .background {
                        RoundedRectangle(cornerRadius: .radius8).fill(Color.grey0)
                            .overlay(RoundedRectangle(cornerRadius: .radius8).fill(status.accent.opacity(0.12)))
                    }
                    .overlay(RoundedRectangle(cornerRadius: .radius8)
                        .stroke(status.accent, style: StrokeStyle(lineWidth: 2, dash: [6, 4])))
                    .allowsHitTesting(false)
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("task-column-drop-target-\(status.rawValue)")
            }
            ForEach(Array(columnTasks.prefix(visible))) { item in
                taskCard(item)
            }
            ForEach(Array(columnPlans.prefix(max(0, visible - columnTasks.count)))) { plan in
                planCard(plan)
            }
            if count > visible {
                Button(AppStrings.tasksShowMore) { visibleCounts[status] = TaskBoardRenderWindow.expanded(visible) }
                    .font(.omSmall)
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("task-column-show-more-\(status.rawValue)")
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12).padding(.vertical, 16)
        .frame(minHeight: compactProjectBoard ? 280 : 410, alignment: .topLeading)
        .background(status == .blocked ? Color.grey25 : Color.clear,
                    in: RoundedRectangle(cornerRadius: .radius8))
        .accessibilityElement(children: .contain)
        .onDrop(of: [UTType.utf8PlainText], isTargeted: Binding(
            get: { targetedColumn == status },
            set: { NativeDragDiagnostics.record("task.targeted=\($0)"); if $0 { targetedColumn = status } else if targetedColumn == status { targetedColumn = nil } }
        )) { providers in acceptDrop(providers, to: status) }
        .animation(boardAnimation, value: columnTasks.map { "\($0.id):\($0.position)" })
        .animation(boardAnimation, value: targetedColumn)
        .accessibilityIdentifier("task-column-\(status.rawValue)")
    }

    private func showsDropInsertion(in status: UserTaskStatus) -> Bool {
        guard targetedColumn == status, !store.isSaving, let draggedTaskID,
              let item = store.boardItems.first(where: { $0.id == draggedTaskID }), case .task(let task) = item else { return false }
        return task.status != status
    }

    private func taskCard(_ item: TaskBoardItem) -> some View {
        let isDraggable: Bool = { if case .task = item { return true }; return false }()
        #if os(macOS)
        // A canceled SwiftUI drag can retain its session token. Actual pointer
        // release ends the hover suppression without retiring an awaiting drop.
        let pointerDragActive = draggedTaskID != nil && NSEvent.pressedMouseButtons != 0
        #else
        let pointerDragActive = draggedTaskID != nil
        #endif
        let hoverScale = TaskCardHoverPolicy.scale(isHovered: hoveredCardID == item.id,
            isDraggable: isDraggable, isDragging: pointerDragActive,
            isEnabled: workspaceIsEnabled && !promptActive && !store.isSaving)
        return VStack(alignment: .leading, spacing: .spacing2) {
            Button {
                guard cardActionsID != item.id else { return }
                switch item {
                case .task: store.openTask(item.id)
                case .workflowRun: store.openWorkflowRun(item.id)
                }
            } label: {
                Text(item.title).font(.omP).fontWeight(.bold)
                    .foregroundStyle(Color.grey100)
                    .lineLimit(3)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .simultaneousGesture(cardActivationGesture(onSelect: {
                cardActionsID = nil
                switch item {
                case .task: store.openTask(item.id)
                case .workflowRun: store.openWorkflowRun(item.id)
                }
            }, onActions: {
                if case .task = item { cardActionsID = item.id }
            }, allowsPointerDrag: true))
            .accessibilityIdentifier({
                if case .workflowRun = item { return "workflow-run-projection" }
                return "task-card-open"
            }())
            if case .task(let task) = item {
                HStack(spacing: 6) {
                    if let projectID = task.linkedProjectIds.first {
                        HStack(spacing: 4) {
                            Icon("project", size: 12)
                            Text(store.projectNames[projectID] ?? AppStrings.projects).lineLimit(1)
                        }
                            .font(.omXxs)
                            .padding(.horizontal, .spacing3).padding(.vertical, .spacing1)
                            .background(LinearGradient.primary, in: Capsule())
                            .foregroundStyle(.white)
                    }
                    if let dueAt = task.dueAt {
                        Text("\(AppStrings.tasksDue) \(Date(timeIntervalSince1970: TimeInterval(dueAt)).formatted(date: .abbreviated, time: .omitted))")
                            .font(.omXxs)
                            .foregroundStyle(Color.fontSecondary)
                            .padding(.horizontal, .spacing3).padding(.vertical, .spacing1)
                            .background(Color.grey10, in: Capsule())
                            .accessibilityIdentifier("task-card-due")
                    }
                    Spacer(minLength: 0)
                    if task.assigneeType == .openmates || task.assigneeType == .externalAI {
                        Icon("ai", size: 12).foregroundStyle(.white)
                            .frame(width: 20, height: 20)
                            .background(LinearGradient.primary, in: Circle())
                            .accessibilityIdentifier("task-assignment-ai")
                    } else if task.assigneeType == .user {
                        Icon("user", size: 12).foregroundStyle(.white)
                            .frame(width: 20, height: 20)
                            .background(LinearGradient.primary, in: Circle())
                            .accessibilityIdentifier("task-assignment-user")
                    }
                }
                if (task.assigneeType == .openmates || task.assigneeType == .externalAI), let chatID = task.primaryChatId {
                    Button(AppStrings.tasksOpenChat) { onOpenChat(chatID) }
                        .font(.omXs).buttonStyle(.plain)
                        .foregroundStyle(Color.buttonPrimary)
                }
            } else if case .workflowRun(let run) = item {
                Button {
                    onOpenWorkflowRun(run.workflowId, run.workflowRunId)
                } label: {
                    HStack(spacing: 4) {
                        Icon("workflow", size: 14)
                        Text(AppStrings.tasksOpenWorkflowRun)
                    }
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("workflow-run-open")
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: .radius5).fill(Color.grey0)
        }
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1))
        .shadow(color: .black.opacity(0.10), radius: 5, y: 2)
        .onHover { hovering in
            if hovering {
                #if os(macOS)
                // Read the current event state here, not the last body snapshot.
                // Pending drop tokens/generations remain owned by acceptDrop.
                hoveredCardID = NSEvent.pressedMouseButtons == 0 ? item.id : nil
                #else
                hoveredCardID = draggedTaskID == nil ? item.id : nil
                #endif
            } else if hoveredCardID == item.id {
                hoveredCardID = nil
            }
        }
        .overlay(alignment: .topTrailing) {
            if case .task(let task) = item {
                cardActions(task)
            }
        }
        .scaleEffect(hoverScale)
        .animation(boardAnimation, value: hoverScale)
        // Geometry and drop ownership remain in the original, unscaled slot.
        .background(GeometryReader { proxy in
            Color.clear.preference(key: TaskCardFramesKey.self,
                                   value: [item.id: proxy.frame(in: .named("tasks-workspace"))])
        })
        .contentShape(Rectangle())
        .modifier(TaskCardDragSource(task: {
            if case .task(let task) = item { return task }; return nil
        }(), onBegin: beginDrag))
        .accessibilityAction(named: Text(AppStrings.tasksMoreActions)) {
            if case .task = item { cardActionsID = item.id }
        }
        .zIndex(cardActionsID == item.id ? 9 : hoverScale > 1 ? 1 : 0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("task-card")
    }

    private func planCard(_ plan: UserPlanItem) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Button { if cardActionsID != plan.id { store.openPlan(plan.id) } } label: {
                Text(plan.title).font(.omP).fontWeight(.bold)
                    .foregroundStyle(Color.grey100)
                    .lineLimit(3).frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .highPriorityGesture(cardActivationGesture(
                onSelect: { cardActionsID = nil; store.openPlan(plan.id) },
                onActions: { cardActionsID = plan.id }))
            if let projectID = plan.linkedProjectIds.first {
                HStack(spacing: .spacing2) {
                    Icon("project", size: 12)
                    Text(store.projectNames[projectID] ?? AppStrings.projects)
                }
                    .font(.omXs)
                    .padding(.horizontal, .spacing3).padding(.vertical, .spacing1)
                    .background(LinearGradient.primary, in: Capsule())
                    .foregroundStyle(.white)
            }
            Button(AppStrings.tasksOpenPlan) { store.openPlan(plan.id) }
                .font(.omXs).buttonStyle(.plain).foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("task-board-open-plan")
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: .radius5).fill(Color.grey0)
            Color.clear.contentShape(RoundedRectangle(cornerRadius: .radius5))
                .highPriorityGesture(cardActivationGesture(
                    onSelect: { cardActionsID = nil; store.openPlan(plan.id) },
                    onActions: { cardActionsID = plan.id }))
                .accessibilityHidden(true)
        }
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1))
        .shadow(color: .black.opacity(0.10), radius: 5, y: 2)
        .onHover { hoveredCardID = $0 ? plan.id : nil }
        .overlay(alignment: .topTrailing) { planActions(plan) }
        .zIndex(cardActionsID == plan.id ? 9 : 0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("task-board-plan-card")
    }

    /// Task title taps retain the semantic Button action. Stationary holds
    /// open actions on release so the native card drag can own movement.
    private func cardActivationGesture(onSelect: @escaping () -> Void,
                                       onActions: @escaping () -> Void,
                                       allowsPointerDrag: Bool = false) -> AnyGesture<Void> {
        #if os(macOS)
        // Pointer dragging owns the whole card, including its title. Secondary
        // click opens actions through TaskSecondaryClickReader.
        if allowsPointerDrag { return AnyGesture(TapGesture().map { _ in () }) }
        #else
        if allowsPointerDrag && hoveredCardID != nil {
            // iPad trackpad/mouse uses the same full-card drag surface as Mac.
            // The visible More actions control retains menu access.
            return AnyGesture(TapGesture().map { _ in () })
        }
        #endif
        if allowsPointerDrag {
            // UIKit observes stationary release and native drag completion for
            // the whole card. The semantic title Button keeps normal taps.
            return AnyGesture(TapGesture().map { _ in () })
        }
        return AnyGesture(LongPressGesture(minimumDuration: 0.5)
            .exclusively(before: TapGesture())
            .onEnded { gesture in
                switch gesture {
                case .first(let completed): if completed { onActions() }
                case .second: onSelect()
                }
            }
            .map { _ in () })
    }

    @ViewBuilder private func cardActions(_ task: UserTaskItem) -> some View {
        if hoveredCardID == task.id {
            Button { cardActionsID = task.id } label: {
                Text("•••").font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .frame(width: 28, height: 24)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.tasksMoreActions)
            .accessibilityIdentifier("task-actions-more")
            .padding(.spacing2)
        }
    }

    @ViewBuilder private var taskActionsOverlay: some View {
        if let id = cardActionsID,
           let item = store.boardItems.first(where: { $0.id == id }), case .task(let task) = item {
            ZStack {
                Button { cardActionsID = nil } label: {
                    Color.black.opacity(0.28).ignoresSafeArea().contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.cancelAction)
                .accessibilityLabel(AppStrings.close)
                .accessibilityIdentifier("task-actions-dismiss")
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(task.title).font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary).lineLimit(1)
                        .padding(.horizontal, .spacing4).padding(.top, .spacing3)
                    taskActionRow("task", AppStrings.tasksOpenTask, id: "task-detail-link") { store.openTask(task.id) }
                    if task.assigneeType != .openmates && task.assigneeType != .externalAI {
                        taskActionRow("ai", AppStrings.tasksAssignAI, id: "task-start-ai") {
                            Task { await store.saveTask(task, patch: UserTaskUpdateInput(assigneeType: .openmates)) }
                        }
                    }
                    ForEach(UserTaskStatus.allCases.filter { $0 != task.status && $0 != .blocked }) { status in
                        taskActionRow("task", status.localizedTitle, id: "task-move-\(status.rawValue)") {
                            Task { await store.moveTask(task, to: status) }
                        }
                    }
                    taskActionRow("task", task.status == .blocked ? AppStrings.tasksUnblock : AppStrings.tasksBlock,
                                  id: "task-action-block") {
                        Task { await store.moveTask(task, to: task.status == .blocked ? .todo : .blocked) }
                    }
                    if task.status != .backlog {
                        taskActionRow("task", AppStrings.tasksSkip, id: "task-action-skip") {
                            Task { await store.moveTask(task, to: .backlog) }
                        }
                    }
                    taskActionRow("delete", AppStrings.delete, id: "task-action-delete", destructive: true) { pendingDelete = task }
                }
                .padding(.vertical, .spacing2).frame(width: 280)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius7))
                .overlay(RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey20, lineWidth: 1))
                .shadow(color: .black.opacity(0.18), radius: 18, x: 0, y: 10)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("task-action-menu-items")
            }
        }
    }

    private func taskActionRow(_ icon: String, _ title: String, id: String,
                               destructive: Bool = false, action: @escaping () -> Void) -> some View {
        Button { cardActionsID = nil; action() } label: {
            HStack(spacing: .spacing3) {
                Icon(icon, size: 17).foregroundStyle(destructive ? Color.error : Color.fontSecondary)
                Text(title).font(.omSmall.weight(.medium))
                    .foregroundStyle(destructive ? Color.error : Color.fontPrimary)
                Spacer()
            }
            .padding(.horizontal, .spacing4).padding(.vertical, .spacing3)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(store.isSaving)
        .accessibilityIdentifier(id)
    }

    private func diagnosticCardID(at point: CGPoint) -> String? {
        let match = cardFrames.first(where: { $0.value.contains(point) })
        if let frame = match?.value {
            NativeDragDiagnostics.record("task.frame=\(Int(frame.minX)),\(Int(frame.minY)),\(Int(frame.width)),\(Int(frame.height))")
        } else { NativeDragDiagnostics.record("task.frame.none;count=\(cardFrames.count)") }
        return match?.key
    }

    private func beginDrag(_ task: UserTaskItem) -> NSItemProvider {
        NativeDragDiagnostics.record("task.beginDrag")
        cardActionsID = nil
        hoveredCardID = nil
        draggedTaskID = task.id
        let token = UUID().uuidString
        dragToken = token
        dragGeneration = store.interactionGeneration
        return NSItemProvider(object: token as NSString)
    }

    private func acceptDrop(_ providers: [NSItemProvider], to status: UserTaskStatus) -> Bool {
        NativeDragDiagnostics.record("task.drop.invoked;providers=\(providers.count)")
        guard !store.isSaving, dragGeneration == store.interactionGeneration,
              let id = draggedTaskID, let token = dragToken,
              let item = store.boardItems.first(where: { $0.id == id }),
              case .task(let task) = item, task.status != status,
              let provider = providers.first(where: { $0.hasItemConformingToTypeIdentifier(UTType.utf8PlainText.identifier) })
        else { NativeDragDiagnostics.record("task.drop.guardRejected"); return false }
        NativeDragDiagnostics.record("task.drop.accepted")
        provider.loadDataRepresentation(forTypeIdentifier: UTType.utf8PlainText.identifier) { data, _ in
            guard let data, String(data: data, encoding: .utf8) == token else { return }
            Task { @MainActor in NativeDragDiagnostics.record("task.drop.tokenDecoded") }
            Task { @MainActor in
                guard dragToken == token, draggedTaskID == id,
                      dragGeneration == store.interactionGeneration else { return }
                dragToken = nil; draggedTaskID = nil; targetedColumn = nil; hoveredCardID = nil
                withAnimation(boardAnimation) { cardActionsID = nil }
                await store.moveTask(task, to: status)
            }
        }
        return true
    }

    @ViewBuilder private func planActions(_ plan: UserPlanItem) -> some View {
        if hoveredCardID == plan.id || cardActionsID == plan.id {
            VStack(alignment: .trailing, spacing: .spacing2) {
                Button { cardActionsID = cardActionsID == plan.id ? nil : plan.id } label: {
                    Text("•••").font(.omXxs).foregroundStyle(Color.fontSecondary)
                        .frame(width: 28, height: 24)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.tasksMoreActions)
                .accessibilityIdentifier("plan-actions-more")
                if cardActionsID == plan.id {
                    VStack(spacing: .spacing2) {
                        ForEach(UserTaskStatus.allCases) { status in
                            Button(status.localizedTitle) {
                                cardActionsID = nil
                                Task { await store.movePlan(plan, to: status) }
                            }
                        }
                    }
                    .buttonStyle(TasksCardActionStyle())
                    .padding(.spacing4)
                    .frame(width: 136)
                    .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
                    .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1))
                    .shadow(color: .black.opacity(0.2), radius: 8, y: 4)
                }
            }
            .padding(.spacing2)
        }
    }

    private var composer: some View {
        TaskWorkspacePromptComposer(store: store, compactProjectBoard: compactProjectBoard,
            focusRequestID: composerFocusRequestID, onSubmit: submitPrompt,
            onActiveChanged: { promptActive = $0 }, dismissRequestID: promptDismissID,
            availableHeight: promptAvailableHeight)
    }

    private func submitPrompt(_ value: String) {
        let title = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return }
        if showPlansOnly {
            store.promptDraft = ""
            newTaskTitle = title
            showingNewTask = true
        } else {
            Task {
                if await store.createTask(UserTaskCreateInput(title: title)), store.promptDraft.trimmingCharacters(in: .whitespacesAndNewlines) == title {
                    store.promptDraft = ""
                }
            }
        }
    }

    private var newTaskSheet: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            TextField(showPlansOnly ? AppStrings.tasksNewPlan : AppStrings.tasksNew, text: $newTaskTitle)
                .textFieldStyle(OMTextFieldStyle())
                .accessibilityIdentifier("task-create-title")
            if showPlansOnly {
                TextField(AppStrings.tasksPlanGoal, text: $newPlanGoal)
                    .textFieldStyle(OMTextFieldStyle())
                OMDropdown(title: AppStrings.tasksPlanRequiresProject,
                           options: store.projectNames.keys.sorted().map {
                               OMDropdownOption($0, label: store.projectNames[$0] ?? AppStrings.projects)
                           }, selection: $newPlanProjectID)
            }
            HStack {
                Button(AppStrings.cancel) { showingNewTask = false }
                    .buttonStyle(OMSecondaryButtonStyle())
                Button(AppStrings.tasksAdd) {
                    let title = newTaskTitle.trimmingCharacters(in: .whitespacesAndNewlines)
                    showingNewTask = false
                    newTaskTitle = ""
                    if showPlansOnly {
                        let goal = newPlanGoal
                        let projectID = newPlanProjectID
                        newPlanGoal = ""
                        newPlanProjectID = ""
                        Task { await store.createPlan(title: title, goal: goal, projectIDs: [projectID]) }
                    } else {
                        Task { await store.createTask(UserTaskCreateInput(title: title)) }
                    }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(newTaskTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                          || (showPlansOnly && newPlanProjectID.isEmpty))
            }
        }
    }

}

/// The shell may already have adopted SwiftUI's keyboard safe area. Only
/// subtract the part still covering this pane; floating keyboards retain the
/// full workspace and mobile inspiration stays at the web's fixed 190 points.
enum TasksWorkspaceLayoutPolicy {
    static func keyboardOverlap(container: CGRect, keyboard: CGRect?) -> CGFloat {
        guard !container.isEmpty, let keyboard, !keyboard.isEmpty,
              keyboard.maxY >= container.maxY,
              container.intersection(keyboard).width > 0 else { return 0 }
        return min(container.height, max(0, container.maxY - keyboard.minY))
    }

    static func bannerHeight(width: CGFloat, height: CGFloat) -> CGFloat {
        width < 730 ? 190 : max(240, height * 0.35)
    }
}

// TaskCard.svelte .task-action-menu-items: 41px rendered button height,
// 12px text, 6px horizontal padding, pill-shaped grey10 background.
private struct TasksCardActionStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omXxs)
            .frame(maxWidth: .infinity, minHeight: 41)
            .padding(.horizontal, .spacing3)
            .background(Color.grey10, in: Capsule())
            .opacity(configuration.isPressed ? 0.8 : 1)
    }
}

private enum TasksDetailSelection: Identifiable {
    case task(String), plan(String), workflowRun(String)
    var id: String {
        switch self {
        case .task(let id): "task-\(id)"
        case .plan(let id): "plan-\(id)"
        case .workflowRun(let id): "workflow-run-\(id)"
        }
    }
}

/// Project Tasks mounts this same editor in its viewport bottom lane while its
/// outer page owns vertical scrolling of the compact board.
struct TaskWorkspacePromptComposer: View {
    @ObservedObject var store: TasksWorkspaceStore
    var compactProjectBoard = false
    var focusRequestID: UUID? = nil
    var onSubmit: ((String) -> Void)? = nil
    var onActiveChanged: (Bool) -> Void = { _ in }
    var dismissRequestID: UUID? = nil
    var availableHeight: CGFloat = 350

    var body: some View {
        WorkspacePromptComposerView(text: $store.promptDraft,
            placeholder: compactProjectBoard ? AppStrings.tasksPromptCompact : AppStrings.tasksPrompt,
            submitLabel: AppStrings.tasksSend, submittingLabel: AppStrings.tasksSaving,
            disabled: store.isSaving, submitting: store.isSaving,
            identifier: compactProjectBoard ? "project-task-workspace-composer" : "task-workspace-composer",
            inputIdentifier: compactProjectBoard ? "project-task-workspace-input" : "task-workspace-input",
            submitIdentifier: compactProjectBoard ? "project-task-workspace-submit" : "task-workspace-submit",
            micIdentifier: compactProjectBoard ? "project-task-workspace-mic" : "task-workspace-mic",
            onSubmit: { value in
                if let onSubmit { onSubmit(value); return }
                let title = value.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !title.isEmpty else { return }
                Task {
                    if await store.createTask(UserTaskCreateInput(title: title)), store.promptDraft.trimmingCharacters(in: .whitespacesAndNewlines) == title {
                        store.promptDraft = ""
                    }
                }
            },
            onMic: { ToastManager.shared.show(AppStrings.tasksMicUnavailable, type: .error) },
            focusRequestID: focusRequestID, onActiveChanged: onActiveChanged,
            dismissRequestID: dismissRequestID, availableHeight: availableHeight)
            .padding(.horizontal, compactProjectBoard ? 0 : 32).padding(.bottom, 12)
    }
}

private struct TasksDetailPresentation: ViewModifier {
    @Binding var selection: TasksDetailSelection?
    @ObservedObject var store: TasksWorkspaceStore
    let allowsSplit: Bool
    let isEnabled: Bool
    let onOpenProject: (String) -> Void
    let onOpenChat: (String) -> Void
    let onReportIssue: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @ViewBuilder func body(content: Content) -> some View {
        if !isEnabled {
            content
        } else {
            GeometryReader { geometry in
                let split = allowsSplit && geometry.size.width >= 1100
                    && (store.selectedTaskID != nil || store.selectedWorkflowRunID != nil)
                if split, let selection {
                    HStack(spacing: .spacing5) {
                        content.frame(width: max(340, geometry.size.width * 0.32))
                        reader(selection)
                            .transition(reduceMotion ? .opacity : .move(edge: .bottom))
                    }
                    .animation(reduceMotion ? nil : .easeInOut(duration: 0.3), value: selection.id)
                    .accessibilityIdentifier("tasks-workspace-split")
                } else {
                    content.overlay {
                        if let selection {
                            reader(selection).zIndex(10)
                                .transition(reduceMotion ? .opacity : .move(edge: .bottom))
                        }
                    }
                    .animation(reduceMotion ? nil : .easeInOut(duration: 0.3), value: selection?.id)
                }
            }
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.3), value: selection?.id)
        }
    }

    private func reader(_ selection: TasksDetailSelection) -> some View {
        TasksWorkspaceDetailView(store: store, onOpenProject: onOpenProject,
            onOpenChat: onOpenChat, onReportIssue: onReportIssue)
    }
}

/// Shared reader: Projects presents this beside its complete page while its
/// embedded Tasks board keeps the same selection and mutation store.
// Web source: frontend/packages/ui/src/components/tasks/TaskDetailFullscreen.svelte
// Specification: specifications/features/tasks/specification.yml
// Assertions: tasks.detail.embed-responsive
struct TasksWorkspaceDetailView: View {
    @ObservedObject var store: TasksWorkspaceStore
    var onOpenProject: (String) -> Void = { _ in }
    var onOpenChat: (String) -> Void = { _ in }
    var onReportIssue: () -> Void = {}

    var body: some View {
        Group {
            if let task = store.selectedTask {
                TaskDetailView(store: store, task: task,
                    onOpenProject: onOpenProject, onOpenChat: onOpenChat,
                    onReportIssue: onReportIssue)
                    .id(task.id)
                    .onAppear { store.taskDetailDidAppear(task.id) }
            } else if let plan = store.selectedPlan {
                PlanDetailView(store: store, plan: plan,
                    onOpenProject: onOpenProject, onOpenChat: onOpenChat,
                    onReportIssue: onReportIssue)
            } else if let projection = store.selectedWorkflowRun {
                WorkflowRunTaskDetailView(store: store, projection: projection)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey20)
        // UnifiedEmbedFullscreen's rendered outer radius is 17px.
        .clipShape(RoundedRectangle(cornerRadius: 17))
    }
}

/// Read-only exact-run detail used by Workflow projections on the Tasks board.
/// Its task is cancelled when the reader closes, and every fetch is account/server fenced.
private struct WorkflowRunTaskDetailView: View {
    @ObservedObject var store: TasksWorkspaceStore
    let projection: WorkflowRunTaskProjection

    @State private var run: WorkflowRunDetail?
    @State private var graph: WorkflowGraph?
    @State private var errorMessage: String?

    private var displayedStatus: String { run?.status ?? projection.runStatus }
    private var isTerminal: Bool {
        ["completed", "failed", "cancelled"].contains(displayedStatus)
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                OMIconButton(icon: "back", label: AppStrings.tasks) { store.closeDetail() }
                    .accessibilityIdentifier("workflow-run-detail-close")
                Text(projection.displayTitle).font(.omH3).lineLimit(2)
                Spacer()
            }
            .padding(.spacing8)
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(AppStrings.workflowRun(.run))
                            .font(.omXs).fontWeight(.bold)
                            .foregroundStyle(Color.fontSecondary)
                        Text(Date(timeIntervalSince1970: TimeInterval(run?.startedAt ?? projection.scheduledAt ?? projection.createdAt))
                            .formatted(.dateTime.month(.abbreviated).day().hour().minute()))
                            .font(.omP)
                            .accessibilityIdentifier("workflow-run-detail-started-at")
                        Text(statusTitle(displayedStatus))
                            .font(.omP.weight(.semibold))
                            .foregroundStyle(displayedStatus == "completed" ? Color.chatRainbowGreen :
                                             displayedStatus == "failed" ? Color.error : Color.fontPrimary)
                            .accessibilityIdentifier("workflow-run-detail-live-status")
                    }
                    .padding(20)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: 8))
                    if let errorMessage {
                        Text(errorMessage).foregroundStyle(Color.error)
                            .accessibilityIdentifier("workflow-run-detail-load-error")
                    } else if run == nil {
                        ProgressView(AppStrings.loading)
                    }
                    if let run {
                        if !run.contentAvailable {
                            Text(AppStrings.workflowRun(.content_unavailable))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                                .accessibilityIdentifier("workflow-run-content-unavailable")
                        }
                        VStack(alignment: .leading, spacing: 12) {
                            Text(AppStrings.tasksWorkflowNodeStatus).font(.omH3).fontWeight(.bold)
                            ForEach(run.nodeRuns) { node in
                                HStack {
                                    Text(nodeTitle(node)).lineLimit(2)
                                    Spacer()
                                    Text(statusTitle(node.status))
                                        .fontWeight(.semibold)
                                }
                                .font(.omP)
                                .padding(12)
                                .background(Color.grey10, in: RoundedRectangle(cornerRadius: 6))
                                .accessibilityIdentifier("workflow-run-detail-node-status")
                            }
                        }
                        if let graph {
                            WorkflowGraphView(graph: graph, readOnly: true, nodeRuns: run.nodeRuns)
                                .accessibilityIdentifier("workflow-run-task-graph")
                        }
                    }
                }
                .padding(24)
            }
            .background(Color.grey0)
            .task(id: "\(projection.id):\(projection.workflowRunId ?? "")") { await loadExactRun() }
            .accessibilityIdentifier("workflow-run-projection-detail")
        }
    }

    private func nodeTitle(_ run: WorkflowNodeRun) -> String {
        graph?.nodes.first(where: { $0.id == run.nodeId })?.title ?? AppStrings.tasksWorkflowNodeStatus
    }

    private func statusTitle(_ status: String) -> String {
        let key: AppStrings.WorkflowRunCopy
        switch status {
        case "completed": key = .status_completed
        case "failed": key = .status_failed
        case "cancelled": key = .status_cancelled
        case "skipped", "skipped_by_user": key = .status_skipped
        case "queued": key = .status_queued
        case "running": key = .status_running
        case "waiting": key = .status_waiting
        case "cancellation_requested": key = .status_cancellation_requested
        default: key = .status_unavailable
        }
        return AppStrings.workflowRun(key)
    }

    private func loadExactRun() async {
        run = nil
        graph = nil
        errorMessage = nil
        guard projection.workflowRunId != nil else {
            errorMessage = AppStrings.localized("workflows.runs.load_failed")
            return
        }
        for _ in 0..<90 {
            guard !Task.isCancelled, store.selectedWorkflowRunID == projection.id else { return }
            do {
                let (fetchedRun, fetchedGraph) = try await store.workflowRunDetail(
                    projection, currentGraph: graph)
                guard !Task.isCancelled, store.selectedWorkflowRunID == projection.id else { return }
                run = fetchedRun
                graph = fetchedGraph
                errorMessage = nil
                if isTerminal { return }
                try await Task.sleep(for: .seconds(1))
            } catch is CancellationError {
                return
            } catch {
                guard !Task.isCancelled, store.selectedWorkflowRunID == projection.id else { return }
                errorMessage = WorkflowRunTaskReader.loadErrorMessage(error)
                return
            }
        }
    }
}

extension UserTaskStatus {
    @MainActor var localizedTitle: String {
        switch self {
        case .backlog: AppStrings.tasksBacklog
        case .todo: AppStrings.tasksTodo
        case .inProgress: AppStrings.tasksInProgress
        case .blocked: AppStrings.tasksBlocked
        case .done: AppStrings.tasksDone
        }
    }

    var accent: Color {
        switch self {
        case .backlog: .chatRainbowPurple
        case .todo: .chatRainbowCyan
        case .inProgress: .warning
        case .blocked: .error
        case .done: .chatRainbowGreen
        }
    }
}

/// A compact status and recent-item rail for the app shell on wider screens.
struct TasksSidebarView: View {
    @ObservedObject var store: TasksWorkspaceStore
    var onClose: () -> Void = {}
    @State private var showsSearch = false
    var onOpenTask: (String) -> Void = { _ in }
    var onOpenPlan: (String) -> Void = { _ in }

    var body: some View {
        let items = store.visibleBoardItems
        let plans = store.visiblePlans
        VStack(spacing: 0) {
            WorkspaceSidebarHeader(onSearch: { showsSearch.toggle(); if !showsSearch { store.searchText = "" } },
                onClose: onClose, searchIdentifier: "tasks-sidebar-search",
                closeIdentifier: "tasks-sidebar-close", topBarIdentifier: "tasks-sidebar-topbar")
            if showsSearch {
                WorkspaceSidebarSearchField(query: $store.searchText, identifier: "tasks-sidebar-search-input")
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(AppStrings.tasks).font(.omH2).fontWeight(.bold)
                    ForEach(UserTaskStatus.allCases) { status in
                        HStack(spacing: 8) {
                            Circle().fill(status.accent).frame(width: 8, height: 8)
                            Text(status.localizedTitle).font(.omP)
                            Spacer()
                            let count = items.filter { $0.status == status }.count
                                + plans.filter { $0.status.boardColumn == status }.count
                            Text("\(count)").font(.omXs).foregroundStyle(Color.fontSecondary)
                        }
                        .padding(.vertical, 5)
                    }
                    Divider()
                    if !store.searchText.isEmpty && items.isEmpty && plans.isEmpty {
                        Text(AppStrings.tasksNoMatches).font(.omSmall).foregroundStyle(Color.fontSecondary)
                            .accessibilityIdentifier("tasks-sidebar-no-matches")
                    }
                    ForEach(items.prefix(8)) { item in
                        Button(item.title) {
                            switch item {
                            case .task: onOpenTask(item.id)
                            case .workflowRun: store.openWorkflowRun(item.id)
                            }
                        }
                            .font(.omSmall).lineLimit(2).buttonStyle(.plain)
                            .accessibilityIdentifier("task-sidebar-row-\(item.id)")
                    }
                    ForEach(plans.prefix(4)) { plan in
                        Button(plan.title) { onOpenPlan(plan.id) }
                            .font(.omSmall).lineLimit(2).buttonStyle(.plain)
                            .accessibilityIdentifier("plan-sidebar-row-\(plan.id)")
                    }
                }
                .padding(16)
            }
        }
        .background(Color.grey20)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("tasks-sidebar")
    }
}
