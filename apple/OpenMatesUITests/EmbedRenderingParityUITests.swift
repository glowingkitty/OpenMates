// UI parity smoke coverage for native embed preview/fullscreen surfaces.
// Uses the debug-only embed gallery so assertions are deterministic and do not
// require credentials, private chat records, provider APIs, or AI calls. The
// paired web contract spec captures the browser source of truth; this simulator
// test exports native screenshots for agent visual review.

import XCTest

@MainActor
final class EmbedRenderingParityUITests: XCTestCase {
    private let appSlugs = [
        "audio",
        "business",
        "calendar",
        "code",
        "design",
        "diagrams",
        "docs",
        "electronics",
        "events",
        "fitness",
        "health",
        "home",
        "images",
        "mail",
        "maps",
        "math",
        "mindmaps",
        "models3d",
        "music",
        "news",
        "nutrition",
        "pdf",
        "reminder",
        "sheets",
        "shopping",
        "social_media",
        "tasks",
        "travel",
        "videos",
        "weather",
        "web",
        "workflows"
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testAllEmbedPreviewAppsRenderProductChrome() throws {
        for appSlug in appSlugs {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", appSlug]
            app.launchEnvironment["DEV_PREVIEW"] = "embeds"
            app.launchEnvironment["DEV_PREVIEW_APP"] = appSlug
            app.launch()

            let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
            XCTAssertTrue(gallery.waitForExistence(timeout: 8), "\(appSlug) gallery did not load")

            let skillSection = app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "dev-preview-skill-"))
                .firstMatch
            XCTAssertTrue(skillSection.waitForExistence(timeout: 5), "\(appSlug) has no visible skill section")
            XCTAssertFalse(app.tables.firstMatch.exists, "Embed product UI must not render default List/table chrome")

            attachScreenshot(name: "Embed gallery \(appSlug)")
            app.terminate()
        }
    }

    func testVersionedCodeEmbedFullscreenTimelineRendersAndRestores() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "code"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
        XCTAssertTrue(gallery.waitForExistence(timeout: 8), "Code embed gallery did not load")

        let timeline = app.descendants(matching: .any)["embed-version-timeline"]
        scrollUntilVisible(app: app, element: timeline)
        XCTAssertTrue(timeline.exists, "Versioned code embed timeline did not render")
        XCTAssertTrue(app.descendants(matching: .any)["embed-version-dot-1"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["embed-version-dot-3"].exists)

        app.descendants(matching: .any)["embed-version-dot-1"].tap()

        let historicalStatus = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Viewing historical version v1"))
            .firstMatch
        XCTAssertTrue(historicalStatus.waitForExistence(timeout: 3))

        let restoreButton = app.descendants(matching: .any)["embed-version-restore-button"]
        XCTAssertTrue(restoreButton.exists)
        restoreButton.tap()

        let confirmRestore = app.buttons
            .containing(NSPredicate(format: "label CONTAINS %@", "Confirm restore v1"))
            .firstMatch
        XCTAssertTrue(confirmRestore.waitForExistence(timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Embed timeline must not render default List/table chrome")

        attachScreenshot(name: "Versioned code embed timeline")
    }

    func testSheetsPreviewAndFullscreenUseSpreadsheetChrome() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "sheets"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "sheets"
        app.launch()

        XCTAssertTrue(
            app.descendants(matching: .any)["sheet-preview-table"].waitForExistence(timeout: 8),
            "Sheets preview must render spreadsheet cells instead of a generic table card."
        )
        attachScreenshot(name: "Sheets preview")

        app.descendants(matching: .any)["embed-preview"].firstMatch.tap()

        XCTAssertTrue(
            app.descendants(matching: .any)["sheet-fullscreen-table"].waitForExistence(timeout: 5),
            "Sheets fullscreen must preserve spreadsheet-specific content."
        )
        XCTAssertFalse(app.tables.firstMatch.exists, "Sheets embed must not render default List/table chrome")
        attachScreenshot(name: "Sheets fullscreen")
    }

    func testTaskWorkflowAndModelEmbedsUseSpecificNativeChrome() throws {
        let cases: [(appSlug: String, previewIdentifiers: [String], childFullscreenIdentifier: String)] = [
            ("tasks", ["task-create-embed-preview", "task-search-embed-preview", "task-embed-card"], "task-embed-fullscreen"),
            ("workflows", ["workflow-create-embed-preview", "workflow-search-embed-preview", "workflow-embed-card"], "workflow-embed-fullscreen"),
            ("models3d", ["models3d-search-preview", "models3d-result-card", "models3d-generate-preview"], "models3d-result-fullscreen")
        ]

        for testCase in cases {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", testCase.appSlug]
            app.launchEnvironment["DEV_PREVIEW"] = "embeds"
            app.launchEnvironment["DEV_PREVIEW_APP"] = testCase.appSlug
            app.launch()

            let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
            XCTAssertTrue(gallery.waitForExistence(timeout: 8), "\(testCase.appSlug) gallery did not load")

            for identifier in testCase.previewIdentifiers {
                let element = app.descendants(matching: .any)[identifier]
                scrollUntilVisible(app: app, element: element)
                XCTAssertTrue(element.exists, "\(testCase.appSlug) missing specific preview chrome: \(identifier)")
            }

            let routeHarness = app.descendants(matching: .any)["dev-embed-fullscreen-route-harness"]
            scrollUntilHittable(app: app, element: routeHarness)
            XCTAssertTrue(routeHarness.isHittable, "\(testCase.appSlug) fullscreen route harness did not become visible")

            let firstChildButton = app.buttons["dev-embed-route-open-first-child"]
            XCTAssertTrue(firstChildButton.waitForExistence(timeout: 3), "\(testCase.appSlug) has no parent-to-child fullscreen route")
            firstChildButton.tap()

            XCTAssertTrue(
                app.descendants(matching: .any)[testCase.childFullscreenIdentifier].waitForExistence(timeout: 5),
                "\(testCase.appSlug) child fullscreen did not render specific native chrome: \(testCase.childFullscreenIdentifier)"
            )
            XCTAssertFalse(app.tables.firstMatch.exists, "\(testCase.appSlug) embed product UI must not render default List/table chrome")
            attachScreenshot(name: "Embed specific chrome \(testCase.appSlug)")
            app.terminate()
        }
    }

    func testFullscreenParentChildRouteStackReturnsToParentBeforeClosing() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "web"
        app.launch()

        let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
        XCTAssertTrue(gallery.waitForExistence(timeout: 8), "Web embed gallery did not load")

        let routeHarness = app.descendants(matching: .any)["dev-embed-fullscreen-route-harness"]
        scrollUntilHittable(app: app, element: routeHarness)
        XCTAssertTrue(routeHarness.isHittable, "Fullscreen route harness did not become visible")

        let routeLabel = app.staticTexts["dev-embed-active-route"]
        XCTAssertTrue(routeLabel.label.contains("preview-web-search-1"), "Parent fullscreen route was not active")

        let firstChildButton = app.buttons["dev-embed-route-open-first-child"]
        XCTAssertTrue(firstChildButton.isHittable, "First child route opener was not tappable")
        firstChildButton.tap()

        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-web-search-result-1", timeout: 5),
            "Opening a child from parent fullscreen did not make the child route active"
        )

        tapFirstHittableButton(app: app, identifier: "embed-minimize")
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-web-search-1", timeout: 5),
            "Closing child fullscreen did not return to the parent fullscreen route"
        )

        tapFirstHittableButton(app: app, identifier: "embed-minimize")
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "none", timeout: 5),
            "Closing parent fullscreen did not return to the non-fullscreen state"
        )
        XCTAssertTrue(app.buttons["dev-embed-route-reset"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Embed fullscreen route stack must not render default List/table chrome")

        attachScreenshot(name: "Fullscreen parent child route stack")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func scrollUntilVisible(app: XCUIApplication, element: XCUIElement) {
        for _ in 0..<8 where !element.exists {
            app.swipeUp()
        }
    }

    private func scrollUntilHittable(app: XCUIApplication, element: XCUIElement) {
        for _ in 0..<10 where !element.isHittable {
            app.swipeUp()
        }
    }

    private func waitForLabel(_ element: XCUIElement, containing expected: String, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.label.contains(expected) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return element.label.contains(expected)
    }

    private func tapFirstHittableButton(app: XCUIApplication, identifier: String) {
        let matches = app.buttons.matching(identifier: identifier).allElementsBoundByIndex
        if let button = matches.first(where: { $0.isHittable }) {
            button.tap()
            return
        }
        XCTFail("No hittable button found for identifier \(identifier)")
    }
}
