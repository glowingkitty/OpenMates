// Tests of the queued-message revision (edit and steer of a queued follow-up)
// and of the voice-call turn options through the core actions: the call goes to
// a scripted fake client with the mapped revision, text and queue mode, a typed
// core refusal becomes the chat's existing error text, and the voice-call fields
// reach the send options. The core's own revision rules are covered by the crate tests.
// Specification: specifications/features/chat-queued-followups/specification.yml
// Assertions: chat-queued-followups.editing.stable-revision, chat-queued-followups.steering.safe-boundary, chat-queued-followups.access.scoped
import Combine
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeRevisionClient: ChatActionsCoreClient, QueuedRevisionCoreClient {
    struct Call: Equatable {
        let chatId: String
        let messageId: String
        let revision: UInt64
        let text: String?
        let modeChange: SendQueueModeRecord?
        let options: SendOptionsRecord
    }

    private(set) var revisions: [Call] = []
    var failure: CoreError?

    func reviseQueuedMessage(chatId: String, messageId: String, revision: UInt64, text: String?,
                             modeChange: SendQueueModeRecord?,
                             options: SendOptionsRecord) async throws -> QueuedRevisionReceiptRecord {
        revisions.append(Call(chatId: chatId, messageId: messageId, revision: revision, text: text,
                              modeChange: modeChange, options: options))
        if let failure { throw failure }
        return QueuedRevisionReceiptRecord(chatId: chatId, messageId: messageId,
                                           queueMode: modeChange ?? .followUp, queueRevision: revision + 1)
    }

    func sendWithOptions(request: UInt64, chatId: String?, text: String,
                         options: SendOptionsRecord) async throws -> SendReceiptRecord { throw CoreError.Cancelled }
    func editMessageWithOptions(request: UInt64, chatId: String, messageId: String, text: String,
                                options: SendOptionsRecord) async throws -> SendReceiptRecord { throw CoreError.Cancelled }
    func retryLastTurn(request: UInt64, chatId: String) async throws -> ChatWindowViewRecord { throw CoreError.Cancelled }
    func cancelSend() -> Bool { false }
    func stopReply(chatId: String, taskId: String) async throws {}
    func deleteMessage(request: UInt64, chatId: String, messageId: String) async throws {}
    func deleteChat(chatId: String) async throws {}
    func forkChat(chatId: String, messageId: String, title: String?) async throws -> String { "fork" }
    func answerConsent(chatId: String, requestId: String, approvedItemIds: [String]) async throws {}
}

final class CoreQueuedRevisionTests: XCTestCase {
    @MainActor
    private func makeActions() -> (CoreChatActions, FakeRevisionClient) {
        let actions = CoreChatActions(window: CoreChatWindow())
        let client = FakeRevisionClient()
        actions.attach(client: client, events: PassthroughSubject<ViewEventRecord, Never>().eraseToAnyPublisher())
        return (actions, client)
    }

    // contract-test: direct surface=gui.apple assertions=chat-queued-followups.editing.stable-revision
    @MainActor
    func testEditSendsTextAtTheExpectedRevisionAndKeepsTheMode() async throws {
        let (actions, client) = makeActions()
        let receipt = try await actions.reviseQueued(
            chatId: "chat-1", messageId: "queued-1", revision: 3, text: "Use the oak table", mode: nil)
        XCTAssertEqual(client.revisions.map(\.revision), [3])
        XCTAssertEqual(client.revisions.first?.text, "Use the oak table")
        XCTAssertNil(client.revisions.first?.modeChange)
        XCTAssertEqual(receipt.queueRevision, 4)
    }

    // contract-test: direct surface=gui.apple assertions=chat-queued-followups.steering.safe-boundary
    @MainActor
    func testSteerChangesOnlyTheQueueMode() async throws {
        let (actions, client) = makeActions()
        let receipt = try await actions.reviseQueued(
            chatId: "chat-1", messageId: "queued-1", revision: 1, text: nil, mode: .steer)
        XCTAssertNil(client.revisions.first?.text)
        XCTAssertEqual(client.revisions.first?.modeChange, .steer)
        XCTAssertEqual(receipt.queueMode, .steer)
    }

    // contract-test: direct surface=gui.apple assertions=chat-queued-followups.editing.stable-revision
    @MainActor
    func testConflictIsATypedRejectionWithTheConflictText() async {
        let (actions, client) = makeActions()
        client.failure = .Conflict
        do {
            _ = try await actions.reviseQueued(chatId: "chat-1", messageId: "queued-1", revision: 2, text: "x", mode: nil)
            XCTFail("a conflict must throw")
        } catch {
            XCTAssertEqual(error as? CoreQueuedRevisionRejection, .conflict)
            XCTAssertEqual(CoreChatActions.queuedRevisionMessage(for: error), AppStrings.queuedFollowupConflict)
        }
    }

    // contract-test: direct surface=gui.apple assertions=chat-queued-followups.access.scoped
    @MainActor
    func testForbiddenAndUnavailableShowTheUnavailableText() async {
        let (actions, client) = makeActions()
        for failure in [CoreError.Forbidden, CoreError.Unavailable(code: "queue", reason: "inactive")] {
            client.failure = failure
            do {
                _ = try await actions.reviseQueued(chatId: "chat-1", messageId: "queued-1", revision: 2, text: nil, mode: .steer)
                XCTFail("a refusal must throw")
            } catch {
                XCTAssertEqual(CoreChatActions.queuedRevisionMessage(for: error), AppStrings.queuedFollowupUnavailable)
            }
        }
    }

    // contract-test: direct surface=gui.apple assertions=chat-queued-followups.editing.stable-revision
    @MainActor
    func testRevisionWithoutACoreReportsNoCore() async {
        let actions = CoreChatActions(window: CoreChatWindow())
        do {
            _ = try await actions.reviseQueued(chatId: "chat-1", messageId: "queued-1", revision: 1, text: "x", mode: nil)
            XCTFail("no core must throw")
        } catch {
            XCTAssertEqual(error as? CoreChatActionsError, .noCore)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.access.scoped
    func testVoiceCallTurnOptionsCarryTheCallAndTheHeardBoundary() {
        let boundary = NativeVoiceCallHeardBoundary(
            assistantMessageID: "reply-1", completedSequences: [2, 0], activeSequence: 3, activeOffsetMilliseconds: 450)
        let record = CoreSendMapping.voiceCallTurn(callID: "call-1", turnID: "turn-1", heardBoundary: boundary)
        let options = CoreSendMapping.options(reservedMessageId: "turn-1", voiceCall: record)
        XCTAssertEqual(options.voiceCall?.callId, "call-1")
        XCTAssertEqual(options.voiceCall?.turnId, "turn-1")
        XCTAssertEqual(options.voiceCall?.heardBoundary?.completedSequences, [0, 2])
        XCTAssertEqual(options.voiceCall?.heardBoundary?.activeSequence, 3)
        XCTAssertEqual(options.voiceCall?.heardBoundary?.activeOffsetMs, 450)
        XCTAssertNil(CoreSendMapping.voiceCallTurn(callID: "c", turnID: "t", heardBoundary: nil).heardBoundary)
    }
}
