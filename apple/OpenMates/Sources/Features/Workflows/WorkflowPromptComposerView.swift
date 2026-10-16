// Workflow prompt field shared by the home and editor surfaces.
// Web source: WorkspacePromptComposer.svelte (surface="workflows").

import SwiftUI

struct WorkflowPromptComposerView: View {
    @Binding var text: String
    let placeholder: String
    let submitLabel: String
    let submittingLabel: String
    let disabled: Bool
    let submitting: Bool
    let identifier: String
    let inputIdentifier: String
    let submitIdentifier: String
    let micIdentifier: String
    let onSubmit: (String) -> Void
    let onMic: () -> Void
    var onActiveChanged: (Bool) -> Void = { _ in }
    var dismissRequestID: UUID? = nil
    var availableHeight: CGFloat = 350

    var body: some View {
        WorkspacePromptComposerView(
            text: $text, placeholder: placeholder,
            submitLabel: submitLabel, submittingLabel: submittingLabel,
            disabled: disabled, submitting: submitting,
            identifier: identifier, inputIdentifier: inputIdentifier,
            submitIdentifier: submitIdentifier, micIdentifier: micIdentifier,
            onSubmit: onSubmit, onMic: onMic,
            onActiveChanged: onActiveChanged, dismissRequestID: dismissRequestID,
            availableHeight: availableHeight
        )
    }
}

struct WorkflowVoiceSheetLayout: ViewModifier {
    @ViewBuilder
    func body(content: Content) -> some View {
        #if os(iOS)
        content.presentationDetents([.medium])
        #else
        content
        #endif
    }
}

#if DEBUG
/// Explicitly gated disposable transport controls for a suspended local submit.
/// They never appear for an account request or without the held-submit fixture.
struct WorkflowPromptHeldFixtureControls: View {
    @ObservedObject var store: WorkflowStore
    let replaceDraft: () -> Void
    var body: some View {
        if store.previewPromptSubmitting,
           ProcessInfo.processInfo.arguments.contains("--ui-test-workflow-prompt-held") {
            HStack {
                Button("Replace synthetic draft", action: replaceDraft)
                    .accessibilityIdentifier("workflow-held-replace-draft")
                Button("Complete synthetic submit", action: store.completeHeldPreviewPrompt)
                    .accessibilityIdentifier("workflow-held-complete-submit")
            }
            .font(.omSmall).padding(.spacing4).background(Color.grey0)
            .onDisappear { store.cancelHeldPreviewPrompt() }
        }
    }
}
#endif
