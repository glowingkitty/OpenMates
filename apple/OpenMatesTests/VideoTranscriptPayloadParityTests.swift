// Focused unit coverage for persisted web-originated video transcript payload parity.
// Uses bounded synthetic/public fixture data; no provider API, account data, secrets, or network.

import XCTest
@testable import OpenMates

final class VideoTranscriptPayloadParityTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=videos.transcript.surface-parity
    @MainActor
    func testPersistedWebVideoTranscriptCompactToonDecodesForNativeRenderer() throws {
        let persistedToon = #"""
        app_id: videos
        skill_id: get_transcript
        results[1]{type,url,transcript,word_count,characters_count,language,hash}:
          transcript_result,"https://www.youtube.com/watch?v=8S0FDjFBj8o","[00:00:00.000] Public fixture opening line.\n[00:00:02.000] Tab:\t backslash:\\ quote:\" unicode:\u00E9 \uD83D\uDC08 carriage:\rnext",13,102,English," 123 "
        result_count: 1
        status: finished
        embed_ref: youtube.com-public
        embed_id: persisted-video-transcript
        url: "https://www.youtube.com/watch?v=8S0FDjFBj8o"
        """#
        let envelope: [String: Any] = [
            "embed_id": "persisted-video-transcript",
            "type": "app_skill_use",
            "status": "finished",
            "content": persistedToon,
        ]
        let encoded = try JSONSerialization.data(withJSONObject: envelope)

        let record = try JSONDecoder().decode(EmbedRecord.self, from: encoded)
        let payload = VideoTranscriptPayload(data: record.rawData)

        XCTAssertTrue(record.isAppSkillUse)
        XCTAssertEqual(record.type, "app-skill-use")
        XCTAssertEqual(record.rawData?["app_id"]?.value as? String, "videos")
        XCTAssertEqual(record.rawData?["skill_id"]?.value as? String, "get_transcript")
        XCTAssertEqual(payload.sourceURL, "https://www.youtube.com/watch?v=8S0FDjFBj8o")
        XCTAssertEqual(payload.videoID, "8S0FDjFBj8o")
        XCTAssertEqual(payload.wordCount, 13)
        XCTAssertEqual(payload.language, "English")
        XCTAssertEqual(
            payload.transcript,
            "[00:00:00.000] Public fixture opening line.\n[00:00:02.000] Tab:\t backslash:\\ quote:\" unicode:é 🐈 carriage:\rnext"
        )
        let result = try XCTUnwrap(record.rawData?["results"]?.value as? [[String: Any]])
        XCTAssertEqual(
            result.first?["hash"] as? String,
            " 123 ",
            "Quoted scalars must remain strings and preserve leading/trailing whitespace"
        )
        XCTAssertNotNil(
            payload.videoThumbnailURL,
            "A persisted YouTube URL must still produce the fullscreen video preview"
        )
    }

    // contract-test: direct surface=gui.apple assertions=videos.transcript.surface-parity
    @MainActor
    func testVideoTranscriptSkillUsesLocalizedWebCatalogName() {
        XCTAssertEqual(AppStrings.videoGetTranscript, "Get Transcript")
    }

    // contract-test: direct surface=gui.apple assertions=videos.transcript.surface-parity
    @MainActor
    func testMalformedCompactToonRowDoesNotConsumeFollowingMetadata() throws {
        let persistedToon = #"""
        app_id: videos
        skill_id: get_transcript
        results[1]{type,url,transcript}:
          transcript_result,"https://www.youtube.com/watch?v=8S0FDjFBj8o","unterminated
        result_count: 1
        status: finished
        embed_ref: youtube.com-public
        """#
        let envelope: [String: Any] = [
            "embed_id": "malformed-video-transcript",
            "type": "app_skill_use",
            "status": "finished",
            "content": persistedToon,
        ]
        let encoded = try JSONSerialization.data(withJSONObject: envelope)

        let record = try JSONDecoder().decode(EmbedRecord.self, from: encoded)

        XCTAssertEqual((record.rawData?["results"]?.value as? [[String: Any]])?.count, 0)
        XCTAssertEqual(record.rawData?["result_count"]?.value as? String, "1")
        XCTAssertEqual(record.rawData?["status"]?.value as? String, "finished")
        XCTAssertEqual(record.rawData?["embed_ref"]?.value as? String, "youtube.com-public")
    }
}
