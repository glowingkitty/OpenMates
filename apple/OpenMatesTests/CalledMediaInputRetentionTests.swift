// Synthetic input identity cases for called media skills; no network or media jobs.
import XCTest
@testable import OpenMates

@MainActor
final class CalledMediaInputRetentionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWebReadRetainsRequestedURLWhenResultUsesAnotherURL() {
        let data = ["url": AnyCodable("https://example.org/requested"),
                    "results": AnyCodable([["url": "https://example.org/redirected", "markdown": "Article text"]])]
        XCTAssertEqual(WebReadEmbedRenderer.inputURL(in: data), "https://example.org/requested")
        XCTAssertEqual(WebReadEmbedRenderer.sourceContent(in: data), "Article text")
        XCTAssertEqual(WebReadEmbedRenderer.inputURL(in: ["results": data["results"]!]), "https://example.org/redirected")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,videos.transcript.surface-parity
    func testTranscriptRetainsRequestedURLAlongsideCompletedContent() {
        let payload = VideoTranscriptPayload(data: [
            "url": AnyCodable("https://youtu.be/requested"),
            "results": AnyCodable([["url": "https://youtube.com/watch?v=requested", "transcript": "Spoken text", "title": "Result title"]])])
        XCTAssertEqual(payload.sourceURL, "https://youtu.be/requested")
        XCTAssertEqual(payload.transcript, "Spoken text")
        XCTAssertEqual(payload.title, "Result title")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testImageViewMediaResolutionCannotReplaceCalledFilePath() {
        let upload = EmbedRecord(id: "upload", type: "image", status: .finished,
            data: .raw(["file_path": AnyCodable("upload-internal-path"), "filename": AnyCodable("photo.jpg")]),
            parentEmbedId: nil, appId: "images", skillId: nil, embedIds: nil, createdAt: nil)
        for status in [EmbedStatus.processing, .finished, .error] {
            let called = EmbedRecord(id: "called", type: "app:images:view", status: status,
                data: .raw(["embed_id": AnyCodable(upload.id), "file_path": AnyCodable("requested/photo.jpg")]),
                parentEmbedId: nil, appId: "images", skillId: "view", embedIds: nil, createdAt: nil)
            let model = ImageViewSkillModel(embed: called, allEmbedRecords: [upload.id: upload])
            XCTAssertEqual(model.resolvedData?["file_path"]?.value as? String, "requested/photo.jpg")
            XCTAssertEqual(model.resolvedData?["filename"]?.value as? String, "photo.jpg")
        }
    }
}
