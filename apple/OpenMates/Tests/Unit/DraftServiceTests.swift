// DraftService unit tests — validates draft save, load, clear, and debounce.

import XCTest
@testable import OpenMates

final class DraftServiceTests: XCTestCase {

    override func setUp() {
        super.setUp()
        UserDefaults.standard.removeObject(forKey: "openmates.drafts")
    }

    override func tearDown() {
        UserDefaults.standard.removeObject(forKey: "openmates.drafts")
        super.tearDown()
    }

    @MainActor func testSaveAndLoadDraft() async {
        let service = DraftService.shared
        service.updateDraft("Hello draft", chatId: "chat-1")
        // Wait for debounce
        try? await Task.sleep(for: .seconds(1))

        let loaded = service.loadDraft(chatId: "chat-1")
        XCTAssertEqual(loaded, "Hello draft")
    }

    @MainActor func testClearDraft() async {
        let service = DraftService.shared
        service.updateDraft("To be cleared", chatId: "chat-2")
        try? await Task.sleep(for: .seconds(1))

        service.clearDraft(chatId: "chat-2")
        let loaded = service.loadDraft(chatId: "chat-2")
        XCTAssertEqual(loaded, "")
    }

    @MainActor func testHasDraft() async {
        let service = DraftService.shared
        XCTAssertFalse(service.hasDraft(chatId: "chat-3"))

        service.updateDraft("Draft content", chatId: "chat-3")
        try? await Task.sleep(for: .seconds(1))

        XCTAssertTrue(service.hasDraft(chatId: "chat-3"))
    }

    @MainActor func testClearAll() async {
        let service = DraftService.shared
        service.updateDraft("Draft A", chatId: "chat-a")
        service.updateDraft("Draft B", chatId: "chat-b")
        try? await Task.sleep(for: .seconds(1))

        service.clearAll()
        XCTAssertEqual(service.chatIdsWithDrafts().count, 0)
    }

    @MainActor func testEmptyDraftNotStored() async {
        let service = DraftService.shared
        service.updateDraft("   ", chatId: "chat-empty")
        try? await Task.sleep(for: .seconds(1))

        XCTAssertFalse(service.hasDraft(chatId: "chat-empty"))
    }
}
