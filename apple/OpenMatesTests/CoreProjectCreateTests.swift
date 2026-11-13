// Tests of assistant-created Projects through the core: every send opts in to
// Project creation requests, the undo wrapper reaches the core and maps its
// Forbidden refusal, and the created-Project card's undo state follows the call.
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.creation.assistant-inferred
import Combine
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeProjectUndoClient: ChatActionsCoreClient, CreatedProjectUndoCoreClient {
    private(set) var undoneChats: [String] = []
    var failure: CoreError?

    func undoCreatedProject(chatId: String) async throws -> CreatedProjectRecord {
        undoneChats.append(chatId)
        if let failure { throw failure }
        return CreatedProjectRecord(requestId: "req", chatId: chatId, projectId: "project-1", focusId: "focus-1", name: "Kitchen renovation", kind: "hosted", subfolder: "", teamId: nil, undoAvailable: true)
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

final class CoreProjectCreateTests: XCTestCase {
    @MainActor
    private func makeActions() -> (CoreChatActions, FakeProjectUndoClient) {
        let actions = CoreChatActions(window: CoreChatWindow())
        let client = FakeProjectUndoClient()
        actions.attach(client: client, events: PassthroughSubject<ViewEventRecord, Never>().eraseToAnyPublisher())
        return (actions, client)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.creation.assistant-inferred
    func testSendOptionsOptInToProjectCreateRequests() {
        let options = CoreSendMapping.options()
        XCTAssertTrue(options.projectCreateRequests)
        XCTAssertEqual(options.machineProject, .unavailable)
        XCTAssertFalse(options.projectFileJobs)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.creation.assistant-inferred
    @MainActor
    func testUndoWrapperReachesTheCore() async throws {
        let (actions, client) = makeActions()
        let record = try await actions.undoCreatedProject(chatId: "chat-1")
        XCTAssertEqual(client.undoneChats, ["chat-1"])
        XCTAssertEqual(record.projectId, "project-1")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.creation.assistant-inferred
    @MainActor
    func testUndoForbiddenMapsToTypedError() async {
        let (actions, client) = makeActions()
        client.failure = .Forbidden
        do {
            _ = try await actions.undoCreatedProject(chatId: "chat-1")
            XCTFail("expected forbidden")
        } catch {
            XCTAssertEqual(error as? CoreCreatedProjectUndoError, .forbidden)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.creation.assistant-inferred
    @MainActor
    func testCardUndoStateFollowsTheCall() async {
        var calls: [String] = []
        let model = ProjectCreatedUndoModel(chatID: "chat-1") { calls.append($0) }
        XCTAssertTrue(model.canUndo)
        await model.performUndo()
        XCTAssertEqual(calls, ["chat-1"])
        XCTAssertTrue(model.isUndone)
        XCTAssertFalse(model.canUndo)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.creation.assistant-inferred
    @MainActor
    func testCardUndoFailureShowsErrorAndKeepsUndo() async {
        let model = ProjectCreatedUndoModel(chatID: "chat-1") { _ in throw CoreCreatedProjectUndoError.forbidden }
        await model.performUndo()
        XCTAssertTrue(model.failed)
        XCTAssertFalse(model.isUndone)
        XCTAssertTrue(model.canUndo)
        XCTAssertFalse(ProjectCreatedUndoModel(chatID: nil).canUndo)
    }
}
