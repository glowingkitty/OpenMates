import SwiftUI

/// The central Tasks surface follows TasksPage.svelte and TaskBoard.svelte. The
/// shell retains `store`; this view does not own account or team state.
// Web source: frontend/packages/ui/src/components/tasks/TasksPage.svelte
//             frontend/packages/ui/src/components/tasks/TaskBoard.svelte
//             frontend/packages/ui/src/components/workspace/WorkspaceHomeShell.svelte
// Specification: specifications/features/tasks/specification.yml
// Assertions: tasks.lifecycle.visible, tasks.detail.embed-responsive, tasks.surface.semantic-parity
struct TasksWorkspaceView: View {
    @ObservedObject var store: TasksWorkspaceStore
    var showPlansOnly = false
    var compactProjectBoard = false
    var inspiration: DailyInspirationData? = nil
    var onStartInspiration: (String) -> Void = { _ in }
    var onOpenProject: (String) -> Void = { _ in }
    var onOpenChat: (String) -> Void = { _ in }
    var onOpenWorkflowRun: (String, String?) -> Void = { _, _ in }
    var onReportIssue: () -> Void = {}

    @State private var searchExpanded = false
    @State private var filtersExpanded = false
    @State private var desktopFiltersExpanded = true
    @State private var prompt = ""
    @State private var showingNewTask = false
    @State private var newTaskTitle = ""
    @State private var newPlanGoal = ""
    @State private var newPlanProjectID = ""
    @State private var visibleCounts: [UserTaskStatus: Int] = [:]
    @State private var pendingDelete: UserTaskItem?
    @State private var inspirationIndex = 0
    @State private var cardActionsID: String?
    @State private var hoveredCardID: String?

    var body: some View {
        GeometryReader { geometry in
            // TasksPage.svelte measures the remaining workspace width after
            // opening its 32% board / reader split, rather than window width.
            let split = !compactProjectBoard && geometry.size.width >= 1100
                && (store.selectedTaskID != nil || store.selectedWorkflowRunID != nil)
            let workspaceWidth = split ? max(340, geometry.size.width * 0.32) : geometry.size.width
            let narrow = workspaceWidth <= 900
            ZStack(alignment: .bottom) {
                ScrollView(.vertical) {
                    VStack(spacing: 0) {
                        if compactProjectBoard {
                            compactProjectToolbar
                        } else {
                            banner(width: workspaceWidth, height: geometry.size.height)
                            toolbar(narrow: narrow)
                            greeting
                        }
                        if store.isLoading {
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
                            board(narrow: narrow, width: workspaceWidth)
                        }
                    }
                    .padding(.bottom, 120)
                }
                composer
            }
            .background(Color.grey20.ignoresSafeArea())
            .overlay { OMSheet(isPresented: $showingNewTask, title: showPlansOnly ? AppStrings.tasksNewPlan : AppStrings.tasksNew) { newTaskSheet } }
            .modifier(TasksDetailPresentation(selection: selectedDetailBinding,
                store: store, allowsSplit: !compactProjectBoard,
                onOpenProject: onOpenProject, onOpenChat: onOpenChat,
                onReportIssue: onReportIssue))
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
                                heightOverride: width < 730 ? 190 : max(240, height * 0.35),
                                ctaTitle: showPlansOnly ? AppStrings.plansInspirationCTA : AppStrings.tasksInspirationCTA,
                                tapHint: showPlansOnly ? AppStrings.plansInspirationCTA : AppStrings.tasksInspirationCTA) {
                    prompt = value.text
                    newTaskTitle = value.text
                    onStartInspiration(value.text)
                }
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
        let visible = visibleCounts[status] ?? 30
        return VStack(alignment: .leading, spacing: .spacing8) {
            HStack(spacing: .spacing3) {
                RoundedRectangle(cornerRadius: 2).fill(status.accent).frame(width: 4, height: 28)
                Text(status.localizedTitle).font(.omH3).fontWeight(.bold)
                Text("(\(count))").font(.omXxs).foregroundStyle(Color.fontSecondary)
            }
            .frame(height: 28)
            ForEach(Array(columnTasks.prefix(visible))) { item in
                taskCard(item)
            }
            ForEach(Array(columnPlans.prefix(max(0, visible - columnTasks.count)))) { plan in
                planCard(plan)
            }
            if count > visible {
                Button(AppStrings.tasksShowMore) { visibleCounts[status] = visible + 20 }
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
        .accessibilityIdentifier("task-column-\(status.rawValue)")
    }

    private func taskCard(_ item: TaskBoardItem) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
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
            .highPriorityGesture(cardActivationGesture(onSelect: {
                cardActionsID = nil
                switch item {
                case .task: store.openTask(item.id)
                case .workflowRun: store.openWorkflowRun(item.id)
                }
            }, onActions: {
                if case .task = item { cardActionsID = item.id }
            }))
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
            Color.clear.contentShape(RoundedRectangle(cornerRadius: .radius5))
                .highPriorityGesture(cardActivationGesture(onSelect: {
                    cardActionsID = nil
                    switch item {
                    case .task: store.openTask(item.id)
                    case .workflowRun: store.openWorkflowRun(item.id)
                    }
                }, onActions: {
                    if case .task = item { cardActionsID = item.id }
                }))
                .accessibilityHidden(true)
        }
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1))
        .shadow(color: .black.opacity(0.10), radius: 5, y: 2)
        .onHover { hoveredCardID = $0 ? item.id : nil }
        .overlay(alignment: .topTrailing) {
            if case .task(let task) = item {
                cardActions(task)
            }
        }
        .zIndex(cardActionsID == item.id ? 9 : 0)
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

    /// One exclusive recognizer owns touch activation. The semantic Button
    /// action remains available for accessibility activation; long press never
    /// reaches the tap branch or the underlying Button's touch handler.
    private func cardActivationGesture(onSelect: @escaping () -> Void,
                                       onActions: @escaping () -> Void) -> some Gesture {
        LongPressGesture(minimumDuration: 0.5)
            .exclusively(before: TapGesture())
            .onEnded { gesture in
                switch gesture {
                case .first(let completed): if completed { onActions() }
                case .second: onSelect()
                }
            }
    }

    @ViewBuilder private func cardActions(_ task: UserTaskItem) -> some View {
        if hoveredCardID == task.id || cardActionsID == task.id {
            VStack(alignment: .trailing, spacing: .spacing2) {
                Button { cardActionsID = cardActionsID == task.id ? nil : task.id } label: {
                    Text("•••").font(.omXxs).foregroundStyle(Color.fontSecondary)
                        .frame(width: 28, height: 24)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.tasksMoreActions)
                .accessibilityIdentifier("task-actions-more")
                if cardActionsID == task.id {
                    VStack(spacing: .spacing2) {
                        Button(AppStrings.tasksOpenTask) { cardActionsID = nil; store.openTask(task.id) }
                            .accessibilityIdentifier("task-detail-link")
                        if task.assigneeType != .openmates && task.assigneeType != .externalAI {
                            Button(AppStrings.tasksAssignAI) {
                                cardActionsID = nil
                                Task { await store.saveTask(task, patch: UserTaskUpdateInput(assigneeType: .openmates)) }
                            }
                            .accessibilityIdentifier("task-start-ai")
                        }
                        ForEach(UserTaskStatus.allCases.filter { $0 != task.status && $0 != .blocked }) { status in
                            Button(status.localizedTitle) {
                                cardActionsID = nil
                                Task { await store.moveTask(task, to: status) }
                            }
                            .accessibilityIdentifier("task-move-\(status.rawValue)")
                        }
                        Button(task.status == .blocked ? AppStrings.tasksUnblock : AppStrings.tasksBlock) {
                            cardActionsID = nil
                            Task { await store.taskAction(task.status == .blocked ? "unblock" : "block", task: task) }
                        }
                        if task.status != .backlog {
                            Button(AppStrings.tasksSkip) { cardActionsID = nil; Task { await store.taskAction("skip", task: task) } }
                        }
                        Button(AppStrings.delete) { cardActionsID = nil; pendingDelete = task }
                            .foregroundStyle(Color.error)
                    }
                    .font(.omXxs)
                    .buttonStyle(TasksCardActionStyle())
                    .padding(.spacing4)
                    .frame(width: 136)
                    .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
                    .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1))
                    .shadow(color: .black.opacity(0.2), radius: 8, y: 4)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("task-action-menu-items")
                }
            }
            .padding(.spacing2)
        }
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
        WorkspacePromptComposerView(
            text: $prompt,
            placeholder: compactProjectBoard ? AppStrings.tasksPromptCompact : AppStrings.tasksPrompt,
            submitLabel: AppStrings.tasksSend,
            submittingLabel: AppStrings.tasksSaving,
            disabled: store.isSaving,
            submitting: store.isSaving,
            identifier: compactProjectBoard ? "project-task-workspace-composer" : "task-workspace-composer",
            inputIdentifier: compactProjectBoard ? "project-task-workspace-input" : "task-workspace-input",
            submitIdentifier: compactProjectBoard ? "project-task-workspace-submit" : "task-workspace-submit",
            micIdentifier: compactProjectBoard ? "project-task-workspace-mic" : "task-workspace-mic",
            onSubmit: submitPrompt,
            onMic: { ToastManager.shared.show(AppStrings.tasksMicUnavailable, type: .error) }
        )
        .padding(.horizontal, compactProjectBoard ? 0 : 32).padding(.bottom, 12)
    }

    private func submitPrompt(_ value: String) {
        let title = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return }
        prompt = ""
        if showPlansOnly {
            newTaskTitle = title
            showingNewTask = true
        } else {
            Task { await store.createTask(UserTaskCreateInput(title: title)) }
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

private struct TasksDetailPresentation: ViewModifier {
    @Binding var selection: TasksDetailSelection?
    @ObservedObject var store: TasksWorkspaceStore
    let allowsSplit: Bool
    let onOpenProject: (String) -> Void
    let onOpenChat: (String) -> Void
    let onReportIssue: () -> Void

    func body(content: Content) -> some View {
        GeometryReader { geometry in
            let split = allowsSplit && geometry.size.width >= 1100
                && (store.selectedTaskID != nil || store.selectedWorkflowRunID != nil)
            if split, let selection {
                HStack(spacing: .spacing5) {
                    content.frame(width: max(340, geometry.size.width * 0.32))
                    reader(selection)
                }
                .accessibilityIdentifier("tasks-workspace-split")
            } else {
                content.overlay {
                    if let selection { reader(selection).zIndex(10) }
                }
            }
        }
    }

    private func reader(_ selection: TasksDetailSelection) -> some View {
        detail(selection)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.grey20)
            // UnifiedEmbedFullscreen's rendered outer radius is 17px.
            .clipShape(RoundedRectangle(cornerRadius: 17))
    }

    @ViewBuilder private func detail(_ selection: TasksDetailSelection) -> some View {
        switch selection {
        case .task(let id):
            if let task = store.boardItems.compactMap({ item -> UserTaskItem? in
                if case .task(let task) = item, task.id == id { return task }
                return nil
            }).first {
                TaskDetailView(store: store, task: task,
                               onOpenProject: onOpenProject, onOpenChat: onOpenChat,
                               onReportIssue: onReportIssue)
            }
        case .plan(let id):
            if let plan = store.plans.first(where: { $0.id == id }) {
                PlanDetailView(store: store, plan: plan,
                               onOpenProject: onOpenProject, onOpenChat: onOpenChat,
                               onReportIssue: onReportIssue)
            }
        case .workflowRun(let id):
            if let projection = store.boardItems.compactMap({ item -> WorkflowRunTaskProjection? in
                if case .workflowRun(let run) = item, run.id == id { return run }
                return nil
            }).first {
                WorkflowRunTaskDetailView(store: store, projection: projection)
            }
        }
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
                Text(projection.displayTitle).font(.omH3).lineLimit(2)
                Spacer()
            }
            .padding(.spacing8)
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(AppStrings.tasksWorkflowRunID)
                            .font(.omXs).fontWeight(.bold)
                            .foregroundStyle(Color.fontSecondary)
                        Text(projection.workflowRunId ?? AppStrings.tasksNoWorkflowRunID)
                            .font(.omSmall.monospaced())
                            .textSelection(.enabled)
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.grey20, in: RoundedRectangle(cornerRadius: 6))
                            .accessibilityIdentifier("workflow-run-detail-id")
                        Text(displayedStatus.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.omP.weight(.semibold))
                            .foregroundStyle(displayedStatus == "completed" ? Color.chatRainbowGreen :
                                             displayedStatus == "failed" ? Color.error : Color.fontPrimary)
                            .accessibilityIdentifier("workflow-run-detail-live-status")
                    }
                    .padding(20)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: 8))
                    if let errorMessage {
                        Text(errorMessage).foregroundStyle(Color.error)
                    } else if run == nil && !store.usesPreviewData {
                        ProgressView(AppStrings.loading)
                    }
                    if let run {
                        VStack(alignment: .leading, spacing: 12) {
                            Text(AppStrings.tasksWorkflowNodeStatus).font(.omH3).fontWeight(.bold)
                            ForEach(run.nodeRuns) { node in
                                HStack {
                                    Text(node.nodeId).lineLimit(2)
                                    Spacer()
                                    Text(node.status.replacingOccurrences(of: "_", with: " ").capitalized)
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
            .task(id: projection.id) { await loadExactRun() }
            .accessibilityIdentifier("workflow-run-projection-detail")
        }
    }

    private func loadExactRun() async {
        guard !store.usesPreviewData else { return }
        guard projection.workflowRunId != nil else {
            errorMessage = AppStrings.tasksNoWorkflowRunID
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
                guard !Task.isCancelled else { return }
                errorMessage = error.localizedDescription
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
    var onOpenTask: (String) -> Void = { _ in }
    var onOpenPlan: (String) -> Void = { _ in }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text(AppStrings.tasks).font(.omH2).fontWeight(.bold)
                ForEach(UserTaskStatus.allCases) { status in
                    HStack(spacing: 8) {
                        Circle().fill(status.accent).frame(width: 8, height: 8)
                        Text(status.localizedTitle).font(.omP)
                        Spacer()
                        let count = store.boardItems.filter { $0.status == status }.count
                            + store.plans.filter { $0.status.boardColumn == status }.count
                        Text("\(count)").font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    .padding(.vertical, 5)
                }
                Divider()
                ForEach(store.boardItems.prefix(8)) { item in
                    Button(item.title) {
                        switch item {
                        case .task: onOpenTask(item.id)
                        case .workflowRun: store.openWorkflowRun(item.id)
                        }
                    }
                        .font(.omSmall).lineLimit(2).buttonStyle(.plain)
                }
                ForEach(store.plans.prefix(4)) { plan in
                    Button(plan.title) { onOpenPlan(plan.id) }
                        .font(.omSmall).lineLimit(2).buttonStyle(.plain)
                }
            }
            .padding(16)
        }
        .background(Color.grey20)
        .accessibilityIdentifier("tasks-sidebar")
    }
}
