// UI smoke coverage for skill, application, code, and file/media parity fixtures.
// Runs only debug preview galleries with synthetic data, avoiding credentials,
// provider calls, private files, code-run logs, and private screenshots.

import XCTest

@MainActor
final class SkillApplicationParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSkillApplicationAndMediaPreviewSectionsRenderWithoutRawPayloadLeaks() throws {
        assertPreviewApp(
            "code",
            exposesSkillSections: [
                "dev-preview-skill-code-code",
                "dev-preview-skill-code-application",
                "dev-preview-skill-code-get-docs",
            ]
        )
        assertPreviewApp(
            "images",
            exposesSkillSections: [
                "dev-preview-skill-images-generate",
                "dev-preview-skill-images-upload",
                "dev-preview-skill-images-view",
            ]
        )
        assertPreviewApp("pdf", exposesSkillSections: ["dev-preview-skill-pdf"])
        assertPreviewApp("videos", exposesSkillSections: ["dev-preview-skill-videos-generate"])
    }

    private func assertPreviewApp(_ slug: String, exposesSkillSections sectionIdentifiers: [String]) {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", slug]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = slug
        app.launch()

        XCTAssertTrue(
            app.descendants(matching: .any)["dev-embed-preview-gallery"].waitForExistence(timeout: 8),
            "\(slug) gallery did not load. Visible UI: \(visibleStateLabels(in: app))"
        )
        XCTAssertFalse(app.tables.firstMatch.exists, "\(slug) preview must not render default List/table chrome")

        for identifier in sectionIdentifiers {
            XCTAssertTrue(
                waitForElement(identifier, in: app, timeout: 8),
                "Expected \(identifier). Visible UI: \(visibleStateLabels(in: app))"
            )
        }

        assertNoRawPayloadLeak(in: app, appSlug: slug)
        attachScreenshot(name: "Skill application preview \(slug)")
        app.terminate()
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<5 where scrollView.exists {
            scrollView.swipeUp()
            if element.waitForExistence(timeout: 1) { return true }
        }
        return false
    }

    private func assertNoRawPayloadLeak(in app: XCUIApplication, appSlug: String) {
        let forbiddenFragments = ["app_skill_use", "encrypted_content", "private_url", "secret", "api_key"]
        let visibleText = visibleStateLabels(in: app).lowercased()
        for fragment in forbiddenFragments {
            XCTAssertFalse(visibleText.contains(fragment), "\(appSlug) leaked raw payload fragment: \(fragment)")
        }
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        let buttons = elementSummaries(app.buttons.allElementsBoundByIndex, prefix: "button")
        return (staticTexts + buttons).prefix(80).joined(separator: " | ")
    }

    private func elementSummaries(_ elements: [XCUIElement], prefix: String) -> [String] {
        elements.compactMap { element in
            let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
            let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !identifier.isEmpty || !label.isEmpty else { return nil }
            if identifier.isEmpty { return "\(prefix):\(redact(label))" }
            if label.isEmpty || label == identifier { return "\(prefix)#\(identifier)" }
            return "\(prefix)#\(identifier)=\(redact(label))"
        }
    }

    private func redact(_ value: String) -> String {
        value.contains("@") ? "<email>" : value
    }
}
