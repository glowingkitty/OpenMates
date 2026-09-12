// Focused, account-free interaction coverage for the isolated preview host.
// Every scenario launches production components with synthetic fixture state.
// No test account, backend, notification injector, or saved draft is required.
// These checks prove local interaction wiring; visual parity still requires a
// rendered comparison against each registry URL and user approval of the web UI.

import XCTest
#if os(iOS)
import UIKit
#endif

@MainActor
final class DevComponentPreviewUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    override func tearDownWithError() throws {
        if let testRun, testRun.failureCount > 0 {
            attachScreenshot("Component preview failure — \(name)")
        }
        try super.tearDownWithError()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testComposerEditsSubmitsAndRemovesLocalAttachment() throws {
        let app = launch(component: "composer", variant: "filled", props: ["text": "Synthetic preview draft"])
        let editor = element(app, "message-editor")
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        editor.tap()
        editor.typeText(" edited")
        XCTAssertTrue((editor.value as? String)?.contains("edited") == true)
        attachScreenshot("Production composer focused with edited text")
        app.buttons["send-button"].tap()
        assertAction("submitted-locally", in: app)

        app.terminate()
        let attachmentApp = launch(component: "composer", variant: "attachment")
        // Use the real translated control so missing catalog keys fail visibly.
        let remove = attachmentApp.buttons["Remove"].firstMatch
        XCTAssertTrue(remove.waitForExistence(timeout: 10))
        remove.tap()
        assertAction("attachment-removed", in: attachmentApp)
        XCTAssertFalse(remove.exists)
        XCTAssertFalse((element(attachmentApp, "message-editor").value as? String)?.contains("Synthetic preview draft") == true,
                       "Launching another fixture must not restore an earlier preview draft")
        attachScreenshot("Composer local attachment removed")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageThinkingExpandsAndCollapses() {
        let app = launch(component: "message", variant: "thinking")
        let expand = app.buttons["Expand AI reasoning"]
        XCTAssertTrue(expand.waitForExistence(timeout: 10))
        expand.tap()
        let collapse = app.buttons["Collapse AI reasoning"]
        XCTAssertTrue(collapse.waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@",
                         "The user wants to migrate from Svelte 4 to Svelte 5.")).firstMatch.exists)
        attachScreenshot("Production message thinking expanded")
        collapse.tap()
        XCTAssertTrue(expand.waitForExistence(timeout: 3))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEmbedPreviewOpensChildAndMinimizesBackToCard() {
        let app = launch(component: "embed-preview")
        let preview = app.buttons["embed-preview"].firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 10))
        XCTAssertEqual(preview.frame.width, 300, accuracy: 2, "Regular cards retain their web width on phones and tablets")
        XCTAssertEqual(preview.frame.height, 200, accuracy: 2)
        preview.tap()
        let fullscreen = element(app, "dev-preview-embed-fullscreen")
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
        waitForEmbedPresentation(app)
        let child = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
        if !child.isHittable { app.swipeUp() }
        XCTAssertTrue(child.waitForExistence(timeout: 5))
        child.tap()
        waitForEmbedPresentation(app)
        assertAction("opened-preview-web-search-result-1", in: app)
        let title = app.staticTexts["Top 10 Restaurants in Berlin - Local Guide"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        let websiteBody = element(app, "website-fullscreen-body")
        let description = app.staticTexts["website-description"].firstMatch
        XCTAssertTrue(description.waitForExistence(timeout: 5))
        let bodyWidth = websiteBody.frame.width
        if bodyWidth <= 400 {
            XCTAssertEqual(description.frame.width, bodyWidth - 32, accuracy: 2,
                           "Phone source body must use the rendered web's 16pt side padding")
        }
        XCTAssertFalse(app.buttons["embed-previous"].exists,
                       "The first result has no previous result; its parent is a separate route")
        let next = app.buttons["embed-next"]
        XCTAssertTrue(next.isHittable)
        next.tap()
        XCTAssertTrue(app.staticTexts["Berlin Food Scene: A Complete Guide"].firstMatch.waitForExistence(timeout: 5))
        let previous = app.buttons["embed-previous"]
        XCTAssertTrue(previous.isHittable)
        previous.tap()
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        attachScreenshot("Production child embed fullscreen")
        let minimize = app.buttons["embed-minimize"].firstMatch
        XCTAssertTrue(minimize.isHittable, "Fullscreen controls must remain outside the system status area")
        XCTAssertGreaterThanOrEqual(title.frame.minY, minimize.frame.maxY,
                                    "The embed title must appear below the fullscreen controls")
        minimize.tap()
        XCTAssertTrue(child.waitForExistence(timeout: 5), "Minimizing a child must restore its parent results")
        waitForEmbedPresentation(app)
        XCTAssertTrue(minimize.isHittable)
        minimize.tap()
        XCTAssertTrue(fullscreen.waitForNonExistence(timeout: 5))
        XCTAssertTrue(preview.exists)
        assertAction("embed-minimized", in: app)
    }

    // Local state changes model a sibling hydration update while a result is open.
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testEmbedSelectionSurvivesInsertedAndRemovedResults() {
        let app = launch(component: "embed-preview", extraArguments: ["--ui-test-embed-navigation-mutations"])
        app.buttons["embed-preview"].firstMatch.tap()
        waitForEmbedPresentation(app)
        let child = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
        if !child.isHittable { app.swipeUp() }
        XCTAssertTrue(child.waitForExistence(timeout: 5))
        child.tap()
        waitForEmbedPresentation(app)
        let next = app.buttons["embed-next"]
        XCTAssertTrue(next.isHittable)
        next.tap()
        assertFullscreenSelection("preview-web-search-result-2", title: "Berlin Food Scene: A Complete Guide", app: app)
        app.buttons["dev-preview-insert-result"].tap()
        assertFullscreenSelection("preview-web-search-result-2", title: "Berlin Food Scene: A Complete Guide", app: app)
        app.buttons["embed-next"].tap()
        assertFullscreenSelection("preview-web-search-result-3", title: "Where to Eat in Berlin - Travel Blog", app: app)
        app.buttons["embed-next"].tap()
        assertFullscreenSelection("preview-web-search-result-4", title: "Berlin Restaurant Guide 2026", app: app)
        XCTAssertFalse(app.buttons["embed-next"].exists)
        app.buttons["embed-previous"].tap()
        app.buttons["embed-previous"].tap()
        app.buttons["dev-preview-remove-result-2"].tap()
        assertFullscreenSelection("preview-web-search-result-1", title: "Top 10 Restaurants in Berlin - Local Guide", app: app)
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(app.buttons["embed-preview-preview-web-search-result-inserted"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(element(app, "dev-preview-embed-fullscreen").waitForNonExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenPeerNavigationRestoresActualParentAfterChildClose() {
        let app = launch(component: "embed-fullscreen", variant: "withNavigation")
        XCTAssertTrue(app.buttons["embed-previous"].isHittable)
        XCTAssertTrue(app.buttons["embed-next"].isHittable)
        app.buttons["embed-next"].tap()
        assertFullscreenSelection("preview-web-search-1-next", title: "Next search fixture", app: app)
        XCTAssertFalse(app.buttons["embed-next"].exists)
        let child = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
        if !child.isHittable { app.swipeUp() }
        XCTAssertTrue(child.waitForExistence(timeout: 5))
        child.tap()
        assertFullscreenSelection("preview-web-search-result-1", title: "Top 10 Restaurants in Berlin - Local Guide", app: app)
        app.buttons["embed-minimize"].firstMatch.tap()
        assertFullscreenSelection("preview-web-search-1-next", title: "Next search fixture", app: app)
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(app.buttons["embed-preview"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(element(app, "embed-fullscreen-header").exists)
    }

    private func waitForEmbedPresentation(_ app: XCUIApplication,
                                          file: StaticString = #filePath, line: UInt = #line) {
        let state = element(app, "embed-presentation-state")
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: state)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed,
                       "Wait for the actual slide animation before resolving tap coordinates", file: file, line: line)
    }

    private func assertFullscreenSelection(_ id: String, title: String, app: XCUIApplication,
                                           file: StaticString = #filePath, line: UInt = #line) {
        waitForEmbedPresentation(app, file: file, line: line)
        let header = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "embed-fullscreen-header", id)).firstMatch
        XCTAssertTrue(header.waitForExistence(timeout: 5), file: file, line: line)
        let actualTitle = header.descendants(matching: .staticText).matching(identifier: "embed-header-title").firstMatch
        XCTAssertTrue(actualTitle.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertEqual(actualTitle.label, title, file: file, line: line)
        XCTAssertTrue(actualTitle.isHittable, "Assert real rendered content, not only a callback/route metric", file: file, line: line)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenHeaderUsesWebBreakpointInRegularWidthEnvironment() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            throw XCTSkip("Run the 730/731 width boundary on iPad Simulator so both viewports fit")
        }
        #endif
        var heights: [CGFloat] = []
        var titleHeights: [CGFloat] = []
        for width in [730, 731] {
            let app = launch(component: "embed-fullscreen", extraArguments: ["--dev-preview-width", "\(width)"])
            let header = element(app, "embed-fullscreen-header")
            XCTAssertTrue(header.waitForExistence(timeout: 5))
            XCTAssertEqual(header.frame.width, CGFloat(width), accuracy: 1)
            let title = app.staticTexts.matching(identifier: "embed-header-title").firstMatch
            XCTAssertTrue(title.isHittable)
            let minimize = app.buttons["embed-minimize"].firstMatch
            XCTAssertTrue(minimize.isHittable)
            XCTAssertGreaterThanOrEqual(title.frame.minY, minimize.frame.maxY)
            heights.append(header.frame.height)
            titleHeights.append(title.frame.height)
            attachScreenshot("Embed header at width \(width)")
            app.terminate()
        }
        XCTAssertEqual(heights[1] - heights[0], 50, accuracy: 1,
                       "Web body height changes from 190 to 240; native system insets remain unchanged")
        XCTAssertGreaterThan(titleHeights[1], titleHeights[0], "The title must use the corresponding larger web type size")
    }

    // Matches WebSearchEmbedFullscreen.preview.ts and SearchResultsTemplate's
    // real card-open/child-close flow, not a fixture-only callback counter.
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSearchResultsUseResponsiveWebGridAndOpenFourthSource() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            throw XCTSkip("Run both 390/730 preview widths on iPad Simulator")
        }
        #endif
        for width in [390, 730] {
            let app = launch(component: "embed-fullscreen", extraArguments: ["--dev-preview-width", "\(width)"])
            let header = element(app, "embed-fullscreen-header")
            let first = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
            let second = app.buttons["embed-preview-preview-web-search-result-2"].firstMatch
            XCTAssertTrue(first.waitForExistence(timeout: 5))
            XCTAssertTrue(second.waitForExistence(timeout: 5))
            XCTAssertEqual(first.frame.width, 320, accuracy: 1)
            XCTAssertEqual(first.frame.height, 200, accuracy: 1)
            if width == 730 {
                XCTAssertEqual(first.frame.minX - header.frame.minX, 23.5, accuracy: 1)
                XCTAssertEqual(second.frame.minX - first.frame.minX, 363, accuracy: 1)
                XCTAssertEqual(second.frame.minY, first.frame.minY, accuracy: 1)
            } else {
                XCTAssertEqual(first.frame.minX - header.frame.minX, 35, accuracy: 1)
                XCTAssertEqual(second.frame.minX, first.frame.minX, accuracy: 1)
                XCTAssertEqual(second.frame.minY - first.frame.minY, 210, accuracy: 1)
            }
            attachScreenshot("Website result cards at width \(width)")
            let fourth = app.buttons["embed-preview-preview-web-search-result-4"].firstMatch
            let scroll = element(app, "dev-preview-embed-fullscreen").scrollViews.firstMatch
            for _ in 0..<5 where !fourth.isHittable { scroll.swipeUp() }
            XCTAssertTrue(fourth.isHittable)
            fourth.tap()
            assertFullscreenSelection("preview-web-search-result-4", title: "Berlin Restaurant Guide 2026", app: app)
            XCTAssertFalse(app.buttons["embed-next"].exists)
            app.buttons["embed-previous"].tap()
            assertFullscreenSelection("preview-web-search-result-3", title: "Where to Eat in Berlin - Travel Blog", app: app)
            app.buttons["embed-minimize"].firstMatch.tap()
            XCTAssertTrue(first.waitForExistence(timeout: 5), "Closing the source returns to the actual search results")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testInvalidPreviewPropsStayInPreviewErrorSurface() {
        let app = launch(component: "composer", props: ["notAComposerProp": "invalid"])
        XCTAssertTrue(element(app, "dev-preview-error").waitForExistence(timeout: 10))
        XCTAssertFalse(element(app, "message-composer").exists)
        XCTAssertFalse(app.buttons["auth-login-tab"].exists,
                       "An invalid requested preview must never fall through to account UI")
    }

    private func launch(component: String, variant: String = "default", props: [String: String] = [:],
                        extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--dev-preview-variant", variant,
                               "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"] + extraArguments
        if !props.isEmpty,
           let data = try? JSONSerialization.data(withJSONObject: props, options: [.sortedKeys]),
           let json = String(data: data, encoding: .utf8) {
            app.launchArguments += ["--dev-preview-props", json]
        }
        app.launch()
        let root = element(app, "dev-preview-root")
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected",
                       "Preview startup must leave the real account runtime inactive")
        if component == "embed-fullscreen" { waitForEmbedPresentation(app) }
        return app
    }

    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func assertAction(_ action: String, in app: XCUIApplication,
                              file: StaticString = #filePath, line: UInt = #line) {
        let actionProbe = element(app, "dev-preview-local-action")
        let delivered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", action), object: actionProbe)
        XCTAssertEqual(XCTWaiter.wait(for: [delivered], timeout: 5), .completed, file: file, line: line)
    }

    nonisolated private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}

@MainActor
final class EmbedHeaderActionComponentUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPhoneCodeMoreUsesRealCopyAndCloseActions() {
        let app = launchHeader(variant: "actions-code", width: 390)
        let more = app.buttons["embed-more-button"]
        XCTAssertTrue(more.waitForExistence(timeout: 8)); more.tap()
        let copy = app.buttons["embed-copy-button"]
        XCTAssertTrue(copy.waitForExistence(timeout: 3))
        XCTAssertEqual(copy.value as? String, "content-control", "Overflow pills must opt out of header-white styling")
        copy.tap()
        XCTAssertTrue(app.staticTexts["Code copied to clipboard"].waitForExistence(timeout: 3),
                      "The production copy action must complete, not only dismiss More")
        XCTAssertFalse(copy.exists, "A real menu action closes More")
        // The real toast auto-dismisses after three seconds. Waiting for its
        // removal avoids tapping a disappearing dismiss control (hit point -1,-1)
        // or reopening More while its full-screen overlay still intercepts hits.
        XCTAssertTrue(app.staticTexts["Code copied to clipboard"].waitForNonExistence(timeout: 5))
        let moreReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            more.exists && more.isHittable && more.value as? String == "collapsed"
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [moreReady], timeout: 3), .completed)
        more.tap()
        let reopened = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            more.value as? String == "expanded"
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [reopened], timeout: 3), .completed)
        XCTAssertTrue(app.buttons["embed-download-button"].waitForExistence(timeout: 3))
        app.buttons["embed-minimize"].tap()
        XCTAssertTrue(app.buttons["embed-more-button"].waitForNonExistence(timeout: 3))
    }
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testHeaderControlsSwitchStyleWhenScrolledAwayAtNarrowAndWideWidths() {
        for width in [390, 800] {
            let app = launchHeader(variant: "default", width: width, height: 400)
            let close = app.buttons["embed-minimize"]
            XCTAssertTrue(close.waitForExistence(timeout: 8))
            XCTAssertEqual(close.value as? String, "header-overlay")
            XCTAssertFalse(app.buttons["embed-more-button"].exists)
            let fullscreen = app.descendants(matching: .any)["dev-preview-embed-fullscreen"].firstMatch
            let scroll = fullscreen.scrollViews.firstMatch
            for _ in 0..<8 {
                if close.value as? String == "content-control" { break }
                scroll.swipeUp()
            }
            XCTAssertEqual(close.value as? String, "content-control")
            app.terminate()
        }
    }
    private func launchHeader(variant: String, width: Int, height: Int = 844) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-fullscreen", "--dev-preview-variant", variant,
            "--dev-preview-width", String(width), "--dev-preview-height", String(height),
            "--ui-test-embed-presentation", "-AppleLanguages", "(en)"]
        app.launch()
        return app
    }
}
