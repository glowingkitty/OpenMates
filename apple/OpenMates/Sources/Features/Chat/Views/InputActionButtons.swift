// Input action buttons — row of quick-action buttons above the message input.
// Mirrors the web app's enter_message/ActionButtons.svelte: camera, sketch,
// maps, and file attachment shortcuts.

import SwiftUI

struct InputActionButtons: View {
    let onCamera: () -> Void
    let onSketch: () -> Void
    let onMaps: () -> Void
    let onAttach: () -> Void
    @State private var isExpanded = false

    var body: some View {
        HStack(spacing: .spacing2) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            } label: {
                Image(systemName: isExpanded ? "xmark" : "plus")
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(Color.fontSecondary)
                    .frame(width: 32, height: 32)
            }
            .accessibilityLabel(isExpanded ? "Close actions" : "More actions")

            if isExpanded {
                Group {
                    #if os(iOS)
                    ActionButton(icon: "camera", label: "Camera", action: onCamera)
                    ActionButton(icon: "paintbrush.pointed", label: "Sketch", action: onSketch)
                    #endif
                    ActionButton(icon: "map", label: "Location", action: onMaps)
                    ActionButton(icon: "paperclip", label: "File", action: onAttach)
                }
                .transition(.scale.combined(with: .opacity))
            }
        }
    }
}

private struct ActionButton: View {
    let icon: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundStyle(Color.fontSecondary)
                .frame(width: 32, height: 32)
                .background(Color.grey10)
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
