// Deterministic live-waveform tests for the native Apple voice recorder.
// These tests use synthetic decibel values and never access microphone data.
// They lock the rendered web sampling, normalization, and rolling-buffer contract.
// Cleanup assertions ensure stopped recordings retain no waveform state.
// See RecordAudio.svelte for the cross-platform source of truth.

import AVFoundation
import XCTest
@testable import OpenMates

@MainActor
final class VoiceRecorderTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testWaveformContractMatchesRenderedWebConstants() {
        XCTAssertEqual(VoiceRecorder.waveformSampleCount, 64)
        XCTAssertEqual(VoiceRecorder.waveformSampleInterval, 0.05, accuracy: 0.000_1)
        XCTAssertEqual(VoiceRecorder.waveformMinimumVisibleLevel, 0.04, accuracy: 0.000_1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testAveragePowerNormalizationMatchesRenderedWebRange() {
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -160), 0)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -46), 0)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -32), 0.5, accuracy: 0.000_1)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -18), 1)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: 0), 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testWaveformBufferRollsLeftAndKeepsSixtyFourSamples() throws {
        let recorder = VoiceRecorder()

        for index in 0...64 {
            recorder.appendLocalWaveformLevel(Double(index) / 64)
        }

        XCTAssertEqual(recorder.waveformSamples.count, 64)
        XCTAssertEqual(try XCTUnwrap(recorder.waveformSamples.first), 1.0 / 64.0, accuracy: 0.000_1)
        XCTAssertEqual(try XCTUnwrap(recorder.waveformSamples.last), 1, accuracy: 0.000_1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testStopAndCancelClearEveryWaveformSample() {
        let recorder = VoiceRecorder()
        recorder.appendLocalWaveformLevel(0.75)

        XCTAssertNil(recorder.stopRecording())
        XCTAssertEqual(recorder.waveformSamples, Array(repeating: 0, count: 64))

        recorder.appendLocalWaveformLevel(0.5)
        recorder.cancelRecording()

        XCTAssertEqual(recorder.waveformSamples, Array(repeating: 0, count: 64))
        XCTAssertEqual(recorder.duration, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testMicrophoneTapProcessesPCMOffMainActor() async throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("voice-recorder-tap-\(UUID().uuidString).m4a")
        defer { try? FileManager.default.removeItem(at: url) }
        let format = try XCTUnwrap(AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 44_100,
            channels: 1,
            interleaved: false
        ))
        let writer = try AudioRecordingFileWriter(url: url, sourceFormat: format)
        let receivedPCM = expectation(description: "audio tap forwards PCM from the realtime queue")
        let tap = VoiceRecorder.makePCMInputTapHandler(
            writer: writer,
            handler: { samples, sampleRate in
                XCTAssertFalse(Thread.isMainThread)
                XCTAssertEqual(samples.count, 512)
                XCTAssertEqual(sampleRate, 44_100)
                receivedPCM.fulfill()
            },
            recorder: VoiceRecorder()
        )

        DispatchQueue(label: "org.openmates.tests.audio-tap").async {
            guard let format = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: 44_100,
                channels: 1,
                interleaved: false
            ), let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 512) else {
                XCTFail("Could not construct the synthetic microphone buffer")
                receivedPCM.fulfill()
                return
            }
            buffer.frameLength = 512
            buffer.floatChannelData?[0][0] = 0.2
            tap(buffer, AVAudioTime())
        }

        await fulfillment(of: [receivedPCM], timeout: 5)
        XCTAssertTrue(writer.finish())
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testSyntheticPCMProducesNonemptyPlayableM4A() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("voice-recorder-\(UUID().uuidString).m4a")
        defer { try? FileManager.default.removeItem(at: url) }

        let sampleRate = 44_100.0
        let frameCount = AVAudioFrameCount(sampleRate / 4)
        let format = try XCTUnwrap(AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: 1,
            interleaved: false
        ))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount))
        buffer.frameLength = frameCount
        let channel = try XCTUnwrap(buffer.floatChannelData?[0])
        for frame in 0..<Int(frameCount) {
            channel[frame] = Float(sin(2 * Double.pi * 440 * Double(frame) / sampleRate) * 0.2)
        }

        var output: AudioRecordingFileWriter? = try AudioRecordingFileWriter(url: url, sourceFormat: format)
        XCTAssertTrue(output?.enqueue(buffer) == true)
        XCTAssertTrue(output?.finish() == true)
        output = nil

        let fileSize = try XCTUnwrap(url.resourceValues(forKeys: [.fileSizeKey]).fileSize)
        XCTAssertGreaterThan(fileSize, 0)
        let reopened = try AVAudioFile(forReading: url)
        XCTAssertGreaterThan(reopened.length, 0)
        XCTAssertGreaterThan(reopened.fileFormat.sampleRate, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testSyntheticStereoPCMProducesNonemptyPlayableM4A() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("voice-recorder-stereo-\(UUID().uuidString).m4a")
        defer { try? FileManager.default.removeItem(at: url) }

        let sampleRate = 48_000.0
        let frameCount: AVAudioFrameCount = 4_800
        let format = try XCTUnwrap(AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: 2,
            interleaved: false
        ))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount))
        buffer.frameLength = frameCount
        let channels = try XCTUnwrap(buffer.floatChannelData)
        for frame in 0..<Int(frameCount) {
            channels[0][frame] = Float(sin(2 * Double.pi * 330 * Double(frame) / sampleRate) * 0.15)
            channels[1][frame] = Float(sin(2 * Double.pi * 550 * Double(frame) / sampleRate) * 0.15)
        }

        var output: AudioRecordingFileWriter? = try AudioRecordingFileWriter(url: url, sourceFormat: format)
        XCTAssertTrue(output?.enqueue(buffer) == true)
        XCTAssertTrue(output?.finish() == true)
        output = nil

        let reopened = try AVAudioFile(forReading: url)
        XCTAssertGreaterThan(reopened.length, 0)
        XCTAssertEqual(reopened.fileFormat.channelCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testWriterRejectsInterleavedPCMInsteadOfReadingInvalidChannelPointers() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("voice-recorder-interleaved-\(UUID().uuidString).m4a")
        defer { try? FileManager.default.removeItem(at: url) }
        let format = try XCTUnwrap(AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 2,
            interleaved: true
        ))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 480))
        buffer.frameLength = 480

        let writer = try AudioRecordingFileWriter(url: url, sourceFormat: format)
        XCTAssertFalse(writer.enqueue(buffer))
        XCTAssertFalse(writer.finish(), "Rejected hardware layouts must make Finish fail safely")
    }
}
