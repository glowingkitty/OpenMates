// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.typed-input, video-call.audio.single-owner
import XCTest
@testable import OpenMates

@MainActor
final class NativeVoiceCallRootAdmissionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input
    func testCallReceiptsAdvanceMessagesVersionMonotonically() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: Data(#"{"id":"chat","created_at":1,"messages_v":2}"#.utf8))
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChat(chat)
            NativeVoiceCallAppFactory.advanceMessagesVersion(store, chatID: "chat", receipt: "call_message_confirmed", fields: ["messages_v": 5])
            XCTAssertEqual(store.chat(for: "chat")?.messagesV, 5)
            NativeVoiceCallAppFactory.advanceMessagesVersion(store, chatID: "chat", receipt: "call_message_confirmed", fields: ["messages_v": 3])
            XCTAssertEqual(store.chat(for: "chat")?.messagesV, 5)
            NativeVoiceCallAppFactory.advanceMessagesVersion(store, chatID: "chat", receipt: "system_message_confirmed", fields: ["messages_v": 6])
            XCTAssertEqual(store.chat(for: "chat")?.messagesV, 6)
            NativeVoiceCallAppFactory.advanceMessagesVersion(store, chatID: "chat", receipt: "other", fields: ["messages_v": 9])
            NativeVoiceCallAppFactory.advanceMessagesVersion(store, chatID: "chat", receipt: "call_message_confirmed", fields: [:])
            XCTAssertEqual(store.chat(for: "chat")?.messagesV, 6)
        }
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.chat.typed-input
    func testPreparationBlocksCallOnlyForItsExactOriginChat() {
        let gate = NativeVoiceCallSendAdmission()
        guard let send = gate.beginOrdinary(chatID: "origin") else { XCTFail("unexpected live audio owner"); return }
        XCTAssertFalse(gate.claimCall(UUID(), chatID: "origin"))
        let other = UUID()
        XCTAssertTrue(gate.claimCall(other, chatID: "other"))
        gate.releaseCall(other); gate.endOrdinary(send)
        let origin = UUID()
        XCTAssertTrue(gate.claimCall(origin, chatID: "origin"))
        gate.releaseCall(origin)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.audio.single-owner
    func testOtherWindowCannotAdmitOrdinarySendDuringConsentOrCall() {
        let gate = NativeVoiceCallSendAdmission(), owner = UUID()
        XCTAssertTrue(gate.claimCall(owner, chatID: "origin"))
        XCTAssertNil(gate.beginOrdinary(chatID: "origin"))
        XCTAssertNil(gate.beginOrdinary(chatID: "other"))
        XCTAssertFalse(gate.claimCall(UUID(), chatID: "other"))
        gate.releaseCall(owner)
        guard let next = gate.beginOrdinary(chatID: "other") else { XCTFail("owner remained reserved"); return }
        gate.endOrdinary(next)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding
    func testUnrelatedOwnerCannotReleaseCurrentCallClaim() {
        let gate = NativeVoiceCallSendAdmission(), owner = UUID()
        XCTAssertTrue(gate.claimCall(owner, chatID: "origin"))
        gate.releaseCall(UUID())
        XCTAssertNil(gate.beginOrdinary(chatID: "origin"))
        gate.releaseCall(owner)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input
    func testEndingOlderPreparationDoesNotReleaseNewerPreparation() {
        let gate = NativeVoiceCallSendAdmission()
        guard let old = gate.beginOrdinary(chatID: "origin"), let newer = gate.beginOrdinary(chatID: "origin")
        else { XCTFail("unexpected live audio owner"); return }
        gate.endOrdinary(old)
        XCTAssertTrue(gate.isPreparing(chatID: "origin"))
        XCTAssertFalse(gate.claimCall(UUID(), chatID: "origin"))
        gate.endOrdinary(newer)
        XCTAssertFalse(gate.isPreparing(chatID: "origin"))
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input
    func testOriginalDocumentAndSelectionSurviveMemoryOnlySnapshot() throws {
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "original", source: "Original draft")])
        let snapshot = NativeVoiceCallRootDraftSnapshot(document: document, selectionLocation: 3, selectionLength: 4)
        let readback = try JSONDecoder().decode(NativeVoiceCallRootDraftSnapshot.self, from: JSONEncoder().encode(snapshot))
        XCTAssertEqual(readback.document, document)
        XCTAssertEqual(readback.selectionLocation, 3); XCTAssertEqual(readback.selectionLength, 4)
    }
}
