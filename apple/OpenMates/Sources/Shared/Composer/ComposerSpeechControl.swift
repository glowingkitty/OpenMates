import SwiftUI

// ActionButtons.svelte: 25pt glyph, 180ms opacity + status fly16, lifetime1800ms.
// Both images are exact web SVG paths copied into this artifact's asset catalog.
struct ComposerSpeechControl: View {
    @ObservedObject var speech: NativeAssistantSpeech
    var body: some View {
        HStack(spacing: 4) {
            if let state = speech.feedback {
                Text(text(state ? "speech_on" : "speech_off"))
                    .font(.system(size: 12, weight: .bold))
                    .transition(.asymmetric(insertion: .offset(x: 16).combined(with: .opacity),
                                            removal: .offset(x: 16).combined(with: .opacity)))
                    .accessibilityIdentifier("assistant-speech-toggle-status")
            }
            Button { Task { await speech.toggle() } } label: {
                ZStack {
                    Icon("assistant-speech-muted", size: 25).opacity(speech.enabled ? 0 : 1)
                    Icon("assistant-speech-audio", size: 25).opacity(speech.enabled ? 1 : 0)
                }.frame(width: 25, height: 25).contentShape(Circle())
            }.buttonStyle(.plain)
                .disabled(!speech.ready)
                .accessibilityLabel(text(speech.enabled ? "speech_disable" : "speech_enable"))
                .accessibilityValue(speech.enabled ? AppStrings.on : AppStrings.off)
                .accessibilityAddTraits(speech.enabled ? .isSelected : [])
                .accessibilityIdentifier("assistant-speech-toggle")
        }.foregroundStyle(Color(hex: 0x4867CD))
            .animation(.easeInOut(duration: 0.18), value: speech.enabled)
            .animation(.easeInOut(duration: 0.18), value: speech.feedback)
            .overlay(alignment: .topTrailing) {
                if let error = speech.error {
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(error).font(.caption).fixedSize(horizontal: false, vertical: true)
                        if speech.canRetry {
                            Button(AppStrings.retry) { Task { await speech.retry() } }.buttonStyle(.plain)
                        }
                    }.accessibilityIdentifier("assistant-speech-error").offset(y: -36)
                }
            }
    }
    private func text(_ key: String) -> String {
        LocalizationManager.shared.text("enter_message.\(key)")
    }
}
