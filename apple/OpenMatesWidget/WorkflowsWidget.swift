// WidgetKit surface for scheduled workflows. Web behavior: WorkflowDetailPage.svelte and workflowStore.ts.
import AppIntents
import SwiftUI
import WidgetKit

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
struct WorkflowsWidgetConfiguration: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "apple.workflows_widget.title"
    static let description = IntentDescription("apple.workflows_widget.description")
    @Parameter(title: "apple.workflows_widget.workflow_parameter") var workflow: WidgetWorkflowEntity?
}
struct WorkflowsWidgetEntry: TimelineEntry {
    let date: Date
    let identifier: String?
    let workflow: WidgetWorkflowSummary?
    let hasSnapshot: Bool
}
struct WorkflowsWidgetProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> WorkflowsWidgetEntry { WorkflowsWidgetFixtures.entry }
    func snapshot(for configuration: WorkflowsWidgetConfiguration, in context: Context) async -> WorkflowsWidgetEntry {
        if context.isPreview { return WorkflowsWidgetFixtures.entry }
        return await entry(configuration)
    }
    func timeline(for configuration: WorkflowsWidgetConfiguration, in context: Context) async -> Timeline<WorkflowsWidgetEntry> {
        Timeline(entries: [await entry(configuration)], policy: .never)
    }
    private func entry(_ configuration: WorkflowsWidgetConfiguration) async -> WorkflowsWidgetEntry {
        await MainActor.run {
            let snapshot = WidgetWorkflowsStorage.shared.load()
            let workflow = snapshot?.workflows.first { WidgetWorkflowEntity.identifier($0, owner: snapshot?.owner ?? "") == configuration.workflow?.id }
            return .init(date: Date(), identifier: workflow == nil ? nil : configuration.workflow?.id, workflow: workflow, hasSnapshot: snapshot != nil)
        }
    }
}
struct WorkflowsWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: WorkflowsWidgetEntry
    var body: some View {
        WidgetWorkflowsContentView(workflow: entry.workflow, identifier: entry.identifier, hasSnapshot: entry.hasSnapshot,
            compact: isAccessory, labels: .init(title: WorkflowsWidgetStrings.title, choose: WorkflowsWidgetStrings.choose,
                openApp: WorkflowsWidgetStrings.openApp, run: WorkflowsWidgetStrings.run))
            .widgetURL(WidgetWorkflowsLinks.workspace)
    }
    private var isAccessory: Bool {
        #if os(iOS)
        return family == .accessoryCircular || family == .accessoryRectangular
        #else
        return false
        #endif
    }
}
struct WorkflowsWidget: Widget {
    let kind = "WorkflowsWidget"
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: kind, intent: WorkflowsWidgetConfiguration.self, provider: WorkflowsWidgetProvider()) { entry in
            WorkflowsWidgetView(entry: entry).containerBackground(Color.grey0, for: .widget)
        }.configurationDisplayName(WorkflowsWidgetStrings.title).description(WorkflowsWidgetStrings.description)
        #if os(iOS)
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge, .accessoryRectangular])
        #else
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
        #endif
    }
}
enum WorkflowsWidgetFixtures {
    static var entry: WorkflowsWidgetEntry {
        .init(date: Date(timeIntervalSince1970: 1_800_000_000), identifier: "preview", workflow: .init(id: "workflow-preview", title: "Morning weather report", versionID: "version-preview"), hasSnapshot: true)
    }
}
#if DEBUG
#Preview("Scheduled workflow", as: .systemSmall) { WorkflowsWidget() } timeline: { WorkflowsWidgetFixtures.entry }
#endif
