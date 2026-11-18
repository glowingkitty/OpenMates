// Video call camera pacing, encoding bounds and source-frame request mapping.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.video.input-and-output, video-call.video.source-frame-provenance

import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class NativeVoiceCallCameraTests: XCTestCase {
    private let jpeg = Data([0xFF, 0xD8, 0xFF, 0xE0, 0x01, 0x02])

    private func request(_ overrides: NativeVoiceCallFrame = [:]) -> NativeVoiceCallFrame {
        var frame: NativeVoiceCallFrame = [
            "type": .string("voice_source_frame"), "call_id": .string("call-1"),
            "user_message_id": .string("user-1"), "frame_id": .string("frame-1"),
            "data": .string(jpeg.base64EncodedString()), "captured_at": .number(1_770_000_000_123),
            "created_at": .number(1_770_000_000)]
        frame.merge(overrides) { _, new in new }
        return frame
    }

    // contract-test: direct surface=gui.apple assertions=video-call.video.input-and-output
    func testFramesAreAdmittedAtMostOncePerSecond() {
        var pacer = NativeVoiceCallCameraPacer()
        XCTAssertTrue(pacer.admit(now: 10))
        XCTAssertFalse(pacer.admit(now: 10.4))
        XCTAssertFalse(pacer.admit(now: 10.99))
        XCTAssertTrue(pacer.admit(now: 11.0))
        pacer.reset()
        XCTAssertTrue(pacer.admit(now: 11.1))
    }

    // contract-test: direct surface=gui.apple assertions=video-call.video.input-and-output
    func testSizeIsBoundedTo720pWithoutUpscaling() {
        XCTAssertEqual(NativeVoiceCallCameraLimits.scaledSize(width: 1920, height: 1080).width, 1280)
        XCTAssertEqual(NativeVoiceCallCameraLimits.scaledSize(width: 1920, height: 1080).height, 720)
        XCTAssertEqual(NativeVoiceCallCameraLimits.scaledSize(width: 1080, height: 1920).height, 720)
        XCTAssertEqual(NativeVoiceCallCameraLimits.scaledSize(width: 640, height: 480).width, 640)
    }

    // contract-test: direct surface=gui.apple assertions=video-call.video.input-and-output
    func testQualityLadderStopsAtFirstJPEGWithinCapAndDropsOversizedFrames() {
        var tried: [Double] = []
        let small = NativeVoiceCallCameraLimits.firstWithinCap { quality in
            tried.append(quality)
            return Data(count: quality > 0.6 ? 300 * 1024 : 100 * 1024)
        }
        XCTAssertEqual(tried, [0.72, 0.5])
        XCTAssertEqual(small?.count, 100 * 1024)
        XCTAssertNil(NativeVoiceCallCameraLimits.firstWithinCap { _ in Data(count: 300 * 1024) })
    }

    // contract-test: direct surface=gui.apple assertions=video-call.video.input-and-output
    func testCameraFrameMessageUsesTheWireNames() {
        let frame = NativeVoiceCallCameraFrame(frameID: "f", jpeg: jpeg, capturedAt: 42, width: 1, height: 1)
        let message = frame.message(callID: "call-1")
        XCTAssertEqual(message["type"]?.string, "camera_frame")
        XCTAssertEqual(message["frame_id"]?.string, "f")
        XCTAssertEqual(message["data"]?.string, jpeg.base64EncodedString())
        XCTAssertEqual(message["captured_at"]?.number, 42)
        XCTAssertEqual(message["source"]?.string, "camera")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.video.apple-screen-share
    func testScreenFrameIsSentAsCameraFrameMarkedScreen() {
        let frame = NativeVoiceCallCameraFrame(frameID: "s", jpeg: jpeg, capturedAt: 7, width: 0, height: 0, source: "screen")
        let message = frame.message(callID: "call-1")
        XCTAssertEqual(message["type"]?.string, "camera_frame")
        XCTAssertEqual(message["source"]?.string, "screen")
        XCTAssertEqual(message["call_id"]?.string, "call-1")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.video.input-and-output
    func testPermissionErrorsUseWebCodes() {
        XCTAssertEqual(NativeVoiceCallCameraError.denied.rawValue, "camera_denied")
        XCTAssertEqual(NativeVoiceCallCameraError.missing.rawValue, "camera_missing")
        XCTAssertEqual(NativeVoiceCallCameraError.failed.rawValue, "camera_failed")
    }

    // contract-test: direct surface=gui.apple assertions=video-call.video.source-frame-provenance
    func testSourceFrameRequestPassesTheServersExactBase64Through() throws {
        let parsed = try XCTUnwrap(NativeVoiceCallSourceFrameRequest(frame: request(), expectedCallID: "call-1"))
        XCTAssertEqual(parsed.data, jpeg.base64EncodedString())
        XCTAssertEqual(parsed.source, .camera)
        XCTAssertEqual(parsed.capturedAt, 1_770_000_000_123)
        let screen = try XCTUnwrap(NativeVoiceCallSourceFrameRequest(
            frame: request(["source": .string("screen")]), expectedCallID: "call-1"))
        XCTAssertEqual(screen.source, .screen)
    }

    // contract-test: direct surface=gui.apple assertions=video-call.video.source-frame-provenance
    func testMalformedRequestsAreRefusedAndValidIdsGetAFailureAnswer() {
        XCTAssertNil(NativeVoiceCallSourceFrameRequest(frame: request(["call_id": .string("other")]), expectedCallID: "call-1"))
        let failure = NativeVoiceCallSourceFrameRequest.failureMessage(
            frame: request(["data": .string("not-jpeg")]), expectedCallID: "call-1")
        XCTAssertEqual(failure?["type"]?.string, "source_frame_failed")
        XCTAssertEqual(failure?["frame_id"]?.string, "frame-1")
        XCTAssertNil(NativeVoiceCallSourceFrameRequest.failureMessage(
            frame: request(["call_id": .string("other")]), expectedCallID: "call-1"))
    }

    // contract-test: direct surface=gui.apple assertions=video-call.video.source-frame-provenance
    func testSavedAnswerCarriesTheEmbedReferenceAndFailureAnswersOnError() async throws {
        let ok = NativeVoiceCallSourceFrames { request, _ in
            NativeVoiceCallSourceReference(embedID: "embed-1", sourceFrameID: request.frameID,
                                           capturedAt: request.capturedAt, sourceCallID: request.callID, source: request.source)
        }
        let saved = await ok.answer(frame: request(), callID: "call-1", chatID: "chat-1")
        XCTAssertEqual(saved?["type"]?.string, "source_frame_saved")
        let reference = saved?["embed_reference"]?.object
        XCTAssertEqual(reference?["embed_id"]?.string, "embed-1")
        XCTAssertEqual(reference?["type"]?.string, "image")
        XCTAssertEqual(reference?["source"]?.string, "camera")
        struct Boom: Error {}
        let bad = NativeVoiceCallSourceFrames { _, _ in throw Boom() }
        let failed = await bad.answer(frame: request(), callID: "call-1", chatID: "chat-1")
        XCTAssertEqual(failed?["type"]?.string, "source_frame_failed")
    }
}
