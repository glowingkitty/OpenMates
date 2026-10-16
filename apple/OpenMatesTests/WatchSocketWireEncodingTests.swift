// Exercise the exact production Watch socket encoding boundary after durable
// prepared-turn JSON has been decrypted and reopened as Foundation values.
import XCTest
import CoreFoundation
@testable import OpenMates

@MainActor
final class WatchSocketWireEncodingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.audio-reply
    func testReopenedPreflightKeepsProtocolAndVersionsNumericAndFlagsBoolean() throws {
        let persisted = Data(#"{"protocol_version":1,"chat_key_version":1,"expected_messages_v":0,"encrypted_user_message":{"encrypted_content":"AAECAwQFBg==","created_at":1800000001},"inference_request":{"broadcast":false,"message":{"chat_has_title":false,"current_chat_title_v":0,"current_chat_metadata_v":1}}}"#.utf8)
        let reopened = try XCTUnwrap(JSONSerialization.jsonObject(with: persisted) as? [String: Any])
        let wire = try payload(type: "chat_turn_preflight", object: reopened)
        try assertNumber(wire["protocol_version"], equals: 1)
        try assertNumber(wire["chat_key_version"], equals: 1)
        try assertNumber(wire["expected_messages_v"], equals: 0)
        let inference = try XCTUnwrap(wire["inference_request"] as? [String: Any])
        try assertBoolean(inference["broadcast"], equals: false)
        let message = try XCTUnwrap(inference["message"] as? [String: Any])
        try assertBoolean(message["chat_has_title"], equals: false)
        try assertNumber(message["current_chat_title_v"], equals: 0)
        try assertNumber(message["current_chat_metadata_v"], equals: 1)
        let encrypted = try XCTUnwrap(wire["encrypted_user_message"] as? [String: Any])
        XCTAssertEqual(encrypted["encrypted_content"] as? String, "AAECAwQFBg==")
        try assertNumber(encrypted["created_at"], equals: 1_800_000_001)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,chats.persistence.client-encrypted
    func testCommitAndRetryRetainNumericMetadataOpaqueCiphertextAndNulls() throws {
        let persisted = Data(#"{"protocol_version":1,"message":{"message_id":"synthetic-message","current_chat_title_v":1,"current_chat_metadata_v":0,"chat_has_title":true},"encrypted_chat_key":"AA/+==","encrypted_embeds":[{"version_number":1,"embed_keys":[{"created_at":1800000001,"encrypted_embed_key":"BB/+==","hashed_chat_id":null}]}]}"#.utf8)
        let reopened = try XCTUnwrap(JSONSerialization.jsonObject(with: persisted) as? [String: Any])
        for _ in 0..<2 {
            let wire = try payload(type: "chat_message_added", object: reopened)
            try assertNumber(wire["protocol_version"], equals: 1)
            XCTAssertEqual(wire["encrypted_chat_key"] as? String, "AA/+==")
            let message = try XCTUnwrap(wire["message"] as? [String: Any])
            XCTAssertEqual(message["message_id"] as? String, "synthetic-message")
            try assertNumber(message["current_chat_title_v"], equals: 1)
            try assertNumber(message["current_chat_metadata_v"], equals: 0)
            try assertBoolean(message["chat_has_title"], equals: true)
            let embeds = try XCTUnwrap(wire["encrypted_embeds"] as? [[String: Any]])
            try assertNumber(embeds.first?["version_number"], equals: 1)
            let keys = try XCTUnwrap(embeds.first?["embed_keys"] as? [[String: Any]])
            XCTAssertEqual(keys.first?["encrypted_embed_key"] as? String, "BB/+==")
            XCTAssertTrue(keys.first?["hashed_chat_id"] is NSNull)
        }
        XCTAssertTrue(NSDictionary(dictionary: reopened).isEqual(to: try XCTUnwrap(JSONSerialization.jsonObject(with: persisted) as? [String: Any])),
                      "Wire preparation must not mutate the retained immutable turn")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testWireRejectsUnsupportedValuesInsteadOfSilentlyChangingTheirIdentity() {
        XCTAssertThrowsError(try WatchWSOutboundMessage(type: "chat_turn_preflight", payload: ["protocol_version": Double.nan]).encodedData())
        XCTAssertThrowsError(try WatchWSOutboundMessage(type: "chat_turn_preflight", payload: ["unsupported": Date(timeIntervalSince1970: 0)]).encodedData())
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,chats.persistence.client-encrypted
    func testClientUpdateRequiredPreflightNeverDispatchesInference() async throws {
        let inference: [String: Any] = ["chat_id": "synthetic-chat", "turn_id": "synthetic-turn"]
        let preflight: [String: Any] = ["chat_id": "synthetic-chat", "turn_id": "synthetic-turn", "inference_request": inference]
        let pending = WatchPendingTextSend(id: "synthetic-turn", chatId: "synthetic-chat", messageId: "synthetic-message",
            encryptedContent: "opaque-cipher", encryptedChatKey: "opaque-wrapper", createdAt: "1800000001",
            preflightJSON: try JSONSerialization.data(withJSONObject: preflight),
            inferenceJSON: try JSONSerialization.data(withJSONObject: inference))
        var requests: [String] = []
        var inbox: [(type: String, payload: [String: Any])] = [
            ("error", ["turn_id": pending.id, "code": "client_update_required"])
        ]
        do {
            try await WatchCanonicalStorage.sendTurn(pending, request: { type, _, responseTypes, matching in
                requests.append(type)
                let response = try WatchSocketResponses.takeMatchingResponse(from: &inbox,
                    requestType: type, responseTypes: responseTypes, matching: matching)
                return try XCTUnwrap(response)
            }, encryptMetadata: { _ in
                XCTFail("Rejected preflight cannot advance to canonical metadata encryption")
                return "unreachable"
            }, validate: {})
            XCTFail("Rejected preflight cannot authorize inference")
        } catch WatchChatRuntimeError.turnAdmissionFailure(let diagnostic) {
            XCTAssertEqual(diagnostic.stage, .preflight)
            XCTAssertEqual(diagnostic.reason, "client_update_required")
            XCTAssertFalse(diagnostic.invalidAcknowledgement)
        }
        XCTAssertEqual(requests, ["chat_turn_preflight"], "No chat_message_added dispatch follows a rejected preflight")
    }

    private func payload(type: String, object: [String: Any]) throws -> [String: Any] {
        let data = try WatchWSOutboundMessage(type: type, payload: object).encodedData()
        let envelope = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(envelope["type"] as? String, type)
        return try XCTUnwrap(envelope["payload"] as? [String: Any])
    }

    private func assertNumber(_ value: Any?, equals expected: Int, file: StaticString = #filePath, line: UInt = #line) throws {
        let number = try XCTUnwrap(value as? NSNumber, file: file, line: line)
        XCTAssertNotEqual(CFGetTypeID(number), CFBooleanGetTypeID(), "Protocol numbers must never encode as JSON Boolean", file: file, line: line)
        XCTAssertEqual(number.intValue, expected, file: file, line: line)
    }

    private func assertBoolean(_ value: Any?, equals expected: Bool, file: StaticString = #filePath, line: UInt = #line) throws {
        let number = try XCTUnwrap(value as? NSNumber, file: file, line: line)
        XCTAssertEqual(CFGetTypeID(number), CFBooleanGetTypeID(), "Actual flags must remain JSON Boolean", file: file, line: line)
        XCTAssertEqual(number.boolValue, expected, file: file, line: line)
    }
}
