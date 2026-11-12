// Tests of `CoreChatWindow`, `CoreMessageMapper` and the chat view model's
// core message source (plan apple-client-core-migration A4 lane 3): the open
// chat's messages from the client core over an in-memory credential store
// (`InMemoryCredentialStore` from CoreSessionTests) and a temporary cache
// container. Core events are fed through `CoreSession.events`, the subject the
// core's relay publishes on. They cover the mapping of a full message, a
// cached then canonical window replacing the rows without re-mapping unchanged
// messages, a per-message update patching one row, events of another chat or a
// superseded open being ignored, unavailability and sign-out emptying the
// window, window calls settling typed instead of hanging, and `ChatViewModel`
// placing core windows and updates into its rows while keeping rows the Swift
// send path added locally. No network: the API host never resolves.
import Combine
import Foundation
import XCTest
@testable import OpenMates

final class CoreChatWindowTests: XCTestCase {
    private static let apiURL = "https://never-contact.example.invalid"
    private static let chatID = "0b6f3a52-6d1e-4c43-9a43-2f6a0c1d9e11"
    private static let otherChatID = "7c2e1d90-3b4a-4f5e-8a6b-1c2d3e4f5a6b"

    @MainActor
    private func makeWindow() throws -> (CoreChatWindow, CoreSession) {
        let container = FileManager.default.temporaryDirectory.path
        let name = "core-chat-window-\(UUID().uuidString)"
        let directory = (container as NSString).appendingPathComponent(name)
        addTeardownBlock { try? FileManager.default.removeItem(atPath: directory) }
        let session = try CoreSession(
            config: CoreConfig(
                apiUrl: Self.apiURL, appUrl: "https://app.example.invalid",
                cacheContainer: container, cacheDirectoryName: name),
            credentials: InMemoryCredentialStore())
        let window = CoreChatWindow()
        window.attach(session)
        return (window, session)
    }

    private static func metadata(createdAt: Int64?, piiMappings: [PiiMappingRecord] = []) -> MessageMetadataRecord {
        MessageMetadataRecord(
            createdAt: createdAt, updatedAt: createdAt.map { $0 + 30 }, appId: "travel",
            serverMessageId: "server-1", clientMessageId: "client-1", userMessageId: "user-1",
            storedStatus: "synced", modelName: "Synthetic model", category: "general_knowledge",
            hasThinking: true, thinkingTokenCount: 42, queueRevision: 2, queueMode: "after",
            queueDispatchStatus: "queued", queueDispatchMode: "auto", queueDispatchTaskId: "task-1",
            piiMappings: piiMappings)
    }

    private static func message(_ id: String, role: MessageRoleRecord = .assistant, content: String = "Tiles and lighting",
                                status: MessageStatusRecord = .complete, createdAt: Int64? = 1_700_000_000,
                                embeds: [EmbedRefRecord] = [],
                                piiMappings: [PiiMappingRecord] = []) -> MessageViewRecord {
        MessageViewRecord(
            id: id, role: role, status: status, content: content, sender: role == .assistant ? "Mate" : "",
            thinking: "", embeds: embeds, sendState: nil,
            metadata: metadata(createdAt: createdAt, piiMappings: piiMappings))
    }

    private static func window(_ messages: [MessageViewRecord], chatId: String = CoreChatWindowTests.chatID,
                               source: ChatWindowSourceRecord = .canonical, hasMoreBefore: Bool? = false) -> ChatWindowViewRecord {
        ChatWindowViewRecord(
            chatId: chatId, title: "Kitchen renovation", category: "general_knowledge", messages: messages,
            source: source, hasMoreBefore: hasMoreBefore, hasMoreAfter: false, historyComplete: hasMoreBefore != true,
            refreshing: source == .cached, piiRestoration: .pageLocal)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.shell.allowed-responsibilities
    @MainActor
    func testMapsAFullCoreMessageIncludingEmbedsPiiAndQueueFields() throws {
        let record = Self.message(
            "message-1", content: "Call Alex about the tiles",
            embeds: [EmbedRefRecord(id: "embed-1", kind: "sheets-sheet", appId: "sheets", skillId: "sheet",
                                    title: "Budget", description: "", status: "finished",
                                    dataJson: "{\"rows\":3}")],
            piiMappings: [PiiMappingRecord(placeholder: "[NAME_1]", original: "Alex", kind: "NAME")])
        let mapped = CoreMessageMapper.map(record, chatId: Self.chatID, fallbackCreatedAt: "")
        XCTAssertEqual(mapped.id, "message-1")
        XCTAssertEqual(mapped.chatId, Self.chatID)
        XCTAssertEqual(mapped.role, .assistant)
        XCTAssertEqual(mapped.content, "Call Alex about the tiles")
        XCTAssertNil(mapped.encryptedContent, "the core decrypts; no ciphertext reaches the shell")
        XCTAssertEqual(mapped.createdAt, CoreMessageMapper.seconds(1_700_000_000))
        XCTAssertEqual(mapped.updatedAt, CoreMessageMapper.seconds(1_700_000_030))
        XCTAssertEqual(mapped.appId, "travel")
        XCTAssertEqual(mapped.isStreaming, false)
        XCTAssertEqual(mapped.embedRefs?.first?.id, "embed-1")
        XCTAssertEqual(mapped.embedRefs?.first?.type, "sheets-sheet")
        XCTAssertEqual(mapped.embedRefs?.first?.status, "finished")
        XCTAssertEqual((mapped.embedRefs?.first?.data?["rows"]?.value as? NSNumber)?.intValue, 3)
        XCTAssertEqual(mapped.modelName, "Synthetic model")
        XCTAssertEqual(mapped.senderName, "Mate")
        XCTAssertEqual(mapped.category, "general_knowledge")
        XCTAssertEqual(mapped.piiMappings, [PIIMapping(placeholder: "[NAME_1]", original: "Alex", type: "NAME")])
        XCTAssertNil(mapped.thinkingContent)
        XCTAssertEqual(mapped.thinkingTokenCount, 42)
        XCTAssertEqual(mapped.serverMessageId, "server-1")
        XCTAssertEqual(mapped.userMessageId, "user-1")
        XCTAssertEqual(mapped.queueRevision, 2)
        XCTAssertEqual(mapped.queueMode, "after")
        XCTAssertEqual(mapped.queueDispatchStatus, "queued")
        XCTAssertEqual(mapped.queueDispatchMode, "auto")
        XCTAssertEqual(mapped.deliveryStatus, "synced")

        let streaming = CoreMessageMapper.map(Self.message("reply", status: .streaming, createdAt: nil),
                                              chatId: Self.chatID, fallbackCreatedAt: "2023-11-14T22:13:20Z")
        XCTAssertEqual(streaming.isStreaming, true)
        XCTAssertEqual(streaming.createdAt, "2023-11-14T22:13:20Z", "an unsaved reply keeps the core's order")
        XCTAssertNil(streaming.embedRefs)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.viewmodel.stream-updates
    @MainActor
    func testCachedThenCanonicalWindowReplacesOnceAndKeepsUnchangedMessages() throws {
        let (window, session) = try makeWindow()
        var changes: [CoreChatWindowChange] = []
        let subscription = window.changes.sink { changes.append($0) }
        defer { subscription.cancel() }
        let request = window.begin(chatId: Self.chatID)
        let first = Self.message("m1", role: .user, content: "Plan the kitchen", createdAt: 1_700_000_000)
        let second = Self.message("m2", content: "Start with the tiles", createdAt: 1_700_000_060)
        session.events.send(.chatWindow(request: request,
            window: Self.window([first, second], source: .cached, hasMoreBefore: true)))
        XCTAssertEqual(window.messages.map(\.id), ["m1", "m2"])
        XCTAssertEqual(window.source, .cached)
        XCTAssertTrue(window.hasOlderMessages)
        XCTAssertTrue(window.refreshing)
        XCTAssertEqual(window.title, "Kitchen renovation")
        XCTAssertEqual(window.mappedMessageCount, 2)

        let edited = Self.message("m2", content: "Start with the tiles, then lighting", createdAt: 1_700_000_060)
        let third = Self.message("m3", role: .user, content: "Thanks", createdAt: 1_700_000_120)
        session.events.send(.chatWindow(request: request, window: Self.window([first, edited, third])))
        XCTAssertEqual(window.messages.map(\.id), ["m1", "m2", "m3"])
        XCTAssertEqual(window.messages[1].content, "Start with the tiles, then lighting")
        XCTAssertEqual(window.source, .canonical)
        XCTAssertFalse(window.hasOlderMessages)
        XCTAssertEqual(window.mappedMessageCount, 4, "the unchanged first message is not mapped again")
        XCTAssertEqual(changes, [.window(chatId: Self.chatID, reason: .opened),
                                 .window(chatId: Self.chatID, reason: .updated)])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.stream-updates
    @MainActor
    func testMessageUpdatedPatchesOneMessageAndAppendsANewReply() throws {
        let (window, session) = try makeWindow()
        var changes: [CoreChatWindowChange] = []
        let subscription = window.changes.sink { changes.append($0) }
        defer { subscription.cancel() }
        let request = window.begin(chatId: Self.chatID)
        session.events.send(.chatWindow(request: request, window: Self.window([
            Self.message("m1", role: .user, content: "Plan the kitchen", createdAt: 1_700_000_000)])))
        let mappedAfterWindow = window.mappedMessageCount

        // A send uses its own, newer request id.
        let reply = Self.message("reply", content: "Start", status: .streaming, createdAt: nil)
        session.events.send(.messageUpdated(request: request + 1, chatId: Self.chatID, message: reply))
        XCTAssertEqual(window.messages.map(\.id), ["m1", "reply"])
        XCTAssertEqual(window.messages[1].createdAt, window.messages[0].createdAt)
        XCTAssertEqual(window.messages[1].isStreaming, true)

        let longer = Self.message("reply", content: "Start with the tiles", status: .streaming, createdAt: nil)
        session.events.send(.messageUpdated(request: request + 1, chatId: Self.chatID, message: longer))
        XCTAssertEqual(window.message(id: "reply")?.content, "Start with the tiles")
        XCTAssertEqual(window.messages.count, 2)
        XCTAssertEqual(window.mappedMessageCount, mappedAfterWindow + 2, "each update maps only its own message")
        XCTAssertEqual(changes.suffix(2), [.message(chatId: Self.chatID, messageId: "reply"),
                                           .message(chatId: Self.chatID, messageId: "reply")])

        // The same record again changes nothing.
        session.events.send(.messageUpdated(request: request + 1, chatId: Self.chatID, message: longer))
        XCTAssertEqual(window.mappedMessageCount, mappedAfterWindow + 2)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testEventsOfAnotherChatOrASupersededOpenAreIgnored() throws {
        let (window, session) = try makeWindow()
        let stale = window.begin(chatId: Self.chatID)
        let current = window.begin(chatId: Self.chatID)
        XCTAssertGreaterThan(current, stale)
        session.events.send(.chatWindow(request: stale, window: Self.window([Self.message("old")])))
        session.events.send(.chatWindow(request: current, window: Self.window([Self.message("other")],
                                                                               chatId: Self.otherChatID)))
        session.events.send(.messageUpdated(request: current, chatId: Self.otherChatID, message: Self.message("x")))
        XCTAssertTrue(window.messages.isEmpty)
        XCTAssertNil(window.source)

        session.events.send(.chatWindow(request: current, window: Self.window([Self.message("m1")])))
        XCTAssertEqual(window.messages.map(\.id), ["m1"])
        // Opening another chat empties the window before its first window arrives.
        window.begin(chatId: Self.otherChatID)
        XCTAssertTrue(window.messages.isEmpty)
        XCTAssertEqual(window.chatId, Self.otherChatID)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testUnavailableChatAndSignOutEmptyTheWindow() throws {
        let (window, session) = try makeWindow()
        var request = window.begin(chatId: Self.chatID)
        session.events.send(.chatWindow(request: request, window: Self.window([Self.message("m1")])))
        session.events.send(.chatUnavailable(chatId: Self.otherChatID))
        XCTAssertEqual(window.messages.count, 1, "another chat's unavailability is not this window's")
        session.events.send(.chatUnavailable(chatId: Self.chatID))
        XCTAssertTrue(window.messages.isEmpty)

        request = window.begin(chatId: Self.chatID)
        session.events.send(.chatWindow(request: request, window: Self.window([Self.message("m1")])))
        session.events.send(.session(event: .signedOut))
        XCTAssertTrue(window.messages.isEmpty)
        XCTAssertNil(window.chatId)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testWindowCallsSettleTypedInsteadOfHanging() async throws {
        let unattached = CoreChatWindow()
        let noCore = await unattached.open(chatId: Self.chatID)
        XCTAssertEqual(noCore, .noCore)

        let (window, session) = try makeWindow()
        try await session.start()
        // Signed out the core holds no account: the open is refused, typed, and
        // the caller's local shape applies.
        let refused = await window.open(chatId: Self.chatID)
        XCTAssertEqual(refused, .refused)
        XCTAssertNil(window.chatId)

        let request = window.begin(chatId: Self.chatID)
        let loaded = await window.loadOlder()
        XCTAssertFalse(loaded)
        XCTAssertNotNil(window.lastError)
        await window.close(request: request)
        XCTAssertNil(window.chatId)
        XCTAssertTrue(window.messages.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.viewmodel.stream-updates
    @MainActor
    func testChatViewModelShowsCoreWindowsAndPatchesStreamingReplies() throws {
        let (window, session) = try makeWindow()
        let model = ChatViewModel(coreWindow: window)
        model.chat = Chat(id: Self.chatID, title: "Kitchen renovation", lastMessageAt: nil, createdAt: "",
                          updatedAt: nil, isArchived: nil, isPinned: nil, appId: nil,
                          encryptedTitle: nil, encryptedChatKey: nil)
        // A pending send the frozen Swift send path added before the core knows it.
        let pending = CoreMessageMapper.map(Self.message("pending-send", role: .user, content: "And the lights?",
                                                         createdAt: 1_700_000_500),
                                            chatId: Self.chatID, fallbackCreatedAt: "")
        model.allMessages = [pending]

        let request = model.beginCoreWindow(chatId: Self.chatID)
        XCTAssertTrue(model.ownsCoreWindow(Self.chatID))
        session.events.send(.chatWindow(request: request, window: Self.window([
            Self.message("m1", role: .user, content: "Plan the kitchen", createdAt: 1_700_000_000),
            Self.message("m2", content: "Start with the tiles", createdAt: 1_700_000_060),
        ], hasMoreBefore: true)))
        XCTAssertEqual(model.messages.map(\.id), ["m1", "m2", "pending-send"])
        XCTAssertTrue(model.hasOlderMessages)
        XCTAssertFalse(model.isLoading)

        let revision = model.historyWindowRevision
        let reply = Self.message("reply", content: "Warm white", status: .streaming, createdAt: nil)
        session.events.send(.messageUpdated(request: request + 1, chatId: Self.chatID, message: reply))
        XCTAssertEqual(model.messages.last?.id, "reply")
        let longer = Self.message("reply", content: "Warm white LEDs", status: .streaming, createdAt: nil)
        session.events.send(.messageUpdated(request: request + 1, chatId: Self.chatID, message: longer))
        XCTAssertEqual(model.messages.last?.content, "Warm white LEDs")
        XCTAssertEqual(model.messages.filter { $0.id == "reply" }.count, 1)
        XCTAssertEqual(model.historyWindowRevision, revision, "a streaming update patches a row, not the window")

        // The canonical window now carries the send: the local row is replaced, not doubled.
        session.events.send(.chatWindow(request: request, window: Self.window([
            Self.message("m1", role: .user, content: "Plan the kitchen", createdAt: 1_700_000_000),
            Self.message("m2", content: "Start with the tiles", createdAt: 1_700_000_060),
            Self.message("pending-send", role: .user, content: "And the lights?", createdAt: 1_700_000_500),
            Self.message("reply", content: "Warm white LEDs", createdAt: 1_700_000_560),
        ])))
        XCTAssertEqual(model.messages.map(\.id), ["m1", "m2", "pending-send", "reply"])
        XCTAssertEqual(model.messages.last?.isStreaming, false)
        XCTAssertFalse(model.hasOlderMessages)

        model.closeCoreWindow()
        XCTAssertFalse(model.ownsCoreWindow(Self.chatID))
    }
}
