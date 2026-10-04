// OS-owned Lock Screen / Dynamic Island presentation of app-local activities.
// Web source: none — ActivityKit is an Apple platform capability.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.download.progress, apple-live-activities.memories.upcoming
#if os(iOS) && canImport(ActivityKit)
import ActivityKit
import SwiftUI
import WidgetKit
import AppIntents

@available(iOS 16.2, *)
struct OpenMatesLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: OpenMatesLiveActivityAttributes.self) { context in
            OpenMatesActivityContent(state: context.state, kind: context.attributes.kind, identity: context.attributes.identity, isStale: context.isStale)
                .padding()
                .widgetURL(activityURL(kind: context.attributes.kind))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) { Image(systemName: symbol(context.attributes.kind)) }
                DynamicIslandExpandedRegion(.center) { Text(context.state.title).lineLimit(1) }
                DynamicIslandExpandedRegion(.bottom) {
                    OpenMatesActivityContent(state: context.state, kind: context.attributes.kind, identity: context.attributes.identity, isStale: context.isStale)
                }
            } compactLeading: {
                Image(systemName: symbol(context.attributes.kind))
            } compactTrailing: {
                if context.attributes.kind == "download" {
                    Text(context.state.progress, format: .percent.precision(.fractionLength(0)))
                } else if let start = context.state.startsAt {
                    Text(timerInterval: min(Date(), start)...start, countsDown: true)
                        .monospacedDigit().frame(maxWidth: 55)
                }
            } minimal: {
                Image(systemName: symbol(context.attributes.kind))
            }
            .widgetURL(activityURL(kind: context.attributes.kind))
        }
    }
    private func activityURL(kind: String) -> URL? {
        switch kind {
        case "download": return URL(string: "openmates://settings/developers/local-models")
        default: return URL(string: "openmates://settings/settings_memories")
        }
    }
    private func symbol(_ kind: String) -> String {
        switch kind {
        case "download": return "arrow.down.circle"
        default: return "calendar"
        }
    }
}

@available(iOS 16.2, *)
private struct OpenMatesActivityContent: View {
    let state: OpenMatesLiveActivityAttributes.ContentState
    let kind: String
    let identity: String
    let isStale: Bool
    private var staleOrExpired: Bool { isStale || state.expiresAt.map { $0 <= Date() } == true }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(state.title).font(.headline).lineLimit(1)
            Text(staleOrExpired ? (state.staleDetail ?? state.detail) : state.detail).font(.caption).lineLimit(2)
            if kind == "download" {
                ProgressView(value: state.progress)
                HStack {
                    Text(state.progress, format: .percent.precision(.fractionLength(0)))
                    Spacer()
                    Text(ByteCountFormatter.string(fromByteCount: state.completedBytes, countStyle: .file))
                    Text("/")
                    Text(ByteCountFormatter.string(fromByteCount: state.totalBytes, countStyle: .file))
                }
                .font(.caption).monospacedDigit()
            } else if let start = state.startsAt {
                HStack {
                    Text(start, style: .time)
                    Spacer()
                    Text(timerInterval: min(Date(), start)...start, countsDown: true).monospacedDigit()
                }
                .font(.title3)
                if #available(iOS 17.0, *) {
                    UpcomingMemoryActivityNavigationControls(state: state, identity: identity,
                        labels: LiveActivityWidgetStrings.navigation)
                }
            }
        }
    }
}

private enum LiveActivityWidgetStrings {
    private static func text(_ key: String) -> String { WidgetStrings.text(key, languageKey: "widget_tasks_language") }
    static var navigation: UpcomingMemoryActivityNavigationLabels {
        .init(previous: text("live_activities.upcoming_previous"), next: text("live_activities.upcoming_next"),
              position: text("live_activities.upcoming_position"), total: text("live_activities.upcoming_total"),
              viewAll: text("live_activities.upcoming_view_all"))
    }
}
#endif
