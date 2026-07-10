// Deterministic live-waveform tests for the native Apple voice recorder.
// These tests use synthetic decibel values and never access microphone data.
// They lock the rendered web sampling, normalization, and rolling-buffer contract.
// Cleanup assertions ensure stopped recordings retain no waveform state.
// See RecordAudio.svelte for the cross-platform source of truth.

import XCTest
@testable import OpenMates

@MainActor
final class VoiceRecorderTests: XCTestCase {
    func testWaveformContractMatchesRenderedWebConstants() {
        XCTAssertEqual(VoiceRecorder.waveformSampleCount, 64)
        XCTAssertEqual(VoiceRecorder.waveformSampleInterval, 0.05, accuracy: 0.000_1)
        XCTAssertEqual(VoiceRecorder.waveformMinimumVisibleLevel, 0.04, accuracy: 0.000_1)
    }

    func testAveragePowerNormalizationMatchesRenderedWebRange() {
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -160), 0)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -46), 0)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -32), 0.5, accuracy: 0.000_1)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: -18), 1)
        XCTAssertEqual(VoiceRecorder.normalizedWaveformLevel(forAveragePower: 0), 1)
    }

    func testWaveformBufferRollsLeftAndKeepsSixtyFourSamples() {
        let recorder = VoiceRecorder()

        for index in 0...64 {
            recorder.recordWaveformSample(normalizedLevel: Double(index) / 64)
        }

        XCTAssertEqual(recorder.waveformSamples.count, 64)
        XCTAssertEqual(recorder.waveformSamples.first, 1.0 / 64.0, accuracy: 0.000_1)
        XCTAssertEqual(recorder.waveformSamples.last, 1, accuracy: 0.000_1)
    }

    func testWaveformResetClearsEverySample() {
        let recorder = VoiceRecorder()
        recorder.recordWaveformSample(normalizedLevel: 0.75)

        recorder.resetWaveform()

        XCTAssertEqual(recorder.waveformSamples, Array(repeating: 0, count: 64))
    }
}
