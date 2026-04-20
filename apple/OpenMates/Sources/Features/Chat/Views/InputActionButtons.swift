// Input action buttons displayed inside the message field.
// Mirrors ActionButtons.svelte: left side has files/maps/sketch, right side has camera/record.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/ActionButtons.svelte
// CSS:     ActionButtons.svelte <style>
//          .action-buttons { position:absolute; bottom:1rem; left:1rem; right:1rem;
//                            display:flex; justify-content:space-between; height:40px }
//          .left-buttons / .right-buttons { gap:1rem }
// i18n:    enter_message.attachments.{attach_files,share_location,sketch,take_photo,record_audio}
//          enter_message.record_audio.press_and_hold_reminder
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct InputActionButtons: View {
    let onAttach: () -> Void
    let onMaps: () -> Void
    let onSketch: () -> Void
    let onCamera: () -> Void
    let onRecord: () -> Void
    /// Shows the "Press & hold to record" hint — set by parent after a short mic tap.
    var showPressHoldHint: Bool = false

    var body: some View {
        HStack {
            // Left buttons: files, location, sketch (matches ActionButtons.svelte .left-buttons)
            HStack(spacing: .spacing8) {
                ActionIcon("files", label: AppStrings.attachFiles, action: onAttach)
                ActionIcon("maps", label: AppStrings.shareLocation, action: onMaps)
                ActionIcon("modify", label: AppStrings.sketchAction, action: onSketch)
            }

            Spacer()

            // Right buttons: [press-hold hint] camera, record (matches .right-buttons)
            HStack(spacing: .spacing8) {
                if showPressHoldHint {
                    Text(AppStrings.pressAndHoldToRecord)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                        .transition(.opacity)
                }
                #if os(iOS)
                ActionIcon("take_photo", label: AppStrings.takePhoto, action: onCamera)
                #endif
                ActionIcon("recordaudio", label: AppStrings.recordAudio, action: onRecord)
            }
        }
        .frame(height: 40)
        .animation(.easeInOut(duration: 0.2), value: showPressHoldHint)
    }
}

private struct ActionIcon: View {
    let iconName: String
    let label: String
    let action: () -> Void

    init(_ iconName: String, label: String, action: @escaping () -> Void) {
        self.iconName = iconName
        self.label = label
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            Icon(iconName, size: 22)
                .foregroundStyle(Color.fontSecondary)
                .frame(width: 32, height: 32)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
