// Image-view reference resolution uses only synthetic chat-scoped records.
import XCTest
@testable import OpenMates

final class ImageViewReferenceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testErrorOutputResolvesExactFilenameToOriginalEncryptedUpload() {
        let upload = image(id: "upload", filename: "photo.jpg")
        let result = skill(["file_path": AnyCodable("photo.jpg"), "error": AnyCodable("fixture cache miss")])
        let model = ImageViewSkillModel(embed: result, allEmbedRecords: [upload.id: upload, result.id: result])
        XCTAssertEqual(model.originalEmbedId, upload.id)
        XCTAssertEqual(model.resolvedData?["filename"]?.value as? String, "photo.jpg")
        XCTAssertEqual(EmbedMediaPayload.previewS3Key(from: model.resolvedData), "preview.enc")
        XCTAssertEqual(EmbedMediaPayload.s3Key(from: model.resolvedData), "original.enc")
        XCTAssertEqual(model.resolvedData?["error"]?.value as? String, "fixture cache miss")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testFilenameResolutionRejectsAmbiguousAndGuessedPaths() {
        let first = image(id: "upload-1", filename: "photo.jpg")
        let second = image(id: "upload-2", filename: "photo.jpg")
        let result = skill(["file_path": AnyCodable("photo.jpg")])
        XCTAssertNil(ImageViewSkillModel(embed: result, allEmbedRecords: [first.id: first, second.id: second]).originalEmbedId)
        let pathResult = skill(["file_path": AnyCodable("folder/photo.jpg")])
        XCTAssertNil(ImageViewSkillModel(embed: pathResult, allEmbedRecords: [first.id: first]).originalEmbedId)
        let nonImage = EmbedRecord(id: "file", type: "file-file", status: .finished,
            data: .raw(["filename": AnyCodable("photo.jpg")]), parentEmbedId: nil, appId: "file", skillId: nil, embedIds: nil, createdAt: nil)
        XCTAssertNil(ImageViewSkillModel(embed: result, allEmbedRecords: [nonImage.id: nonImage]).originalEmbedId)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testExplicitInputReferenceTakesPrecedenceAndNeverFallsBackToFilename() {
        let upload = image(id: "upload", filename: "photo.jpg")
        let inputResult = skill(["input_embed_ids": AnyCodable([upload.id])])
        XCTAssertEqual(ImageViewSkillModel(embed: inputResult, allEmbedRecords: [upload.id: upload]).originalEmbedId, upload.id)
        let missing = skill(["embed_id": AnyCodable("absent"), "file_path": AnyCodable("photo.jpg")])
        XCTAssertNil(ImageViewSkillModel(embed: missing, allEmbedRecords: [upload.id: upload]).originalEmbedId)
    }

    private func skill(_ data: [String: AnyCodable]) -> EmbedRecord {
        EmbedRecord(id: "view", type: "app:images:view", status: .error, data: .raw(data),
            parentEmbedId: nil, appId: "images", skillId: "view", embedIds: nil, createdAt: nil)
    }
    private func image(id: String, filename: String) -> EmbedRecord {
        EmbedRecord(id: id, type: "image", status: .finished, data: .raw([
            "filename": AnyCodable(filename), "embed_ref": AnyCodable(filename),
            "files": AnyCodable(["preview": ["s3_key": "preview.enc"], "original": ["s3_key": "original.enc"]]),
            "aes_key": AnyCodable("synthetic-key"), "encryption": AnyCodable("aes-gcm-nonce-prefixed-v1")]),
            parentEmbedId: nil, appId: "images", skillId: nil, embedIds: nil, createdAt: nil)
    }
}
