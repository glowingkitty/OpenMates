// Tests of the core-owned send, edit and stop of `ChatViewModel`
// (`ChatViewModel+CoreTurns.swift`): the turn goes to the core client with the
// reserved id and the mapped embeds, the view model keeps only presentation
// state (streaming flag, composer embeds, follow-ups, error) and appends no
// Swift message. The core calls go to a scripted fake client and its events to
// a local subject; the core's own send behaviour is covered by the crate tests.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.send.immediate-admission
import Combine
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeTurnsCoreClient: ChatActionsCoreClient {
    private(set) var calls: [String] = []
    private(set) var requests: [UInt64] = []
    private(set) var cancelSends = 0
    private(set) var sentOptions: [SendOptionsRecord] = []
    var sendFailure: CoreError?
    private var pending: [CheckedContinuation<SendReceiptRecord, Error>] = []

    static func receipt(chatId: String) -> SendReceiptRecord {
        SendReceiptRecord(
            window: ChatWindowViewRecord(
                chatId: chatId, title: "Kitchen renovation", category: "general_knowledge", messages: [],
                source: .canonical, hasMoreBefore: false, hasMoreAfter: false, historyComplete: true,
                refreshing: false, piiRestoration: .pageLocal),
            status: .completed, chatId: chatId, userMessageId: "user-1", assistantMessageId: "reply-1",
            queueMode: nil, queueRevision: nil)
    }

    var sendIsRunning: Bool { !pending.isEmpty }

    func finishSend(chatId: String) {
        guard !pending.isEmpty else { return }
        pending.removeFirst().resume(returning: Self.receipt(chatId: chatId))
    }

    private func turn(_ name: String, request: UInt64) async throws -> SendReceiptRecord {
        calls.append(name)
        requests.append(request)
        if let sendFailure { throw sendFailure }
        return try await withCheckedThrowingContinuation { pending.append($0) }
    }

    func sendWithOptions(request: UInt64, chatId: String?, text: String,
                         options: SendOptionsRecord) async throws -> SendReceiptRecord {
        sentOptions.append(options)
        return try await turn("send:\(text)", request: request)
    }

    func editMessageWithOptions(request: UInt64, chatId: String, messageId: String, text: String,
                                options: SendOptionsRecord) async throws -> SendReceiptRecord {
        sentOptions.append(options)
        return try await turn("edit:\(messageId):\(text)", request: request)
    }

    func retryLastTurn(request: UInt64, chatId: String) async throws -> ChatWindowViewRecord {
        try await turn("retry", request: request).window
    }

    func cancelSend() -> Bool {
        cancelSends += 1
        guard !pending.isEmpty else { return false }
        pending.removeFirst().resume(throwing: CoreError.Cancelled)
        return true
    }

    func stopReply(chatId: String, taskId: String) async throws { calls.append("stop:\(taskId)") }
    func deleteMessage(request: UInt64, chatId: String, messageId: String) async throws {}
    func deleteChat(chatId: String) async throws {}
    func answerConsent(chatId: String, requestId: String, approvedItemIds: [String]) async throws {}
    func forkChat(chatId: String, messageId: String, title: String?) async throws -> String { "fork" }
}

final class ChatViewModelCoreTurnsTests: XCTestCase {
    private static let chatID = "0b6f3a52-6d1e-4c43-9a43-2f6a0c1d9e11"
    private static let messageID = "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f"

    private struct Harness {
        let model: ChatViewModel
        let client: FakeTurnsCoreClient
        let events: PassthroughSubject<ViewEventRecord, Never>
        let actions: CoreChatActions
    }

    @MainActor
    private func makeHarness() -> Harness {
        let window = CoreChatWindow()
        let actions = CoreChatActions(window: window)
        let client = FakeTurnsCoreClient()
        let events = PassthroughSubject<ViewEventRecord, Never>()
        actions.attach(client: client, events: events.eraseToAnyPublisher())
        let model = ChatViewModel(coreWindow: window, coreActions: actions)
        model.chat = Chat(id: Self.chatID, title: "Kitchen renovation", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil, messagesV: 0)
        model.coreBinding.chatID = Self.chatID
        return Harness(model: model, client: client, events: events, actions: actions)
    }

    @MainActor
    private func waitUntil(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<1_000 where !condition() { await Task.yield() }
        XCTAssertTrue(condition(), "condition not reached", file: file, line: line)
    }

    private func pendingEmbed(status: String) -> ComposerPendingEmbed {
        let record = EmbedRecord(id: "embed-1", type: "file-file", status: .finished, data: nil,
            parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, hashedChatId: nil, createdAt: nil)
        return ComposerPendingEmbed(id: "embed-1", type: "file-file", referenceType: "", status: status,
            content: "body", textPreview: "preview", record: record, localData: nil,
            filename: "plan.pdf", size: 0, piiMappings: [])
    }

    /// Starts a send and admits it as the core's `Submitted` stream event does.
    @MainActor
    private func admit(_ harness: Harness, _ send: Task<Bool, Never>) async -> Bool {
        await waitUntil { harness.client.sendIsRunning }
        harness.events.send(.stream(request: harness.client.requests[0], chatId: Self.chatID, event: .submitted(
            chatId: Self.chatID, messageId: "user-1")))
        return await send.value
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    @MainActor
    func testSendInCoreOwnedChatGoesToCoreAndKeepsOnlyPresentationState() async {
        let harness = makeHarness()
        let model = harness.model
        model.pendingComposerEmbeds = [pendingEmbed(status: "finished")]
        model.followUpSuggestions = ["Which tiles?"]
        let send = Task<Bool, Never> { @MainActor in
            await model.sendMessage("Tiles for the kitchen", messageId: Self.messageID)
        }
        let accepted = await admit(harness, send)

        XCTAssertTrue(accepted)
        XCTAssertEqual(harness.client.calls, ["send:Tiles for the kitchen"])
        let options = try? XCTUnwrap(harness.client.sentOptions.first)
        XCTAssertEqual(options?.reservedMessageId, Self.messageID)
        XCTAssertEqual(options?.embeds.map(\.embedId), ["embed-1"])
        XCTAssertEqual(options?.embeds.first?.embedType, "file-file")
        XCTAssertTrue(model.isStreaming)
        XCTAssertTrue(model.pendingComposerEmbeds.isEmpty)
        XCTAssertTrue(model.followUpSuggestions.isEmpty)
        XCTAssertNil(model.error)
        XCTAssertTrue(model.allMessages.isEmpty, "the core, not Swift, stores the user message")
        XCTAssertTrue(model.messages.isEmpty)
        harness.client.finishSend(chatId: Self.chatID)
        await waitUntil { !model.isStreaming }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    @MainActor
    func testEditingMessageSendsEditTurnForThatMessageToCore() async {
        let harness = makeHarness()
        let model = harness.model
        let send = Task<Bool, Never> { @MainActor in
            await model.sendMessage("Better tiles", editingMessageID: "message-9")
        }
        let accepted = await admit(harness, send)

        XCTAssertTrue(accepted)
        XCTAssertEqual(harness.client.calls, ["edit:message-9:Better tiles"])
        XCTAssertTrue(model.allMessages.isEmpty)
        harness.client.finishSend(chatId: Self.chatID)
        await waitUntil { !model.isStreaming }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    @MainActor
    func testUnmappableComposerEmbedSetsErrorAndSendsNoTurn() async {
        let harness = makeHarness()
        let model = harness.model
        model.pendingComposerEmbeds = [pendingEmbed(status: "error")]

        let accepted = await model.sendMessage("Tiles for the kitchen")

        XCTAssertFalse(accepted)
        XCTAssertNotNil(model.error)
        XCTAssertTrue(harness.client.calls.isEmpty)
        XCTAssertFalse(model.isStreaming)
        XCTAssertEqual(model.pendingComposerEmbeds.count, 1, "the composer keeps what was not sent")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    @MainActor
    func testRejectedTurnSetsErrorAndLeavesStreamingOff() async {
        let harness = makeHarness()
        harness.client.sendFailure = .Offline

        let accepted = await harness.model.sendMessage("Tiles for the kitchen")

        XCTAssertFalse(accepted)
        XCTAssertEqual(harness.client.calls, ["send:Tiles for the kitchen"])
        XCTAssertNotNil(harness.model.error)
        XCTAssertFalse(harness.model.isStreaming)
        XCTAssertTrue(harness.model.allMessages.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    @MainActor
    func testStopCancelsTheRunningCoreSend() async {
        let harness = makeHarness()
        let model = harness.model
        let send = Task<Bool, Never> { @MainActor in await model.sendMessage("Tiles for the kitchen") }
        _ = await admit(harness, send)

        model.stopThroughCore(chatId: Self.chatID, taskId: nil)
        await waitUntil { harness.client.cancelSends == 1 }

        XCTAssertFalse(harness.client.sendIsRunning)
        XCTAssertFalse(harness.client.calls.contains { $0.hasPrefix("stop:") })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    @MainActor
    func testStopWithNothingRunningStopsTheReplyByKnownTaskId() async {
        let harness = makeHarness()

        harness.model.stopThroughCore(chatId: Self.chatID, taskId: "task-7")
        await waitUntil { harness.client.calls == ["stop:task-7"] }

        XCTAssertEqual(harness.client.cancelSends, 0)
        XCTAssertNil(harness.model.error)
    }
}
