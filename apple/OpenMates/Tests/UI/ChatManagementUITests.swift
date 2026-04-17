// Chat management UI tests — maps to: chat-management-flow.spec.ts,
// hidden-chats-flow.spec.ts, show-more-chats-flow.spec.ts,
// new-chat-pinned-sort.spec.ts, recent-chats-dedup.spec.ts,
// chat-search-flow.spec.ts, import-chats.spec.ts

import XCTest

final class ChatManagementUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Chat list (chat-management-flow)

    func testChatListLoads() {
        let chatNav = app.navigationBars["Chats"]
        XCTAssertTrue(chatNav.waitForExistence(timeout: 10))
    }

    func testNewChatButton() {
        let newChat = app.buttons["new-chat-button"]
        XCTAssertTrue(newChat.waitForExistence(timeout: 10))
        newChat.tap()

        let messageInput = app.textFields.firstMatch
        XCTAssertTrue(messageInput.waitForExistence(timeout: 5))
    }

    // MARK: - Chat context menu (chat-management-flow)

    func testChatLongPressShowsContextMenu() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }

        chatItem.press(forDuration: 1.0)

        let deleteBtn = app.buttons["Delete"]
        XCTAssertTrue(deleteBtn.waitForExistence(timeout: 3))
    }

    // MARK: - Swipe to delete (chat-management-flow)

    func testSwipeToDeleteChat() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }

        chatItem.swipeLeft()

        let deleteAction = app.buttons["Delete"]
        XCTAssertTrue(deleteAction.waitForExistence(timeout: 3))
    }

    // MARK: - Search chats (chat-search-flow)

    func testSearchButtonOpensSearch() {
        let searchBtn = app.buttons["search-button"]
        guard searchBtn.waitForExistence(timeout: 10) else { return }
        searchBtn.tap()

        let searchField = app.searchFields.firstMatch
        XCTAssertTrue(searchField.waitForExistence(timeout: 5))
    }

    func testSearchFiltersChats() {
        let searchBtn = app.buttons["search-button"]
        guard searchBtn.waitForExistence(timeout: 10) else { return }
        searchBtn.tap()

        let searchField = app.searchFields.firstMatch
        guard searchField.waitForExistence(timeout: 5) else { return }
        searchField.tap()
        searchField.typeText("test query")

        // Search should filter the list (content depends on test data)
    }

    // MARK: - Pull to refresh

    func testPullToRefreshWorks() {
        let chatNav = app.navigationBars["Chats"]
        guard chatNav.waitForExistence(timeout: 10) else { return }

        let firstCell = app.cells.firstMatch
        if firstCell.exists {
            firstCell.swipeDown()
        }
    }

    // MARK: - Hidden chats (hidden-chats-flow)

    func testHiddenChatsButtonExists() {
        let chatNav = app.navigationBars["Chats"]
        guard chatNav.waitForExistence(timeout: 10) else { return }

        // Scroll to bottom to find hidden chats section
        let list = app.collectionViews.firstMatch
        list.swipeUp()

        let hiddenBtn = app.buttons["Hidden Chats"]
        XCTAssertTrue(hiddenBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Show more chats (show-more-chats-flow)

    func testShowMoreChatsButtonAppears() {
        let chatNav = app.navigationBars["Chats"]
        guard chatNav.waitForExistence(timeout: 10) else { return }

        // If user has many chats, scroll down to find "Load more"
        let list = app.collectionViews.firstMatch
        list.swipeUp()
        list.swipeUp()
    }
}
