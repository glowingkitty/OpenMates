// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// Retained Tasks workspace state. MainAppView owns this object so board selection,
// horizontal position, and detail context survive workspace switches.
// Specification: specifications/features/tasks/specification.yml
// Assertions: tasks.lifecycle.visible, tasks.surface.semantic-parity
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.drag-move, apple-task-board.workflow-run, apple-task-board.edit

import Combine
import Foundation

@MainActor
final class TasksWorkspaceStore: ObservableObject {
    @Published private(set) var boardItems: [TaskBoardItem] = []
    @Published private(set) var plans: [UserPlanItem] = []
    @Published private(set) var projectNames: [String: String] = [:]
    @Published private(set) var isLoading = false
    @Published private(set) var isSaving = false
    @Published private(set) var taskEditErrorMessage: String?
    @Published private(set) var interactionErrorMessage: String?
    @Published private(set) var errorMessage: String?
    @Published private(set) var plansLoadErrorMessage: String?
    @Published private(set) var projectNamesLoadErrorMessage: String?
    @Published var selectedTaskID: String?
    @Published private(set) var presentedTaskID: String?
    @Published var selectedPlanID: String?
    @Published var selectedWorkflowRunID: String?
    @Published var searchText = ""
    @Published var promptDraft = ""
    @Published var tagsExpanded = true

    private let teamContext: TeamWorkspaceContext
    private var teamEpoch: UInt64?
    private var contextTeamID: String?
    private let tasks: UserTasksService
    private let plansService: UserPlansService
    private let projects: ProjectsWorkspaceServing
    private var accountID: String?
    private var projectID: String?
    private var teamID: String?
    private var scope: UUID?
    private var serverProfile: ServerProfile?
    private var loadGeneration = UUID()
    private var pendingTaskDetail: (id: String, generation: UUID)?
    private var hasLoaded = false
    private var isPreview = false
    #if DEBUG
    /// A suspended loader lets the unit test prove that a new filter request
    /// starts while the previous request is still in flight.
    var debugTaskEditor: (@MainActor (UserTaskItem, UserTaskUpdateInput) async throws -> UserTaskItem)?
    var debugTaskMover: (@MainActor (UserTaskItem, UserTaskStatus, Int) async throws -> UserTaskItem)?
    var debugBoardLoader: (@MainActor (UserTaskListFilters) async throws -> [TaskBoardItem])?
    #endif

    init(tasks: UserTasksService = UserTasksService(),
         plansService: UserPlansService = UserPlansService(),
         projects: ProjectsWorkspaceServing = ProjectsWorkspaceService(),
         teamContext: TeamWorkspaceContext = .shared) {
        self.teamContext = teamContext
        self.tasks = tasks
        self.plansService = plansService
        self.projects = projects
    }

    var selectedTask: UserTaskItem? {
        guard let selectedTaskID else { return nil }
        return boardItems.compactMap { item -> UserTaskItem? in
            if case .task(let task) = item, task.id == selectedTaskID { return task }
            return nil
        }.first
    }

    var selectedPlan: UserPlanItem? {
        guard let selectedPlanID else { return nil }
        return plans.first { $0.id == selectedPlanID }
    }

    var selectedWorkflowRun: WorkflowRunTaskProjection? {
        guard let selectedWorkflowRunID else { return nil }
        return boardItems.compactMap { item -> WorkflowRunTaskProjection? in
            if case .workflowRun(let run) = item, run.id == selectedWorkflowRunID { return run }
            return nil
        }.first
    }

    var usesPreviewData: Bool { isPreview }

    var canEditPlans: Bool { teamID == nil }

    /// TasksPage.svelte keeps the first three distinct labels in board order.
    var filterTags: [String] {
        var seen = Set<String>()
        var labels: [String] = []
        for item in boardItems {
            guard case .task(let task) = item else { continue }
            for tag in task.tags where !tag.isEmpty && seen.insert(tag).inserted {
                labels.append(tag)
                if labels.count == 3 { return labels }
            }
        }
        return labels.isEmpty ? ["my-tasks", "software", "hardware"] : labels
    }

    var visibleBoardItems: [TaskBoardItem] {
        let query = normalizedSearchQuery
        guard !query.isEmpty else { return boardItems }
        return boardItems.filter { item in
            if case .task(let task) = item {
                return task.title.localizedCaseInsensitiveContains(query)
                    || task.description.localizedCaseInsensitiveContains(query)
                    || task.assigneeType.rawValue.localizedCaseInsensitiveContains(query)
                    || task.tags.contains { $0.localizedCaseInsensitiveContains(query) }
            }
            if case .workflowRun(let run) = item {
                return run.displayTitle.localizedCaseInsensitiveContains(query)
                    || (run.blockedMessage ?? "").localizedCaseInsensitiveContains(query)
                    || "user".localizedCaseInsensitiveContains(query)
            }
            return false
        }
    }

    var visiblePlans: [UserPlanItem] {
        let query = normalizedSearchQuery
        return plans.filter { plan in
            plan.status != .archived && (query.isEmpty || plan.title.localizedCaseInsensitiveContains(query)
                || plan.goal.localizedCaseInsensitiveContains(query)
                || plan.status.rawValue.localizedCaseInsensitiveContains(query)
                || plan.status.rawValue.replacingOccurrences(of: "_", with: "-").localizedCaseInsensitiveContains(query)
                || plan.risks.localizedCaseInsensitiveContains(query)
                || plan.linkedProjectIds.contains { (projectNames[$0] ?? "").localizedCaseInsensitiveContains(query) })
        }
    }

    /// TasksPage.svelte strips one leading label marker before searching every
    /// supported field; a marker inside a title or label remains meaningful.
    private var normalizedSearchQuery: String {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        return query.hasPrefix("#") ? String(query.dropFirst()) : query
    }

    func reset(accountID: String?) {
        guard accountID == nil || self.accountID != accountID
                || scope != OfflineStore.shared.scopeGeneration
                || serverProfile != ServerProfile.current()
                || teamEpoch != teamContext.contextEpoch
                || contextTeamID != teamContext.teamID else { return }
        self.accountID = accountID
        teamEpoch = teamContext.contextEpoch
        contextTeamID = teamContext.teamID
        isPreview = false
        scope = OfflineStore.shared.scopeGeneration
        serverProfile = accountID == nil ? nil : ServerProfile.current()
        loadGeneration = UUID()
        pendingTaskDetail = nil
        projectID = nil
        teamID = teamContext.teamID
        boardItems = []
        plans = []
        projectNames = [:]
        selectedTaskID = nil
        presentedTaskID = nil
        selectedPlanID = nil
        selectedWorkflowRunID = nil
        searchText = ""
        promptDraft = ""
        errorMessage = nil
        interactionErrorMessage = nil
        taskEditErrorMessage = nil
        plansLoadErrorMessage = nil
        projectNamesLoadErrorMessage = nil
        hasLoaded = false
        isLoading = false
        isSaving = false
    }

    func load(accountID: String, projectID: String? = nil,
              teamID: String? = nil, force: Bool = false, requestedTaskID: String? = nil) async {
        reset(accountID: accountID)
        isPreview = false
        if self.projectID != projectID || self.teamID != teamID {
            self.projectID = projectID
            self.teamID = teamID
            loadGeneration = UUID()
            pendingTaskDetail = nil
            hasLoaded = false
            // The previous request still owns its old generation. Its defer
            // must not keep this new filter context permanently loading.
            isLoading = false
            boardItems = []
            plans = []
            projectNames = [:]
            selectedTaskID = nil
            presentedTaskID = nil
            selectedPlanID = nil
            selectedWorkflowRunID = nil
            promptDraft = ""
        }
        if let requestedTaskID { openTaskWhenAvailable(requestedTaskID) }
        guard !isLoading, force || !hasLoaded else { return }
        let fence = UserTasksAccountFence(accountID: accountID, teamContext: teamContext)
        let generation = loadGeneration
        isLoading = true
        errorMessage = nil
        defer { if generation == loadGeneration { isLoading = false } }
        plansLoadErrorMessage = nil
        projectNamesLoadErrorMessage = nil
        let filters = UserTaskListFilters(projectID: projectID, teamID: teamID)
        #if DEBUG
        let useCache = debugBoardLoader == nil
        #else
        let useCache = true
        #endif
        if useCache {
            if let cached = try? await tasks.cachedBoard(filters: filters, fence: fence),
               await acceptsLoadResult(generation: generation, fence: fence) {
                boardItems = cached
                applyPendingTaskDetail()
            }
            if let cached = try? await plansService.cachedPlans(projectID: projectID, teamID: teamID, fence: fence),
               await acceptsLoadResult(generation: generation, fence: fence) { plans = cached }
            if let cached = try? await projects.cachedProjects(accountID: accountID, teamID: teamID),
               await acceptsLoadResult(generation: generation, fence: fence) {
                projectNames = Dictionary(cached.map { ($0.id, $0.name) }, uniquingKeysWith: { _, last in last })
            }
        }
        var boardLoaded = false
        var plansLoaded = false
        do {
            let filters = UserTaskListFilters(projectID: projectID, teamID: teamID)
            let fetchedItems: [TaskBoardItem]
            #if DEBUG
            if let debugBoardLoader {
                fetchedItems = try await debugBoardLoader(filters)
            } else {
                fetchedItems = try await tasks.listBoard(filters: filters, fence: fence)
            }
            #else
            fetchedItems = try await tasks.listBoard(filters: filters, fence: fence)
            #endif
            try await fence.check()
            guard generation == loadGeneration else { return }
            boardItems = fetchedItems
            applyPendingTaskDetail()
            boardLoaded = true
        } catch {
            guard await acceptsLoadResult(generation: generation, fence: fence) else { return }
            recordLoadFailure(error, stage: .tasks, generation: generation)
        }
        // The deployed web loads these independently. A Plan or project-label
        // failure must not discard successfully opened, account-fenced Tasks.
        do {
            let fetchedPlans = try await plansService.list(projectID: projectID, teamID: teamID, fence: fence)
            try await fence.check()
            guard generation == loadGeneration else { return }
            plans = fetchedPlans
            plansLoaded = true
        } catch {
            guard await acceptsLoadResult(generation: generation, fence: fence) else { return }
            recordLoadFailure(error, stage: .plans, generation: generation)
        }
        do {
            let fetchedProjects = try await projects.listProjects(accountID: accountID, teamID: teamID)
            try await fence.check()
            guard generation == loadGeneration else { return }
            projectNames = Dictionary(fetchedProjects.map { ($0.id, $0.name) }, uniquingKeysWith: { _, current in current })
        } catch {
            guard await acceptsLoadResult(generation: generation, fence: fence) else { return }
            recordLoadFailure(error, stage: .projectNames, generation: generation)
        }
        guard generation == loadGeneration else { return }
        hasLoaded = boardLoaded && plansLoaded
    }

    private enum LoadStage: String { case tasks, plans, projectNames = "project_names" }

    func retryLoad() async {
        guard let accountID, currentFence() != nil else { return }
        await load(accountID: accountID, projectID: projectID, teamID: teamID, force: true)
    }

    private func acceptsLoadResult(generation: UUID, fence: UserTasksAccountFence) async -> Bool {
        guard generation == loadGeneration, (try? await fence.check()) != nil else { return false }
        return generation == loadGeneration
    }

    private func recordLoadFailure(_ error: Error, stage: LoadStage, generation: UUID) {
        guard generation == loadGeneration else { return }
        NativeDiagnostics.error("Tasks workspace load failed stage=\(stage.rawValue) error_type=\(type(of: error))", category: "tasks")
        switch stage {
        case .tasks: errorMessage = error.localizedDescription
        case .plans: plansLoadErrorMessage = error.localizedDescription
        case .projectNames: projectNamesLoadErrorMessage = error.localizedDescription
        }
    }

    #if DEBUG
    // Local fixture application exercises the production failure reducer. It
    // does not make requests, open keys, or bypass the real load/account fence.
    var debugLoadGeneration: UUID { loadGeneration }
    func debugCompleteWidgetInventory(_ items: [TaskBoardItem], generation: UUID) {
        guard isPreview, generation == loadGeneration else { return }
        boardItems = items
        applyPendingTaskDetail()
    }
    func debugApplyLoadFailure(_ error: Error, stage: String, generation: UUID) {
        guard let stage = LoadStage(rawValue: stage) else { return }
        recordLoadFailure(error, stage: stage, generation: generation)
    }
    #endif

    func openTask(_ id: String) {
        pendingTaskDetail = nil
        if selectedTaskID != id { presentedTaskID = nil }
        selectedPlanID = nil
        selectedWorkflowRunID = nil
        selectedTaskID = id
    }

    /// A widget may arrive while the same scoped inventory is already loading.
    /// Retain its destination until the actual Task is available, never an
    /// empty fullscreen reader or a selection from a replaced load context.
    func openTaskWhenAvailable(_ id: String) {
        pendingTaskDetail = (id, loadGeneration)
        applyPendingTaskDetail()
    }

    func cancelPendingTaskDetail() { pendingTaskDetail = nil }

    func taskDetailDidAppear(_ id: String) {
        guard selectedTask?.id == id,
              isPreview || (scope == OfflineStore.shared.scopeGeneration &&
                serverProfile == ServerProfile.current() && teamEpoch == teamContext.contextEpoch &&
                contextTeamID == teamContext.teamID) else { return }
        presentedTaskID = id
    }

    private func applyPendingTaskDetail() {
        guard let pending = pendingTaskDetail, pending.generation == loadGeneration,
              isPreview || (scope == OfflineStore.shared.scopeGeneration &&
                serverProfile == ServerProfile.current() && teamEpoch == teamContext.contextEpoch &&
                contextTeamID == teamContext.teamID),
              boardItems.contains(where: { if case .task(let task) = $0 { return task.id == pending.id }; return false }) else { return }
        openTask(pending.id)
    }

    #if DEBUG
    /// In-memory mirror of TaskBoard.preview.ts for signed-out visual checks.
    /// Ciphertext records are synthetic and never sent to the API.
    func installPreview(projectID: String? = nil, manyBacklog: Bool = false, accountID: String? = nil,
                        widgetTaskID: String? = nil) {
        reset(accountID: accountID)
        isPreview = true
        let timestamp = 1_788_883_200
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        func record<T: Decodable>(_ value: [String: Any], as type: T.Type) -> T? {
            guard let data = try? JSONSerialization.data(withJSONObject: value) else { return nil }
            return try? decoder.decode(type, from: data)
        }
        func task(_ id: String, _ title: String, _ status: UserTaskStatus,
                  _ position: Int, projects: [String] = [], tags: [String] = ["OpenMates"],
                  assignee: UserTaskAssigneeType = .openmates, chatID: String? = nil,
                  blockedReason: String = "", priority: Int = 0) -> TaskBoardItem? {
            var json: [String: Any] = [
                "task_id": id, "encrypted_title": "preview-ciphertext",
                "status": status.rawValue, "assignee_type": assignee.rawValue,
                "created_at": timestamp, "updated_at": timestamp,
                "position": position, "version": 1, "priority": priority,
            ]
            if let chatID { json["primary_chat_id"] = chatID }
            guard let encrypted = record(json, as: EncryptedUserTaskRecord.self) else { return nil }
            return .task(UserTaskItem(record: encrypted, title: title, description: "",
                latestInstruction: "", tags: tags, linkedProjectIds: projects,
                blockedReason: blockedReason, externalChat: nil))
        }
        boardItems = [
            task(widgetTaskID ?? "preview-backlog-1", "Research how expensive hoverboard motors are to carry 2–3 people", .backlog, 0,
                 projects: ["project-ballpit"], tags: ["Self driving ballpit"], priority: 3),
            task("preview-backlog-2", "Teams feature", .backlog, 1, projects: ["project-openmates"]),
            task("preview-todo", "Design 3D model", .todo, 0, projects: ["project-ballpit"],
                 tags: ["Self driving ballpit"], assignee: .user),
            task("preview-active", "Research open source accounting software alternatives", .inProgress, 0,
                 projects: ["project-openmates"], chatID: "preview-chat"),
            task("preview-blocked", "Confirm launch requirements", .blocked, 0,
                 tags: [], assignee: .unassigned, blockedReason: "Waiting for confirmation."),
        ].compactMap { $0 }
        if manyBacklog {
            // TaskBoard.preview.ts manyBacklog: 55 Tasks plus one draft Plan.
            boardItems += (0..<53).compactMap { index in
                task("preview-extra-\(index)", "Extra backlog task \(index + 1)",
                     .backlog, index + 2)
            }
        }
        boardItems.append(.workflowRun(WorkflowRunTaskProjection(
            taskId: "preview-workflow", source: "workflow_run", projectionKind: "next_run",
            workflowId: "weather-report", workflowRunId: "weather-report-run",
            triggerId: "daily-trigger", label: "Daily Weather Report — July 3 2026", title: nil,
            status: .done, runStatus: "completed", canCancel: false, canDelete: false,
            dueAt: nil, scheduledAt: nil, blockedMessage: nil, readOnly: true,
            createdAt: timestamp, updatedAt: timestamp, position: 0)))
        func plan(_ id: String, _ title: String, _ status: UserPlanStatus) -> UserPlanItem? {
            let json: [String: Any] = [
                "plan_id": id, "encrypted_title": "preview-ciphertext",
                "encrypted_goal": "preview-ciphertext", "status": status.rawValue,
                "created_at": timestamp, "updated_at": timestamp, "version": 1,
            ]
            guard let encrypted = record(json, as: EncryptedUserPlanRecord.self) else { return nil }
            return UserPlanItem(record: encrypted, title: title,
                goal: "Coordinate the work and verify the outcome before completion.",
                scopeIn: "", scopeOut: "", userFlows: [], assumptions: "", openQuestions: "",
                constraints: "", decisions: "", risks: "", linkedProjectIds: ["project-openmates"])
        }
        plans = [
            plan("preview-plan-draft", "Prepare the OpenMates launch plan", .draft),
            plan("preview-plan-completed", "Verify production launch readiness", .completed),
        ].compactMap { $0 }
        projectNames = ["project-ballpit": "Self driving ballpit", "project-openmates": "OpenMates"]
        if let projectID {
            let sourceProjectID = projectID == "preview-project" ? "project-openmates" : projectID
            boardItems = boardItems.compactMap { item in
                guard case .task(let task) = item,
                      task.linkedProjectIds.contains(sourceProjectID) else { return nil }
                return .task(UserTaskItem(record: task.record, title: task.title,
                    description: task.description, latestInstruction: task.latestInstruction,
                    tags: task.tags, linkedProjectIds: [projectID],
                    blockedReason: task.blockedReason, externalChat: task.externalChat))
            }
            plans = plans.filter { $0.linkedProjectIds.contains(sourceProjectID) }.map { plan in
                UserPlanItem(record: plan.record, title: plan.title, goal: plan.goal,
                    scopeIn: plan.scopeIn, scopeOut: plan.scopeOut, userFlows: plan.userFlows,
                    assumptions: plan.assumptions, openQuestions: plan.openQuestions,
                    constraints: plan.constraints, decisions: plan.decisions, risks: plan.risks,
                    linkedProjectIds: [projectID])
            }
            projectNames = [projectID: projectNames[sourceProjectID] ?? "OpenMates"]
        }
        hasLoaded = true
    }
    #endif

    func openPlan(_ id: String) {
        pendingTaskDetail = nil
        presentedTaskID = nil
        selectedTaskID = nil
        selectedWorkflowRunID = nil
        selectedPlanID = id
    }

    func openWorkflowRun(_ id: String) {
        pendingTaskDetail = nil
        presentedTaskID = nil
        guard boardItems.contains(where: { item in
            if case .workflowRun(let run) = item { return run.id == id && run.workflowRunId != nil }
            return false
        }) else { return }
        selectedTaskID = nil
        selectedPlanID = nil
        selectedWorkflowRunID = id
    }

    func closeDetail() {
        pendingTaskDetail = nil
        presentedTaskID = nil
        selectedTaskID = nil
        selectedPlanID = nil
        selectedWorkflowRunID = nil
    }

    func workflowRunDetail(_ projection: WorkflowRunTaskProjection,
                           currentGraph: WorkflowGraph? = nil) async throws -> (WorkflowRunDetail, WorkflowGraph?) {
        #if DEBUG
        if isPreview { return try await WorkflowRunTaskReader.preview(projection) }
        #endif
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        return try await WorkflowRunTaskReader.read(projection, currentGraph: currentGraph,
            request: { path in
                try await fence.check()
                let data: Data = try await APIClient.shared.request(.get, path: path,
                    serverProfile: fence.serverProfile,
                    expectedAccountID: fence.accountID, expectedScope: fence.scope,
                    expectedTeamContext: fence.requestTeamContext)
                try await fence.check()
                return data
            }, validate: { try await fence.check() })
    }

    @discardableResult
    func createTask(_ input: UserTaskCreateInput) async -> Bool {
        #if DEBUG
        if isPreview, ProcessInfo.processInfo.arguments.contains("--ui-test-task-prompt-submit") {
            guard !isSaving else { return false }
            if ProcessInfo.processInfo.arguments.contains("--ui-test-task-create-failure") {
                interactionErrorMessage = "Synthetic task creation rejected"
                return false
            }
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let id = "preview-created-\(UUID().uuidString)"
            let json: [String: Any] = ["task_id": id, "encrypted_title": "preview-ciphertext",
                "status": "backlog", "assignee_type": "openmates", "created_at": 1788883200,
                "updated_at": 1788883200, "position": boardItems.count, "version": 1, "priority": 0]
            guard let data = try? JSONSerialization.data(withJSONObject: json),
                  let record = try? decoder.decode(EncryptedUserTaskRecord.self, from: data) else { return false }
            boardItems.append(.task(UserTaskItem(record: record, title: input.title, description: "",
                latestInstruction: "", tags: [], linkedProjectIds: projectID.map { [$0] } ?? [],
                blockedReason: "", externalChat: nil)))
            interactionErrorMessage = nil
            return true
        }
        #endif
        guard let fence = currentFence(), !isSaving else { return false }
        guard teamID == nil else {
            errorMessage = UserTasksError.unsupportedTeamMutation.localizedDescription
            return false
        }
        isSaving = true
        defer { isSaving = false }
        do {
            var scopedInput = input
            if let projectID, !scopedInput.linkedProjectIDs.contains(projectID) {
                scopedInput.linkedProjectIDs.append(projectID)
            }
            let item = try await tasks.create(scopedInput, fence: fence)
            try await fence.check()
            boardItems.append(.task(item))
            selectedTaskID = item.id
            errorMessage = nil
            return true
        } catch {
            guard (try? await fence.check()) != nil else { return false }
            errorMessage = error.localizedDescription
            return false
        }
    }

    func clearTaskEditError() { taskEditErrorMessage = nil }

    /// Return success only after an account-fenced authoritative response. The
    /// detail view retains its original version and draft when this returns false.
    @discardableResult
    func saveTask(_ task: UserTaskItem, patch: UserTaskUpdateInput) async -> Bool {
        guard !isSaving, boardItems.contains(where: { item in
            if case .task(let current) = item { return current.id == task.id }; return false
        }) else { return false }
        let generation = loadGeneration
        let fence = currentFence()
        #if DEBUG
        let preview = isPreview
        guard preview || fence != nil else { return false }
        #else
        guard fence != nil else { return false }
        #endif
        isSaving = true
        taskEditErrorMessage = nil
        defer { if generation == loadGeneration { isSaving = false } }
        do {
            let updated: UserTaskItem
            #if DEBUG
            if preview {
                guard let latest = boardItems.compactMap({ item -> UserTaskItem? in
                    if case .task(let value) = item, value.id == task.id { return value }; return nil
                }).first, latest.version == task.version else {
                    throw APIError.httpError(status: 409, message: "")
                }
                if let debugTaskEditor { updated = try await debugTaskEditor(task, patch) }
                else {
                    if ProcessInfo.processInfo.arguments.contains("--ui-test-task-edit-conflict") {
                        throw APIError.httpError(status: 409, message: "")
                    }
                    if ProcessInfo.processInfo.arguments.contains("--ui-test-task-edit-failure") {
                        throw UserTasksError.invalidResponse
                    }
                    updated = try previewEditedTask(task, patch: patch)
                }
                guard generation == loadGeneration, isPreview else { return false }
            } else {
                guard let fence else { return false }
                updated = try await tasks.update(task, patch: patch, teamID: teamID, fence: fence)
                try await fence.check()
            }
            #else
            guard let fence else { return false }
            updated = try await tasks.update(task, patch: patch, teamID: teamID, fence: fence)
            try await fence.check()
            #endif
            guard generation == loadGeneration else { return false }
            replace(updated)
            errorMessage = nil
            return true
        } catch {
            guard generation == loadGeneration else { return false }
            if let fence, (try? await fence.check()) == nil { return false }
            if case APIError.httpError(let code, _) = error, code == 409 {
                taskEditErrorMessage = AppStrings.tasksEditConflict
            } else { taskEditErrorMessage = AppStrings.tasksEditFailed }
            NativeDiagnostics.error("Task edit failed error_type=\(type(of: error))", category: "tasks")
            return false
        }
    }

    #if DEBUG
    /// Synthetic preview writes use the same save reducer with no network,
    /// real account state, ciphertext creation or persistent storage.
    private func previewEditedTask(_ task: UserTaskItem, patch: UserTaskUpdateInput) throws -> UserTaskItem {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        guard var json = try JSONSerialization.jsonObject(with: encoder.encode(task.record)) as? [String: Any] else {
            throw UserTasksError.invalidResponse
        }
        json["version"] = task.version + 1
        if let value = patch.assigneeType {
            json["assignee_type"] = value.rawValue
            if value != task.assigneeType {
                if value == .openmates { json["assignee_identity"] = UserTaskAssigneeIdentity.openmates.rawValue }
                else { json["assignee_identity"] = NSNull() }
            }
        }
        if let value = patch.assigneeIdentity { json["assignee_identity"] = value.rawValue }
        if patch.clearDueAt { json.removeValue(forKey: "due_at") }
        else if let value = patch.dueAt { json["due_at"] = value }
        if let value = patch.priority { json["priority"] = value }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let record = try decoder.decode(EncryptedUserTaskRecord.self,
            from: JSONSerialization.data(withJSONObject: json))
        return UserTaskItem(record: record, title: patch.title ?? task.title,
            description: patch.description ?? task.description, latestInstruction: task.latestInstruction,
            tags: patch.tags ?? task.tags, linkedProjectIds: task.linkedProjectIds,
            blockedReason: task.blockedReason, externalChat: task.externalChat)
    }
    #endif

    /// Drops and explicit menu moves share ordering, optimistic feedback and rollback.
    func moveTask(_ task: UserTaskItem, to status: UserTaskStatus) async {
        guard !isSaving, let current = boardItems.compactMap({ item -> UserTaskItem? in
            if case .task(let candidate) = item, candidate.id == task.id { return candidate }
            return nil
        }).first, current.status != status else { return }
        let position = firstPosition(in: status, excluding: current.id)
        let generation = loadGeneration
        let fence = currentFence()
        #if DEBUG
        let preview = isPreview
        guard preview || fence != nil else { return }
        #else
        guard fence != nil else { return }
        #endif
        isSaving = true
        interactionErrorMessage = nil
        replace(current.placing(on: status, at: position))
        defer { if generation == loadGeneration { isSaving = false } }
        do {
            let updated: UserTaskItem
            #if DEBUG
            if preview {
                if let debugTaskMover {
                    updated = try await debugTaskMover(current, status, position)
                } else {
                    try await Task.sleep(for: .milliseconds(180))
                    if ProcessInfo.processInfo.arguments.contains("--ui-test-task-move-failure") {
                        throw UserTasksError.invalidResponse
                    }
                    updated = current.placing(on: status, at: position)
                }
                guard generation == loadGeneration, isPreview else { return }
            } else {
                guard let fence else { return }
                updated = try await persistMove(current, to: status, position: position, fence: fence, generation: generation)
                try await fence.check()
            }
            #else
            guard let fence else { return }
            updated = try await persistMove(current, to: status, position: position, fence: fence, generation: generation)
            try await fence.check()
            #endif
            guard generation == loadGeneration else { return }
            replace(updated)
        } catch {
            guard generation == loadGeneration else { return }
            if let fence {
                guard await acceptsLoadResult(generation: generation, fence: fence) else { return }
                if let refreshed = try? await tasks.listBoard(filters: .init(projectID: projectID, teamID: teamID), fence: fence),
                   await acceptsLoadResult(generation: generation, fence: fence) {
                    boardItems = refreshed
                } else {
                    guard await acceptsLoadResult(generation: generation, fence: fence) else { return }
                    replace(current)
                }
            } else {
                #if DEBUG
                guard isPreview else { return }
                replace(current)
                #endif
            }
            interactionErrorMessage = AppStrings.tasksMoveFailed
            NativeDiagnostics.error("Task move failed error_type=\(type(of: error))", category: "tasks")
        }
    }

    var interactionGeneration: UUID { loadGeneration }

    /// Web inserts a moved card ahead of every item in its destination column.
    func firstPosition(in status: UserTaskStatus, excluding id: String) -> Int {
        let lowest = boardItems.filter { $0.id != id && $0.status == status }.map(\.position).min() ?? 0
        return min(0, lowest) > Int.min ? min(0, lowest) - 1 : Int.min
    }

    private func persistMove(_ task: UserTaskItem, to status: UserTaskStatus, position: Int,
                             fence: UserTasksAccountFence, generation: UUID) async throws -> UserTaskItem {
        do {
            return try await tasks.move(task, to: status, position: position, teamID: teamID, fence: fence)
        } catch APIError.httpError(let statusCode, _) where statusCode == 409 {
            let latest = try await tasks.listBoard(filters: .init(projectID: projectID, teamID: teamID), fence: fence)
            try await fence.check()
            guard generation == loadGeneration else { throw UserTasksError.accountChanged }
            guard let current = latest.compactMap({ item -> UserTaskItem? in
                if case .task(let candidate) = item, candidate.id == task.id { return candidate }
                return nil
            }).first else { throw UserTasksError.invalidResponse }
            boardItems = latest
            replace(current.placing(on: status, at: position))
            return try await tasks.move(current, to: status, position: position, teamID: teamID, fence: fence)
        }
    }

    func taskAction(_ action: String, task: UserTaskItem) async {
        guard let fence = currentFence(), !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        do {
            let updated = try await tasks.action(action, task: task, teamID: teamID, fence: fence)
            try await fence.check()
            replace(updated)
            errorMessage = nil
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
        }
    }

    func deleteTask(_ task: UserTaskItem) async {
        guard let fence = currentFence(), !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        do {
            try await tasks.delete(task, teamID: teamID, fence: fence)
            try await fence.check()
            boardItems.removeAll { $0.id == task.id }
            if selectedTaskID == task.id { selectedTaskID = nil }
            errorMessage = nil
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
        }
    }

    func movePlan(_ plan: UserPlanItem, to column: UserTaskStatus) async {
        guard let fence = currentFence(), !isSaving else { return }
        guard canEditPlans else { errorMessage = UserTasksError.unsupportedTeamMutation.localizedDescription; return }
        isSaving = true
        defer { isSaving = false }
        do {
            let updated: UserPlanItem
            switch column {
            case .backlog: updated = try await plansService.update(plan, status: .draft, fence: fence)
            case .todo:
                if plan.primaryChatId == nil {
                    updated = try await plansService.update(plan, status: .awaitingConfirmation, fence: fence)
                } else {
                    updated = try await plansService.activate(plan, fence: fence)
                }
            case .inProgress:
                guard plan.primaryChatId != nil else { throw UserTasksError.missingLinkedKey("chat") }
                updated = try await plansService.update(plan, status: .executing, fence: fence)
            case .blocked:
                guard plan.primaryChatId != nil else { throw UserTasksError.missingLinkedKey("chat") }
                updated = try await plansService.update(plan, status: .blocked, fence: fence)
            case .done: updated = try await plansService.complete(plan, fence: fence)
            }
            try await fence.check()
            replace(updated)
            errorMessage = nil
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
        }
    }

    func savePlan(_ plan: UserPlanItem, title: String? = nil,
                  goal: String? = nil, status: UserPlanStatus? = nil) async {
        guard let fence = currentFence(), !isSaving else { return }
        guard canEditPlans else { errorMessage = UserTasksError.unsupportedTeamMutation.localizedDescription; return }
        isSaving = true
        defer { isSaving = false }
        do {
            let updated = try await plansService.update(plan, title: title, goal: goal,
                status: status, fence: fence)
            try await fence.check()
            replace(updated)
            errorMessage = nil
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
        }
    }

    func planDetail(_ plan: UserPlanItem) async throws -> UserPlanDetailState {
        if isPreview {
            return UserPlanDetailState(
                assumptions: [UserPlanDetailEntry(id: "preview-assumption", title: "Launch requirements are confirmed",
                    subtitle: "unchecked before implementation", evidence: "", status: "unchecked")],
                criteria: [UserPlanDetailEntry(id: "preview-criterion", title: "The release is ready for users",
                    subtitle: "uncovered · 0 checks", evidence: "", status: "pending")],
                verifications: [], referencePatterns: [])
        }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        return try await plansService.detail(plan, fence: fence)
    }

    func createPlan(title: String, goal: String, projectIDs: [String]) async {
        guard let fence = currentFence(), !isSaving else { return }
        guard canEditPlans else { errorMessage = UserTasksError.unsupportedTeamMutation.localizedDescription; return }
        isSaving = true
        defer { isSaving = false }
        do {
            let plan = try await plansService.create(title: title, goal: goal,
                projectIDs: projectIDs, teamID: teamID, fence: fence)
            try await fence.check()
            plans.append(plan)
            openPlan(plan.id)
            errorMessage = nil
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
        }
    }

    func createPlanAssumption(_ text: String, plan: UserPlanItem) async throws -> UserPlanDetailState {
        guard canEditPlans else { throw UserTasksError.unsupportedTeamMutation }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        try await plansService.createAssumption(text, plan: plan, fence: fence)
        return try await plansService.detail(plan, fence: fence)
    }

    func confirmPlanAssumption(_ id: String, plan: UserPlanItem) async throws -> UserPlanDetailState {
        guard canEditPlans else { throw UserTasksError.unsupportedTeamMutation }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        try await plansService.confirmAssumption(id, plan: plan, fence: fence)
        return try await plansService.detail(plan, fence: fence)
    }

    func createPlanCriterion(_ text: String, plan: UserPlanItem) async throws -> UserPlanDetailState {
        guard canEditPlans else { throw UserTasksError.unsupportedTeamMutation }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        try await plansService.createCriterion(text, plan: plan, fence: fence)
        return try await plansService.detail(plan, fence: fence)
    }

    func createPlanVerification(title: String, command: String,
                                covering criterionIDs: [String], plan: UserPlanItem) async throws -> UserPlanDetailState {
        guard canEditPlans else { throw UserTasksError.unsupportedTeamMutation }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        try await plansService.createVerification(title: title, command: command,
            covering: criterionIDs, plan: plan, fence: fence)
        return try await plansService.detail(plan, fence: fence)
    }

    func addPlanVerificationEvidence(_ summary: String, verificationID: String,
                                     plan: UserPlanItem) async throws -> UserPlanDetailState {
        guard canEditPlans else { throw UserTasksError.unsupportedTeamMutation }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        try await plansService.addVerificationEvidence(summary, verificationID: verificationID,
            plan: plan, fence: fence)
        return try await plansService.detail(plan, fence: fence)
    }

    func taskActivity(_ task: UserTaskItem) async throws -> [UserTaskActivityEntry] {
        if isPreview { return [] }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        return try await tasks.activity(for: task, teamID: teamID, fence: fence)
    }

    func addTaskComment(_ message: String, task: UserTaskItem) async throws -> UserTaskActivityEntry {
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        return try await tasks.addComment(message, task: task, teamID: teamID, fence: fence)
    }

    func taskDependencies(_ task: UserTaskItem) async throws -> [UserTaskDependency] {
        if isPreview { return [] }
        guard let fence = currentFence() else { throw UserTasksError.accountChanged }
        return try await tasks.dependencies(for: task, fence: fence)
    }

    private func currentFence() -> UserTasksAccountFence? {
        guard let accountID,
              scope == OfflineStore.shared.scopeGeneration,
              serverProfile == ServerProfile.current(),
              teamEpoch == teamContext.contextEpoch,
              contextTeamID == teamContext.teamID,
              teamID == teamContext.teamID else { return nil }
        return UserTasksAccountFence(accountID: accountID, teamContext: teamContext)
    }

    private func replace(_ task: UserTaskItem) {
        if let index = boardItems.firstIndex(where: { $0.id == task.id }) {
            boardItems[index] = .task(task)
        }
    }

    private func replace(_ plan: UserPlanItem) {
        if let index = plans.firstIndex(where: { $0.id == plan.id }) {
            plans[index] = plan
        }
    }
}


/// Tasks uses the Workflow wire decoder: APIClient's automatic camel-case
/// conversion cannot decode the explicit snake_case graph and run CodingKeys.
/// The injected read closure is shared by live requests and synthetic coverage.
@MainActor
enum WorkflowRunTaskReader {
    typealias Request = @MainActor (String) async throws -> Data
    enum ReadError: Error { case missingRun, invalidIdentity }

    static func read(_ projection: WorkflowRunTaskProjection, currentGraph: WorkflowGraph? = nil,
                     request: Request, validate: @MainActor () async throws -> Void) async throws -> (WorkflowRunDetail, WorkflowGraph?) {
        guard let runID = projection.workflowRunId, !runID.isEmpty else { throw ReadError.missingRun }
        try await validate()
        let runData = try await request(WorkflowAPIRequestFactory.runDetailPath(workflowId: projection.workflowId, runId: runID))
        try await validate()
        let run = try decode(WorkflowRunResponse.self, from: runData).run
        guard run.id == runID, run.workflowId == projection.workflowId else { throw ReadError.invalidIdentity }
        var graph = currentGraph
        if graph == nil {
            let workflowData = try await request(WorkflowAPIRequestFactory.workflowPath(projection.workflowId))
            try await validate()
            let workflow = try decode(WorkflowResponse.self, from: workflowData).workflow
            guard workflow.id == projection.workflowId else { throw ReadError.invalidIdentity }
            if run.versionId == workflow.currentVersionId { graph = workflow.graph }
            else {
                let versionData = try await request(WorkflowAPIRequestFactory.versionPath(workflowId: projection.workflowId, versionId: run.versionId))
                try await validate()
                let version = try decode(WorkflowVersionResponse.self, from: versionData).version
                guard version.versionId == run.versionId else { throw ReadError.invalidIdentity }
                graph = version.graph
            }
        }
        try await validate()
        return (run, graph)
    }

    private static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do { return try WorkflowAPI.decodeResponse(type, from: data) }
        catch {
            APIResponseDecodingDiagnostics.record(error: error, responseType: type)
            throw error
        }
    }

    static func loadErrorMessage(_ error: Error) -> String {
        // Server bodies, schema keys and record IDs belong in diagnostics, not
        // the run UI. A retention miss is displayed separately after a valid read.
        AppStrings.localized("workflows.runs.load_failed")
    }

    #if DEBUG
    static func preview(_ projection: WorkflowRunTaskProjection) async throws -> (WorkflowRunDetail, WorkflowGraph?) {
        let graph: [String: Any] = ["version": 1, "trigger_node_id": "schedule",
            "nodes": [["id": "schedule", "type": "schedule_trigger", "title": "Daily schedule", "config": [:]],
                      ["id": "end", "type": "end", "title": "Finished", "config": [:]]],
            "edges": [["from": "schedule", "to": "end"]], "variables": [:], "limits": [:], "ui_layout": [:]]
        let workflow: [String: Any] = ["id": projection.workflowId, "title": projection.displayTitle,
            "status": "active", "enabled": false, "lifecycle": "persisted", "source": "manual",
            "created_by_assistant": false, "run_content_retention": "last_5", "current_version_id": "preview-version",
            "created_at": projection.createdAt, "updated_at": projection.updatedAt, "graph": graph]
        let run: [String: Any] = ["id": projection.workflowRunId ?? "", "workflow_id": projection.workflowId,
            "version_id": "preview-version", "status": projection.runStatus, "trigger_type": "scheduled",
            "started_at": projection.createdAt, "finished_at": projection.updatedAt, "content_available": true,
            "node_runs": [["id": "preview-node-run", "run_id": projection.workflowRunId ?? "",
                "workflow_id": projection.workflowId, "node_id": "schedule", "node_type": "schedule_trigger", "status": "completed"]]]
        return try await read(projection, request: { path in
            let body: [String: Any] = path.contains("/runs/") ? ["run": run] : ["workflow": workflow]
            return try JSONSerialization.data(withJSONObject: body)
        }, validate: {})
    }
    #endif
}
