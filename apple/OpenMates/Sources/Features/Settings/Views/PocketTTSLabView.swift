// Native-only developer experiment using canonical settings primitives.
// Web source: settings/elements/SettingsTextarea.svelte, SettingsButton.svelte, SettingsInfoBox.svelte
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.local-execution, apple-local-model-lab.ephemeral-state
import SwiftUI

struct PocketTTSLabView: View {
    @ObservedObject var controller: PocketTTSLabController
    let enabled: Bool
    var body: some View {
        OMSettingsInfoBox(message: AppStrings.localLabPocketDescription, identifier: "pocket-tts-scope")
        OMSettingsDetailRow(label: AppStrings.localLabPocketVoice, value: "Alba · CC BY 4.0")
        Link(AppStrings.localLabPocketAttribution,
             destination: URL(string: "https://huggingface.co/kyutai/tts-voices#alba-mackenna")!)
            .font(.omSmall)
        OMSettingsTextInput(label: AppStrings.localLabPocketInput, placeholder: AppStrings.localLabInputPlaceholder,
                            value: $controller.text, identifier: "pocket-tts-input", multiline: true)
            .disabled(!enabled || controller.busy)
        Text(AppStrings.localLabPocketInputLimit).font(.omSmall).foregroundStyle(Color.fontSecondary)
        Button(AppStrings.localLabRun) { controller.run(enabled: enabled) }
            .buttonStyle(OMSettingsButtonStyle())
            .disabled(!enabled || controller.busy || !controller.validInput || !controller.available)
            .accessibilityIdentifier("local-model-pocketTTS-run")
        if controller.busy {
            Text(controller.cancelling ? AppStrings.localLabPocketCancelling : phaseCopy(controller.measurement?.phase ?? .submission))
                .font(.omSmall).accessibilityIdentifier("pocket-tts-running")
            if controller.measurement?.warning == true {
                OMSettingsInfoBox(kind: .warning, message: AppStrings.localLabPhaseWarning, identifier: "pocket-tts-phase-warning")
            }
            Button(AppStrings.cancel) { controller.cancel() }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(controller.cancelling)
                .accessibilityIdentifier("pocket-tts-cancel")
        }
        if let error = controller.errorMessage { OMSettingsInfoBox(kind: .warning, message: error, identifier: "pocket-tts-error") }
        if let audio = controller.audio, let metrics = controller.measurement {
            OMSettingsDetailRow(label: AppStrings.localLabAudioReady(seconds: String(format: "%.1f", audio.duration)), value: "24 kHz")
                .accessibilityIdentifier("pocket-tts-audio-ready")
            Button(controller.playing ? AppStrings.localLabPocketStop : AppStrings.localLabPocketPlay) {
                if controller.playing { controller.stopPlayback() } else { controller.play() }
            }.buttonStyle(OMSettingsButtonStyle()).disabled(!enabled || controller.busy)
                .accessibilityIdentifier("pocket-tts-play")
            OMSettingsDetailRow(label: AppStrings.localLabElapsed, value: String(format: "%.2f s", metrics.elapsed))
            OMSettingsDetailRow(label: AppStrings.localLabRtf, value: String(format: "%.3f", metrics.elapsed / audio.duration))
        }
        if let metrics = controller.measurement {
            if let bytes = metrics.baselineBytes { memory(AppStrings.localLabBaselineMemory, bytes) }
            if let bytes = metrics.peakBytes { memory(AppStrings.localLabPeakMemory, bytes) }
            if let bytes = metrics.endBytes { memory(AppStrings.localLabEndMemory, bytes) }
            ForEach(Array(metrics.timings.enumerated()), id: \.offset) { _, timing in
                Text(AppStrings.localLabPhaseDuration(phase: phaseCopy(timing.phase), seconds: String(format: "%.2f", timing.durationSeconds)))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
        }
    }
    private func memory(_ label: String, _ bytes: Int64) -> some View {
        OMSettingsDetailRow(label: label, value: ByteCountFormatter.string(fromByteCount: bytes, countStyle: .memory))
    }
    private func phaseCopy(_ phase: LocalModelRunPhase) -> String {
        switch phase {
        case .submission: AppStrings.localLabPhaseSubmission
        case .tokenizerPreparation: AppStrings.localLabPhaseTokenizer
        case .modelLoading: AppStrings.localLabPhaseModelLoading
        case .transcription, .inference: AppStrings.localLabPocketSynthesis
        case .cleanup: AppStrings.localLabPhaseCleanup
        case .completion: AppStrings.localLabPhaseCompletion
        }
    }
}
