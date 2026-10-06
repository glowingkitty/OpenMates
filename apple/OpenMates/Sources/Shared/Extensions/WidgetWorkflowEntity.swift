// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability, apple-controls.quick-actions, apple-controls.workflow, apple-controls.project, apple-controls.private-cache
// Shared entity for Home Screen and Control Center configuration. Uses encrypted local snapshot only.
import AppIntents
import Foundation

struct WidgetWorkflowEntity: AppEntity {
    static var typeDisplayRepresentation: TypeDisplayRepresentation {
        TypeDisplayRepresentation(name: "apple.workflows_widget.workflow_parameter")
    }
    static var defaultQuery: WidgetWorkflowEntityQuery { WidgetWorkflowEntityQuery() }
    let id: String
    let title: String
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(title)") }
    static func identifier(_ item: WidgetWorkflowSummary, owner: String) -> String { owner + ":" + item.id }
}
struct WidgetWorkflowEntityQuery: EntityQuery {
    func entities(for identifiers: [String]) async throws -> [WidgetWorkflowEntity] {
        await MainActor.run {
            guard let snapshot = WidgetWorkflowsStorage.shared.load() else { return [] }
            return snapshot.workflows.compactMap { item in
                let id = WidgetWorkflowEntity.identifier(item, owner: snapshot.owner)
                return identifiers.contains(id) ? .init(id: id, title: item.title) : nil
            }
        }
    }
    func suggestedEntities() async throws -> [WidgetWorkflowEntity] {
        await MainActor.run {
            guard let snapshot = WidgetWorkflowsStorage.shared.load() else { return [] }
            return snapshot.workflows.map { .init(id: WidgetWorkflowEntity.identifier($0, owner: snapshot.owner), title: $0.title) }
        }
    }
}
