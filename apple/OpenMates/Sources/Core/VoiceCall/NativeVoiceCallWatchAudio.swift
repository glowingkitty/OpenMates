// Web source: frontend/packages/ui/src/services/voiceCall.ts, voiceCallAudioGate.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.audio.single-owner, video-call.audio.automatic-idle,
// video-call.audio.startup-buffer, video-call.lifecycle.recovery-and-billing, video-call.audio.spoken-rich-response
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
#if os(watchOS)
import AVFoundation
import Foundation
import WatchKit

@MainActor
final class NativeVoiceCallWatchAudio: NSObject, NativeVoiceCallAudio, AVAudioPlayerDelegate {
    struct Diagnostics: Sendable {
        var activated = false
        var hardwareSampleRate: Double = 0
        var capturedFrames = 0
        var playedFrames = 0
        var inputRouteKinds: [String] = []
        var outputRouteKinds: [String] = []
        var idleTransitions = 0
        var ownershipReleased = false
    }
    private let ownership: WatchAudioOwnership
    private let eligible: @MainActor @Sendable () -> Bool
    private let activity: @Sendable (Bool) async -> Void
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var lease: WatchAudioOwnership.Lease?
    private var capture: NativeVoiceCallWatchConverter?
    private var continuation: AsyncStream<Data>.Continuation?
    private var consumer: Task<Void, Never>?
    private var foregroundMonitor: Task<Void, Never>?
    private var observers: [NSObjectProtocol] = []
    private var installed = false
    private var configured = false
    private var activation: Task<Bool, any Error>?
    private var activationGeneration = UUID()
    private var manualEnabled = true
    private var uploadIdle = false
    private var detector = NativeVoiceCallEnergyGate()
    private var generation = UUID()
    private var playbackGeneration = UUID()
    private var speechPlayer: AVAudioPlayer?
    private var currentSpeechSequence: Int?
    private(set) var completedSpeechSequence: Int?
    private var speechCompletion: CheckedContinuation<Void, any Error>?
    private var scheduledFrames = 0
    private(set) var diagnostics = Diagnostics()

    /// Eligibility is a source-bound physical-route gate owned by the app.
    /// The explicit hardware probe uses a separate launch-gated admission path.
    init(ownership: WatchAudioOwnership,
         eligible: @escaping @MainActor @Sendable () -> Bool,
         inputIdle: @escaping @Sendable (Bool) async -> Void) {
        self.ownership = ownership; self.eligible = eligible; activity = inputIdle
        super.init()
    }
    func reserve(scope: NativeVoiceCallScope) async throws {
        guard lease == nil, eligible(), WKExtension.shared().applicationState == .active
        else { throw NativeVoiceCallError.unsupportedTransport }
        WatchAudioPlaybackLoader.stopCurrentPlayback()
        let acquired = try ownership.acquire(owner: .liveCall)
        lease = acquired
        let granted = await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
        }
        guard granted, ownership.isCurrent(acquired), eligible(),
              WKExtension.shared().applicationState == .active else {
            ownership.release(acquired); lease = nil
            throw NativeVoiceCallError.audioUnavailable
        }
    }
    func start(input: @escaping @Sendable (Data) async -> Void,
               failure: @escaping @Sendable (NativeVoiceCallError) async -> Void) async throws {
        guard let lease, ownership.isCurrent(lease), eligible(), !installed,
              WKExtension.shared().applicationState == .active else { throw NativeVoiceCallError.audioUnavailable }
        let session = AVAudioSession.sharedInstance()
        // defaultToSpeaker/preferredSampleRate are unavailable on watchOS.
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetoothHFP])
        let activationToken = UUID(); activationGeneration = activationToken
        let operation = Task { @MainActor in
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Bool, any Error>) in
                session.activate(options: []) { active, error in
                    if let error { continuation.resume(throwing: error) }
                    else { continuation.resume(returning: active) }
                }
            }
        }
        activation = operation
        let activated = try await operation.value
        if activationGeneration == activationToken { activation = nil }
        guard activationGeneration == activationToken, activated, ownership.isCurrent(lease), eligible(),
              WKExtension.shared().applicationState == .active else { throw NativeVoiceCallError.audioUnavailable }
        diagnostics = Diagnostics(); diagnostics.activated = true
        diagnostics.hardwareSampleRate = session.sampleRate
        diagnostics.inputRouteKinds = session.currentRoute.inputs.map { $0.portType.rawValue }
        diagnostics.outputRouteKinds = session.currentRoute.outputs.map { $0.portType.rawValue }
        guard session.isInputAvailable, !session.currentRoute.inputs.isEmpty,
              !session.currentRoute.outputs.isEmpty else { throw NativeVoiceCallError.audioUnavailable }
        try engine.inputNode.setVoiceProcessingEnabled(true)
        let source = engine.inputNode.outputFormat(forBus: 0)
        guard source.sampleRate > 0, source.channelCount > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: false),
              let output = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000, channels: 1, interleaved: false)
        else { throw NativeVoiceCallError.audioUnavailable }
        let converter = try NativeVoiceCallWatchConverter(source: source, target: target)
        capture = converter; detector.reset(); manualEnabled = true; uploadIdle = false
        let token = UUID(); generation = token
        let stream = AsyncStream<Data>(bufferingPolicy: .bufferingOldest(96)) { continuation = $0 }
        guard let continuation else { throw NativeVoiceCallError.audioUnavailable }
        consumer = Task { [weak self] in
            for await pcm in stream {
                guard !Task.isCancelled, let self, generation == token, manualEnabled,
                      ownership.isCurrent(lease) else { continue }
                diagnostics.capturedFrames += pcm.count / 2
                do {
                    switch try detector.process(pcm) {
                    case .upload(let data):
                        if !uploadIdle { await input(data) }
                    case .enteredIdle:
                        uploadIdle = true; diagnostics.idleTransitions += 1
                        await activity(true) // ordered real audio_stream_end via controller
                    case .idle: break
                    case .resumed(let preRoll):
                        uploadIdle = false
                        await activity(false)
                        guard generation == token, manualEnabled, ownership.isCurrent(lease) else { continue }
                        await input(preRoll)
                    }
                } catch { await failure(.audioUnavailable); return }
            }
        }
        engine.inputNode.installTap(onBus: 0, bufferSize: 1_024, format: source) { buffer, _ in
            do {
                guard let data = try converter.convert(buffer) else { return }
                if case .dropped = continuation.yield(data) {
                    converter.stop(); continuation.finish()
                    Task { await failure(.audioQueueFull) }
                }
            } catch {
                converter.stop(); continuation.finish()
                Task { await failure(.audioUnavailable) }
            }
        }
        installed = true
        if !configured {
            engine.attach(player); engine.connect(player, to: engine.mainMixerNode, format: output)
            configured = true
        }
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification,
            object: nil, queue: .main) { notification in
                if notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt == AVAudioSession.InterruptionType.began.rawValue {
                    Task { await failure(.audioUnavailable) }
                }
            })
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification,
            object: nil, queue: .main) { notification in
                if notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue {
                    Task { await failure(.audioUnavailable) }
                }
            })
        engine.prepare(); try engine.start(); player.play()
        foregroundMonitor = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
                guard let self, generation == token else { return }
                if WKExtension.shared().applicationState != .active {
                    // Dispatch terminal handling independently: stop must not
                    // cancel the very task persisting its final lifecycle row.
                    Task { await failure(.unsupportedTransport) }
                    return
                }
            }
        }
    }
    func setMicrophoneEnabled(_ enabled: Bool) {
        if manualEnabled != enabled { detector.reset() }
        manualEnabled = enabled
        capture?.setEnabled(enabled)
    }
    func setInputIdle(_ idle: Bool) { uploadIdle = idle }
    func play(_ pcm16: Data, sampleRate: Int) throws {
        guard sampleRate == 24_000, let lease, ownership.isCurrent(lease), engine.isRunning,
              scheduledFrames + pcm16.count / 2 <= 24_000 * 10,
              let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000, channels: 1, interleaved: false),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(pcm16.count / 2)),
              let channel = buffer.floatChannelData?[0] else { throw NativeVoiceCallError.audioUnavailable }
        let samples = try NativeVoiceCallPCM.decode(pcm16)
        buffer.frameLength = AVAudioFrameCount(samples.count)
        for index in samples.indices { channel[index] = samples[index] }
        scheduledFrames += samples.count
        let token = playbackGeneration, frames = samples.count
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.playbackGeneration == token else { return }
                self.scheduledFrames = max(0, self.scheduledFrames - frames)
                self.diagnostics.playedFrames += frames
            }
        }
        if !player.isPlaying { player.play() }
    }
    /// Generated encrypted speech is decoded in memory under the existing
    /// duplex lease; it must not reconfigure the session or start a second mic.
    var isSpeechPlaying: Bool { speechPlayer != nil }
    var speechPositionMilliseconds: Int {
        let milliseconds = (speechPlayer?.currentTime ?? 0) * 1_000
        return milliseconds.isFinite ? Int(min(3_600_000, max(0, milliseconds))) : 0
    }
    func playSpeech(_ bytes: Data, sequence: Int = 0) async throws {
        guard let lease, ownership.isCurrent(lease), engine.isRunning, eligible(),
              !bytes.isEmpty, bytes.count <= 16 * 1_024 * 1_024 else { throw NativeVoiceCallError.audioUnavailable }
        interruptPlayback()
        let token = playbackGeneration
        let output = try AVAudioPlayer(data: bytes)
        output.delegate = self; output.enableRate = true; output.rate = 1.25
        output.prepareToPlay(); speechPlayer = output; currentSpeechSequence = sequence; completedSpeechSequence = nil
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                speechCompletion = continuation
                guard !Task.isCancelled, output.play() else {
                    finishSpeech(NativeVoiceCallError.audioUnavailable); return
                }
            }
        } onCancel: { Task { @MainActor [weak self] in
            guard let self, playbackGeneration == token else { return }; interruptPlayback()
        } }
    }
    private func finishSpeech(_ error: (any Error)? = nil) {
        let completion = speechCompletion; speechCompletion = nil
        if error == nil, speechPlayer != nil { completedSpeechSequence = currentSpeechSequence }
        currentSpeechSequence = nil
        speechPlayer?.stop(); speechPlayer = nil
        if let error { completion?.resume(throwing: error) } else { completion?.resume() }
    }
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let identity = ObjectIdentifier(player)
        Task { @MainActor [weak self] in
            guard let self, let current = speechPlayer, ObjectIdentifier(current) == identity else { return }
            finishSpeech(flag ? nil : NativeVoiceCallError.audioUnavailable)
        }
    }
    func interruptPlayback() {
        finishSpeech(CancellationError())
        playbackGeneration = UUID(); scheduledFrames = 0
        player.stop(); if engine.isRunning { player.play() }
    }
    func stop() async {
        finishSpeech(CancellationError())
        activationGeneration = UUID()
        foregroundMonitor?.cancel(); foregroundMonitor = nil
        let pendingActivation = activation
        if pendingActivation != nil, let lease, ownership.isCurrent(lease) {
            // Ask the OS to cancel activation, but retain our lease until its
            // actual callback drains. A late activation cannot steal a newer
            // recorder/call's session after an early release.
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
        _ = try? await pendingActivation?.value
        activation = nil
        capture?.stop(); capture = nil
        if installed { engine.inputNode.removeTap(onBus: 0); installed = false }
        continuation?.finish(); continuation = nil; consumer = nil
        // Finishing the bounded stream and revoking generation drains old
        // callbacks without self-cancelling terminal encrypted persistence.
        generation = UUID(); playbackGeneration = UUID(); detector.reset(); scheduledFrames = 0
        player.stop(); engine.stop()
        observers.forEach { NotificationCenter.default.removeObserver($0) }; observers.removeAll()
        // A disappearing nonowner may stop only its own engine. It must never
        // deactivate a newer recorder/call's process-wide audio session.
        if let lease, ownership.isCurrent(lease) {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            diagnostics.ownershipReleased = ownership.release(lease)
        }
        lease = nil
    }
}

private final class NativeVoiceCallWatchConverter: @unchecked Sendable {
    private let lock = NSLock()
    private let converter: AVAudioConverter
    private let target: AVAudioFormat
    private var enabled = true
    private var stopped = false
    init(source: AVAudioFormat, target: AVAudioFormat) throws {
        guard let converter = AVAudioConverter(from: source, to: target) else { throw NativeVoiceCallError.audioUnavailable }
        self.converter = converter; self.target = target
    }
    func setEnabled(_ value: Bool) { lock.lock(); defer { lock.unlock() }; enabled = value }
    func stop() { lock.lock(); defer { lock.unlock() }; enabled = false; stopped = true }
    func convert(_ source: AVAudioPCMBuffer) throws -> Data? {
        lock.lock(); defer { lock.unlock() }
        guard enabled, !stopped else { return nil }
        let frames = AVAudioFrameCount(ceil(Double(source.frameLength) * 16_000 / source.format.sampleRate) + 32)
        guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: frames) else { throw NativeVoiceCallError.audioUnavailable }
        var consumed = false; var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, state in
            if consumed { state.pointee = .noDataNow; return nil }
            consumed = true; state.pointee = .haveData; return source
        }
        guard status != .error, error == nil, let channel = output.floatChannelData?[0]
        else { throw NativeVoiceCallError.audioUnavailable }
        guard output.frameLength > 0 else { return nil }
        return NativeVoiceCallPCM.encode(Array(UnsafeBufferPointer(start: channel, count: Int(output.frameLength))))
    }
}
#endif
