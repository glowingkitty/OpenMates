// Compact Watch workflow reads and edits using the existing graph update API.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.workflows.compact-editor, apple-watch.lists.read-only-private
import Combine
import Foundation

struct WatchWorkflowDetailScope: Equatable, Sendable {
    let accountID: String
    let profile: ServerProfile
    let generation: UInt64
    let teamID: String?
    @MainActor static func capture(accountID: String, teamID: String? = nil) -> Self {
        Self(accountID: accountID, profile: ServerProfile.current(), generation: WatchChatAccountLifecycle.generation, teamID: teamID)
    }
}

/// Preserve the full JSON tree, including unknown keys and large integers.
indirect enum WatchWorkflowValue: Codable, Equatable, Sendable {
    case string(String), integer(Int64), unsigned(UInt64), number(Double), bool(Bool)
    case object([String: Self]), array([Self]), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode(Int64.self) { self = .integer(v) }
        else if let v = try? c.decode(UInt64.self) { self = .unsigned(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode([String: Self].self) { self = .object(v) }
        else { self = .array(try c.decode([Self].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case let .string(v): try c.encode(v)
        case let .integer(v): try c.encode(v)
        case let .unsigned(v): try c.encode(v)
        case let .number(v): try c.encode(v)
        case let .bool(v): try c.encode(v)
        case let .object(v): try c.encode(v)
        case let .array(v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    var text: String? { if case let .string(v) = self { return v }; return nil }
    var object: [String: Self] { if case let .object(v) = self { return v }; return [:] }
    var array: [Self] { if case let .array(v) = self { return v }; return [] }
    var editText: String {
        switch self {
        case let .string(v): return v
        case let .integer(v): return String(v)
        case let .unsigned(v): return String(v)
        case let .number(v): return String(v)
        case let .bool(v): return v ? "true" : "false"
        default: return ""
        }
    }
    func replacing(path: ArraySlice<String>, with value: Self) throws -> Self {
        guard let key = path.first else { return value }
        switch self {
        case var .object(object):
            guard let prior = object[key] else { throw WatchWorkflowEditingError.invalidDraft }
            object[key] = try prior.replacing(path: path.dropFirst(), with: value)
            return .object(object)
        case var .array(array):
            guard let index = Int(key), array.indices.contains(index) else { throw WatchWorkflowEditingError.invalidDraft }
            array[index] = try array[index].replacing(path: path.dropFirst(), with: value)
            return .array(array)
        default: throw WatchWorkflowEditingError.invalidDraft
        }
    }
}

struct WatchWorkflowNode: Codable, Equatable, Sendable, Identifiable {
    var raw: [String: WatchWorkflowValue]
    init(raw: [String: WatchWorkflowValue]) { self.raw = raw }
    init(from decoder: Decoder) throws { raw = try decoder.singleValueContainer().decode([String: WatchWorkflowValue].self) }
    func encode(to encoder: Encoder) throws { var c = encoder.singleValueContainer(); try c.encode(raw) }
    var id: String { raw["id"]?.text ?? "" }
    var type: String { raw["type"]?.text ?? "" }
    var title: String? { raw["title"]?.text }
    var config: [String: WatchWorkflowValue] { raw["config"]?.object ?? [:] }
    var inputMapping: [String: WatchWorkflowValue] { raw["input_mapping"]?.object ?? [:] }
    var isAskAI: Bool { type == "app_skill_action" && config["app_id"]?.text == "ai" && config["skill_id"]?.text == "ask" }
    var editable: Bool {
        ["schedule_trigger", "manual_trigger", "webhook_trigger", "event_trigger", "app_skill_action", "check", "decision", "send_chat_message", "create_chat_report", "start_new_chat"].contains(type)
    }
}
struct WatchWorkflowEdge: Codable, Equatable, Sendable { let from: String; let to: String; let branch: String? }
struct WatchWorkflowGraph: Codable, Equatable, Sendable {
    var raw: [String: WatchWorkflowValue]
    init(raw: [String: WatchWorkflowValue]) { self.raw = raw }
    init(from decoder: Decoder) throws { raw = try decoder.singleValueContainer().decode([String: WatchWorkflowValue].self) }
    func encode(to encoder: Encoder) throws { var c = encoder.singleValueContainer(); try c.encode(raw) }
    var triggerNodeID: String? { raw["trigger_node_id"]?.text }
    var nodes: [WatchWorkflowNode] { raw["nodes"]?.array.map { WatchWorkflowNode(raw: $0.object) } ?? [] }
    var edges: [WatchWorkflowEdge] {
        raw["edges"]?.array.compactMap {
            let object = $0.object
            guard let from = object["from"]?.text, let to = object["to"]?.text else { return nil }
            return WatchWorkflowEdge(from: from, to: to, branch: object["branch"]?.text)
        } ?? []
    }
    func orderedNodes() throws -> [WatchWorkflowNode] {
        let nodes = nodes
        guard nodes.count <= 300, nodes.allSatisfy({ !$0.id.isEmpty && !$0.type.isEmpty }), Set(nodes.map(\.id)).count == nodes.count else { throw APIError.invalidResponse }
        let byID = Dictionary(uniqueKeysWithValues: nodes.map { ($0.id, $0) })
        let outgoing = Dictionary(grouping: edges, by: \.from)
        var visited = Set<String>()
        var result: [WatchWorkflowNode] = []
        func append(_ id: String) {
            guard let node = byID[id], visited.insert(id).inserted else { return }
            result.append(node)
            for edge in outgoing[id] ?? [] { append(edge.to) }
        }
        if let triggerNodeID { append(triggerNodeID) }
        let incoming = Set(edges.map(\.to))
        for node in nodes where !incoming.contains(node.id) { append(node.id) }
        for node in nodes { append(node.id) }
        return result
    }
    func replacing(_ node: WatchWorkflowNode) throws -> Self {
        var graph = self
        var values = raw["nodes"]?.array ?? []
        guard let index = values.firstIndex(where: { $0.object["id"]?.text == node.id }) else { throw WatchWorkflowEditingError.invalidDraft }
        values[index] = .object(node.raw)
        graph.raw["nodes"] = .array(values)
        return graph
    }
}
struct WatchWorkflowDetail: Decodable, Equatable, Sendable {
    let id: String
    let title: String
    let description: String?
    let enabled: Bool
    let graph: WatchWorkflowGraph
    let currentVersionID: String?
    let teamID: String?
    enum CodingKeys: String, CodingKey { case id, title, description, enabled, graph; case currentVersionID = "current_version_id", teamID = "team_id" }
}
enum WatchWorkflowEditingError: Error, Equatable { case invalidDraft, changed, unavailable, invalidResponse }
struct WatchWorkflowEditField: Identifiable, Equatable {
    let path: [String]
    let original: WatchWorkflowValue
    var value: String
    var id: String { path.joined(separator: "/") }
}
struct WatchWorkflowNodeDraft: Equatable {
    let original: WatchWorkflowNode
    var fields: [WatchWorkflowEditField]
    var id: String { original.id }
    init(node: WatchWorkflowNode) {
        original = node
        fields = [WatchWorkflowEditField(path: ["title"], original: .string(node.title ?? ""), value: node.title ?? "")]
        func append(_ value: WatchWorkflowValue, path: [String]) {
            switch value {
            case let .object(object): for key in object.keys.sorted() { append(object[key]!, path: path + [key]) }
            case let .array(array): for (index, value) in array.enumerated() { append(value, path: path + [String(index)]) }
            case .null: break
            default: fields.append(WatchWorkflowEditField(path: path, original: value, value: value.editText))
            }
        }
        for key in node.config.keys.sorted() where !["app_id", "skill_id", "mode"].contains(key) { append(node.config[key]!, path: ["config", key]) }
    }
    func editedNode() throws -> WatchWorkflowNode {
        var node = original
        if let title = fields.first(where: { $0.path == ["title"] }), title.value != title.original.editText,
           node.raw["title"] == nil || node.raw["title"] == .null { node.raw["title"] = .string("") }
        var value = WatchWorkflowValue.object(node.raw)
        for field in fields {
            guard field.value != field.original.editText else { continue }
            let updated: WatchWorkflowValue
            switch field.original {
            case .string: updated = .string(field.value)
            case .integer: guard let v = Int64(field.value) else { throw WatchWorkflowEditingError.invalidDraft }; updated = .integer(v)
            case .unsigned: guard let v = UInt64(field.value) else { throw WatchWorkflowEditingError.invalidDraft }; updated = .unsigned(v)
            case .number: guard let v = Double(field.value), v.isFinite else { throw WatchWorkflowEditingError.invalidDraft }; updated = .number(v)
            case .bool: guard ["true", "false"].contains(field.value) else { throw WatchWorkflowEditingError.invalidDraft }; updated = .bool(field.value == "true")
            default: throw WatchWorkflowEditingError.invalidDraft
            }
            value = try value.replacing(path: field.path[...], with: updated)
        }
        node.raw = value.object
        if node.isAskAI {
            let prompt = node.config["input"]?.object["prompt"]?.text ?? ""
            guard !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, prompt.count <= 4_000 else { throw WatchWorkflowEditingError.invalidDraft }
        }
        if ["check", "decision"].contains(node.type) {
            if node.config["mode"]?.text == "ai" {
                let question = node.config["question"]?.text ?? ""
                guard !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, question.count <= 4_000 else { throw WatchWorkflowEditingError.invalidDraft }
            } else { guard node.config["predicate"]?.object["op"]?.text != nil else { throw WatchWorkflowEditingError.invalidDraft } }
        }
        if node.type == "schedule_trigger" {
            guard let type = node.config["schedule"]?.object["type"]?.text, ["once", "hourly", "daily", "weekly"].contains(type) else { throw WatchWorkflowEditingError.invalidDraft }
        }
        if node.type == "send_chat_message" {
            guard !(node.config["title"]?.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  !(node.config["message"]?.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !(node.config["blocks"]?.array ?? []).isEmpty else { throw WatchWorkflowEditingError.invalidDraft }
        }
        return node
    }
}

@MainActor final class WatchWorkflowDetailService: ObservableObject {
    enum State: Equatable { case idle, loading, loaded(WatchWorkflowDetail), failed, unavailable }
    typealias Validate = @MainActor @Sendable () throws -> Void
    typealias Request = @MainActor @Sendable (HTTPMethod, String, Data?, WatchWorkflowDetailScope, @escaping Validate) async throws -> Data
    @Published private(set) var state: State = .idle
    @Published private(set) var orderedNodes: [WatchWorkflowNode] = []
    @Published var draft: WatchWorkflowNodeDraft?
    @Published private(set) var isSaving = false
    @Published private(set) var saveError: WatchWorkflowEditingError?
    private let currentAccountID: @MainActor @Sendable () -> String?
    private let request: Request
    private var requestID = UUID()
    private var selectionID: String?
    private var selectionScope: WatchWorkflowDetailScope?
    init(currentAccountID: @escaping @MainActor @Sendable () -> String? = { nil }, request: Request? = nil) {
        self.currentAccountID = currentAccountID
        self.request = request ?? { method, path, body, scope, validate in
            try await APIClient.shared.requestForVerifiedWatchSession(method, path: path,
                serverProfile: scope.profile, body: body.map { JSONRawBody(data: $0) }, validate: validate)
        }
    }
    func permits(_ scope: WatchWorkflowDetailScope) -> Bool {
        !scope.accountID.isEmpty && scope.teamID == nil && currentAccountID() == scope.accountID && scope.generation == WatchChatAccountLifecycle.generation && scope.profile == ServerProfile.current() && !PairSessionDeadlineStore.isExpired(userID: scope.accountID)
    }
    func matches(id: String, scope: WatchWorkflowDetailScope?) -> Bool {
        guard let scope else { return false }
        return selectionID == id && selectionScope == scope && permits(scope)
    }
    func clear() {
        requestID = UUID(); selectionID = nil; selectionScope = nil
        orderedNodes = []; state = .idle; draft = nil; isSaving = false; saveError = nil
    }
    static func path(id: String) throws -> String {
        guard WatchItemOpenRequest(kind: .workflow, id: id) != nil,
              let encoded = id.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) else { throw WatchWorkflowEditingError.invalidResponse }
        return "/v1/workflows/\(encoded)"
    }
    private func validation(_ operation: UUID, scope: WatchWorkflowDetailScope) -> Validate {
        { [weak self] in
            try Task.checkCancellation()
            guard let self, self.requestID == operation, self.permits(scope) else { throw CancellationError() }
        }
    }
    private func fetch(_ id: String, scope: WatchWorkflowDetailScope, operation: UUID) async throws -> WatchWorkflowDetail {
        let data = try await request(.get, Self.path(id: id), nil, scope, validation(operation, scope: scope))
        try validation(operation, scope: scope)()
        guard data.count <= 2_000_000 else { throw APIError.invalidResponse }
        struct Response: Decodable { let workflow: WatchWorkflowDetail }
        let detail = try JSONDecoder().decode(Response.self, from: data).workflow
        guard detail.id == id, !detail.title.isEmpty, detail.teamID == nil else { throw WatchWorkflowEditingError.invalidResponse }
        _ = try detail.graph.orderedNodes()
        return detail
    }
    func load(id: String, scope: WatchWorkflowDetailScope?) async {
        clear()
        guard let scope, permits(scope) else { state = .unavailable; return }
        selectionID = id; selectionScope = scope
        let operation = requestID
        state = .loading
        do {
            let detail = try await fetch(id, scope: scope, operation: operation)
            try validation(operation, scope: scope)()
            orderedNodes = try detail.graph.orderedNodes(); state = .loaded(detail)
        } catch {
            guard requestID == operation else { return }
            orderedNodes = []; state = permits(scope) ? .failed : .unavailable
        }
    }
    func beginEditing(nodeID: String) {
        guard !isSaving, let scope = selectionScope, permits(scope), case let .loaded(detail) = state,
              let node = detail.graph.nodes.first(where: { $0.id == nodeID }), node.editable else { return }
        draft = WatchWorkflowNodeDraft(node: node); saveError = nil
    }
    func cancelEditing() { guard !isSaving else { return }; draft = nil; saveError = nil }
    // PATCH has no route-level CAS today. Preflight detects existing changes;
    // it cannot close the race between GET and PATCH. Only graph is sent.
    func save() async -> Bool {
        guard !isSaving, let draft, let scope = selectionScope, permits(scope), let id = selectionID, case let .loaded(original) = state else { return false }
        let operation = requestID
        isSaving = true; saveError = nil
        defer { if requestID == operation { isSaving = false } }
        do {
            let node = try draft.editedNode()
            let graph = try original.graph.replacing(node)
            let latest = try await fetch(id, scope: scope, operation: operation)
            guard latest.currentVersionID == original.currentVersionID, latest.graph == original.graph else { throw WatchWorkflowEditingError.changed }
            struct Patch: Encodable { let graph: WatchWorkflowGraph }
            let body = try JSONEncoder().encode(Patch(graph: graph))
            let data = try await request(.patch, Self.path(id: id), body, scope, validation(operation, scope: scope))
            try validation(operation, scope: scope)()
            guard data.count <= 2_000_000 else { throw WatchWorkflowEditingError.invalidResponse }
            struct Response: Decodable { let workflow: WatchWorkflowDetail }
            let saved = try JSONDecoder().decode(Response.self, from: data).workflow
            guard saved.id == id, saved.teamID == nil,
                  let confirmed = saved.graph.nodes.first(where: { $0.id == node.id }),
                  confirmed.title == node.title, confirmed.config == node.config,
                  confirmed.inputMapping == node.inputMapping else { throw WatchWorkflowEditingError.invalidResponse }
            orderedNodes = try saved.graph.orderedNodes(); state = .loaded(saved)
            self.draft = nil; saveError = nil
            return true
        } catch {
            guard requestID == operation else { return false }
            if !permits(scope) { clear(); state = .unavailable }
            else { saveError = (error as? WatchWorkflowEditingError) ?? .unavailable }
            return false
        }
    }
}

#if DEBUG
/// Synthetic routes use the production service and graph editor without accounts
/// or network. Both hub list IDs can be opened through this injected transport.
@MainActor enum WatchWorkflowDetailFixtures {
    static let accountID = "watch-workflow-fixture-account"
    static var scope: WatchWorkflowDetailScope { .capture(accountID: accountID) }
    static func service(failFirstRead: Bool = false, failFirstSave: Bool = false, empty: Bool = false) -> WatchWorkflowDetailService {
        let transport = Transport(failFirstRead: failFirstRead, failFirstSave: failFirstSave, empty: empty)
        return WatchWorkflowDetailService(currentAccountID: { accountID }, request: transport.request)
    }
    static func item(id: String = "workflow-one") -> WatchWorkflowListItem {
        WatchWorkflowListItem(id: id, title: "Weekly AI events", enabled: false, updatedAt: 1,
            openRequest: WatchItemOpenRequest(kind: .workflow, id: id)!)
    }
    static func graph(empty: Bool = false) throws -> WatchWorkflowGraph {
        let data = Data(#"{"version":2,"trigger_node_id":"trigger","nodes":[{"id":"trigger","type":"schedule_trigger","title":"Every morning","config":{"schedule":{"type":"daily","time":"09:00","timezone":"Europe/Berlin"}},"ui":{"x":1,"unrecognized_style":"keep"},"future_node_metadata":{"camelCase":true}},{"id":"weather","type":"app_skill_action","title":"Weather forecast","config":{"app_id":"weather","skill_id":"search","input":{"location":"Berlin","count":3,"future_schema_key":{"enabled":true}}},"input_mapping":{"source":"$nodes.trigger.date"}},{"id":"ask","type":"app_skill_action","title":"Ask AI","config":{"app_id":"ai","skill_id":"ask","input":{"prompt":"Summarize {{steps.weather.forecast}}"},"model":"auto"}},{"id":"check","type":"check","title":"Rain check","config":{"mode":"exact","predicate":{"left":"$nodes.weather.forecast.rain","op":"gt","right":50}}},{"id":"message","type":"send_chat_message","title":"Morning message","config":{"title":"Morning weather","message":"{{steps.ask.answer}}","chat_id":"fixture-chat","blocks":[{"id":"forecast-block","source":"$nodes.weather.forecast","only_new_results":true}]}}],"edges":[{"from":"trigger","to":"weather","future_edge_style":"keep"},{"from":"weather","to":"ask"},{"from":"ask","to":"check"},{"from":"check","to":"message","branch":"yes"}],"variables":{"futureVariable":9007199254740993},"limits":{"max_credits":10},"ui_layout":{"zoom":0.5,"camelCase":"keep"},"future_graph_key":{"keep":"unchanged"}}"#.utf8)
        var graph = try JSONDecoder().decode(WatchWorkflowGraph.self, from: data)
        if empty { graph.raw["nodes"] = .array([]); graph.raw["edges"] = .array([]); graph.raw["trigger_node_id"] = .null }
        return graph
    }
    static func response(id: String = "workflow-one", graph: WatchWorkflowGraph, version: String = "fixture-v1") throws -> Data {
        try JSONEncoder().encode(WatchWorkflowValue.object(["workflow": .object([
            "id": .string(id), "title": .string("Weekly AI events"), "description": .string("Synthetic workflow for Watch testing."),
            "enabled": .bool(false), "current_version_id": .string(version), "graph": .object(graph.raw)
        ])]))
    }
    @MainActor private final class Transport {
        var failRead: Bool
        var failSave: Bool
        var graph: WatchWorkflowGraph
        var version = "fixture-v1"
        init(failFirstRead: Bool, failFirstSave: Bool, empty: Bool) {
            failRead = failFirstRead; failSave = failFirstSave
            graph = try! WatchWorkflowDetailFixtures.graph(empty: empty)
        }
        func request(method: HTTPMethod, path: String, body: Data?, scope: WatchWorkflowDetailScope,
                     validate: @escaping WatchWorkflowDetailService.Validate) async throws -> Data {
            try validate()
            let id = String(path.split(separator: "/").last ?? "workflow-one")
            if method == .get {
                if failRead { failRead = false; throw APIError.invalidResponse }
            } else if method == .patch {
                if failSave { failSave = false; throw APIError.invalidResponse }
                guard let body else { throw APIError.invalidResponse }
                struct Patch: Decodable { let graph: WatchWorkflowGraph }
                graph = try JSONDecoder().decode(Patch.self, from: body).graph
                version = "fixture-v2"
            } else { throw APIError.invalidResponse }
            try validate()
            return try WatchWorkflowDetailFixtures.response(id: id, graph: graph, version: version)
        }
    }
}
#endif
