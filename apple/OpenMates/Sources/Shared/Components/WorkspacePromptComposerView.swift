import SwiftUI

// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.new-task-shortcuts
// Shared Projects, Tasks and Workflows field; each surface owns its actions.
// Web source: frontend/packages/ui/src/components/workspace/WorkspacePromptComposer.svelte
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

    @Environment(\.workspaceViewportWidth) private var viewportWidth
    @Environment(\.horizontalSizeClass) private var sizeClass
    @FocusState private var focused: Bool

    private var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var isCompact: Bool {
        compact ?? (viewportWidth > 0 ? viewportWidth <= 730 : sizeClass == .compact)
    }

    var body: some View {
        HStack(spacing: .spacing4) {
            ZStack {
                // TextField's prompt truncates even for a vertical field. The
                // web textarea wraps its centered placeholder at this width.
                if text.isEmpty {
                    Text(placeholder)
                        .font(.omP.weight(.bold))
                        .foregroundStyle(Color.grey60)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
                TextField(placeholder, text: $text, prompt: Text(""), axis: .vertical)
                .textFieldStyle(.plain)
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
                .multilineTextAlignment(hasText || focused ? .leading : .center)
                .lineLimit(1...7)
                .fixedSize(horizontal: false, vertical: true)
                // The complete textarea region must receive pointer/touch events,
                // including the empty area above and below the first text line.
                .frame(maxWidth: .infinity, minHeight: 64)
                .focused($focused)
                .disabled(disabled)
                .submitLabel(.send)
                .onSubmit(submit)
                .accessibilityLabel(placeholder)
                .accessibilityIdentifier(inputIdentifier)
            }
            .frame(maxWidth: .infinity, minHeight: 64)
            .contentShape(Rectangle())
            .simultaneousGesture(TapGesture().onEnded {
                if !disabled { focused = true }
            })
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("\(inputIdentifier)-hit-region")

            if hasText {
                Button {
                    // Web clicking the submit button transfers focus away from
                    // the textarea; keyboard submission keeps the field focused.
                    focused = false
                    submit()
                } label: {
                    Text(submitting ? submittingLabel : submitLabel)
                        .font((isCompact ? Font.omSmall : .omP).weight(.heavy))
                        .foregroundStyle(Color.fontButton)
                        .padding(.vertical, .spacing4)
                        .padding(.horizontal, isCompact ? .spacing6 : .spacing8)
                        .frame(minHeight: 40)
                        .background(Color.buttonPrimary,
                                    in: RoundedRectangle(cornerRadius: .radius8))
                }
                .buttonStyle(.plain)
                .fixedSize()
                .disabled(disabled || submitting)
                .opacity(disabled || submitting ? 0.55 : 1)
                .accessibilityIdentifier(submitIdentifier)
            }
        }
        .padding(.leading, hasText || focused ? (isCompact ? 52 : 56) : (isCompact ? 58 : 64))
        .padding(.trailing, hasText || focused ? (isCompact ? .spacing4 : .spacing5) : (isCompact ? 58 : 64))
        .frame(maxWidth: 629, minHeight: 64)
        .background(Color.greyBlue,
                    in: RoundedRectangle(cornerRadius: hasText || focused ? 24 : 32))
        .overlay(alignment: .leading) {
            Icon("ai", size: 24)
                .foregroundStyle(Color.fontPrimary.opacity(0.72))
                .padding(.leading, 22)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
        .overlay(alignment: .trailing) {
            if !hasText {
                Button(action: onMic) {
                    Icon("recordaudio", size: 24)
                        .foregroundStyle(LinearGradient.primary)
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.trailing, 14)
                .disabled(disabled)
                .opacity(disabled ? 0.55 : 1)
                .accessibilityLabel(AppStrings.projectVoiceInput)
                .accessibilityIdentifier(micIdentifier)
            }
        }
        .shadow(color: .black.opacity(0.08), radius: 12, y: 4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
        .task(id: focusRequestID) {
            if focusRequestID != nil, !disabled { focused = true }
        }
    }

    private func submit() {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !disabled, !submitting, !value.isEmpty else { return }
        onSubmit(value)
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
