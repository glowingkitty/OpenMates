// Compact Watch Task reader and encrypted draft editor.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.tasks.edit-private, apple-watch.lists.read-only-private
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/tasks/TaskDetailContent.svelte
//         frontend/packages/ui/src/components/workspace/WorkspaceDetailHeader.svelte
// CSS: those components' task-controls and editable-field classes.
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// Native difference: Watch uses one compact draft and explicit Save/Cancel,
// with dedicated compact choice pages rather than a desktop select popup.

import SwiftUI
#if DEBUG
import CryptoKit
#endif

@MainActor
private enum WatchTaskCopy {
    static var edit: String { WatchLocalization.text("common.edit") }
    static var save: String { WatchLocalization.text("common.save") }
    static var cancel: String { WatchLocalization.text("common.cancel") }
    static var title: String { WatchLocalization.text("watch.task.title") }
    static var description: String { WatchLocalization.text("watch.task.description") }
    static var status: String { WatchLocalization.text("common.status") }
    static var priority: String { WatchLocalization.text("watch.task.priority") }
    static var failed: String { WatchLocalization.text("watch.task.save_failed") }
    static var accountChanged: String { WatchLocalization.text("watch.task.account_changed") }

    static func group(_ group: WatchTaskGroup) -> String {
        switch group {
        case .backlog: WatchLocalization.text("watch.hub.backlog")
        case .todo: WatchLocalization.text("watch.hub.todo")
        case .inProgress: WatchLocalization.text("watch.hub.in_progress")
        case .blocked: WatchLocalization.text("watch.hub.blocked")
        case .done: WatchLocalization.text("watch.hub.done")
        }
    }

    static func priority(_ value: Int) -> String {
        let keys = ["none", "low", "medium", "high", "urgent"]
        return WatchLocalization.text("tasks.detail.priority_\(keys[min(4, max(0, value))])")
    }
}

struct WatchTaskDetailView: View {
    @ObservedObject private var service: WatchHubDataService
    @State private var item: WatchTaskListItem
    @State private var draft: WatchTaskDraft
    @State private var isEditing = false
    @State private var expandedChoice: String?
    @State private var failure: WatchTaskEditingError?
    private let onClose: () -> Void
    private let onOpenItem: (WatchItemOpenRequest) -> Void
    private let onSaved: ((WatchTaskListItem) -> Void)?

    init(service: WatchHubDataService, item: WatchTaskListItem,
         onClose: @escaping () -> Void, onOpenItem: @escaping (WatchItemOpenRequest) -> Void,
         onSaved: ((WatchTaskListItem) -> Void)? = nil) {
        self.service = service
        _item = State(initialValue: item)
        _draft = State(initialValue: WatchTaskDraft(item: item))
        self.onClose = onClose
        self.onOpenItem = onOpenItem
        self.onSaved = onSaved
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: .spacing2) {
                Button {
                    if expandedChoice != nil { expandedChoice = nil }
                    else if isEditing { cancel() }
                    else { onClose() }
                } label: {
                    HStack(spacing: .spacing1) {
                        Icon("chevron-left", size: .spacing4)
                        Text(isEditing && expandedChoice == nil ? WatchTaskCopy.cancel : WatchStrings.back)
                    }
                    .font(.omXs).padding(.vertical, .spacing3)
                }
                .buttonStyle(.plain)
                .disabled(service.isSavingTask)
                .accessibilityIdentifier("watch-task-detail-back")
                Spacer(minLength: 0)
                if let expandedChoice {
                    Text(expandedChoice == "status" ? WatchTaskCopy.status : WatchTaskCopy.priority)
                        .font(.omMicro).lineLimit(1).minimumScaleFactor(0.8)
                }
                if !isEditing && service.canEditTask(item) {
                    Button {
                        draft = WatchTaskDraft(item: item)
                        failure = nil
                        isEditing = true
                    } label: {
                        Text(WatchTaskCopy.edit).font(.omXs.weight(.semibold))
                            .padding(.vertical, .spacing3)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-task-detail-edit")
                }
            }
            .padding(.horizontal, .spacing3)
            ScrollView(.vertical) {
                VStack(alignment: .leading, spacing: .spacing4) {
                    if isEditing { editor }
                    else { reader }
                }
                .padding(.horizontal, .spacing3)
                .padding(.bottom, .spacing6)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // Reset only the scroll surface on editor-page changes. The draft
            // stays in this parent view, including when returning from choices.
            .id(isEditing ? (expandedChoice ?? "fields") : "reader")
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityIdentifier(isEditing ? "watch-task-editor-scroll" : "watch-task-detail-scroll")
            if isEditing && expandedChoice == nil { saveControls }
        }
        .foregroundStyle(WatchWorkspacePalette.foreground)
        .background(WatchWorkspacePalette.background)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(isEditing ? "watch-task-editor" : "watch-task-detail")
    }

    private var reader: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(item.title).font(.omSmall.weight(.bold))
                .accessibilityIdentifier("watch-task-detail-title")
            Text(WatchTaskCopy.group(item.group)).font(.omXs)
                .foregroundStyle(accent(item.group))
                .accessibilityIdentifier("watch-task-detail-status")
            Text(WatchTaskCopy.priority(item.priority)).font(.omMicro).foregroundStyle(WatchWorkspacePalette.foreground)
                .accessibilityIdentifier("watch-task-detail-priority")
            detail(WatchTaskCopy.description, value: item.description, id: "description")
            detail(WatchLocalization.text("watch.task.context"), value: item.latestInstruction, id: "context")
            detail(WatchLocalization.text("watch.task.progress"), value: item.activitySummary, id: "progress")
            detail(WatchLocalization.text("tasks.blocked_heading"), value: item.blockedReason, id: "blocked-reason")
            Button { onOpenItem(item.openRequest) } label: {
                Text(WatchLocalization.text("watch.hub.open_on_phone"))
                    .font(.omXs).frame(maxWidth: .infinity).padding(.spacing3)
                    .background(Color.buttonPrimary, in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("watch-task-detail-open-on-phone")
        }
    }

    @ViewBuilder private var editor: some View {
        if expandedChoice == "status" {
            VStack(alignment: .leading, spacing: .spacing2) {
                ForEach(WatchTaskGroup.allCases) { group in
                    option(WatchTaskCopy.group(group), selected: draft.group == group,
                           id: "watch-task-status-\(group.status)") {
                        draft.group = group
                        expandedChoice = nil
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("watch-task-status-choices")
        } else if expandedChoice == "priority" {
            VStack(alignment: .leading, spacing: .spacing2) {
                ForEach(0...4, id: \.self) { priority in
                    option(WatchTaskCopy.priority(priority), selected: draft.priority == priority,
                           id: "watch-task-priority-\(priority)") {
                        draft.priority = priority
                        expandedChoice = nil
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("watch-task-priority-choices")
        } else {
            // Put frequent metadata edits within the first Watch viewport.
            // Text input remains real OS-owned input below these controls.
            VStack(alignment: .leading, spacing: .spacing2) {
                choice(WatchTaskCopy.status, value: WatchTaskCopy.group(draft.group), id: "status")
                choice(WatchTaskCopy.priority, value: WatchTaskCopy.priority(draft.priority), id: "priority")
                fieldLabel(WatchTaskCopy.title)
                TextField(WatchTaskCopy.title, text: $draft.title)
                    .font(.omXs).textFieldStyle(.plain).padding(.spacing3)
                    .background(WatchWorkspacePalette.surface, in: RoundedRectangle(cornerRadius: .radius4))
                    .accessibilityIdentifier("watch-task-title-input")
                fieldLabel(WatchTaskCopy.description)
                TextField(WatchTaskCopy.description, text: $draft.description, axis: .vertical)
                    .lineLimit(1...3).font(.omXs).textFieldStyle(.plain).padding(.spacing3)
                    .background(WatchWorkspacePalette.surface, in: RoundedRectangle(cornerRadius: .radius4))
                    .accessibilityIdentifier("watch-task-description-input")
            }
            .disabled(service.isSavingTask)
        }
    }

    private var saveControls: some View {
        VStack(spacing: .spacing2) {
            if let failure {
                Text(failure == .accountChanged ? WatchTaskCopy.accountChanged : WatchTaskCopy.failed)
                    .font(.omMicro).foregroundStyle(Color.error)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("watch-task-save-error")
            }
            HStack(spacing: .spacing2) {
                Button(action: cancel) {
                    Text(WatchTaskCopy.cancel).font(.omXs).frame(maxWidth: .infinity)
                        .padding(.vertical, .spacing3)
                        .background(WatchWorkspacePalette.surface, in: Capsule())
                }
                .buttonStyle(.plain).disabled(service.isSavingTask)
                .accessibilityIdentifier("watch-task-edit-cancel")
                Button {
                    Task { await save() }
                } label: {
                    Group {
                        if service.isSavingTask { ProgressView().tint(WatchWorkspacePalette.foreground) }
                        else { Text(WatchTaskCopy.save).font(.omXs.weight(.semibold)) }
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, .spacing3)
                    .background(Color.buttonPrimary, in: Capsule())
                }
                .buttonStyle(.plain)
                .disabled(service.isSavingTask || !draft.isValid || !draft.hasChanges(from: item) || !service.canEditTask(item))
                .opacity(draft.isValid && draft.hasChanges(from: item) ? 1 : 0.6)
                .accessibilityIdentifier("watch-task-edit-save")
            }
        }
        .padding(.spacing3)
        .background(WatchWorkspacePalette.background)
    }

    private func choice(_ title: String, value: String, id: String) -> some View {
        Button {
            expandedChoice = expandedChoice == id ? nil : id
        } label: {
            VStack(alignment: .leading, spacing: .spacing1) {
                fieldLabel(title)
                HStack {
                    Text(value).font(.omXs.weight(.semibold))
                    Spacer(minLength: 0)
                    Icon("chevron-down", size: .spacing4)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading).padding(.spacing3)
            .background(WatchWorkspacePalette.surface, in: RoundedRectangle(cornerRadius: .radius4))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("watch-task-edit-\(id)")
    }

    private func option(_ title: String, selected: Bool, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                Text(title).font(.omXs)
                Spacer(minLength: 0)
                if selected { Icon("check", size: .spacing4) }
            }
            .padding(.spacing3).frame(maxWidth: .infinity)
            .background(selected ? Color.buttonPrimary : WatchWorkspacePalette.surface,
                        in: RoundedRectangle(cornerRadius: .radius4))
        }
        .buttonStyle(.plain).accessibilityIdentifier(id)
    }

    private func fieldLabel(_ text: String) -> some View {
        Text(text).font(.omMicro).foregroundStyle(WatchWorkspacePalette.foreground)
    }

    @ViewBuilder private func detail(_ title: String, value: String, id: String) -> some View {
        if !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            VStack(alignment: .leading, spacing: .spacing1) {
                fieldLabel(title)
                Text(value).font(.omXs).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("watch-task-detail-\(id)")
            }
        }
    }

    private func accent(_ group: WatchTaskGroup) -> Color {
        switch group {
        case .backlog: .chatRainbowPurple
        case .todo: .chatRainbowCyan
        case .inProgress: .warning
        case .blocked: .error
        case .done: .chatRainbowGreen
        }
    }

    private func cancel() {
        guard !service.isSavingTask else { return }
        draft = WatchTaskDraft(item: item)
        failure = nil
        expandedChoice = nil
        isEditing = false
    }

    @MainActor private func save() async {
        guard draft.isValid, draft.hasChanges(from: item), !service.isSavingTask else { return }
        failure = nil
        do {
            let returned = try await service.saveTask(item, draft: draft)
            item = returned
            draft = WatchTaskDraft(item: returned)
            isEditing = false
            expandedChoice = nil
            onSaved?(returned)
        } catch {
            failure = (error as? WatchTaskEditingError) ?? .invalidResponse
        }
    }
}

#if DEBUG
/// Network-free launch fixture. It uses real task-key encryption, the production
/// service and editor, and a synthetic versioned server response.
struct WatchTaskEditingUITestFixtureView: View {
    let failsSave: Bool
    let workflowProjection: Bool
    @State private var fixture: WatchTaskEditingFixture?
    @State private var isClosed = false
    @State private var requestCount = 0

    init(failsSave: Bool = false, workflowProjection: Bool = false) {
        self.failsSave = failsSave
        self.workflowProjection = workflowProjection
    }

    var body: some View {
        Group {
            if let fixture {
                if !isClosed {
                    WatchTaskDetailView(service: fixture.service, item: fixture.item,
                        onClose: { isClosed = true }, onOpenItem: { _ in })
                        .onReceive(fixture.$requestCount) { requestCount = $0 }
                } else {
                    ScrollView {
                        ForEach(fixture.service.tasks) { item in
                            VStack(alignment: .leading, spacing: .spacing2) {
                                Text(WatchTaskCopy.group(item.group)).font(.omXs)
                                    .accessibilityIdentifier("watch-task-fixture-returned-group")
                                Text(item.title).font(.omXs)
                                    .accessibilityIdentifier("watch-task-fixture-returned-title")
                            }
                            .padding(.spacing3)
                        }
                    }
                }
            } else { ProgressView() }
        }
        .overlay(alignment: .bottom) {
            if fixture != nil {
                Text("\(requestCount)").font(.omMicro).foregroundStyle(Color.clear)
                    .accessibilityIdentifier("watch-task-fixture-request-count")
            }
        }
        .task {
            guard fixture == nil else { return }
            fixture = try? await WatchTaskEditingFixture.make(failsSave: failsSave, workflowProjection: workflowProjection)
        }
    }
}

@MainActor
private final class WatchTaskEditingFixture: ObservableObject {
    @Published var requestCount = 0
    private(set) var service: WatchHubDataService!
    private(set) var item: WatchTaskListItem!
    private var wire: [String: Any] = [:]
    private let masterKey = SymmetricKey(size: .bits256)
    private let taskKey = SymmetricKey(size: .bits256)

    static func make(failsSave: Bool, workflowProjection: Bool) async throws -> WatchTaskEditingFixture {
        let fixture = WatchTaskEditingFixture()
        fixture.wire = ["task_id": "watch-ui-edit-task", "source": "user", "status": "todo",
                        "priority": 0, "position": 0, "version": 1, "updated_at": 1,
                        "encrypted_task_key": try await CryptoManager.shared.wrapChatKey(fixture.taskKey, masterKey: fixture.masterKey),
                        "encrypted_title": try await CryptoManager.shared.encryptContent("Watch fixture task", key: fixture.taskKey),
                        "encrypted_description": try await CryptoManager.shared.encryptContent("Keep my draft on failure", key: fixture.taskKey)]
        if workflowProjection {
            fixture.wire["source"] = "workflow_run"
            fixture.wire["workflow_id"] = "watch-ui-workflow"
            fixture.wire["title"] = "Read-only workflow task"
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let record = try decoder.decode(WatchTaskRecord.self, from: JSONSerialization.data(withJSONObject: fixture.wire))
        guard let item = await WatchHubDataService.openTask(record, masterKey: fixture.masterKey) else {
            throw WatchTaskEditingError.invalidResponse
        }
        fixture.item = item
        fixture.service = WatchHubDataService(userId: "watch-ui-edit-account", fixtureTasks: [item],
            currentAccountID: { "watch-ui-edit-account" }, taskDependencies: WatchTaskDependencies(
                request: { method, _, body, context in
                    try context.check()
                    guard method == .patch, let body,
                          let patch = try JSONSerialization.jsonObject(with: body) as? [String: Any] else {
                        throw WatchTaskEditingError.invalidResponse
                    }
                    fixture.requestCount += 1
                    if failsSave { throw URLError(.notConnectedToInternet) }
                    var returned = fixture.wire
                    returned.merge(patch) { _, replacement in replacement }
                    returned["version"] = 2
                    return try JSONSerialization.data(withJSONObject: ["task": returned])
                }, masterKey: { _ in fixture.masterKey }))
        return fixture
    }
}
#endif
