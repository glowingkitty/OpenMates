// Tests of `CoreChatActions` (Core/CoreBridge/CoreChatActions.swift): a
// turn is accepted on the core's `Submitted` stream event while the call still
// runs, a refusal before dispatch is typed, options and receipts pass through,
// turns of different chats run in parallel and a second send into a chat is
// reported queued, stop uses `cancelSend` for this device's send and
// `stopReply` by the `taskAssigned` task id, action requests are newer than the
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
    private(set) var sentOptions: [SendOptionsRecord] = []
    private(set) var stoppedTasks: [String] = []
    var sendFailure: CoreError?
    var editFailure: CoreError?
    var forkedChatId = "5d1c2b3a-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    private var pending: [CheckedContinuation<SendReceiptRecord, Error>] = []

    static func window(chatId: String) -> ChatWindowViewRecord {
        ChatWindowViewRecord(
            chatId: chatId, title: "Kitchen renovation", category: "general_knowledge", messages: [],
            source: .canonical, hasMoreBefore: false, hasMoreAfter: false, historyComplete: true,
            refreshing: false, piiRestoration: .pageLocal)
    }

    static func receipt(chatId: String, status: SendStatusRecord = .completed, queueMode: SendQueueModeRecord? = nil,
                        queueRevision: UInt64? = nil) -> SendReceiptRecord {
        SendReceiptRecord(
            window: window(chatId: chatId), status: status, chatId: chatId, userMessageId: "user-1",
            assistantMessageId: status == .completed ? "reply-1" : nil, queueMode: queueMode,
            queueRevision: queueRevision)
    }

    var sendIsRunning: Bool { !pending.isEmpty }
    var runningCount: Int { pending.count }

    /// Ends the oldest running send as the core would.
    func finishSend(_ result: Result<SendReceiptRecord, CoreError>) {
        guard !pending.isEmpty else { return }
        pending.removeFirst().resume(with: result.mapError { $0 as Error })
    }

    func finishSend(chatId: String) {
        finishSend(.success(Self.receipt(chatId: chatId)))
    }

    private func turn(_ name: String, request: UInt64, chatId: String?, failure: CoreError?) async throws -> SendReceiptRecord {
        calls.append(name)
        requests.append(request)
        if let failure { throw failure }
        return try await withCheckedThrowingContinuation { continuation in
            pending.append(continuation)
        }
    }

    func sendWithOptions(request: UInt64, chatId: String?, text: String,
                         options: SendOptionsRecord) async throws -> SendReceiptRecord {
        sentOptions.append(options)
        return try await turn("send:\(text)", request: request, chatId: chatId, failure: sendFailure)
    }

    func editMessageWithOptions(request: UInt64, chatId: String, messageId: String, text: String,
                                options: SendOptionsRecord) async throws -> SendReceiptRecord {
        sentOptions.append(options)
        return try await turn("edit:\(messageId):\(text)", request: request, chatId: chatId,
                              failure: editFailure ?? sendFailure)
    }

    func retryLastTurn(request: UInt64, chatId: String) async throws -> ChatWindowViewRecord {
        try await turn("retry", request: request, chatId: chatId, failure: sendFailure).window
    }

    func cancelSend() -> Bool {
        cancelSends += 1
        guard !pending.isEmpty else { return false }
        finishSend(.failure(.Cancelled))
        return true
    }

    func stopReply(chatId: String, taskId: String) async throws {
        calls.append("stop:\(taskId)")
        stoppedTasks.append(taskId)
    }

    func deleteMessage(request: UInt64, chatId: String, messageId: String) async throws {
        calls.append("delete_message:\(messageId)")
        requests.append(request)
    }

    func deleteChat(chatId: String) async throws {
        calls.append("delete_chat:\(chatId)")
    }

    func answerConsent(chatId: String, requestId: String, approvedItemIds: [String]) async throws {
        calls.append("consent:\(chatId):\(requestId):\(approvedItemIds.joined(separator: ","))")
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
        client.finishSend(chatId: Self.chatID)
        await waitUntil { !recorder.ends.isEmpty }
        XCTAssertEqual(recorder.ends, [CoreTurnEnd(
            outcome: .completed, wasAccepted: true, receipt: FakeChatActionsClient.receipt(chatId: Self.chatID))])
        XCTAssertTrue(actions.activeTurns.isEmpty)
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
        XCTAssertTrue(actions.activeTurns.isEmpty)
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
        let stopped = try? await actions.stop(chatId: Self.chatID)
        XCTAssertEqual(stopped, .cancelledSend)
        let acceptance = await start.value
        XCTAssertEqual(acceptance, .cancelled)
        XCTAssertEqual(client.cancelSends, 1)
        XCTAssertEqual(recorder.ends, [CoreTurnEnd(outcome: .cancelled, wasAccepted: false)])
        let again = try? await actions.stop(chatId: Self.chatID)
        XCTAssertEqual(again, .nothingToStop, "nothing runs any more")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testSecondTurnIsNotRefusedAndRequestsAreNewerThanTheOpen() async {
        let (actions, client, events, window) = makeActions()
        let openRequest = window.begin(chatId: Self.chatID)
        let start = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "First"), chatId: Self.chatID) { _ in }
        }
        await waitUntil { client.sendIsRunning }
        XCTAssertGreaterThan(client.requests[0], openRequest)
        let recorder = TurnEndRecorder()
        let second = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "Second"), chatId: Self.chatID) { recorder.ends.append($0) }
        }
        await waitUntil { client.runningCount == 2 }
        XCTAssertEqual(actions.activeTurns.count, 2, "the core, not the shell, decides to queue")
        events.send(.stream(request: client.requests[0] &+ 5, chatId: Self.chatID, event: .submitted(
            chatId: Self.chatID, messageId: "other")))
        XCTAssertFalse(actions.turnMessageIDs.contains("other"), "events of another request are ignored")
        client.finishSend(chatId: Self.chatID)
        client.finishSend(.success(FakeChatActionsClient.receipt(
            chatId: Self.chatID, status: .queued, queueMode: .followUp, queueRevision: 3)))
        let firstResult = await start.value
        let secondResult = await second.value
        XCTAssertEqual(firstResult, .accepted)
        XCTAssertEqual(secondResult, .accepted)
        XCTAssertEqual(client.calls, ["send:First", "send:Second"])
        XCTAssertEqual(recorder.ends.count, 1)
        XCTAssertTrue(recorder.ends[0].isQueued)
        XCTAssertEqual(recorder.ends[0].receipt?.queueMode, .followUp)
        XCTAssertEqual(recorder.ends[0].receipt?.queueRevision, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testTurnsOfDifferentChatsRunInParallel() async {
        let (actions, client, _, _) = makeActions()
        let otherChat = "7a1d4c20-2b3e-4f5a-9c6d-0e1f2a3b4c5d"
        let first = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "Tiles"), chatId: Self.chatID) { _ in }
        }
        let second = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "Paint"), chatId: otherChat) { _ in }
        }
        await waitUntil { client.runningCount == 2 }
        XCTAssertTrue(actions.hasActiveTurn(in: Self.chatID))
        XCTAssertTrue(actions.hasActiveTurn(in: otherChat))
        client.finishSend(chatId: Self.chatID)
        client.finishSend(chatId: otherChat)
        let results = [await first.value, await second.value]
        XCTAssertEqual(results, [.accepted, .accepted])
        XCTAssertTrue(actions.activeTurns.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testOptionsAndReceiptPassThroughUnchanged() async {
        let (actions, client, _, _) = makeActions()
        let options = SendOptionsRecord(
            piiDetection: false, incognito: false, slug: nil, reservedChatId: Self.chatID,
            reservedMessageId: "user-1", embeds: [SendEmbedRecord(embedId: "embed-1", embedType: "image", referenceType: nil,
                                                                  status: "finished", content: nil, textPreview: nil,
                                                                  childEmbedIds: nil)],
            excludedPiiOriginals: ["Ada"], excludedPiiPlaceholders: ["[NAME_1]"],
            piiMappings: [PiiMappingRecord(placeholder: "[EMAIL_1]", original: "ada@example.org", kind: "EMAIL")],
            projectId: "project-1")
        let recorder = TurnEndRecorder()
        let start = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "Plan", options: options), chatId: nil) { recorder.ends.append($0) }
        }
        await waitUntil { client.sendIsRunning }
        XCTAssertEqual(client.sentOptions, [options])
        XCTAssertTrue(actions.hasActiveTurn(in: Self.chatID), "a reserved chat id names the new chat's turn")
        let receipt = FakeChatActionsClient.receipt(chatId: Self.chatID)
        client.finishSend(.success(receipt))
        _ = await start.value
        XCTAssertEqual(recorder.ends, [CoreTurnEnd(outcome: .completed, wasAccepted: true, receipt: receipt)])
        XCTAssertFalse(recorder.ends[0].isQueued)
        XCTAssertTrue(actions.turnMessageIDs.isSuperset(of: ["user-1", "reply-1"]))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testEditRejectSurfacesTheTypedErrorAndKeepsLastError() async {
        let (actions, client, _, _) = makeActions()
        let rejection = CoreError.Invalid(message: "An edit cannot start an incognito chat.")
        client.editFailure = rejection
        let options = SendOptionsRecord(incognito: true)
        let recorder = TurnEndRecorder()
        let acceptance = await actions.startTurn(.edit(messageId: "user-1", text: "Matte", options: options),
                                                 chatId: Self.chatID) { recorder.ends.append($0) }
        XCTAssertEqual(acceptance, .rejected(rejection))
        XCTAssertEqual(client.sentOptions, [options])
        XCTAssertEqual(recorder.ends, [CoreTurnEnd(outcome: .failed(rejection), wasAccepted: false)])
        XCTAssertEqual(actions.lastError, rejection)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.viewmodel.stream-updates
    @MainActor
    func testTaskAssignedIsTrackedAndAContinuationReplacesIt() async {
        let (actions, _, events, _) = makeActions()
        XCTAssertNil(actions.taskId(for: Self.chatID))
        events.send(.stream(request: 99, chatId: Self.chatID, event: .taskAssigned(
            chatId: Self.chatID, messageId: "user-1", taskId: "task-1")))
        XCTAssertEqual(actions.taskId(for: Self.chatID), "task-1")
        events.send(.stream(request: 99, chatId: Self.chatID, event: .taskAssigned(
            chatId: Self.chatID, messageId: "user-1", taskId: "task-2")))
        XCTAssertEqual(actions.taskId(for: Self.chatID), "task-2")
        events.send(.stream(request: 99, chatId: Self.chatID, event: .completed(
            chatId: Self.chatID, messageId: "reply-1", content: "Done")))
        XCTAssertNil(actions.taskId(for: Self.chatID), "a finished reply has no task to stop")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testStopUsesStopReplyForAReplyThisCallDidNotStart() async throws {
        let (actions, client, events, _) = makeActions()
        let none = try await actions.stop(chatId: Self.chatID)
        XCTAssertEqual(none, .nothingToStop)
        events.send(.stream(request: 99, chatId: Self.chatID, event: .taskAssigned(
            chatId: Self.chatID, messageId: "user-9", taskId: "task-7")))
        let stopped = try await actions.stop(chatId: Self.chatID)
        XCTAssertEqual(stopped, .stoppedReply(taskId: "task-7"))
        XCTAssertEqual(client.stoppedTasks, ["task-7"])
        XCTAssertEqual(client.cancelSends, 0, "no own send runs, so cancelSend is not used")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testStopCancelsTheOwnSendEvenWhenATaskIdIsKnown() async throws {
        let (actions, client, events, _) = makeActions()
        let start = Task<CoreTurnAcceptance, Never> { @MainActor in
            await actions.startTurn(.send(text: "Tiles"), chatId: Self.chatID) { _ in }
        }
        await waitUntil { client.sendIsRunning }
        events.send(.stream(request: client.requests[0], chatId: Self.chatID, event: .taskAssigned(
            chatId: Self.chatID, messageId: "user-1", taskId: "task-1")))
        let stopped = try await actions.stop(chatId: Self.chatID)
        XCTAssertEqual(stopped, .cancelledSend)
        XCTAssertEqual(client.cancelSends, 1)
        XCTAssertTrue(client.stoppedTasks.isEmpty)
        let acceptance = await start.value
        XCTAssertEqual(acceptance, .cancelled)
        XCTAssertNil(actions.taskId(for: Self.chatID), "the ended turn leaves no task id")
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
        events.send(.stream(request: 99, chatId: Self.chatID, event: .taskAssigned(
            chatId: Self.chatID, messageId: "user-3", taskId: "task-3")))
        XCTAssertEqual(actions.taskId(for: Self.chatID), "task-3")
        events.send(.session(event: .signedOut))
        XCTAssertTrue(actions.turnMessageIDs.isEmpty)
        XCTAssertNil(actions.taskId(for: Self.chatID))
        XCTAssertNil(actions.lastError)
        client.finishSend(chatId: Self.chatID)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testAnAppWithoutACoreReportsIt() async {
        let actions = CoreChatActions(window: CoreChatWindow())
        XCTAssertFalse(actions.isAttached)
        do {
            try await actions.stop(chatId: Self.chatID)
            XCTFail("stop must throw without a core")
        } catch {
            XCTAssertEqual(error as? CoreChatActionsError, .noCore)
        }
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

    private static func consentItem(_ id: String) -> EmbedRefRecord {
        EmbedRefRecord(id: id, kind: "memory", appId: "app", skillId: "", title: "Item \(id)",
                       description: "", status: "finished", dataJson: "{}")
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.selection.source-scoped
    @MainActor
    func testConsentEventPublishesAndAnswerSendsSelectedIdsThenClears() async throws {
        let (actions, client, events, _) = makeActions()
        let sent = Task { @MainActor in
            await actions.startTurn(.send(text: "hi"), chatId: Self.chatID) { _ in }
        }
        await waitUntil { client.sendIsRunning }
        events.send(.stream(request: client.requests[0], chatId: Self.chatID, event: .consent(
            requestId: "req-1", items: [Self.consentItem("a"), Self.consentItem("b")])))
        XCTAssertEqual(actions.pendingConsent[Self.chatID]?.requestId, "req-1")
        XCTAssertEqual(actions.pendingConsent[Self.chatID]?.items.map(\.id), ["a", "b"])
        try await actions.answerConsent(chatId: Self.chatID, requestId: "req-1", approvedItemIds: ["b"])
        XCTAssertTrue(client.calls.contains("consent:\(Self.chatID):req-1:b"))
        XCTAssertNil(actions.pendingConsent[Self.chatID])
        client.finishSend(chatId: Self.chatID)
        _ = await sent.value
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.selection.source-scoped
    @MainActor
    func testTurnEndClearsAPendingConsentRequest() async {
        let (actions, client, events, window) = makeActions()
        let sent = Task { @MainActor in
            await actions.startTurn(.send(text: "hi"), chatId: Self.chatID) { _ in }
        }
        await waitUntil { client.sendIsRunning }
        let request = client.requests[0]
        events.send(.stream(request: request, chatId: Self.chatID, event: .consent(
            requestId: "req-2", items: [Self.consentItem("a")])))
        XCTAssertNotNil(actions.pendingConsent[Self.chatID])
        client.finishSend(chatId: Self.chatID)
        _ = await sent.value
        XCTAssertNil(actions.pendingConsent[Self.chatID])
        _ = window
    }
}
