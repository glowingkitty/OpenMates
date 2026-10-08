// Shared production Smart Stack layout and detached geometry fixture.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.memories.upcoming, apple-live-activities.lifecycle.isolation
#if os(iOS) && canImport(ActivityKit)
import SwiftUI
import ActivityKit

@available(iOS 16.2, *)
struct UpcomingMemorySmallActivityView: View {
    let state: OpenMatesLiveActivityAttributes.ContentState
    let kind: String
    let isStale: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(state.title, systemImage: kind == "upcoming" ? "calendar" : "arrow.down.circle")
                .font(.caption).lineLimit(1)
            if kind == "download" {
                ProgressView(value: state.progress)
                Text(state.progress, format: .percent.precision(.fractionLength(0))).font(.caption)
            } else if let start = state.startsAt {
                Text(start, style: .time).font(.headline)
                    .accessibilityIdentifier("upcoming-small-start")
                if !isStale && start > Date() {
                    Text(timerInterval: min(Date(), start)...start, countsDown: true).monospacedDigit().font(.caption)
                } else { Text(state.staleDetail ?? state.detail).font(.caption).lineLimit(1) }
                Text(state.itemCount, format: .number).font(.caption2)
                    .accessibilityIdentifier("upcoming-small-total")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("upcoming-live-activity-small")
    }
}
#endif
