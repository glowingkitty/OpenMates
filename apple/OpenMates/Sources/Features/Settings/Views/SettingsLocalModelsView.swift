// Local model diagnostics with optional explicit Privacy scope.
// Developers exposes only experimental audio models; Privacy owns PII assets.
// ─── Web source ─────────────────────────────────────────────────────
// Native-only page, composed from existing canonical settings elements.
// Svelte: frontend/packages/ui/src/components/settings/elements/SettingsInfoBox.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsCard.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsInput.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsTextarea.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsButton.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.apple.enhanced-local-detection, apple-local-model-lab.optional-downloads, apple-local-model-lab.local-execution, apple-local-model-lab.availability, apple-local-model-lab.ephemeral-state
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import UniformTypeIdentifiers

struct SettingsLocalModelsView: View {
    #if DEBUG
    @ObservedObject private var activityCoordinator = LocalModelLiveActivityCoordinator.shared
    #endif
    @EnvironmentObject private var authManager: AuthManager
    @ObservedObject private var offline = OfflineStore.shared
    @ObservedObject private var workspace = TeamWorkspaceContext.shared
    @ObservedObject private var store: LocalModelStore
    @StateObject private var controller: LocalModelLabController
    @AppStorage("lab-use-local-models") private var useLocalModels = false
    @State private var importingAudio = false
    @State private var pageActive = false
    @Environment(\.scenePhase) private var scenePhase
    @State private var observedTransferIDs: Set<LocalModelID> = []
    let modelIDs: [LocalModelID]
    let privacyDiagnosticMode: Bool

    private var ownerIdentity: String {
        "\(authManager.currentUser?.id ?? "guest"):\(ServerProfile.current().id):\(offline.scopeGeneration):\(workspace.contextEpoch)"
    }
    var diagnosticEnabled: Bool { privacyDiagnosticMode || useLocalModels }

    init(store: LocalModelStore = .shared, modelIDs: [LocalModelID]? = nil, privacyDiagnosticMode: Bool = false) {
        self.modelIDs = modelIDs ?? LocalModelID.allCases.filter { $0 != .privacyFilter }
        self.privacyDiagnosticMode = privacyDiagnosticMode
        self.store = store
        _controller = StateObject(wrappedValue: store === LocalModelStore.shared
            ? LocalModelLabController.shared : LocalModelLabController(store: store))
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.localLabTitle, showsHeader: false,
                       scrollAccessibilityIdentifier: "local-model-lab-scroll") {
            OMSettingsInfoBox(
                title: privacyDiagnosticMode ? AppStrings.enhancedPIIModelDiagnosticTitle : AppStrings.localLabTitle,
                message: privacyDiagnosticMode ? AppStrings.enhancedPIIModelDiagnosticDescription : AppStrings.localLabDescription,
                identifier: privacyDiagnosticMode ? "privacy-model-diagnostic-scope" : "local-model-lab-local-only")
            if !privacyDiagnosticMode {
                OMSettingsSection {
                    OMSettingsToggleRow(title: AppStrings.localLabToggle, isOn: $useLocalModels)
                        .accessibilityIdentifier("local-model-lab-toggle")
                    Text(AppStrings.localLabScope)
                        .font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.spacing6)
                        .accessibilityIdentifier("local-model-lab-production-scope")
                }
            }
            if let error = store.catalogError {
                OMSettingsInfoBox(kind: .warning, message: error, identifier: "local-model-lab-catalog-error")
            }
            ForEach(modelIDs) { id in
                modelCard(id)
            }
            if privacyDiagnosticMode {
                // Keep an existing asset transfer cancellable while diagnosing PII.
                ForEach(LocalModelID.allCases.filter { observedTransferIDs.contains($0) }) { id in
                    if isDownloadActive(id) {
                        installControls(id)
                    } else {
                        Text(store.state(for: id) == .ready ? AppStrings.localLabReady : AppStrings.localLabNotDownloaded)
                            .font(.omSmall).accessibilityIdentifier("local-model-\(id.rawValue)-status")
                    }
                }
            }
            if let error = controller.errorMessage {
                OMSettingsInfoBox(kind: .warning, message: error, identifier: "local-model-lab-error")
            }
            OMSettingsInfoBox(message: AppStrings.localLabPrivacyNote, identifier: "local-model-lab-privacy")
            Text(controller.environmentCopy).font(.omSmall).foregroundStyle(Color.fontSecondary)
                .padding(.spacing6).accessibilityIdentifier("local-model-lab-device")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-local-models-page")
        .fileImporter(isPresented: $importingAudio, allowedContentTypes: [.audio]) { result in
            if pageActive, case .success(let url) = result { controller.importAudio(url) }
        }
        .onChange(of: useLocalModels) { _, enabled in if !privacyDiagnosticMode && !enabled { controller.leave() } }
        .task { await store.prepareForLab() }
        .onReceive(store.$states) { states in
            guard privacyDiagnosticMode else { return }
            for id in LocalModelID.allCases where !modelIDs.contains(id) {
                switch states[id] {
                case .downloading, .waitingForConnection, .retrying, .verifying:
                    observedTransferIDs.insert(id)
                default: break
                }
            }
        }
        .onChange(of: ownerIdentity) { _, _ in controller.leave() }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active, controller.runningModel?.isSpeechSynthesis == true || controller.resultModel?.isSpeechSynthesis == true {
                controller.leave()
            }
        }
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
                    if let reason = unavailableReason(id) {
                        OMSettingsInfoBox(kind: .warning, message: reason,
                            identifier: "local-model-\(id.rawValue)-unavailable")
                    }
                    installControls(id)
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--ui-test-local-lab-live-activity") {
                        Text(activityCoordinator.diagnosticReceipt).font(.omSmall)
                            .accessibilityIdentifier("local-model-\(id.rawValue)-live-activity-receipt")
                    }
                    #endif
                    if case .ready = store.state(for: id) {
                        inputControls(id)
                        Button(AppStrings.localLabRun) { controller.run(id, enabled: diagnosticEnabled) }
                            .buttonStyle(OMSettingsButtonStyle())
                            .disabled(!canRun(id))
                            .accessibilityIdentifier("local-model-\(id.rawValue)-run")
                    }
                    if controller.runningModel == id {
                        Text(controller.cancelling ? AppStrings.localLabCancelling : controller.phase.map(phaseCopy) ?? AppStrings.localLabRunning)
                            .font(.omSmall).accessibilityIdentifier("local-model-lab-running")
                        if controller.phaseWarning {
                            OMSettingsInfoBox(kind: .warning, message: AppStrings.localLabPhaseWarning,
                                identifier: "local-model-lab-phase-warning")
                        }
                        Button(AppStrings.cancel) { controller.cancel() }
                            .buttonStyle(OMSettingsButtonStyle(secondary: true))
                            .disabled(controller.cancelling)
                            .accessibilityIdentifier("local-model-lab-cancel-run")
                    }
                    if controller.resultModel == id { resultView(id) }
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("local-model-\(id.rawValue)-card")
    }

    @ViewBuilder private func installControls(_ id: LocalModelID) -> some View {
        switch store.state(for: id) {
        case .notDownloaded:
            Text(AppStrings.localLabNotDownloaded).font(.omSmall)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            downloadButton(id, title: AppStrings.localLabDownload)
        case .downloading(let progress):
            Text(AppStrings.localLabDownloading(percent: percent(progress))).font(.omSmall)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            ProgressView(value: progress).tint(Color.buttonPrimary)
            Button(AppStrings.cancel) { store.cancel(id) }
                .buttonStyle(OMSettingsButtonStyle(secondary: true))
                .accessibilityIdentifier("local-model-\(id.rawValue)-cancel-download")
        case .waitingForConnection(let progress):
            Text(AppStrings.localLabWaitingForConnection(percent: percent(progress))).font(.omSmall)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            ProgressView(value: progress).tint(Color.buttonPrimary)
            Button(AppStrings.cancel) { store.cancel(id) }
                .buttonStyle(OMSettingsButtonStyle(secondary: true))
                .accessibilityIdentifier("local-model-\(id.rawValue)-cancel-download")
        case .retrying(let progress):
            Text(AppStrings.localLabRetrying(percent: percent(progress))).font(.omSmall)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            ProgressView(value: progress).tint(Color.buttonPrimary)
            Button(AppStrings.cancel) { store.cancel(id) }
                .buttonStyle(OMSettingsButtonStyle(secondary: true))
                .accessibilityIdentifier("local-model-\(id.rawValue)-cancel-download")
        case .verifying(let progress):
            Text(AppStrings.localLabVerifyingProgress(percent: percent(progress))).font(.omSmall)
                .accessibilityIdentifier("local-model-\(id.rawValue)-status")
            ProgressView(value: progress).tint(Color.buttonPrimary)
            Button(AppStrings.cancel) { store.cancel(id) }
                .buttonStyle(OMSettingsButtonStyle(secondary: true))
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
            .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(controller.busy || store.manifest(for: id) == nil || unavailableReason(id) != nil)
            .accessibilityIdentifier("local-model-\(id.rawValue)-download")
    }

    @ViewBuilder private func inputControls(_ id: LocalModelID) -> some View {
        switch id {
        case .whisper:
            Button(AppStrings.localLabImportAudio) { importingAudio = true }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(controller.busy || !diagnosticEnabled)
                .accessibilityIdentifier("local-model-lab-import-audio")
            Button(controller.isRecording ? AppStrings.localLabStopRecording : AppStrings.localLabRecord) {
                if controller.isRecording { controller.stopRecording() }
                else { Task { await controller.startRecording() } }
            }
            .buttonStyle(OMSettingsButtonStyle(secondary: true))
            .disabled(controller.runningModel != nil || !diagnosticEnabled)
            .accessibilityIdentifier("local-model-lab-record")
            if let seconds = controller.audioDuration {
                Text(AppStrings.localLabAudioReady(seconds: String(format: "%.1f", seconds)))
                    .font(.omSmall).accessibilityIdentifier("local-model-lab-audio-ready")
            }
        case .supertonic3:
            OMSettingsTextInput(label: AppStrings.localLabSynthesisInput, placeholder: AppStrings.localLabInputPlaceholder,
                value: $controller.synthesisText, identifier: "local-model-\(id.rawValue)-text", multiline: true)
                .disabled(controller.busy || !diagnosticEnabled)
            OMDropdown(title: AppStrings.localLabSynthesisVoice,
                options: LocalTTSSynthesisInput.supertonicVoices.map { OMDropdownOption($0, label: $0) },
                selection: $controller.supertonicVoice, disabled: controller.busy || !diagnosticEnabled)
                .disabled(controller.busy || !diagnosticEnabled).accessibilityIdentifier("local-model-\(id.rawValue)-voice")
            OMDropdown(title: AppStrings.localLabSynthesisLanguage,
                options: LocalTTSSynthesisInput.supertonicLanguages.map { OMDropdownOption($0, label: $0) },
                selection: $controller.synthesisLanguage, disabled: controller.busy || !diagnosticEnabled)
                .disabled(controller.busy || !diagnosticEnabled).accessibilityIdentifier("local-model-supertonic3-language")
            OMDropdown(title: AppStrings.localLabSynthesisSteps,
                options: ["4", "8", "16"].map { OMDropdownOption($0, label: $0) },
                selection: $controller.synthesisSteps, disabled: controller.busy || !diagnosticEnabled)
                .disabled(controller.busy || !diagnosticEnabled).accessibilityIdentifier("local-model-supertonic3-steps")
        case .privacyFilter:
            OMSettingsTextInput(label: AppStrings.localLabPrivacyInput, placeholder: AppStrings.localLabInputPlaceholder,
                value: $controller.privacyText, identifier: "local-model-lab-privacy-input", multiline: true)
                .disabled(controller.busy || !diagnosticEnabled)
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
        if let memory = controller.baselineResidentBytes {
            OMSettingsDetailRow(label: AppStrings.localLabBaselineMemory,
                value: ByteCountFormatter.string(fromByteCount: memory, countStyle: .memory))
        }
        if let memory = controller.endResidentBytes {
            OMSettingsDetailRow(label: AppStrings.localLabEndMemory,
                value: ByteCountFormatter.string(fromByteCount: memory, countStyle: .memory))
        }
        ForEach(Array(controller.phaseTimings.enumerated()), id: \.offset) { _, timing in
            Text(AppStrings.localLabPhaseDuration(phase: phaseCopy(timing.phase), seconds: String(format: "%.2f", timing.durationSeconds)))
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("local-model-lab-phase-timing-\(timing.phase.rawValue)")
        }
        if let rtf = controller.realTimeFactor {
            OMSettingsDetailRow(label: AppStrings.localLabRtf, value: String(format: "%.3f", rtf))
        }
        if let text = controller.output?.text {
            Text(text).font(.omP).textSelection(.enabled).accessibilityIdentifier("local-model-lab-transcript")
        }
        if id.isSpeechSynthesis, controller.output?.audioURL != nil {
            Button(controller.isPlaying ? AppStrings.localLabStopPlayback : AppStrings.localLabPlay) {
                if controller.isPlaying { controller.stopPlayback() } else { controller.playResult() }
            }.buttonStyle(OMSettingsButtonStyle())
                .accessibilityIdentifier("local-model-\(id.rawValue)-play")
            if let seconds = controller.output?.audioDurationSeconds {
                Text(AppStrings.localLabAudioReady(seconds: String(format: "%.2f", seconds)))
                    .font(.omSmall).accessibilityIdentifier("local-model-\(id.rawValue)-audio-duration")
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
        guard unavailableReason(id) == nil else { return false }
        guard diagnosticEnabled, !controller.busy else { return false }
        switch id {
        case .whisper: return controller.audioInput != nil
        case .supertonic3:
            let input = LocalTTSSynthesisInput(text: controller.synthesisText,
                voice: controller.supertonicVoice,
                language: controller.synthesisLanguage,
                steps: Int(controller.synthesisSteps) ?? 0)
            return (try? input.validate(for: id)) != nil
        case .privacyFilter: return !controller.privacyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }
    private func unavailableReason(_ id: LocalModelID) -> String? {
        return controller.unavailableReason(for: id)
    }
    private func isDownloadActive(_ id: LocalModelID) -> Bool {
        switch store.state(for: id) {
        case .downloading, .waitingForConnection, .retrying, .verifying: return true
        default: return false
        }
    }
    private func percent(_ progress: Double) -> Int { Int(max(0, min(1, progress)) * 100) }
    private func phaseCopy(_ phase: LocalModelRunPhase) -> String {
        switch phase {
        case .submission: AppStrings.localLabPhaseSubmission
        case .tokenizerPreparation: AppStrings.localLabPhaseTokenizer
        case .modelLoading: AppStrings.localLabPhaseModelLoading
        case .transcription: AppStrings.localLabPhaseTranscription
        case .inference: AppStrings.localLabPhaseInference
        case .speechSynthesis: AppStrings.localLabPhaseSpeechSynthesis
        case .audioEncoding: AppStrings.localLabPhaseAudioEncoding
        case .cleanup: AppStrings.localLabPhaseCleanup
        case .completion: AppStrings.localLabPhaseCompletion
        }
    }
    private func modelTitle(_ id: LocalModelID) -> String {
        switch id {
        case .whisper: AppStrings.localLabWhisper
        case .privacyFilter: AppStrings.localLabPrivacyFilter
        case .supertonic3: AppStrings.localLabSupertonic
        }
    }
}
