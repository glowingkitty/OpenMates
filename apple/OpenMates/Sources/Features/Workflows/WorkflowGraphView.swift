// Native workflow graph and focused step editor.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/workflows/WorkflowGraphRenderer.svelte
//          frontend/packages/ui/src/components/workflows/WorkflowGraphRenderer.preview.ts
// CSS:     WorkflowGraphRenderer.svelte .graph-panel, .node-stack,
//          .node-summary, .branch-group, .editor
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.mvp.steps, workflows.control.check,
//             workflows.control.typed-data

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

struct WorkflowGraphView: View {
    @ObservedObject private var offlineStore = OfflineStore.shared
    @ObservedObject private var teamContext = TeamWorkspaceContext.shared
    let graph: WorkflowGraph
    var readOnly = false
    var nodeRuns: [WorkflowNodeRun] = []
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
    @State private var choosingChat = false

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
        .frame(maxWidth: 960)
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing8)
        .frame(maxWidth: .infinity, alignment: .center)
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-node-stack")
        .task(id: "\(workflowId ?? "")|\(accountId ?? "")|\(offlineStore.scopeGeneration)|\(teamContext.contextEpoch)") {
            stepTest.reset(accountId: accountId)
            askHints.reset(accountId: accountId)
        }
        .onChange(of: teamContext.contextEpoch) { _, _ in
            editingNodeId = nil
            draftNewNode = nil
            draftConfig = [:]
            askHints.reset(accountId: nil)
        }
        .onDisappear { askHints.reset(accountId: nil) }
    }

    @ViewBuilder
    private func step(_ node: WorkflowNode) -> some View {
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
                    askHints.reset(accountId: accountId)
                    if isAskAI(node) {
                        scheduleAskHints(for: node, instruction: askInstruction)
                    }
                }
            } label: {
                WorkflowStepSummary(node: node, run: nodeRuns.first { $0.nodeId == node.id })
                    .frame(maxWidth: editingNodeId == node.id ? 672 : 304)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier(isAskAI(node) ? "workflow-ask-ai-node" : "workflow-node-summary")
            .accessibilityValue(editingNodeId == node.id ? "expanded" : "collapsed")
            .draggable(node.id)

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
                }
            }
        }
        .frame(maxWidth: .infinity)
        .dropDestination(for: String.self) { items, _ in
            guard !readOnly, let sourceId = items.first,
                  let next = WorkflowGraphReordering.moveAfter(graph, sourceId: sourceId, afterId: node.id)
            else { return false }
            Task { await persistReorder(next) }
            return true
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-node-card")
    }

    @ViewBuilder
    private func editor(for node: WorkflowNode) -> some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            HStack {
                Button {
                    if choosingChat {
                        choosingChat = false
                        if draftNewNode?.id == node.id { draftNewNode = nil; editingNodeId = nil }
                    } else {
                        editingNodeId = nil
                        if draftNewNode?.id == node.id { draftNewNode = nil }
                    }
                } label: { Icon("back", size: 20) }
                .accessibilityLabel(AppStrings.workflowBuilder(.close))
                Spacer()
                Text(WorkflowStepSummary.kind(node))
                    .font(.omP.weight(.semibold))
                Spacer()
                if onSave != nil && draftNewNode?.id != node.id {
                    Button {
                        Task { await move(node, direction: .up) }
                    } label: { Icon("up", size: 18) }
                    .disabled(saving || !WorkflowGraphReordering.canMove(graph, nodeId: node.id, direction: .up))
                    .accessibilityLabel(AppStrings.workflowBuilder(.move_up))
                    .accessibilityIdentifier("workflow-move-step-up")
                    Button {
                        Task { await move(node, direction: .down) }
                    } label: { Icon("down", size: 18) }
                    .disabled(saving || !WorkflowGraphReordering.canMove(graph, nodeId: node.id, direction: .down))
                    .accessibilityLabel(AppStrings.workflowBuilder(.move_down))
                    .accessibilityIdentifier("workflow-move-step-down")
                }
                Button {
                    if deleteArmed { Task { await remove(node) } }
                    else { deleteArmed = true }
                } label: { Icon("delete", size: 20) }
                .accessibilityLabel(AppStrings.workflowBuilder(deleteArmed ? .confirm_delete_node : .delete_node))
                .accessibilityIdentifier("workflow-delete-node")
                Button {
                    editingNodeId = nil
                    choosingChat = false
                    draftConfig = node.config
                    if draftNewNode?.id == node.id { draftNewNode = nil }
                } label: { Icon("close", size: 20) }
                .accessibilityLabel(AppStrings.cancel)
            }

            if node.type != .sendChatMessage && node.type != .createChatReport && !choosingChat {
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
                        Text(AppStrings.workflowBuilder(.message_question))
                            .font(.omP.weight(.semibold))
                        Button {
                            choosingChat = true
                        } label: {
                            Text("\(AppStrings.workflowBuilder(.to)): \(messageDestinationTitle)")
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("workflow-message-destination")
                        TextField(AppStrings.workflowBuilder(.chat_title), text: Binding(
                            get: { draftConfig["title"]?.value as? String ?? "" },
                            set: { draftConfig["title"] = AnyCodable($0) }
                        ))
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("workflow-message-title")
                        WorkflowMessageTemplateEditor(
                            value: Binding(
                                get: { draftConfig["message"]?.value as? String ?? "" },
                                set: { draftConfig["message"] = AnyCodable($0) }
                            ),
                            outputs: previousOutputs(before: node.id).map {
                                WorkflowMessageOutput(reference: $0.id, label: $0.label, appId: nil)
                            },
                            placeholder: AppStrings.workflowBuilder(.send_message)
                        )
                    }
                    messagePreviewControls(for: node)
                }
            }

            if !choosingChat {
                HStack {
                    Button(AppStrings.cancel) {
                        editingNodeId = nil
                        draftConfig = node.config
                        if draftNewNode?.id == node.id { draftNewNode = nil }
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    Spacer()
                    Button {
                        Task { await save(node) }
                    } label: {
                        Text(AppStrings.workflowBuilder(.save))
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(saving || (isAskAI(node) && askVerdict.blocksSave))
                    .accessibilityIdentifier("workflow-node-save")
                }
            }

            if let editError {
                Text(editError)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
            }
        }
        .padding(.spacing5)
        .frame(maxWidth: 672, alignment: .leading)
        .background(Color.grey10)
        .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: .radius6, bottomTrailingRadius: .radius6))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-node-expanded")
    }

    private var scheduleFields: some View {
        let schedule = dictionary(draftConfig["schedule"])
        return VStack(alignment: .leading, spacing: .spacing3) {
            Text(AppStrings.workflowBuilder(.repeat)).font(.omP.weight(.semibold))
            Picker(AppStrings.workflowBuilder(.repeat), selection: Binding(
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
            )) {
                Text(AppStrings.workflowBuilder(.once)).tag("once")
                Text(AppStrings.workflowBuilder(.hourly)).tag("hourly")
                Text(AppStrings.workflowBuilder(.daily)).tag("daily")
                Text(AppStrings.workflowBuilder(.weekly)).tag("weekly")
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("workflow-time-trigger-schedule")

            if schedule["type"] as? String == "once" {
                TextField(AppStrings.workflowBuilder(.date_time), text: scheduleBinding("at"))
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibilityIdentifier("workflow-schedule-at")
            } else if schedule["type"] as? String == "hourly" {
                Stepper(value: Binding(
                    get: { schedule["minute"] as? Int ?? 0 },
                    set: { setSchedule("minute", value: $0) }
                ), in: 0...59) {
                    Text("\(AppStrings.workflowBuilder(.minute)): \(schedule["minute"] as? Int ?? 0)")
                }
                .accessibilityIdentifier("workflow-schedule-minute")
            } else {
                TextField(AppStrings.workflowBuilder(.date_time), text: scheduleBinding("time"))
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibilityIdentifier("workflow-schedule-time")
            }

            TextField(AppStrings.workflowBuilder(.timezone), text: scheduleBinding("timezone"))
                .textFieldStyle(OMTextFieldStyle())
                .accessibilityIdentifier("workflow-schedule-timezone")

            if schedule["type"] as? String == "weekly" {
                let days: [(String, AppStrings.WorkflowBuilderCopy)] = [
                    ("monday", .monday), ("tuesday", .tuesday), ("wednesday", .wednesday),
                    ("thursday", .thursday), ("friday", .friday), ("saturday", .saturday),
                    ("sunday", .sunday)
                ]
                ForEach(days, id: \.0) { day, key in
                    Toggle(AppStrings.workflowBuilder(key), isOn: Binding(
                        get: { (dictionary(draftConfig["schedule"])["weekdays"] as? [String] ?? []).contains(day) },
                        set: { enabled in
                            var selected = dictionary(draftConfig["schedule"])["weekdays"] as? [String] ?? []
                            if enabled && !selected.contains(day) { selected.append(day) }
                            if !enabled { selected.removeAll { $0 == day } }
                            setSchedule("weekdays", value: selected)
                        }
                    ))
                }
            }
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
            Text(AppStrings.workflowBuilder(askAI ? .ask_ai_question : .input))
                .font(.omP.weight(.semibold))
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
                    placeholder: AppStrings.workflowBuilder(.ask_ai_placeholder)
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
                                        timezone: dictionary(draftConfig["schedule"])["timezone"] as? String ?? TimeZone.current.identifier)
            } else {
                ForEach(input.keys.sorted(), id: \.self) { key in
                    if let boolean = input[key] as? Bool {
                        Toggle(WorkflowValueView.displayLabel(key), isOn: Binding(
                            get: { (dictionary(draftConfig["input"])[key] as? Bool) ?? boolean },
                            set: { setInput(key, value: $0) }
                        ))
                        .accessibilityIdentifier("workflow-input-\(key)")
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

            testControls(for: node, capability: capability)

            Button(AppStrings.workflowBuilder(showOutputFields ? .hide_output_fields : .show_output_fields)) {
                showOutputFields.toggle()
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("workflow-show-output-fields")
            if showOutputFields {
                HStack {
                    Text(AppStrings.workflowBuilder(.output))
                    .font(.omP.weight(.semibold))
                    Spacer()
                    Text(AppStrings.workflowBuilder(stepTest.outputsByNode[node.id] == nil ? .example : .test_output))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                }
                if stepTest.activeNodeId == node.id && stepTest.status == .processing {
                    ProgressView(AppStrings.workflowBuilder(.processing))
                        .accessibilityIdentifier("workflow-test-output-loading")
                } else if let tested = stepTest.outputsByNode[node.id] {
                    WorkflowValueView(value: tested.mapValues(\.value), appId: appId)
                        .accessibilityIdentifier("workflow-output-fields")
                } else {
                    let properties = capability?.outputSchema["properties"]?.value as? [String: Any] ?? [:]
                    ForEach(properties.keys.sorted(), id: \.self) { key in
                        let field = properties[key] as? [String: Any] ?? [:]
                        HStack {
                            Text(field["title"] as? String ?? WorkflowValueView.displayLabel(key))
                            Spacer()
                            Text(field["type"] as? String ?? "")
                                .foregroundStyle(Color.fontSecondary)
                        }
                        .font(.omSmall)
                    }
                }
            }
        }
    }

    private func checkFields(for node: WorkflowNode) -> some View {
        let predicate = dictionary(draftConfig["predicate"])
        let outputs = previousOutputs(before: node.id)
        let selected = outputs.first { $0.id == predicate["left"] as? String }
        let number = selected?.type == "number" || selected?.type == "integer"
        let boolean = selected?.type == "boolean"
        let operators: [(String, AppStrings.WorkflowBuilderCopy)] = number
            ? [("eq", .operator_eq), ("ne", .operator_ne), ("gt", .operator_gt),
               ("gte", .operator_gte), ("lt", .operator_lt), ("lte", .operator_lte)]
            : boolean ? [("eq", .operator_eq), ("ne", .operator_ne)]
            : [("eq", .operator_eq), ("ne", .operator_ne), ("contains", .operator_contains)]
        return VStack(alignment: .leading, spacing: .spacing3) {
            Text(AppStrings.workflowBuilder(.check_question))
                .font(.omP.weight(.semibold))
            Picker(AppStrings.workflowBuilder(.check_mode), selection: Binding(
                get: { draftConfig["mode"]?.value as? String ?? "exact" },
                set: { draftConfig["mode"] = AnyCodable($0) }
            )) {
                Text(AppStrings.workflowBuilder(.exact_rule)).tag("exact")
                Text(AppStrings.workflowBuilder(.ai_judgment)).tag("ai")
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("workflow-check-mode")

            if draftConfig["mode"]?.value as? String == "ai" {
                textField(key: "question", label: AppStrings.workflowBuilder(.ai_check_question), multiline: true)
            } else {
                Text(AppStrings.workflowBuilder(.if)).font(.omP.weight(.semibold))
                Picker(AppStrings.workflowBuilder(.select_output), selection: Binding(
                    get: { predicate["left"] as? String ?? "" },
                    set: { setPredicate("left", value: $0); setPredicate("op", value: "") }
                )) {
                    Text(AppStrings.workflowBuilder(.select_output)).tag("")
                    ForEach(outputs) { output in Text(output.label).tag(output.id) }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("workflow-check-output")
                if selected != nil {
                    Picker(AppStrings.workflowBuilder(.compare_type), selection: Binding(
                        get: { predicate["op"] as? String ?? "" },
                        set: { setPredicate("op", value: $0) }
                    )) {
                        Text(AppStrings.workflowBuilder(.compare_type)).tag("")
                        ForEach(operators, id: \.0) { op, label in
                            Text(AppStrings.workflowBuilder(label)).tag(op)
                        }
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("workflow-check-operator")
                }
                if let op = predicate["op"] as? String, !op.isEmpty {
                    if boolean {
                        Picker(AppStrings.workflowBuilder(.compare_value), selection: Binding(
                            get: { predicate["right"] as? Bool ?? true },
                            set: { setPredicate("right", value: $0) }
                        )) {
                            Text(AppStrings.workflowBuilder(.true)).tag(true)
                            Text(AppStrings.workflowBuilder(.false)).tag(false)
                        }
                        .pickerStyle(.menu)
                    } else {
                        TextField(AppStrings.workflowBuilder(.compare_value), text: Binding(
                            get: { String(describing: dictionary(draftConfig["predicate"])["right"] ?? "") },
                            set: { setPredicate("right", value: number ? (Double($0) ?? 0) as Any : $0) }
                        ))
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("workflow-check-value")
                    }
                }
            }
            testControls(for: node)
            if let matched = stepTest.outputsByNode[node.id]?["matched"]?.value as? Bool {
                Text("\(AppStrings.workflowBuilder(.test_output)): \(AppStrings.workflowBuilder(matched ? .true : .false))")
                    .font(.omP)
                    .accessibilityIdentifier("workflow-check-test-result")
            }
        }
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
                        if node.type == .appSkillAction || draftConfig["mode"]?.value as? String == "ai" {
                            Icon("coins", size: 14)
                            Text(capability?.fixedCreditCost.map(String.init) ??
                                 (node.type == .check ? "1" : AppStrings.workflowBuilder(.variable_cost)))
                        }
                    }
                }
                .buttonStyle(.plain)
                .disabled(workflowId == nil || accountId == nil || accountId == "workflow-preview"
                          || saving || !canTest(node, capability: capability))
                .accessibilityIdentifier("workflow-test-action")
            }
        }
        if stepTest.activeNodeId == node.id, let error = stepTest.errorMessage {
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
                guard type != "object", type != "array" else { return nil }
                return WorkflowOutputChoice(id: "$nodes.\(node.id).output.\(key)",
                    label: "\(node.title ?? appId.capitalized) · \(field["title"] as? String ?? WorkflowValueView.displayLabel(key))",
                    type: type)
            }
        }
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
        }.map { WorkflowMessageOutput(reference: $0.id, label: $0.label, appId: nil) }
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

    private var appId: String {
        node.config["app_id"]?.value as? String ?? "workflows"
    }

    var body: some View {
        VStack(spacing: .spacing2) {
            Icon(Self.icon(node), size: 33)
                .foregroundStyle(Color.grey0)
            Text(Self.kind(node))
                .font(.omSmall)
                .foregroundStyle(Color.grey0.opacity(0.9))
            Text(Self.summary(node))
                .font(.omP.weight(.bold))
                .foregroundStyle(Color.grey0)
                .multilineTextAlignment(.center)
                .lineLimit(3)
            if let location = Self.inputSummary(node) {
                Text(location)
                    .font(.omP)
                    .foregroundStyle(Color.grey0.opacity(0.85))
                    .lineLimit(2)
            }
            if let run {
                Text(run.status.capitalized)
                    .font(.omTiny.weight(.semibold))
                    .foregroundStyle(Color.grey0)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 148)
        .padding(.horizontal, .spacing5)
        .background(gradient)
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 4)
        .accessibilityElement(children: .combine)
    }

    private var gradient: LinearGradient {
        if node.type == .appSkillAction { return AppIconView.gradient(forAppId: appId) }
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

    static func summary(_ node: WorkflowNode) -> String {
        if node.type == .appSkillAction {
            if node.config["app_id"]?.value as? String == "ai",
               node.config["skill_id"]?.value as? String == "ask" {
                return AppStrings.workflowBuilder(.ask_ai)
            }
            let app = node.config["app_id"]?.value as? String ?? "App"
            let skill = node.title ?? (node.config["skill_id"]?.value as? String ?? "Skill")
            return "\(app.capitalized) | \(skill)"
        }
        if node.type == .scheduleTrigger,
           let schedule = node.config["schedule"]?.value as? [String: Any] {
            let type = schedule["type"] as? String ?? "daily"
            let time = schedule["time"] as? String ?? "09:00"
            return "\(type.capitalized), \(time)"
        }
        return node.title ?? kind(node)
    }

    static func inputSummary(_ node: WorkflowNode) -> String? {
        guard node.type == .appSkillAction,
              let input = node.config["input"]?.value as? [String: Any]
        else { return nil }
        return (input["location"] as? String)
            ?? (input["city"] as? String)
            ?? (input["query"] as? String)
    }

    static func icon(_ node: WorkflowNode) -> String {
        switch node.type.rawValue {
        case "schedule_trigger", "manual_trigger": return "calendar"
        case "check", "decision": return "workflow-check"
        case "send_chat_message", "create_chat_report": return "chat"
        case "app_skill_action":
            let app = node.config["app_id"]?.value as? String ?? "app"
            let skill = node.config["skill_id"]?.value as? String ?? ""
            if app == "weather", skill == "forecast" { return "weather" }
            return app
        default: return "workflow"
        }
    }
}
