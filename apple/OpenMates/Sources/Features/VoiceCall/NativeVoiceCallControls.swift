// Web source: frontend/packages/ui/src/components/voicecall/VoiceCallBar.svelte
// Computed reference: .runtime/followups123/web-voice-reference362.json (root).
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/voicecall/VoiceCallBar.svelte
//          frontend/packages/ui/src/components/enter_message/VoiceCallLiveTranscript.svelte
//          (.call-live-transcript: font-primary at 0.45 opacity, 0.6 when submitted,
//          new words fade in over 320ms; reduced motion: no animation)
// Logic:   frontend/packages/ui/src/services/voiceCall.ts (liveTranscript, cameraError,
//          endBecauseMicrophoneLost -> voicecall.ended_in_background)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-strip-layout, video-call.chat.fixed-binding,
// video-call.privacy.first-call-warning, video-call.chat.transcripts, video-call.audio.background-resume,
// video-call.video.input-and-output
// Source geometry only; actual Apple appearance/audio proof belongs to root.
#if !os(watchOS)
import AVFoundation
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
                if coordinator.isActive || coordinator.state.status == .failed || coordinator.integrationError != nil
                    || coordinator.state.error == .endedInBackground {
                    VStack(spacing: .spacing4) {
                        // Web renders this inside the composer; the composer is
                        // owned by the chat window, so the call surface shows it.
                        if let live = coordinator.state.liveTranscript, coordinator.isActive {
                            NativeVoiceCallLiveTranscriptView(transcript: live)
                        }
                        if let error = coordinator.integrationError ?? coordinator.state.error {
                            Text(AppStrings.nativeCallError(error)).font(.omSmall)
                                .accessibilityIdentifier("voice-call-error")
                        } else if let notice = coordinator.state.cameraNotice, coordinator.isActive {
                            Text(AppStrings.nativeCallCameraNotice(notice)).font(.omSmall)
                                .accessibilityIdentifier("voice-call-camera-error")
                        }
                        if let failure = coordinator.camera.error, coordinator.isActive {
                            Text(AppStrings.nativeCall(failure.rawValue)).font(.omSmall)
                                .accessibilityIdentifier("voice-call-camera-error")
                        }
                        NativeVoiceCallCameraPreview(model: coordinator.camera)
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
    /// A capture device exists (web `hasCamera`); permission is asked when the button is used.
    private static var cameraAvailable: Bool { AVCaptureDevice.default(for: .video) != nil }
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
            NativeVoiceCallVideoButton(model: coordinator.camera, cameraAvailable: Self.cameraAvailable,
                                       live: coordinator.state.status == .live)
            #if os(iOS)
            if !coordinator.minimized, coordinator.state.status == .live {
                NativeVoiceCallScreenShareButton(reader: coordinator.screenShare)
            }
            #endif
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
        // Keeps the buttons' own identifiers: without it the bar's identifier replaces theirs.
        .accessibilityElement(children: .contain)
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

/// Display only: the user's in-progress utterance, never part of the draft.
struct NativeVoiceCallLiveTranscriptView: View {
    let transcript: NativeVoiceCallLiveTranscript
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        Text(transcript.text.trimmingCharacters(in: .whitespacesAndNewlines))
            .font(.omP).foregroundStyle(Color.fontPrimary)
            .opacity(transcript.submitted ? 0.6 : 0.45)
            .frame(maxWidth: 390, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.32), value: transcript.text)
            .allowsHitTesting(false)
            .accessibilityIdentifier("voice-call-live-transcript")
            .accessibilityAddTraits(.updatesFrequently)
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
