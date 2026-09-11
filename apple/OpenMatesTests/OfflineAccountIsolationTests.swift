// Offline account isolation regression coverage uses only synthetic chats and
// per-test temporary SwiftData directories. No shared app container is opened.
// Account and API environment switches must never adopt another scope's cache,
// while returning to the original scope must preserve its queued offline work.
// Each server/account owns a distinct persistent container without schema changes.

import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class OfflineAccountIsolationTests: XCTestCase {
    private let development = URL(string: "https://dev.fixture.invalid")!
    private let production = URL(string: "https://fixture.invalid")!

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testDifferentAccountCannotReadPreviousAccountsChatsOrPendingActions() throws {
        try withTemporaryDirectory { directory in
            try seedAccount(directory: directory, userId: "account-a", apiBaseURL: development)
            let otherAccount = try OfflineStore(directory: directory, userId: "account-b", apiBaseURL: development)
            XCTAssertTrue(otherAccount.loadChats().isEmpty, "Account B must not adopt account A's chat cache")
            XCTAssertTrue(otherAccount.loadPendingActions().isEmpty, "Account B must not replay account A's queued work")
        }
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testDifferentServerCannotReadPreviousEnvironmentsChatsOrPendingActions() throws {
        try withTemporaryDirectory { directory in
            try seedAccount(directory: directory, userId: "account-a", apiBaseURL: development)
            let otherEnvironment = try OfflineStore(directory: directory, userId: "account-a", apiBaseURL: production)
            XCTAssertTrue(otherEnvironment.loadChats().isEmpty, "Production must not adopt development chat history")
            XCTAssertTrue(otherEnvironment.loadPendingActions().isEmpty, "Production must not replay development actions")
        }
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testReturningToSameAccountAndServerPreservesChatsAndPendingActions() throws {
        try withTemporaryDirectory { directory in
            try seedAccount(directory: directory, userId: "account-a", apiBaseURL: development)
            let reopened = try OfflineStore(directory: directory, userId: "account-a", apiBaseURL: development)
            XCTAssertEqual(reopened.loadChats().map(\.id), ["synthetic-owner-chat"])
            XCTAssertEqual(reopened.loadPendingActions().map(\.actionType), ["synthetic-offline-action"])
        }
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testSwitchingActiveScopeDetachesOldDataAndRetainsOriginalQueuedWork() throws {
        try withTemporaryDirectory { directory in
            try seedAccount(directory: directory, userId: "account-a", apiBaseURL: development)
            let store = try OfflineStore(directory: directory, userId: "account-a", apiBaseURL: development)
            let firstGeneration = store.scopeGeneration
            try store.activate(userId: "account-b", apiBaseURL: development)
            XCTAssertNotEqual(store.scopeGeneration, firstGeneration)
            XCTAssertTrue(store.loadChats().isEmpty)
            XCTAssertEqual(store.pendingActionCount, 0)
            store.deactivate()
            XCTAssertNil(store.activeScopeId)
            XCTAssertTrue(store.loadPendingActions().isEmpty)
            try store.activate(userId: "account-a", apiBaseURL: development)
            XCTAssertEqual(store.loadChats().map(\.id), ["synthetic-owner-chat"])
            XCTAssertEqual(store.pendingActionCount, 1)
        }
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testStoppedRetainedBridgeCannotDeleteOrQueueWork() throws {
        try withTemporaryDirectory { directory in
            try seedAccount(directory: directory, userId: "account-a", apiBaseURL: development)
            let store = try OfflineStore(directory: directory, userId: "account-a", apiBaseURL: development)
            let bridge = OfflineSyncBridge(chatStore: ChatStore(), offlineStore: store)
            bridge.stopSession()
            bridge.onChatDeleted("synthetic-owner-chat")
            bridge.queueDraftDelete(chatId: "synthetic-owner-chat")
            XCTAssertEqual(store.loadChats().count, 1)
            XCTAssertEqual(store.loadPendingActions().count, 1)
        }
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testRetainedBridgeCannotWriteIntoReactivatedScope() throws {
        try withTemporaryDirectory { directory in
            try seedAccount(directory: directory, userId: "account-a", apiBaseURL: development)
            let store = try OfflineStore(directory: directory, userId: "account-a", apiBaseURL: development)
            let chat = try XCTUnwrap(store.loadChats().first)
            let bridge = OfflineSyncBridge(chatStore: ChatStore(), offlineStore: store)
            try store.activate(userId: "account-b", apiBaseURL: development)
            bridge.onChatsReceived([chat])
            bridge.queueDraftDelete(chatId: chat.id)
            XCTAssertTrue(store.loadChats().isEmpty)
            XCTAssertTrue(store.loadPendingActions().isEmpty)
        }
    }

    private func seedAccount(directory: URL, userId: String, apiBaseURL: URL) throws {
        let store = try OfflineStore(directory: directory, userId: userId, apiBaseURL: apiBaseURL)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: Data("""
        {"id":"synthetic-owner-chat","title":"Synthetic account A chat","created_at":1770000000}
        """.utf8))
        store.persistChats([chat])
        store.queueOfflineAction(type: "synthetic-offline-action", payload: ["chat_id": chat.id])
        XCTAssertEqual(store.loadChats().count, 1, "Fixture persistence must succeed before isolation assertions")
        XCTAssertEqual(store.loadPendingActions().count, 1)
    }

    private func withTemporaryDirectory(_ body: (URL) throws -> Void) throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("OfflineAccountIsolation-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        try body(directory)
    }
}
