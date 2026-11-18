// Mapping coverage for the videos.generate timeline model (synthetic payloads only).
//
// Web source: frontend/packages/ui/src/components/embeds/videos/videoTimelineModel.ts
// Specification: specifications/features/app-skills/videos-generate/specification.yml

import XCTest
@testable import OpenMates

final class VideoEmbedParityTests: XCTestCase {
    private func content(_ timeline: [String: Any], extra: [String: Any] = [:]) -> [String: AnyCodable] {
        var result: [String: AnyCodable] = ["timeline": AnyCodable(timeline)]
        for (key, value) in extra { result[key] = AnyCodable(value) }
        return result
    }

    private let sample: [String: Any] = [
        "fps": 30,
        "tracks": [[
            "id": "main", "name": "Scenes", "kind": "visual",
            "parts": [
                ["id": "b", "label": "Second", "from": 90, "duration_in_frames": 60],
                ["id": "a", "from": 0, "duration_in_frames": 90, "kind": "scene"],
                ["id": "bad", "from": -1, "duration_in_frames": 10]
            ]
        ]],
        "audio": [["id": "m", "kind": "music", "label": "Bed", "from": 0, "durationInFrames": 200]]
    ]

    // contract-test: supporting surface=gui.apple assertions=videos-generate.timeline.below-the-video
    func testStoredTimelineSortsPartsDropsInvalidAndExtendsDurationToAudio() throws {
        let model = try XCTUnwrap(VideoTimelineModel.resolve(content: content(sample, extra: ["made_by": "composed", "width": 1280]), loadedSeconds: 0, clipLabel: "Clip"))
        XCTAssertEqual(model.tracks.first?.parts.map(\.id), ["a", "b"])
        XCTAssertEqual(model.tracks.first?.parts.first?.label, "a")
        XCTAssertEqual(model.durationInFrames, 200)
        XCTAssertEqual(model.madeBy, .composed)
        XCTAssertEqual(model.width, 1280)
        XCTAssertEqual(model.audioRows.map(\.kind), [.music])
        XCTAssertTrue(model.showsTrackNames(compact: false))
        XCTAssertFalse(model.showsTrackNames(compact: true))
    }

    // contract-test: supporting surface=gui.apple assertions=videos-generate.timeline.below-the-video
    func testMissingTimelineSynthesizesOneClipFromStoredOrLoadedLength() throws {
        XCTAssertNil(VideoTimelineModel.resolve(content: ["timeline": AnyCodable(["tracks": [Any]()])], loadedSeconds: 0, clipLabel: "Clip"))
        XCTAssertNil(VideoTimelineModel.resolve(content: [:], loadedSeconds: 0, clipLabel: "Clip"))
        let model = try XCTUnwrap(VideoTimelineModel.resolve(content: ["duration_seconds": AnyCodable(8.0)], loadedSeconds: 3, clipLabel: "Clip"))
        XCTAssertEqual(model.durationInFrames, 240)
        XCTAssertEqual(model.tracks.first?.parts.first?.label, "Clip")
        XCTAssertEqual(model.madeBy, .generative)
    }

    // contract-test: supporting surface=gui.apple assertions=videos-generate.timeline.below-the-video
    func testPlayheadSeekAndRulerGeometryMatchWeb() throws {
        let model = try XCTUnwrap(VideoTimelineModel.resolve(content: ["duration_seconds": AnyCodable(10.0)], loadedSeconds: 0, clipLabel: "Clip"))
        XCTAssertEqual(model.playheadFraction(currentTime: 5), 0.5, accuracy: 0.0001)
        XCTAssertEqual(model.playheadFraction(currentTime: 99), 1)
        XCTAssertEqual(model.seekTime(ratio: 0.25), 2.5, accuracy: 0.0001)
        XCTAssertEqual(model.seekTime(ratio: -1), 0)
        XCTAssertEqual(model.rulerMarks, [0, 2, 4, 6, 8, 10])
        XCTAssertTrue(VideoTimelineModel.showsLabel(widthFraction: 0.07, compact: false))
        XCTAssertFalse(VideoTimelineModel.showsLabel(widthFraction: 0.1, compact: true))
        XCTAssertTrue(VideoTimelineModel.showsLength(widthFraction: 0.16, compact: false))
    }

    // contract-test: supporting surface=gui.apple assertions=videos-generate.timeline.below-the-video
    func testFormatSecondsMatchesWebLabels() {
        XCTAssertEqual(VideoTimelineModel.formatSeconds(8), "8 s")
        XCTAssertEqual(VideoTimelineModel.formatSeconds(2.46), "2.5 s")
        XCTAssertEqual(VideoTimelineModel.formatSeconds(65), "1:05")
    }
}
