// Web counterpart: frontend/packages/ui/src/components/FocusPhaseNotice.svelte
// Specification: specifications/features/focus-modes/specification.yml
// Assertions: focus-modes.phases, focus-modes.history-events, focus-modes.history-side-effects
import SwiftUI

struct FocusPhaseNoticeView: View {
    let event: FocusPhaseEvent
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: .spacing1) {
            Text(L(event.direction == "backward" ? "focus_phases.returned" : "focus_phases.switched"))
            if let path = event.detailPath {
                Button {
                    if let url = URL(string: "openmates://settings/\(path)") {
                        NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
                    }
                } label: { Text(event.phaseTitle).underline().foregroundStyle(Color.buttonPrimary) }
                .buttonStyle(.plain).accessibilityIdentifier("focus-phase-details-link")
            } else { Text(event.phaseTitle) }
        }
        .font(.omSmall).foregroundStyle(Color.fontSecondary)
        .accessibilityIdentifier("focus-phase-notice")
    }
}
