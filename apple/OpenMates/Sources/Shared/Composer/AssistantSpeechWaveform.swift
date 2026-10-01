// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
import Foundation
import AudioToolbox
import AVFoundation

// Web: utils/audioWaveform.ts. Decode provider bytes in memory only, then retain
// the compact RMS envelope. Decrypted audio never needs a temporary disk file.
enum AssistantSpeechWaveform {
    static func decode(_ data: Data) -> [Float] {
        let holder = NSData(data: data)
        let pointer = Unmanaged.passRetained(holder).toOpaque()
        defer { Unmanaged<NSData>.fromOpaque(pointer).release() }
        var file: AudioFileID?
        let result = AudioFileOpenWithCallbacks(pointer, { context, position, count, output, actual in
            let data = Unmanaged<NSData>.fromOpaque(context).takeUnretainedValue()
            guard position >= 0, position <= data.length else { return kAudioFilePositionError }
            let length = min(Int(count), data.length - Int(position))
            if length > 0 { memcpy(output, data.bytes.advanced(by: Int(position)), length) }
            actual.pointee = UInt32(length)
            return noErr
        }, nil, { context in
            return Int64(Unmanaged<NSData>.fromOpaque(context).takeUnretainedValue().length)
        }, nil, 0, &file)
        guard result == noErr, let file else { return [] }
        defer { AudioFileClose(file) }
        var decoder: ExtAudioFileRef?
        guard ExtAudioFileWrapAudioFileID(file, false, &decoder) == noErr, let decoder else { return [] }
        defer { ExtAudioFileDispose(decoder) }
        var format = AudioStreamBasicDescription(mSampleRate: 22050, mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked,
            mBytesPerPacket: 4, mFramesPerPacket: 1, mBytesPerFrame: 4,
            mChannelsPerFrame: 1, mBitsPerChannel: 32, mReserved: 0)
        guard ExtAudioFileSetProperty(decoder, kExtAudioFileProperty_ClientDataFormat,
            UInt32(MemoryLayout.size(ofValue: format)), &format) == noErr else { return [] }
        var levels: [Float] = []
        var decoded = [Float](repeating: 0, count: 1024)
        // Provider segment length is bounded; cap decode work for malformed media.
        for _ in 0..<6500 {
            var frames: UInt32 = 1024
            let success = decoded.withUnsafeMutableBytes { bytes -> Bool in
                var buffers = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 1,
                    mDataByteSize: UInt32(bytes.count), mData: bytes.baseAddress))
                return ExtAudioFileRead(decoder, &frames, &buffers) == noErr
            }
            guard success else { return [] }
            if frames == 0 { break }
            levels.append(contentsOf: decoded.prefix(Int(frames)))
        }
        return levels
    }
    static func samples(_ data: Data) -> [Double] {
        let levels = decode(data)
        guard !levels.isEmpty else { return [] }
        return (0..<128).map { index in
            let start = index * levels.count / 128
            let end = min(levels.count, max(start + 1, (index + 1) * levels.count / 128))
            let squareSum = levels[start..<end].reduce(0.0) { $0 + Double($1 * $1) }
            return max(4, (sqrt(squareSum / Double(end - start)) * 100).rounded())
        }
    }
    static func buffer(_ data: Data) throws -> AVAudioPCMBuffer {
        let frames = decode(data)
        guard !frames.isEmpty, let format = AVAudioFormat(standardFormatWithSampleRate: 22050, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames.count)),
              let channel = buffer.floatChannelData?[0] else { throw CocoaError(.fileReadCorruptFile) }
        buffer.frameLength = AVAudioFrameCount(frames.count)
        frames.withUnsafeBufferPointer { source in
            if let base = source.baseAddress { channel.update(from: base, count: frames.count) }
        }
        return buffer
    }
}
