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

    var body: some View {
        WorkspacePromptComposerView(
            text: $text, placeholder: placeholder,
            submitLabel: submitLabel, submittingLabel: submittingLabel,
            disabled: disabled, submitting: submitting,
            identifier: identifier, inputIdentifier: inputIdentifier,
            submitIdentifier: submitIdentifier, micIdentifier: micIdentifier,
            onSubmit: onSubmit, onMic: onMic
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
