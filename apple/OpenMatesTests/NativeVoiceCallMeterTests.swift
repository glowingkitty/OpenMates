// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.activity-status, video-call.audio.single-owner
import AVFoundation
import XCTest
@testable import OpenMates

/// Level metering of the buffers already flowing through the call's audio engine.
final class NativeVoiceCallMeterTests: XCTestCase {
    private final class Clock: @unchecked Sendable { var time: TimeInterval = 100 }
    private final class Received: @unchecked Sendable { var frames: [[Float]] = [] }

    private func tone(amplitude: Float, count: Int = 1_024) -> [Float] {
        (0..<count).map { amplitude * sin(Float($0) * 0.2) }
    }
    private func level(_ samples: [Float]) -> Float {
        samples.withUnsafeBufferPointer { NativeVoiceCallLevelMeter.level(of: $0) }
    }
    private func make(_ clock: Clock, _ received: Received) -> NativeVoiceCallLevelMeter {
        NativeVoiceCallLevelMeter(now: { clock.time }, sink: { received.frames.append($0) })
    }

    // contract-test: direct surface=gui.apple assertions=video-call.chat.activity-status
    func testSyntheticPCMLevelsFollowAmplitudeAndSilenceIsFlat() {
        XCTAssertEqual(level([Float](repeating: 0, count: 1_024)), 0)
        XCTAssertEqual(level([]), 0)
        XCTAssertEqual(level([Float](repeating: .nan, count: 8)), 0)
        let quiet = level(tone(amplitude: 0.05)), loud = level(tone(amplitude: 0.5))
        XCTAssertGreaterThan(quiet, 0)
        XCTAssertGreaterThan(loud, quiet)
        XCTAssertLessThanOrEqual(loud, 1)
        let clock = Clock(), received = Received()
        let meter = make(clock, received)
        meter.submit(.playback, level: 0)
        XCTAssertEqual(received.frames.last, [0], "idle is a flat baseline")
    }

    // contract-test: direct surface=gui.apple assertions=video-call.chat.activity-status
    func testMicrophoneAndPlaybackLevelsReachBarsAndMutedMicContributesNothing() {
        let clock = Clock(), received = Received()
        let meter = make(clock, received)
        meter.submit(.microphone, level: level(tone(amplitude: 0.3)))
        clock.time += 0.06
        meter.submit(.playback, level: level(tone(amplitude: 0.4)))
        clock.time += 0.06
        meter.submit(.microphone, level: 0) // muted tap reports zero
        XCTAssertEqual(received.frames.last?.count, 3)
        XCTAssertGreaterThan(received.frames.last?[0] ?? 0, 0)
        XCTAssertGreaterThan(received.frames.last?[1] ?? 0, 0)
        XCTAssertEqual(received.frames.last?[2], 0)
    }

    // contract-test: direct surface=gui.apple assertions=video-call.chat.activity-status
    func testThrottleCoalescesBuffersToTwentyHertzAndBoundsHistory() {
        let clock = Clock(), received = Received()
        let meter = make(clock, received)
        meter.submit(.microphone, level: 0.2)
        for step in 1...4 { clock.time += 0.01; meter.submit(.microphone, level: Float(step) / 10) }
        XCTAssertEqual(received.frames.count, 1, "buffers inside 50 ms do not emit")
        clock.time += 0.02
        meter.submit(.playback, level: 0.1)
        XCTAssertEqual(received.frames.count, 2)
        XCTAssertEqual(received.frames.last?.last, 0.4, "coalesced to the maximum")
        for _ in 0..<100 { clock.time += 0.06; meter.submit(.microphone, level: 0.5) }
        XCTAssertEqual(received.frames.last?.count, NativeVoiceCallLevelMeter.barCount)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.single-owner
    /// AVFoundation runs player completions and node taps on its own audio
    /// threads. Build 100 crashed there: closures written inside a @MainActor
    /// type trap under Swift 6 when called off the main actor. The factories
    /// must run from any thread and reach the main actor only through a hop.
    func testAudioThreadCallbacksRunOffTheMainThreadAndHopToTheMainActor() {
        let completed = expectation(description: "played-back completion reached the main actor")
        let handler = NativeAudioCallbacks.playedBack {
            XCTAssertTrue(Thread.isMainThread)
            completed.fulfill()
        }
        let received = Received(), clock = Clock()
        let meter = make(clock, received)
        let tap = NativeVoiceCallAppleAudio.makePlaybackTap(meter: meter)
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000, channels: 1, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 1_024)!
        buffer.frameLength = 1_024
        let samples = tone(amplitude: 0.4)
        for index in samples.indices { buffer.floatChannelData![0][index] = samples[index] }
        let tapped = expectation(description: "playback tap ran on an audio-like thread")
        DispatchQueue.global(qos: .userInteractive).async {
            XCTAssertFalse(Thread.isMainThread)
            handler(.dataPlayedBack)
            tap(buffer, AVAudioTime(sampleTime: 0, atRate: 24_000))
            tapped.fulfill()
        }
        wait(for: [tapped, completed], timeout: 5)
        XCTAssertGreaterThan(received.frames.last?.last ?? 0, 0, "the tap metered the buffer")
    }
}
