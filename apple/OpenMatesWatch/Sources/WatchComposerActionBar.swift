// Fixed Watch phone, keyboard and microphone actions for new/existing chats.
// User-approved Watch placement: docs/plans/apple-october-web-parity/plan.yml
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//         frontend/packages/ui/src/components/enter_message/ActionButtons.svelte
// CSS: frontend/packages/ui/src/styles/fields.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// Computed reference: .runtime/followups123/web-voice-reference362.json
// Watch keeps the approved three-action placement. Common call targets are 44pt.
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions, apple-watch.chats.compact-layout
import SwiftUI

struct WatchComposerActionBar: View {
    let policy: WatchComposerControlPolicy
    let call: WatchCallActionProjection
    let tint: Color
    let onCall: () -> Void
    let onKeyboard: () -> Void
    let onRecord: () -> Void

    var body: some View {
        HStack(spacing: .spacing2) {
            action(icon: "phone", label: WatchLocalization.text(call.ownsAudio ? "videocall.hangup" : "videocall.voice_call"),
                   identifier: "watch-call-button", enabled: policy.canActivateCall,
                   active: call.ownsAudio, perform: onCall)
                .accessibilityValue(WatchLocalization.text(call.ownsAudio ? "videocall.conversation" :
                    (call.canStart ? "videocall.start" : "videocall.call_unavailable")))
            action(icon: "keyboard", label: WatchLocalization.text("watch.chats.enter_text"),
                   identifier: "watch-keyboard-button", enabled: policy.canEdit,
                   active: false, perform: onKeyboard)
            action(icon: "recordaudio", label: WatchLocalization.text(call.phase == .live
                    ? (call.muted ? "watch.chats.unmute_call" : "watch.chats.mute_call") : "enter_message.attachments.record_audio"),
                   identifier: "watch-audio-record-button", enabled: call.phase == .live ? !policy.busy : policy.canRecord,
                   active: call.phase == .live && !call.muted,
                   iconColor: call.phase == .live && call.muted ? Color.buttonPrimary : nil,
                   perform: onRecord)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-composer-actions")
    }

    private func action(icon: String, label: String, identifier: String, enabled: Bool,
                        active: Bool, iconColor: Color? = nil, perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            Image(icon)
                .renderingMode(.template)
                .resizable().scaledToFit()
                .frame(width: .spacing12, height: .spacing12)
                .foregroundStyle(active ? Color.fontButton : (iconColor ?? tint))
                .frame(width: 44, height: 44)
                .background(active ? tint : Color.grey90, in: Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.6)
        .accessibilityLabel(label)
        .accessibilityIdentifier(identifier)
        .frame(maxWidth: .infinity)
    }
}
