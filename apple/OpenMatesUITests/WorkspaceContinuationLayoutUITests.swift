import XCTest

@MainActor
final class WorkspaceContinuationLayoutUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testTallPhoneContinuationCardsFitBetweenBannerAndComposerOnAllThreeSurfaces() {
        for surface in surfaces {
            let app = launch(surface.component, variant: surface.variant, height: 844)
            let card = element(app, surface.card)
            XCTAssertTrue(card.waitForExistence(timeout: 10), surface.component)
            XCTAssertEqual(card.frame.width, 300, accuracy: 2, surface.component)
            XCTAssertEqual(card.frame.height, 200, accuracy: 2, surface.component)
            assertBetweenBannerAndComposer(card, surface: surface, app: app)
            attach(app, name: "\(surface.component)-tall-phone-expanded-continuation")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testShortViewportContinuationCardsStayCompactOnAllThreeSurfaces() {
        for surface in surfaces {
            let app = launch(surface.component, variant: surface.variant, height: 568)
            let card = element(app, surface.component == "welcome" ? "welcome-chat-compact-card-fixture-resume" : surface.card)
            XCTAssertTrue(card.waitForExistence(timeout: 10), surface.component)
            XCTAssertLessThan(card.frame.height, 100, surface.component)
            XCTAssertGreaterThanOrEqual(card.frame.height, 44)
            assertBetweenBannerAndComposer(card, surface: surface, app: app)
            attach(app, name: "\(surface.component)-short-viewport-compact-continuation")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.order.sidebar-header-match
    func testChatContinuationShowAllOpensRailAndSearchFindsActualSyntheticChat() {
        let app = launch("welcome", variant: "continuation", height: 844)
        let showAll = app.buttons["welcome-show-all-chats"]
        XCTAssertTrue(showAll.waitForExistence(timeout: 5)); XCTAssertTrue(showAll.isHittable)
        showAll.tap()
        let rail = element(app, "chat-history-panel")
        XCTAssertTrue(rail.waitForExistence(timeout: 5))
        let row = app.descendants(matching: .any).matching(NSPredicate(format:
            "identifier == 'chat-item-wrapper' AND value == %@", "user-chat:fixture-second")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        XCTAssertTrue(row.isHittable)
        app.buttons["chat-sidebar-close"].tap()
        let search = app.buttons["welcome-search-chats"]
        XCTAssertTrue(search.waitForExistence(timeout: 5)); XCTAssertTrue(search.isHittable)
        search.tap()
        let input = app.textFields["search-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        input.typeText("Telescope")
        let result = app.buttons.matching(identifier: "search-chat-item")
            .matching(NSPredicate(format: "label == %@", "Telescope research")).firstMatch
        XCTAssertTrue(result.waitForExistence(timeout: 8)); XCTAssertTrue(result.isHittable)
        result.tap()
        let selected = element(app, "dev-preview-local-action")
        let selection = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "open:fixture-second"), object: selected)
        XCTAssertEqual(XCTWaiter.wait(for: [selection], timeout: 5), .completed)
        XCTAssertFalse(input.exists, "Actual selection closes the search surface")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity,projects.access.explicit-context
    func testProjectsShowAllAndSearchUseProjectMetadataAndOpenProjectDetail() {
        let app = launch("projects", variant: "landing", height: 844)
        let showAll = app.buttons["projects-show-all"]
        XCTAssertTrue(showAll.waitForExistence(timeout: 5)); XCTAssertTrue(showAll.isHittable)
        showAll.tap()
        XCTAssertTrue(element(app, "projects-browse-list").waitForExistence(timeout: 5))
        let input = app.textFields["projects-browse-search"]
        XCTAssertTrue(input.waitForExistence(timeout: 5)); input.tap(); input.typeText("zz-no-match\n")
        XCTAssertFalse(app.buttons["project-card-preview-project"].exists)
        XCTAssertFalse(app.textFields["search-input"].exists, "Project browsing must not open chat search")
        app.buttons["projects-back-to-recent"].tap()
        let search = app.buttons["projects-search"]
        XCTAssertTrue(search.waitForExistence(timeout: 5)); XCTAssertTrue(search.isHittable)
        search.tap()
        XCTAssertTrue(input.waitForExistence(timeout: 5)); input.tap(); input.typeText("OpenMates\n")
        let card = app.buttons["project-card-preview-project"]
        XCTAssertTrue(card.waitForExistence(timeout: 5)); XCTAssertTrue(card.isHittable)
        card.tap()
        XCTAssertTrue(app.buttons["project-header-edit"].waitForExistence(timeout: 5), "The matched project must open its actual workspace detail")
        XCTAssertFalse(element(app, "projects-browse").exists)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testKeyboardShrinksProjectContinuationGapWithoutCoveringComposer() {
        let app = launch("projects", variant: "landing", height: 844)
        let input = app.textFields["project-input-textarea"]
        XCTAssertTrue(input.waitForExistence(timeout: 5)); input.tap()
        #if os(iOS)
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        #endif
        let card = app.buttons["project-card-preview-project"]
        XCTAssertLessThan(card.frame.height, 100)
        assertBetweenBannerAndComposer(card, surface: surfaces[2], app: app)
        attach(app, name: "projects-keyboard-reduces-continuation-gap")
    }

    private struct Surface {
        let component: String
        let variant: String
        let card: String
        let banner: String
        let composer: String
    }
    private var surfaces: [Surface] {
        [.init(component: "welcome", variant: "continuation", card: "welcome-chat-card-fixture-resume", banner: "continuation-inspiration", composer: "continuation-composer"),
         .init(component: "workflows", variant: "home", card: "workflow-landing-card", banner: "workflows-daily-inspiration-area", composer: "workflow-input-composer"),
         .init(component: "projects", variant: "landing", card: "project-card-preview-project", banner: "daily-inspiration-card", composer: "project-input-composer")]
    }
    private func assertBetweenBannerAndComposer(_ card: XCUIElement, surface: Surface, app: XCUIApplication) {
        let banner = element(app, surface.banner), composer = element(app, surface.composer)
        XCTAssertTrue(banner.exists); XCTAssertTrue(composer.exists)
        XCTAssertGreaterThanOrEqual(card.frame.minY, banner.frame.maxY - 1)
        XCTAssertLessThanOrEqual(card.frame.maxY, composer.frame.minY + 1)
        XCTAssertTrue(card.isHittable)
    }
    private func launch(_ component: String, variant: String, height: Int) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--dev-preview-variant", variant,
            "--dev-preview-width", "390", "--dev-preview-height", String(height),
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let root = element(app, "dev-preview-root")
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected")
        XCTAssertFalse(element(app, "dev-preview-error").exists)
        return app
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func attach(_ app: XCUIApplication, name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
}
