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
            // Left buttons: files, location, sketch
            HStack(spacing: .spacing8) {
                ActionIcon(systemName: "paperclip", label: AppStrings.attachFiles, action: onAttach)
                ActionIcon(systemName: "location", label: AppStrings.shareLocation, action: onMaps)
                ActionIcon(systemName: "pencil.tip", label: AppStrings.sketchAction, action: onSketch)
            }

            Spacer()

            // Right buttons: [press-hold hint] camera, record
            HStack(spacing: .spacing8) {
                if showPressHoldHint {
                    Text(AppStrings.pressAndHoldToRecord)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                        .transition(.opacity)
                }
                #if os(iOS)
                ActionIcon(systemName: "camera", label: AppStrings.takePhoto, action: onCamera)
                #endif
                ActionIcon(systemName: "mic", label: AppStrings.recordAudio, action: onRecord)
            }
        }
        .frame(height: 40)
        .animation(.easeInOut(duration: 0.2), value: showPressHoldHint)
    }
}

private struct ActionIcon: View {
    let systemName: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 18))
                .foregroundStyle(Color.fontSecondary)
                .frame(width: 32, height: 32)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
