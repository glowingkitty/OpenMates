// Canonical Mail preview/fullscreen matches the public web draft fixture.
// Web: embeds/mail/MailEmbedPreview.svelte, embeds/mail/MailEmbedFullscreen.svelte
import XCTest
import UIKit

@MainActor
final class MailEmbedParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMailPreviewShowsBodyAndCanonicalFooter() {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launch(surface: "preview")
        let body = app.staticTexts["mail-body-preview"]
        XCTAssertTrue(body.waitForExistence(timeout: 8))
        XCTAssertTrue(body.label.hasPrefix("Hi Anna,\nThe latest sprint review went well."))
        XCTAssertFalse(body.label.contains("\n\n"))
        XCTAssertTrue(app.staticTexts["Project Update — Sprint 12 Review"].exists)
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "To [EMAIL_1_com]")).firstMatch.exists)
        let card = app.buttons["embed-preview"]
        XCTAssertTrue(card.exists)
        // BasicInfosBar occupies the final 61 points of the 200-point card.
        // The mail details fill and center in the remaining content area.
        XCTAssertEqual(body.frame.midY, card.frame.midY - 30.5, accuracy: 8)
        XCTAssertGreaterThanOrEqual(body.frame.minY, card.frame.minY)
        XCTAssertLessThanOrEqual(body.frame.maxY, card.frame.maxY - 55)
        attach("Mail canonical preview")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMailFullscreenFieldsAndClientActionNarrow() {
        verifyFullscreen(orientation: .portrait, name: "Mail canonical fullscreen narrow")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMailFullscreenFieldsAndClientActionWide() {
        verifyFullscreen(orientation: .landscapeLeft, name: "Mail canonical fullscreen wide")
    }

    private func verifyFullscreen(orientation: UIDeviceOrientation, name: String) {
        XCUIDevice.shared.orientation = orientation
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launch(surface: "fullscreen")
        let receiver = app.descendants(matching: .any)["mail-receiver"]
        XCTAssertTrue(receiver.waitForExistence(timeout: 8))
        XCTAssertEqual(receiver.label, "[EMAIL_1_com]")
        let subject = app.descendants(matching: .any)["mail-subject"]
        let content = app.descendants(matching: .any)["mail-content"]
        XCTAssertEqual(subject.label, "Project Update — Sprint 12 Review")
        XCTAssertTrue(content.label.contains("Hi Anna,\n\nThe latest sprint review"))
        XCTAssertTrue(content.label.hasSuffix("Best,\nMax"))
        XCTAssertLessThan(receiver.frame.minY, subject.frame.minY)
        XCTAssertLessThan(subject.frame.minY, content.frame.minY)
        let panel = app.descendants(matching: .any)["mail-fullscreen-content"]
        XCTAssertTrue(panel.exists)
        let frames = XCTAttachment(string: "panel=\(panel.frame); receiver=\(receiver.frame); subject=\(subject.frame); bodyText=\(content.frame); action=\(app.buttons["mail-open-client"].frame)")
        frames.name = "Mail rendered field and action bounds"
        frames.lifetime = .keepAlways
        add(frames)
        attach("Mail fullscreen before geometry assertions")
        // The painted panel starts 12 points inside the scroll viewport; its
        // fields start a further 16 points inside the panel border.
        let viewport = app.scrollViews["embed-fullscreen-scroll"]
        XCTAssertTrue(viewport.exists)
        XCTAssertEqual(panel.frame.minX - viewport.frame.minX, 12, accuracy: 1)
        XCTAssertEqual(viewport.frame.maxX - panel.frame.maxX, 12, accuracy: 1)
        XCTAssertEqual(receiver.frame.minX - panel.frame.minX, 16, accuracy: 1)
        XCTAssertEqual(panel.frame.maxX - receiver.frame.maxX, 16, accuracy: 1)
        XCTAssertEqual(receiver.frame.minX - viewport.frame.minX, 28, accuracy: 1)
        XCTAssertEqual(receiver.frame.height, 20.3, accuracy: 1)
        XCTAssertEqual(subject.frame.height, 20.3, accuracy: 1)
        // Native selectable-text accessibility bounds describe the text inside
        // the bordered body, which adds the web's 12-point horizontal padding.
        XCTAssertEqual(content.frame.minX - receiver.frame.minX, 12, accuracy: 1)
        XCTAssertEqual(receiver.frame.maxX - content.frame.maxX, 12, accuracy: 1)
        if orientation == .landscapeLeft {
            XCTAssertGreaterThan(app.frame.width, app.frame.height)
        } else {
            XCTAssertLessThan(app.frame.width, app.frame.height)
        }
        let action = app.buttons["mail-open-client"]
        XCTAssertTrue(action.exists && action.isHittable)
        XCTAssertEqual(action.label, "Open in Mail App")
        XCTAssertEqual(action.frame.height, viewport.frame.width <= 600 ? 41 : 45, accuracy: 1)
        if viewport.frame.width <= 600 {
            XCTAssertEqual(action.frame.width, 162, accuracy: 2)
        } else {
            XCTAssertGreaterThanOrEqual(action.frame.width, 200)
        }
        attach(name)
    }

    private func launch(surface: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "mail", "--embed-registry-key", "mail-email", "--embed-surface", surface]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "mail"
        app.launch()
        return app
    }

    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
