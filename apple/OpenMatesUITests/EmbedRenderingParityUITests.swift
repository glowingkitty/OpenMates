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
        "code",
        "docs",
        "electronics",
        "events",
        "health",
        "home",
        "images",
        "mail",
        "maps",
        "math",
        "music",
        "news",
        "nutrition",
        "pdf",
        "reminder",
        "sheets",
        "shopping",
        "social_media",
        "travel",
        "videos",
        "weather",
        "web"
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
        XCTAssertTrue(restoreButton.exists, app.debugDescription)
        restoreButton.tap()

        let confirmRestore = app.buttons
            .containing(NSPredicate(format: "label CONTAINS %@", "Confirm restore v1"))
            .firstMatch
        XCTAssertTrue(confirmRestore.waitForExistence(timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Embed timeline must not render default List/table chrome")

        attachScreenshot(name: "Versioned code embed timeline")
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
}
