// Native-only experimental local model page; production providers are unchanged.
// ─── Web source ─────────────────────────────────────────────────────
// Native-only page, composed from existing canonical settings elements.
// Svelte: frontend/packages/ui/src/components/settings/elements/SettingsInfoBox.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsCard.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsInput.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsTextarea.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsButton.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import UniformTypeIdentifiers

struct SettingsLocalModelsView: View {
    @ObservedObject private var store: LocalModelStore
    @StateObject private var controller: LocalModelLabController
    @AppStorage("lab-use-local-models") private var useLocalModels = false
    @State private var importingAudio = false
    @State private var pageActive = false

    init(store: LocalModelStore = .shared) {
        self.store = store
        _controller = StateObject(wrappedValue: store === LocalModelStore.shared
            ? LocalModelLabController.shared : LocalModelLabController(store: store))
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.localLabTitle, showsHeader: false,
                       scrollAccessibilityIdentifier: "local-model-lab-scroll") {
            OMSettingsInfoBox(title: AppStrings.localLabTitle, message: AppStrings.localLabDescription, identifier: "local-model-lab-local-only")
            OMSettingsSection {
                OMSettingsToggleRow(title: AppStrings.localLabToggle, isOn: $useLocalModels)
                    .accessibilityIdentifier("local-model-lab-toggle")
                Text(AppStrings.localLabScope)
                    .font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.spacing6)
                    .accessibilityIdentifier("local-model-lab-production-scope")
            }
            if let error = store.catalogError {
                OMSettingsInfoBox(kind: .warning, message: error, identifier: "local-model-lab-catalog-error")
            }
            ForEach(LocalModelID.allCases) { id in
                modelCard(id)
            }
            if let error = controller.errorMessage {
                OMSettingsInfoBox(kind: .warning, message: error, identifier: "local-model-lab-error")
            }
            OMSettingsInfoBox(message: AppStrings.localLabPrivacyNote, identifier: "local-model-lab-privacy")
            Text(controller.environmentCopy).font(.omSmall).foregroundStyle(Color.fontSecondary)
                .padding(.spacing6).accessibilityIdentifier("local-model-lab-device")
        }
        .accessibilityIdentifier("settings-local-models-page")
        .fileImporter(isPresented: $importingAudio, allowedContentTypes: [.audio]) { result in
            if pageActive, case .success(let url) = result { controller.importAudio(url) }
        }
        .onChange(of: useLocalModels) { _, enabled in if !enabled { controller.leave() } }
        .onAppear { pageActive = true }
        .onDisappear { pageActive = false; controller.leave() }
    }

    @ViewBuilder private func modelCard(_ id: LocalModelID) -> some View {
        OMSettingsSection(modelTitle(id)) {
            OMSettingsCard {
                VStack(alignment: .leading, spacing: .spacing6) {
                    if let manifest = store.manifest(for: id) {
                        OMSettingsDetailRow(label: AppStrings.localLabInstalledSize,
                            value: ByteCountFormatter.string(fromByteCount: manifest.estimatedSizeBytes, countStyle: .file))
                        OMSettingsDetailRow(label: AppStrings.localLabRevision, value: manifest.revision)
                    }
                    if let reason = controller.unavailableReason(for: id) {
                        OMSettingsInfoBox(kind: .warning, message: reason,
                            identifier: "local-model-\(id.rawValue)-unavailable")
                    }
                    installControls(id)
                    if id == .kokoro {
                        OMSettingsInfoBox(kind: .warning, message: AppStrings.localLabKokoroInputLimits,
                            identifier: "local-model-lab-kokoro-input-limits")
                    }
                    if case .ready = store.state(for: id) {
                        inputControls(id)
                        Button(AppStrings.localLabRun) { controller.run(id, enabled: useLocalModels) }
                            .buttonStyle(OMSettingsButtonStyle())
                            .disabled(!canRun(id))
                            .accessibilityIdentifier("local-model-\(id.rawValue)-run")
                    }
                    if controller.runningModel == id {
                        Text(controller.cancelling ? AppStrings.localLabCancelling : AppStrings.localLabRunning)
                            .font(.omSmall).accessibilityIdentifier("local-model-lab-running")
                        Button(AppStrings.cancel) { controller.cancel() }
                            .buttonStyle(OMSettingsButtonStyle(secondary: true))
                            .disabled(controller.cancelling)
                            .accessibilityIdentifier("local-model-lab-cancel-run")
                    }
                    if controller.resultModel == id { resultView(id) }
                }
            }
        }
        .accessibilityIdentifier("local-model-\(id.rawValue)-card")
    }

    @ViewBuilder private func installControls(_ id: LocalModelID) -> some View {
        switch store.state(for: id) {
        case .notDownloaded:
            Text(AppStrings.localLabNotDownloaded).font(.omSmall)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            downloadButton(id, title: AppStrings.localLabDownload)
        case .downloading(let progress):
            Text(progress >= 1 ? AppStrings.localLabVerifying : AppStrings.localLabDownloading(percent: Int(max(0, min(1, progress)) * 100))).font(.omSmall)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            ProgressView(value: progress).tint(Color.buttonPrimary)
            Button(AppStrings.cancel) { store.cancel(id) }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(controller.busy)
                .accessibilityIdentifier("local-model-\(id.rawValue)-cancel-download")
        case .ready:
            Text(AppStrings.localLabReady).font(.omSmall).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            Button(AppStrings.remove) { Task { await store.remove(id) } }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(controller.busy)
                .accessibilityIdentifier("local-model-\(id.rawValue)-remove")
        case .failed(let message):
            Text(message).font(.omSmall).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            downloadButton(id, title: AppStrings.retry)
        }
    }
    private func downloadButton(_ id: LocalModelID, title: String) -> some View {
        Button(title) { Task { await store.download(id) } }
            .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(controller.busy || store.manifest(for: id) == nil || controller.unavailableReason(for: id) != nil)
            .accessibilityIdentifier("local-model-\(id.rawValue)-download")
    }

    @ViewBuilder private func inputControls(_ id: LocalModelID) -> some View {
        switch id {
        case .whisper:
            Button(AppStrings.localLabImportAudio) { importingAudio = true }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(controller.busy || !useLocalModels)
                .accessibilityIdentifier("local-model-lab-import-audio")
            Button(controller.isRecording ? AppStrings.localLabStopRecording : AppStrings.localLabRecord) {
                if controller.isRecording { controller.stopRecording() }
                else { Task { await controller.startRecording() } }
            }
            .buttonStyle(OMSettingsButtonStyle(secondary: true))
            .disabled(controller.runningModel != nil || !useLocalModels)
            .accessibilityIdentifier("local-model-lab-record")
            if let seconds = controller.audioDuration {
                Text(AppStrings.localLabAudioReady(seconds: String(format: "%.1f", seconds)))
                    .font(.omSmall).accessibilityIdentifier("local-model-lab-audio-ready")
            }
        case .kokoro:
            OMSettingsTextInput(label: AppStrings.localLabSpeechInput, placeholder: AppStrings.localLabInputPlaceholder,
                value: $controller.speechText, identifier: "local-model-lab-speech-input", multiline: true)
                .disabled(controller.busy || !useLocalModels)
        case .privacyFilter:
            OMSettingsTextInput(label: AppStrings.localLabPrivacyInput, placeholder: AppStrings.localLabInputPlaceholder,
                value: $controller.privacyText, identifier: "local-model-lab-privacy-input", multiline: true)
                .disabled(controller.busy || !useLocalModels)
        }
    }

    @ViewBuilder private func resultView(_ id: LocalModelID) -> some View {
        Text(AppStrings.localLabResult).font(.omP.weight(.semibold))
        if let elapsed = controller.elapsed {
            OMSettingsDetailRow(label: AppStrings.localLabElapsed, value: String(format: "%.2f s", elapsed))
        }
        if let memory = controller.peakResidentBytes {
            OMSettingsDetailRow(label: AppStrings.localLabPeakMemory,
                value: ByteCountFormatter.string(fromByteCount: memory, countStyle: .memory))
        }
        if let rtf = controller.realTimeFactor {
            OMSettingsDetailRow(label: AppStrings.localLabRtf, value: String(format: "%.3f", rtf))
        }
        if let text = controller.output?.text {
            Text(text).font(.omP).textSelection(.enabled).accessibilityIdentifier("local-model-lab-transcript")
        }
        if id == .kokoro, !controller.waveform.isEmpty {
            waveform
            HStack(spacing: .spacing6) {
                Button(AppStrings.localLabPlay) { controller.play() }
                    .buttonStyle(OMSettingsButtonStyle()).accessibilityIdentifier("local-model-lab-play")
                Button(AppStrings.localLabStopPlayback) { controller.stopPlayback() }
                    .buttonStyle(OMSettingsButtonStyle(secondary: true)).accessibilityIdentifier("local-model-lab-stop-playback")
            }
        }
        if id == .privacyFilter {
            Text(highlightedPrivacyText).font(.omP).textSelection(.enabled)
                .accessibilityIdentifier("local-model-lab-pii-highlighted-text")
            if let spans = controller.output?.piiSpans, !spans.isEmpty {
                ForEach(Array(spans.enumerated()), id: \.offset) { _, span in
                    Text(AppStrings.localLabEntity(label: span.label.rawValue, start: span.range.location,
                        end: NSMaxRange(span.range), score: String(format: "%.2f", span.score)))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
            } else { Text(AppStrings.localLabNoEntities).font(.omSmall) }
        }
    }
    private var waveform: some View {
        Canvas { context, size in
            let samples = controller.waveform
            let step = size.width / CGFloat(max(1, samples.count))
            for (index, sample) in samples.enumerated() {
                let height = max(1, CGFloat(min(1, sample)) * size.height)
                context.fill(Path(CGRect(x: CGFloat(index) * step, y: (size.height - height) / 2,
                    width: max(1, step / 2), height: height)), with: .color(.buttonPrimary))
            }
        }
        .frame(height: .spacing16)
        .accessibilityLabel(AppStrings.localLabWaveform).accessibilityIdentifier("local-model-lab-waveform")
    }
    private var highlightedPrivacyText: AttributedString {
        var text = AttributedString(controller.resultInput)
        for span in controller.output?.piiSpans ?? [] {
            guard let sourceRange = Range(span.range, in: controller.resultInput),
                  let range = Range(sourceRange, in: text) else { continue }
            text[range].backgroundColor = Color.grey25
            text[range].foregroundColor = Color.buttonPrimary
        }
        return text
    }
    private func canRun(_ id: LocalModelID) -> Bool {
        guard controller.unavailableReason(for: id) == nil else { return false }
        guard useLocalModels, !controller.busy else { return false }
        switch id {
        case .whisper: return controller.audioInput != nil
        case .kokoro: return !controller.speechText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .privacyFilter: return !controller.privacyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }
    private func modelTitle(_ id: LocalModelID) -> String {
        switch id {
        case .whisper: AppStrings.localLabWhisper
        case .kokoro: AppStrings.localLabKokoro
        case .privacyFilter: AppStrings.localLabPrivacyFilter
        }
    }
}
