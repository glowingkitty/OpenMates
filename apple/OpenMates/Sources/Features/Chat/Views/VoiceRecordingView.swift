// Voice recording input — record audio messages directly in chat.
// Mirrors RecordAudio.svelte: start/stop/cancel, duration timer, waveform.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/RecordAudio.svelte
// CSS:     RecordAudio.svelte <style>
// i18n:    enter_message.record_audio.{recording,enter_to_finish_escape_to_cancel,
//          allow_microphone_access,microphone_blocked,cancel,finish}
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import AVFoundation

final class AudioRecordingFileWriter: @unchecked Sendable {
    static let maximumPendingBuffers = 24

    private let file: AVAudioFile
    private let queue = DispatchQueue(label: "org.openmates.audio-recording-writer", qos: .userInitiated)
    private let stateLock = NSLock()
    private var pendingBufferCount = 0
    private var acceptingBuffers = true
    private var writeFailed = false

    init(url: URL, sourceFormat: AVAudioFormat) throws {
        file = try VoiceRecorder.makeAACRecordingFile(at: url, sourceFormat: sourceFormat)
    }

    func enqueue(_ source: AVAudioPCMBuffer) -> Bool {
        stateLock.lock()
        guard acceptingBuffers, pendingBufferCount < Self.maximumPendingBuffers else {
            writeFailed = true
            stateLock.unlock()
            return false
        }
        pendingBufferCount += 1
        stateLock.unlock()

        guard let copy = Self.copyBuffer(source) else {
            completeBuffer(failed: true)
            return false
        }
        queue.async { [self] in
            do {
                try file.write(from: copy)
                completeBuffer(failed: false)
            } catch {
                completeBuffer(failed: true)
            }
        }
        return true
    }

    func finish() -> Bool {
        stateLock.lock()
        acceptingBuffers = false
        stateLock.unlock()
        queue.sync {}
        stateLock.lock()
        let succeeded = !writeFailed && pendingBufferCount == 0
        stateLock.unlock()
        return succeeded
    }

    private func completeBuffer(failed: Bool) {
        stateLock.lock()
        pendingBufferCount = max(0, pendingBufferCount - 1)
        writeFailed = writeFailed || failed
        stateLock.unlock()
    }

    private static func copyBuffer(_ source: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard source.format.commonFormat == .pcmFormatFloat32,
              !source.format.isInterleaved,
              let sourceChannels = source.floatChannelData,
              let copy = AVAudioPCMBuffer(
                pcmFormat: source.format,
                frameCapacity: source.frameLength
              ),
              let destinationChannels = copy.floatChannelData else { return nil }
        copy.frameLength = source.frameLength
        let byteCount = Int(source.frameLength) * MemoryLayout<Float>.size
        for channel in 0..<Int(source.format.channelCount) {
            memcpy(destinationChannels[channel], sourceChannels[channel], byteCount)
        }
        return copy
    }
}

private final class OrderedRealtimePCMForwarder: @unchecked Sendable {
    private struct Chunk: Sendable {
        let samples: [Float]
        let sampleRate: Double
    }

    private let continuation: AsyncStream<Chunk>.Continuation
    private let consumer: Task<Void, Never>
    private let onFailure: @Sendable () async -> Void

    init(
        client: AudioRealtimeTranscriptionClient,
        chatID: String,
        onFailure: @escaping @Sendable () async -> Void
    ) {
        var streamContinuation: AsyncStream<Chunk>.Continuation?
        let stream = AsyncStream<Chunk>(bufferingPolicy: .bufferingNewest(96)) {
            streamContinuation = $0
        }
        continuation = streamContinuation!
        self.onFailure = onFailure
        consumer = Task {
            do {
                try await client.start(chatID: chatID)
                for await chunk in stream {
                    try await client.append(samples: chunk.samples, sourceSampleRate: chunk.sampleRate)
                }
                await client.finish()
            } catch {
                await onFailure()
            }
        }
    }

    func append(samples: [Float], sampleRate: Double) {
        if case .dropped = continuation.yield(Chunk(samples: samples, sampleRate: sampleRate)) {
            Task { await onFailure() }
        }
    }

    func finish() {
        continuation.finish()
    }

    func cancel() {
        continuation.finish()
        consumer.cancel()
    }

    deinit {
        continuation.finish()
        consumer.cancel()
    }
}

@MainActor
final class AudioRecordingRealtimeSession {
    typealias PresentationHandler = @MainActor @Sendable (_ transcript: String, _ isConnecting: Bool) -> Void

    private var liveTranscript = ""
    private var isConnecting = false
    private var presentationHandler: PresentationHandler?
    private var rawTranscriptHandler: (@MainActor @Sendable (String) -> Void)?
    private var rawTranscript: String?

    private var client: AudioRealtimeTranscriptionClient?
    private var pcmForwarder: OrderedRealtimePCMForwarder?
    private var resultWaiters: [CheckedContinuation<AudioRecordingRealtimeResult?, Never>] = []
    private var settledResult: AudioRecordingRealtimeResult??

    func begin(
        authManager: AuthManager,
        chatID: String,
        presentationHandler: @escaping PresentationHandler
    ) {
        self.presentationHandler = presentationHandler
        liveTranscript = ""
        isConnecting = true
        presentationHandler("", true)
        settledResult = nil
        resultWaiters = []
        rawTranscript = nil
        rawTranscriptHandler = nil

        let client = AudioRealtimeTranscriptionClient.live(authManager: authManager) { [weak self] event in
            await self?.receive(event)
        }
        self.client = client
        pcmForwarder = OrderedRealtimePCMForwarder(client: client, chatID: chatID) { [weak self, weak client] in
            await client?.cancel()
            await self?.settle(nil)
        }
    }

    nonisolated func append(samples: [Float], sampleRate: Double) {
        Task { @MainActor [weak self] in
            self?.pcmForwarder?.append(samples: samples, sampleRate: sampleRate)
        }
    }

    func finish() {
        pcmForwarder?.finish()
    }

    func cancel() async {
        pcmForwarder?.cancel()
        pcmForwarder = nil
        await client?.cancel()
        settle(nil)
    }

    func awaitResult() async -> AudioRecordingRealtimeResult? {
        if let settledResult { return settledResult }
        return await withCheckedContinuation { continuation in
            resultWaiters.append(continuation)
        }
    }

    func observeRawTranscript(_ handler: @escaping @MainActor @Sendable (String) -> Void) {
        rawTranscriptHandler = handler
        if let rawTranscript { handler(rawTranscript) }
    }

    private func receive(_ event: AudioRealtimeTranscriptionClient.Event) async {
        switch event {
        case .status(.connecting):
            isConnecting = true
            presentationHandler?(liveTranscript, true)
        case .status(.listening):
            isConnecting = false
            presentationHandler?(liveTranscript, false)
        case .status(.correcting):
            isConnecting = false
            presentationHandler?(liveTranscript, false)
        case .status(.failed), .status(.cancelled):
            settle(nil)
        case .status(.completed):
            break
        case .transcript(let transcript):
            liveTranscript = transcript
            presentationHandler?(transcript, false)
        case .transcriptionDone(let result):
            liveTranscript = result.transcript
            rawTranscript = result.transcript
            rawTranscriptHandler?(result.transcript)
            presentationHandler?(result.transcript, false)
        case .correctionDone(let correction):
            liveTranscript = correction.transcript
            presentationHandler?(correction.transcript, false)
            settle(AudioRecordingRealtimeResult(
                title: correction.title,
                transcript: correction.transcript,
                transcriptOriginal: correction.transcriptOriginal,
                transcriptCorrected: correction.transcriptCorrected,
                useCorrected: correction.useCorrected,
                model: correction.model,
                correctionModel: correction.correctionModel
            ))
        }
    }

    private func settle(_ result: AudioRecordingRealtimeResult?) {
        guard settledResult == nil else { return }
        settledResult = .some(result)
        isConnecting = false
        presentationHandler?(liveTranscript, false)
        let waiters = resultWaiters
        resultWaiters = []
        waiters.forEach { $0.resume(returning: result) }
    }
}

@MainActor
enum MicPermissionState: Equatable {
    case unknown
    case granted
    case denied
}

@MainActor
final class VoiceRecorder: ObservableObject {
    static let waveformSampleCount = 64
    static let waveformSampleInterval: TimeInterval = 0.05
    static let waveformMinimumVisibleLevel = 0.04

    private static let waveformMinimumDecibels: Float = -46
    private static let waveformMaximumDecibels: Float = -18

    @Published var isRecording = false
    @Published var duration: TimeInterval = 0
    @Published var error: String?
    @Published private(set) var waveformSamples = Array(
        repeating: 0.0,
        count: VoiceRecorder.waveformSampleCount
    )

    private var recordingWriter: AudioRecordingFileWriter?
    private var audioEngine: AVAudioEngine?
    private var pcmHandler: (@Sendable ([Float], Double) -> Void)?
    private var durationTask: Task<Void, Never>?
    private var recordingURL: URL?
    private var recordedWaveformLevels: [Double] = []

    deinit {
        durationTask?.cancel()
    }

    func requestPermission() async -> Bool {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-mic-request-granted") {
            return true
        }
        #endif
        #if os(iOS)
        return await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
        #else
        return true
        #endif
    }

    func startRecording() {
        guard !isRecording else { return }
        error = nil
        resetWaveform()
        recordedWaveformLevels = []
        #if DEBUG
        if isUITestSimulatedRecording {
            isRecording = true
            duration = 1
            return
        }
        #endif
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default)
            try session.setActive(true)
        } catch {
            self.error = AppStrings.microphoneBlocked
            return
        }
        #endif

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("recording_\(UUID().uuidString.lowercased()).m4a")
        recordingURL = url

        do {
            try startPCMInputTap(writingTo: url)
            isRecording = true
            duration = 0

            durationTask = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .milliseconds(100))
                    guard let self, self.isRecording, !Task.isCancelled else { return }
                    self.duration += 0.1
                }
            }
        } catch {
            stopPCMInputTap()
            try? FileManager.default.removeItem(at: url)
            recordingURL = nil
            stopTimersAndWaveform()
            self.error = error.localizedDescription
        }
    }

    func stopRecording() -> URL? {
        guard isRecording else {
            stopTimersAndWaveform()
            return nil
        }
        #if DEBUG
        if isUITestSimulatedRecording {
            isRecording = false
            stopTimersAndWaveform()
            if isUITestFailedOutput {
                error = AppStrings.uploadProgressError
                return nil
            }
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent("recording-ui-test.m4a")
            if isUITestGuestLocalRecording {
                guard Self.writeUITestRecording(to: url) else { return nil }
            }
            return url
        }
        #endif
        let writerSucceeded = stopPCMInputTap()
        isRecording = false
        stopTimersAndWaveform()
        guard writerSucceeded,
              let recordingURL,
              let fileSize = try? recordingURL.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              fileSize > 0 else {
            if let recordingURL {
                try? FileManager.default.removeItem(at: recordingURL)
            }
            self.recordingURL = nil
            error = AppStrings.uploadProgressError
            return nil
        }
        return recordingURL
    }

    func cancelRecording() {
        stopPCMInputTap()
        if let recordingURL {
            try? FileManager.default.removeItem(at: recordingURL)
        }
        isRecording = false
        stopTimersAndWaveform()
        duration = 0
        recordingURL = nil
    }

    static func normalizedWaveformLevel(forAveragePower averagePower: Float) -> Double {
        guard averagePower.isFinite, averagePower > waveformMinimumDecibels else { return 0 }
        let decibelRange = waveformMaximumDecibels - waveformMinimumDecibels
        let normalized = (averagePower - waveformMinimumDecibels) / decibelRange
        return Double(min(1, max(0, normalized)))
    }

    func appendLocalWaveformLevel(_ normalizedLevel: Double) {
        let level = min(1, max(0, normalizedLevel))
        waveformSamples = Array(waveformSamples.dropFirst()) + [level]
        recordedWaveformLevels.append(level)
    }

    func setPCMHandler(_ handler: (@Sendable ([Float], Double) -> Void)?) {
        pcmHandler = handler
    }

    func recordingWaveform(duration: TimeInterval) -> AudioRecordingWaveform? {
        AudioRecordingWaveform(normalizedLevels: recordedWaveformLevels, duration: duration)
    }

    func resetWaveform() {
        waveformSamples = Array(repeating: 0, count: Self.waveformSampleCount)
    }

    private func startPCMInputTap(writingTo url: URL) throws {
        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate.isFinite, format.sampleRate > 0, format.channelCount > 0 else {
            throw AudioRealtimeTranscriptionError.invalidAudioFormat
        }
        let writer = try AudioRecordingFileWriter(url: url, sourceFormat: format)
        // AVAudioEngine invokes this block on its realtime queue. Constructing it
        // outside MainActor isolation prevents Swift's executor check from
        // trapping before the first microphone buffer can be processed.
        let tap = Self.makePCMInputTapHandler(
            writer: writer,
            handler: pcmHandler,
            recorder: self
        )
        input.installTap(onBus: 0, bufferSize: 2_048, format: format, block: tap)
        audioEngine = engine
        recordingWriter = writer
        engine.prepare()
        try engine.start()
    }

    // contract-implementation: message-input.recording.lifecycle
    nonisolated static func makePCMInputTapHandler(
        writer: AudioRecordingFileWriter,
        handler: (@Sendable ([Float], Double) -> Void)?,
        recorder: VoiceRecorder
    ) -> @Sendable (AVAudioPCMBuffer, AVAudioTime) -> Void {
        { [weak recorder] buffer, _ in
            _ = writer.enqueue(buffer)
            guard let samples = Self.monoSamples(from: buffer), !samples.isEmpty else { return }
            let sampleRate = buffer.format.sampleRate
            let rms = Self.normalizedRMS(samples)
            handler?(samples, sampleRate)
            Task { @MainActor [weak recorder] in
                guard let recorder, recorder.isRecording else { return }
                recorder.appendLocalWaveformLevel(rms)
            }
        }
    }

    nonisolated static func makeAACRecordingFile(
        at url: URL,
        sourceFormat: AVAudioFormat
    ) throws -> AVAudioFile {
        let fileSettings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: sourceFormat.sampleRate,
            AVNumberOfChannelsKey: Int(sourceFormat.channelCount),
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]
        return try AVAudioFile(
            forWriting: url,
            settings: fileSettings,
            commonFormat: .pcmFormatFloat32,
            interleaved: false
        )
    }

    nonisolated private static func monoSamples(from buffer: AVAudioPCMBuffer) -> [Float]? {
        guard let channels = buffer.floatChannelData else { return nil }
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        guard frameCount > 0, channelCount > 0 else { return nil }
        if channelCount == 1 {
            return Array(UnsafeBufferPointer(start: channels[0], count: frameCount))
        }
        var samples = Array(repeating: Float.zero, count: frameCount)
        let scale = Float(1) / Float(channelCount)
        for channel in 0..<channelCount {
            let source = channels[channel]
            for frame in 0..<frameCount {
                samples[frame] += source[frame] * scale
            }
        }
        return samples
    }

    nonisolated private static func normalizedRMS(_ samples: [Float]) -> Double {
        guard !samples.isEmpty else { return 0 }
        let meanSquare = samples.reduce(0.0) { partial, sample in
            let finiteSample = sample.isFinite ? Double(sample) : 0
            return partial + finiteSample * finiteSample
        } / Double(samples.count)
        // Speech captured by the device microphone commonly occupies the lower
        // portion of full scale. The multiplier keeps quiet speech visible while
        // the final clamp protects the envelope contract.
        return min(1, max(0, sqrt(meanSquare) * 8))
    }

    @discardableResult
    private func stopPCMInputTap() -> Bool {
        if let audioEngine {
            audioEngine.inputNode.removeTap(onBus: 0)
            audioEngine.stop()
            self.audioEngine = nil
        }
        let writerSucceeded = recordingWriter?.finish() ?? true
        recordingWriter = nil
        return writerSucceeded
    }

    private func stopTimersAndWaveform() {
        durationTask?.cancel()
        durationTask = nil
        resetWaveform()
    }

    #if DEBUG
    private var isUITestSimulatedRecording: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-welcome-simulated-recording")
            || ProcessInfo.processInfo.arguments.contains("--ui-test-simulated-recording")
            || isUITestGuestLocalRecording
            || isUITestFailedOutput
    }

    private var isUITestGuestLocalRecording: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-welcome-guest-local-recording")
    }

    private var isUITestFailedOutput: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-welcome-recording-output-failure")
    }

    private static func writeUITestRecording(to url: URL) -> Bool {
        try? FileManager.default.removeItem(at: url)
        guard let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4_410),
              let samples = buffer.floatChannelData?[0],
              let writer = try? AudioRecordingFileWriter(url: url, sourceFormat: format) else { return false }
        buffer.frameLength = 4_410
        for index in 0..<Int(buffer.frameLength) {
            samples[index] = sin(Float(index) * 2 * .pi * 440 / 44_100) * 0.15
        }
        return writer.enqueue(buffer) && writer.finish()
    }
    #endif
}

struct ComposerRecordingOverlay: View {
    static let recordingPanelHeight: CGFloat = 220
    private static let minimumTouchTargetSize: CGFloat = 44
    private static let waveformTrackHeight: CGFloat = 64
    private static let waveformBarSpacing: CGFloat = 2
    private static let waveformBarMaximumWidth: CGFloat = 3
    private static let waveformBarMinimumHeight: CGFloat = 2

    @ObservedObject var recorder: VoiceRecorder
    let dragOffsetX: CGFloat
    var startedFromKeyboard = false
    var liveTranscript: String? = nil
    var isRealtimeConnecting = false
    let onStop: (URL) -> Void
    let onCancel: () -> Void
    var onFailure: () -> Void = {}

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: .spacing4) {
                VStack(spacing: .spacing1) {
                    Text(recordingHeading)
                        .font(.omP.weight(.bold))
                        .foregroundStyle(Color.white)
                        .multilineTextAlignment(.center)
                        .lineLimit(1)
                        .accessibilityIdentifier("release-text")

                    Text(AppStrings.recordingShortcuts)
                        .font(.omXs.weight(.medium))
                        .foregroundStyle(Color.white.opacity(0.72))
                        .multilineTextAlignment(.center)
                        .accessibilityIdentifier("record-shortcuts")
                }

                recordingWaveform

                if isRealtimeConnecting && normalizedLiveTranscript == nil {
                    Text("•••")
                        .font(.omXs.weight(.bold))
                        .foregroundStyle(Color.white.opacity(0.72))
                        .accessibilityLabel(AppStrings.recordingActive)
                        .accessibilityIdentifier("recording-realtime-connecting")
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            HStack(spacing: .spacing4) {
                Text(formatDuration(recorder.duration))
                    .font(.omSmall.weight(.bold))
                    .foregroundStyle(Color.white)
                    .monospacedDigit()
                    .frame(minWidth: 60)
                    // RecordAudio.svelte: .timer-pill padding 6px 14px.
                    .padding(.horizontal, 14)
                    .padding(.vertical, .spacing3)
                    .background(Color.recordingTimer)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .accessibilityIdentifier("timer-pill")

                // RecordAudio.svelte switches the action separation to spacing-2 at compact widths.
                HStack(spacing: .spacing2) {
                    Button(action: onCancel) {
                        Text(AppStrings.cancelRecording)
                            .font(.omSmall.weight(.bold))
                            .foregroundStyle(Color.white)
                            .padding(.horizontal, .spacing8)
                            .padding(.vertical, .spacing4)
                            .frame(minHeight: 41)
                            .frame(minWidth: 112)
                            .background(Color.white.opacity(0.18))
                            .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                    .buttonStyle(.plain)
                    .frame(minHeight: Self.minimumTouchTargetSize)
                    .contentShape(Rectangle())
                    .accessibilityLabel(AppStrings.cancelRecording)
                    .accessibilityIdentifier("record-cancel-button")

                    Button {
                        if let url = recorder.stopRecording() {
                            onStop(url)
                        } else {
                            onFailure()
                        }
                    } label: {
                        Text(AppStrings.finishRecording)
                            .font(.omSmall.weight(.bold))
                            .foregroundStyle(Color.white)
                            .padding(.horizontal, .spacing8)
                            .padding(.vertical, .spacing4)
                            .frame(minHeight: 41)
                            .frame(minWidth: 112)
                            .background(Color.buttonPrimary)
                            .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                    .buttonStyle(.plain)
                    .frame(minHeight: Self.minimumTouchTargetSize)
                    .contentShape(Rectangle())
                    .help(Text(startedFromKeyboard ? AppStrings.pressEnterToFinishRecording : AppStrings.finishRecording))
                    .accessibilityLabel(AppStrings.finishRecording)
                    .accessibilityIdentifier("record-finish-button")
                }
                .frame(maxWidth: .infinity, alignment: .trailing)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("record-action-buttons")
            }
            .frame(minHeight: Self.minimumTouchTargetSize)
            .contentShape(Rectangle())
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("record-controls")
        }
        .padding(.top, .spacing10)
        .padding(.horizontal, .spacing10)
        // RecordAudio.svelte uses an 18px bottom inset, between spacing8 and spacing10.
        .padding(.bottom, 18)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .frame(height: Self.recordingPanelHeight)
        .background(LinearGradient.recordingOverlay)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .overlay(alignment: .topLeading) {
            Button(action: onCancel) {
                Color.clear.frame(width: 1, height: 1)
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.cancelAction)
            .accessibilityHidden(true)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("record-overlay")
    }

    private var recordingWaveform: some View {
        GeometryReader { proxy in
            let totalSpacing = Self.waveformBarSpacing * CGFloat(VoiceRecorder.waveformSampleCount - 1)
            let availableBarWidth = (proxy.size.width - totalSpacing) / CGFloat(VoiceRecorder.waveformSampleCount)
            let barWidth = min(Self.waveformBarMaximumWidth, max(1, availableBarWidth))

            HStack(spacing: Self.waveformBarSpacing) {
                ForEach(Array(recorder.waveformSamples.enumerated()), id: \.offset) { _, level in
                    Capsule()
                        .fill(Color.white)
                        .frame(
                            width: barWidth,
                            height: max(
                                Self.waveformBarMinimumHeight,
                                Self.waveformTrackHeight * max(VoiceRecorder.waveformMinimumVisibleLevel, level)
                            )
                        )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: 480)
        .frame(height: Self.waveformTrackHeight)
        .padding(.horizontal, .spacing2)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func formatDuration(_ seconds: TimeInterval) -> String {
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return String(format: "%02d:%02d", mins, secs)
    }

    private var normalizedLiveTranscript: String? {
        let transcript = liveTranscript?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return transcript.isEmpty ? nil : transcript
    }

    private var recordingHeading: String {
        recorder.error ?? normalizedLiveTranscript ?? AppStrings.recordingActive
    }
}
