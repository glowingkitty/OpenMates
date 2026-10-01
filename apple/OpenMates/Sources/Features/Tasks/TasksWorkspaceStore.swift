// Retained Tasks workspace state. MainAppView owns this object so board selection,
// horizontal position, and detail context survive workspace switches.

import Combine
import Foundation

@MainActor
final class TasksWorkspaceStore: ObservableObject {
    @Published private(set) var boardItems: [TaskBoardItem] = []
    @Published private(set) var plans: [UserPlanItem] = []
    @Published private(set) var projectNames: [String: String] = [:]
    @Published private(set) var isLoading = false
    @Published private(set) var isSaving = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var plansLoadErrorMessage: String?
    @Published private(set) var projectNamesLoadErrorMessage: String?
    @Published var selectedTaskID: String?
    @Published var selectedPlanID: String?
    @Published var selectedWorkflowRunID: String?
    @Published var searchText = ""
    @Published var tagsExpanded = true

    private let tasks: UserTasksService
    private let plansService: UserPlansService
    private let projects: ProjectsWorkspaceServing
    private var accountID: String?
    private var projectID: String?
    private var teamID: String?
    private var scope: UUID?
    private var serverProfile: ServerProfile?
    private var loadGeneration = UUID()
    private var hasLoaded = false
    private var isPreview = false
    #if DEBUG
    /// A suspended loader lets the unit test prove that a new filter request
    /// starts while the previous request is still in flight.
    var debugBoardLoader: (@MainActor (UserTaskListFilters) async throws -> [TaskBoardItem])?
    #endif

    init(tasks: UserTasksService = UserTasksService(),
         plansService: UserPlansService = UserPlansService(),
         projects: ProjectsWorkspaceServing = ProjectsWorkspaceService()) {
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

    var visibleBoardItems: [TaskBoardItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return boardItems }
        return boardItems.filter { item in
            if case .task(let task) = item {
                return task.title.localizedCaseInsensitiveContains(query)
                    || task.description.localizedCaseInsensitiveContains(query)
                    || task.tags.contains { $0.localizedCaseInsensitiveContains(query.replacingOccurrences(of: "#", with: "")) }
            }
            return item.title.localizedCaseInsensitiveContains(query)
        }
    }

    var visiblePlans: [UserPlanItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        return plans.filter { plan in
            plan.status != .archived && (query.isEmpty || plan.title.localizedCaseInsensitiveContains(query)
                || plan.goal.localizedCaseInsensitiveContains(query))
        }
    }

    func reset(accountID: String?) {
        guard accountID == nil || self.accountID != accountID
                || scope != OfflineStore.shared.scopeGeneration
                || serverProfile != ServerProfile.current() else { return }
        self.accountID = accountID
        isPreview = false
        scope = OfflineStore.shared.scopeGeneration
        serverProfile = accountID == nil ? nil : ServerProfile.current()
        loadGeneration = UUID()
        projectID = nil
        teamID = nil
        boardItems = []
        plans = []
        projectNames = [:]
        selectedTaskID = nil
        selectedPlanID = nil
        selectedWorkflowRunID = nil
        searchText = ""
        errorMessage = nil
        plansLoadErrorMessage = nil
        projectNamesLoadErrorMessage = nil
        hasLoaded = false
        isLoading = false
        isSaving = false
    }

    func load(accountID: String, projectID: String? = nil,
              teamID: String? = nil, force: Bool = false) async {
        reset(accountID: accountID)
        isPreview = false
        if self.projectID != projectID || self.teamID != teamID {
            self.projectID = projectID
            self.teamID = teamID
            loadGeneration = UUID()
            hasLoaded = false
            // The previous request still owns its old generation. Its defer
            // must not keep this new filter context permanently loading.
            isLoading = false
            boardItems = []
            plans = []
            projectNames = [:]
            selectedTaskID = nil
            selectedPlanID = nil
            selectedWorkflowRunID = nil
        }
        guard !isLoading, force || !hasLoaded else { return }
        let fence = UserTasksAccountFence(accountID: accountID)
        let generation = loadGeneration
        isLoading = true
        errorMessage = nil
        defer { if generation == loadGeneration { isLoading = false } }
        plansLoadErrorMessage = nil
        projectNamesLoadErrorMessage = nil
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
            projectNames = [:]
            recordLoadFailure(error, stage: .projectNames, generation: generation)
        }
        guard generation == loadGeneration else { return }
        hasLoaded = boardLoaded && plansLoaded
    }

    private enum LoadStage: String { case tasks, plans, projectNames = "project_names" }

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
    func debugApplyLoadFailure(_ error: Error, stage: String, generation: UUID) {
        guard let stage = LoadStage(rawValue: stage) else { return }
        recordLoadFailure(error, stage: stage, generation: generation)
    }
    #endif

    func openTask(_ id: String) {
        selectedPlanID = nil
        selectedWorkflowRunID = nil
        selectedTaskID = id
    }

    #if DEBUG
    /// In-memory mirror of TaskBoard.preview.ts for signed-out visual checks.
    /// Ciphertext records are synthetic and never sent to the API.
    func installPreview(projectID: String? = nil) {
        reset(accountID: nil)
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
            task("preview-backlog-1", "Research how expensive hoverboard motors are to carry 2–3 people", .backlog, 0,
                 projects: ["project-ballpit"], tags: ["Self driving ballpit"], priority: 3),
            task("preview-backlog-2", "Teams feature", .backlog, 1, projects: ["project-openmates"]),
            task("preview-todo", "Design 3D model", .todo, 0, projects: ["project-ballpit"],
                 tags: ["Self driving ballpit"], assignee: .user),
            task("preview-active", "Research open source accounting software alternatives", .inProgress, 0,
                 projects: ["project-openmates"], chatID: "preview-chat"),
            task("preview-blocked", "Confirm launch requirements", .blocked, 0,
                 tags: [], assignee: .unassigned, blockedReason: "Waiting for confirmation."),
        ].compactMap { $0 }
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
        selectedTaskID = nil
        selectedWorkflowRunID = nil
        selectedPlanID = id
    }

    func openWorkflowRun(_ id: String) {
        selectedTaskID = nil
        selectedPlanID = nil
        selectedWorkflowRunID = id
    }

    func closeDetail() {
        selectedTaskID = nil
        selectedPlanID = nil
        selectedWorkflowRunID = nil
    }

    func workflowRunDetail(_ projection: WorkflowRunTaskProjection,
                           currentGraph: WorkflowGraph? = nil) async throws -> (WorkflowRunDetail, WorkflowGraph?) {
        guard let runID = projection.workflowRunId,
              let fence = currentFence() else { throw UserTasksError.accountChanged }
        try await fence.check()
        let response: WorkflowRunResponse = try await APIClient.shared.request(.get,
            path: WorkflowAPIRequestFactory.runDetailPath(workflowId: projection.workflowId, runId: runID),
            serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        var graph = currentGraph
        if graph == nil {
            let workflowResponse: WorkflowResponse = try await APIClient.shared.request(.get,
                path: WorkflowAPIRequestFactory.workflowPath(projection.workflowId),
                serverProfile: fence.serverProfile,
                expectedAccountID: fence.accountID, expectedScope: fence.scope)
            try await fence.check()
            let workflow = workflowResponse.workflow
            if response.run.versionId == workflow.currentVersionId {
                graph = workflow.graph
            } else {
                let versionResponse: WorkflowVersionResponse = try await APIClient.shared.request(.get,
                    path: WorkflowAPIRequestFactory.versionPath(workflowId: projection.workflowId,
                                                                versionId: response.run.versionId),
                    serverProfile: fence.serverProfile,
                    expectedAccountID: fence.accountID, expectedScope: fence.scope)
                try await fence.check()
                graph = versionResponse.version.graph
            }
        }
        return (response.run, graph)
    }

    func createTask(_ input: UserTaskCreateInput) async {
        guard let fence = currentFence(), !isSaving else { return }
        guard teamID == nil else {
            errorMessage = UserTasksError.unsupportedTeamMutation.localizedDescription
            return
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
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
        }
    }

    func saveTask(_ task: UserTaskItem, patch: UserTaskUpdateInput) async {
        guard let fence = currentFence(), !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        do {
            let updated = try await tasks.update(task, patch: patch, teamID: teamID, fence: fence)
            try await fence.check()
            replace(updated)
            errorMessage = nil
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
        }
    }

    func moveTask(_ task: UserTaskItem, to status: UserTaskStatus) async {
        guard let fence = currentFence(), !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        do {
            let updated = try await tasks.move(task, to: status, teamID: teamID, fence: fence)
            try await fence.check()
            replace(updated)
            errorMessage = nil
        } catch {
            guard (try? await fence.check()) != nil else { return }
            errorMessage = error.localizedDescription
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
              serverProfile == ServerProfile.current() else { return nil }
        return UserTasksAccountFence(accountID: accountID)
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
