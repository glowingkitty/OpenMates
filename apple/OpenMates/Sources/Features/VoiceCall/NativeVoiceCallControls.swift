// Web source: frontend/packages/ui/src/components/voicecall/VoiceCallBar.svelte
// Computed reference: .runtime/followups123/web-voice-reference362.json (root).
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-strip-layout, video-call.chat.fixed-binding,
// video-call.privacy.first-call-warning
// Source geometry only; actual Apple appearance/audio proof belongs to root.
#if !os(watchOS)
import SwiftUI

/// Install above the root navigation container. Changing destinations never
/// destroys the coordinator or ends its fixed-chat call.
struct NativeVoiceCallOverlay: View {
    @ObservedObject var coordinator: NativeVoiceCallAppCoordinator
    let returnToChat: (String) -> Void
    var body: some View {
        ZStack {
            VStack {
                Spacer()
                if coordinator.isActive || coordinator.state.status == .failed || coordinator.integrationError != nil {
                    VStack(spacing: .spacing4) {
                        if let error = coordinator.integrationError ?? coordinator.state.error {
                            Text(AppStrings.nativeCallError(error)).font(.omSmall)
                                .accessibilityIdentifier("voice-call-error")
                        }
                        NativeVoiceCallBar(coordinator: coordinator, returnToChat: returnToChat)
                    }
                    .padding(.horizontal, .spacing6).padding(.bottom, .spacing4)
                }
            }
            .accessibilityHidden(coordinator.consentRequestID != nil)
            if let id = coordinator.consentRequestID {
                Color.black.opacity(0.35).ignoresSafeArea()
                NativeVoiceCallConsentView {
                    coordinator.decideConsent(id: id, accepted: $0)
                }.padding(.spacing10)
            }
        }
        // No onDisappear hangup: this surface is navigation-persistent.
    }
}

struct NativeVoiceCallBar: View {
    @ObservedObject var coordinator: NativeVoiceCallAppCoordinator
    let returnToChat: (String) -> Void
    private var status: String {
        if coordinator.state.status == .connecting { return AppStrings.nativeCall("connecting") }
        if coordinator.state.processing { return AppStrings.nativeCall("working") }
        if coordinator.state.muted { return AppStrings.nativeCall("muted") }
        if coordinator.state.inputIdle, !coordinator.state.inputListening, !coordinator.state.processing { return AppStrings.nativeCall("input_idle") }
        return AppStrings.nativeCall("live")
    }
    var body: some View {
        HStack(spacing: .spacing2) {
            control(coordinator.minimized ? "fullscreen" : "minimize",
                    label: AppStrings.nativeCall(coordinator.minimized ? "expand" : "minimize"), id: "voice-call-minimize") {
                coordinator.minimized.toggle()
            }
            Button {
                if let id = coordinator.boundChatID { returnToChat(id) }
            } label: {
                Text(coordinator.formattedDuration).font(.omH4.weight(.bold)).monospacedDigit()
                    .frame(minWidth: 44, minHeight: 44)
            }
            .buttonStyle(.plain).accessibilityLabel(AppStrings.nativeCall("return_to_chat"))
            .accessibilityIdentifier("voice-call-return")
            ZStack {
                if !coordinator.minimized {
                    NativeVoiceCallMeter(levels: coordinator.meterLevels, muted: coordinator.state.muted)
                        .frame(height: .spacing16).accessibilityHidden(true)
                }
                control("recordaudio", label: AppStrings.nativeCall(coordinator.state.muted ? "unmute" : "mute"),
                        id: "voice-call-mute", muted: coordinator.state.muted) {
                    Task { await coordinator.setMuted(!coordinator.state.muted) }
                }
                .foregroundStyle(coordinator.state.muted ? Color.buttonPrimary : .white)
                .disabled(coordinator.state.status != .live)
                .accessibilityValue(status)
            }
            .frame(maxWidth: coordinator.minimized ? 44 : .infinity, minHeight: 44)
            control("audiocall", label: AppStrings.nativeCall(coordinator.isActive ? "hangup" : "close"),
                    id: "voice-call-hangup", destructive: true) {
                if coordinator.isActive { Task { await coordinator.hangup() } }
                else { coordinator.dismissError() }
            }
        }
        .foregroundStyle(.white).padding(.spacing4)
        .frame(maxWidth: coordinator.minimized ? 224 : 390).frame(height: 68)
        .background(LinearGradient.primary)
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .accessibilityIdentifier(coordinator.minimized ? "voice-call-minimized" : "voice-call-bar")
    }
    private func control(_ symbol: String, label: String, id: String, destructive: Bool = false, muted: Bool = false,
                         action: @escaping () -> Void) -> some View {
        Button(action: action) {
            ZStack {
                Icon(symbol, size: 28).rotationEffect(.degrees(destructive ? 135 : 0))
                    .foregroundStyle(destructive ? Color.buttonPrimary : (muted ? Color.buttonPrimary : .white))
                if muted {
                    Capsule().fill(Color.buttonPrimary).frame(width: 24, height: 3)
                        .rotationEffect(.degrees(-45))
                }
            }
            // VoiceCallBar .round: 44px, 20% white, 28px web icon.
            .frame(width: 44, height: 44).background(.white.opacity(0.2)).clipShape(Circle())
        }.buttonStyle(.plain).accessibilityLabel(label).accessibilityIdentifier(id)
    }
}

private struct NativeVoiceCallMeter: View {
    let levels: [Float]
    let muted: Bool
    var body: some View {
        GeometryReader { geometry in
            if levels.isEmpty || muted {
                // No invented amplitude when the adapter has not supplied it.
                Capsule().fill(.white.opacity(0.55)).frame(height: 2)
                    .frame(maxHeight: .infinity)
            } else {
                HStack(alignment: .center, spacing: .spacing1) {
                    ForEach(Array(levels.enumerated()), id: \.offset) { _, level in
                        Capsule().fill(.white).frame(height: max(2, CGFloat(level) * geometry.size.height))
                    }
                }.frame(maxHeight: .infinity)
            }
        }
    }
}

struct NativeVoiceCallConsentView: View {
    let decide: (Bool) -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            Text(AppStrings.nativeCall("privacy_title")).font(.omH3.weight(.semibold))
            Text(AppStrings.nativeCall("privacy_description")).font(.omP)
            Text(AppStrings.nativeCall("pricing_explanation")).font(.omSmall).foregroundStyle(Color.fontSecondary)
            Link(AppStrings.nativeCall("privacy_terms"), destination: URL(string: "https://legal.mistral.ai/terms/privacy-policy")!)
                .buttonStyle(.plain).foregroundStyle(Color.settingsPrimaryStart)
                .frame(minHeight: 44).accessibilityIdentifier("voice-call-consent-terms")
            HStack(spacing: .spacing6) {
                Button(AppStrings.cancel) { decide(false) }.frame(maxWidth: .infinity, minHeight: 44)
                    .accessibilityIdentifier("voice-call-consent-cancel")
                Button(AppStrings.nativeCall("privacy_continue")) { decide(true) }
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .accessibilityIdentifier("voice-call-consent-continue")
            }.buttonStyle(OMSettingsButtonStyle())
        }
        .padding(.spacing10).frame(maxWidth: 440)
        .background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius7))
        .overlay(RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey25, lineWidth: 1))
        .accessibilityElement(children: .contain).accessibilityIdentifier("voice-call-consent")
    }
}
#endif
