// Shared OpenMates message composer for Apple product surfaces.
// This is the native counterpart to the web MessageInput.svelte and
// ActionButtons.svelte shell: hosts provide destination/send plumbing, while
// this component owns the field shape, action row placement, gradient icons,
// and stable accessibility identifiers used by parity tests.
// Specification: specifications/features/message-input/specification.yml
// Assertion: message-input.layout.responsive-parity

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//          frontend/packages/ui/src/components/enter_message/ActionButtons.svelte
// CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//          .message-field, .message-field.inline-compact, .action-buttons
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct CompactKeyboardComposerEligibilityPreferenceKey: PreferenceKey {
    static let defaultValue = false
    static func reduce(value: inout Bool, nextValue: () -> Bool) { value = value || nextValue() }
}

enum MessageComposerMetric {
    /// Web `ActiveChat.svelte`: `.message-input-container :global(> *:not(.suggestions-wrapper)) { max-width: 629px; }`.
    static let mainAppMaxWidth: CGFloat = 629
    /// Web `MessageInput.styles.css`: `.message-field { min-height: 100px; border-radius: 24px; padding-bottom: 60px; }`.
    static let expandedMinHeight: CGFloat = 100
    /// Browser-computed focused empty field height at 393x852: 117.59px from MessageInput's editor line box plus action row.
    static let focusedEmptyHeight: CGFloat = 118
    /// Web ProseMirror body typography uses a 1.6 line-height at 16px.
    static let editorLineHeight: CGFloat = 25.6
    /// Keep the three most recent lines visible in the collapsed composer before its editor scrolls.
    static let collapsedVisibleLineCount: CGFloat = 3
    /// Matches the native editor's 14pt top and bottom text-container insets.
    static let editorVerticalInset: CGFloat = .spacing6 + .spacing1
    /// Fullscreen hosts retain this dismissal/outside budget; plaintext no
    /// longer adds it above the editor. The icon shares its first text line.
    static let expandedTopReservedHeight: CGFloat = .spacing20 + .spacing10
    static let expandControlSize: CGFloat = 44
    static let expandControlTopInset: CGFloat = 10
    static let expandControlTrailingInset: CGFloat = 15
    static let expandControlContentGap: CGFloat = .spacing2
    static let editorHorizontalInset: CGFloat = .spacing6
    static let plaintextControlRightInset = expandControlSize + expandControlTrailingInset + expandControlContentGap
    static let mediaPreviewWidth: CGFloat = 300
    /// Space reserved below the editor for the web-parity action row.
    static let expandedBottomReservedHeight: CGFloat = .spacing20 + .spacing10
    static let collapsedTextEditorMaxHeight: CGFloat =
        (editorVerticalInset * 2) + (editorLineHeight * collapsedVisibleLineCount)
    static let collapsedTextFieldMaxHeight: CGFloat =
        collapsedTextEditorMaxHeight + expandedBottomReservedHeight
    /// Web image previews are 300x200. Keep that full card plus three message
    /// lines visible before the editor itself begins scrolling.
    static let embedPreviewHeight: CGFloat = 200
    static let embedTextEditorMaxHeight: CGFloat =
        embedPreviewHeight + (editorVerticalInset * 2) + (editorLineHeight * collapsedVisibleLineCount)
    static let embedTextFieldMaxHeight: CGFloat =
        embedTextEditorMaxHeight + expandedBottomReservedHeight
    /// Web `MessageInput.styles.css`: `.message-field { max-height: 350px; }`.
    static let expandedMaxHeight: CGFloat = 350
    static let expandedCornerRadius: CGFloat = 24
    /// Web `MessageInput.styles.css`: `.message-field.inline-compact { min-height/max-height: 48px; border-radius: radius-full; }`.
    static let inlineCompactHeight: CGFloat = 48
    /// Web draft-preview summary retains a single 60pt row.
    static let draftPreviewHeight: CGFloat = 60

    static func compactKeyboardLayout(isPhone: Bool, compactHeight: Bool, keyboardVisible: Bool) -> Bool {
        isPhone && compactHeight && keyboardVisible
    }

    static func welcomeMaximumFieldHeight(availableHeight: CGFloat, compactKeyboardLayout: Bool) -> CGFloat {
        // Dismissal and stack retain their budget; reclaim only the actual
        // 20-point outside bottom inset removed by the Welcome host.
        let outsideReserve = expandedTopReservedHeight - (compactKeyboardLayout ? .spacing10 : 0)
        return max(0, availableHeight - outsideReserve)
    }

    static func boundedFieldHeight(intrinsicHeight: CGFloat, maximumHeight: CGFloat?,
                                   compact: Bool, fullscreen: Bool, containsEmbed: Bool,
                                   topReservedHeight: CGFloat, hasInlineContent: Bool = false) -> CGFloat {
        guard let maximumHeight else { return intrinsicHeight }
        let cap = max(0, maximumHeight)
        if !compact && !fullscreen && !containsEmbed && !hasInlineContent
            && cap < collapsedTextFieldMaxHeight + topReservedHeight {
            return min(intrinsicHeight, focusedEmptyHeight + topReservedHeight, cap)
        }
        return min(intrinsicHeight, cap)
    }

    static func editorHeight(for contentHeight: CGFloat, containsEmbed: Bool) -> CGFloat {
        min(contentHeight, containsEmbed ? embedTextEditorMaxHeight : collapsedTextEditorMaxHeight)
    }
}

enum MessageComposerPresentation {
    static func showsPlaceholder(markdown: String, isFocused: Bool) -> Bool {
        markdown.isEmpty && !isFocused
    }

    @MainActor static func draftPreviewSummary(document: ComposerDocumentV1) -> String {
        document.nodes.map { node in
            switch node.kind {
            case "embed":
                let type = node.embedType == "recording" ? "audio" : node.embedType ?? "embed"
                return " " + AppStrings.draftEmbedPreviewLabel(type: type) + " "
            case "mention": return node.displayLabel ?? node.canonicalSyntax ?? ""
            case "hardBreak": return " "
            default: return node.source ?? ""
            }
        }.joined().split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    @MainActor static func showsDraftPreview(document: ComposerDocumentV1, isFocused: Bool,
                                  isExpanded: Bool, hasActiveOverlay: Bool) -> Bool {
        !isFocused && !isExpanded && !hasActiveOverlay
            && !draftPreviewSummary(document: document).isEmpty
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

/// Idle decoration must not cover the retained native editor. Restrict the
/// overlay's interaction surface to its actual trailing microphone/stop control.
struct ComposerIdleControlHitRegion: Shape {
    var isRTL: Bool
    func path(in rect: CGRect) -> Path {
        let width = min(44, rect.width)
        let height = min(44, rect.height)
        let x = isRTL ? rect.minX + 14 : rect.maxX - 14 - width
        return Path(CGRect(x: x, y: rect.midY - height / 2, width: width, height: height))
    }
}

struct ComposerIdleFieldControls<Control: View>: View {
    @Environment(\.layoutDirection) private var layoutDirection
    @ViewBuilder var control: () -> Control

    var body: some View {
        ZStack(alignment: .trailing) {
            HStack(spacing: 0) {
                Icon("ai", size: 24)
                    .foregroundStyle(LinearGradient.primary)
                    .accessibilityHidden(true)
                Spacer(minLength: 0)
            }
            .allowsHitTesting(false)

            control()
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .padding(.leading, 22)
        .padding(.trailing, 14)
        .contentShape(.interaction, ComposerIdleControlHitRegion(isRTL: layoutDirection == .rightToLeft))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("message-input-idle-actions")
    }
}

/// Display-only projection. The retained semantic editor remains the draft authority.
/// Restore and microphone are sibling buttons so a microphone tap cannot focus the editor.
struct ComposerDraftPreviewField: View {
    let summary: String
    let microphone: AnyView
    let onRestore: () -> Void
    var fieldAccessibilityIdentifier = "message-draft-preview-surface"

    var body: some View {
        HStack(spacing: .spacing4) {
            Button(action: onRestore) {
                HStack(spacing: .spacing4) {
                    Icon("ai", size: 24)
                        .foregroundStyle(LinearGradient.primary)
                        .accessibilityHidden(true)
                    Text(summary)
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityIdentifier("message-draft-summary-text")
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("message-draft-summary")

            microphone
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .padding(.leading, 22)
        .padding(.trailing, 14)
        .frame(maxWidth: .infinity)
        .frame(height: MessageComposerMetric.draftPreviewHeight)
        .background(Color.greyBlue, in: RoundedRectangle(cornerRadius: 24))
        .shadow(color: .black.opacity(0.08), radius: 12, x: 0, y: 4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(fieldAccessibilityIdentifier)
    }
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
    var idleFieldContent: AnyView? = nil
    // Hosts explicitly opt in after evaluating focus, fullscreen and active overlays.
    var showsDraftPreview = false
    var draftPreviewMicrophone: AnyView? = nil
    var onRestoreDraft: (() -> Void)? = nil
    @ViewBuilder var preFieldContent: () -> PreFieldContent
    @ViewBuilder var overlayContent: () -> OverlayContent
    @ViewBuilder var actionButtons: () -> ActionButtons

    var body: some View {
        VStack(spacing: .spacing2) {
            preFieldContent()

            OMMessageInputField(
                session: session,
                isFocused: isFocused,
                compact: compact || showsDraftPreview,
                placeholder: placeholder,
                compactHeight: showsDraftPreview ? MessageComposerMetric.draftPreviewHeight : compactHeight,
                compactCornerRadius: compactCornerRadius,
                showActionButtonsWhenCompact: !showsDraftPreview && showActionButtonsWhenCompact,
                expandedMinHeight: expandedMinHeight,
                fieldAccessibilityIdentifier: showsDraftPreview ? "message-input-retained-editor-field" : "message-field",
                accessibilityHint: accessibilityHint,
                isComposerEditable: isComposerEditable,
                piiDecorations: piiDecorations,
                onExcludePII: onExcludePII,
                inlineFieldContent: inlineFieldContent,
                idleFieldContent: idleFieldContent,
                overlayContent: AnyView(overlayContent()),
                onSubmit: onSubmit
            ) {
                actionButtons()
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("action-buttons")
            }
            .opacity(showsDraftPreview ? 0 : 1)
            .allowsHitTesting(!showsDraftPreview)
            .accessibilityHidden(showsDraftPreview)
            .overlay {
                // Keep the microphone mounted across the recording-start transition.
                if let draftPreviewMicrophone {
                    ComposerDraftPreviewField(
                        summary: MessageComposerPresentation.draftPreviewSummary(document: session.controller.document),
                        microphone: draftPreviewMicrophone,
                        onRestore: onRestoreDraft ?? { isFocused.wrappedValue = true },
                        fieldAccessibilityIdentifier: showsDraftPreview ? "message-field" : "message-draft-preview-surface"
                    )
                    .opacity(showsDraftPreview ? 1 : 0)
                    .allowsHitTesting(showsDraftPreview)
                    .accessibilityHidden(!showsDraftPreview)
                }
            }
            .animation(.easeInOut(duration: 0.25), value: showsDraftPreview)
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
        idleFieldContent: AnyView? = nil,
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
            idleFieldContent: idleFieldContent,
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
        #if DEBUG && os(iOS)
        .background {
            if NativeComposerReactionMetrics.enabled {
                NativeComposerReadyRenderProbe(enabled: !disabled)
                    .allowsHitTesting(false).accessibilityHidden(true)
            }
        }
        #endif
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

struct ComposerNativeOverflowPreferenceKey: PreferenceKey {
    static var defaultValue: Bool { false }
    static func reduce(value: inout Bool, nextValue: () -> Bool) { value = value || nextValue() }
}
private struct ComposerFullscreenKey: EnvironmentKey { static var defaultValue: Bool { false } }
extension EnvironmentValues {
    var composerFullscreen: Bool {
        get { self[ComposerFullscreenKey.self] }
        set { self[ComposerFullscreenKey.self] = newValue }
    }
}
