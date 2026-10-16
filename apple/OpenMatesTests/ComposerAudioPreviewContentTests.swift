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

@MainActor
final class ChatDraftPreviewFormattingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
    func testSerializedAndTruncatedAudioReferencesBecomeReadableWithoutLosingText() {
        let source = "Before ```json\n{\"type\":\"audio\",\"embed_id\":\"synthetic-audio\"}\n``` after"
        XCTAssertEqual(ChatDraftPreviewFormatter.format(source), "Before [Audio] after")
        XCTAssertEqual(ChatDraftPreviewFormatter.format("```json\n{\"type\":\"audio\",\"embed_id\":\"synthetic"), "[Audio]")
        XCTAssertEqual(ChatDraftPreviewFormatter.format("{\"type\":\"image\",\"embed_id\":\"synthetic"), "[Image]")
        XCTAssertEqual(ChatDraftPreviewFormatter.format("Before {\"embed_id\":\"synthetic\",\"type\":\"image\"} after"), "Before [Image] after")
        XCTAssertEqual(ChatDraftPreviewFormatter.format("Read [report](embed:synthetic) please"), "Read [Embed] please")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
    func testStructuredDocumentsPreserveTextAndEmbedOrderIncludingLocalAttachments() {
        let tiptap = #"{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Before "},{"type":"embed","attrs":{"type":"audio"}},{"type":"text","text":" after"}]},{"type":"paragraph","content":[{"type":"embed","attrs":{"type":"image"}},{"type":"text","text":" describe it"}]}]}"#
        XCTAssertEqual(ChatDraftPreviewFormatter.format(tiptap), "Before [Audio] after [Image] describe it")
        let native = #"{"version":1,"nodes":[{"kind":"text","source":"Before "},{"kind":"embed","embedType":"audio-recording"},{"kind":"text","source":" after"},{"kind":"hardBreak"},{"kind":"mention","displayLabel":"@Synthetic"}]}"#
        XCTAssertEqual(ChatDraftPreviewFormatter.format(native), "Before [Audio] after @Synthetic")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
    func testOrdinaryTextAndJSONRemainVisible() {
        XCTAssertEqual(ChatDraftPreviewFormatter.format("  An ordinary\n draft [Audio]  "), "An ordinary draft [Audio]")
        let ordinaryJSON = #"{"type":"audio","message":"Discuss this JSON"}"#
        XCTAssertEqual(ChatDraftPreviewFormatter.format(ordinaryJSON), ordinaryJSON)
        XCTAssertEqual(ChatDraftPreviewFormatter.format("Please explain {\"count\":2} today"), "Please explain {\"count\":2} today")
        XCTAssertEqual(ChatDraftPreviewFormatter.format(nil), "")
        XCTAssertEqual(ChatDraftPreviewFormatter.format(" \n "), "")
    }
}
