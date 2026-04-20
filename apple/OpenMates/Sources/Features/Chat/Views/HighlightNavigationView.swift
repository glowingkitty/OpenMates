// Highlight navigation — floating up/down buttons to jump between highlights in a chat.
// Mirrors the web app's HighlightNavigationOverlay.svelte.
// Also includes the text selection toolbar for creating new highlights.

import SwiftUI

// MARK: - Highlight navigation overlay (jump between highlights)

struct HighlightNavigationOverlay: View {
    let highlightCount: Int
    @Binding var currentIndex: Int
    let onDismiss: () -> Void

    var body: some View {
        if highlightCount > 0 {
            HStack(spacing: .spacing3) {
                Button {
                    currentIndex = max(0, currentIndex - 1)
                } label: {
                    Icon("up", size: 14)
                }
                .disabled(currentIndex <= 0)
                .accessibilityLabel("Previous highlight")

                Text("\(currentIndex + 1) / \(highlightCount)")
                    .font(.omXs).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .monospacedDigit()

                Button {
                    currentIndex = min(highlightCount - 1, currentIndex + 1)
                } label: {
                    Icon("down", size: 14)
                }
                .disabled(currentIndex >= highlightCount - 1)
                .accessibilityLabel("Next highlight")

                Divider().frame(height: 20)

                Button {
                    onDismiss()
                } label: {
                    Icon("close", size: 12)
                        .foregroundStyle(Color.fontTertiary)
                }
                .accessibilityLabel("Close highlight navigation")
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing2)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .shadow(color: .black.opacity(0.1), radius: 6, y: 2)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

// MARK: - Text selection toolbar (floating pill for highlight actions)

struct TextSelectionToolbar: View {
    let onHighlight: () -> Void
    let onHighlightWithComment: () -> Void
    let onCopy: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            ToolbarButton(icon: "highlighter", label: "Highlight") {
                onHighlight()
            }

            Divider().frame(height: 24)

            ToolbarButton(icon: "chat", label: "Comment") {
                onHighlightWithComment()
            }

            Divider().frame(height: 24)

            ToolbarButton(icon: "copy", label: "Copy") {
                onCopy()
            }
        }
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .shadow(color: .black.opacity(0.15), radius: 8, y: 4)
        .transition(.scale.combined(with: .opacity))
    }
}

private struct ToolbarButton: View {
    let icon: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 2) {
                Icon(icon, size: 16)
                Text(label)
                    .font(.system(size: 10))
            }
            .foregroundStyle(Color.fontPrimary)
            .frame(width: 64, height: 48)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
