// Shared scheduled Workflow widget rendering for WidgetKit and detached previews.
// Web source: frontend/packages/ui/src/components/workflows/WorkflowDetailPage.svelte
// Native difference: a compact OS widget with one configured workflow and explicit Run.
import AppIntents
import SwiftUI

struct WidgetWorkflowsLabels {
    let title: String
    let choose: String
    let openApp: String
    let run: String
}
struct WidgetWorkflowsContentView: View {
    let workflow: WidgetWorkflowSummary?
    let identifier: String?
    let hasSnapshot: Bool
    let compact: Bool
    let labels: WidgetWorkflowsLabels
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(labels.title).font(.omMicro.bold()).lineLimit(1)
            if let workflow, let identifier {
                Text(workflow.title).font(.omSmall.weight(.semibold)).lineLimit(compact ? 1 : 3).privacySensitive()
                    .accessibilityIdentifier("workflows-widget-title")
                if !compact { Spacer(minLength: 0) }
                Button(intent: RunWidgetWorkflowIntent(identifier: identifier)) {
                    Label(labels.run, systemImage: "play.fill").font(.omSmall.weight(.semibold))
                }.buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("workflows-widget-run")
            } else {
                Link(destination: WidgetWorkflowsLinks.workspace) {
                    Text(hasSnapshot ? labels.choose : labels.openApp).font(.omMicro).lineLimit(3)
                }.accessibilityIdentifier("workflows-widget-unavailable")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflows-widget")
    }
}
