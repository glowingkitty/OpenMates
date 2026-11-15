// Call start/end transcript notice: text/time selection and the shared-core
// parse/build round trip used for the stored system message.
import XCTest
@testable import OpenMates

@MainActor
final class VoiceCallEventNoticeTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    private let en = Locale(identifier: "en_GB")
    private let date = Date(timeIntervalSince1970: 1_781_526_660) // fixed instant

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.call-events
    func testStartedAndEndedSelectDistinctText() {
        let started = VoiceCallEventNoticeModel(action: .started, createdAt: date, activeElapsedSeconds: 0)
        let ended = VoiceCallEventNoticeModel(action: .ended, createdAt: date, activeElapsedSeconds: 120)
        XCTAssertEqual(started.text, AppStrings.voiceCallEventStarted)
        XCTAssertEqual(ended.text, AppStrings.voiceCallEventEnded)
        XCTAssertNotEqual(started.text, ended.text)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.call-events
    func testLineJoinsTextAndTwoDigitTimeWithEnDash() {
        let model = VoiceCallEventNoticeModel(action: .ended, createdAt: date, activeElapsedSeconds: nil)
        let time = model.timeText(locale: en, timeZone: utc)
        XCTAssertEqual(time.count, 5)
        XCTAssertEqual(model.line(locale: en, timeZone: utc), "\(model.text) – \(time)")
    }

    // contract-test: direct surface=gui.apple assertions=video-call.chat.call-events
    func testCoreBuiltNoticeIsTheStoredSystemMessageTheTranscriptRenders() throws {
        let ended = try buildVoiceCallNotice(action: .ended, callId: "fixture-call", createdAt: 1_792_067_580,
                                             activeElapsedSeconds: 120.9)
        XCTAssertEqual(ended.messageId, "ffffffff-voice-call-fixture-call-ended")
        XCTAssertEqual(ended.contentJson, #"{"schema_version":1,"type":"voice_call","action":"ended","call_id":"fixture-call","created_at":1792067580,"active_elapsed_seconds":120}"#)
        let model = try XCTUnwrap(VoiceCallEventNoticeModel.systemMessage(ended.contentJson))
        XCTAssertEqual(model.action, .ended)
        XCTAssertEqual(model.createdAt, Date(timeIntervalSince1970: 1_792_067_580))
        XCTAssertEqual(model.activeElapsedSeconds, 120)
        XCTAssertNil(VoiceCallEventNoticeModel.systemMessage("Ordinary system text"))
        XCTAssertThrowsError(try buildVoiceCallNotice(action: .started, callId: "bad", createdAt: 1,
                                                      activeElapsedSeconds: 0))
    }
}
