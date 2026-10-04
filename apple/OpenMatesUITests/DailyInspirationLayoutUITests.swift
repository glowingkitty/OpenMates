// Layout regression proof uses real InspirationCard and EmbedPreviewCard.
import XCTest

@MainActor
final class DailyInspirationLayoutUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testWideInspirationKeepsPhraseSeparateAndVideoFooterVisible() {
        checkLayout(variant: "wide", expectsSideBySide: true)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testShortInspirationFitsEntirePreviewAndKeepsStartActionHittable() {
        checkLayout(variant: "short", expectsSideBySide: true)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testNarrowInspirationAlternatesPreviewWithoutCoveredTextInteraction() {
        checkLayout(variant: "narrow", expectsSideBySide: false)
    }

    private func checkLayout(variant: String, expectsSideBySide: Bool) {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "daily-inspiration", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let banner = element(app, "daily-inspiration-card")
        XCTAssertTrue(banner.waitForExistence(timeout: 10))
        let phrase = element(app, "daily-inspiration-phrase")
        let cta = element(app, "daily-inspiration-cta-text")
        XCTAssertTrue(phrase.exists)
        XCTAssertTrue(cta.exists)
        XCTAssertTrue(banner.frame.contains(phrase.frame))
        XCTAssertTrue(banner.frame.contains(cta.frame))
        XCTAssertLessThanOrEqual(phrase.frame.maxY, cta.frame.minY + 1)
        XCTAssertTrue(banner.isHittable)

        let video = element(app, "daily-inspiration-video-preview")
        if expectsSideBySide && banner.frame.width > 730 {
            XCTAssertTrue(video.exists)
            XCTAssertLessThanOrEqual(phrase.frame.maxX + 13, video.frame.minX)
        } else {
            XCTAssertFalse(video.exists, "Inactive preview must not expose hidden card or footer controls")
            XCTAssertFalse(element(app, "embed-basic-info-title").exists)
            // Existence alone previously returned for an invisible retained
            // preview. Wait for the real production phase and both AX branches.
            let previewPhase = NSPredicate { _, _ in
                (banner.value as? String) == "How to Build a Great Developer Experience"
                    && video.exists && !phrase.exists && !cta.exists
            }
            expectation(for: previewPhase, evaluatedWith: banner)
            waitForExpectations(timeout: 15)
            XCTAssertFalse(phrase.exists, "Hidden phrase must leave the accessibility and interaction tree")
            XCTAssertFalse(cta.exists, "Inactive CTA must leave the accessibility and interaction tree")
        }
        let footerTitle = element(app, "embed-basic-info-title")
        XCTAssertTrue(footerTitle.exists)
        XCTAssertTrue(banner.frame.contains(footerTitle.frame), "Video footer title must remain inside the visible banner")
        XCTAssertTrue(banner.frame.contains(video.frame), "Entire preview must fit the banner")
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Daily inspiration \(variant) layout"
        attachment.lifetime = .keepAlways
        add(attachment)
        banner.tap()
        XCTAssertEqual(element(app, "dev-preview-local-action").label, "inspiration-started")
    }

    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
