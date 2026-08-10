// Shared OpenMates message composer for Apple product surfaces.
// This is the native counterpart to the web MessageInput.svelte and
// ActionButtons.svelte shell: hosts provide destination/send plumbing, while
// this component owns the field shape, action row placement, gradient icons,
// and stable accessibility identifiers used by parity tests.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//          frontend/packages/ui/src/components/enter_message/ActionButtons.svelte
// CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//          .message-field, .message-field.inline-compact, .action-buttons
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

enum MessageComposerMetric {
    /// Web `ActiveChat.svelte`: `.message-input-container :global(> *:not(.suggestions-wrapper)) { max-width: 629px; }`.
    static let mainAppMaxWidth: CGFloat = 629
    /// Web `MessageInput.styles.css`: `.message-field { min-height: 100px; border-radius: 24px; padding-bottom: 60px; }`.
    static let expandedMinHeight: CGFloat = 100
    /// Browser-computed focused empty field height at 393x852: 117.59px from MessageInput's editor line box plus action row.
    static let focusedEmptyHeight: CGFloat = 118
    /// Web `MessageInput.styles.css`: `.message-field { max-height: 350px; }`.
    static let expandedMaxHeight: CGFloat = 350
    static let expandedCornerRadius: CGFloat = 24
    /// Web `MessageInput.styles.css`: `.message-field.inline-compact { min-height/max-height: 48px; border-radius: radius-full; }`.
    static let inlineCompactHeight: CGFloat = 48
}

enum MessageComposerPresentation {
    static func showsPlaceholder(markdown: String, isFocused: Bool) -> Bool {
        markdown.isEmpty && !isFocused
    }
}

struct MessageComposerCapabilities: Equatable {
    var files = false
    var maps = false
    var sketch = false
    var camera = false
    var recordAudio = false
    var send = true

    static let mainChat = MessageComposerCapabilities(files: true, maps: true, sketch: true, camera: true, recordAudio: true, send: true)
    static let welcome = MessageComposerCapabilities(files: true, maps: true, sketch: true, camera: true, recordAudio: true, send: true)
    static let quickCapture = MessageComposerCapabilities(files: false, maps: false, sketch: false, camera: false, recordAudio: true, send: true)

    var orderedActions: [MessageComposerAction] {
        var actions: [MessageComposerAction] = []
        if files { actions.append(.files) }
        if maps { actions.append(.maps) }
        if sketch { actions.append(.sketch) }
        if camera { actions.append(.camera) }
        if recordAudio { actions.append(.recordAudio) }
        if send { actions.append(.send) }
        return actions
    }

    func showsSendButton(text: String, hasPendingEmbeds: Bool) -> Bool {
        send && (!text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || hasPendingEmbeds)
    }
}

enum MessageComposerAction: Equatable {
    case files
    case maps
    case sketch
    case camera
    case recordAudio
    case send
}

struct MessageComposerView<PreFieldContent: View, OverlayContent: View, ActionButtons: View>: View {
    @ObservedObject var session: NativeComposerSession
    let isFocused: Binding<Bool>
    var compact: Bool
    var placeholder: String
    var compactHeight: CGFloat = MessageComposerMetric.inlineCompactHeight
    var compactCornerRadius: CGFloat = .radiusFull
    var showActionButtonsWhenCompact = false
    var expandedMinHeight: CGFloat = MessageComposerMetric.expandedMinHeight
    var maxWidth: CGFloat? = MessageComposerMetric.mainAppMaxWidth
    var accessibilityHint: String = AppStrings.typeMessage
    var isComposerEditable = true
    var piiDecorations: [NativeComposerPIIDecoration] = []
    var onExcludePII: (String) -> Void = { _ in }
    var onSubmit: () -> Void
    var inlineFieldContent: AnyView? = nil
    @ViewBuilder var preFieldContent: () -> PreFieldContent
    @ViewBuilder var overlayContent: () -> OverlayContent
    @ViewBuilder var actionButtons: () -> ActionButtons

    var body: some View {
        VStack(spacing: .spacing2) {
            preFieldContent()

            OMMessageInputField(
                session: session,
                isFocused: isFocused,
                compact: compact,
                placeholder: placeholder,
                compactHeight: compactHeight,
                compactCornerRadius: compactCornerRadius,
                showActionButtonsWhenCompact: showActionButtonsWhenCompact,
                expandedMinHeight: expandedMinHeight,
                accessibilityHint: accessibilityHint,
                isComposerEditable: isComposerEditable,
                piiDecorations: piiDecorations,
                onExcludePII: onExcludePII,
                inlineFieldContent: inlineFieldContent,
                overlayContent: AnyView(overlayContent()),
                onSubmit: onSubmit
            ) {
                actionButtons()
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("action-buttons")
            }
        }
        .frame(maxWidth: maxWidth ?? .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("message-composer")
    }
}

extension MessageComposerView where PreFieldContent == EmptyView, OverlayContent == EmptyView {
    init(
        session: NativeComposerSession,
        isFocused: Binding<Bool>,
        compact: Bool,
        placeholder: String,
        compactHeight: CGFloat = MessageComposerMetric.inlineCompactHeight,
        compactCornerRadius: CGFloat = .radiusFull,
        showActionButtonsWhenCompact: Bool = false,
        expandedMinHeight: CGFloat = MessageComposerMetric.expandedMinHeight,
        maxWidth: CGFloat? = MessageComposerMetric.mainAppMaxWidth,
        accessibilityHint: String = AppStrings.typeMessage,
        onSubmit: @escaping () -> Void,
        @ViewBuilder actionButtons: @escaping () -> ActionButtons
    ) {
        self.init(
            session: session,
            isFocused: isFocused,
            compact: compact,
            placeholder: placeholder,
            compactHeight: compactHeight,
            compactCornerRadius: compactCornerRadius,
            showActionButtonsWhenCompact: showActionButtonsWhenCompact,
            expandedMinHeight: expandedMinHeight,
            maxWidth: maxWidth,
            accessibilityHint: accessibilityHint,
            onSubmit: onSubmit,
            inlineFieldContent: nil,
            preFieldContent: { EmptyView() },
            overlayContent: { EmptyView() },
            actionButtons: actionButtons
        )
    }
}

extension MessageComposerView where PreFieldContent == EmptyView {
    init(
        session: NativeComposerSession,
        isFocused: Binding<Bool>,
        compact: Bool,
        placeholder: String,
        compactHeight: CGFloat = MessageComposerMetric.inlineCompactHeight,
        compactCornerRadius: CGFloat = .radiusFull,
        showActionButtonsWhenCompact: Bool = false,
        expandedMinHeight: CGFloat = MessageComposerMetric.expandedMinHeight,
        maxWidth: CGFloat? = MessageComposerMetric.mainAppMaxWidth,
        accessibilityHint: String = AppStrings.typeMessage,
        onSubmit: @escaping () -> Void,
        @ViewBuilder overlayContent: @escaping () -> OverlayContent,
        @ViewBuilder actionButtons: @escaping () -> ActionButtons
    ) {
        self.init(
            session: session,
            isFocused: isFocused,
            compact: compact,
            placeholder: placeholder,
            compactHeight: compactHeight,
            compactCornerRadius: compactCornerRadius,
            showActionButtonsWhenCompact: showActionButtonsWhenCompact,
            expandedMinHeight: expandedMinHeight,
            maxWidth: maxWidth,
            accessibilityHint: accessibilityHint,
            onSubmit: onSubmit,
            inlineFieldContent: nil,
            preFieldContent: { EmptyView() },
            overlayContent: overlayContent,
            actionButtons: actionButtons
        )
    }
}

extension MessageComposerView where OverlayContent == EmptyView {
    init(
        session: NativeComposerSession,
        isFocused: Binding<Bool>,
        compact: Bool,
        placeholder: String,
        compactHeight: CGFloat = MessageComposerMetric.inlineCompactHeight,
        compactCornerRadius: CGFloat = .radiusFull,
        showActionButtonsWhenCompact: Bool = false,
        expandedMinHeight: CGFloat = MessageComposerMetric.expandedMinHeight,
        maxWidth: CGFloat? = MessageComposerMetric.mainAppMaxWidth,
        accessibilityHint: String = AppStrings.typeMessage,
        onSubmit: @escaping () -> Void,
        @ViewBuilder preFieldContent: @escaping () -> PreFieldContent,
        @ViewBuilder actionButtons: @escaping () -> ActionButtons
    ) {
        self.init(
            session: session,
            isFocused: isFocused,
            compact: compact,
            placeholder: placeholder,
            compactHeight: compactHeight,
            compactCornerRadius: compactCornerRadius,
            showActionButtonsWhenCompact: showActionButtonsWhenCompact,
            expandedMinHeight: expandedMinHeight,
            maxWidth: maxWidth,
            accessibilityHint: accessibilityHint,
            onSubmit: onSubmit,
            inlineFieldContent: nil,
            preFieldContent: preFieldContent,
            overlayContent: { EmptyView() },
            actionButtons: actionButtons
        )
    }
}

struct MessageComposerActionIcon: View {
    let icon: String
    let label: String
    var identifier: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Icon(icon, size: 25)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 25, height: 25)
        }
        .buttonStyle(.plain)
        .help(Text(label))
        .accessibilityLabel(label)
        .modifier(OptionalAccessibilityIdentifier(identifier: identifier))
    }
}

struct MessageComposerSendButton: View {
    let title: String
    var disabled = false
    var accessibilityLabel: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.omP)
                .fontWeight(.medium)
                .foregroundStyle(Color.fontButton)
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing4)
                .frame(height: 40)
                .background(Color.buttonPrimary)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.6 : 1.0)
        .help(Text(accessibilityLabel ?? title))
        .accessibilityLabel(accessibilityLabel ?? title)
        .accessibilityIdentifier("send-button")
    }
}

private struct OptionalAccessibilityIdentifier: ViewModifier {
    let identifier: String?

    func body(content: Content) -> some View {
        if let identifier {
            content.accessibilityIdentifier(identifier)
        } else {
            content
        }
    }
}
