// Tests of `CoreChatActions` (Core/CoreBridge/CoreChatActions.swift): a
// turn is accepted on the core's `Submitted` stream event while the call still
// runs, a refusal before dispatch is typed, cancel reaches `cancelSend`, a
// second turn is refused while one runs, action requests are newer than the
// window's open request, the menu actions pass their ids and an app without a
// core reports it. The core calls go to a scripted fake (`FakeChatActionsClient`)
// and its events to a local subject; the core's send, edit and delete
// behaviour is covered by the crate tests.
import Combine
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeChatActionsClient: ChatActionsCoreClient {
    private(set) var calls: [String] = []
    private(set) var requests: [UInt64] = []
    private(set) var cancelSends = 0
    var sendFailure: CoreError?
    var forkedChatId = "5d1c2b3a-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    private var pendingSend: CheckedContinuation<ChatWindowViewRecord, Error>?

    static func window(chatId: String) -> ChatWindowViewRecord {
        ChatWindowViewRecord(
            chatId: chatId, title: "Kitchen renovation", category: "general_knowledge", messages: [],
            source: .canonical, hasMoreBefore: false, hasMoreAfter: false, historyComplete: true,
            refreshing: false, piiRestoration: .pageLocal)
    }

    var sendIsRunning: Bool { pendingSend != nil }

    /// Ends the running send as the core would.
    func finishSend(_ result: Result<ChatWindowViewRecord, CoreError>) {
        let pending = pendingSend
        pendingSend = nil
        pending?.resume(with: result.mapError { $0 as Error })
    }

    private func turn(_ name: String, request: UInt64) async throws -> ChatWindowViewRecord {
        calls.append(name)
        requests.append(request)
        if let sendFailure { throw sendFailure }
        return try await withCheckedThrowingContinuation { continuation in
            pendingSend = continuation
        }
    }

    func send(request: UInt64, chatId: String?, text: String) async throws -> ChatWindowViewRecord {
        try await turn("send:\(text)", request: request)
    }

    func editMessage(request: UInt64, chatId: String, messageId: String, text: String) async throws -> ChatWindowViewRecord {
        try await turn("edit:\(messageId):\(text)", request: request)
    }

    func retryLastTurn(request: UInt64, chatId: String) async throws -> ChatWindowViewRecord {
        try await turn("retry", request: request)
    }

    func cancelSend() -> Bool {
        cancelSends += 1
        guard pendingSend != nil else { return false }
        finishSend(.failure(.Cancelled))
        return true
    }

    func stopReply(chatId: String, taskId: String) async throws {
        calls.append("stop:\(taskId)")
    }

    func deleteMessage(request: UInt64, chatId: String, messageId: String) async throws {
        calls.append("delete_message:\(messageId)")
        requests.append(request)
    }

    func deleteChat(chatId: String) async throws {
        calls.append("delete_chat:\(chatId)")
    }

    func forkChat(chatId: String, messageId: String, title: String?) async throws -> String {
        calls.append("fork:\(messageId):\(title ?? "")")
        return forkedChatId
    }
}

/// Collects turn ends (a reference, so `@MainActor` closures may append).
@MainActor
private final class TurnEndRecorder {
    var ends: [CoreTurnEnd] = []
}

final class CoreChatActionsTests: XCTestCase {
    private static let chatID = "0b6f3a52-6d1e-4c43-9a43-2f6a0c1d9e11"

    @MainActor
    private func makeActions() -> (CoreChatActions, FakeChatActionsClient, PassthroughSubject<ViewEventRecord, Never>, CoreChatWindow) {
        let window = CoreChatWindow()
        let actions = CoreChatActions(window: window)
        let client = FakeChatActionsClient()
        let events = PassthroughSubject<ViewEventRecord, Never>()
        actions.attach(client: client, events: events.eraseToAnyPublisher())
        return (actions, client, events, window)
    }

    @MainActor
    private func waitUntil(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<1_000 where !condition() {
            await Task.yield()
        }
        XCTAssertTrue(condition(), "condition not reached", file: file, line: line)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.viewmodel.stream-updates
    @MainActor
    func testTurnIsAcceptedOnSubmittedWhileTheReplyStillStreams() async {
        let (actions, client, events, _) = makeActions()
        let recorder = TurnEndRecorder()
        let start = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "Tiles for the kitchen"), chatId: Self.chatID) { recorder.ends.append($0) }
        }
        await waitUntil { client.sendIsRunning }
        XCTAssertEqual(client.calls, ["send:Tiles for the kitchen"])
        XCTAssertTrue(actions.hasActiveTurn(in: Self.chatID))
        let request = client.requests[0]
        events.send(.stream(request: request, chatId: Self.chatID, event: .started(
            chatId: Self.chatID, messageId: "user-1", expectsReply: true)))
        events.send(.stream(request: request, chatId: Self.chatID, event: .submitted(
            chatId: Self.chatID, messageId: "user-1")))
        let acceptance = await start.value
        XCTAssertEqual(acceptance, .accepted)
        XCTAssertTrue(recorder.ends.isEmpty, "the turn still runs after acceptance")
        XCTAssertTrue(actions.turnMessageIDs.contains("user-1"))

        events.send(.stream(request: request, chatId: Self.chatID, event: .completed(
            chatId: Self.chatID, messageId: "reply-1", content: "Use matte tiles.")))
        client.finishSend(.success(FakeChatActionsClient.window(chatId: Self.chatID)))
        await waitUntil { !recorder.ends.isEmpty }
        XCTAssertEqual(recorder.ends, [CoreTurnEnd(outcome: .completed, wasAccepted: true)])
        XCTAssertNil(actions.activeTurn)
        XCTAssertTrue(actions.turnMessageIDs.contains("reply-1"))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testRefusalBeforeDispatchIsTypedAndEndsTheTurn() async {
        let (actions, client, _, _) = makeActions()
        client.sendFailure = .Offline
        let recorder = TurnEndRecorder()
        let acceptance = await actions.startTurn(.edit(messageId: "user-1", text: "Matte tiles"), chatId: Self.chatID) {
            recorder.ends.append($0)
        }
        XCTAssertEqual(acceptance, .rejected(.Offline))
        XCTAssertEqual(client.calls, ["edit:user-1:Matte tiles"])
        XCTAssertEqual(recorder.ends, [CoreTurnEnd(outcome: .failed(.Offline), wasAccepted: false)])
        XCTAssertNil(actions.activeTurn)
        XCTAssertEqual(CoreChatActions.userMessage(for: CoreError.Offline), AppStrings.reconnecting)
        XCTAssertNil(CoreChatActions.userMessage(for: CoreError.Cancelled))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testCancelStopsTheRunningTurnThroughCancelSend() async {
        let (actions, client, _, _) = makeActions()
        let recorder = TurnEndRecorder()
        let start = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.retry, chatId: Self.chatID) { recorder.ends.append($0) }
        }
        await waitUntil { client.sendIsRunning }
        XCTAssertTrue(actions.cancel())
        let acceptance = await start.value
        XCTAssertEqual(acceptance, .cancelled)
        XCTAssertEqual(client.cancelSends, 1)
        XCTAssertEqual(recorder.ends, [CoreTurnEnd(outcome: .cancelled, wasAccepted: false)])
        XCTAssertFalse(actions.cancel(), "nothing runs any more")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testSecondTurnIsRefusedWhileOneRunsAndRequestsAreNewerThanTheOpen() async {
        let (actions, client, events, window) = makeActions()
        let openRequest = window.begin(chatId: Self.chatID)
        let start = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "First"), chatId: Self.chatID) { _ in }
        }
        await waitUntil { client.sendIsRunning }
        XCTAssertGreaterThan(client.requests[0], openRequest)
        let second = await actions.startTurn(.send(text: "Second"), chatId: Self.chatID) { _ in }
        XCTAssertEqual(second, .busy)
        events.send(.stream(request: client.requests[0] &+ 1, chatId: Self.chatID, event: .submitted(
            chatId: Self.chatID, messageId: "other")))
        XCTAssertFalse(actions.turnMessageIDs.contains("other"), "events of another request are ignored")
        client.finishSend(.success(FakeChatActionsClient.window(chatId: Self.chatID)))
        let first = await start.value
        XCTAssertEqual(first, .accepted)
        XCTAssertEqual(client.calls, ["send:First"])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.shell.allowed-responsibilities
    @MainActor
    func testMenuActionsPassTheirIdsAndSignOutForgetsTurnIds() async throws {
        let (actions, client, events, window) = makeActions()
        let openRequest = window.begin(chatId: Self.chatID)
        try await actions.deleteMessage(chatId: Self.chatID, messageId: "user-2")
        try await actions.deleteChat(chatId: Self.chatID)
        try await actions.stopReply(chatId: Self.chatID, taskId: "task-1")
        let forked = try await actions.forkChat(chatId: Self.chatID, messageId: "reply-1", title: "Kitchen plan")
        XCTAssertEqual(forked, client.forkedChatId)
        XCTAssertEqual(client.calls, ["delete_message:user-2", "delete_chat:\(Self.chatID)", "stop:task-1",
                                      "fork:reply-1:Kitchen plan"])
        XCTAssertGreaterThan(client.requests[0], openRequest)

        let start = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "Grout"), chatId: Self.chatID) { _ in }
        }
        await waitUntil { client.sendIsRunning }
        events.send(.stream(request: client.requests.last ?? 0, chatId: Self.chatID, event: .admitted(
            chatId: Self.chatID, messageId: "user-3")))
        _ = await start.value
        XCTAssertTrue(actions.turnMessageIDs.contains("user-3"))
        events.send(.session(event: .signedOut))
        XCTAssertTrue(actions.turnMessageIDs.isEmpty)
        client.finishSend(.success(FakeChatActionsClient.window(chatId: Self.chatID)))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testAnAppWithoutACoreReportsIt() async {
        let actions = CoreChatActions(window: CoreChatWindow())
        XCTAssertFalse(actions.isAttached)
        let acceptance = await actions.startTurn(.send(text: "Hello"), chatId: Self.chatID) { _ in }
        XCTAssertEqual(acceptance, .noCore)
        do {
            try await actions.deleteChat(chatId: Self.chatID)
            XCTFail("deleteChat must throw without a core")
        } catch let error as CoreChatActionsError {
            XCTAssertEqual(error, .noCore)
        } catch {
            XCTFail("unexpected error \(error)")
        }
    }
}
