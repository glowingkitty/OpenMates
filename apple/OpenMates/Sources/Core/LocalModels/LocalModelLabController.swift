// Independent, ephemeral local-model test lifecycle. No API, billing or chat integration.

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
                                  architectureSupported: Bool = supportsArchitecture,
                                  osMajorVersion: Int = ProcessInfo.processInfo.operatingSystemVersion.majorVersion) -> String? {
        guard architectureSupported else { return AppStrings.localLabArchitectureUnavailable }
        if id == .kokoro, osMajorVersion >= 27 { return AppStrings.localLabKokoroOsError }
        return nil
    }
}

@MainActor
final class LocalModelLabController: ObservableObject {
    static let shared = LocalModelLabController(store: .shared)
    @Published var speechText = ""
    @Published var privacyText = ""
    @Published private(set) var audioInput: URL?
    @Published private(set) var isRecording = false
    @Published private(set) var runningModel: LocalModelID?
    @Published private(set) var cancelling = false
    @Published private(set) var resultModel: LocalModelID?
    @Published private(set) var resultInput = ""
    @Published private(set) var output: LocalModelTestOutput?
    @Published private(set) var elapsed: TimeInterval?
    @Published private(set) var peakResidentBytes: Int64?
    @Published private(set) var realTimeFactor: Double?
    @Published private(set) var waveform: [Float] = []
    @Published private(set) var errorMessage: String?
    private let store: LocalModelStore
    private var job: Task<Void, Never>?
    private var recorder: AVAudioRecorder?
    private var player: AVAudioPlayer?
    private var temporaryDirectory: URL?
    private var generation = UUID()
    private var activeRuntime: (any LocalModelRuntime)?
    private let runtimeFactory: (LocalModelID) -> any LocalModelRuntime
    private let availability: @MainActor (LocalModelID) -> String?
    private let temporaryRoot: URL

    init(store: LocalModelStore = .shared,
         temporaryRoot: URL = FileManager.default.temporaryDirectory,
         availability: @escaping @MainActor (LocalModelID) -> String? = { LocalModelLabAvailability.unavailableReason(for: $0) },
         runtimeFactory: @escaping (LocalModelID) -> any LocalModelRuntime = { id in
             switch id {
             case .whisper: WhisperKitLocalRuntime()
             case .kokoro: KokoroLocalRuntime()
             case .privacyFilter: LocalPrivacyFilterRuntime()
             }
         }) {
        self.store = store
        self.temporaryRoot = temporaryRoot
        self.availability = availability
        self.runtimeFactory = runtimeFactory
    }

    func unavailableReason(for id: LocalModelID) -> String? { availability(id) }

    var busy: Bool { runningModel != nil || isRecording }
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
        stopPlayback()
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

    func startRecording() async {
        guard !busy else { return }
        let token = generation
        #if os(iOS)
        let permission = await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { continuation.resume(returning: $0) }
        }
        #else
        let permission = await AVCaptureDevice.requestAccess(for: .audio)
        #endif
        guard generation == token, !busy else { return }
        guard permission else { errorMessage = AppStrings.localLabMicrophoneError; return }
        clearResult()
        stopPlayback()
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
        case .kokoro:
            guard !speechText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            request = .speak(speechText)
        case .privacyFilter:
            guard !privacyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            request = .detectPII(privacyText)
        }
        clearResult()
        stopPlayback()
        let token = generation
        runningModel = id
        let runtime = runtimeFactory(id)
        activeRuntime = runtime
        let sourceDuration = id == .whisper ? audioDuration : nil
        let submittedText = id == .privacyFilter ? privacyText : ""
        job = Task {
            do {
                let directory = try store.installedDirectory(id)
                let start = ContinuousClock.now
                let result = try await runtime.run(request, directory: directory)
                try Task.checkCancellation()
                let duration = start.duration(to: .now)
                let seconds = Double(duration.components.seconds) + Double(duration.components.attoseconds) / 1e18
                if token == generation {
                    resultInput = submittedText
                    output = result
                    resultModel = id
                    elapsed = seconds
                    var usage = rusage()
                    if getrusage(RUSAGE_SELF, &usage) == 0 { peakResidentBytes = Int64(usage.ru_maxrss) }
                    let audioSeconds = sourceDuration ?? result.audioDurationSeconds ?? result.audioSamples.flatMap { samples in
                        result.sampleRate.map { Double(samples.count) / Double($0) }
                    }
                    realTimeFactor = audioSeconds.flatMap { $0 > 0 ? seconds / $0 : nil }
                    prepareWaveform(result.audioSamples ?? [])
                }
            } catch LocalSpeechRuntimeError.incompatibleOS {
                if token == generation { errorMessage = AppStrings.localLabKokoroOsError }
            } catch is CancellationError {
                // Cancellation is an expected terminal state, with no retained result.
            } catch {
                if token == generation { errorMessage = AppStrings.localLabRunError }
            }
            await runtime.unload()
            activeRuntime = nil
            runningModel = nil
            cancelling = false
            job = nil
            if token != generation { removeTemporaryFiles() }
        }
    }

    func cancel() {
        guard job != nil else { return }
        cancelling = true
        job?.cancel()
        clearResult()
    }

    /// Await the actual runtime completion and unload; cancellation does not imply idle.
    func waitUntilIdle() async {
        if let job { await job.value }
    }

    func play() {
        guard !busy, let samples = output?.audioSamples, let rate = output?.sampleRate,
              rate > 0, !samples.isEmpty else { return }
        stopPlayback()
        do {
            #if os(iOS)
            try AVAudioSession.sharedInstance().setCategory(.playback)
            try AVAudioSession.sharedInstance().setActive(true)
            #endif
            let url = try tempDirectory().appendingPathComponent("speech.wav")
            let format = AVAudioFormat(standardFormatWithSampleRate: Double(rate), channels: 1)!
            guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count)),
                  let channel = buffer.floatChannelData?[0] else { throw CocoaError(.fileWriteUnknown) }
            buffer.frameLength = AVAudioFrameCount(samples.count)
            for (index, sample) in samples.enumerated() { channel[index] = sample }
            // AVAudioFile finalizes the WAV header when released. Drain the writer
            // before AVAudioPlayer opens the completed output file.
            try autoreleasepool {
                let file = try AVAudioFile(forWriting: url, settings: format.settings)
                try file.write(from: buffer)
            }
            player = try AVAudioPlayer(contentsOf: url)
            guard player?.play() == true else { throw CocoaError(.fileReadUnknown) }
        } catch { errorMessage = AppStrings.localLabAudioError; deactivateAudio() }
    }

    func stopPlayback() { player?.stop(); player = nil; deactivateAudio() }
    func leave() {
        generation = UUID()
        cancel()
        stopRecording()
        stopPlayback()
        speechText = ""
        privacyText = ""
        audioInput = nil
        clearResult()
        if job == nil { removeTemporaryFiles() }
    }
    private func clearResult() {
        resultInput = ""; output = nil; resultModel = nil; elapsed = nil; realTimeFactor = nil
        waveform = []; peakResidentBytes = nil; errorMessage = nil
    }
    private func prepareWaveform(_ samples: [Float]) {
        let stride = max(1, samples.count / 80)
        waveform = Swift.stride(from: 0, to: samples.count, by: stride).map { start in
            samples[start..<min(samples.count, start + stride)].reduce(Float(0)) { max($0, abs($1)) }
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
