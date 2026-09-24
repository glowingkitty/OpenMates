// UI parity smoke coverage for native embed preview/fullscreen surfaces.
// Uses the debug-only embed gallery so assertions are deterministic and do not
// require credentials, private chat records, provider APIs, or AI calls. The
// paired web contract spec captures the browser source of truth; this simulator
// test exports native screenshots for agent visual review.

import XCTest

@MainActor
final class EmbedRenderingParityUITests: XCTestCase {
    private let canonicalRegistryKeys = [
        "app:audio:generate", "app:audio:speak", "app:business:company_financials",
        "app:calendar:create-event", "app:calendar:delete-event", "app:calendar:get-events",
        "app:calendar:list-calendars", "app:calendar:update-event", "app:code:get_docs",
        "app:code:search_repos", "app:design:search_icons", "app:electronics:search_components",
        "app:events:search", "app:finance:check_accounts", "app:fitness:search_classes",
        "app:fitness:search_locations", "app:health:search_appointments", "app:home:search",
        "app:images:generate", "app:images:generate_draft", "app:images:search",
        "app:mail:search", "app:maps:search", "app:math:calculate", "app:models3d:generate",
        "app:models3d:search", "app:music:generate", "app:news:search",
        "app:nutrition:search_recipes", "app:reminder:cancel-reminder",
        "app:reminder:list-reminders", "app:reminder:set-reminder",
        "app:shopping:search_products", "app:social_media:get-posts", "app:social_media:search",
        "app:tasks:create", "app:tasks:search", "app:travel:get_flight",
        "app:travel:price_calendar", "app:travel:search_connections", "app:travel:search_stays",
        "app:videos:create", "app:videos:generate", "app:videos:get_transcript",
        "app:videos:search", "app:weather:forecast", "app:weather:rain_radar",
        "app:web:read", "app:web:search", "app:workflows:create-or-modify",
        "app:workflows:search", "business-company-financial-result", "code-application",
        "code-code", "code-notebook", "code-repo", "design-icon-result", "docs-doc",
        "electronics-component", "electronics-pcb-schematic", "events-event", "file-file",
        "fitness-class", "fitness-location", "focus-mode-activation", "health-appointment",
        "home-listing", "image", "images-image-result", "mail-email", "maps", "maps-place",
        "math-plot", "mindmaps-mindmap", "models3d-model-result", "nutrition-recipe", "pdf",
        "recording", "sheets-sheet", "shopping-product", "social-media-post", "tasks-task",
        "travel-connection", "travel-stay", "videos-video", "weather-day", "web-website",
        "workflows-workflow"
    ]
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

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testCanonicalRegistryKeysRenderPreviewAndFullscreenWithoutGenericFallback() throws {
        let requestedKey = ProcessInfo.processInfo.environment["EMBED_REGISTRY_KEY"]
        let keys = requestedKey.map { [$0] } ?? canonicalRegistryKeys
        XCTAssertEqual(canonicalRegistryKeys.count, 88, "The canonical native evidence inventory must track all generated registry keys.")

        for key in keys {
            for surface in ["preview", "fullscreen"] {
                let app = XCUIApplication()
                app.launchArguments = [
                    "--dev-preview", "embeds",
                    "--dev-preview-app", "web",
                    "--dev-preview-theme", "light",
                    "--embed-registry-key", key,
                    "--embed-surface", surface
                ]
                app.launchEnvironment["DEV_PREVIEW"] = "embeds"
                app.launchEnvironment["DEV_PREVIEW_APP"] = "web"
                app.launchEnvironment["DEV_PREVIEW_THEME"] = "light"
                app.launch()

                let identifier = "dev-embed-canonical-\(surface)"
                let canonical = app.descendants(matching: .any)[identifier]
                XCTAssertTrue(canonical.waitForExistence(timeout: 8), "Missing canonical \(surface) for \(key)")
                XCTAssertEqual(canonical.value as? String, "\(key)|default")
                XCTAssertFalse(app.descendants(matching: .any)["dev-embed-registry-missing"].exists, "Missing native fixture for \(key)")

                if surface == "fullscreen" {
                    let readiness = app.descendants(matching: .any)["embed-presentation-state"]
                    XCTAssertTrue(readiness.waitForExistence(timeout: 3), "Fullscreen readiness signal missing for \(key)")
                    XCTAssertTrue(waitForLabel(readiness, containing: "ready", timeout: 3), "Fullscreen was still animating for \(key)")
                }

                XCTAssertFalse(
                    app.staticTexts.matching(NSPredicate(format: "label == %@", key)).firstMatch.exists,
                    "\(key) rendered the generic raw-data fallback in \(surface)"
                )
                XCTAssertFalse(app.tables.firstMatch.exists, "\(key) rendered default List/table chrome")
                attachScreenshot(name: "Embed parity|\(key)|\(surface)|iphone-light-ltr")
                app.terminate()
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
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

    // contract-test: direct surface=gui.apple assertions=code-run.surface-parity
    func testFinishedIndexHTMLRendersSourceInPreviewAndFullscreen() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "code"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let sourcePreview = app.descendants(matching: .any)["code-embed-source-preview"].firstMatch
        XCTAssertTrue(sourcePreview.waitForExistence(timeout: 8), "Finished index.html remained in the processing preview")
        XCTAssertFalse(app.descendants(matching: .any)["code-embed-processing"].exists)

        let previewButton = app.buttons
            .matching(identifier: "embed-preview")
            .containing(.any, identifier: "code-embed-source-preview")
            .firstMatch
        XCTAssertTrue(previewButton.waitForExistence(timeout: 3), "Finished source was not inside a tappable embed preview")
        previewButton.tap()
        let sourcePanel = app.descendants(matching: .any)["code-source-panel"].firstMatch
        XCTAssertTrue(
            sourcePanel.waitForExistence(timeout: 5),
            "Fullscreen did not receive the hydrated index.html source"
        )
        XCTAssertFalse(app.staticTexts["Processing"].exists)
        attachScreenshot(name: "Finished index.html preview and fullscreen")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.artifacts.chat-bound-versioned
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

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
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

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
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

    // contract-test: supporting surface=gui.apple assertions=code-run.artifacts.parent-child-navigation
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

    // contract-test: direct surface=gui.apple assertions=videos.transcript.surface-parity
    func testGroupedVideoTranscriptRendersPreviewAndFullscreenContent() throws {
        for surface in ["preview", "fullscreen"] {
            let app = XCUIApplication()
            app.launchArguments = [
                "--dev-preview", "embeds",
                "--dev-preview-app", "videos",
                "--embed-registry-key", "app:videos:get_transcript",
                "--embed-surface", surface
            ]
            app.launchEnvironment["DEV_PREVIEW"] = "embeds"
            app.launchEnvironment["DEV_PREVIEW_APP"] = "videos"
            app.launchEnvironment["DEV_TRANSCRIPT_METADATA_RESPONSE"] = """
                {"title":"Resolved transcript metadata fixture","channel_name":"Resolved fixture channel"}
                """
            app.launch()

            if surface == "preview" {
                XCTAssertTrue(app.descendants(matching: .any)["video-transcript-preview"].waitForExistence(timeout: 8))
                XCTAssertTrue(
                    app.staticTexts["Get Transcript"].waitForExistence(timeout: 5),
                    "The preview footer must use the localized web skill catalog name."
                )
                let title = app.staticTexts["video-transcript-title"]
                XCTAssertTrue(
                    waitForLabel(title, containing: "Resolved transcript metadata fixture", timeout: 5),
                    "Preview must resolve the real video title from the source URL when the transcript result contains no metadata."
                )
                XCTAssertTrue(
                    waitForLabel(app.staticTexts["video-transcript-subtitle"], containing: "Resolved fixture channel", timeout: 5),
                    "Preview must resolve the channel through the privacy-preserving preview endpoint."
                )
            } else {
                XCTAssertTrue(
                    app.staticTexts.matching(NSPredicate(
                        format: "label CONTAINS %@", "Resolved transcript metadata fixture"
                    )).firstMatch.waitForExistence(timeout: 8),
                    "Fullscreen must preserve metadata resolved from the transcript source URL."
                )
                XCTAssertTrue(
                    app.staticTexts.matching(NSPredicate(
                        format: "label CONTAINS %@", "Resolved fixture channel"
                    )).firstMatch.waitForExistence(timeout: 8),
                    "Fullscreen must preserve the resolved channel metadata."
                )
                XCTAssertTrue(
                    app.buttons["video-transcript-video-preview"].waitForExistence(timeout: 8),
                    "Fullscreen must include the linked web-style video preview above the transcript."
                )
                XCTAssertTrue(
                    waitForLabel(app.staticTexts["video-transcript-fullscreen-metadata"], containing: "words", timeout: 5),
                    "Fullscreen must show the transcript word count above the content."
                )
                let transcript = app.staticTexts["video-transcript-fullscreen-text"]
                XCTAssertTrue(transcript.waitForExistence(timeout: 8), "Grouped skill results must load the actual transcript in fullscreen.")
                XCTAssertTrue(transcript.label.contains("Grouped transcript fixture proof text"))
                XCTAssertFalse(app.descendants(matching: .any)["video-transcript-fullscreen-empty"].exists)
            }

            attachScreenshot(name: "Video transcript grouped result \(surface)")
            app.terminate()
        }
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
