// Compact Watch adaptation of the rendered workflow node editor composition.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.workflows.compact-editor, apple-watch.handoff.exact-private
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/workflows/WorkflowGraphRenderer.svelte
//         frontend/packages/ui/src/components/workflows/WorkflowDetailPage.svelte
// CSS: WorkflowGraphRenderer.svelte: .node-summary, .editor, .connector, .branch
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

@MainActor
private enum WatchWorkflowCopy {
    static var back: String { WatchLocalization.text("common.back") }
    static var retry: String { WatchLocalization.text("common.retry") }
    static var loading: String { WatchLocalization.text("activity.syncing") }
    static var openOnPhone: String { WatchLocalization.text("watch.hub.open_on_phone") }
    static var empty: String { WatchLocalization.text("watch.workflow.empty_steps") }
    static var failure: String { WatchLocalization.text("common.detail_load_error", replacements: ["item": WatchLocalization.text("navigation.workflows")]) }
    static var configuration: String { WatchLocalization.text("watch.workflow.configuration") }
    static var branches: String { WatchLocalization.text("watch.workflow.connections") }
    static func builder(_ key: String) -> String { WatchLocalization.text("workflows.builder.\(key)") }
}

struct WatchWorkflowDetailView: View {
    let item: WatchWorkflowListItem
    let accountScope: WatchWorkflowDetailScope?
    let onClose: () -> Void
    let onOpenOnPhone: (WatchItemOpenRequest) -> Void
    let crownActive: Bool
    @ObservedObject private var service: WatchWorkflowDetailService
    @State private var expandedNodeID: String?
    @State private var editingFieldID: String?
    @State private var cards: [WatchWorkflowCard] = []
    @State private var crownScrollRevision = 0
    @Environment(\.scenePhase) private var scenePhase

    init(item: WatchWorkflowListItem, accountScope: WatchWorkflowDetailScope?,
         service: WatchWorkflowDetailService, crownActive: Bool = true, onClose: @escaping () -> Void,
         onOpenOnPhone: @escaping (WatchItemOpenRequest) -> Void) {
        self.item = item
        self.accountScope = accountScope
        self.onClose = onClose
        self.onOpenOnPhone = onOpenOnPhone
        self.service = service
        self.crownActive = crownActive
    }

    private struct Selection: Equatable { let id: String; let scope: WatchWorkflowDetailScope? }

    private var visibleState: WatchWorkflowDetailService.State {
        guard let accountScope, service.permits(accountScope) else { return .unavailable }
        if case .loaded = service.state, !service.matches(id: item.id, scope: accountScope) { return .unavailable }
        return service.state
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: .spacing2) {
                Button {
                    if editingFieldID != nil { editingFieldID = nil }
                    else if service.draft != nil { service.cancelEditing() }
                    else { service.clear(); cards = []; onClose() }
                } label: {
                    HStack(spacing: .spacing1) {
                        Icon("back", size: .iconSizeXs)
                        Text(WatchWorkflowCopy.back)
                    }
                    .font(.omXs)
                    .padding(.vertical, .spacing3)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(service.isSaving)
                .accessibilityLabel(WatchWorkflowCopy.back)
                .accessibilityIdentifier("watch-workflow-detail-back")
                Text(accountScope.map(service.permits) == true ? item.title : WatchLocalization.text("navigation.workflows"))
                    .font(.omXs).fontWeight(.semibold)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("watch-workflow-detail-title")
            }
            .padding(.horizontal, .spacing3)
            ScrollViewReader { proxy in
                WatchCrownScrollView(
                    active: crownActive && editingFieldID == nil && !service.isSaving &&
                        service.matches(id: item.id, scope: accountScope),
                    identity: item.id, externalScrollRevision: crownScrollRevision
                ) {
                    LazyVStack(spacing: .spacing3) {
                        if let draft = service.draft, service.matches(id: item.id, scope: accountScope) {
                            editor(draft).id("workflow-editor")
                        } else {
                        switch visibleState {
                        case .idle, .loading:
                            ProgressView().tint(Color.grey0).accessibilityLabel(WatchWorkflowCopy.loading)
                                .accessibilityIdentifier("watch-workflow-detail-loading")
                        case .failed, .unavailable:
                            Text(WatchWorkflowCopy.failure).font(.omXs)
                                .accessibilityIdentifier("watch-workflow-detail-error")
                            Button(WatchWorkflowCopy.retry) { Task { await reload() } }
                                .buttonStyle(.plain).padding(.spacing2)
                                .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius4))
                                .accessibilityIdentifier("watch-workflow-detail-retry")
                        case let .loaded(detail):
                            Text(WatchWorkflowCopy.builder(detail.enabled ? "enabled" : "workflow_off"))
                                .font(.omMicro).foregroundStyle(Color.grey30)
                                .accessibilityIdentifier("watch-workflow-detail-status")
                            if let description = detail.description, !description.isEmpty {
                                Text(description).font(.omXs).frame(maxWidth: .infinity, alignment: .leading)
                                    .accessibilityIdentifier("watch-workflow-detail-description")
                            }
                            if cards.isEmpty {
                                Text(WatchWorkflowCopy.empty).font(.omXs)
                                    .accessibilityIdentifier("watch-workflow-detail-empty")
                            }
                            ForEach(cards) { card in nodeCard(card).id(card.id) }
                            Button(WatchWorkflowCopy.openOnPhone) { onOpenOnPhone(item.openRequest) }
                                .font(.omXs).buttonStyle(.plain)
                                .padding(.spacing3)
                                .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius4))
                                .accessibilityIdentifier("watch-workflow-detail-open-on-phone")
                        }
                        }
                    }
                    .padding(.horizontal, .spacing1)
                    .padding(.bottom, .spacing5)
                }
                .accessibilityIdentifier("watch-workflow-detail-scroll")
                .onChange(of: expandedNodeID) { _, id in
                    // Keep the selected header and its primary action together on
                    // the small viewport when a lazy card changes height.
                    if let id {
                        crownScrollRevision &+= 1
                        proxy.scrollTo(id, anchor: .top)
                    }
                }
                .onChange(of: service.draft?.id) { oldID, id in
                    editingFieldID = nil
                    crownScrollRevision &+= 1
                    if id != nil { proxy.scrollTo("workflow-editor", anchor: .top) }
                    else if let oldID { proxy.scrollTo(oldID, anchor: .top) }
                }
                .onChange(of: editingFieldID) { _, _ in
                    crownScrollRevision &+= 1
                    proxy.scrollTo("workflow-editor", anchor: .top)
                }
            }
            if service.draft != nil, service.matches(id: item.id, scope: accountScope) {
                editorFooter
            }
        }
        // Match the Watch task palette: the Watch canvas uses the catalogue's
        // white foreground and dark surfaces directly. A colorScheme override
        // does not reliably select the catalogue's semantic font variants here.
        .foregroundStyle(Color.grey0)
        .background(Color.grey100)
        .task(id: Selection(id: item.id, scope: accountScope)) {
            await reload()
            guard !Task.isCancelled else { return }
        }
        .onChange(of: service.state) { _, _ in refreshCards() }
        .onDisappear { service.clear(); cards = []; expandedNodeID = nil; editingFieldID = nil }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, let accountScope, !service.permits(accountScope) {
                service.clear(); cards = []; expandedNodeID = nil
            }
        }
    }

    private func reload() async {
        cards = []
        expandedNodeID = nil
        await service.load(id: item.id, scope: accountScope)
        refreshCards()
    }

    private func refreshCards() {
        guard service.matches(id: item.id, scope: accountScope), case let .loaded(detail) = service.state else { cards = []; return }
        cards = WatchWorkflowCard.make(nodes: service.orderedNodes, edges: detail.graph.edges)
    }

    private func editor(_ draft: WatchWorkflowNodeDraft) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(WatchLocalization.text("common.edit")).font(.omXs).fontWeight(.semibold)
                .accessibilityIdentifier("watch-workflow-editor-title")
            if let editingFieldID, let field = draft.fields.first(where: { $0.id == editingFieldID }) {
                // Text entry is deliberate: scrolling the field list never
                // passes over a live Watch input or opens its OS keyboard.
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(fieldLabel(field.path)).font(.omMicro).foregroundStyle(Color.grey30)
                    TextField(fieldLabel(field.path), text: Binding(
                        get: { service.draft?.fields.first(where: { $0.id == field.id })?.value ?? field.value },
                        set: { changeField(field.id, value: $0) }
                    ), axis: .vertical)
                    .font(.omXs).textFieldStyle(.plain).padding(.spacing3)
                    .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius3))
                    .accessibilityIdentifier("watch-workflow-edit-field-\(field.id)")
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("watch-workflow-field-editor")
                .disabled(service.isSaving)
            } else {
                // Compact choices come before lengthy text values. Preserve
                // the original order within each group and stable field IDs.
                ForEach(draft.fields.filter { if case .bool = $0.original { return true }; return false }) { field in
                    Button { changeField(field.id, value: field.value == "true" ? "false" : "true") } label: {
                        HStack(spacing: .spacing2) {
                            Text(fieldLabel(field.path)).font(.omMicro).lineLimit(2)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Text(WatchWorkflowCopy.builder(field.value == "true" ? "true" : "false"))
                                .font(.omXs)
                        }
                        .frame(minHeight: .spacing20)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(fieldLabel(field.path))
                    .accessibilityValue(WatchWorkflowCopy.builder(field.value == "true" ? "true" : "false"))
                    .accessibilityIdentifier("watch-workflow-edit-field-\(field.id)")
                    .disabled(service.isSaving)
                }
                ForEach(draft.fields.filter { if case .bool = $0.original { return false }; return true }) { field in
                    Button { editingFieldID = field.id } label: {
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(fieldLabel(field.path)).font(.omMicro).foregroundStyle(Color.grey30)
                            Text(field.value).font(.omXs).lineLimit(2)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.spacing3)
                        .frame(maxWidth: .infinity, minHeight: .spacing20, alignment: .leading)
                        .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius3))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-workflow-choose-field-\(field.id)")
                    .disabled(service.isSaving)
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-workflow-editor")
    }

    private var editorFooter: some View {
        VStack(spacing: .spacing2) {
            if let error = service.saveError {
                Text(saveErrorText(error)).font(.omMicro).foregroundStyle(Color.error)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("watch-workflow-save-error")
            }
            HStack(spacing: .spacing2) {
                Button(WatchWorkflowCopy.builder(service.isSaving ? "saving" : "save")) {
                    Task { if await service.save() { refreshCards() } }
                }
                .font(.omXs).buttonStyle(.plain)
                .frame(maxWidth: .infinity, minHeight: .spacing20)
                .foregroundStyle(Color.fontButton)
                .background(Color.buttonPrimary, in: RoundedRectangle(cornerRadius: .radius4))
                .disabled(service.isSaving)
                .accessibilityIdentifier("watch-workflow-save")
                Button(WatchLocalization.text("common.cancel")) { service.cancelEditing() }
                    .font(.omXs).buttonStyle(.plain)
                    .frame(maxWidth: .infinity, minHeight: .spacing20)
                    .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius4))
                    .disabled(service.isSaving)
                    .accessibilityIdentifier("watch-workflow-cancel")
            }
        }
        .padding(.spacing3)
        .background(Color.grey100)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-workflow-editor-footer")
    }

    private func changeField(_ id: String, value: String) {
        guard !service.isSaving, var draft = service.draft,
              let index = draft.fields.firstIndex(where: { $0.id == id }) else { return }
        draft.fields[index].value = value
        service.draft = draft
    }

    private func fieldLabel(_ path: [String]) -> String {
        switch path.joined(separator: ".") {
        case "title": return WatchLocalization.text("watch.workflow.node_title")
        case "config.title": return WatchWorkflowCopy.builder("chat_title")
        case "config.schedule.type": return WatchWorkflowCopy.builder("repeat")
        case "config.schedule.time": return WatchWorkflowCopy.builder("time")
        case "config.schedule.timezone": return WatchWorkflowCopy.builder("timezone")
        case "config.input.prompt": return WatchWorkflowCopy.builder("ask_ai_question")
        case "config.question": return WatchWorkflowCopy.builder("ai_check_question")
        case "config.message": return WatchWorkflowCopy.builder("message_question")
        case "config.predicate.left": return WatchWorkflowCopy.builder("select_check_source")
        case "config.predicate.op": return WatchWorkflowCopy.builder("compare_type")
        case "config.predicate.right": return WatchWorkflowCopy.builder("compare_value")
        default: return path.dropFirst().map { $0.replacingOccurrences(of: "_", with: " ").capitalized }.joined(separator: " · ")
        }
    }

    private func saveErrorText(_ error: WatchWorkflowEditingError) -> String {
        switch error {
        case .invalidDraft: return WatchLocalization.text("watch.workflow.invalid_fields")
        case .changed: return WatchLocalization.text("watch.workflow.changed")
        default: return WatchWorkflowCopy.builder("save_failed")
        }
    }

    private func nodeCard(_ card: WatchWorkflowCard) -> some View {
        VStack(spacing: 0) {
            Button {
                expandedNodeID = expandedNodeID == card.id ? nil : card.id
            } label: {
                VStack(spacing: .spacing1) {
                    HStack(spacing: .spacing2) {
                        Icon(card.icon, size: .iconSizeSm)
                        Text(card.kind).font(.omMicro)
                        Spacer(minLength: 0)
                        Icon(expandedNodeID == card.id ? "up" : "down", size: .iconSizeXs)
                    }
                    Text(card.title).font(.omSmall).fontWeight(.semibold)
                        .frame(maxWidth: .infinity, alignment: .leading).fixedSize(horizontal: false, vertical: true)
                }
                .padding(.spacing3)
                .foregroundStyle(Color.fontButton)
                .background(card.gradient)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("watch-workflow-node-\(card.id)")
            .accessibilityValue(WatchWorkflowCopy.builder(expandedNodeID == card.id ? "collapse" : "details"))
            if expandedNodeID == card.id {
                VStack(alignment: .leading, spacing: .spacing2) {
                    if card.editable {
                        Button(WatchLocalization.text("common.edit")) { service.beginEditing(nodeID: card.id) }
                            .buttonStyle(.plain).font(.omXs).padding(.spacing3)
                            .frame(maxWidth: .infinity, minHeight: .spacing20)
                            .background(Color.grey80, in: RoundedRectangle(cornerRadius: .radius4))
                            .accessibilityIdentifier("watch-workflow-edit-\(card.id)")
                    }
                    ForEach(card.sections) { section in
                        Text(section.title).font(.omMicro).fontWeight(.semibold)
                            .foregroundStyle(Color.grey30)
                        ForEach(section.fields) { field in
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(field.label).font(.omMicro).foregroundStyle(Color.grey30)
                                Text(field.value).font(.omXs)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityIdentifier("watch-workflow-field-\(card.id)-\(field.id)")
                        }
                    }
                    if card.sections.isEmpty { Text(WatchWorkflowCopy.builder("do_nothing")).font(.omXs) }
                }
                .padding(.spacing3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.grey90)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("watch-workflow-node-expanded-\(card.id)")
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
    }
}

/// Build once per successful load, never decode or traverse JSON in SwiftUI body.
@MainActor
private struct WatchWorkflowCard: Identifiable {
    struct Field: Identifiable { let id: String; let label: String; let value: String }
    struct Section: Identifiable { let id: String; let title: String; let fields: [Field] }
    let id: String
    let title: String
    let kind: String
    let icon: String
    let gradient: LinearGradient
    let editable: Bool
    let sections: [Section]

    static func make(nodes: [WatchWorkflowNode], edges: [WatchWorkflowEdge]) -> [Self] {
        let titles = Dictionary(uniqueKeysWithValues: nodes.map { ($0.id, title($0)) })
        return nodes.map { node in
            let appID = node.config["app_id"]?.text ?? ""
            let kindKey: String
            let icon: String
            let gradient: LinearGradient
            if node.type.hasSuffix("_trigger") { kindKey = node.type == "schedule_trigger" ? "time_trigger" : "trigger"; icon = "calendar"; gradient = .primary }
            else if node.isAskAI { kindKey = "ask_ai"; icon = "ai"; gradient = .appAi }
            else if ["check", "decision"].contains(node.type) { kindKey = "check"; icon = "workflow-check"; gradient = .primary }
            else if ["send_chat_message", "create_chat_report", "start_new_chat"].contains(node.type) { kindKey = "send_message"; icon = "chat"; gradient = .appMessages }
            else { kindKey = "use_app_skill"; icon = "\(appID.isEmpty ? "apps" : appID)"; let colors = AppGradientPalette.colors(for: appID); gradient = .omGradient(start: colors.start, end: colors.end) }

            var sections: [Section] = []
            @MainActor func add(_ id: String, _ heading: String, _ values: [String: WatchWorkflowValue]) {
                let fields = flatten(values, titles: titles)
                if !fields.isEmpty { sections.append(Section(id: id, title: heading, fields: fields)) }
            }
            if case let .object(input) = node.config["input"] { add("input", WatchWorkflowCopy.builder("input"), input) }
            add("mapping", WatchWorkflowCopy.builder("input"), node.inputMapping)
            add("config", WatchWorkflowCopy.configuration, node.config.filter { !["input", "app_id", "skill_id"].contains($0.key) })
            let connections = edges.enumerated().filter { $0.element.from == node.id }.map { index, edge in
                let key: String
                switch edge.branch {
                case "true", "yes": key = "if_true"
                case "false", "no": key = "else"
                case "unsure": key = "if_unsure"
                default: key = "then"
                }
                return Field(id: "edge-\(index)", label: WatchWorkflowCopy.builder(key), value: titles[edge.to] ?? edge.to)
            }
            if !connections.isEmpty { sections.append(Section(id: "connections", title: WatchWorkflowCopy.branches, fields: connections)) }
            return Self(id: node.id, title: title(node), kind: kindKey == "trigger" ? WatchLocalization.text("watch.workflow.trigger") : WatchWorkflowCopy.builder(kindKey), icon: icon, gradient: gradient, editable: node.editable, sections: sections)
        }
    }

    private static func title(_ node: WatchWorkflowNode) -> String {
        if let title = node.title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return title }
        if node.isAskAI { return WatchWorkflowCopy.builder("ask_ai") }
        if node.type == "app_skill_action" {
            return [node.config["app_id"]?.text, node.config["skill_id"]?.text].compactMap { $0 }.map(humanize).joined(separator: " · ")
        }
        switch node.type {
        case "schedule_trigger": return WatchWorkflowCopy.builder("time_trigger")
        case "check", "decision": return WatchWorkflowCopy.builder("check")
        case "send_chat_message", "create_chat_report", "start_new_chat": return WatchWorkflowCopy.builder("send_message")
        default: return humanize(node.type)
        }
    }

    private static func flatten(_ values: [String: WatchWorkflowValue], titles: [String: String]) -> [Field] {
        var fields: [Field] = []
        let priority = ["schedule", "mode", "predicate", "question", "prompt", "model", "chat_id", "chat_title", "message", "summary"]
        func visit(_ value: WatchWorkflowValue, path: String) {
            switch value {
            case let .object(object):
                for key in object.keys.sorted() { visit(object[key]!, path: path + "." + key) }
            case let .array(array):
                for (index, entry) in array.enumerated() { visit(entry, path: path + ".\(index + 1)") }
            default:
                let text: String
                switch value {
                case let .string(string): text = string
                case let .number(number): text = number.formatted(.number.grouping(.never))
                case let .integer(number): text = String(number)
                case let .unsigned(number): text = String(number)
                case let .bool(boolean): text = WatchWorkflowCopy.builder(boolean ? "true" : "false")
                default: text = "—"
                }
                guard !text.isEmpty else { return }
                // Resolve stored output references to the visible node titles.
                var readable = text
                for (id, title) in titles.sorted(by: { $0.key.count > $1.key.count }) {
                    readable = readable.replacingOccurrences(of: "$nodes.\(id).", with: "\(title) · ")
                    readable = readable.replacingOccurrences(of: "steps.\(id).", with: "\(title) · ")
                }
                fields.append(Field(id: path, label: path.split(separator: ".").map { humanize(String($0)) }.joined(separator: " · "), value: readable))
            }
        }
        for key in values.keys.sorted(by: {
            let lhs = priority.firstIndex(of: $0) ?? priority.count
            let rhs = priority.firstIndex(of: $1) ?? priority.count
            return lhs == rhs ? $0 < $1 : lhs < rhs
        }) { visit(values[key]!, path: key) }
        return fields
    }

    private static func humanize(_ key: String) -> String { key.replacingOccurrences(of: "_", with: " ").capitalized }
}

#if DEBUG
/// Uses the production detail/editor controls with an injected local transport.
struct WatchWorkflowUITestFixtureView: View {
    @StateObject private var service: WatchWorkflowDetailService
    @State private var selected = true
    @State private var openedItem: WatchItemOpenRequest?
    init(failFirstRead: Bool = false, failFirstSave: Bool = false, empty: Bool = false) {
        _service = StateObject(wrappedValue: WatchWorkflowDetailFixtures.service(
            failFirstRead: failFirstRead, failFirstSave: failFirstSave, empty: empty))
    }
    var body: some View {
        if selected {
            WatchWorkflowDetailView(item: WatchWorkflowDetailFixtures.item(),
                accountScope: WatchWorkflowDetailFixtures.scope, service: service,
                onClose: { selected = false }, onOpenOnPhone: { openedItem = $0 })
        } else {
            Button(WatchWorkflowDetailFixtures.item().title) { selected = true }
                .buttonStyle(.plain).accessibilityIdentifier("watch-workflow-row-workflow-one")
        }
        if let openedItem {
            Text("\(openedItem.kind.rawValue):\(openedItem.id)")
                .accessibilityIdentifier("watch-ui-test-open-request")
        }
    }
}
#endif
