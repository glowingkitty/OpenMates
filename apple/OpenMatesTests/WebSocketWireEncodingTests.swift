// Synthetic actual retained-bundle and production socket serialization coverage.
// No network, account credentials, user data, Keychain mutation or inference.
import XCTest
import CryptoKit
import CoreFoundation
@testable import OpenMates

@MainActor
final class WebSocketWireEncodingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,message-input.send.ownership
    func testReloadedRetainedTurnPreservesNumericProtocolAndVersionsThroughPreflightCommitAndRetry() throws {
        let chatID = "synthetic-chat", messageID = "synthetic-message", turnID = "synthetic-turn"
        let cipher = "AA/+==", wrapper = "BB/+==", embedCipher = "CC/+=="
        let fence = ChatSendRetryFence(processEpoch: UUID(), accountID: "synthetic-owner", accountScope: UUID(),
            server: "https://synthetic.invalid", teamID: nil, teamEpoch: 0, keyGeneration: UUID(),
            deletionVersion: 0, chatKeyDigest: "synthetic-digest")
        let outbound: [String: Any] = ["chat_id": chatID, "turn_id": turnID, "chat_key_version": 1,
            "broadcast": false, "encrypted_chat_key": wrapper,
            "message": ["message_id": messageID, "chat_has_title": true,
                        "current_chat_title_v": 1, "current_chat_metadata_v": 0],
            "encrypted_embeds": [["embed_id": "synthetic-embed", "version_number": 1,
                "encrypted_content": embedCipher, "embed_keys": [["encrypted_embed_key": wrapper, "hashed_chat_id": NSNull()]]]]]
        let preflight: [String: Any] = ["protocol_version": 1, "chat_key_version": 1,
            "chat_id": chatID, "turn_id": turnID, "message_id": messageID,
            "expected_messages_v": 0, "inference_request": outbound,
            "encrypted_user_message": ["encrypted_content": cipher, "created_at": 1_800_000_001]]
        let original = try ChatRetainedSendBundle(chatID: chatID, messageID: messageID, turnID: turnID,
            inputDigest: "synthetic-input", messagesVersion: 1, fence: fence, preflight: preflight, outbound: outbound)
        let masterKey = SymmetricKey(size: .bits256)
        var encryptedDisk: [String: Data] = [:]
        let store = ChatRetainedSendStore(read: { encryptedDisk[$0] }, write: { encryptedDisk[$0] = $1 }, erase: { _ in
            XCTFail("Wire retries must not erase retained ownership or immutable ciphertext")
        })
        try store.save(original, masterKey: masterKey)
        for _ in 0..<2 {
            let restored = try XCTUnwrap(store.load(accountID: fence.accountID, server: fence.server,
                chatID: chatID, messageID: messageID, masterKey: masterKey))
            XCTAssertEqual(restored, original)
            let opened = try restored.payloads()
            let head = try payload(WSOutboundMessage(type: "chat_turn_preflight", payload: opened.preflight))
            try assertNumber(head["protocol_version"], equals: 1)
            try assertNumber(head["chat_key_version"], equals: 1)
            try assertNumber(head["expected_messages_v"], equals: 0)
            XCTAssertEqual(head["chat_id"] as? String, chatID)
            XCTAssertEqual(head["turn_id"] as? String, turnID)
            XCTAssertEqual(head["message_id"] as? String, messageID)
            let user = try XCTUnwrap(head["encrypted_user_message"] as? [String: Any])
            XCTAssertEqual(user["encrypted_content"] as? String, cipher)
            try assertNumber(user["created_at"], equals: 1_800_000_001)
            var committed = opened.outbound
            committed["protocol_version"] = 1
            committed["preflight_id"] = "synthetic-preflight"
            let commit = try payload(WSOutboundMessage(type: "chat_message_added", payload: committed))
            try assertNumber(commit["protocol_version"], equals: 1)
            try assertNumber(commit["chat_key_version"], equals: 1)
            try assertBoolean(commit["broadcast"], equals: false)
            XCTAssertEqual(commit["chat_id"] as? String, chatID)
            XCTAssertEqual(commit["turn_id"] as? String, turnID)
            XCTAssertEqual(commit["encrypted_chat_key"] as? String, wrapper)
            let message = try XCTUnwrap(commit["message"] as? [String: Any])
            XCTAssertEqual(message["message_id"] as? String, messageID)
            try assertNumber(message["current_chat_title_v"], equals: 1)
            try assertNumber(message["current_chat_metadata_v"], equals: 0)
            try assertBoolean(message["chat_has_title"], equals: true)
            let embeds = try XCTUnwrap(commit["encrypted_embeds"] as? [[String: Any]])
            try assertNumber(embeds.first?["version_number"], equals: 1)
            XCTAssertEqual(embeds.first?["encrypted_content"] as? String, embedCipher)
            let keys = try XCTUnwrap(embeds.first?["embed_keys"] as? [[String: Any]])
            XCTAssertEqual(keys.first?["encrypted_embed_key"] as? String, wrapper)
            XCTAssertTrue(keys.first?["hashed_chat_id"] is NSNull)
            let nested = try XCTUnwrap(head["inference_request"] as? [String: Any])
            try assertNumber(nested["chat_key_version"], equals: 1)
            try assertBoolean(nested["broadcast"], equals: false)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testOptionalEnvelopeShapeAndLegacyEncodableConsumerPreserveJSONTypes() throws {
        let absent = try object(WSOutboundMessage(type: "synthetic").encodedData())
        XCTAssertEqual(Set(absent.keys), ["type"])
        let dataOnly = try object(WSOutboundMessage(type: "synthetic", data: [:]).encodedData())
        XCTAssertEqual(Set(dataOnly.keys), ["type", "data"])
        XCTAssertEqual((dataOnly["data"] as? [String: Any])?.count, 0)
        let payloadOnly = try object(WSOutboundMessage(type: "synthetic", payload: [:]).encodedData())
        XCTAssertEqual(Set(payloadOnly.keys), ["type", "payload"])
        let reopened = try object(Data(#"{"version":1,"zero":0,"enabled":true,"nullable":null}"#.utf8))
        let both = WSOutboundMessage(type: "synthetic", data: reopened, payload: reopened)
        // Keep recording transports on Encodable consistent with the actual wire boundary.
        for data in [try both.encodedData(), try JSONEncoder().encode(both)] {
            let envelope = try object(data)
            XCTAssertEqual(Set(envelope.keys), ["type", "data", "payload"])
            for field in ["data", "payload"] {
                let values = try XCTUnwrap(envelope[field] as? [String: Any])
                try assertNumber(values["version"], equals: 1)
                try assertNumber(values["zero"], equals: 0)
                try assertBoolean(values["enabled"], equals: true)
                XCTAssertTrue(values["nullable"] is NSNull)
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,message-input.send.ownership
    func testUnsupportedValuesFailBeforeEitherWireEncodingEntryPoint() {
        for message in [WSOutboundMessage(type: "synthetic", payload: ["nested": ["invalid": Double.nan]]),
                        WSOutboundMessage(type: "synthetic", data: ["invalid": Date(timeIntervalSince1970: 0)])] {
            XCTAssertThrowsError(try message.encodedData())
            XCTAssertThrowsError(try JSONEncoder().encode(message))
        }
    }

    private func payload(_ message: WSOutboundMessage) throws -> [String: Any] {
        try XCTUnwrap(object(message.encodedData())["payload"] as? [String: Any])
    }

    private func object(_ data: Data) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func assertNumber(_ value: Any?, equals expected: Int, file: StaticString = #filePath, line: UInt = #line) throws {
        let number = try XCTUnwrap(value as? NSNumber, file: file, line: line)
        XCTAssertNotEqual(CFGetTypeID(number), CFBooleanGetTypeID(), "Versions must stay numeric", file: file, line: line)
        XCTAssertEqual(number.intValue, expected, file: file, line: line)
    }

    private func assertBoolean(_ value: Any?, equals expected: Bool, file: StaticString = #filePath, line: UInt = #line) throws {
        let number = try XCTUnwrap(value as? NSNumber, file: file, line: line)
        XCTAssertEqual(CFGetTypeID(number), CFBooleanGetTypeID(), "Actual flags must stay Boolean", file: file, line: line)
        XCTAssertEqual(number.boolValue, expected, file: file, line: line)
    }
}
