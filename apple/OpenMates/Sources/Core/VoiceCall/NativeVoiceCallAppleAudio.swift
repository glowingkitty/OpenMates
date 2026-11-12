// Web source: frontend/packages/ui/src/services/voiceCall.ts, voiceCallAudioGate.ts, voiceCallBackground.ts,
// assistantSpeechController.ts (live-call speech output)
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.audio.single-owner, video-call.audio.startup-buffer,
// video-call.audio.automatic-idle, video-call.lifecycle.recovery-and-billing,
// video-call.audio.background-resume

#if !os(watchOS)
import AVFoundation
import Foundation
#if os(iOS)
import UIKit
#endif

/// Memory-only duplex audio, separate from AAC composer recording and ordinary
/// 1.25x response speech. Foreground adapter; no background/call-route promise:
/// capture the OS stops while the app is away ends the call cleanly instead.
@MainActor
final class NativeVoiceCallAppleAudio: NativeVoiceCallAudio {
    private let runtime: AssistantSpeechAppRuntime
    private let permission: @MainActor @Sendable () async -> Bool
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    /// Assistant speech of the call (`assistant_speech_audio` MP3 on the chat socket).
    private let speechOutput = NativeVoiceCallSpeechEngineOutput()
    private var reservation: UUID?
    private var playbackGeneration = UUID()
    private var queuedPlaybackFrames = 0
    private var continuation: AsyncStream<Data>.Continuation?
    private var consumer: Task<Void, Never>?
    private var capture: NativeVoiceCallAVCaptureConverter?
    private var tapInstalled = false
    private var configured = false
    private var onFailure: (@Sendable (NativeVoiceCallError) async -> Void)?
    private var interruptionObserver: NSObjectProtocol?
    private var routeObserver: NSObjectProtocol?
    private var lifecycleObservers: [NSObjectProtocol] = []
    private var inBackground = false
    private var invalidated: @Sendable () async -> Void

    init(runtime: AssistantSpeechAppRuntime = .shared,
         permission: @escaping @MainActor @Sendable () async -> Bool = {
             #if os(iOS)
             return await withCheckedContinuation { continuation in
                 AVAudioSession.sharedInstance().requestRecordPermission { continuation.resume(returning: $0) }
             }
             #else
             return await AVCaptureDevice.requestAccess(for: .audio)
             #endif
         }, invalidated: @escaping @Sendable () async -> Void) {
        self.runtime = runtime; self.permission = permission; self.invalidated = invalidated
    }

    func reserve(scope: NativeVoiceCallScope) async throws {
        guard reservation == nil else { throw NativeVoiceCallError.audioUnavailable }
        let invalidated = invalidated
        reservation = try await runtime.reserveLiveCall(chatID: scope.chatID) {
            Task { await invalidated() }
        }
        // Permission is requested after consent and exclusive speech drain.
        guard await permission() else {
            if let reservation { runtime.releaseLiveCall(reservation) }
            reservation = nil
            throw NativeVoiceCallError.audioUnavailable
        }
    }

    func start(input: @escaping @Sendable (Data) async -> Void,
               failure: @escaping @Sendable (NativeVoiceCallError) async -> Void) async throws {
        guard let reservation, runtime.isLiveCallReservationCurrent(reservation), !tapInstalled
        else { throw NativeVoiceCallError.audioUnavailable }
        onFailure = failure
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetooth])
        try session.setPreferredSampleRate(48_000)
        try session.setActive(true)
        #endif
        // The voice-processing I/O unit provides echo cancellation for duplex.
        try engine.inputNode.setVoiceProcessingEnabled(true)
        let source = engine.inputNode.outputFormat(forBus: 0)
        guard source.sampleRate > 0, source.channelCount > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000,
                                         channels: 1, interleaved: false),
              let playback = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000,
                                           channels: 1, interleaved: false)
        else { throw NativeVoiceCallError.audioUnavailable }
        let converter = try NativeVoiceCallAVCaptureConverter(source: source, target: target)
        capture = converter
        let stream = AsyncStream<Data>(bufferingPolicy: .bufferingOldest(96)) { continuation = $0 }
        guard let continuation else { throw NativeVoiceCallError.audioUnavailable }
        consumer = Task {
            for await data in stream {
                guard !Task.isCancelled else { return }
                await input(data)
            }
        }
        engine.inputNode.installTap(onBus: 0, bufferSize: 1_024, format: source) { buffer, _ in
            do {
                guard let data = try converter.convert(buffer) else { return }
                if case .dropped = continuation.yield(data) {
                    converter.stop()
                    continuation.finish()
                    Task { await failure(.audioQueueFull) }
                }
            } catch {
                converter.stop()
                continuation.finish()
                Task { await failure(.audioUnavailable) }
            }
        }
        tapInstalled = true
        if !configured {
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: playback)
            speechOutput.attach(to: engine)
            configured = true
        }
        #if os(iOS)
        interruptionObserver = NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification,
            object: nil, queue: .main) { [weak self] notification in
                if notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt == AVAudioSession.InterruptionType.began.rawValue {
                    // Away from the screen the user can no longer speak: end, do not fail.
                    let away = MainActor.assumeIsolated { self?.inBackground ?? false }
                    let error = NativeVoiceCallInterruptionPolicy.interruptionError(appInBackground: away)
                    Task { await failure(error) }
                }
            }
        inBackground = false
        lifecycleObservers = [
            NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification,
                object: nil, queue: .main) { [weak self] _ in
                    MainActor.assumeIsolated {
                        guard let self else { return }
                        self.inBackground = true
                    }
                },
            NotificationCenter.default.addObserver(forName: UIApplication.willEnterForegroundNotification,
                object: nil, queue: .main) { [weak self] _ in
                    // A suspended app may return with its engine stopped and no
                    // interruption delivered; that capture cannot be trusted.
                    let error: NativeVoiceCallError? = MainActor.assumeIsolated {
                        guard let self else { return nil }
                        self.inBackground = false
                        return NativeVoiceCallInterruptionPolicy.returnError(
                            captureInstalled: self.tapInstalled, engineRunning: self.engine.isRunning)
                    }
                    if let error { Task { await failure(error) } }
                },
        ]
        routeObserver = NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification,
            object: nil, queue: .main) { notification in
                // A lost device ends visibly; no silent capture on a new route.
                if notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue {
                    Task { await failure(.audioUnavailable) }
                }
            }
        #endif
        engine.prepare()
        try engine.start()
        player.play()
        runtime.attachLiveCallSpeechOutput(speechOutput)
    }

    func setMicrophoneEnabled(_ enabled: Bool) { capture?.setEnabled(enabled) }

    func play(_ pcm16: Data, sampleRate: Int) throws {
        guard sampleRate == 24_000, let reservation, runtime.isLiveCallReservationCurrent(reservation),
              engine.isRunning, pcm16.count % 2 == 0,
              queuedPlaybackFrames + pcm16.count / 2 <= 24_000 * 10,
              let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000,
                                         channels: 1, interleaved: false),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(pcm16.count / 2)),
              let output = buffer.floatChannelData?[0] else { throw NativeVoiceCallError.audioUnavailable }
        let samples = try NativeVoiceCallPCM.decode(pcm16)
        buffer.frameLength = AVAudioFrameCount(samples.count)
        for index in samples.indices { output[index] = samples[index] }
        queuedPlaybackFrames += samples.count
        let frames = samples.count, generation = playbackGeneration
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.playbackGeneration == generation else { return }
                self.queuedPlaybackFrames = max(0, self.queuedPlaybackFrames - frames)
            }
        }
        if !player.isPlaying { player.play() }
    }

    func interruptPlayback() {
        playbackGeneration = UUID(); queuedPlaybackFrames = 0
        player.stop()
        if engine.isRunning { player.play() }
    }

    func stop() {
        guard reservation != nil || tapInstalled || engine.isRunning else { return }
        // Stop converter under its lock before removing the tap; an in-flight
        // callback drains without exposing AVAudioPCMBuffer across actors.
        capture?.stop(); capture = nil
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        continuation?.finish(); continuation = nil
        consumer = nil // finished bounded stream drains; controller generation rejects late callbacks
        playbackGeneration = UUID(); queuedPlaybackFrames = 0
        runtime.detachLiveCallSpeechOutput(speechOutput); speechOutput.stop()
        player.stop(); engine.stop()
        if let interruptionObserver { NotificationCenter.default.removeObserver(interruptionObserver) }
        if let routeObserver { NotificationCenter.default.removeObserver(routeObserver) }
        lifecycleObservers.forEach { NotificationCenter.default.removeObserver($0) }
        lifecycleObservers = []; inBackground = false
        interruptionObserver = nil; routeObserver = nil; onFailure = nil
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
        if let reservation { runtime.releaseLiveCall(reservation) }
        reservation = nil
    }
}

/// The tap owns conversion synchronously. The lock serializes stop/mute against
/// conversion; only immutable Data leaves the callback. A muted mic produces no
/// uploaded silence. 96 tap chunks bound the forwarding backlog independently.
private final class NativeVoiceCallAVCaptureConverter: @unchecked Sendable {
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
    func stop() { lock.lock(); defer { lock.unlock() }; stopped = true; enabled = false }
    func convert(_ source: AVAudioPCMBuffer) throws -> Data? {
        lock.lock(); defer { lock.unlock() }
        guard !stopped, enabled else { return nil }
        let capacity = AVAudioFrameCount(ceil(Double(source.frameLength) * 16_000 / source.format.sampleRate) + 32)
        guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { throw NativeVoiceCallError.audioUnavailable }
        var consumed = false
        var error: NSError?
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
