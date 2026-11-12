// Web source: frontend/packages/ui/src/services/assistantSpeechStream.ts (MediaSource
// append of transient MP3 chunks) and assistantSpeechQueue.ts (1.25x playback with
// preserved pitch, source-time position for word progress).
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.audio.spoken-rich-response, video-call.audio.single-owner
//
// Gapless live-call speech output on the call's own AVAudioEngine: MP3 bytes are
// parsed with AudioFileStream, decoded with AVAudioConverter and scheduled back to
// back on one AVAudioPlayerNode. Audio stays in memory and is dropped on stop.

#if !os(watchOS)
import AudioToolbox
import AVFoundation
import Foundation

/// Incremental MP3 to PCM decoder. Not thread-safe; one owner calls it serially.
/// AudioFileStream invokes its callbacks synchronously inside `append`.
final class NativeVoiceCallMP3StreamDecoder {
    enum Failure: Error { case open, parse, format, convert }
    private let target: AVAudioFormat
    private var stream: AudioFileStreamID?
    private var sourceFormat: AVAudioFormat?
    private var converter: AVAudioConverter?
    private var decoded: [AVAudioPCMBuffer] = []
    private var failure: Failure?

    init(target: AVAudioFormat) throws {
        self.target = target
        var opened: AudioFileStreamID?
        let client = Unmanaged.passUnretained(self).toOpaque()
        let status = AudioFileStreamOpen(client, { client, stream, property, _ in
            guard let owner = NativeVoiceCallMP3StreamDecoder.owner(client) else { return }
            owner.property(stream, property)
        }, { client, byteCount, packetCount, data, descriptions in
            guard let owner = NativeVoiceCallMP3StreamDecoder.owner(client) else { return }
            owner.packets(byteCount: byteCount, packetCount: packetCount, data: data, descriptions: descriptions)
        }, kAudioFileMP3Type, &opened)
        guard status == noErr, let opened else { throw Failure.open }
        stream = opened
    }

    deinit { if let stream { AudioFileStreamClose(stream) } }

    private static func owner(_ client: UnsafeMutableRawPointer?) -> NativeVoiceCallMP3StreamDecoder? {
        guard let client else { return nil }
        return Unmanaged<NativeVoiceCallMP3StreamDecoder>.fromOpaque(client).takeUnretainedValue()
    }

    /// Returns PCM decoded so far; the decoder keeps codec state across calls.
    func append(_ bytes: Data) throws -> [AVAudioPCMBuffer] {
        guard let stream, failure == nil, !bytes.isEmpty else { throw failure ?? Failure.parse }
        let status: OSStatus = bytes.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { return OSStatus(kAudioFileStreamError_UnspecifiedError) }
            return AudioFileStreamParseBytes(stream, UInt32(raw.count), base, [])
        }
        guard status == noErr else { throw Failure.parse }
        if let failure { throw failure }
        defer { decoded = [] }
        return decoded
    }

    /// Flushes the codec tail at end of stream.
    func finish() throws -> [AVAudioPCMBuffer] {
        guard failure == nil else { throw failure ?? Failure.convert }
        guard let converter else { return [] }
        drain(converter, input: nil)
        if let failure { throw failure }
        defer { decoded = [] }
        return decoded
    }

    private func property(_ stream: AudioFileStreamID, _ property: AudioFileStreamPropertyID) {
        guard property == kAudioFileStreamProperty_ReadyToProducePackets, converter == nil else { return }
        var description = AudioStreamBasicDescription()
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        guard AudioFileStreamGetProperty(stream, kAudioFileStreamProperty_DataFormat, &size, &description) == noErr,
              let format = AVAudioFormat(streamDescription: &description),
              let converter = AVAudioConverter(from: format, to: target) else { failure = .format; return }
        sourceFormat = format
        self.converter = converter
    }

    private func packets(byteCount: UInt32, packetCount: UInt32, data: UnsafeRawPointer?,
                         descriptions: UnsafeMutablePointer<AudioStreamPacketDescription>?) {
        guard failure == nil, byteCount > 0, packetCount > 0 else { return }
        // MP3 is variable-size per packet: AudioFileStream always describes packets.
        guard let format = sourceFormat, let converter, let data, let descriptions else { failure = .format; return }
        var largest: UInt32 = 1
        for index in 0..<Int(packetCount) { largest = max(largest, descriptions[index].mDataByteSize) }
        let compressed = AVAudioCompressedBuffer(format: format, packetCapacity: AVAudioPacketCount(packetCount),
                                                 maximumPacketSize: Int(largest))
        guard Int(byteCount) <= Int(packetCount) * Int(largest), let target = compressed.packetDescriptions else {
            failure = .parse; return
        }
        compressed.data.copyMemory(from: data, byteCount: Int(byteCount))
        compressed.byteLength = byteCount
        compressed.packetCount = AVAudioPacketCount(packetCount)
        for index in 0..<Int(packetCount) { target[index] = descriptions[index] }
        drain(converter, input: compressed)
    }

    /// One compressed buffer in, as many PCM buffers out as the codec yields.
    private func drain(_ converter: AVAudioConverter, input: AVAudioCompressedBuffer?) {
        let packets = Double(input?.packetCount ?? 4)
        let framesPerPacket = Double(max(1, sourceFormat?.streamDescription.pointee.mFramesPerPacket ?? 1_152))
        let ratio = target.sampleRate / max(1, sourceFormat?.sampleRate ?? target.sampleRate)
        let capacity = AVAudioFrameCount(packets * framesPerPacket * ratio) + 4_096
        var supplied = false
        for _ in 0..<64 {
            guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { failure = .convert; return }
            var error: NSError?
            let status = converter.convert(to: output, error: &error) { _, state in
                guard let input else { state.pointee = .endOfStream; return nil }
                if supplied { state.pointee = .noDataNow; return nil }
                supplied = true; state.pointee = .haveData; return input
            }
            guard status != .error, error == nil else { failure = .convert; return }
            if output.frameLength > 0 { decoded.append(output) }
            guard status == .haveData else { return }
        }
    }
}

/// The call engine's speech output. Opened per stream; one stream plays at a time.
@MainActor
final class NativeVoiceCallSpeechEngineOutput: NativeVoiceCallSpeechSink {
    private let node = AVAudioPlayerNode()
    private let tempo = AVAudioUnitTimePitch()
    private let format: AVAudioFormat?
    private weak var engine: AVAudioEngine?
    private var decoder: NativeVoiceCallMP3StreamDecoder?
    private var events: (@MainActor (NativeVoiceCallSpeechSinkEvent) -> Void)?
    private var generation = UUID()
    private var started = false
    private var finished = false
    private var outstanding = 0
    private var scheduledFrames: AVAudioFramePosition = 0
    private var scheduledEnd: AVAudioFramePosition = 0
    private var starvedFrames: AVAudioFramePosition = 0

    init() {
        format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 44_100, channels: 1, interleaved: false)
        tempo.rate = 1.25; tempo.pitch = 0
    }

    /// Attach before the engine starts; connecting a running graph is avoided.
    func attach(to engine: AVAudioEngine) {
        guard self.engine !== engine, let format else { return }
        engine.attach(node); engine.attach(tempo)
        engine.connect(node, to: tempo, format: format)
        engine.connect(tempo, to: engine.mainMixerNode, format: format)
        self.engine = engine
    }

    func open(_ events: @escaping @MainActor (NativeVoiceCallSpeechSinkEvent) -> Void) throws {
        stop()
        guard let format, let engine, engine.isRunning else { throw NativeVoiceCallError.audioUnavailable }
        decoder = try NativeVoiceCallMP3StreamDecoder(target: format)
        self.events = events
    }

    func append(_ mp3: Data) throws {
        guard let decoder else { throw NativeVoiceCallError.audioUnavailable }
        for buffer in try decoder.append(mp3) { try schedule(buffer) }
    }

    func finish() throws {
        guard let decoder else { throw NativeVoiceCallError.audioUnavailable }
        for buffer in try decoder.finish() { try schedule(buffer) }
        finished = true
        if outstanding == 0 { complete() }
    }

    func stop() {
        generation = UUID()
        events = nil; decoder = nil
        started = false; finished = false; outstanding = 0
        scheduledFrames = 0; scheduledEnd = 0; starvedFrames = 0
        if engine != nil { node.stop() }
    }

    var sourcePositionMilliseconds: Int {
        guard started, let render = node.lastRenderTime,
              let time = node.playerTime(forNodeTime: render), time.sampleRate > 0 else { return 0 }
        let frames = min(max(0, time.sampleTime - starvedFrames), scheduledFrames)
        let milliseconds = Double(frames) / time.sampleRate * 1_000
        return milliseconds.isFinite ? Int(min(3_600_000, max(0, milliseconds))) : 0
    }

    private func schedule(_ buffer: AVAudioPCMBuffer) throws {
        guard let engine, engine.isRunning else { throw NativeVoiceCallError.audioUnavailable }
        let frames = AVAudioFramePosition(buffer.frameLength)
        guard frames > 0 else { return }
        if started, let render = node.lastRenderTime, let time = node.playerTime(forNodeTime: render),
           time.sampleTime > scheduledEnd {
            // Network starvation: the node timeline advanced over silence.
            starvedFrames += time.sampleTime - scheduledEnd
            scheduledEnd = time.sampleTime
        }
        scheduledEnd += frames; scheduledFrames += frames; outstanding += 1
        let token = generation
        node.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.generation == token else { return }
                self.outstanding = max(0, self.outstanding - 1)
                if self.finished, self.outstanding == 0 { self.complete() }
            }
        }
        if !started {
            started = true
            node.play()
            events?(.started)
        }
    }

    private func complete() {
        let events = events
        self.events = nil
        events?(.drained)
    }
}
#endif
