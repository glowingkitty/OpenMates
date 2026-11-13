// Specification: specifications/features/video-call/specification.yml
// Web source: frontend/packages/ui/src/services/assistantSpeechController.ts,
// assistantSpeechStream.ts, assistantSpeechQueue.ts (live-call turn track).
// Deterministic receiver evidence with an injected sink: these tests do not prove
// MP3 decoding, gapless output, echo cancellation or the 1.25x tempo on hardware.
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class SpeechSinkFixture: NativeVoiceCallSpeechSink {
    var opens = 0, stops = 0, finishes = 0
    var appended: [Data] = []
    var position = 0
    private var events: (@MainActor (NativeVoiceCallSpeechSinkEvent) -> Void)?
    func open(_ events: @escaping @MainActor (NativeVoiceCallSpeechSinkEvent) -> Void) throws {
        opens += 1; self.events = events
    }
    func append(_ mp3: Data) throws { appended.append(mp3) }
    func finish() throws { finishes += 1 }
    func stop() { stops += 1; events = nil }
    var sourcePositionMilliseconds: Int { position }
    func emit(_ event: NativeVoiceCallSpeechSinkEvent) { events?(event) }
}

@MainActor
final class NativeVoiceCallSpeechTests: XCTestCase {
    private let chat = "00000000-0000-4000-8000-000000000001"
    private let call = "00000000-0000-4000-8000-0000000000ca"
    private let message = "assistant-message-1"
    private let track = String(repeating: "ab", count: 32)
    private let waitingID = "00000000-0000-4000-8000-0000000000aa"
    private let clause = String(repeating: "cd", count: 32)
    private let attempt = "6f1c2e8a-1b2c-4d3e-8f4a-0123456789ab"

    private func makeReceiver() -> (NativeVoiceCallSpeechReceiver, SpeechSinkFixture) {
        // Timers never fire: a cancelled sleep returns before the timeout action.
        let receiver = NativeVoiceCallSpeechReceiver(sleep: { _ in throw CancellationError() })
        let sink = SpeechSinkFixture()
        receiver.sink = sink
        receiver.setCallOwner(chatID: chat, callID: call)
        return (receiver, sink)
    }

    private func frame(_ phase: String, _ index: Int, kind: String = "voice_prose_turn", segment: String? = nil,
                       sequence: Int? = nil, message: String? = nil, callID: String? = nil, attempt: String? = nil,
                       extra: [String: Any] = [:]) -> [String: Any] {
        var fields: [String: Any] = [
            "chat_id": chat, "message_id": message ?? self.message, "voice_call_id": callID ?? call,
            "segment_id": segment ?? track, "kind": kind, "sequence": sequence ?? (kind == "waiting_confirmation" ? -1 : 0),
            "mime_type": "audio/mpeg", "attempt_id": attempt ?? self.attempt, "source_version": 1,
            "execution_version": 1, "phase": phase, "chunk_index": index,
        ]
        if phase == "chunk" { fields["audio_data"] = Data([UInt8(index + 1), 0xFF, 0xFB]).base64EncodedString() }
        for (key, value) in extra { fields[key] = value }
        return fields
    }

    private func turnStatus(_ status: String = "queued", message: String? = nil) -> [String: Any] {
        ["chat_id": chat, "message_id": message ?? self.message, "voice_call_id": call, "segment_id": track,
         "kind": "voice_prose_turn", "sequence": 0, "source_version": 1, "execution_version": 1, "status": status]
    }

    private func waitingStatus() -> [String: Any] {
        ["chat_id": chat, "message_id": message, "voice_call_id": call, "segment_id": waitingID,
         "kind": "waiting_confirmation", "sequence": -1, "source_version": 1, "execution_version": 1, "status": "ready"]
    }

    private func sealStatus() -> [String: Any] {
        ["chat_id": chat, "message_id": message, "voice_call_id": call, "status": "sealed", "source_version": 1,
         "turn_track_id": track,
         "segments": [["segment_id": clause, "sequence": 0, "kind": "voice_prose_clause", "source_version": 1]]]
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testFrameValidationMirrorsWebAudioEventGuard() {
        XCTAssertNotNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0)))
        XCTAssertNotNil(NativeVoiceCallSpeechAudioFrame(frame("start", 0, kind: "waiting_confirmation", segment: waitingID)))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, extra: ["mime_type": "audio/ogg"])))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, attempt: "not-a-uuid")))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, sequence: 1)), "Turn track is sequence 0")
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("start", 0, kind: "waiting_confirmation", segment: waitingID, sequence: 0)))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, extra: ["sequence": true])), "Booleans are not integers")
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, extra: ["source_version": 0])))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", -1)))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, extra: ["audio_data": "AQ"])), "Non-canonical base64")
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, extra: ["audio_data": ""])))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("end", 1, extra: ["audio_data": "AQID"])), "Only chunks carry audio")
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("chunk", 0, extra: ["word_starts": [[0, 0]]])))
        XCTAssertNotNil(NativeVoiceCallSpeechAudioFrame(frame("words", 1, extra: ["word_starts": [[0, 0], [1, 300]]])))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("words", 1, extra: ["word_starts": [[1, 300], [0, 400]]])))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("words", 1, extra: ["word_starts": [[0, 400], [1, 300]]])))
        XCTAssertNil(NativeVoiceCallSpeechAudioFrame(frame("words", 1, kind: "waiting_confirmation", segment: waitingID,
                                                           extra: ["word_starts": [[0, 0]]])))
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testTurnTrackPlaysChunksInOrderAndSettlesWhenDrained() {
        let (receiver, sink) = makeReceiver()
        var changes = 0
        receiver.onChange = { changes += 1 }
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        XCTAssertEqual(sink.opens, 0, "No sink before the first bytes")
        receiver.receiveAudio(frame("chunk", 0))
        receiver.receiveAudio(frame("chunk", 1))
        XCTAssertEqual(sink.opens, 1)
        XCTAssertEqual(sink.appended, [Data([1, 0xFF, 0xFB]), Data([2, 0xFF, 0xFB])])
        sink.emit(.started)
        XCTAssertTrue(receiver.speaking)
        XCTAssertFalse(receiver.isSettled(messageID: message))
        receiver.receiveAudio(frame("end", 2))
        XCTAssertEqual(sink.finishes, 1)
        sink.position = 900
        sink.emit(.drained)
        XCTAssertFalse(receiver.speaking)
        XCTAssertTrue(receiver.isSettled(messageID: message))
        XCTAssertGreaterThan(changes, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testOutOfOrderChunkFailsTheTurnWithoutPlayingLaterBytes() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 1))
        XCTAssertTrue(sink.appended.isEmpty)
        XCTAssertTrue(receiver.isSettled(messageID: message))
        receiver.receiveAudio(frame("chunk", 0))
        XCTAssertTrue(sink.appended.isEmpty, "A failed turn track never resumes")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testDuplicateChunkStopsPlaybackAndFailsTheTurn() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 0))
        sink.emit(.started)
        receiver.receiveAudio(frame("chunk", 0))
        XCTAssertEqual(sink.appended.count, 1)
        XCTAssertGreaterThanOrEqual(sink.stops, 1)
        XCTAssertFalse(receiver.speaking)
        XCTAssertTrue(receiver.isSettled(messageID: message))
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testStreamMustStartAtChunkZeroAndEndWithAudio() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("chunk", 0))
        XCTAssertEqual(sink.opens, 0, "Chunks before start are a gap")
        XCTAssertTrue(receiver.isSettled(messageID: message))

        let (empty, emptySink) = makeReceiver()
        empty.receiveStatus(turnStatus())
        empty.receiveAudio(frame("start", 0))
        empty.receiveAudio(frame("end", 0))
        XCTAssertEqual(emptySink.finishes, 0)
        XCTAssertTrue(empty.isSettled(messageID: message), "An end without audio fails the turn")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testAudioBeforeItsStatusIsBufferedAndFlushedInOrder() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 0))
        receiver.receiveAudio(frame("chunk", 1))
        XCTAssertEqual(sink.opens, 0)
        receiver.receiveStatus(turnStatus())
        XCTAssertEqual(sink.opens, 1)
        XCTAssertEqual(sink.appended.map { $0.first }, [1, 2])
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.localized-waiting,video-call.audio.single-owner
    func testTurnAudioPreemptsTheWaitingConfirmation() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveStatus(waitingStatus())
        receiver.receiveAudio(frame("start", 0, kind: "waiting_confirmation", segment: waitingID))
        receiver.receiveAudio(frame("chunk", 0, kind: "waiting_confirmation", segment: waitingID))
        XCTAssertEqual(sink.opens, 1)
        sink.emit(.started)
        XCTAssertTrue(receiver.speaking)
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 0, attempt: "7f1c2e8a-1b2c-4d3e-8f4a-0123456789ab"))
        XCTAssertEqual(sink.appended.count, 1, "A chunk of another attempt is ignored")
        receiver.receiveAudio(frame("chunk", 0))
        XCTAssertEqual(sink.opens, 2)
        XCTAssertGreaterThanOrEqual(sink.stops, 1)
        XCTAssertFalse(receiver.speaking, "Speaking resumes only when the turn starts")
        receiver.receiveAudio(frame("chunk", 1, kind: "waiting_confirmation", segment: waitingID))
        XCTAssertEqual(sink.appended.count, 2, "The stopped waiting clip never plays again")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.single-owner
    func testBargeInStopsNowAndCancelsLateStatusesOfThatResponse() {
        let (receiver, sink) = makeReceiver()
        var cancelled: [String] = []
        receiver.cancelResponse = { _, id in cancelled.append(id) }
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 0))
        sink.emit(.started)
        receiver.stop()
        XCTAssertFalse(receiver.speaking)
        XCTAssertGreaterThanOrEqual(sink.stops, 1)
        XCTAssertTrue(receiver.isSettled(messageID: message))
        receiver.receiveAudio(frame("chunk", 1))
        XCTAssertEqual(sink.appended.count, 1)
        receiver.receiveStatus(turnStatus("queued"))
        XCTAssertEqual(cancelled, [message])
        XCTAssertEqual(sink.opens, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testCancelledTurnStatusDiscardsPlayback() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 0))
        sink.emit(.started)
        receiver.receiveStatus(turnStatus("cancelled"))
        XCTAssertFalse(receiver.speaking)
        XCTAssertTrue(receiver.isSettled(messageID: message))
        XCTAssertGreaterThanOrEqual(sink.stops, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.single-owner
    func testFramesOfAnotherCallOrAfterCallEndAreIgnored() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0, callID: "00000000-0000-4000-8000-0000000000cb"))
        receiver.receiveAudio(frame("chunk", 0, callID: "00000000-0000-4000-8000-0000000000cb"))
        XCTAssertEqual(sink.opens, 0)
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 0))
        sink.emit(.started)
        receiver.setCallOwner(chatID: nil, callID: nil)
        XCTAssertFalse(receiver.speaking)
        XCTAssertGreaterThanOrEqual(sink.stops, 1)
        receiver.receiveAudio(frame("chunk", 1))
        XCTAssertEqual(sink.appended.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testWordProgressFollowsSourcePlaybackTime() {
        let (receiver, sink) = makeReceiver()
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("words", 0, extra: ["word_starts": [[0, 0], [1, 400], [2, 800]]]))
        receiver.receiveAudio(frame("chunk", 0))
        XCTAssertEqual(receiver.spokenWordProgress,
                       .init(responseID: message, words: 0, began: false, settled: false))
        sink.emit(.started)
        sink.position = 500
        XCTAssertEqual(receiver.spokenWordProgress?.words, 2)
        sink.position = 900
        XCTAssertEqual(receiver.spokenWordProgress?.words, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.spoken-rich-response
    func testHeardBoundaryCoversSealedTurnOnlyAfterItEnded() {
        let (receiver, sink) = makeReceiver()
        XCTAssertNil(receiver.heardBoundary(messageID: message))
        receiver.receiveStatus(turnStatus())
        receiver.receiveAudio(frame("start", 0))
        receiver.receiveAudio(frame("chunk", 0))
        XCTAssertNil(receiver.heardBoundary(messageID: message), "No coverage before playback began")
        sink.emit(.started)
        receiver.receiveStatus(sealStatus())
        XCTAssertEqual(receiver.heardBoundary(messageID: message)?.completedSequences, [])
        receiver.receiveAudio(frame("end", 1))
        sink.position = 1_200
        sink.emit(.drained)
        XCTAssertEqual(receiver.heardBoundary(messageID: message),
                       .init(assistantMessageID: message, completedSequences: [0], activeSequence: nil,
                             activeOffsetMilliseconds: 0))
    }
}
