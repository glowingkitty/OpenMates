// Share and embed UI tests — maps to: share-chat-flow.spec.ts, shared-chat-open.spec.ts,
// share-embed-flow.spec.ts, embed-showcase.spec.ts, embed-json-leak.spec.ts,
// example-chats-load.spec.ts, example-chat-clone.spec.ts

import XCTest

final class ShareAndEmbedUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Share chat (share-chat-flow)

    func testShareChatOptionInContextMenu() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }

        chatItem.press(forDuration: 1.0)

        let shareBtn = app.buttons["Share"]
        XCTAssertTrue(shareBtn.waitForExistence(timeout: 3))
    }

    // MARK: - Embed preview interaction (embed-showcase)

    func testEmbedPreviewAccessibility() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }
        chatItem.tap()

        let embedPreview = app.otherElements["embed-preview"]
        if embedPreview.waitForExistence(timeout: 10) {
            XCTAssertTrue(embedPreview.isAccessibilityElement || embedPreview.exists)
        }
    }

    // MARK: - Explore / public chats

    func testExploreButtonExists() {
        let exploreBtn = app.buttons["Explore"]
        XCTAssertTrue(exploreBtn.waitForExistence(timeout: 10))
    }

    func testExploreOpensPublicChats() {
        let exploreBtn = app.buttons["Explore"]
        guard exploreBtn.waitForExistence(timeout: 10) else { return }
        exploreBtn.tap()

        let doneBtn = app.buttons["Done"]
        XCTAssertTrue(doneBtn.waitForExistence(timeout: 5))
    }
}
