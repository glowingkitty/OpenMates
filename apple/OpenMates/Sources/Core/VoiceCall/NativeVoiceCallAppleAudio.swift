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
/// 1.25x response speech. On iOS the voice-chat audio session stays active for
/// the whole call, so with the `audio` background mode the call keeps running
/// off screen and with the screen locked. Only a microphone the system removes
/// for good ends it (`NativeVoiceCallInterruptionPolicy`).
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
    #if os(iOS)
    private let sessionLifecycle: NativeVoiceCallAudioSessionLifecycle
    #endif
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
        #if os(iOS)
        self.sessionLifecycle = NativeVoiceCallAudioSessionLifecycle()
        #endif
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
            throw NativeVoiceCallError.microphoneDenied
        }
    }

    func start(input: @escaping @Sendable (Data) async -> Void,
               failure: @escaping @Sendable (NativeVoiceCallError) async -> Void) async throws {
        guard let reservation, runtime.isLiveCallReservationCurrent(reservation), !tapInstalled
        else { throw NativeVoiceCallError.audioUnavailable }
        onFailure = failure
        #if os(iOS)
        // Active until stop(): also off screen and with the screen locked.
        try sessionLifecycle.activate(.init(
            resume: { [weak self] in try self?.resumeAfterInterruption() },
            end: { error in Task { await failure(error) } },
            isRunning: { [weak self] in self?.engine.isRunning ?? false }))
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
        engine.prepare()
        try engine.start()
        player.play()
        runtime.attachLiveCallSpeechOutput(speechOutput)
    }

    func setMicrophoneEnabled(_ enabled: Bool) { capture?.setEnabled(enabled) }

    func play(_ pcm16: Data, sampleRate: Int) throws {
        #if os(iOS)
        // The system owns the audio during an interruption (phone call, Siri);
        // the call continues with the next chunk once it hands the audio back.
        if sessionLifecycle.isSuspended { return }
        #endif
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
        onFailure = nil
        #if os(iOS)
        // No call, no background audio: release the session with the call.
        sessionLifecycle.deactivate()
        #endif
        if let reservation { runtime.releaseLiveCall(reservation) }
        reservation = nil
        #if os(iOS)
        NativeVoiceCallBackgroundPresence.shared.callEnded(appIsActive: UIApplication.shared.applicationState == .active)
        #endif
    }

    #if os(iOS)
    /// The system handed the audio back: restart the engine and both players
    /// with the existing capture tap; the call, its timer and transport never paused.
    private func resumeAfterInterruption() throws {
        guard tapInstalled else { return }
        if !engine.isRunning {
            engine.prepare()
            try engine.start()
        }
        player.play()
        speechOutput.resumeAfterInterruption()
    }
    #endif
}

#if os(iOS)
/// The AVAudioSession calls of one call; a seam so lifecycle tests need no hardware.
@MainActor
protocol NativeVoiceCallAudioSessionControlling: AnyObject {
    /// `.playAndRecord` + `.voiceChat`, active for the whole call. With the
    /// `audio` background mode this keeps the app running off screen.
    func activate() throws
    /// Releases the session so the app holds no background audio without a call.
    func deactivate()
    var isInputAvailable: Bool { get }
}

@MainActor
final class NativeVoiceCallSystemAudioSession: NativeVoiceCallAudioSessionControlling {
    func activate() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetooth])
        try session.setPreferredSampleRate(48_000)
        try session.setActive(true)
    }

    func deactivate() {
        do { try AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
        catch {
            NativeDiagnostics.warning("Voice call audio session deactivation failed: \(type(of: error))",
                                      category: "voice_call")
        }
    }

    var isInputAvailable: Bool { AVAudioSession.sharedInstance().isInputAvailable }
}

/// Owns the call's audio session from start to hangup and turns system audio
/// events into continue/end decisions. App background, foreground and screen
/// lock never end or pause the call; only `NativeVoiceCallInterruptionPolicy`
/// ends do, reported once through `Handlers.end`.
@MainActor
final class NativeVoiceCallAudioSessionLifecycle {
    struct Handlers {
        /// Restarts engine and players after the system handed the audio back.
        let resume: @MainActor () throws -> Void
        let end: @MainActor (NativeVoiceCallError) -> Void
        let isRunning: @MainActor () -> Bool
    }

    private let session: any NativeVoiceCallAudioSessionControlling
    private let center: NotificationCenter
    private let queue: OperationQueue?
    private var observers: [NSObjectProtocol] = []
    private var handlers: Handlers?
    private(set) var isActive = false
    /// The system holds the audio (interruption began and has not ended).
    private(set) var isSuspended = false

    /// `queue` nil delivers on the posting thread (tests post on the main actor).
    init(session: (any NativeVoiceCallAudioSessionControlling)? = nil,
         center: NotificationCenter = .default, queue: OperationQueue? = .main) {
        self.session = session ?? NativeVoiceCallSystemAudioSession()
        self.center = center; self.queue = queue
    }

    func activate(_ handlers: Handlers) throws {
        deactivate()
        try session.activate()
        isActive = true
        self.handlers = handlers
        observers = [
            center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: queue) { [weak self] note in
                let type = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
                let options = AVAudioSession.InterruptionOptions(
                    rawValue: note.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0)
                let event: NativeVoiceCallAudioSessionEvent
                if type == AVAudioSession.InterruptionType.began.rawValue {
                    event = .interruptionBegan
                } else if type == AVAudioSession.InterruptionType.ended.rawValue {
                    event = .interruptionEnded(shouldResume: options.contains(.shouldResume))
                } else { return }
                MainActor.assumeIsolated { self?.handle(event) }
            },
            center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: queue) { [weak self] _ in
                MainActor.assumeIsolated { self?.handle(.mediaServicesReset) }
            },
            center.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: queue) { [weak self] note in
                guard note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                        == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue else { return }
                MainActor.assumeIsolated { self?.inputDeviceLost() }
            },
            center.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: queue) { [weak self] _ in
                MainActor.assumeIsolated { self?.returnedToForeground() }
            },
        ]
    }

    func handle(_ event: NativeVoiceCallAudioSessionEvent) {
        guard let handlers else { return }
        switch NativeVoiceCallInterruptionPolicy.action(for: event) {
        case .suspend:
            // The system stopped the engine; capture and speech restart on resume.
            isSuspended = true
        case .resume:
            isSuspended = false
            do {
                try session.activate()
                try handlers.resume()
            } catch {
                // The system did not give the audio back.
                NativeDiagnostics.warning("Voice call audio did not resume: \(type(of: error))", category: "voice_call")
                end(.endedInBackground)
            }
        case .end(let error):
            end(error)
        }
    }

    private func inputDeviceLost() {
        handle(.inputDeviceLost(otherInputAvailable: session.isInputAvailable))
    }

    /// The app can come back on screen with the engine stopped and no
    /// interruption end delivered; try once to get the audio back.
    func returnedToForeground() {
        guard let handlers, !isSuspended, !handlers.isRunning() else { return }
        handle(.interruptionEnded(shouldResume: true))
    }

    /// One terminal report; the caller's stop() then deactivates the session.
    private func end(_ error: NativeVoiceCallError) {
        let handlers = self.handlers
        self.handlers = nil
        handlers?.end(error)
    }

    func deactivate() {
        observers.forEach { center.removeObserver($0) }
        observers = []
        handlers = nil; isSuspended = false
        guard isActive else { return }
        isActive = false
        session.deactivate()
    }
}

/// A running call keeps the chat socket in the foreground state: assistant
/// speech and call turns travel on it. The app's background announcement,
/// which also closes that socket, waits until the call has ended.
@MainActor
final class NativeVoiceCallBackgroundPresence {
    static let shared = NativeVoiceCallBackgroundPresence()
    private var deferred: (@MainActor () -> Void)?

    /// True when `announce` was held back because a call is running.
    func deferWhileCallRuns(callRunning: Bool, _ announce: @escaping @MainActor () -> Void) -> Bool {
        guard callRunning else { deferred = nil; return false }
        deferred = announce
        return true
    }

    /// After the call, announce the background state only if still off screen.
    func callEnded(appIsActive: Bool) {
        let announce = deferred
        deferred = nil
        if !appIsActive { announce?() }
    }
}
#endif

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
