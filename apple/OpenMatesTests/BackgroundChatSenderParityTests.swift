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
}
