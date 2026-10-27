// Editable draft transcription from local recording files, including Watch 44.1kHz M4A.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context
import AVFoundation
import Foundation

/// Shared file wrapper. A Watch-specific protocol can adopt this type in its own target.
/// It has no network transport or cloud fallback. Use a fresh runtime for each recording.
actor WhistleRecordingDraftTranscriber {
    private let makeRuntime: @Sendable () async throws -> any LocalPCMTranscribing
    private var active: (any LocalPCMTranscribing)?
    private var generation: UInt64 = 0
    private var running = false

    init(makeRuntime: @escaping @Sendable () async throws -> any LocalPCMTranscribing = {
        try WhistlePCMRuntime.bundled()
    }) { self.makeRuntime = makeRuntime }

    func transcribe(fileURL: URL) async throws -> String {
        guard !running else { throw LocalSpeechRuntimeError.busy }
        running = true
        defer { active = nil; running = false }
        let token = generation
        let runtime = try await makeRuntime()
        active = runtime
        do {
            try checkActive(token)
            let decoder = WhistlePCMFileDecoder(url: fileURL)
            var text: [String] = []
            while let samples = try await decoder.nextWindow() {
                try checkActive(token)
                let segment = try await runtime.transcribe(samples)
                try checkActive(token)
                if !segment.isEmpty { text.append(segment) }
            }
            try checkActive(token)
            await runtime.unload()
            try checkActive(token)
            return text.joined(separator: " ")
        } catch {
            await runtime.unload()
            if error is CancellationError { throw CancellationError() }
            if let category = error as? LocalSpeechRuntimeError { throw category }
            throw LocalSpeechRuntimeError.invalidOutput
        }
    }

    func cancel() async {
        generation &+= 1
        await active?.unload()
    }

    private func checkActive(_ token: UInt64) throws {
        try Task.checkCancellation()
        guard generation == token else { throw CancellationError() }
    }
}

/// Actor-isolated AVAudioFile/AVAudioConverter keep decode work off the UI executor.
/// At most one 20-second mono window plus a 4096-frame source buffer is retained here.
private actor WhistlePCMFileDecoder {
    private let url: URL
    private var file: AVAudioFile?
    private var converter: AVAudioConverter?
    private var finished = false
    private let windowFrames: AVAudioFrameCount = 16_000 * 20

    init(url: URL) { self.url = url }

    func nextWindow() throws -> [Float]? {
        try Task.checkCancellation()
        if finished { return nil }
        do {
            if file == nil {
                let source = try AVAudioFile(forReading: url, commonFormat: .pcmFormatFloat32, interleaved: false)
                guard source.processingFormat.sampleRate > 0, source.processingFormat.channelCount > 0,
                      let output = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000,
                                                 channels: 1, interleaved: false),
                      let conversion = AVAudioConverter(from: source.processingFormat, to: output) else {
                    throw LocalSpeechRuntimeError.invalidRequest
                }
                // AVAudioConverter defaults to remapping, which can discard a
                // stereo channel. Mix every input channel into the mono output.
                conversion.downmix = true
                file = source; converter = conversion
            }
            guard let file, let converter,
                  let output = AVAudioPCMBuffer(pcmFormat: converter.outputFormat, frameCapacity: windowFrames) else {
                throw LocalSpeechRuntimeError.invalidOutput
            }
            var inputFailure: Error?
            var conversionFailure: NSError?
            let status = converter.convert(to: output, error: &conversionFailure) { requested, state in
                if file.framePosition >= file.length { state.pointee = .endOfStream; return nil }
                let frames = min(requested, 4_096)
                guard let input = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames) else {
                    state.pointee = .noDataNow; inputFailure = LocalSpeechRuntimeError.invalidOutput; return nil
                }
                do {
                    try file.read(into: input, frameCount: frames)
                    state.pointee = input.frameLength > 0 ? .haveData : .endOfStream
                    return input.frameLength > 0 ? input : nil
                } catch { inputFailure = error; state.pointee = .noDataNow; return nil }
            }
            guard inputFailure == nil, conversionFailure == nil, status != .error else {
                throw LocalSpeechRuntimeError.invalidOutput
            }
            if status == .endOfStream { finished = true }
            guard output.frameLength > 0 else {
                if finished { self.file = nil; self.converter = nil; return nil }
                throw LocalSpeechRuntimeError.invalidOutput
            }
            guard let channel = output.floatChannelData?[0] else { throw LocalSpeechRuntimeError.invalidOutput }
            let result = Array(UnsafeBufferPointer(start: channel, count: Int(output.frameLength)))
            guard result.allSatisfy(\.isFinite) else { throw LocalSpeechRuntimeError.invalidOutput }
            return result.map { min(1, max(-1, $0)) }
        } catch {
            finished = true; file = nil; converter = nil
            if error is CancellationError { throw CancellationError() }
            if let category = error as? LocalSpeechRuntimeError { throw category }
            throw LocalSpeechRuntimeError.invalidOutput
        }
    }
}
