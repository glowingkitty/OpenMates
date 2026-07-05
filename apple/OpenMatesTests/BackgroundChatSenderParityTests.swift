// Unit coverage for Apple background chat sender parity.
// The notification and share-extension paths run outside the foreground chat UI,
// so these tests keep coverage at the deterministic payload-contract layer. They
// avoid network calls, credentials, plaintext chat content, and raw encryption
// keys while guarding the storage package sent after assistant task startup.

import XCTest
@testable import OpenMates

final class BackgroundChatSenderParityTests: XCTestCase {
    private struct SessionProbe: Encodable {
        let sessionId: String
        let deviceInfo: DeviceInfoProbe
    }

    private struct DeviceInfoProbe: Encodable {
        let os: String
        let deviceModel: String
        let appVersion: String
    }

    func testBackgroundHTTPEncoderUsesBackendSnakeCaseContract() throws {
        let probe = SessionProbe(
            sessionId: "session-1",
            deviceInfo: DeviceInfoProbe(os: "iOS", deviceModel: "iPhone", appVersion: "1.0")
        )
        let data = try BackgroundChatHTTPContract.makeEncoder().encode(probe)
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let deviceInfo = try XCTUnwrap(payload["device_info"] as? [String: String])

        XCTAssertEqual(payload["session_id"] as? String, "session-1")
        XCTAssertNil(payload["sessionId"])
        XCTAssertEqual(deviceInfo["device_model"], "iPhone")
        XCTAssertEqual(deviceInfo["app_version"], "1.0")
        XCTAssertNil(deviceInfo["deviceModel"])
    }

    func testEncryptedStoragePayloadContainsOnlyEncryptedDurableContentAndVersions() throws {
        let payload = BackgroundChatStoragePayload(
            chatId: "chat-1",
            messageId: "user-1",
            encryptedContent: "encrypted-user-message",
            createdAtUnix: 1_780_000_000,
            encryptedChatKey: "encrypted-chat-key",
            messagesV: 7,
            titleV: 3,
            taskId: "task-1",
            encryptedSenderName: "encrypted-user",
            encryptedTitle: "encrypted-title",
            encryptedIcon: "encrypted-icon",
            encryptedChatCategory: "encrypted-chat-category",
            encryptedUserCategory: "encrypted-user-category"
        ).dictionary

        XCTAssertEqual(payload["chat_id"] as? String, "chat-1")
        XCTAssertEqual(payload["message_id"] as? String, "user-1")
        XCTAssertEqual(payload["encrypted_content"] as? String, "encrypted-user-message")
        XCTAssertEqual(payload["encrypted_chat_key"] as? String, "encrypted-chat-key")
        XCTAssertEqual(payload["task_id"] as? String, "task-1")
        XCTAssertEqual(payload["encrypted_sender_name"] as? String, "encrypted-user")
        XCTAssertEqual(payload["encrypted_title"] as? String, "encrypted-title")
        XCTAssertEqual(payload["encrypted_icon"] as? String, "encrypted-icon")
        XCTAssertEqual(payload["encrypted_chat_category"] as? String, "encrypted-chat-category")
        XCTAssertEqual(payload["encrypted_category"] as? String, "encrypted-user-category")
        XCTAssertNil(payload["content"])
        XCTAssertNil(payload["plaintext"])
        XCTAssertNil(payload["sender_name"])

        let versions = try XCTUnwrap(payload["versions"] as? [String: Int])
        XCTAssertEqual(versions["messages_v"], 7)
        XCTAssertEqual(versions["title_v"], 3)
        XCTAssertEqual(versions["last_edited_overall_timestamp"], 1_780_000_000)
    }

    func testQueuedBackgroundEventDoesNotTriggerEncryptedStoragePackage() {
        XCTAssertFalse(
            BackgroundChatStorageContract.shouldSendEncryptedStoragePackage(afterInboundEventType: "message_queued")
        )
        XCTAssertTrue(
            BackgroundChatStorageContract.shouldSendEncryptedStoragePackage(afterInboundEventType: "ai_typing_started")
        )
        XCTAssertTrue(
            BackgroundChatStorageContract.shouldSendEncryptedStoragePackage(afterInboundEventType: "ai_task_initiated")
        )
    }

    func testBackgroundAttachmentClassificationMatchesComposerSupportedTypes() {
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "photo.png", contentType: "image/png")?.embedType, "images-image")
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "brief.pdf", contentType: "application/pdf")?.embedType, "pdf")
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "notes.md", contentType: "text/markdown")?.embedType, "docs-doc")
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "voice.m4a", contentType: "audio/mp4")?.embedType, "audio-recording")
        XCTAssertNil(BackgroundAttachmentClassifier.classification(filename: "archive.zip", contentType: "application/zip"))
    }

    func testBackgroundAudioEmbedPreservesFullTranscriptMetadata() throws {
        let upload = BackgroundUploadFileResponse.testFixture(
            embedId: "audio-embed-1",
            filename: "voice.m4a",
            contentType: "audio/mp4"
        )
        let metadata = BackgroundAudioTranscriptionMetadata(
            transcript: "Corrected transcript",
            transcriptOriginal: "Raw transcript",
            transcriptCorrected: "Corrected transcript",
            useCorrected: true,
            correctionModel: "gemini-3.5-flash",
            model: "voxtral-mini-2602"
        )

        let embed = try BackgroundPreparedEmbed.from(upload: upload, audioMetadata: metadata, durationSeconds: 2.5)

        XCTAssertEqual(embed.type, "audio-recording")
        XCTAssertEqual(embed.referenceType, "audio-recording")
        XCTAssertEqual(embed.textPreview, "Corrected transcript")
        XCTAssertEqual(embed.content["transcript"] as? String, "Corrected transcript")
        XCTAssertEqual(embed.content["transcript_original"] as? String, "Raw transcript")
        XCTAssertEqual(embed.content["transcript_corrected"] as? String, "Corrected transcript")
        XCTAssertEqual(embed.content["use_corrected"] as? Bool, true)
        XCTAssertEqual(embed.content["correction_model"] as? String, "gemini-3.5-flash")
        XCTAssertEqual(embed.content["model"] as? String, "voxtral-mini-2602")
        XCTAssertTrue(embed.markdownReference.contains("audio-embed-1"))
    }

    func testBackgroundSendContentAllowsEmbedOnlyMessages() throws {
        let upload = BackgroundUploadFileResponse.testFixture(
            embedId: "image-embed-1",
            filename: "screenshot.png",
            contentType: "image/png"
        )
        let embed = try BackgroundPreparedEmbed.from(upload: upload)

        XCTAssertNoThrow(try BackgroundChatSendContract.contentForSend(text: "", embeds: [embed]))
        let content = try BackgroundChatSendContract.contentForSend(text: "Please inspect this", embeds: [embed])

        XCTAssertTrue(content.hasPrefix("Please inspect this"))
        XCTAssertTrue(content.contains("image-embed-1"))
        XCTAssertThrowsError(try BackgroundChatSendContract.contentForSend(text: "", embeds: []))
    }

    func testBackgroundPdfEmbedUsesProcessingUntilOcrDedupCompletes() throws {
        let processingUpload = BackgroundUploadFileResponse.testFixture(
            embedId: "pdf-embed-1",
            filename: "brief.pdf",
            contentType: "application/pdf",
            deduplicated: false
        )
        let finishedUpload = BackgroundUploadFileResponse.testFixture(
            embedId: "pdf-embed-2",
            filename: "brief.pdf",
            contentType: "application/pdf",
            deduplicated: true
        )

        let processingEmbed = try BackgroundPreparedEmbed.from(upload: processingUpload)
        let finishedEmbed = try BackgroundPreparedEmbed.from(upload: finishedUpload)

        XCTAssertEqual(processingEmbed.status, "processing")
        XCTAssertEqual(processingEmbed.content["status"] as? String, "processing")
        XCTAssertEqual(finishedEmbed.status, "finished")
        XCTAssertEqual(finishedEmbed.content["status"] as? String, "finished")
    }
}

private extension BackgroundUploadFileResponse {
    static func testFixture(
        embedId: String,
        filename: String,
        contentType: String,
        deduplicated: Bool = true
    ) -> BackgroundUploadFileResponse {
        BackgroundUploadFileResponse(
            embedId: embedId,
            filename: filename,
            contentType: contentType,
            contentHash: "hash-1",
            files: [
                "original": BackgroundUploadedFileVariant(
                    s3Key: "uploads/\(filename)",
                    sizeBytes: 123,
                    width: contentType.hasPrefix("image/") ? 100 : nil,
                    height: contentType.hasPrefix("image/") ? 80 : nil,
                    format: (filename as NSString).pathExtension
                )
            ],
            s3BaseUrl: "https://example.invalid/files",
            aesKey: "aes-key",
            aesNonce: "aes-nonce",
            vaultWrappedAesKey: "wrapped-key",
            pageCount: contentType == "application/pdf" ? 1 : nil,
            deduplicated: deduplicated
        )
    }
}
