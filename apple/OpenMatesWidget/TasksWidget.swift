// Native WidgetKit Tasks list; the OS owns widget sizing and configuration UI.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/tasks/TaskCard.svelte
//         frontend/packages/ui/src/components/tasks/TasksPage.svelte
// CSS: TaskCard.svelte .task-card-copy, h3; TasksPage.svelte board columns
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Native difference: compact OS widget rows with status configuration and deep links.
// Specification: specifications/features/apple-tasks-widget/specification.yml
// Assertions: apple-tasks-widget.status-filter, apple-tasks-widget.links, apple-tasks-widget.private-cache

import AppIntents
import SwiftUI
import WidgetKit

extension WidgetTaskFilter: AppEnum {
    // AppIntents extracts this metadata at build time; keys and the exhaustive
    // dictionary must remain literals. Widget Localizable.xcstrings is derived
    // from the same generated locale JSON used by the runtime string reader.
    static var typeDisplayRepresentation: TypeDisplayRepresentation {
        TypeDisplayRepresentation(name: "apple.tasks_widget.status_parameter")
    }

    static var caseDisplayRepresentations: [WidgetTaskFilter: DisplayRepresentation] {
        [
            .all: DisplayRepresentation(title: "apple.tasks_widget.all"),
            .todo: DisplayRepresentation(title: "tasks.workspace.todo"),
            .inProgress: DisplayRepresentation(title: "tasks.workspace.in_progress"),
            .blocked: DisplayRepresentation(title: "tasks.workspace.blocked"),
            .backlog: DisplayRepresentation(title: "tasks.workspace.backlog"),
            .done: DisplayRepresentation(title: "tasks.workspace.done"),
        ]
    }
}

struct TasksWidgetConfiguration: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "apple.tasks_widget.title"
    static let description = IntentDescription("apple.tasks_widget.description")

    @Parameter(title: "apple.tasks_widget.status_parameter", default: .all)
    var status: WidgetTaskFilter
}

struct TasksWidgetEntry: TimelineEntry {
    let date: Date
    let status: WidgetTaskFilter
    let tasks: [WidgetTaskSummary]
    let hasSnapshot: Bool
    let taskCount: Int?

    init(date: Date, status: WidgetTaskFilter, tasks: [WidgetTaskSummary], hasSnapshot: Bool, taskCount: Int? = nil) {
        self.date = date
        self.status = status
        self.tasks = tasks
        self.hasSnapshot = hasSnapshot
        self.taskCount = hasSnapshot ? taskCount ?? tasks.count : nil
    }
}

struct TasksWidgetProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> TasksWidgetEntry {
        TasksWidgetFixtures.entry(status: .all)
    }

    func snapshot(for configuration: TasksWidgetConfiguration, in context: Context) async -> TasksWidgetEntry {
        if context.isPreview { return TasksWidgetFixtures.entry(status: configuration.status) }
        return await entry(status: configuration.status)
    }

    func timeline(for configuration: TasksWidgetConfiguration, in context: Context) async -> Timeline<TasksWidgetEntry> {
        let entry = await entry(status: configuration.status)
        return Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(15 * 60)))
    }

    private func entry(status: WidgetTaskFilter) async -> TasksWidgetEntry {
        let snapshot = await MainActor.run { WidgetTasksStorage.load() }
        return TasksWidgetEntry(date: Date(), status: status,
            tasks: snapshot?.tasks(matching: status, limit: 12) ?? [], hasSnapshot: snapshot != nil,
            taskCount: snapshot?.taskCount(matching: status))
    }
}

struct TasksWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: TasksWidgetEntry

    private var rowLimit: Int { WidgetTasksLayout.rowLimit(for: family) }

    var body: some View {
        Group {
            #if os(iOS)
            if family == .accessoryCircular {
                circularContent
            } else if family == .accessoryRectangular {
                rectangularContent
            } else {
                homeContent
            }
            #else
            homeContent
            #endif
        }
        .widgetURL(WidgetTasksLayout.primaryURL(for: family, tasks: entry.tasks))
        .accessibilityIdentifier("tasks-widget")
    }

    #if os(iOS)
    private var circularContent: some View {
        ZStack {
            AccessoryWidgetBackground()
            VStack(spacing: .spacing1) {
                Image(systemName: "plus").font(.omSmall.weight(.semibold))
                Text(entry.taskCount.map(String.init) ?? "—").font(.omSmall.bold())
                    .privacySensitive()
            }
        }
        .accessibilityLabel(entry.hasSnapshot ? TasksWidgetStrings.title : TasksWidgetStrings.openApp)
        .accessibilityValue(entry.taskCount.map(String.init) ?? "")
        .accessibilityHint(TasksWidgetStrings.newTask)
        .accessibilityIdentifier("tasks-widget-circular-new-task")
    }
    private var rectangularContent: some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            HStack(spacing: .spacing2) {
                Text(TasksWidgetStrings.title).font(.omMicro.bold())
                Spacer(minLength: 0)
                Text(TasksWidgetStrings.status(entry.status)).font(.omMicro).lineLimit(1)
            }
            if let task = entry.tasks.first, let url = WidgetTasksLinks.task(task.id) {
                Link(destination: url) {
                    Text(task.title).font(.omSmall).lineLimit(1).privacySensitive()
                }.accessibilityIdentifier("tasks-widget-task-\(task.id)")
            } else {
                Link(destination: WidgetTasksLinks.workspace) {
                    Text(entry.hasSnapshot ? TasksWidgetStrings.empty : TasksWidgetStrings.openApp)
                        .font(.omMicro).lineLimit(1)
                }.accessibilityIdentifier("tasks-widget-empty")
            }
            Link(destination: WidgetTasksLinks.newTask) {
                Label(TasksWidgetStrings.newTask, systemImage: "plus").font(.omMicro.weight(.semibold)).lineLimit(1)
            }.accessibilityIdentifier("tasks-widget-new-task")
        }
    }
    #endif

    private var homeContent: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing2) {
                Text(TasksWidgetStrings.title).font(.omSmall.bold())
                Spacer(minLength: .spacing2)
                Text(TasksWidgetStrings.status(entry.status))
                    .font(.omMicro).foregroundStyle(Color.fontSecondary)
            }
            if entry.tasks.isEmpty {
                Link(destination: WidgetTasksLinks.workspace) {
                    Text(entry.hasSnapshot ? TasksWidgetStrings.empty : TasksWidgetStrings.openApp)
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                }
                .accessibilityIdentifier("tasks-widget-empty")
            } else {
                ForEach(Array(entry.tasks.prefix(rowLimit))) { task in
                    if let url = WidgetTasksLinks.task(task.id) {
                        Link(destination: url) {
                            HStack(alignment: .firstTextBaseline, spacing: .spacing3) {
                                Text(task.title).font(.omSmall).lineLimit(1)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                if entry.status == .all {
                                    Text(TasksWidgetStrings.status(task.status))
                                        .font(.omMicro).foregroundStyle(Color.fontSecondary).lineLimit(1)
                                }
                            }
                            .foregroundStyle(Color.fontPrimary)
                            .privacySensitive()
                        }
                        .accessibilityIdentifier("tasks-widget-task-\(task.id)")
                    }
                }
                Spacer(minLength: 0)
            }
            Link(destination: WidgetTasksLinks.newTask) {
                HStack(spacing: .spacing2) {
                    Image(systemName: "plus")
                    Text(TasksWidgetStrings.newTask)
                }
                .font(.omSmall.weight(.semibold)).foregroundStyle(Color.buttonPrimary)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityIdentifier("tasks-widget-new-task")
        }
    }
}

struct TasksWidget: Widget {
    let kind = "TasksWidget"
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: kind, intent: TasksWidgetConfiguration.self, provider: TasksWidgetProvider()) { entry in
            TasksWidgetView(entry: entry).containerBackground(Color.grey0, for: .widget)
        }
        .configurationDisplayName(TasksWidgetStrings.title)
        .description(TasksWidgetStrings.description)
        #if os(iOS)
        .supportedFamilies([.systemMedium, .systemLarge, .accessoryCircular, .accessoryRectangular])
        #else
        .supportedFamilies([.systemMedium, .systemLarge])
        #endif
    }
}

// Deterministic non-private fixtures for the gallery, previews and link checks.
enum TasksWidgetFixtures {
    static let tasks: [WidgetTaskSummary] = [
        .init(id: "00000000-0000-4000-8000-000000000001", title: "Prepare launch notes", status: .todo),
        .init(id: "00000000-0000-4000-8000-000000000002", title: "Review workspace", status: .inProgress),
        .init(id: "00000000-0000-4000-8000-000000000003", title: "Confirm release access", status: .blocked),
        .init(id: "00000000-0000-4000-8000-000000000004", title: "Explore follow-up ideas", status: .backlog),
        .init(id: "00000000-0000-4000-8000-000000000005", title: "Publish project summary", status: .done),
    ]
    static func entry(status: WidgetTaskFilter) -> TasksWidgetEntry {
        let snapshot = WidgetTasksSnapshot(owner: "preview", updatedAt: Date(), tasks: tasks)
        return TasksWidgetEntry(date: Date(), status: status,
            tasks: snapshot.tasks(matching: status, limit: 12), hasSnapshot: true,
            taskCount: snapshot.taskCount(matching: status))
    }
}

#if DEBUG
#if os(iOS)
#Preview("Tasks — Lock Screen circular", as: .accessoryCircular) { TasksWidget() } timeline: {
    TasksWidgetFixtures.entry(status: .todo)
    TasksWidgetEntry(date: Date(), status: .all, tasks: [], hasSnapshot: false)
}
#Preview("Tasks — Lock Screen rectangular", as: .accessoryRectangular) { TasksWidget() } timeline: {
    TasksWidgetFixtures.entry(status: .inProgress)
    TasksWidgetEntry(date: Date(), status: .todo, tasks: [], hasSnapshot: true)
    TasksWidgetEntry(date: Date(), status: .all, tasks: [], hasSnapshot: false)
}
#endif
#Preview("Tasks — all", as: .systemMedium) { TasksWidget() } timeline: {
    TasksWidgetFixtures.entry(status: .all)
}
#Preview("Tasks — status filters", as: .systemLarge) { TasksWidget() } timeline: {
    TasksWidgetFixtures.entry(status: .todo)
    TasksWidgetFixtures.entry(status: .inProgress)
    TasksWidgetFixtures.entry(status: .blocked)
    TasksWidgetFixtures.entry(status: .backlog)
    TasksWidgetFixtures.entry(status: .done)
}
#Preview("Tasks — empty and locked", as: .systemMedium) { TasksWidget() } timeline: {
    TasksWidgetEntry(date: Date(), status: .todo, tasks: [], hasSnapshot: true)
    TasksWidgetEntry(date: Date(), status: .all, tasks: [], hasSnapshot: false)
}
#endif
