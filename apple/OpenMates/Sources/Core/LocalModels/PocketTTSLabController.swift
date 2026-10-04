// Ephemeral developer lab; never called by chat playback or speech-recognition providers.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.local-execution, apple-local-model-lab.serialized-cancellation, apple-local-model-lab.ephemeral-state
import AVFoundation
import Combine
import Foundation

@MainActor
final class PocketTTSLabController: ObservableObject {
    static let shared = PocketTTSLabController()
    @Published var text = ""
    @Published private(set) var busy = false
    @Published private(set) var cancelling = false
    @Published private(set) var measurement: LocalModelRunMeasurement.Snapshot?
    @Published private(set) var audio: PocketTTSAudio?
    @Published private(set) var errorMessage: String?
    @Published private(set) var playing = false
    private let store: LocalModelStore
    private let runtime: any PocketTTSRuntime
    private let availability: @Sendable () -> Bool
    private var player: AVAudioPlayer?
    private var job: Task<Void, Never>?
    private var generation = UUID()
    private var playbackJob: Task<Void, Never>?

    init(store: LocalModelStore = .shared, runtime: any PocketTTSRuntime = PocketTTSCPURuntime(),
         availability: @escaping @Sendable () -> Bool = { PocketTTSCPURuntime.available }) {
        self.store = store; self.runtime = runtime; self.availability = availability
    }
    var available: Bool { availability() }
    var validInput: Bool { (try? PocketTTSInput.sentences(text)) != nil }

    func run(enabled: Bool) {
        guard enabled, !busy, available else { return }
        guard validInput else { errorMessage = AppStrings.localLabPocketInputLimit; return }
        let directory: URL
        do { directory = try store.installedDirectory(.pocketTTS) }
        catch { errorMessage = AppStrings.localLabRunError; return }
        stopPlayback(); audio = nil; errorMessage = nil
        generation = UUID(); let token = generation
        busy = true; cancelling = false
        let submitted = text, runtime = runtime
        guard let manifest = store.manifest(for: .pocketTTS) else { busy = false; return }
        let metrics = LocalModelRunMeasurement()
        measurement = metrics.snapshot()
        let owner = self
        job = Task {
            let sampler = Task {
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .milliseconds(250)) } catch { break }
                    metrics.sample()
                    if owner.generation == token { owner.measurement = metrics.snapshot() }
                }
            }
            var output: PocketTTSAudio?
            do {
                metrics.transition(.tokenizerPreparation)
                let verification = Task.detached(priority: .utility) { try LocalModelDisk.verify(manifest, at: directory) }
                try await withTaskCancellationHandler(operation: { try await verification.value }, onCancel: { verification.cancel() })
                try Task.checkCancellation()
                output = try await runtime.synthesize(submitted, directory: directory) { phase in metrics.transition(phase) }
                try Task.checkCancellation()
            } catch is CancellationError { output = nil }
            catch {
                output = nil
                if owner.generation == token, !Task.isCancelled { owner.errorMessage = AppStrings.localLabRunError }
            }
            // The runtime returns only after its synchronous engine has been destroyed.
            metrics.transition(.cleanup); metrics.sample(); metrics.transition(.completion)
            sampler.cancel(); await sampler.value
            if owner.generation == token {
                owner.measurement = metrics.snapshot()
                owner.audio = Task.isCancelled ? nil : output
            }
            owner.busy = false; owner.cancelling = false; owner.job = nil
            if owner.generation != token { owner.measurement = nil }
        }
    }
    func cancel() {
        guard busy else { return }
        cancelling = true; audio = nil; job?.cancel()
    }
    func waitUntilIdle() async { let current = job; await current?.value }
    func leave() {
        generation = UUID(); text = ""; audio = nil; measurement = nil; errorMessage = nil
        stopPlayback(); cancel()
    }
    func play() {
        guard !busy, let audio else { return }
        stopPlayback()
        do {
            #if os(iOS)
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
            try AVAudioSession.sharedInstance().setActive(true)
            #endif
            let next = try AVAudioPlayer(data: audio.wav)
            guard next.prepareToPlay(), next.play() else { throw PocketTTSError.invalidOutput }
            player = next; playing = true
            playbackJob = Task { [weak self] in
                while let self, self.player?.isPlaying == true, !Task.isCancelled {
                    do { try await Task.sleep(for: .milliseconds(100)) } catch { return }
                }
                if !Task.isCancelled { self?.stopPlayback() }
            }
        } catch { errorMessage = AppStrings.localLabAudioError; stopPlayback() }
    }
    func stopPlayback() {
        let ownedAudioSession = player != nil
        playbackJob?.cancel(); playbackJob = nil
        player?.stop(); player = nil; playing = false
        #if os(iOS)
        if ownedAudioSession { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
        #endif
    }
}
