// Watch-only developer experiment using the existing laboratory content contract.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/settings/SettingsDevelopers.svelte
// CSS: frontend/packages/ui/src/styles/buttons.css
// Native difference: foreground microphone experiment on a compact Watch screen;
// no web Whisper testing page or Watch document picker exists.
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.watch-tiny, apple-local-model-lab.isolated-scope, apple-local-model-lab.ephemeral-state
// ────────────────────────────────────────────────────────────────────
import AVFoundation
import CryptoKit
import SwiftUI

@MainActor
enum WatchWhisperCopy {
    static var title: String { WatchLocalization.text("settings.watch_whisper.title") }
    static var experiment: String { WatchLocalization.text("settings.watch_whisper.experiment") }
    static var enable: String { WatchLocalization.text("settings.watch_whisper.enable") }
    static var disable: String { WatchLocalization.text("settings.watch_whisper.disable") }
    static var recordingLimit: String { WatchLocalization.text("settings.watch_whisper.record_limit") }
    static var fixture: String { WatchLocalization.text("settings.watch_whisper.fixture") }
    static var download: String { WatchLocalization.text("settings.local_models.download") }
    static var record: String { WatchLocalization.text("settings.local_models.record") }
    static var stopRecording: String { WatchLocalization.text("settings.local_models.stop_recording") }
    static var run: String { WatchLocalization.text("settings.local_models.run") }
    static var remove: String { WatchLocalization.text("settings.sessions.remove") }
    static var cancelling: String { WatchLocalization.text("settings.local_models.cancelling") }
    static var unavailable: String { WatchLocalization.text("settings.local_models.unavailable") }
    static var audioError: String { WatchLocalization.text("settings.local_models.audio_error") }
    static var microphoneError: String { WatchLocalization.text("settings.local_models.microphone_error") }
    static var runError: String { WatchLocalization.text("settings.local_models.run_error") }
    static var noDownload: String { WatchLocalization.text("settings.local_models.not_downloaded") }
    static var ready: String { WatchLocalization.text("settings.local_models.ready") }
    static var downloadFailed: String { WatchLocalization.text("settings.local_models.download_failed") }
    static var loading: String { WatchLocalization.text("settings.local_models.phase_model_loading") }
    static var transcribing: String { WatchLocalization.text("settings.local_models.phase_transcription") }
    static var unloading: String { WatchLocalization.text("settings.local_models.phase_cleanup") }
    static func progress(_ state: WatchWhisperInstallState) -> String {
        switch state {
        case .absent: noDownload
        case .ready: ready
        case .failed: downloadFailed
        case .transfer(let fraction): WatchLocalization.text("settings.local_models.downloading", replacements: ["percent": String(Int(fraction * 100))])
        case .verifying(let fraction): WatchLocalization.text("settings.local_models.verifying_progress", replacements: ["percent": String(Int(fraction * 100))])
        }
    }
    static func phase(_ phase: WatchWhisperRunPhase?) -> String {
        switch phase {
        case .loading: loading
        case .transcribing: transcribing
        case .unloading: unloading
        case .completed: ready
        case nil: ""
        }
    }
    static func metrics(_ timings: [WatchWhisperPhaseDuration]) -> String {
        func duration(_ phase: WatchWhisperRunPhase) -> String {
            String(format: "%.2f", timings.first(where: { $0.phase == phase })?.seconds ?? 0)
        }
        return WatchLocalization.text("settings.watch_whisper.metrics", replacements: [
            "load": duration(.loading), "transcribe": duration(.transcribing), "unload": duration(.unloading)])
    }
    static func memory(_ controller: WatchWhisperLabController) -> String {
        func bytes(_ value: Int64?) -> String {
            value.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .memory) } ?? unavailable
        }
        return WatchLocalization.text("settings.watch_whisper.memory", replacements: [
            "start": bytes(controller.baselineBytes), "peak": bytes(controller.sampledPeakBytes), "end": bytes(controller.endBytes)])
    }
}

struct WatchWhisperLabView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var controller: WatchWhisperLabController
    @ObservedObject private var store: WatchWhisperAssetStore
    private let onClose: () -> Void
    private let fixture: Bool

    init(onClose: @escaping () -> Void = {}) {
        self.onClose = onClose
        #if DEBUG
        let fixture = ProcessInfo.processInfo.arguments.contains("--watch-whisper-lab-fixture")
            || ProcessInfo.processInfo.arguments.contains("--watch-whisper-use-fixtures")
        let store = fixture ? WatchWhisperLabFixture.makeStore() : WatchWhisperAssetStore()
        let controller = WatchWhisperLabController(store: store, runtimeFactory: {
            if fixture { return WatchWhisperLabFixtureRuntime() }
            return WatchWhisperTinyRuntime()
        })
        #else
        let fixture = false
        let store = WatchWhisperAssetStore()
        let controller = WatchWhisperLabController(store: store, runtimeFactory: { WatchWhisperTinyRuntime() })
        #endif
        self.fixture = fixture
        _store = ObservedObject(wrappedValue: store)
        _controller = StateObject(wrappedValue: controller)
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button { controller.leave(); onClose() } label: {
                    HStack(spacing: .spacing1) { Icon("chevron-left", size: .spacing4); Text(WatchStrings.back).font(.omXs) }
                        .padding(.vertical, .spacing3)
                }
                .buttonStyle(.plain).accessibilityIdentifier("watch-whisper-back")
                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing3)
            WatchCrownScrollView(active: true, identity: "watch-whisper-lab") {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(WatchWhisperCopy.title).font(.omSmall.weight(.semibold)).accessibilityIdentifier("watch-whisper-title")
                    Text(WatchWhisperCopy.experiment).font(.omMicro).foregroundStyle(Color.fontSecondary)
                    control(controller.enabled ? WatchWhisperCopy.disable : WatchWhisperCopy.enable, id: "watch-whisper-enable") {
                        if controller.enabled { controller.disable() } else { controller.enabled = true }
                    }
                    Text(WatchWhisperCopy.progress(store.state)).font(.omXs).accessibilityIdentifier("watch-whisper-install-state")
                    if let manifest = store.manifest {
                        Text(manifest.model + " · " + ByteCountFormatter.string(fromByteCount: manifest.estimatedSizeBytes, countStyle: .file))
                            .font(.omMicro).foregroundStyle(Color.fontSecondary)
                    }
                    if store.active {
                        if case .transfer(let value) = store.state { ProgressView(value: value) }
                        if case .verifying(let value) = store.state { ProgressView(value: value) }
                        control(WatchStrings.cancel, id: "watch-whisper-cancel-download") { store.cancel() }
                    } else if store.state == .ready {
                        control(WatchWhisperCopy.remove, id: "watch-whisper-remove", disabled: controller.busy) {
                            Task { await controller.removeModel() }
                        }
                    } else {
                        control(WatchWhisperCopy.download, id: "watch-whisper-download", disabled: !controller.enabled || controller.busy) {
                            store.download(enabled: controller.enabled)
                        }
                    }
                    Text(WatchWhisperCopy.recordingLimit).font(.omMicro).foregroundStyle(Color.fontSecondary)
                    control(controller.recording ? WatchWhisperCopy.stopRecording : WatchWhisperCopy.record,
                            id: "watch-whisper-record", disabled: !controller.enabled || controller.running || controller.requestingMicrophone) {
                        if controller.recording { controller.stopRecording() } else { Task { await controller.startRecording() } }
                    }
                    #if DEBUG
                    if fixture {
                        control(WatchWhisperCopy.fixture, id: "watch-whisper-import-fixture", disabled: !controller.enabled || controller.busy) {
                            if let url = try? WatchWhisperLabFixture.audio() { controller.importAudio(url); try? FileManager.default.removeItem(at: url) }
                        }
                    }
                    #endif
                    if let seconds = controller.audioSeconds {
                        Text(String(format: "%.2f s", seconds)).font(.omMicro).accessibilityIdentifier("watch-whisper-audio-duration")
                    }
                    if controller.running {
                        Text(WatchWhisperCopy.phase(controller.phase)).font(.omXs).accessibilityIdentifier("watch-whisper-run-phase")
                        control(controller.cancelling ? WatchWhisperCopy.cancelling : WatchStrings.cancel,
                                id: "watch-whisper-cancel-run", disabled: controller.cancelling) { controller.cancel() }
                    } else {
                        control(WatchWhisperCopy.run, id: "watch-whisper-run",
                                disabled: !controller.enabled || controller.busy || store.active || store.state != .ready || controller.audioSeconds == nil) { controller.run() }
                    }
                    if let transcript = controller.transcript {
                        Text(transcript).font(.omXs).accessibilityIdentifier("watch-whisper-transcript")
                    }
                    if !controller.timings.isEmpty {
                        Text(WatchWhisperCopy.metrics(controller.timings)).font(.omMicro).accessibilityIdentifier("watch-whisper-timings")
                        Text(WatchWhisperCopy.memory(controller)).font(.omMicro).accessibilityIdentifier("watch-whisper-memory")
                    }
                    if let error = controller.error {
                        Text(errorCopy(error)).font(.omMicro).foregroundStyle(Color.error).accessibilityIdentifier("watch-whisper-error")
                    }
                }
                .padding(.horizontal, .spacing3).padding(.bottom, .spacing4)
            }.accessibilityIdentifier("watch-whisper-scroll")
        }
        .foregroundStyle(Color.fontPrimary).background(Color.grey0)
        .task { await store.restore() }
        .onDisappear { controller.leave(); store.cancel() }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { controller.leave(); store.cancel() }
        }
    }
    private func errorCopy(_ error: WatchWhisperLabError) -> String {
        switch error {
        case .assets, .transfer: WatchWhisperCopy.downloadFailed
        case .microphone: WatchWhisperCopy.microphoneError
        case .audio: WatchWhisperCopy.audioError
        case .inference: WatchWhisperCopy.runError
        }
    }
    private func control(_ title: String, id: String, disabled: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.omXs.weight(.semibold)).frame(maxWidth: .infinity)
                .padding(.vertical, .spacing2).background(Color.grey20)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
        }
        .buttonStyle(.plain).disabled(disabled).opacity(disabled ? 0.6 : 1).accessibilityIdentifier(id)
    }
}

#if DEBUG
@MainActor
private enum WatchWhisperLabFixture {
    static func makeStore() -> WatchWhisperAssetStore {
        let data = Data("watch-tiny-disposable-test".utf8), revision = String(repeating: "a", count: 40)
        let file = WatchWhisperAsset(path: "fixture.bin",
            url: URL(string: "https://huggingface.co/argmaxinc/whisperkit-coreml/resolve/\(revision)/openai_whisper-tiny/fixture.bin")!,
            sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(), sizeBytes: Int64(data.count))
        let manifest = WatchWhisperManifest(model: "openai_whisper-tiny", revision: revision,
            tokenizerRevision: revision, estimatedSizeBytes: Int64(data.count), files: [file])
        return WatchWhisperAssetStore(manifest: manifest,
            root: FileManager.default.temporaryDirectory.appendingPathComponent("watch-tiny-fixture-" + UUID().uuidString), transfer: { file, destination, progress in
                for step in 1...4 { try await Task.sleep(for: .milliseconds(400)); progress(file.sizeBytes * Int64(step) / 4) }
                try data.write(to: destination)
            })
    }
    static func audio() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathExtension("wav")
        let format = AVAudioFormat(standardFormatWithSampleRate: 16_000, channels: 1)!
        let file = try AVAudioFile(forWriting: url, settings: format.settings)
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 16_000)!
        buffer.frameLength = 16_000
        if let samples = buffer.floatChannelData { for index in 0..<16_000 { samples[0][index] = 0 } }
        try file.write(from: buffer)
        return url
    }
}
private actor WatchWhisperLabFixtureRuntime: WatchWhisperRuntime {
    func transcribe(_ audio: URL, directory: URL,
                    phase: @escaping @Sendable (WatchWhisperRunPhase) async -> Void) async throws -> WatchWhisperResult {
        await phase(.loading); try await Task.sleep(for: .seconds(1))
        await phase(.transcribing); try await Task.sleep(for: .seconds(2))
        return .init(text: "Disposable English and German fixture result.", audioSeconds: 1)
    }
    func unload() async { await Task.detached { try? await Task.sleep(for: .seconds(2)) }.value }
}
#endif
