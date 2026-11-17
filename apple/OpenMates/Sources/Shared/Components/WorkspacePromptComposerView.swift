import SwiftUI

// Shared native editor for Task creation and Workflow creation/editing.
// Hosts retain their draft and clear it only after their mutation is accepted.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/workspace/WorkspacePromptComposer.svelte
//          `collapsible` is true only for Task/Workflow surfaces; Projects stay one 64pt row
//          (radius 24 when focused or with text, inline mic and labeled submit, Cancel outside the form).
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.layout.responsive-parity, message-input.focus.workspace-suppression
struct WorkspacePromptComposerView: View {
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
    var compact: Bool? = nil
    var focusRequestID: UUID? = nil
    var onActiveChanged: (Bool) -> Void = { _ in }
    var dismissRequestID: UUID? = nil
    var availableHeight: CGFloat = 350
    /// Tasks/Workflows expand into the chat-composer layout; Projects keep one
    /// fixed 64pt row (the editor scrolls internally) with inline actions.
    var collapsible: Bool = true

    @StateObject private var session = NativeComposerSession()
    @State private var focused = false
    @State private var active = false
    @State private var expanded = false
    @State private var contentOverflows = false
    @State private var inlineActionsWidth: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var hasText: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    private var animation: Animation? { reduceMotion ? nil : .easeInOut(duration: 0.25) }
    private var focus: Binding<Bool> {
        Binding(get: { focused }, set: { value in
            focused = value
            if value { activate() }
        })
    }

    private var inlineRowActions: AnyView {
        AnyView(HStack {
            Spacer()
            HStack(spacing: .spacing2) {
                if active && hasText {
                    MessageComposerSendButton(title: submitting ? submittingLabel : submitLabel,
                        disabled: disabled || submitting, action: submit)
                        .accessibilityIdentifier(submitIdentifier)
                }
                MessageComposerActionIcon(icon: "recordaudio", label: AppStrings.projectVoiceInput,
                    identifier: micIdentifier, action: onMic).disabled(disabled || submitting)
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width in
                if abs(inlineActionsWidth - width) > 0.5 { inlineActionsWidth = width }
            }
        }
        .padding(.trailing, .spacing10))
    }

    @ViewBuilder private var cancelButton: some View {
        if active {
            Button(action: collapse) { ComposerDismissLabel(title: AppStrings.cancel) }
                .buttonStyle(.plain)
                .accessibilityIdentifier("\(identifier)-cancel")
        }
    }

    private var rowComposer: some View {
        MessageComposerView(session: session, isFocused: focus, compact: true,
            placeholder: placeholder, compactHeight: 64,
            compactCornerRadius: (active || hasText) ? 24 : 32,
            maxWidth: 629, accessibilityHint: placeholder,
            onSubmit: submit,
            idleFieldContent: inlineRowActions,
            actionButtons: { EmptyView() })
            .environment(\.composerRowActionsInset, hasText || active ? inlineActionsWidth + .spacing10 : 0)
            .environment(\.workspacePromptEditorIdentifier, inputIdentifier)
            .environment(\.workspacePromptEditorEditable, !disabled && !submitting)
            .accessibilityIdentifier("\(inputIdentifier)-hit-region")
    }

    var body: some View {
        Group {
            if collapsible {
                collapsibleBody
            } else {
                VStack(spacing: .spacing2) {
                    rowComposer
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier(identifier)
                    cancelButton
                }
                .frame(maxWidth: 629)
            }
        }
        .animation(animation, value: active)
        .task { session.replaceMarkdown(text) }
        .onChange(of: text) { oldValue, newValue in
            // Native editing has already updated the session. A host clearing
            // its still populated session signals an accepted mutation.
            let hostCleared = !oldValue.isEmpty && newValue.isEmpty && !session.canonicalMarkdown.isEmpty
            session.replaceMarkdown(newValue)
            if hostCleared { collapse() }
        }
        .onChange(of: session.canonicalMarkdown) { _, value in
            if value != text { text = value }
        }
        .task(id: focusRequestID) {
            guard focusRequestID != nil, !disabled else { return }
            activate(); focused = true
        }
        .onChange(of: dismissRequestID) { _, _ in collapse() }
        .onDisappear { onActiveChanged(false) }
    }

    private var collapsibleBody: some View {
        VStack(spacing: .spacing2) {
            MessageComposerView(session: session, isFocused: focus, compact: !active,
                placeholder: placeholder, compactHeight: 64, compactCornerRadius: 32,
                expandedMinHeight: expanded ? max(0, availableHeight - MessageComposerMetric.expandedTopReservedHeight) : 100,
                maxWidth: 629, accessibilityHint: placeholder,
                onSubmit: submit,
                idleFieldContent: !active ? AnyView(HStack {
                    Spacer()
                    MessageComposerActionIcon(icon: "recordaudio", label: AppStrings.projectVoiceInput,
                        identifier: micIdentifier, action: onMic).disabled(disabled || submitting)
                }.padding(.trailing, .spacing10)) : nil,
                actionButtons: {
                    HStack {
                        Spacer()
                        if hasText {
                            MessageComposerSendButton(title: submitting ? submittingLabel : submitLabel,
                                disabled: disabled || submitting, action: submit)
                                .accessibilityIdentifier(submitIdentifier)
                        }
                        MessageComposerActionIcon(icon: "recordaudio",
                            label: AppStrings.projectVoiceInput, identifier: micIdentifier, action: onMic)
                            .disabled(disabled || submitting)
                    }
                    .padding(.horizontal, .spacing4)
                    .frame(height: 56)
                })
                .environment(\.composerFieldMaximumHeight, max(0, availableHeight - MessageComposerMetric.expandedTopReservedHeight))
                .environment(\.composerFullscreen, expanded)
                .onPreferenceChange(ComposerNativeOverflowPreferenceKey.self) { contentOverflows = $0 }
                .environment(\.workspacePromptEditorIdentifier, inputIdentifier)
                .environment(\.workspacePromptEditorEditable, !disabled && !submitting)
                .accessibilityIdentifier("\(inputIdentifier)-hit-region")
                .overlay(alignment: .topTrailing) {
                    if active && (expanded || contentOverflows) {
                        Button {
                            withAnimation(animation) { expanded.toggle() }
                            focused = true
                        } label: {
                            Icon(expanded ? "minimize" : "fullscreen", size: 20)
                                .foregroundStyle(LinearGradient.primary)
                                .frame(width: 44, height: 44)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .zIndex(10)
                        .accessibilityLabel(expanded ? AppStrings.exitFullscreen : AppStrings.enterFullscreen)
                        .accessibilityIdentifier("\(identifier)-expand")
                    }
                }
            if active {
                Button(action: collapse) { ComposerDismissLabel(title: AppStrings.cancel) }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("\(identifier)-cancel")
            }
        }
        .frame(maxWidth: 629)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
    }

    private func activate() {
        guard !disabled else { return }
        withAnimation(animation) { active = true }
        onActiveChanged(true)
    }
    private func collapse() {
        focused = false
        withAnimation(animation) { active = false; expanded = false }
        onActiveChanged(false)
    }
    private func submit() {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !disabled, !submitting, !value.isEmpty else { return }
        onSubmit(value)
        // Web submitComposer(): an accepted submit clears focusActive and blurs
        // the textarea, so the host's follow-up (the Project setup sheet) owns
        // the screen and the keyboard goes down. The draft text stays.
        if !collapsible { collapse() }
    }
}

extension View {
    func workspacePromptBackground(active: Bool, identifier: String, activeOpacity: Double = 0,
                                   onDismiss: @escaping () -> Void) -> some View {
        modifier(WorkspacePromptBackgroundModifier(active: active, identifier: identifier,
            activeOpacity: activeOpacity, onDismiss: onDismiss))
    }
}

private struct WorkspacePromptBackgroundModifier: ViewModifier {
    let active: Bool
    let identifier: String
    let activeOpacity: Double
    let onDismiss: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func body(content: Content) -> some View {
        content
            .opacity(active ? activeOpacity : 1)
            .disabled(active)
            .allowsHitTesting(!active)
            // Explicit child suppression also covers descendants that define
            // their own accessibility containers, such as InspirationCard.
            .accessibilityElement(children: active ? .ignore : .contain)
            .accessibilityHidden(active)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.25), value: active)
            .overlay { WorkspacePromptBackdrop(active: active, identifier: identifier,
                activeOpacity: activeOpacity, onDismiss: onDismiss) }
    }
}

/// Mount over host content, below its fixed composer. Outside taps collapse
/// editing while preserving the host's draft and native editor insertion point.
struct WorkspacePromptBackdrop: View {
    let active: Bool
    let identifier: String
    var activeOpacity: Double = 0
    let onDismiss: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        Group {
            if active {
                Button(action: onDismiss) {
                    Color.grey20.opacity(0.001).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.cancel)
                .accessibilityIdentifier(identifier)
                .accessibilityValue("background-opacity=\(activeOpacity == 0 ? "0" : activeOpacity == 1 ? "1" : String(activeOpacity));background-interactive=false")
                .transition(.opacity)
            }
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.25), value: active)
    }

}

private struct WorkspacePromptEditorIdentifierKey: EnvironmentKey {
    static let defaultValue = "message-editor"
}
private struct WorkspacePromptEditorEditableKey: EnvironmentKey {
    static let defaultValue = true
}
extension EnvironmentValues {
    var workspacePromptEditorIdentifier: String {
        get { self[WorkspacePromptEditorIdentifierKey.self] }
        set { self[WorkspacePromptEditorIdentifierKey.self] = newValue }
    }
    var workspacePromptEditorEditable: Bool {
        get { self[WorkspacePromptEditorEditableKey.self] }
        set { self[WorkspacePromptEditorEditableKey.self] = newValue }
    }
}

private struct WorkspaceViewportWidthKey: EnvironmentKey {
    static let defaultValue: CGFloat = 0
}

extension EnvironmentValues {
    // This is the scene viewport, rather than the composer capped at 629px.
    var workspaceViewportWidth: CGFloat {
        get { self[WorkspaceViewportWidthKey.self] }
        set { self[WorkspaceViewportWidthKey.self] = newValue }
    }
}
