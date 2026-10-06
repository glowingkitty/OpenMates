// Native workflow graph and focused step editor.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/workflows/WorkflowGraphRenderer.svelte
//          frontend/packages/ui/src/components/workflows/WorkflowGraphRenderer.preview.ts
// CSS:     WorkflowGraphRenderer.svelte .graph-panel, .node-stack,
//          .node-summary, .run-status, .branch-group, .editor
//          WorkflowEditorHeader.svelte .editor-header, .header-control
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.mvp.steps, workflows.control.check,
//             workflows.control.typed-data, workflows.execution.lifecycle-visible
// Specification: specifications/features/workflows-ui/specification.yml
// Assertions: workflows-ui.template.centered-in-place-editor,
//             workflows-ui.responsive-accessible-reachable

import SwiftUI

struct WorkflowSkillChoice: Identifiable {
    let id: String
    let appId: String
    let skillId: String
    let title: String
    var inputSchema: [String: AnyCodable] = [:]
    var outputSchema: [String: AnyCodable] = [:]
    var fixedCreditCost: Int?
    var testAllowed = true
}

private struct WorkflowOutputChoice: Identifiable {
    let id: String
    let label: String
    let type: String
}

private enum WorkflowPickerStage {
    case trigger, action, app, skill
}

// Emitted by the mounted expanded panel after layout. The parent owns scrolling;
// keeping the scroll ID on each node preserves graph identity across expansion.
struct WorkflowEditorScrollTarget: Equatable {
    let id: String
    let bounds: CGRect

    static let coordinateSpace = "workflow-editor-viewport"
    static func nodeID(_ nodeId: String) -> String { "workflow-node-\(nodeId)" }
}

struct WorkflowEditorScrollTargetKey: PreferenceKey {
    static let defaultValue: WorkflowEditorScrollTarget? = nil
    static func reduce(value: inout WorkflowEditorScrollTarget?, nextValue: () -> WorkflowEditorScrollTarget?) {
        if let next = nextValue() { value = next }
    }
}

// Workflow inputs use the graph renderer's 40px, .8rem field surface;
// settings text-field pills have different dimensions.
struct WorkflowEditorTextFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration
            .font(.omP.weight(.medium))
            .padding(.horizontal, 11.2)
            .frame(minHeight: 40)
            .background(LinearGradient(colors: [.grey10, .grey20], startPoint: .topLeading, endPoint: .bottomTrailing))
            .clipShape(RoundedRectangle(cornerRadius: 12.8))
            .overlay(RoundedRectangle(cornerRadius: 12.8).stroke(Color.grey25, lineWidth: 1))
            .shadow(color: .black.opacity(0.1), radius: 4, y: 4)
    }
}

struct WorkflowGraphView: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var nodeExpansion
    @ObservedObject private var offlineStore = OfflineStore.shared
    @ObservedObject private var teamContext = TeamWorkspaceContext.shared
    let graph: WorkflowGraph
    var readOnly = false
    var nodeRuns: [WorkflowNodeRun] = []
    var executionStatus: String? = nil
    var skills: [WorkflowSkillChoice] = []
    var workflowId: String? = nil
    var accountId: String? = nil
    var chatChoices: [WorkflowChatChoice] = []
    var onSave: ((WorkflowGraph) async -> Bool)? = nil
    var previewAskAIVerdict: WorkflowAskAIVerdict? = nil

    @StateObject private var stepTest = WorkflowStepTestController()
    @StateObject private var askHints = WorkflowAskAIHintsController()

    @State private var editingNodeId: String?
    @State private var draftTitle = ""
    @State private var draftConfig: [String: AnyCodable] = [:]
    @State private var stepPickerAfterId: String?
    @State private var stepPickerBranch: String?
    @State private var stepPickerOpen = false
    @State private var pickerStage: WorkflowPickerStage = .action
    @State private var selectedAppId = ""
    @State private var draftNewNode: WorkflowNode?
    @State private var saving = false
    @State private var editError: String?
    @State private var deleteArmed = false
    @State private var showOutputFields = false
    @State private var selectedCheckSourceId: String?
    @State private var choosingChat = false
    @ObservedObject private var modelCatalog = NativeModelCatalogRuntime.shared
    @State private var modelDetails: NativeModelCatalog.Model?

    private func outputValues(for node: WorkflowNode) -> [String: AnyCodable]? {
        if let values = stepTest.outputsByNode[node.id] { return values }
        #if DEBUG
        // Rendering fixture only. It never executes Test or bypasses API scope capture.
        if ProcessInfo.processInfo.arguments.contains("--ui-test-workflows-fixture"),
           ProcessInfo.processInfo.arguments.contains("--ui-test-workflow-event-output-fixture"), node.id == "news" {
            let events: [[String: String]] = (1...7).map { index in
                ["type": "event_result", "title": "Synthetic event \(index)",
                 "description": "Event \(index) output details",
                 "date_start": "2026-10-0\(index)T18:00:00Z",
                 "venue_city": "Fixture city \(index)"]
            }
            return ["results": AnyCodable(events), "result_count": AnyCodable(events.count)]
        }
        if ProcessInfo.processInfo.arguments.contains("--ui-test-workflows-fixture"),
           ProcessInfo.processInfo.arguments.contains("--ui-test-workflow-output-fixture"), node.id == "news" {
            return ["results": AnyCodable([
                ["title": "First synthetic article", "description": "First synthetic result", "url": "https://example.invalid/first"],
                ["title": "Second synthetic article", "description": "Second synthetic result", "url": "https://example.invalid/second"]
            ]), "result_count": AnyCodable(2)]
        }
        #endif
        return nil
    }

    private var editorHorizontalPadding: CGFloat { horizontalSizeClass == .compact ? .spacing6 : .spacing12 }

    private var visibleNodes: [WorkflowNode] {
        let incoming = Set(graph.edges.map(\.to))
        let start = graph.nodes.first(where: { $0.id == graph.triggerNodeId })
            ?? graph.nodes.first(where: { !incoming.contains($0.id) && $0.type != .end })
        guard let start else { return [] }
        return chain(from: start.id)
    }

    private func nextId(after nodeId: String, branch: String? = nil) -> String? {
        graph.edges.first { $0.from == nodeId && ($0.branch ?? "") == (branch ?? "") }?.to
    }

    private func chain(from startId: String?, stoppingAt stopId: String? = nil) -> [WorkflowNode] {
        var result: [WorkflowNode] = []
        var seen = Set<String>()
        var current = startId
        while let id = current, id != stopId, seen.insert(id).inserted,
              let node = graph.nodes.first(where: { $0.id == id }), node.type != .end {
            result.append(node)
            current = nextId(after: id)
        }
        return result
    }

    var body: some View {
        VStack(spacing: 0) {
            if visibleNodes.isEmpty {
                continuation(after: nil)
            } else {
                ForEach(visibleNodes) { node in
                    step(node)
                    if node.type == .decision || node.type.rawValue == "check" {
                        branchControls(after: node)
                    } else if node.id != visibleNodes.last?.id {
                        Text(AppStrings.workflowBuilder(.then))
                            .font(.omP.weight(.semibold))
                            .foregroundStyle(Color.fontSecondary)
                            .padding(.vertical, .spacing4)
                    }
                }
                if !readOnly {
                    Text(AppStrings.workflowBuilder(.then))
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.vertical, .spacing4)
                    continuation(after: visibleNodes.last?.id)
                }
            }
        }
        .frame(maxWidth: 835.2) // Web .graph-panel final width: 52.2rem.
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing8)
        .frame(maxWidth: .infinity, alignment: .center)
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-node-stack")
        // Web node view transitions share the card's frame in both dimensions
        // over .3s with cubic-bezier(.32, 0, .2, 1).
        .animation(reduceMotion ? nil : .timingCurve(0.32, 0, 0.2, 1, duration: 0.3), value: editingNodeId)
        .transaction { transaction in
            if reduceMotion { transaction.animation = nil; transaction.disablesAnimations = true }
        }
        .task(id: "\(workflowId ?? "")|\(accountId ?? "")|\(offlineStore.scopeGeneration)|\(teamContext.contextEpoch)") {
            stepTest.reset(accountId: accountId)
            askHints.reset(accountId: accountId)
        }
        .onChange(of: teamContext.contextEpoch) { _, _ in
            editingNodeId = nil
            draftNewNode = nil
            draftConfig = [:]
            selectedCheckSourceId = nil
            modelDetails = nil
            askHints.reset(accountId: nil)
        }
        .onDisappear { askHints.reset(accountId: nil) }
    }

    @ViewBuilder
    private func step(_ node: WorkflowNode) -> some View {
        VStack(spacing: 0) {
            if editingNodeId != node.id || readOnly {
            // Web startPointerDrag accepts mouse input only. Touch cards open
            // their editor; reordering uses its explicit move controls. A UIKit
            // drag interaction on this ancestor can consume that touch even
            // when the activation Button is a separate child.
            VStack(spacing: 0) {
            Button {
                if editingNodeId == node.id {
                    editingNodeId = nil
                } else {
                    editingNodeId = node.id
                    draftTitle = node.title ?? ""
                    draftConfig = node.config
                    stepPickerOpen = false
                    deleteArmed = false
                    showOutputFields = false
                    choosingChat = false
                    selectedCheckSourceId = nil
                    modelDetails = nil
                    askHints.reset(accountId: accountId)
                    if isAskAI(node) {
                        scheduleAskHints(for: node, instruction: askInstruction)
                    }
                }
            } label: {
                WorkflowStepSummary(node: node, run: nodeRuns.first { $0.nodeId == node.id }, graph: graph, skills: skills, executionStatus: executionStatus)
                    .frame(maxWidth: editingNodeId == node.id ? 672 : 336)
                    // The entire rendered card is the activation target.
                    .contentShape(.interaction, RoundedRectangle(cornerRadius: .radius7))
            }
            .buttonStyle(.plain)
            .matchedGeometryEffect(id: node.id, in: nodeExpansion, properties: .frame, anchor: .top)
            .transition(.opacity)
            .accessibilityIdentifier(isAskAI(node) ? "workflow-ask-ai-node" : "workflow-node-summary")
            .accessibilityValue(editingNodeId == node.id ? "expanded" : "collapsed")
            }
            #if os(macOS)
            .draggable(node.id)
            #endif
            }

            if editingNodeId == node.id {
                if readOnly {
                    VStack(alignment: .leading, spacing: .spacing4) {
                        Text(AppStrings.workflowBuilder(.input))
                            .font(.omP.weight(.semibold))
                        WorkflowValueView(value: node.config.mapValues(\.value),
                                          appId: node.config["app_id"]?.value as? String ?? "")
                        if let run = nodeRuns.first(where: { $0.nodeId == node.id }) {
                            Text(AppStrings.workflowBuilder(.output))
                                .font(.omP.weight(.semibold))
                            WorkflowValueView(value: run.outputSummary.mapValues(\.value),
                                              appId: node.config["app_id"]?.value as? String ?? "")
                        }
                    }
                    .padding(.spacing5)
                    .frame(maxWidth: 672, alignment: .leading)
                    .background(Color.grey10)
                } else {
                    editor(for: node)
                        .matchedGeometryEffect(id: node.id, in: nodeExpansion, properties: .frame, anchor: .top)
                        .transition(.opacity)
                }
            }
        }
        .frame(maxWidth: editingNodeId == node.id && !readOnly ? 772.8 : .infinity)
        .id(WorkflowEditorScrollTarget.nodeID(node.id))
        .dropDestination(for: String.self) { items, _ in
            guard !readOnly, let sourceId = items.first,
                  let next = WorkflowGraphReordering.moveAfter(graph, sourceId: sourceId, afterId: node.id)
            else { return false }
            Task { await persistReorder(next) }
            return true
        }
        .accessibilityElement(children: .contain)
        // The outer node is the actual panel accessibility boundary. A nested
        // expanded identifier is flattened into this parent by SwiftUI.
        .accessibilityIdentifier(editingNodeId == node.id && !readOnly ? "workflow-node-expanded" : "workflow-node-card")
    }

    @ViewBuilder
    private func editor(for node: WorkflowNode) -> some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            editorHeader(for: node)
                .padding(.horizontal, -editorHorizontalPadding)


            if node.type != .sendChatMessage && node.type != .createChatReport && node.type != .scheduleTrigger && node.type != .appSkillAction && node.type != .check && node.type != .decision && !choosingChat {
                TextField(AppStrings.workflowBuilder(.workflow_name), text: $draftTitle)
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibilityIdentifier("workflow-node-title-input")
            }

            if node.type == .scheduleTrigger {
                scheduleFields
            } else if node.type == .appSkillAction {
                appSkillFields(for: node)
            } else if node.type == .decision || node.type.rawValue == "check" {
                checkFields(for: node)
            } else if node.type.rawValue == "send_chat_message" || node.type == .createChatReport {
                if choosingChat {
                    WorkflowChatDestinationPicker(chats: chatChoices) { chatId in
                        if let chatId { draftConfig["chat_id"] = AnyCodable(chatId) }
                        else { draftConfig.removeValue(forKey: "chat_id") }
                        choosingChat = false
                    }
                } else {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Button {
                            choosingChat = true
                        } label: {
                            Text("\(AppStrings.workflowBuilder(.to)): \(messageDestinationTitle)")
                        }
                        .buttonStyle(.plain)
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                        .accessibilityIdentifier("workflow-message-destination")
                        workflowFieldLabel("lucide-heading", text: AppStrings.workflowBuilder(.chat_title))
                        TextField(AppStrings.workflowBuilder(.chat_title), text: Binding(
                            get: { draftConfig["title"]?.value as? String ?? "" },
                            set: { draftConfig["title"] = AnyCodable($0) }
                        ))
                        .textFieldStyle(WorkflowEditorTextFieldStyle())
                        .accessibilityIdentifier("workflow-message-title")
                        WorkflowMessageTemplateEditor(
                            value: Binding(
                                get: { draftConfig["message"]?.value as? String ?? "" },
                                set: { draftConfig["message"] = AnyCodable($0) }
                            ),
                            outputs: messageOutputs(before: node.id),
                            placeholder: AppStrings.localized("workflows.builder.message_placeholder"),
                            sourceTitles: outputSourceTitles
                        )
                    }
                    messagePreviewControls(for: node)
                }
            }

            if !choosingChat {
                Button {
                    Task { await save(node) }
                } label: {
                    Text(AppStrings.workflowBuilder(.save))
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontButton)
                        .frame(width: 176, height: 41) // Rendered .primary save button.
                        .background(saving ? Color.buttonSecondary : Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        .shadow(color: .black.opacity(0.25), radius: 4, y: 4)
                }
                .buttonStyle(.plain)
                .disabled(saving || (isAskAI(node) && askVerdict.blocksSave))
                .opacity(saving || (isAskAI(node) && askVerdict.blocksSave) ? 0.55 : 1)
                .accessibilityIdentifier("workflow-node-save")
                .frame(maxWidth: .infinity)

            }

            if let editError {
                Text(editError)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
            }
        }
        .padding(.horizontal, editorHorizontalPadding)
        .padding(.bottom, .spacing8)
        .frame(maxWidth: 772.8, alignment: .leading) // Web .editor: 48.3rem.
        .background(node.config["app_id"]?.value as? String == "weather" ? Color.grey10 : Color.grey0, in: RoundedRectangle(cornerRadius: .radius7))
        .overlay(RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey20, lineWidth: 1))
        .background {
            GeometryReader { geometry in
                Color.clear.preference(
                    key: WorkflowEditorScrollTargetKey.self,
                    value: WorkflowEditorScrollTarget(
                        id: WorkflowEditorScrollTarget.nodeID(node.id),
                        bounds: geometry.frame(in: .named(WorkflowEditorScrollTarget.coordinateSpace))
                    )
                )
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func editorHeader(for node: WorkflowNode) -> some View {
        let appSkill = node.type == .appSkillAction
        let askAI = isAskAI(node)
        return ZStack(alignment: .top) {
            WorkflowStepSummary.gradient(for: node)
            VStack(spacing: .spacing4) {
                Icon(node.type == .check || node.type == .decision ? "workflow-check" : WorkflowStepSummary.icon(node, graph: graph), size: horizontalSizeClass == .compact ? 36 : 40)
                    .accessibilityIdentifier("workflow-editor-primary-icon")
                if appSkill && !askAI {
                    Text(WorkflowStepSummary.kind(node)).font(.omP)
                }
                Text(node.type == .check || node.type == .decision ? AppStrings.workflowBuilder(.add_check) : appSkill ? WorkflowStepSummary.summary(node, skills: skills) : WorkflowStepSummary.kind(node))
                    .font(.omP.weight(.bold))
                    .multilineTextAlignment(.center)
                if let location = WorkflowStepSummary.inputSummary(node), appSkill && !askAI {
                    Text(location).font(.omP.weight(.semibold)).multilineTextAlignment(.center)
                }
            }
            .foregroundStyle(Color.fontButton)
            .padding(.horizontal, .spacing24)
            .padding(.top, .spacing24)
            .padding(.bottom, .spacing12)
            .frame(maxWidth: .infinity, minHeight: askAI ? 144 : appSkill ? (horizontalSizeClass == .compact ? 200 : 214) : (horizontalSizeClass == .compact ? 170 : 184))

            HStack(alignment: .top, spacing: .spacing2) {
                if appSkill || choosingChat || askAI || node.type == .check || node.type == .decision {
                    editorControl("back", label: AppStrings.workflowBuilder(.back), identifier: "workflow-node-back") {
                        if choosingChat {
                            choosingChat = false
                            // Back from destination selection restores an existing
                            // message editor, including its unsubmitted draft.
                            if graph.nodes.contains(where: { $0.id == node.id }) { return }
                        }
                        editingNodeId = nil
                        if draftNewNode?.id == node.id { draftNewNode = nil }
                    }
                }
                if draftNewNode?.id != node.id {
                    Button {
                        if deleteArmed { Task { await remove(node) } }
                        else { deleteArmed = true }
                    } label: {
                        HStack(spacing: .spacing2) {
                            Icon("delete", size: 22)
                            if deleteArmed { Text(AppStrings.workflowBuilder(.confirm_delete_node)).font(.omSmall.weight(.semibold)) }
                        }
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing4)
                        .frame(minWidth: 40, minHeight: 40)
                        .background(Color.grey0.opacity(0.22), in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.workflowBuilder(deleteArmed ? .confirm_delete_node : .delete_node))
                    .accessibilityIdentifier("workflow-delete-node")
                }
                Spacer(minLength: .spacing2)
                if onSave != nil && draftNewNode?.id != node.id {
                    if WorkflowGraphReordering.canMove(graph, nodeId: node.id, direction: .up) {
                        editorControl("up", label: AppStrings.workflowBuilder(.move_up), identifier: "workflow-move-step-up") { Task { await move(node, direction: .up) } }
                    }
                    if WorkflowGraphReordering.canMove(graph, nodeId: node.id, direction: .down) {
                        editorControl("down", label: AppStrings.workflowBuilder(.move_down), identifier: "workflow-move-step-down") { Task { await move(node, direction: .down) } }
                    }
                }
                editorControl("close", label: AppStrings.workflowBuilder(.close), identifier: "workflow-node-close") {
                    editingNodeId = nil
                    choosingChat = false
                    selectedCheckSourceId = nil
                    modelDetails = nil
                    draftConfig = node.config
                    if draftNewNode?.id == node.id { draftNewNode = nil }
                }
            }
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing3)
            .disabled(saving)
        }
        .fixedSize(horizontal: false, vertical: true)
        .clipShape(UnevenRoundedRectangle(topLeadingRadius: .radius7, topTrailingRadius: .radius7))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-editor-header")
    }

    private func editorControl(_ icon: String, label: String, identifier: String,
                               action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 22)
                .foregroundStyle(Color.fontButton)
                .frame(width: 40, height: 40)
                .background(Color.grey0.opacity(0.22), in: Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier(identifier)
    }

    private var scheduleFields: some View {
        let schedule = dictionary(draftConfig["schedule"])
        return VStack(alignment: .leading, spacing: .spacing3) {
            workflowFieldLabel("lucide-calendar-days", text: AppStrings.workflowBuilder(.date_time))
            .foregroundStyle(Color.fontSecondary)
            .frame(maxWidth: .infinity)
            LazyVGrid(columns: horizontalSizeClass == .compact ? [GridItem(.flexible())] : [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 12.8) {
            VStack(alignment: .leading, spacing: .spacing3) {
            workflowFieldLabel("lucide-repeat", text: AppStrings.workflowBuilder(.repeat))
            OMDropdown(title: AppStrings.workflowBuilder(.repeat), options: [
                OMDropdownOption("once", label: AppStrings.workflowBuilder(.once)),
                OMDropdownOption("hourly", label: AppStrings.workflowBuilder(.hourly)),
                OMDropdownOption("daily", label: AppStrings.workflowBuilder(.daily)),
                OMDropdownOption("weekly", label: AppStrings.workflowBuilder(.weekly))
            ], selection: Binding(
                get: { schedule["type"] as? String ?? "daily" },
                set: { type in
                    var next: [String: Any] = ["type": type, "timezone": schedule["timezone"] ?? TimeZone.current.identifier]
                    if type == "hourly" { next["minute"] = 0 }
                    else if type == "once" { next["at"] = schedule["at"] ?? "" }
                    else {
                        next["time"] = schedule["time"] ?? "09:00"
                        if type == "weekly" { next["weekdays"] = ["sunday"] }
                    }
                    draftConfig["schedule"] = AnyCodable(next)
                }
            ), controlSurface: workflowInputSurface, controlHeight: 54)
            .accessibilityIdentifier("workflow-time-trigger-schedule")
            }

            VStack(alignment: .leading, spacing: .spacing3) {
            if schedule["type"] as? String == "once" {
                workflowFieldLabel("lucide-calendar-days", text: AppStrings.workflowBuilder(.date_time))
                TextField(AppStrings.workflowBuilder(.date_time), text: scheduleBinding("at"))
                    .textFieldStyle(WorkflowEditorTextFieldStyle())
                    .accessibilityIdentifier("workflow-schedule-at")
            } else if schedule["type"] as? String == "hourly" {
                workflowFieldLabel("lucide-hash", text: AppStrings.workflowBuilder(.minute))
                TextField(AppStrings.workflowBuilder(.minute), text: Binding(
                    get: { String(dictionary(draftConfig["schedule"])["minute"] as? Int ?? 0) },
                    set: { if let minute = Int($0), (0...59).contains(minute) { setSchedule("minute", value: minute) } }
                ))
                .textFieldStyle(WorkflowEditorTextFieldStyle())
                .accessibilityIdentifier("workflow-schedule-minute")
            } else {
                workflowFieldLabel("lucide-clock", text: AppStrings.localized("workflows.builder.time"))
                TextField(AppStrings.localized("workflows.builder.time"), text: scheduleBinding("time"))
                    .textFieldStyle(WorkflowEditorTextFieldStyle())
                    .accessibilityIdentifier("workflow-schedule-time")
            }
            }
            VStack(alignment: .leading, spacing: .spacing3) {
            workflowFieldLabel("lucide-globe", text: AppStrings.workflowBuilder(.timezone))
            TextField(AppStrings.workflowBuilder(.timezone), text: scheduleBinding("timezone"))
                .textFieldStyle(WorkflowEditorTextFieldStyle())
                .accessibilityIdentifier("workflow-schedule-timezone")
            }
            }

            if schedule["type"] as? String == "weekly" {
                let days: [(String, AppStrings.WorkflowBuilderCopy)] = [
                    ("monday", .monday), ("tuesday", .tuesday), ("wednesday", .wednesday),
                    ("thursday", .thursday), ("friday", .friday), ("saturday", .saturday),
                    ("sunday", .sunday)
                ]
                ForEach(days, id: \.0) { day, key in
                    HStack {
                    Text(AppStrings.workflowBuilder(key)).font(.omP)
                    Spacer()
                    OMToggle(isOn: Binding(
                        get: { (dictionary(draftConfig["schedule"])["weekdays"] as? [String] ?? []).contains(day) },
                        set: { enabled in
                            var selected = dictionary(draftConfig["schedule"])["weekdays"] as? [String] ?? []
                            if enabled && !selected.contains(day) { selected.append(day) }
                            if !enabled { selected.removeAll { $0 == day } }
                            setSchedule("weekdays", value: selected)
                        }
                    ))
                    .accessibilityLabel(AppStrings.workflowBuilder(key))
                    }
                }
            }
        }
    }

    private func workflowFieldLabel(_ icon: String, text: String) -> some View {
        HStack(spacing: .spacing2) {
            Icon(icon, size: 16).foregroundStyle(Color.fontSecondary)
            Text(text).font(.omP.weight(.semibold))
        }
    }

    private func scheduleBinding(_ key: String) -> Binding<String> {
        Binding(
            get: { String(describing: dictionary(draftConfig["schedule"])[key] ?? "") },
            set: { setSchedule(key, value: $0) }
        )
    }

    private func setSchedule(_ key: String, value: Any) {
        var next = dictionary(draftConfig["schedule"])
        next[key] = value
        draftConfig["schedule"] = AnyCodable(next)
    }

    private func appSkillFields(for node: WorkflowNode) -> some View {
        let input = dictionary(draftConfig["input"])
        let appId = draftConfig["app_id"]?.value as? String ?? ""
        let skillId = draftConfig["skill_id"]?.value as? String ?? ""
        let askAI = appId == "ai" && skillId == "ask"
        let capability = skills.first { $0.appId == appId && $0.skillId == skillId }
        let schema = capability?.inputSchema.mapValues(\.value) ?? [:]
        return VStack(alignment: .leading, spacing: .spacing4) {
            if !askAI {
            HStack(spacing: .spacing2) {
                Icon("lucide-download", size: 18)
                Text(AppStrings.workflowBuilder(.input))
                    .font(.omP.weight(.semibold))
            }
            .foregroundStyle(Color.fontSecondary)
            .accessibilityIdentifier("workflow-input-heading")
            }
            if askAI {
                let outputs = previousOutputs(before: node.id)
                WorkflowMessageTemplateEditor(
                    value: Binding(
                        get: { dictionary(draftConfig["input"])["prompt"] as? String ?? "" },
                        set: { value in
                            setInput("prompt", value: value)
                            scheduleAskHints(for: node, instruction: value)
                        }
                    ),
                    outputs: suggestedAskOutputs(outputs),
                    placeholder: AppStrings.workflowBuilder(.ask_ai_placeholder),
                    sourceTitles: outputSourceTitles
                )
                .accessibilityIdentifier("workflow-ask-ai-instruction")
                if askVerdict == .asksToInvokeAppSkill {
                    Text(AppStrings.workflowBuilder(.ask_ai_app_warning))
                        .font(.omP)
                        .foregroundStyle(Color.error)
                        .accessibilityIdentifier("workflow-ai-app-warning")
                } else if askVerdict == .unverified {
                    Text(askHints.reminder ?? AppStrings.workflowBuilder(.ask_ai_validation_unavailable))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("workflow-ai-neutral-reminder")
                } else if askVerdict == .checking {
                    Text(AppStrings.workflowBuilder(.checking_instruction))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("workflow-ai-checking")
                }
            } else if !schema.isEmpty {
                WorkflowSchemaInputView(schema: schema, value: input, appId: appId,
                                        onChange: { draftConfig["input"] = AnyCodable($0) },
                                        path: node.id,
                                        timezone: dictionary(draftConfig["schedule"])["timezone"] as? String ?? TimeZone.current.identifier)
            } else {
                ForEach(input.keys.sorted(), id: \.self) { key in
                    if let boolean = input[key] as? Bool {
                        HStack {
                        Text(WorkflowValueView.displayLabel(key)).font(.omP)
                        Spacer()
                        OMToggle(isOn: Binding(
                            get: { (dictionary(draftConfig["input"])[key] as? Bool) ?? boolean },
                            set: { setInput(key, value: $0) }
                        ))
                        .accessibilityLabel(WorkflowValueView.displayLabel(key))
                        .accessibilityIdentifier("workflow-input-\(key)")
                        }
                    } else if input[key] is String || input[key] is Int || input[key] is Double {
                        TextField(WorkflowValueView.displayLabel(key), text: Binding(
                            get: { String(describing: dictionary(draftConfig["input"])[key] ?? "") },
                            set: { setInput(key, value: $0) }
                        ))
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("workflow-input-\(key)")
                    } else if let nested = input[key] {
                        Text(WorkflowValueView.displayLabel(key))
                            .font(.omSmall.weight(.semibold))
                        WorkflowValueView(value: nested)
                    }
                }
            }

            if askAI {
                GeometryReader { geometry in
                    HStack(alignment: .top) {
                        if let catalog = modelCatalog.catalog {
                            NativeComposerModelSelector(
                                catalog: catalog, routing: modelCatalog.routing,
                                selection: input["model"] as? String ?? "auto", ready: !saving,
                                viewportWidth: geometry.size.width,
                                menuLeadingOffset: 0,
                                onSelect: { setInput("model", value: $0) },
                                onOpenDetails: { modelDetails = $0 }
                            )
                        }
                        Spacer(minLength: .spacing3)
                        testControls(for: node, capability: capability)
                    }
                }
                .frame(height: 41)
                .zIndex(20)
            } else {
                testControls(for: node, capability: capability)
                    .frame(maxWidth: .infinity)
            }

            Button(AppStrings.workflowBuilder(showOutputFields ? .hide_output_fields : .show_output_fields)) {
                showOutputFields.toggle()
            }
            .buttonStyle(.plain)
            .font(.omSmall)
            .foregroundStyle(Color.fontSecondary)
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("workflow-show-output-fields")
            if showOutputFields {
                HStack {
                    HStack(spacing: 4) {
                        Icon("lucide-upload", size: 18).foregroundStyle(Color.fontSecondary)
                        Text(AppStrings.workflowBuilder(.output) + ":")
                    }
                    .font(.omP.weight(.semibold))
                    Spacer()
                    Text(AppStrings.workflowBuilder(outputValues(for: node) == nil ? .example : .test_output))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("workflow-output-example-heading")
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("workflow-output-heading")
                if stepTest.activeNodeId == node.id && stepTest.status == .processing {
                    ProgressView(AppStrings.workflowBuilder(.processing))
                        .accessibilityIdentifier("workflow-test-output-loading")
                } else if stepTest.activeNodeId == node.id,
                          [.failed, .cancelled, .pending].contains(stepTest.status) {
                    // Failure never presents schema examples as successful output.
                    Text(stepTest.errorMessage ?? AppStrings.workflowOutputTestFailed)
                        .font(.omP)
                        .foregroundStyle(Color.error)
                        .accessibilityIdentifier("workflow-test-output-error")
                } else if let tested = outputValues(for: node) {
                    WorkflowValueView(value: tested.mapValues(\.value), appId: appId)
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("workflow-output-fields")
                } else {
                    WorkflowOutputFieldsView(properties: capability?.outputSchema["properties"]?.value as? [String: Any] ?? [:], appId: appId)
                }
            }
        }
        .overlay(alignment: .topLeading) {
            if let model = modelDetails {
                NativeComposerModelDetails(model: model, onClose: { modelDetails = nil })
                    .frame(maxWidth: 440).frame(height: 520)
                    .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius8))
                    .shadow(radius: 16)
                    .zIndex(30)
            }
        }
    }

    private func checkFields(for node: WorkflowNode) -> some View {
        let predicate = dictionary(draftConfig["predicate"])
        let outputs = previousOutputs(before: node.id).filter { !["object", "array"].contains($0.type) }
        let selected = outputs.first { $0.id == predicate["left"] as? String }
        let number = selected?.type == "number" || selected?.type == "integer"
        let boolean = selected?.type == "boolean"
        let sourceIds = Set(outputs.map { outputNodeID($0.id) })
        let sources = graph.nodes.filter { $0.type == .appSkillAction && sourceIds.contains($0.id) }
        let sourceId = draftConfig["mode"]?.value as? String == "ai" ? "ai" : outputNodeID(predicate["left"] as? String ?? "")
        let sourceOptions = sources.map(checkSourceOption) + [OMDropdownOption("ai", label: AppStrings.localized("workflows.builder.ai_confirms"), iconName: "ai", iconAppId: "ai")]
        let operatorIds = number ? ["gt", "gte", "lt", "lte", "eq", "neq"] : boolean ? ["eq", "neq"] : ["eq", "neq", "contains"]
        let symbols = ["eq": "=", "neq": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "contains": "∋", "exists": "✓"]
        let compareSource = (predicate["right"] as? String).flatMap { $0.hasPrefix("$nodes.") ? outputNodeID($0) : nil } ?? "literal"
        let compatible = outputs.filter { selected?.type == $0.type || number && ["number", "integer"].contains($0.type) }
        let literalLabel = AppStrings.localized("workflows.builder.output_type_" + (number ? "number" : boolean ? "boolean" : "text"))
        return VStack(spacing: 12.8) {
            Text(AppStrings.workflowBuilder(.if)).font(.omH2.weight(.semibold))
                .accessibilityIdentifier("workflow-check-if-heading")
            OMDropdown(title: AppStrings.localized("workflows.builder.select_check_source"), options: sourceOptions, selection: Binding(
                get: { selectedCheckSourceId ?? sourceId },
                set: { id in
                    draftConfig["mode"] = AnyCodable(id == "ai" ? "ai" : "exact")
                    selectedCheckSourceId = nil
                    if id != "ai", id != sourceId {
                        draftConfig["predicate"] = AnyCodable(["left": "", "op": ""])
                        // Source selection is explicit; its output is chosen next.
                        selectedCheckSourceId = id
                    }
                }
            ), controlSurface: workflowInputSurface, controlHeight: 54)
            .accessibilityIdentifier("workflow-check-source")
            if sourceId == "ai" {
                WorkflowMessageTemplateEditor(value: Binding(
                    get: { draftConfig["question"]?.value as? String ?? "" },
                    set: { draftConfig["question"] = AnyCodable($0) }
                ), outputs: messageOutputs(before: node.id), placeholder: AppStrings.workflowBuilder(.ai_check_placeholder), sourceTitles: outputSourceTitles, minimumInputHeight: 128)
                .accessibilityIdentifier("workflow-ai-check-instruction")
                Text(AppStrings.localized("workflows.builder.ai_check_guidance"))
                    .font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if !(selectedCheckSourceId ?? sourceId).isEmpty {
                let chosenSource = selectedCheckSourceId ?? sourceId
                OMDropdown(title: AppStrings.workflowBuilder(.select_output), options: outputs.filter { outputNodeID($0.id) == chosenSource }.map(checkFieldOption), selection: Binding(
                    get: { predicate["left"] as? String ?? "" },
                    set: { setPredicate("left", value: $0); setPredicate("op", value: ""); selectedCheckSourceId = nil }
                ), controlSurface: workflowInputSurface, controlHeight: 54)
                .accessibilityIdentifier("workflow-check-variable")
                if selected != nil {
                    OMDropdown(title: AppStrings.workflowBuilder(.compare_type), options: operatorIds.map { id in
                        OMDropdownOption(id, label: AppStrings.localized("workflows.builder.operator_" + (id == "neq" ? "ne" : id)), iconText: symbols[id], iconAppId: "events")
                    }, selection: Binding(get: { let value = predicate["op"] as? String ?? ""; return value == "ne" ? "neq" : value }, set: { setPredicate("op", value: $0) }), controlSurface: workflowInputSurface, controlHeight: 54)
                    .accessibilityIdentifier("workflow-check-operator")
                }
                if let op = predicate["op"] as? String, !op.isEmpty, op != "exists" {
                    let compareIds = Set(compatible.map { outputNodeID($0.id) })
                    let compareOptions = [OMDropdownOption("literal", label: literalLabel, iconText: number ? "123" : boolean ? "✓" : "T", iconAppId: "events")] + sources.filter { compareIds.contains($0.id) }.map(checkSourceOption)
                    OMDropdown(title: AppStrings.localized("workflows.builder.compare_source"), options: compareOptions, selection: Binding(get: { compareSource }, set: { id in
                        if id == "literal" { setPredicate("right", value: number ? 0 as Any : boolean ? true as Any : "") }
                        else if let output = compatible.first(where: { outputNodeID($0.id) == id }) { setPredicate("right", value: output.id) }
                    }), controlSurface: workflowInputSurface, controlHeight: 54)
                    .accessibilityIdentifier("workflow-check-compare-source")
                    if compareSource != "literal" {
                        OMDropdown(title: AppStrings.localized("workflows.builder.compare_variable"), options: compatible.filter { outputNodeID($0.id) == compareSource }.map(checkFieldOption), selection: Binding(get: { predicate["right"] as? String ?? "" }, set: { setPredicate("right", value: $0) }), controlSurface: workflowInputSurface, controlHeight: 54)
                        .accessibilityIdentifier("workflow-check-compare-variable")
                    } else if boolean {
                        OMDropdown(title: AppStrings.workflowBuilder(.compare_value), options: [OMDropdownOption("true", label: AppStrings.workflowBuilder(.true), iconText: "✓", iconAppId: "events"), OMDropdownOption("false", label: AppStrings.workflowBuilder(.false), iconText: "×", iconAppId: "events")], selection: Binding(get: { (predicate["right"] as? Bool ?? true) ? "true" : "false" }, set: { setPredicate("right", value: $0 == "true") }), controlSurface: workflowInputSurface, controlHeight: 54)
                    } else {
                        TextField(AppStrings.workflowBuilder(.compare_value), text: Binding(get: { String(describing: dictionary(draftConfig["predicate"])["right"] ?? "") }, set: { raw in
                            if number { if let value = Double(raw) { setPredicate("right", value: value) } }
                            else { setPredicate("right", value: raw) }
                        }))
                        .textFieldStyle(WorkflowEditorTextFieldStyle())
                        .accessibilityIdentifier("workflow-check-value")
                    }
                }
            }
            testControls(for: node)
            if let matched = stepTest.outputsByNode[node.id]?["matched"]?.value as? Bool {
                Text("\(AppStrings.workflowBuilder(.test_output)): \(AppStrings.workflowBuilder(matched ? .true : .false))")
                    .font(.omP).accessibilityIdentifier("workflow-check-test-result")
            }
        }
        .frame(maxWidth: 368).frame(maxWidth: .infinity)
    }

    private var workflowInputSurface: LinearGradient {
        LinearGradient(colors: [.grey10, .grey20], startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    private func outputNodeID(_ reference: String) -> String {
        let parts = reference.split(separator: ".")
        return parts.count > 1 ? String(parts[1]) : ""
    }

    private func checkSourceOption(_ node: WorkflowNode) -> OMDropdownOption {
        let appId = node.config["app_id"]?.value as? String ?? "workflows"
        return OMDropdownOption(node.id, label: outputSourceTitles[node.id] ?? WorkflowStepSummary.summary(node, skills: skills), iconName: WorkflowStepSummary.icon(node), iconAppId: appId)
    }

    private func checkFieldOption(_ output: WorkflowOutputChoice) -> OMDropdownOption {
        let source = graph.nodes.first { $0.id == outputNodeID(output.id) }
        return OMDropdownOption(output.id, label: output.label.components(separatedBy: " · ").last ?? output.label, iconName: source.map { WorkflowStepSummary.icon($0) }, iconAppId: source?.config["app_id"]?.value as? String)
    }

    private func setPredicate(_ key: String, value: Any) {
        var next = dictionary(draftConfig["predicate"])
        next[key] = value
        draftConfig["predicate"] = AnyCodable(next)
    }

    @ViewBuilder
    private func testControls(for node: WorkflowNode, capability: WorkflowSkillChoice? = nil) -> some View {
        let processing = stepTest.activeNodeId == node.id && stepTest.status == .processing
        HStack(spacing: .spacing3) {
            if processing {
                ProgressView(AppStrings.workflowBuilder(.processing))
                    .accessibilityIdentifier("workflow-test-processing")
                if stepTest.canStop {
                    Button(AppStrings.workflowBuilder(.stop)) {
                        Task { await stepTest.cancel() }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("workflow-test-stop")
                }
            } else {
                Button {
                    guard let workflowId else { return }
                    showOutputFields = true
                    let draft = revisedNode(node)
                    Task {
                        await stepTest.test(workflowId: workflowId, node: draft, graph: graph,
                                            insertionAfter: draftNewNode?.id == node.id ? stepPickerAfterId : nil)
                    }
                } label: {
                    HStack(spacing: .spacing2) {
                        Icon("play", size: 16)
                        Text(AppStrings.workflowBuilder(stepTest.outputsByNode[node.id] == nil ? .test_action : .test_again))
                        if node.type == .appSkillAction && !isAskAI(node) || draftConfig["mode"]?.value as? String == "ai" {
                            Icon("coins", size: 14)
                            Text(capability?.fixedCreditCost.map(String.init) ??
                                 (node.type == .check ? "1" : AppStrings.workflowBuilder(.variable_cost)))
                        }
                    }
                }
                .buttonStyle(.plain)
                .font(.omP.weight(.semibold))
                .foregroundStyle(LinearGradient.primary)
                .disabled(workflowId == nil || accountId == nil || accountId == "workflow-preview"
                          || saving || !canTest(node, capability: capability))
                .accessibilityIdentifier("workflow-test-action")
            }
        }
        .frame(maxWidth: .infinity, alignment: .center)
        if stepTest.activeNodeId == node.id, let error = stepTest.errorMessage,
           !(node.type == .appSkillAction && showOutputFields) {
            Text(error)
                .font(.omSmall)
                .foregroundStyle(Color.error)
                .accessibilityIdentifier("workflow-test-output-error")
        }
    }

    private func canTest(_ node: WorkflowNode, capability: WorkflowSkillChoice?) -> Bool {
        if node.type == .appSkillAction { return capability?.testAllowed == true }
        guard node.type == .check || node.type == .decision else { return false }
        if draftConfig["mode"]?.value as? String == "ai" {
            return !(draftConfig["question"]?.value as? String ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        let predicate = dictionary(draftConfig["predicate"])
        return !(predicate["left"] as? String ?? "").isEmpty && !(predicate["op"] as? String ?? "").isEmpty
    }

    private func revisedNode(_ node: WorkflowNode) -> WorkflowNode {
        let message = node.type == .sendChatMessage || node.type == .createChatReport
        let title = message ? messageDestinationTitle : (draftTitle.isEmpty ? nil : draftTitle)
        return WorkflowNode(id: node.id, type: node.type,
                            title: title,
                            config: draftConfig, inputMapping: node.inputMapping, ui: node.ui)
    }

    private var messageDestinationTitle: String {
        guard let chatId = draftConfig["chat_id"]?.value as? String else { return AppStrings.newChat }
        return chatChoices.first(where: { $0.id == chatId })?.title
            ?? AppStrings.workflowBuilder(.existing_chat)
    }

    private func hasEarlierActionReference(_ template: String, before nodeId: String) -> Bool {
        let outputs = previousOutputs(before: nodeId)
        guard !outputs.isEmpty else { return true }
        let segments = WorkflowMessageTokens.parse(template, outputs: outputs.map {
            WorkflowMessageOutput(reference: $0.id, label: $0.label, appId: nil)
        })
        return segments.contains { segment in
            if case .output(let reference, _, _, _) = segment {
                return outputs.contains { $0.id == reference }
            }
            return false
        }
    }

    @ViewBuilder
    private func messagePreviewControls(for node: WorkflowNode) -> some View {
        Button(AppStrings.workflowBuilder(.preview_message)) {
            guard let workflowId else { return }
            Task { await stepTest.preview(workflowId: workflowId, node: revisedNode(node), graph: graph) }
        }
        .buttonStyle(.plain)
        .font(.omP.weight(.semibold))
        .foregroundStyle(Color.fontPrimary)
        .frame(maxWidth: .infinity)
        .disabled(workflowId == nil || accountId == nil || accountId == "workflow-preview"
                  || saving || (draftConfig["title"]?.value as? String ?? "")
                    .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        .accessibilityIdentifier("workflow-preview-message")
        if stepTest.activeNodeId == node.id && stepTest.status == .processing {
            ProgressView(AppStrings.workflowBuilder(.processing))
        }
        if let preview = stepTest.previewByNode[node.id] {
            VStack(alignment: .leading, spacing: .spacing3) {
                if let title = preview["title"]?.value as? String { Text(title).font(.omP.weight(.semibold)) }
                WorkflowValueView(value: preview.mapValues(\.value))
            }
            .padding(.spacing4)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius6))
            .accessibilityIdentifier("workflow-message-preview")
        }
        if stepTest.activeNodeId == node.id, let error = stepTest.errorMessage {
            Text(error).font(.omSmall).foregroundStyle(Color.error)
        }
    }

    private func previousOutputs(before nodeId: String) -> [WorkflowOutputChoice] {
        var ancestors = Set<String>()
        var pending = [nodeId]
        while let next = pending.popLast() {
            for edge in graph.edges where edge.to == next && !ancestors.contains(edge.from) {
                ancestors.insert(edge.from)
                pending.append(edge.from)
            }
        }
        return graph.nodes.filter { ancestors.contains($0.id) }.flatMap { node -> [WorkflowOutputChoice] in
            if node.type == .check || node.type == .decision {
                return [WorkflowOutputChoice(id: "$nodes.\(node.id).output.matched",
                                             label: "\(node.title ?? WorkflowStepSummary.kind(node)) · \(AppStrings.workflowBuilder(.check))",
                                             type: "boolean")]
            }
            guard node.type == .appSkillAction,
                  let appId = node.config["app_id"]?.value as? String,
                  let skillId = node.config["skill_id"]?.value as? String,
                  let schema = skills.first(where: { $0.appId == appId && $0.skillId == skillId })?.outputSchema,
                  let properties = schema["properties"]?.value as? [String: Any]
            else { return [] }
            return properties.keys.sorted().compactMap { key in
                let field = properties[key] as? [String: Any] ?? [:]
                let type = field["type"] as? String ?? "string"
                return WorkflowOutputChoice(id: "$nodes.\(node.id).output.\(key)",
                    label: "\(node.title ?? appId.capitalized) · \(field["title"] as? String ?? WorkflowValueView.displayLabel(key))",
                    type: type)
            }
        }
    }

    private func messageOutputs(before nodeId: String) -> [WorkflowMessageOutput] {
        previousOutputs(before: nodeId).map { output in
            let parts = output.id.split(separator: ".")
            let source = parts.count > 1 ? graph.nodes.first { $0.id == String(parts[1]) } : nil
            return WorkflowMessageOutput(reference: output.id, label: output.label,
                                         appId: source?.config["app_id"]?.value as? String)
        }
    }

    private var outputSourceTitles: [String: String] {
        Dictionary(uniqueKeysWithValues: graph.nodes.map { node in
            let title = WorkflowStepSummary.summary(node, skills: skills)
            let location = WorkflowStepSummary.inputSummary(node)
            return (node.id, title + (location.map { " · " + $0 } ?? ""))
        })
    }

    private func isAskAI(_ node: WorkflowNode) -> Bool {
        node.type == .appSkillAction &&
            node.config["app_id"]?.value as? String == "ai" &&
            node.config["skill_id"]?.value as? String == "ask"
    }

    private var askInstruction: String {
        dictionary(draftConfig["input"])["prompt"] as? String ?? ""
    }

    private var askVerdict: WorkflowAskAIVerdict {
        previewAskAIVerdict ?? askHints.verdict
    }

    private func scheduleAskHints(for node: WorkflowNode, instruction: String) {
        let references = previousOutputs(before: node.id).map { output in
            WorkflowAskAIReferenceHint(
                reference: output.id, label: output.label, valueType: output.type,
                inserted: instruction.contains(WorkflowMessageTokens.storageSyntax(for: output.id))
            )
        }
        askHints.schedule(nodeId: node.id, instruction: instruction, references: references)
    }

    private func suggestedAskOutputs(_ outputs: [WorkflowOutputChoice]) -> [WorkflowMessageOutput] {
        let suggested = askHints.suggestedReferences
        return outputs.sorted { lhs, rhs in
            let lhsRank = suggested.firstIndex(of: lhs.id) ?? Int.max
            let rhsRank = suggested.firstIndex(of: rhs.id) ?? Int.max
            return lhsRank == rhsRank ? lhs.id < rhs.id : lhsRank < rhsRank
        }.map { output in
            let parts = output.id.split(separator: ".")
            let source = parts.count > 1 ? graph.nodes.first { $0.id == String(parts[1]) } : nil
            return WorkflowMessageOutput(reference: output.id, label: output.label,
                                         appId: source?.config["app_id"]?.value as? String)
        }
    }

    @ViewBuilder
    private func textField(key: String, label: String, multiline: Bool) -> some View {
        let binding = Binding<String>(
            get: { draftConfig[key]?.value as? String ?? "" },
            set: { draftConfig[key] = AnyCodable($0) }
        )
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(label).font(.omSmall.weight(.semibold))
            if multiline {
                TextEditor(text: binding)
                    .frame(minHeight: 112)
                    .accessibilityIdentifier("workflow-node-\(key)")
            } else {
                TextField(label, text: binding)
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibilityIdentifier("workflow-node-\(key)")
            }
        }
    }

    @ViewBuilder
    private func branchControls(after node: WorkflowNode) -> some View {
        VStack(alignment: .center, spacing: .spacing3) {
            ForEach(branches(for: node), id: \.self) { branch in
                VStack(spacing: .spacing2) {
                    Text(AppStrings.workflowBuilder(
                        branch == "true" || branch == "yes" ? .if_true :
                        branch == "unsure" ? .if_unsure : .else
                    ))
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)
                    let destination = nextId(after: node.id, branch: branch)
                        ?? nextId(after: node.id, branch: branch == "yes" ? "true" : branch == "no" ? "false" : branch)
                    let branchNodes = chain(from: destination, stoppingAt: nextId(after: node.id))
                    if branchNodes.isEmpty {
                        continuation(after: node.id, branch: branch)
                    } else {
                        ForEach(branchNodes) { branchNode in
                            step(branchNode)
                            if branchNode.id != branchNodes.last?.id {
                                Text(AppStrings.workflowBuilder(.then))
                                    .font(.omP.weight(.semibold))
                                    .foregroundStyle(Color.fontSecondary)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity)
            }
        }
        .padding(.top, .spacing4)
        .padding(.horizontal, .spacing3)
        .padding(.bottom, .spacing3)
        .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey20))
        .frame(maxWidth: 672)
    }

    private func branches(for node: WorkflowNode) -> [String] {
        node.config["mode"]?.value as? String == "ai"
            ? ["true", "false", "unsure"] : ["yes", "no"]
    }

    @ViewBuilder
    private func continuation(after nodeId: String?, branch: String? = nil) -> some View {
        if !readOnly {
            if let draftNewNode, stepPickerAfterId == nodeId, stepPickerBranch == branch {
                editor(for: draftNewNode)
                    .id(WorkflowEditorScrollTarget.nodeID(draftNewNode.id))
            } else if stepPickerOpen, stepPickerAfterId == nodeId, stepPickerBranch == branch {
                stepPickerPanel(after: nodeId)
            } else {
            Button {
                stepPickerAfterId = nodeId
                stepPickerBranch = branch
                stepPickerOpen = true
                pickerStage = nodeId == nil ? .trigger : .action
                selectedAppId = ""
                editingNodeId = nil
                editError = nil
            } label: {
                Text(AppStrings.workflowBuilder(.do_nothing_add_step))
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 336, minHeight: 148)
                    .overlay(RoundedRectangle(cornerRadius: .radius6)
                        .stroke(Color.grey30, style: StrokeStyle(lineWidth: 1, dash: [5, 4])))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("workflow-add-step")
            }
        } else {
            Text(AppStrings.workflowBuilder(.do_nothing))
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 336, minHeight: 148)
                .overlay(RoundedRectangle(cornerRadius: .radius6)
                    .stroke(Color.grey30, style: StrokeStyle(lineWidth: 1, dash: [5, 4])))
        }
    }

    @ViewBuilder
    private func stepPickerPanel(after nodeId: String?) -> some View {
        VStack(spacing: .spacing5) {
            HStack {
                if pickerStage == .app || pickerStage == .skill {
                    Button {
                        pickerStage = pickerStage == .skill ? .app : .action
                    } label: { Icon("back", size: 20) }
                    .accessibilityLabel(AppStrings.workflowBuilder(.back))
                    .accessibilityIdentifier("workflow-step-picker-back")
                }
                Spacer()
                Text(AppStrings.workflowBuilder(
                    pickerStage == .trigger ? .add_trigger :
                    pickerStage == .app ? .use_app :
                    pickerStage == .skill ? .choose_skill : .add_action))
                    .font(.omP.weight(.semibold))
                Spacer()
                Button {
                    stepPickerOpen = false
                } label: { Icon("close", size: 20) }
                .accessibilityLabel(AppStrings.workflowBuilder(.close))
                .accessibilityIdentifier("workflow-step-picker-close")
            }

            Text(AppStrings.workflowBuilder(
                pickerStage == .trigger ? .trigger_question :
                pickerStage == .app ? .app_question :
                pickerStage == .skill ? .skill_question : .action_question))
                .font(.omP.weight(.semibold))

            if pickerStage == .trigger {
                pickerChoice("lucide-calendar-days", title: .date_time,
                             identifier: "workflow-trigger-date-time") {
                    prepareNode(.scheduleTrigger)
                }
            } else if pickerStage == .action {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 108), spacing: .spacing4)], spacing: .spacing4) {
                    pickerChoice("app", title: .use_app, identifier: "workflow-step-app-skill-action") {
                        pickerStage = .app
                    }
                    pickerChoice("ai", title: .ask_ai, identifier: "workflow-step-ask-ai") {
                        if let skill = skills.first(where: { $0.appId == "ai" && $0.skillId == "ask" }) {
                            prepareNode(.appSkillAction, skill: skill)
                        } else { editError = AppStrings.workflowBuilder(.ask_ai_unavailable) }
                    }
                    if let nodeId, graph.nodes.first(where: { $0.id == nodeId })?.type != .scheduleTrigger {
                        pickerChoice("workflow-check", title: .add_check, identifier: "workflow-step-check") {
                            prepareNode(.check)
                        }
                    }
                    pickerChoice("chat", title: .send_message,
                                 identifier: "workflow-step-create-chat-report") {
                        prepareNode(.sendChatMessage)
                    }
                }
            } else if pickerStage == .app {
                ScrollView(.horizontal) {
                    HStack(spacing: .spacing4) {
                        ForEach(Array(Set(skills.map(\.appId))).sorted(), id: \.self) { appId in
                            Button {
                                selectedAppId = appId
                                pickerStage = .skill
                            } label: {
                                pickerCard(icon: AppIconView.iconName(forAppId: appId),
                                           title: appId.capitalized, appId: appId)
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("workflow-picker-app")
                        }
                    }
                }
            } else {
                ScrollView(.horizontal) {
                    HStack(spacing: .spacing4) {
                        ForEach(skills.filter { $0.appId == selectedAppId }) { skill in
                            Button { prepareNode(.appSkillAction, skill: skill) } label: {
                                pickerCard(icon: AppIconView.iconName(forAppId: skill.appId),
                                           title: skill.title, appId: skill.appId)
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("workflow-picker-skill")
                        }
                    }
                }
            }
            if let editError {
                Text(editError).font(.omSmall).foregroundStyle(Color.error)
            }
        }
        .padding(.spacing5)
        .frame(maxWidth: 672, minHeight: 176)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius6))
        .shadow(color: .black.opacity(0.1), radius: 5, y: 3)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-step-menu")
    }

    private func pickerChoice(_ icon: String, title: AppStrings.WorkflowBuilderCopy,
                              identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: .spacing3) {
                Icon(icon, size: 24).foregroundStyle(LinearGradient.primary)
                Text(AppStrings.workflowBuilder(title))
                    .font(.omP.weight(.semibold))
                    .foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)
            }
            .frame(minWidth: 96, minHeight: 76)
            .padding(.spacing3)
            .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius6))
            .shadow(color: .black.opacity(0.1), radius: 3, y: 2)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func pickerCard(icon: String, title: String, appId: String) -> some View {
        VStack(spacing: .spacing3) {
            Icon(icon, size: 28).foregroundStyle(Color.fontButton)
            Text(title)
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontButton)
                .multilineTextAlignment(.center)
                .lineLimit(2)
        }
        .frame(width: 132, height: 100)
        .background(AppIconView.gradient(forAppId: appId),
                    in: RoundedRectangle(cornerRadius: .radius6))
    }

    private func save(_ node: WorkflowNode) async {
        guard let onSave else { return }
        saving = true
        editError = nil
        let revised = revisedNode(node)
        if isAskAI(revised) {
            let prompt = askInstruction
            let failure = WorkflowAskAISavePolicy.failure(
                instruction: prompt,
                hasEarlierReference: hasEarlierActionReference(prompt, before: node.id),
                verdict: askVerdict
            )
            if let failure {
                saving = false
                let key: AppStrings.WorkflowBuilderCopy = switch failure {
                case .missingInstruction: .ask_ai_instruction_required
                case .missingEarlierReference: .earlier_action_variable_required
                case .appSkillInvocation: .ask_ai_app_warning
                }
                editError = AppStrings.workflowBuilder(key)
                return
            }
        }
        if node.type == .sendChatMessage || node.type == .createChatReport {
            let title = draftConfig["title"]?.value as? String ?? ""
            guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                saving = false
                editError = AppStrings.workflowBuilder(.title_required)
                return
            }
            guard hasEarlierActionReference(draftConfig["message"]?.value as? String ?? "",
                                            before: node.id) else {
                saving = false
                editError = AppStrings.workflowBuilder(.earlier_action_variable_required)
                return
            }
        }
        if node.type == .check || node.type == .decision {
            if draftConfig["mode"]?.value as? String == "ai" {
                guard let question = draftConfig["question"]?.value as? String,
                      !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    saving = false
                    editError = AppStrings.workflowBuilder(.check_required)
                    return
                }
                guard hasEarlierActionReference(question, before: node.id) else {
                    saving = false
                    editError = AppStrings.workflowBuilder(.earlier_action_variable_required)
                    return
                }
            } else {
                let predicate = dictionary(draftConfig["predicate"])
                guard let left = predicate["left"] as? String, !left.isEmpty,
                      let op = predicate["op"] as? String, !op.isEmpty else {
                    saving = false
                    editError = AppStrings.workflowBuilder(.check_required)
                    return
                }
            }
        }
        let next = try? (graph.nodes.contains { $0.id == revised.id }
            ? WorkflowGraphEditing.replacing(revised, in: graph)
            : WorkflowGraphEditing.inserting(revised, into: graph,
                after: stepPickerAfterId, branch: stepPickerBranch))
        guard let next else {
            saving = false
            editError = AppStrings.workflowBuilder(.save_failed)
            return
        }
        let didSave = await onSave(next)
        saving = false
        if didSave { editingNodeId = nil; draftNewNode = nil }
        else { editError = AppStrings.workflowBuilder(.save_failed) }
    }

    private func move(_ node: WorkflowNode, direction: WorkflowGraphReordering.Direction) async {
        guard let next = WorkflowGraphReordering.move(graph, nodeId: node.id, direction: direction) else { return }
        await persistReorder(next)
    }

    private func persistReorder(_ graph: WorkflowGraph) async {
        guard let onSave, !saving else { return }
        saving = true
        editError = nil
        if !((await onSave(graph))) { editError = AppStrings.workflowBuilder(.save_failed) }
        saving = false
    }

    private func remove(_ node: WorkflowNode) async {
        if draftNewNode?.id == node.id {
            draftNewNode = nil
            editingNodeId = nil
            deleteArmed = false
            return
        }
        guard let onSave else { return }
        saving = true
        editError = nil
        do {
            let next = try WorkflowGraphEditing.removing(node.id, from: graph)
            if await onSave(next) {
                editingNodeId = nil
                deleteArmed = false
            } else {
                editError = AppStrings.workflowBuilder(.save_failed)
            }
        } catch WorkflowGraphEditError.dependentNodes(let ids) {
            editError = AppStrings.workflowStepInUse(ids.joined(separator: ", "))
        } catch {
            editError = AppStrings.workflowBuilder(.save_failed)
        }
        saving = false
    }

    private func prepareNode(_ type: WorkflowNodeType, skill: WorkflowSkillChoice? = nil) {
        let id = "\(type.rawValue)-\(UUID().uuidString.prefix(8))"
        var config: [String: AnyCodable] = [:]
        if type == .scheduleTrigger {
            config["schedule"] = AnyCodable(["type": "daily", "time": "09:00", "timezone": TimeZone.current.identifier])
        } else if let skill {
            config["app_id"] = AnyCodable(skill.appId)
            config["skill_id"] = AnyCodable(skill.skillId)
            config["input"] = AnyCodable([String: String]())
        } else if type == .check {
            config["mode"] = AnyCodable("exact")
            config["predicate"] = AnyCodable(["left": "", "op": "", "right": ""])
        } else if type == .sendChatMessage {
            config["title"] = AnyCodable("")
            config["message"] = AnyCodable("")
            config["blocks"] = AnyCodable([String]())
        }
        let node = WorkflowNode(id: id, type: type, title: skill?.title,
                                config: config, inputMapping: [:], ui: [:])
        stepPickerOpen = false
        draftNewNode = node
        editingNodeId = id
        draftTitle = node.title ?? ""
        draftConfig = node.config
        choosingChat = type == .sendChatMessage
    }

    private func setInput(_ key: String, value: Any) {
        var input = dictionary(draftConfig["input"])
        input[key] = value
        draftConfig["input"] = AnyCodable(input)
    }

    private func dictionary(_ value: AnyCodable?) -> [String: Any] {
        if let dictionary = value?.value as? [String: Any] { return dictionary }
        if let dictionary = value?.value as? [String: AnyCodable] { return dictionary.mapValues(\.value) }
        return [:]
    }
}

private struct WorkflowStepSummary: View {
    let node: WorkflowNode
    let run: WorkflowNodeRun?
    var graph: WorkflowGraph? = nil
    var skills: [WorkflowSkillChoice] = []
    var executionStatus: String? = nil

    private var appId: String {
        node.config["app_id"]?.value as? String ?? "workflows"
    }

    var body: some View {
        VStack(spacing: .spacing2) {
            Icon(Self.icon(node, graph: graph), size: 33)
                .foregroundStyle(Color.fontButton)
            Text(Self.kind(node))
                .font(.omSmall)
                .foregroundStyle(Color.fontButton.opacity(0.9))
            if node.type == .check || node.type == .decision,
               let source = Self.checkSource(node, graph: graph) {
                Text(Self.summary(source, skills: skills))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontButton.opacity(0.9))
            }
            Text(Self.summary(node, skills: skills))
                .font(.omP.weight(.bold))
                .foregroundStyle(Color.fontButton)
                .multilineTextAlignment(.center)
                .lineLimit(3)
            if let location = Self.inputSummary(node) {
                Text(location)
                    .font(.omP)
                    .foregroundStyle(Color.fontButton.opacity(0.8))
                    .lineLimit(2)
            }
        }
        .padding(.horizontal, .spacing10)
        .padding(.vertical, .spacing6)
        .frame(maxWidth: .infinity, minHeight: 148)
        .background(Self.gradient(for: node))
        .clipShape(RoundedRectangle(cornerRadius: .radius7))
        .overlay(alignment: .topLeading) {
            if let run {
                WorkflowNodeRunBadge(status: run.presentationStatus(executionStatus: executionStatus))
                    // Web .run-status top/left:.4rem (6.4px at 16px root).
                    .padding(6.4)
            }
        }
        .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 4)
        .accessibilityElement(children: run == nil ? .combine : .contain)
    }

    static func gradient(for node: WorkflowNode) -> LinearGradient {
        if node.type == .appSkillAction,
           node.config["app_id"]?.value as? String == "ai",
           node.config["skill_id"]?.value as? String == "ask" { return .primary }
        if node.type == .appSkillAction { return AppIconView.gradient(forAppId: node.config["app_id"]?.value as? String ?? "workflows") }
        return .primary
    }

    static func kind(_ node: WorkflowNode) -> String {
        if node.type == .appSkillAction,
           node.config["app_id"]?.value as? String == "ai",
           node.config["skill_id"]?.value as? String == "ask" {
            return AppStrings.workflowBuilder(.ask_ai)
        }
        switch node.type.rawValue {
        case "schedule_trigger", "manual_trigger": return AppStrings.workflowBuilder(.time_trigger)
        case "app_skill_action": return AppStrings.workflowBuilder(.use_app_skill)
        case "check", "decision": return AppStrings.workflowBuilder(.check)
        case "send_chat_message", "create_chat_report": return AppStrings.workflowBuilder(.send_message)
        default: return WorkflowValueView.displayLabel(node.type.rawValue)
        }
    }

    static func summary(_ node: WorkflowNode, skills: [WorkflowSkillChoice] = []) -> String {
        if node.type == .appSkillAction {
            if node.config["app_id"]?.value as? String == "ai",
               node.config["skill_id"]?.value as? String == "ask" {
                return AppStrings.workflowBuilder(.ask_ai)
            }
            let app = node.config["app_id"]?.value as? String ?? "App"
            let skillId = node.config["skill_id"]?.value as? String ?? ""
            let fallback = skills.first { $0.appId == app && $0.skillId == skillId }?.title ?? WorkflowValueView.displayLabel(skillId)
            let skill = translated(["apps.\(app).\(skillId)", "\(app).\(skillId)"], fallback: fallback)
            let appName = translated(["apps.\(app)", app], fallback: app.capitalized)
            return "\(appName) | \(skill)"
        }
        if node.type == .scheduleTrigger,
           let schedule = node.config["schedule"]?.value as? [String: Any] {
            let type = schedule["type"] as? String ?? "daily"
            let time = schedule["time"] as? String ?? "09:00"
            if type == "hourly" { return "\(AppStrings.workflowBuilder(.hourly)) · :\(String(format: "%02d", schedule["minute"] as? Int ?? 0))" }
            if type == "once" { return schedule["at"] as? String ?? AppStrings.workflowBuilder(.once) }
            let frequency = AppStrings.workflowBuilder(type == "weekly" ? .weekly : .daily)
            return "\(frequency), \(time)"
        }
        if node.type == .check || node.type == .decision {
            if node.config["mode"]?.value as? String == "ai" {
                return node.config["question"]?.value as? String ?? AppStrings.workflowBuilder(.ai_judgment)
            }
            let predicate = node.config["predicate"]?.value as? [String: Any] ?? [:]
            let reference = predicate["left"] as? String ?? ""
            let label = WorkflowValueView.displayLabel(reference.split(separator: ".").last.map(String.init) ?? "")
            let op = predicate["op"] as? String ?? ""
            let symbol = ["gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "ne": "≠", "neq": "≠", "contains": "∋"][op] ?? ""
            return "\(label) \(symbol) \(String(describing: predicate["right"] ?? ""))"
        }
        if node.type == .sendChatMessage || node.type == .createChatReport {
            return node.config["chat_id"]?.value as? String == nil ? AppStrings.newChat : AppStrings.workflowBuilder(.existing_chat)
        }
        return node.title ?? kind(node)
    }

    private static func translated(_ keys: [String], fallback: String) -> String {
        for key in keys {
            let value = AppStrings.localized(key)
            if value != key { return value }
        }
        return fallback
    }

    static func inputSummary(_ node: WorkflowNode) -> String? {
        guard node.type == .appSkillAction,
              let input = node.config["input"]?.value as? [String: Any]
        else { return nil }
        let request = (input["requests"] as? [[String: Any]])?.first ?? [:]
        return (input["location"] as? String)
            ?? (request["location"] as? String)
            ?? (input["city"] as? String)
            ?? (input["query"] as? String)
            ?? (request["query"] as? String)
    }

    static func checkSource(_ node: WorkflowNode, graph: WorkflowGraph?) -> WorkflowNode? {
        let predicate = node.config["predicate"]?.value as? [String: Any] ?? [:]
        let reference = predicate["left"] as? String ?? ""
        let parts = reference.split(separator: ".")
        guard parts.count > 1 else { return nil }
        return graph?.nodes.first { $0.id == String(parts[1]) && $0.type == .appSkillAction }
    }

    static func icon(_ node: WorkflowNode, graph: WorkflowGraph? = nil) -> String {
        switch node.type.rawValue {
        case "schedule_trigger", "manual_trigger": return "calendar"
        case "check", "decision":
            if let source = checkSource(node, graph: graph) {
                return AppIconView.iconName(forAppId: source.config["app_id"]?.value as? String ?? "app")
            }
            return "workflow-check"
        case "send_chat_message", "create_chat_report": return "chat"
        case "app_skill_action":
            let app = node.config["app_id"]?.value as? String ?? "app"
            let skill = node.config["skill_id"]?.value as? String ?? ""
            if app == "weather", skill == "forecast" { return "weather" }
            return AppIconView.iconName(forAppId: app)
        default: return "workflow"
        }
    }
}

private struct WorkflowNodeRunBadge: View {
    let status: String
    private var presentation: WorkflowNodeRunPresentation { .init(status: status) }
    private var copy: AppStrings.WorkflowRunCopy {
        switch presentation {
        case .completed: .status_completed
        case .failed: .status_failed
        case .cancelled: .status_cancelled
        case .skipped: .status_skipped
        case .queued: .status_queued
        case .running: .status_running
        case .cancellationRequested: .status_cancellation_requested
        case .waiting: .status_waiting
        }
    }
    var body: some View {
        Group {
            if presentation == .completed {
                Icon("check", size: 16).frame(width: .spacing12, height: .spacing12)
            } else {
                Text(AppStrings.workflowRun(copy))
                    .font(.omSmall)
                    .padding(.horizontal, .spacing4)
                    .frame(minHeight: .spacing12)
            }
        }
        .foregroundStyle(presentation == .completed || presentation == .failed ? Color.fontButton : Color.fontPrimary)
        .background(presentation == .completed ? Color.chatRainbowGreen : presentation == .failed ? Color.error : Color.grey20,
                    in: Capsule())
        .accessibilityLabel(AppStrings.workflowRun(copy))
        .accessibilityValue(status)
        .accessibilityIdentifier("workflow-run-node-status")
    }
}
