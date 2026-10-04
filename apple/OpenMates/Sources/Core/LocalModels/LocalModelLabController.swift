// Independent, ephemeral local-model test lifecycle. No API, billing or chat integration.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.local-execution, apple-local-model-lab.serialized-cancellation, apple-local-model-lab.ephemeral-state, apple-local-model-lab.availability

import AVFoundation
import Combine
import Foundation
import Darwin

/// Capability checks precede downloads and inference; no alternate provider is selected.
enum LocalModelLabAvailability {
    static var supportsArchitecture: Bool {
        #if arch(arm64) && !os(watchOS)
        true
        #else
        false
        #endif
    }

    @MainActor
    static func unavailableReason(for id: LocalModelID,
                                  architectureSupported: Bool = supportsArchitecture) -> String? {
        guard architectureSupported else { return AppStrings.localLabArchitectureUnavailable }
        return nil
    }
}

@MainActor
final class LocalModelLabController: ObservableObject {
    static let shared: LocalModelLabController = {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-local-lab-progress-fixture") {
            return LocalModelLabController(store: .shared, availability: { _ in nil },
                                           runtimeFactory: { _ in LocalModelProgressFixtureRuntime() })
        }
        #endif
        return LocalModelLabController(store: .shared)
    }()
    @Published var privacyText = ""
    @Published private(set) var audioInput: URL?
    @Published private(set) var isRecording = false
    @Published private(set) var isRequestingMicrophone = false
    @Published private(set) var runningModel: LocalModelID?
    @Published private(set) var cancelling = false
    @Published private(set) var resultModel: LocalModelID?
    @Published private(set) var resultInput = ""
    @Published private(set) var output: LocalModelTestOutput?
    @Published private(set) var elapsed: TimeInterval?
    @Published private(set) var peakResidentBytes: Int64?
    @Published private(set) var baselineResidentBytes: Int64?
    @Published private(set) var endResidentBytes: Int64?
    @Published private(set) var phase: LocalModelRunPhase?
    @Published private(set) var phaseTimings: [LocalModelPhaseTiming] = []
    @Published private(set) var phaseWarning = false
    @Published private(set) var realTimeFactor: Double?
    @Published private(set) var errorMessage: String?
    private let microphonePermission: @MainActor () async -> Bool
    private let store: LocalModelStore
    private var job: Task<Void, Never>?
    private var recorder: AVAudioRecorder?
    private var temporaryDirectory: URL?
    private var generation = UUID()
    private var activeRuntime: (any LocalModelRuntime)?
    private let runtimeFactory: (LocalModelID) -> (any LocalModelRuntime)?
    private let availability: @MainActor (LocalModelID) -> String?
    private let temporaryRoot: URL
    private let monotonicNow: @Sendable () -> Double
    private let memorySample: @Sendable () -> Int64?
    private var lastMeasurementElapsed = -Double.infinity
    private let warningAfter: Double

    init(store: LocalModelStore = .shared,
         temporaryRoot: URL = FileManager.default.temporaryDirectory,
         microphonePermission: @escaping @MainActor () async -> Bool = { await LocalModelLabController.requestMicrophonePermission() },
         monotonicNow: @escaping @Sendable () -> Double = { ProcessInfo.processInfo.systemUptime },
         memorySample: @escaping @Sendable () -> Int64? = { LocalModelRunMeasurement.residentBytes() },
         warningAfter: Double = 30,
         availability: @escaping @MainActor (LocalModelID) -> String? = { LocalModelLabAvailability.unavailableReason(for: $0) },
         runtimeFactory: @escaping (LocalModelID) -> (any LocalModelRuntime)? = { id in
             switch id {
             case .whisper: WhisperKitLocalRuntime()
             case .privacyFilter: LocalPrivacyFilterRuntime()
             case .pocketTTS: nil // Dedicated Pocket controller owns audio synthesis.
             }
         }) {
        self.microphonePermission = microphonePermission
        self.monotonicNow = monotonicNow
        self.memorySample = memorySample
        self.warningAfter = warningAfter
        self.store = store
        self.temporaryRoot = temporaryRoot
        self.availability = availability
        self.runtimeFactory = runtimeFactory
    }

    func unavailableReason(for id: LocalModelID) -> String? { availability(id) }

    var busy: Bool { runningModel != nil || isRecording || isRequestingMicrophone }
    var audioDuration: Double? {
        guard let audioInput, let file = try? AVAudioFile(forReading: audioInput),
              file.processingFormat.sampleRate > 0 else { return nil }
        return Double(file.length) / file.processingFormat.sampleRate
    }
    var environmentCopy: String {
        let info = ProcessInfo.processInfo
        return deviceDescription + " · " + info.operatingSystemVersionString + " · " + AppStrings.localLabEnvironment(cores: info.processorCount,
            memory: ByteCountFormatter.string(fromByteCount: Int64(info.physicalMemory), countStyle: .memory),
            thermal: thermalCopy(info.thermalState))
    }
    private var deviceDescription: String {
        var length = 0
        #if os(macOS)
        let key = "hw.model"
        #else
        let key = "hw.machine"
        #endif
        guard sysctlbyname(key, nil, &length, nil, 0) == 0, length > 0 else { return AppStrings.localLabUnavailable }
        var buffer = [CChar](repeating: 0, count: length)
        guard sysctlbyname(key, &buffer, &length, nil, 0) == 0 else { return AppStrings.localLabUnavailable }
        return String(cString: buffer)
    }
    private func thermalCopy(_ state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: AppStrings.localLabThermalNominal
        case .fair: AppStrings.localLabThermalFair
        case .serious: AppStrings.localLabThermalSerious
        case .critical: AppStrings.localLabThermalCritical
        @unknown default: AppStrings.localLabUnavailable
        }
    }

    func importAudio(_ source: URL) {
        guard !busy else { return }
        clearResult()
        let scoped = source.startAccessingSecurityScopedResource()
        defer { if scoped { source.stopAccessingSecurityScopedResource() } }
        var importedCopy: URL?
        do {
            let destination = try tempDirectory().appendingPathComponent(UUID().uuidString)
                .appendingPathExtension(source.pathExtension)
            importedCopy = destination
            try FileManager.default.copyItem(at: source, to: destination)
            let file = try AVAudioFile(forReading: destination)
            guard file.length > 0 else { throw CocoaError(.fileReadCorruptFile) }
            if let audioInput { try? FileManager.default.removeItem(at: audioInput) }
            audioInput = destination
        } catch {
            if let importedCopy { try? FileManager.default.removeItem(at: importedCopy) }
            errorMessage = AppStrings.localLabAudioError
        }
    }

    private static func requestMicrophonePermission() async -> Bool {
        #if os(iOS)
        return await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { continuation.resume(returning: $0) }
        }
        #else
        return await AVCaptureDevice.requestAccess(for: .audio)
        #endif
    }

    func startRecording() async {
        guard !busy else { return }
        generation = UUID()
        let token = generation
        isRequestingMicrophone = true
        clearResult()
        let permission = await microphonePermission()
        guard generation == token, isRequestingMicrophone else { return }
        isRequestingMicrophone = false
        guard permission else { errorMessage = AppStrings.localLabMicrophoneError; return }
        clearResult()
        do {
            #if os(iOS)
            try AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try AVAudioSession.sharedInstance().setActive(true)
            #endif
            let url = try tempDirectory().appendingPathComponent(UUID().uuidString).appendingPathExtension("wav")
            let recording = try AVAudioRecorder(url: url, settings: [
                AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
            guard recording.record() else { throw CocoaError(.fileWriteUnknown) }
            if let audioInput { try? FileManager.default.removeItem(at: audioInput) }
            audioInput = url
            recorder = recording
            isRecording = true
        } catch { errorMessage = AppStrings.localLabAudioError; deactivateAudio() }
    }

    func stopRecording() {
        if isRequestingMicrophone { generation = UUID() }
        isRequestingMicrophone = false
        recorder?.stop()
        recorder = nil
        isRecording = false
        deactivateAudio()
    }

    func run(_ id: LocalModelID, enabled: Bool) {
        guard enabled, !busy else { return }
        if let reason = unavailableReason(for: id) { errorMessage = reason; return }
        let request: LocalModelTestRequest
        switch id {
        case .whisper:
            guard let audioInput else { return }
            request = .transcribe(audioInput)
        case .privacyFilter:
            guard !privacyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            request = .detectPII(privacyText)
        case .pocketTTS: return
        }
        guard let runtime = runtimeFactory(id) else { return }
        clearResult()
        generation = UUID()
        let token = generation
        runningModel = id
        activeRuntime = runtime
        let sourceDuration = id == .whisper ? audioDuration : nil
        let submittedText = id == .privacyFilter ? privacyText : ""
        let measurement = LocalModelRunMeasurement(now: monotonicNow, memory: memorySample, warningAfter: warningAfter)
        applyMeasurement(measurement.snapshot())
        let progressController = self
        job = Task {
            let sampler = Task.detached(priority: .utility) {
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .milliseconds(250)) } catch { break }
                    measurement.sample()
                    let snapshot = measurement.snapshot()
                    await MainActor.run { [weak progressController] in
                        guard let controller = progressController, controller.generation == token,
                              controller.runningModel == id else { return }
                        controller.applyMeasurement(snapshot)
                    }
                }
            }
            var result: LocalModelTestOutput?
            do {
                let directory = try store.installedDirectory(id)
                result = try await runtime.run(request, directory: directory) { nextPhase in
                    measurement.transition(nextPhase)
                    Task { @MainActor [weak progressController] in
                        guard let controller = progressController, controller.generation == token,
                              controller.runningModel == id else { return }
                        controller.applyMeasurement(measurement.snapshot())
                    }
                }
                try Task.checkCancellation()
            } catch is CancellationError {
                // Cancellation is an expected terminal state, with no retained result.
                result = nil
            } catch {
                if token == generation { errorMessage = AppStrings.localLabRunError }
                result = nil
            }
            measurement.transition(.cleanup)
            if token == generation { applyMeasurement(measurement.snapshot()) }
            await runtime.unload()
            // Keep ownership and sampling until even a non-cooperative native kernel drains.
            sampler.cancel()
            await sampler.value
            measurement.sample()
            measurement.transition(.completion)
            let final = measurement.snapshot()
            if token == generation && !Task.isCancelled {
                applyMeasurement(final)
                if let result {
                    resultInput = submittedText
                    output = result
                    resultModel = id
                    elapsed = final.elapsed
                    let audioSeconds = sourceDuration ?? result.audioDurationSeconds
                    realTimeFactor = audioSeconds.flatMap { $0 > 0 ? final.elapsed / $0 : nil }
                }
            }
            NativeDiagnostics.event("offline_model_run", category: "local_models", flags: ["cancelled": Task.isCancelled],
                counts: ["duration_ms": Int(final.elapsed * 1000), "baseline_bytes": Int(final.baselineBytes ?? 0),
                         "peak_bytes": Int(final.peakBytes ?? 0), "end_bytes": Int(final.endBytes ?? 0)])
            activeRuntime = nil
            runningModel = nil
            cancelling = false
            job = nil
            if token != generation { removeTemporaryFiles() }
            else if Task.isCancelled { clearResult() }
        }
    }

    private func applyMeasurement(_ snapshot: LocalModelRunMeasurement.Snapshot) {
        // Sample and callback tasks can arrive in either order; phase never regresses.
        if let phase, snapshot.phase.rawValue < phase.rawValue { return }
        guard snapshot.elapsed >= lastMeasurementElapsed else { return }
        lastMeasurementElapsed = snapshot.elapsed
        phase = snapshot.phase
        phaseTimings = snapshot.timings
        phaseWarning = snapshot.warning
        baselineResidentBytes = snapshot.baselineBytes
        peakResidentBytes = snapshot.peakBytes
        endResidentBytes = snapshot.endBytes
    }

    func cancel() {
        guard job != nil else { return }
        cancelling = true
        job?.cancel()
        clearResult(keepProgress: true)
    }

    /// Await the actual runtime completion and unload; cancellation does not imply idle.
    func waitUntilIdle() async {
        if let job { await job.value }
    }

    func leave() {
        generation = UUID()
        cancel()
        stopRecording()
        privacyText = ""
        audioInput = nil
        clearResult()
        if job == nil { removeTemporaryFiles() }
    }
    private func clearResult(keepProgress: Bool = false) {
        resultInput = ""; output = nil; resultModel = nil; elapsed = nil; realTimeFactor = nil
        errorMessage = nil
        if !keepProgress {
            peakResidentBytes = nil; baselineResidentBytes = nil; endResidentBytes = nil
            phase = nil; phaseTimings = []; phaseWarning = false
            lastMeasurementElapsed = -Double.infinity
        }
    }
    private func tempDirectory() throws -> URL {
        if let temporaryDirectory { return temporaryDirectory }
        let url = temporaryRoot.appendingPathComponent("local-model-lab-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        temporaryDirectory = url
        return url
    }
    private func removeTemporaryFiles() {
        if let temporaryDirectory { try? FileManager.default.removeItem(at: temporaryDirectory) }
        temporaryDirectory = nil
    }
    private func deactivateAudio() {
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
        #endif
    }
}

#if DEBUG
private actor LocalModelProgressFixtureRuntime: LocalModelRuntime {
    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
        try await run(request, directory: directory, progress: { _ in })
    }
    func run(_ request: LocalModelTestRequest, directory: URL,
             progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> LocalModelTestOutput {
        progress(.tokenizerPreparation)
        try await Task.sleep(for: .milliseconds(300))
        progress(.modelLoading)
        // XCTest's cross-process snapshots can take several seconds. Keep the
        // real fixture phase observable before advancing to held inference.
        try await Task.sleep(for: .seconds(8))
        progress(.inference)
        while true { try await Task.sleep(for: .seconds(1)) }
    }
    func unload() async {
        // Cancellation retains ownership until this simulated native drain
        // ends; detached cleanup deliberately does not inherit cancellation.
        await Task.detached { try? await Task.sleep(for: .seconds(8)) }.value
    }
}

#endif
