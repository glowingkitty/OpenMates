// Focused contract coverage for the native composer recording card's stored
// payload, user-facing model metadata, and waveform playback progress.

import XCTest
@testable import OpenMates

@MainActor
final class ComposerAudioPreviewContentTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testStoredRecordingPayloadDrivesWebParityContent() {
        let content = ComposerAudioPreviewContent(data: [
            "filename": AnyCodable("recording_7bf47044-0c6f-4880.m4a"),
            "title": AnyCodable("Sprint voice note"),
            "duration": AnyCodable(42.4),
            "transcript": AnyCodable("Fallback transcript"),
            "transcript_original": AnyCodable("Raw realtime transcript"),
            "transcript_corrected": AnyCodable("Corrected transcript"),
            "use_corrected": AnyCodable(true),
            "model": AnyCodable("voxtral-mini-transcribe-realtime-2602"),
            "waveform": AnyCodable([
                "version": 1,
                "kind": "rms-envelope",
                "samples": [0, 25, 100]
            ] as [String: Any])
        ])

        XCTAssertEqual(content.title, "Sprint voice note")
        XCTAssertEqual(content.transcript, "Corrected transcript")
        XCTAssertEqual(content.formattedDuration, "0:42")
        XCTAssertEqual(content.modelDisplayName, "Voxtral Mini Realtime")
        XCTAssertEqual(content.waveformSamples ?? [], [0.06, 0.25, 1.0])
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testFilenameAndUnknownModelIdsStayOutOfUserFacingContent() {
        let content = ComposerAudioPreviewContent(data: [
            "filename": AnyCodable("recording_uuid.m4a"),
            "transcript_original": AnyCodable("Raw transcript"),
            "transcript_corrected": AnyCodable("Corrected transcript"),
            "use_corrected": AnyCodable(false),
            "model": AnyCodable("internal-model-routing-id")
        ])

        XCTAssertNil(content.title)
        XCTAssertEqual(content.transcript, "Raw transcript")
        XCTAssertNil(content.formattedDuration)
        XCTAssertNil(content.modelDisplayName)
        XCTAssertNil(
            ComposerAudioPreviewContent(
                data: nil,
                provisionalTranscript: "recording_uuid.m4a"
            ).transcript
        )
        XCTAssertNil(
            ComposerAudioPreviewContent(
                data: nil,
                provisionalTranscript: AppStrings.audioRecording
            ).transcript
        )
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testProvisionalTranscriptFillsPendingRecordingWithoutOverridingStoredContent() {
        let pending = ComposerAudioPreviewContent(
            data: nil,
            provisionalTranscript: "Raw realtime transcript"
        )
        let stored = ComposerAudioPreviewContent(
            data: ["transcript_corrected": AnyCodable("Corrected transcript")],
            provisionalTranscript: "Raw realtime transcript"
        )
        let blank = ComposerAudioPreviewContent(data: nil, provisionalTranscript: "   ")

        XCTAssertEqual(pending.transcript, "Raw realtime transcript")
        XCTAssertEqual(stored.transcript, "Corrected transcript")
        XCTAssertNil(blank.transcript)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testPlaybackProgressIsClampedForWaveformPlayhead() {
        XCTAssertEqual(ComposerAudioPlaybackProgress.normalized(currentTime: 5, duration: 20), 0.25)
        XCTAssertEqual(ComposerAudioPlaybackProgress.normalized(currentTime: -1, duration: 20), 0)
        XCTAssertEqual(ComposerAudioPlaybackProgress.normalized(currentTime: 30, duration: 20), 1)
        XCTAssertEqual(ComposerAudioPlaybackProgress.normalized(currentTime: 5, duration: 0), 0)
        XCTAssertEqual(
            ComposerAudioWaveformGeometry.barWidth(containerWidth: 300, sampleCount: 128),
            1.3515625
        )
    }
}
