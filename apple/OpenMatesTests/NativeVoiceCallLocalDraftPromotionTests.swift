// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.launch-and-provider
import Combine
import XCTest
@testable import OpenMates

@MainActor
final class NativeVoiceCallLocalDraftPromotionTests: XCTestCase {
    private let chatID = "f7d73b3f-0fb1-4d34-ab65-51143a7df126"
    private func draft(wrapper: String? = nil, messages: Int? = nil, metadata: Int? = nil,
                       team: String? = nil, category: String? = "general_knowledge") -> Chat {
        Chat(id: chatID, title: "Local title", lastMessageAt: nil, createdAt: "2026-10-19T10:00:00Z",
            updatedAt: nil, isArchived: false, isPinned: true, appId: nil, category: category,
            encryptedTitle: nil, encryptedChatKey: wrapper, messagesV: messages, titleV: nil,
            draftV: 9, metadataV: metadata, encryptedFocusPhaseState: "focus-cipher",
            activeFocusId: "focus", teamId: team, hasNonEmptyDraft: true, clearedDraftV: 4, unreadCount: 2)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.chat.launch-and-provider
    func testPromotionKeepsOriginIdentityAndLatestDraftMetadata() throws {
        let source = draft()
        let promoted = try NativeVoiceCallLocalDraftPromotion.prepare(source, chatID: chatID,
            encryptedChatKey: "actual-wrapper", mate: "general_knowledge")
        XCTAssertEqual(promoted.id, source.id)
        XCTAssertEqual(promoted.encryptedChatKey, "actual-wrapper")
        XCTAssertEqual(promoted.draftV, 9); XCTAssertEqual(promoted.clearedDraftV, 4)
        XCTAssertEqual(promoted.hasNonEmptyDraft, true); XCTAssertEqual(promoted.unreadCount, 2)
        XCTAssertEqual(promoted.title, source.title); XCTAssertEqual(promoted.isPinned, true)
        XCTAssertEqual(promoted.encryptedFocusPhaseState, "focus-cipher")
        XCTAssertEqual(promoted.activeFocusId, "focus")
        XCTAssertEqual(promoted.messagesV, 0); XCTAssertEqual(promoted.titleV, 0); XCTAssertEqual(promoted.metadataV, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.chat.launch-and-provider
    func testCanonicalOrSharedRowsCannotBePromotedAsLocalDrafts() {
        XCTAssertFalse(NativeVoiceCallLocalDraftPromotion.eligible(draft(wrapper: "canonical"), chatID: chatID))
        XCTAssertFalse(NativeVoiceCallLocalDraftPromotion.eligible(draft(messages: 1), chatID: chatID))
        XCTAssertFalse(NativeVoiceCallLocalDraftPromotion.eligible(draft(metadata: 1), chatID: chatID))
        XCTAssertFalse(NativeVoiceCallLocalDraftPromotion.eligible(draft(team: "team"), chatID: chatID))
        XCTAssertFalse(NativeVoiceCallLocalDraftPromotion.eligible(draft(), chatID: UUID().uuidString.lowercased()))
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding
    func testChangedMateOrEmptyWrapperCannotOverwriteLocalDraft() {
        XCTAssertThrowsError(try NativeVoiceCallLocalDraftPromotion.prepare(draft(category: "science"),
            chatID: chatID, encryptedChatKey: "wrapper", mate: "general_knowledge"))
        XCTAssertThrowsError(try NativeVoiceCallLocalDraftPromotion.prepare(draft(),
            chatID: chatID, encryptedChatKey: "", mate: "general_knowledge"))
        let source = draft()
        XCTAssertNil(source.encryptedChatKey); XCTAssertEqual(source.draftV, 9)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding
    func testCallPresentationDoesNotPublishThroughRootConfiguration() {
        let runtime = NativeVoiceCallRootRuntime()
        var rootInvalidations = 0
        let observation = runtime.objectWillChange.sink { rootInvalidations += 1 }
        runtime.presentation.creditsCharged = 3
        runtime.presentation.toolWorking = true
        XCTAssertEqual(rootInvalidations, 0)
        withExtendedLifetime(observation) {}
    }
}
