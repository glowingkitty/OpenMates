// Apple voice call parity audit: microphone permission refusal and call-turn speech admission.
// Web source: frontend/packages/ui/src/services/voiceCall.ts (`microphone_denied`).
// Specification: specifications/features/video-call/specification.yml
// Deterministic evidence only: no real microphone prompt, speaker or Bluetooth route is exercised.
import XCTest
@testable import OpenMates

@MainActor
final class VoiceCallParityAuditTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.audio.single-owner
    func testRefusedMicrophonePermissionHasItsOwnLocalizedError() {
        XCTAssertEqual(AppStrings.nativeCallError(.microphoneDenied), AppStrings.nativeCall("microphone_denied"))
        XCTAssertNotEqual(AppStrings.nativeCallError(.microphoneDenied), AppStrings.nativeCallError(.audioUnavailable))
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.complete-turn-admission
    func testSpeechAdmissionFollowsCallIdentityNotTurnIdentity() {
        // A resumed turn (after a Memory approval) is tagged with the same call id and is admitted.
        XCTAssertTrue(NativeVoiceCallSpeechAdmission.permits(taggedCallID: "call-1", activeCallID: "call-1"))
        XCTAssertFalse(NativeVoiceCallSpeechAdmission.permits(taggedCallID: "call-1", activeCallID: "call-2"))
        XCTAssertFalse(NativeVoiceCallSpeechAdmission.permits(taggedCallID: "call-1", activeCallID: nil))
        XCTAssertTrue(NativeVoiceCallSpeechAdmission.permits(taggedCallID: nil, activeCallID: "call-1"))
    }
}
