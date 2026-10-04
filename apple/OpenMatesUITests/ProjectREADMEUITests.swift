import XCTest

@MainActor
final class ProjectREADMEUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testReadmeRendersSeparateBlocksAndDecodedImage() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "readme",
            "--dev-preview-theme", "dark", "--dev-preview-width", "390", "--dev-preview-height", "844",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let first = app.descendants(matching: .any)["project-readme-heading-0"]
        XCTAssertTrue(first.waitForExistence(timeout: 8))
        let paragraph = app.descendants(matching: .any)["project-readme-paragraph-1"]
        let second = app.descendants(matching: .any)["project-readme-heading-2"]
        XCTAssertTrue(paragraph.exists)
        XCTAssertTrue(second.exists)
        XCTAssertGreaterThan(paragraph.frame.minY, first.frame.maxY)
        XCTAssertGreaterThan(second.frame.minY, paragraph.frame.maxY)
        XCTAssertTrue(app.descendants(matching: .any)["project-readme-list-3-0"].exists)
        let code = app.descendants(matching: .any)["project-readme-code-4"].firstMatch
        let imageParagraph = app.descendants(matching: .any)["project-readme-paragraph-5"].firstMatch
        let image = imageParagraph.descendants(matching: .image)["project-readme-image-rendered"].firstMatch
        for _ in 0..<6 where !code.exists || code.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(code.exists)
        XCTAssertGreaterThan(code.frame.height, 10)
        for _ in 0..<6 where !image.exists || image.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(imageParagraph.exists, "Image paragraphs retain their own accessibility container")
        XCTAssertTrue(image.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(image.frame.width, 20)
        XCTAssertGreaterThan(image.frame.height, 10)
        XCTAssertFalse(app.staticTexts["[Image: Project overview preview]"].exists)
        let list = app.descendants(matching: .any)["project-readme-list-6-0"].firstMatch
        for _ in 0..<6 where !list.exists || list.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(list.exists)
        XCTAssertTrue(list.descendants(matching: .image)["project-readme-image-rendered"].firstMatch.waitForExistence(timeout: 5),
                      "Reference images in list items must use the real image renderer")
        let table = app.descendants(matching: .any)["project-readme-table-7"].firstMatch
        for _ in 0..<6 where !table.exists || table.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(table.exists)
        XCTAssertTrue(table.staticTexts["Documentation"].exists)
        XCTAssertTrue(table.staticTexts["Ready"].exists)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "README blocks and decoded project image"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
