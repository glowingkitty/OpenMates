// An isolated, foreground Watch experiment. No chat, billing or server integration.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.watch-tiny, apple-local-model-lab.serialized-cancellation, apple-local-model-lab.ephemeral-state
import AVFoundation
import Combine
import Darwin
import Foundation

enum WatchWhisperRunPhase: Int, Sendable { case loading, transcribing, unloading, completed }
struct WatchWhisperPhaseDuration: Equatable, Sendable { let phase: WatchWhisperRunPhase; let seconds: Double }
struct WatchWhisperResult: Sendable { let text: String; let audioSeconds: Double }
protocol WatchWhisperRuntime: Sendable {
    func transcribe(_ audio: URL, directory: URL,
                    phase: @escaping @Sendable (WatchWhisperRunPhase) async -> Void) async throws -> WatchWhisperResult
    func unload() async
}

@MainActor
final class WatchWhisperLabController: ObservableObject {
    @Published var enabled = false
    @Published private(set) var audioInput: URL?
    @Published private(set) var audioSeconds: Double?
    @Published private(set) var recording = false
    @Published private(set) var requestingMicrophone = false
    @Published private(set) var running = false
    @Published private(set) var cancelling = false
    @Published private(set) var phase: WatchWhisperRunPhase?
    @Published private(set) var timings: [WatchWhisperPhaseDuration] = []
    @Published private(set) var elapsed: Double?
    @Published private(set) var sampledPeakBytes: Int64?
    @Published private(set) var baselineBytes: Int64?
    @Published private(set) var endBytes: Int64?
    @Published private(set) var transcript: String?
    @Published private(set) var error: WatchWhisperLabError?
    let store: WatchWhisperAssetStore
    private let factory: @Sendable () -> any WatchWhisperRuntime
    private let memory: @Sendable () -> Int64?
    private let temporaryRoot: URL
    private var privateDirectory: URL?
    private var recorder: AVAudioRecorder?
    private var job: Task<Void, Never>?
    private var generation = UUID()
    private var phaseStarted: Double = 0
    private var recordingLimit: Task<Void, Never>?
    var busy: Bool { running || recording || requestingMicrophone }

    init(store: WatchWhisperAssetStore, temporaryRoot: URL = FileManager.default.temporaryDirectory,
         memory: @escaping @Sendable () -> Int64? = { WatchWhisperLabController.residentBytes() },
         runtimeFactory: @escaping @Sendable () -> any WatchWhisperRuntime) {
        self.store = store; self.factory = runtimeFactory; self.temporaryRoot = temporaryRoot; self.memory = memory
    }
    func importAudio(_ original: URL) {
        guard enabled, !busy else { return }
        clearResult()
        var copy: URL?
        do {
            let destination = try temporaryDirectory().appendingPathComponent(UUID().uuidString).appendingPathExtension(original.pathExtension)
            copy = destination
            try FileManager.default.copyItem(at: original, to: destination)
            let file = try AVAudioFile(forReading: destination)
            let duration = Double(file.length) / file.processingFormat.sampleRate
            guard duration.isFinite, duration > 0, duration <= 30 else { throw WatchWhisperLabError.audio }
            if let audioInput { try? FileManager.default.removeItem(at: audioInput) }
            audioInput = destination; audioSeconds = duration
        } catch {
            if let copy { try? FileManager.default.removeItem(at: copy) }
            self.error = .audio
        }
    }
    func startRecording() async {
        guard enabled, !busy else { return }
        clearResult(); generation = UUID(); let token = generation
        requestingMicrophone = true
        #if os(watchOS)
        let granted = await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { continuation.resume(returning: $0) }
        }
        guard token == generation, enabled else { return }
        requestingMicrophone = false
        guard granted else { error = .microphone; return }
        do {
            try AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .default)
            try AVAudioSession.sharedInstance().setActive(true)
            let url = try temporaryDirectory().appendingPathComponent(UUID().uuidString).appendingPathExtension("wav")
            let recorder = try AVAudioRecorder(url: url, settings: [AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: 16_000, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
            guard recorder.record(forDuration: 30) else { throw WatchWhisperLabError.audio }
            if let audioInput { try? FileManager.default.removeItem(at: audioInput) }
            audioInput = url; audioSeconds = nil; self.recorder = recorder; recording = true
            recordingLimit = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(30)) } catch { return }
                self?.stopRecording()
            }
        } catch { self.error = .audio; stopRecording() }
        #else
        requestingMicrophone = false; error = .microphone
        #endif
    }
    func stopRecording() {
        recordingLimit?.cancel(); recordingLimit = nil
        recorder?.stop(); recorder = nil; recording = false; requestingMicrophone = false
        if let audioInput, let file = try? AVAudioFile(forReading: audioInput) {
            audioSeconds = Double(file.length) / file.processingFormat.sampleRate
        }
        #if os(watchOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
        #endif
    }
    func run() {
        guard enabled, !busy, !store.active, let audioInput, let audioSeconds, audioSeconds > 0,
              audioSeconds <= 30, let directory = store.installedDirectory else { return }
        clearResult(); generation = UUID(); let token = generation
        running = true; phase = .loading; phaseStarted = ProcessInfo.processInfo.systemUptime
        baselineBytes = memory(); sampledPeakBytes = baselineBytes
        let runtime = factory(), started = phaseStarted, controller = self
        job = Task {
            let sampler = Task { [weak controller] in
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
                    guard let controller, controller.generation == token else { return }
                    controller.sampleMemory()
                }
            }
            var result: WatchWhisperResult?
            do {
                result = try await runtime.transcribe(audioInput, directory: directory) { next in
                    await MainActor.run { [weak controller] in
                        guard controller?.generation == token else { return }
                        controller?.transition(next)
                    }
                }
                try Task.checkCancellation()
            } catch is CancellationError { result = nil }
              catch { if generation == token { self.error = .inference }; result = nil }
            if generation == token { transition(.unloading) }
            await runtime.unload()
            sampler.cancel(); await sampler.value
            if generation == token {
                sampleMemory(); transition(.completed)
                if !Task.isCancelled {
                    elapsed = max(0, ProcessInfo.processInfo.systemUptime - started)
                    transcript = result?.text
                }
            }
            running = false; cancelling = false; job = nil
            if token != generation { removeTemporaryFiles() }
        }
    }
    func cancel() {
        guard running else { return }
        cancelling = true; transcript = nil; error = nil; job?.cancel()
    }
    func waitUntilIdle() async { await job?.value }
    func leave() {
        generation = UUID(); cancel(); store.cancel(); stopRecording()
        enabled = false; audioInput = nil; audioSeconds = nil; clearResult()
        if !running { removeTemporaryFiles() }
    }
    func disable() { leave() }
    func removeModel() async { guard !busy else { return }; await store.remove() }
    private func transition(_ next: WatchWhisperRunPhase) {
        guard let phase, next.rawValue > phase.rawValue else { return }
        let now = ProcessInfo.processInfo.systemUptime
        timings.append(.init(phase: phase, seconds: max(0, now - phaseStarted)))
        self.phase = next; phaseStarted = now
    }
    private func sampleMemory() {
        guard let bytes = memory() else { return }
        endBytes = bytes; sampledPeakBytes = max(sampledPeakBytes ?? bytes, bytes)
    }
    private func clearResult() {
        transcript = nil; error = nil; timings = []; phase = nil; elapsed = nil
        baselineBytes = nil; sampledPeakBytes = nil; endBytes = nil
    }
    private func temporaryDirectory() throws -> URL {
        if let privateDirectory { return privateDirectory }
        let directory = temporaryRoot.appendingPathComponent("watch-whisper-input-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        privateDirectory = directory; return directory
    }
    private func removeTemporaryFiles() {
        if let privateDirectory { try? FileManager.default.removeItem(at: privateDirectory) }
        privateDirectory = nil
    }
    nonisolated static func residentBytes() -> Int64? {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? Int64(info.resident_size) : nil
    }
}
