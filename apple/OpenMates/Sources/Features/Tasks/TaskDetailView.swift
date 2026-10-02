import SwiftUI

/// TaskDetailFullscreen.svelte chrome with TaskDetailContent and TaskActivity.
// Web source: frontend/packages/ui/src/components/tasks/TaskDetailFullscreen.svelte
//             frontend/packages/ui/src/components/tasks/TaskDetailContent.svelte
//             frontend/packages/ui/src/components/tasks/TaskActivity.svelte
// Specification: specifications/features/tasks/specification.yml
// Assertions: tasks.detail.embed-responsive, tasks.activity.single-final-section
struct TaskDetailView: View {
    @ObservedObject var store: TasksWorkspaceStore
    let task: UserTaskItem
    var onOpenProject: (String) -> Void = { _ in }
    var onOpenChat: (String) -> Void = { _ in }
    var onReportIssue: () -> Void = {}

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @EnvironmentObject private var authManager: AuthManager
    @State private var title = ""
    @State private var description = ""
    @State private var tags = ""
    @State private var status: UserTaskStatus = .todo
    @State private var assignee: UserTaskAssigneeType = .user
    @State private var dueDate = Date()
    @State private var hasDueDate = false
    @State private var editing = false
    @State private var titleEditHovered = false
    @FocusState private var titleEditFocused: Bool
    @State private var activity: [UserTaskActivityEntry] = []
    @State private var dependencies: [UserTaskDependency] = []
    @State private var activityLoading = false
    @State private var comment = ""
    @State private var commentSending = false

    private var current: UserTaskItem { store.selectedTask ?? task }

    private var priorityLabel: String {
        switch max(0, min(4, current.priority)) {
        case 0: AppStrings.tasksPriorityNone
        case 1: AppStrings.tasksPriorityLow
        case 2: AppStrings.tasksPriorityMedium
        case 3: AppStrings.tasksPriorityHigh
        default: AppStrings.tasksPriorityUrgent
        }
    }

    private var createdByLabel: String {
        let seconds = max(0, Int(Date().timeIntervalSince1970) - current.record.createdAt)
        let created: String
        if seconds < 60 {
            created = AppStrings.tasksCreatedSecondsAgo
        } else if seconds < 3_600 {
            created = AppStrings.tasksCreatedMinutesAgo(seconds / 60)
        } else {
            let date = Date(timeIntervalSince1970: TimeInterval(current.record.createdAt))
                .formatted(.dateTime.month(.abbreviated).day().year().locale(Locale(identifier: "en_US")))
            created = AppStrings.tasksCreatedOn(date)
        }
        let creator = authManager.currentUser?.username.trimmingCharacters(in: .whitespacesAndNewlines)
        return AppStrings.tasksCreatedBy(created, creator: creator?.isEmpty == false ? creator! : AppStrings.tasksCreatorYou)
    }

    var body: some View {
            ScrollView {
                VStack(spacing: 0) {
                    header
                    VStack(alignment: .leading, spacing: 28) {
                    detailIntro
                    VStack(spacing: 14) {
                        statusPicker
                        assigneePicker
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: 22))
                    .overlay(RoundedRectangle(cornerRadius: 22).stroke(Color.grey20, lineWidth: 1))
                    section(AppStrings.tasksDescription, icon: "document") {
                        if editing {
                            TextField(AppStrings.tasksDescription, text: $description, axis: .vertical)
                                .lineLimit(3...10)
                        } else {
                            Text(current.description.isEmpty ? AppStrings.tasksNoDescription : current.description)
                                .foregroundStyle(current.description.isEmpty ? Color.fontSecondary : Color.fontPrimary)
                        }
                    }
                    if current.status == .blocked {
                        section(AppStrings.tasksBlockedReason, icon: "warning") {
                            Text(current.blockedReason.isEmpty ? AppStrings.tasksBlocked : current.blockedReason)
                        }
                        .background(Color.error.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
                    }
                    Group {
                        if horizontalSizeClass == .compact {
                            VStack(alignment: .leading, spacing: 28) { assigneeAndDue }
                        } else {
                            HStack(alignment: .top, spacing: 44) { assigneeAndDue }
                        }
                    }
                    section(AppStrings.tasksProjects, icon: "project") {
                        if current.linkedProjectIds.isEmpty {
                            Text(AppStrings.tasksNoProject).foregroundStyle(Color.fontSecondary)
                        } else {
                            ForEach(current.linkedProjectIds, id: \.self) { id in
                                Button(store.projectNames[id] ?? AppStrings.projects) { onOpenProject(id) }
                                    .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                                    .accessibilityIdentifier("task-detail-project-card")
                            }
                        }
                    }
                    section(AppStrings.tasksPlan, icon: "document") {
                        if let id = current.planId,
                           let plan = store.plans.first(where: { $0.id == id }) {
                            Button(plan.title) { store.openPlan(id) }
                                .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                                .accessibilityIdentifier("task-detail-plan-card")
                        } else {
                            Text(AppStrings.tasksNoPlan).foregroundStyle(Color.fontSecondary)
                        }
                    }
                    section(AppStrings.tasksDependencies, icon: "task") {
                        if dependencies.isEmpty {
                            Text(AppStrings.tasksNoDependencies).foregroundStyle(Color.fontSecondary)
                        } else {
                            ForEach(dependencies) { dependency in
                                Button {
                                    if dependency.targetKind == "task" { store.openTask(dependency.targetId) }
                                    else { store.openPlan(dependency.targetId) }
                                } label: {
                                    HStack {
                                        Text(dependency.targetId).lineLimit(1)
                                        Spacer()
                                        Icon(dependency.satisfied ? "check" : "warning", size: 14)
                                            .foregroundStyle(dependency.satisfied ? Color.chatRainbowGreen : Color.error)
                                    }
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    section(AppStrings.tasksTags, icon: "settings") {
                        if editing {
                            TextField(AppStrings.tasksTags, text: $tags)
                        } else if current.tags.isEmpty {
                            Text(AppStrings.tasksNoTags).foregroundStyle(Color.fontSecondary)
                        } else {
                            ScrollView(.horizontal) {
                                HStack(spacing: 6) {
                                    ForEach(current.tags, id: \.self) { tag in
                                        Text("#\(tag.replacingOccurrences(of: "#", with: ""))")
                                            .font(.omXs)
                                            .padding(.horizontal, 8).padding(.vertical, 4)
                                            .background(Color.grey20, in: Capsule())
                                    }
                                }
                            }
                            .scrollIndicators(.hidden)
                        }
                    }
                    section(AppStrings.tasksChat, icon: "chat") {
                        if let external = current.externalChat {
                            Text(external.title.isEmpty ? external.id : external.title)
                                .foregroundStyle(Color.fontPrimary)
                            Text(external.provider).font(.omXs).foregroundStyle(Color.fontSecondary)
                        } else if let id = current.primaryChatId {
                            Button(AppStrings.tasksOpenChat) { onOpenChat(id) }
                                .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                        } else {
                            Text(AppStrings.tasksNoChat).foregroundStyle(Color.fontSecondary)
                        }
                    }
                    activitySection
                    }
                    .padding(16)
                }
            }
            .background(Color.grey20)
            .task(id: task.id) { await loadRelated() }
            .accessibilityIdentifier("task-detail-content")
    }

    @ViewBuilder private var assigneeAndDue: some View {
        section(AppStrings.tasksAssignee, icon: "user") {
            Text(assigneeLabel)
        }
        section(AppStrings.tasksDue, icon: "calendar") {
            if editing {
                OMToggle(isOn: $hasDueDate, accessibilityIdentifier: "task-detail-due-toggle")
                if hasDueDate { DatePicker(AppStrings.tasksDue, selection: $dueDate, displayedComponents: .date) }
            } else {
                Text(current.dueAt.map { Date(timeIntervalSince1970: TimeInterval($0)).formatted(date: .abbreviated, time: .omitted) }
                     ?? AppStrings.tasksNoDue)
            }
        }
    }

    private var header: some View {
        ZStack {
            AppGradientBackground(appId: "tasks")
            HStack {
                Icon("task", size: 70).rotationEffect(.degrees(-22))
                Spacer()
                Icon("task", size: 70).rotationEffect(.degrees(22))
            }
            .foregroundStyle(.white.opacity(0.22))
            .offset(y: 65)
            .allowsHitTesting(false)
            VStack(spacing: 8) {
                Icon("task", size: 32)
                .foregroundStyle(.white)
                if editing {
                    TextField(AppStrings.tasksNew, text: $title)
                        .font(.omLg.weight(.bold))
                        .multilineTextAlignment(.center)
                } else {
                    Text(current.title)
                        .font(.omLg.weight(.bold))
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .accessibilityIdentifier("task-detail-title")
                }
                Text(createdByLabel)
                    .font(.omXs)
                    .foregroundStyle(.white.opacity(0.85))
                HStack(spacing: 8) {
                    Text(priorityLabel)
                        .padding(.horizontal, 11).padding(.vertical, 6)
                        .background(Color.error, in: Capsule())
                    Text(current.status.localizedTitle)
                        .padding(.horizontal, 11).padding(.vertical, 6)
                        .background(.white.opacity(0.22), in: Capsule())
                }
                .font(.omXs.weight(.bold))
            }
            .foregroundStyle(.white)
            .frame(maxWidth: 350)
            .padding(.horizontal, 20)
            VStack {
                HStack {
                    Button(action: onReportIssue) {
                        Icon("bug", size: 20)
                            .foregroundStyle(.white)
                            .frame(width: 40, height: 40)
                            .background(.white.opacity(0.2), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.reportIssue)
                    .accessibilityIdentifier("task-detail-report-issue")
                    Spacer()
                    Button { store.closeDetail() } label: {
                        Icon("close", size: 19)
                            .foregroundStyle(.white)
                            .frame(width: 40, height: 40)
                            .background(.white.opacity(0.2), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.close)
                    .accessibilityIdentifier("task-detail-minimize")
                }
                Spacer()
            }
            .padding(16)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 190)
        // UnifiedEmbedFullscreen.svelte rendered overlay radius: 17px.
        .clipShape(.rect(bottomLeadingRadius: 17, bottomTrailingRadius: 17))
        .shadow(color: .black.opacity(0.22), radius: 18, y: 10)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("task-detail-fullscreen")
    }

    private var detailIntro: some View {
        VStack(alignment: .leading, spacing: 16) {
            if editing {
                HStack(alignment: .top, spacing: 12) {
                    TextField(AppStrings.tasksNew, text: $title, axis: .vertical)
                        .lineLimit(1...3)
                        .font(.omH3.weight(.bold))
                    Button(AppStrings.save) { save() }
                        .disabled(store.isSaving)
                        .accessibilityIdentifier("task-detail-edit")
                }
            } else {
                ZStack(alignment: .trailing) {
                    Button {
                        hydrateEditState()
                        editing = true
                    } label: {
                        Text(current.title)
                            .font(.omH3.weight(.bold))
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity, alignment: .center)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("task-detail-title")

                    Button {
                        hydrateEditState()
                        editing = true
                    } label: {
                        Icon("lucide-pencil", size: 18)
                            .foregroundStyle(Color.fontPrimary)
                            .frame(width: horizontalSizeClass == .compact ? 32 : 36,
                                   height: horizontalSizeClass == .compact ? 32 : 36)
                            .background(Color.grey100.opacity(0.22), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .opacity(titleEditHovered || titleEditFocused ? 1 : 0)
                    .focused($titleEditFocused)
                    .accessibilityLabel(AppStrings.edit)
                    .accessibilityIdentifier("task-detail-edit")
                }
                .onHover { titleEditHovered = $0 }
            }
            if editing {
                TextField(AppStrings.tasksDescription, text: $description, axis: .vertical)
                    .lineLimit(2...5)
            } else {
                Text(current.description.isEmpty ? AppStrings.tasksNoDescription : current.description)
                    .font(.omSmall)
                    .foregroundStyle(current.description.isEmpty ? Color.fontSecondary : Color.fontPrimary)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
            Text(createdByLabel)
                .font(.omXs.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
        }
        .padding(.horizontal, .spacing4)
        .padding(.top, .spacing6)
        .padding(.bottom, 12)
    }

    private var statusPicker: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(AppStrings.tasksStatus.uppercased()).font(.omXs.weight(.bold)).foregroundStyle(Color.fontSecondary)
            Menu {
                ForEach(UserTaskStatus.allCases) { value in
                    Button(value.localizedTitle) {
                        status = value
                        if !editing && value != current.status {
                            Task { await store.moveTask(current, to: value) }
                        }
                    }
                }
            } label: {
                pickerFace((editing ? status : current.status).localizedTitle)
            }
            .buttonStyle(.plain)
            .disabled(store.isSaving)
            .accessibilityLabel(AppStrings.tasksStatus)
            .accessibilityValue((editing ? status : current.status).localizedTitle)
            .accessibilityIdentifier("task-detail-status-select")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var assigneePicker: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(AppStrings.tasksAssignee.uppercased()).font(.omXs.weight(.bold)).foregroundStyle(Color.fontSecondary)
            Menu {
                Button(AppStrings.tasksMe) { selectAssignee(.user) }
                Button(AppStrings.tasksUnassigned) { selectAssignee(.unassigned) }
                Button(AppStrings.openMatesName) { selectAssignee(.openmates) }
            } label: {
                pickerFace(assigneeTitle(editing ? assignee : current.assigneeType))
            }
            .buttonStyle(.plain)
            .disabled(store.isSaving)
            .accessibilityLabel(AppStrings.tasksAssignee)
            .accessibilityValue(assigneeTitle(editing ? assignee : current.assigneeType))
            .accessibilityIdentifier("task-detail-assignee-select")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func pickerFace(_ title: String) -> some View {
        HStack(spacing: 8) {
            Text(title).font(.omP.weight(.bold))
            Spacer(minLength: 8)
            Icon("lucide-chevron-down", size: 16)
        }
        .foregroundStyle(Color.fontPrimary)
        .padding(.horizontal, 14)
        .frame(maxWidth: .infinity, minHeight: 46, alignment: .leading)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.grey25, lineWidth: 1))
    }

    private func assigneeTitle(_ value: UserTaskAssigneeType) -> String {
        switch value {
        case .user: AppStrings.tasksMe
        case .unassigned: AppStrings.tasksUnassigned
        case .openmates: AppStrings.openMatesName
        case .externalAI: current.assigneeIdentity?.title ?? AppStrings.openMatesName
        }
    }

    private func selectAssignee(_ value: UserTaskAssigneeType) {
        assignee = value
        if !editing && value != current.assigneeType {
            Task { await store.saveTask(current, patch: UserTaskUpdateInput(assigneeType: value)) }
        }
    }

    private func section<Content: View>(_ title: String, icon: String, settingsHeading: Bool = true,
                                        @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if settingsHeading {
                OMSettingsSectionHeading(title: title, icon: icon)
            } else {
                HStack(spacing: .spacing4) {
                    Icon(icon, size: 22).foregroundStyle(Color.fontSecondary)
                    Text(title).font(.omH3.weight(.bold))
                }
                .padding(.vertical, .spacing8)
            }
            content().font(.omP)
                .padding(.horizontal, .spacing4)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var assigneeLabel: String {
        switch current.assigneeType {
        case .user: AppStrings.tasksMe
        case .unassigned: AppStrings.tasksUnassigned
        case .openmates: AppStrings.openMatesName
        case .externalAI: current.assigneeIdentity?.title ?? AppStrings.openMatesName
        }
    }

    private var activitySection: some View {
        section(AppStrings.tasksActivity, icon: "chat", settingsHeading: false) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    TextField(AppStrings.tasksCommentPlaceholder, text: $comment, axis: .vertical)
                        .lineLimit(2...5)
                        .accessibilityIdentifier("task-activity-input")
                    Button {
                        let text = comment
                        comment = ""
                        commentSending = true
                        Task {
                            defer { commentSending = false }
                            if let entry = try? await store.addTaskComment(text, task: current) { activity.append(entry) }
                        }
                    } label: { Icon("up", size: 18) }
                        .disabled(comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || commentSending)
                        .accessibilityLabel(AppStrings.tasksSend)
                        .accessibilityIdentifier("task-activity-submit")
                }
                if activityLoading { ProgressView() }
                else if activity.isEmpty { Text(AppStrings.tasksNoActivity).foregroundStyle(Color.fontSecondary) }
                else {
                    ForEach(activity) { entry in
                        HStack(alignment: .top, spacing: 10) {
                            Circle().fill(entry.record.actorType == "user" ? Color.buttonPrimary : Color.chatRainbowPurple)
                                .frame(width: 24, height: 24)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(entry.record.actorDisplayName ?? entry.record.actorIdentity?.title ?? AppStrings.tasksActivity)
                                    .font(.omXs).fontWeight(.bold)
                                Text(entry.message ?? entry.record.eventType)
                                    .font(.omSmall)
                                Text(Date(timeIntervalSince1970: TimeInterval(entry.record.createdAt))
                                    .formatted(date: .abbreviated, time: .shortened))
                                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                            }
                        }
                        .padding(10)
                        .background(Color.grey10, in: RoundedRectangle(cornerRadius: 10))
                    }
                }
            }
        }
        .accessibilityIdentifier("task-activity")
    }

    private func hydrateEditState() {
        title = current.title
        description = current.description
        tags = current.tags.joined(separator: ", ")
        status = current.status
        assignee = current.assigneeType
        if let timestamp = current.dueAt {
            hasDueDate = true
            dueDate = Date(timeIntervalSince1970: TimeInterval(timestamp))
        } else { hasDueDate = false }
    }

    private func save() {
        let patch = UserTaskUpdateInput(title: title, description: description,
                                        tags: tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) },
                                        status: status, assigneeType: assignee,
                                        dueAt: hasDueDate ? Int(dueDate.timeIntervalSince1970) : nil,
                                        clearDueAt: !hasDueDate && current.dueAt != nil)
        editing = false
        Task { await store.saveTask(current, patch: patch) }
    }

    private func loadRelated() async {
        hydrateEditState()
        activityLoading = true
        async let loadedActivity = store.taskActivity(current)
        async let loadedDependencies = store.taskDependencies(current)
        activity = (try? await loadedActivity) ?? []
        dependencies = (try? await loadedDependencies) ?? []
        activityLoading = false
    }
}
