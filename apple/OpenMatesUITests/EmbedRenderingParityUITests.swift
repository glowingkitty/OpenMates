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

            let routeLabel = app.staticTexts["dev-preview-route"]
            XCTAssertTrue(routeLabel.exists, "\(appSlug) route label is missing")
            XCTAssertEqual(routeLabel.label, "/dev/preview/embeds/\(appSlug)")

            let skillSection = app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "dev-preview-skill-"))
                .firstMatch
            XCTAssertTrue(skillSection.waitForExistence(timeout: 5), "\(appSlug) has no visible skill section")
            XCTAssertFalse(app.tables.firstMatch.exists, "Embed product UI must not render default List/table chrome")

            attachScreenshot(name: "Embed gallery \(appSlug)")
            app.terminate()
        }
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
