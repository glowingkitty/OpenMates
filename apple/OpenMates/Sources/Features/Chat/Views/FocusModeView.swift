// Focus mode UI — app-specific focus mode activation and management.
// Shows activation countdown, active pill above input, and context menu.

import SwiftUI

@MainActor
final class FocusModeManager: ObservableObject {
    @Published var activeFocusMode: FocusModeInfo?
    @Published var isActivating = false
    @Published var activationProgress: Double = 0

    struct FocusModeInfo: Equatable {
        let id: String
        let appId: String
        let name: String
    }

    func activate(_ focusMode: FocusModeInfo) {
        isActivating = true
        activationProgress = 0

        Task {
            for i in 1...20 {
                try? await Task.sleep(for: .milliseconds(200))
                activationProgress = Double(i) / 20.0
            }
            activeFocusMode = focusMode
            isActivating = false
            AccessibilityAnnouncement.announce("Focus mode \(focusMode.name) activated")
        }
    }

    func deactivate() {
        activeFocusMode = nil
        isActivating = false
        activationProgress = 0
    }
}

struct FocusModePill: View {
    @ObservedObject var focusModeManager: FocusModeManager
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    var body: some View {
        if let focus = focusModeManager.activeFocusMode {
            HStack(spacing: .spacing2) {
                AppIconView(appId: focus.appId, size: 20)
                    .accessibilityHidden(true)
                Text(focus.name)
                    .font(.omXs).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                Button {
                    focusModeManager.deactivate()
                    AccessibilityAnnouncement.announce("Focus mode \(focus.name) deactivated")
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(Color.fontTertiary)
                }
                .accessibleButton("Deactivate \(focus.name) focus mode", hint: "Removes the active focus mode from this chat")
            }
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .padding(.horizontal, .spacing4)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Focus mode active: \(focus.name)")
        } else if focusModeManager.isActivating {
            HStack(spacing: .spacing3) {
                ProgressView(value: focusModeManager.activationProgress)
                    .frame(width: 100)
                    .tint(Color.buttonPrimary)
                    .accessibilityHidden(true)
                Text(LocalizationManager.shared.text("embeds.focus_mode.activating"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing2)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Activating focus mode, \(Int(focusModeManager.activationProgress * 100)) percent complete")
        }
    }
}

struct FocusModeBadge: View {
    let appId: String

    var body: some View {
        Image(systemName: "scope")
            .font(.system(size: 8))
            .foregroundStyle(.white)
            .padding(3)
            .background(
                Circle().fill(Color.buttonPrimary)
            )
            .accessibilityHidden(true)
    }
}
