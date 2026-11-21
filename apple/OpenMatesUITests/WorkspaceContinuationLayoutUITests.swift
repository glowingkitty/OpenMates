import XCTest

@MainActor
final class WorkspaceContinuationLayoutUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testTallPhoneContinuationCardsFitBetweenHeadingAndComposerOnAllThreeSurfaces() {
        for surface in surfaces {
            let app = launch(surface.component, variant: surface.variant, height: 844)
            let card = element(app, surface.card)
            XCTAssertTrue(card.waitForExistence(timeout: 10), surface.component)
            XCTAssertEqual(card.frame.width, 300, accuracy: 2, surface.component)
            XCTAssertEqual(card.frame.height, 200, accuracy: 2, surface.component)
            assertBetweenHeadingAndComposer(card, surface: surface, app: app)
            attach(app, name: "\(surface.component)-tall-phone-expanded-continuation")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testOrdinaryTallPhoneUsesExpandedCardsBelowHeadingOnAllThreeSurfaces() {
        for surface in surfaces {
            let app = launch(surface.component, variant: surface.variant, height: 744)
            let card = element(app, surface.card)
            XCTAssertTrue(card.waitForExistence(timeout: 10), surface.component)
            XCTAssertEqual(card.frame.height, 200, accuracy: 2, surface.component)
            assertBetweenHeadingAndComposer(card, surface: surface, app: app)
            let links = app.buttons[surface.component == "welcome" ? "welcome-show-all-chats"
                : surface.component == "projects" ? "projects-show-all" : "workflows-show-all"]
            // Web start row: the browse links are the row's last tile, reached by scrolling the row.
            revealRowItem(links, rowY: card.frame.midY, app: app)
            XCTAssertTrue(links.isHittable, "The row's actions tile must be reachable")
            attach(app, name: "\(surface.component)-ordinary-744-phone-expanded")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testExpandedChatCarouselKeepsBottomShadowInsideHorizontalClip() {
        let app = launch("welcome", variant: "continuation", height: 744)
        let card = app.buttons["welcome-chat-card-fixture-resume"]
        let carousel = app.scrollViews["welcome-chat-cards-carousel"]
        let canvas = element(app, "dev-component-preview-bounds")
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        XCTAssertTrue(carousel.exists)
        XCTAssertTrue(card.isHittable)
        XCTAssertEqual(card.frame.width, 300, accuracy: 2)
        XCTAssertEqual(card.frame.height, 200, accuracy: 2)
        XCTAssertEqual(carousel.frame.width, canvas.frame.width, accuracy: 1,
                       "Shadow clearance must preserve the original horizontal scroll viewport")
        XCTAssertTrue(carousel.frame.contains(card.frame))
        XCTAssertGreaterThanOrEqual(carousel.frame.maxY - card.frame.maxY, 33,
                                    "The tall card shadow needs the web's 34pt bottom reserve inside the clipping viewport")
        assertBetweenHeadingAndComposer(card, surface: surfaces[0], app: app)
        XCTAssertLessThanOrEqual(carousel.frame.maxY, element(app, surfaces[0].composer).frame.minY + 1,
                                 "Shadow reserve must remain above the real composer")
        let geometry = XCTAttachment(string: "card=\(card.frame);carousel=\(carousel.frame);canvas=\(canvas.frame)")
        geometry.name = "Expanded continuation shadow clip geometry"
        geometry.lifetime = .keepAlways
        add(geometry)
        let crop = XCTAttachment(screenshot: carousel.screenshot())
        crop.name = "Expanded continuation real card and full bottom shadow reserve"
        crop.lifetime = .keepAlways
        add(crop)
        attach(app, name: "Expanded continuation shadow inside inspiration and composer boundaries")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testShortViewportContinuationCardsStayCompactOnAllThreeSurfaces() {
        for surface in surfaces {
            // No banner any more (web start row): 568pt now fits the large cards, so the
            // compact fallback is checked where the heading-to-composer gap is below 360pt.
            let app = launch(surface.component, variant: surface.variant, height: 420)
            let card = element(app, surface.component == "welcome" ? "welcome-chat-compact-card-fixture-resume" : surface.card)
            XCTAssertTrue(card.waitForExistence(timeout: 10), surface.component)
            XCTAssertLessThan(card.frame.height, 100, surface.component)
            // CGRect intersections can produce 43.99999999999994 for 44pt.
            XCTAssertGreaterThanOrEqual(card.frame.height + 0.001, 44)
            assertBetweenHeadingAndComposer(card, surface: surface, app: app)
            attach(app, name: "\(surface.component)-short-viewport-compact-continuation")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.order.sidebar-header-match
    func testChatContinuationShowAllOpensGridAndSearchFindsActualSyntheticChat() {
        let app = launch("welcome", variant: "continuation", height: 844)
        let showAll = app.buttons["welcome-show-all-chats"]
        XCTAssertTrue(showAll.waitForExistence(timeout: 5))
        revealRowItem(showAll, rowY: app.buttons["welcome-chat-card-fixture-resume"].frame.midY, app: app)
        XCTAssertTrue(showAll.isHittable)
        showAll.tap()
        let grid = element(app, "welcome-chat-grid")
        XCTAssertTrue(grid.waitForExistence(timeout: 5))
        let sidebarClose = app.buttons.matching(identifier: "chat-sidebar-close")
        let sidebarScroll = app.scrollViews.matching(identifier: "chat-sidebar-scroll")
        let gridSearch = app.textFields["welcome-browse-search"]
        let gridBack = app.buttons["welcome-back-to-recent"]
        let resumeCard = grid.buttons["welcome-chat-card-fixture-resume"]
        let canvas = element(app, "dev-component-preview-bounds")
        let landingOnly = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard grid.exists, gridSearch.exists, gridBack.exists, resumeCard.exists, canvas.exists else { return false }
            // Use the measured fixture viewport inside the actual window. Its
            // closed sidebar ends at the canvas edge but stays mounted in AX.
            let viewport = canvas.frame.intersection(app.windows.firstMatch.frame)
            guard !viewport.isEmpty else { return false }
            func inactiveSidebarChrome(_ chrome: XCUIElement) -> Bool {
                guard chrome.exists else { return true }
                // XCTest cannot compute activation points for offscreen chrome.
                if chrome.frame.intersection(viewport).isEmpty { return true }
                return !chrome.isHittable
            }
            let sidebarIsInactive = sidebarClose.allElementsBoundByIndex.allSatisfy(inactiveSidebarChrome)
                && sidebarScroll.allElementsBoundByIndex.allSatisfy(inactiveSidebarChrome)
            let gridControlsOnscreen = [gridSearch, gridBack, resumeCard].allSatisfy {
                !$0.frame.isEmpty && viewport.contains(CGPoint(x: $0.frame.midX, y: $0.frame.midY))
            }
            guard sidebarIsInactive, gridControlsOnscreen else { return false }
            return gridSearch.isHittable && gridBack.isHittable && resumeCard.isHittable
        }, object: app)
        let landingResult = XCTWaiter.wait(for: [landingOnly], timeout: 5)
        if landingResult != .completed {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "synthetic-show-all-grid-sidebar-AX"; hierarchy.lifetime = .keepAlways; add(hierarchy)
            attach(app, name: "synthetic-show-all-grid-sidebar-screen")
        }
        XCTAssertEqual(landingResult, .completed,
            "Show All must expose actual landing grid controls and cards while the sidebar chrome stays noninteractive")
        let bannerHidden = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
            object: element(app, "continuation-heading"))
        XCTAssertEqual(XCTWaiter.wait(for: [bannerHidden], timeout: 5), .completed, "The heading is replaced by the grid")
        let back = app.buttons["welcome-back-to-recent"]
        XCTAssertTrue(back.isHittable)
        back.tap()
        XCTAssertTrue(showAll.waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "continuation-heading").waitForExistence(timeout: 5))
        showAll.tap()
        let input = app.textFields["welcome-browse-search"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        input.tap()
        input.typeText("Telescope")
        let result = app.buttons["welcome-chat-card-fixture-second"]
        XCTAssertTrue(result.waitForExistence(timeout: 8)); XCTAssertTrue(result.isHittable)
        XCTAssertFalse(element(app, "welcome-chat-card-fixture-resume").exists, "Grid search filters the cached production card population")
        result.tap()
        let selected = element(app, "dev-preview-local-action")
        let selection = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "open:fixture-second"), object: selected)
        XCTAssertEqual(XCTWaiter.wait(for: [selection], timeout: 5), .completed)
        let keyboardHidden = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.keyboards.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [keyboardHidden], timeout: 5), .completed, "Actual grid selection dismisses search focus")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity,projects.access.explicit-context
    func testProjectsShowAllAndSearchUseProjectMetadataAndOpenProjectDetail() {
        let app = launch("projects", variant: "landing", height: 844)
        let showAll = app.buttons["projects-show-all"]
        XCTAssertTrue(showAll.waitForExistence(timeout: 5))
        // Show all / Search are the row's last tile (web start row).
        revealRowItem(showAll, rowY: app.buttons["project-card-preview-project"].frame.midY, app: app)
        XCTAssertTrue(showAll.isHittable)
        showAll.tap()
        XCTAssertTrue(element(app, "projects-browse-list").waitForExistence(timeout: 5))
        let input = app.textFields["projects-browse-search"]
        XCTAssertTrue(input.waitForExistence(timeout: 5)); input.tap(); input.typeText("zz-no-match\n")
        XCTAssertFalse(app.buttons["project-card-preview-project"].exists)
        XCTAssertFalse(app.textFields["search-input"].exists, "Project browsing must not open chat search")
        app.buttons["projects-back-to-recent"].tap()
        let search = app.buttons["projects-search"]
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        revealRowItem(search, rowY: element(app, "welcome-row-actions").frame.midY, app: app)
        XCTAssertTrue(search.isHittable)
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
        // Keep the synthetic canvas inside the real phone's status/home safe
        // area. An 844pt centered canvas places its idle editor over the home
        // gesture region while still satisfying the window-containment check.
        let app = launch("projects", variant: "landing", height: 744)
        let card = app.buttons["project-card-preview-project"]
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        XCTAssertEqual(card.frame.width, 300, accuracy: 2)
        XCTAssertEqual(card.frame.height, 200, accuracy: 2)
        assertBetweenHeadingAndComposer(card, surface: surfaces[2], app: app)
        let input = app.textViews["project-input-textarea"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertTrue(input.isHittable, "The composer must be visible in the real window before opening the keyboard")
        // UITextView's preferred tap point can lie outside its rounded clip.
        input.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["project-input-composer-cancel"].waitForExistence(timeout: 5),
                      "Tapping the idle editor must activate the expanded composer before typing")
        // XCTest can attach its own hardware input session even when the
        // Simulator GUI preference is disconnected. Exercise real typing to
        // present software input before measuring the keyboard's viewport.
        input.typeText("Keyboard layout")
        #if os(iOS)
        let keyboard = app.keyboards.firstMatch
        let keyboardExists = keyboard.waitForExistence(timeout: 5)
        if !keyboardExists {
            let diagnostics = XCTAttachment(string: app.debugDescription)
            diagnostics.name = "Project composer before keyboard presentation"
            diagnostics.lifetime = .keepAlways
            add(diagnostics)
        }
        XCTAssertTrue(keyboardExists)
        let softwareKeys = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                let window = app.windows.firstMatch.frame
                return keyboard.keys["q"].isHittable
                    && keyboard.frame.height > 100
                    && keyboard.frame.intersects(window)
                    && keyboard.frame.minY < window.maxY
            },
            object: keyboard)
        let keyboardResult = XCTWaiter.wait(for: [softwareKeys], timeout: 5)
        if keyboardResult != .completed {
            let diagnostics = XCTAttachment(string: "window=\(app.windows.firstMatch.frame); keyboard=\(keyboard.frame); input=\(input.frame)\n\(app.debugDescription)")
            diagnostics.name = "Project keyboard precondition focus and hierarchy"
            diagnostics.lifetime = .keepAlways
            add(diagnostics)
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Project keyboard precondition screen"
            screenshot.lifetime = .keepAlways
            add(screenshot)
        }
        XCTAssertEqual(keyboardResult, .completed,
                       "This case requires a hittable software key inside the real window; an offscreen UIKeyboardLayoutStar Preview does not reduce the continuation viewport. window=\(app.windows.firstMatch.frame), keyboard=\(keyboard.frame), q=\(keyboard.keys["q"].frame)")
        #endif
        // Focused drafting keeps the background at full opacity but inert. Its
        // card has no accessible geometry until the real editor is dismissed.
        let backdrop = app.buttons["project-home-prompt-backdrop"]
        XCTAssertTrue(backdrop.waitForExistence(timeout: 5))
        XCTAssertTrue(backdrop.isHittable)
        XCTAssertEqual(backdrop.value as? String, "background-opacity=1;background-interactive=false")
        let backgroundHidden = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: card)
        XCTAssertEqual(XCTWaiter.wait(for: [backgroundHidden], timeout: 5), .completed,
                       "Focused drafting must suppress the continuation card from accessibility")
        for identifier in ["projects-show-all", "projects-search"] {
            let backgroundControl = element(app, identifier)
            if backgroundControl.exists {
                XCTAssertFalse(backgroundControl.isEnabled)
                XCTAssertFalse(backgroundControl.isHittable)
            }
        }
        XCTAssertTrue(input.isHittable)
        #if os(iOS)
        let composer = element(app, "project-input-composer")
        let window = app.windows.firstMatch
        let receipt = "window=\(window.frame); keyboard=\(keyboard.frame); composer=\(composer.frame)"
        let geometry = XCTAttachment(string: receipt + "\n" + app.debugDescription)
        geometry.name = "Project focused composer keyboard viewport geometry"
        geometry.lifetime = .keepAlways
        add(geometry)
        XCTAssertGreaterThanOrEqual(composer.frame.minY, window.frame.minY)
        XCTAssertLessThanOrEqual(composer.frame.maxY, keyboard.frame.minY + 1,
                                 "The actual composer must remain above the visible software keyboard: \(receipt)")
        #endif
        let cancel = app.buttons["project-input-composer-cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 5))
        XCTAssertTrue(cancel.isHittable)
        cancel.tap()
        let backdropHidden = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: backdrop)
        XCTAssertEqual(XCTWaiter.wait(for: [backdropHidden], timeout: 5), .completed)
        #if os(iOS)
        let keyboardDismissed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !keyboard.exists || !keyboard.keys["q"].isHittable
        }, object: keyboard)
        XCTAssertEqual(XCTWaiter.wait(for: [keyboardDismissed], timeout: 5), .completed,
                       "Actual Cancel must dismiss the visible software keyboard")
        #endif
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        let expandedRestored = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            card.exists && abs(card.frame.height - 200) <= 2
        }, object: card)
        XCTAssertEqual(XCTWaiter.wait(for: [expandedRestored], timeout: 5), .completed)
        XCTAssertEqual(card.frame.width, 300, accuracy: 2)
        XCTAssertEqual(card.frame.height, 200, accuracy: 2)
        assertBetweenHeadingAndComposer(card, surface: surfaces[2], app: app)
        attach(app, name: "projects-keyboard-reduces-continuation-gap")
    }

    private struct Surface {
        let component: String
        let variant: String
        let card: String
        let heading: String
        let composer: String
    }
    private var surfaces: [Surface] {
        [.init(component: "welcome", variant: "continuation", card: "welcome-chat-card-fixture-resume", heading: "continuation-heading", composer: "continuation-composer"),
         .init(component: "workflows", variant: "home", card: "workflow-landing-card", heading: "workflows-home-greeting", composer: "workflow-input-composer"),
         .init(component: "projects", variant: "landing", card: "project-card-preview-project", heading: "projects-home-greeting", composer: "project-input-composer")]
    }
    private func assertBetweenHeadingAndComposer(_ card: XCUIElement, surface: Surface, app: XCUIApplication) {
        let heading = element(app, surface.heading), composer = element(app, surface.composer)
        XCTAssertTrue(heading.exists); XCTAssertTrue(composer.exists)
        XCTAssertGreaterThanOrEqual(card.frame.minY, heading.frame.maxY - 1)
        XCTAssertLessThanOrEqual(card.frame.maxY, composer.frame.minY + 1)
        XCTAssertTrue(card.isHittable)
    }
    private func launch(_ component: String, variant: String, height: Int) -> XCUIApplication {
        let app = XCUIApplication()
        // Environment is authoritative in DevPreviewLaunchConfiguration;
        // inherited DEV_PREVIEW requests otherwise discard CLI dimensions.
        app.launchEnvironment = [
            "DEV_PREVIEW": component, "DEV_PREVIEW_COMPONENT": component,
            "DEV_PREVIEW_VARIANT": variant, "DEV_PREVIEW_THEME": "light",
            "DEV_PREVIEW_WIDTH": "390", "DEV_PREVIEW_HEIGHT": String(height)
        ]
        app.launchArguments = ["--ui-test-expose-chat-ids",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        #if os(iOS)
        // A preceding rotation test can leave UIKit restoring landscape during
        // launch even after the device was reset. Apply and observe it again.
        XCUIDevice.shared.orientation = .portrait
        #endif
        let window = app.windows.firstMatch
        let canvas = element(app, "dev-component-preview-bounds")
        let viewportReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard window.exists, canvas.exists else { return false }
            let bounds = window.frame, fixture = canvas.frame
            #if os(iOS)
            guard bounds.height > bounds.width else { return false }
            #endif
            return abs(fixture.width - 390) <= 1 && abs(fixture.height - CGFloat(height)) <= 1
                && bounds.contains(fixture)
        }, object: canvas)
        XCTAssertEqual(XCTWaiter.wait(for: [viewportReady], timeout: 10), .completed,
                       "The portrait component canvas must fit the actual window before geometry or taps: window=\(window.frame), canvas=\(canvas.frame)")
        let root = element(app, "dev-preview-root")
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected")
        XCTAssertFalse(element(app, "dev-preview-error").exists)
        return app
    }
    /// Drags the start row leftwards at `rowY` until `item` (e.g. the actions tile link) is hittable.
    private func revealRowItem(_ item: XCUIElement, rowY: CGFloat, app: XCUIApplication) {
        let window = app.windows.firstMatch
        let origin = window.coordinate(withNormalizedOffset: .zero)
        for _ in 0..<8 where !item.isHittable {
            origin.withOffset(CGVector(dx: window.frame.width * 0.85, dy: rowY))
                .press(forDuration: 0.05, thenDragTo: origin.withOffset(CGVector(dx: window.frame.width * 0.15, dy: rowY)))
        }
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func attach(_ app: XCUIApplication, name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
}
