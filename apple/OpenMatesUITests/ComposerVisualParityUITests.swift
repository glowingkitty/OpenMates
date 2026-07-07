// Visual contract smoke coverage for the shared Apple message composer.
// Uses deterministic dev-preview surfaces to assert shared identifiers and the
// web 629pt max-width contract without credentials, network calls, private chat
// records, or system picker automation.
// Screenshots are attached as review artifacts; assertions stay deterministic.

import XCTest

@MainActor
final class ComposerVisualParityUITests: XCTestCase {
    private let maxComposerWidth: CGFloat = 629
    private let widthTolerance: CGFloat = 8
    private let welcomeComposerButtonIds = [
        "attach-files-button",
        "share-location-button",
        "sketch-button",
        "take-photo-button",
        "record-audio-button",
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testChatPreviewComposerUsesSharedIdentifiersAndWidthCap() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        let editor = app.textViews.firstMatch.exists ? app.textViews.firstMatch : app.textFields.firstMatch

        XCTAssertTrue(editor.waitForExistence(timeout: 8), "Expected visible composer editor. Visible UI: \(app.debugDescription)")
        XCTAssertLessThanOrEqual(editor.frame.width, maxComposerWidth + widthTolerance)

        editor.tap()
        XCTAssertFalse(app.tables.firstMatch.exists, "Product composer UI must not render default List/table chrome")

        attachScreenshot(name: "Shared composer chat preview width cap")
    }

    func testFocusedWelcomeComposerScreenshotShowsActionButtons() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"]
        app.launch()

        let skip = app.buttons["guest-interest-skip"]
        if skip.waitForExistence(timeout: 12) {
            skip.tap()
        }

        let editor = waitForMessageEditor(in: app)
        editor.tap()

        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))
        let screenshot = XCUIScreen.main.screenshot()
        for identifier in welcomeComposerButtonIds {
            assertButtonIsVisibleInScreenshot(app.buttons[identifier], identifier: identifier, in: app, screenshot: screenshot)
        }
        attachScreenshot(screenshot, name: "Focused welcome composer action buttons visible")
    }

    func testQuickCaptureComposerUsesSameSharedIdentifierContract() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview",
            "quick-capture",
            "--ui-test-seed-quick-capture-recent-chat"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "quick-capture"
        app.launch()

        XCTAssertTrue(element(in: app, identifier: "quick-capture-tab-chats").waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "quick-capture-composer").exists)
        XCTAssertTrue(element(in: app, identifier: "message-field").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-record-audio-button").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-send-button").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-recent-chats").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-status-list").exists)

        attachScreenshot(name: "Shared composer quick capture contract")
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func waitForMessageEditor(in app: XCUIApplication) -> XCUIElement {
        let candidates = [
            app.textFields.matching(identifier: "message-editor").firstMatch,
            app.textViews.matching(identifier: "message-editor").firstMatch,
            app.descendants(matching: .any).matching(NSPredicate(format: "identifier == %@", "message-editor")).firstMatch,
        ]
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if let editor = candidates.first(where: { $0.exists }) {
                return editor
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTFail("Expected message editor to exist. Visible UI: \(app.debugDescription)")
        return candidates[0]
    }

    private func assertButtonIsVisibleInScreenshot(
        _ button: XCUIElement,
        identifier: String,
        in app: XCUIApplication,
        screenshot: XCUIScreenshot,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(button.waitForExistence(timeout: 5), "Expected \(identifier) to exist", file: file, line: line)
        XCTAssertTrue(button.isHittable, "Expected \(identifier) to be hittable", file: file, line: line)

        let windowFrame = app.windows.firstMatch.frame
        let visibleFrame = button.frame.intersection(windowFrame)
        XCTAssertGreaterThan(visibleFrame.width, 18, "Expected \(identifier) visible width", file: file, line: line)
        XCTAssertGreaterThan(visibleFrame.height, 18, "Expected \(identifier) visible height", file: file, line: line)

        #if canImport(UIKit)
        let buttonScreenshot = button.screenshot()
        guard let image = UIImage(data: buttonScreenshot.pngRepresentation), let cgImage = image.cgImage else {
            XCTFail("Could not decode button screenshot while checking \(identifier)", file: file, line: line)
            return
        }

        var pixels = [UInt8](repeating: 0, count: cgImage.width * cgImage.height * 4)
        guard let context = CGContext(
            data: &pixels,
            width: cgImage.width,
            height: cgImage.height,
            bitsPerComponent: 8,
            bytesPerRow: cgImage.width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
            XCTFail("Could not prepare button screenshot pixels while checking \(identifier)", file: file, line: line)
            return
        }

        context.translateBy(x: 0, y: CGFloat(cgImage.height))
        context.scaleBy(x: 1, y: -1)
        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: cgImage.width, height: cgImage.height))

        let highlightedPixelRatio = highlightedPixelRatio(
            in: CGRect(x: 0, y: 0, width: cgImage.width, height: cgImage.height),
            pixels: pixels,
            imageWidth: cgImage.width,
            imageHeight: cgImage.height,
            scaleX: 1,
            scaleY: 1
        )
        XCTAssertGreaterThan(
            highlightedPixelRatio,
            0.02,
            "Expected \(identifier) screenshot region to contain visible icon pixels, ratio \(highlightedPixelRatio)",
            file: file,
            line: line
        )
        #endif
    }

    #if canImport(UIKit)
    private func highlightedPixelRatio(
        in rect: CGRect,
        pixels: [UInt8],
        imageWidth: Int,
        imageHeight: Int,
        scaleX: CGFloat,
        scaleY: CGFloat
    ) -> Double {
        let minX = max(0, Int((rect.minX * scaleX).rounded(.down)))
        let maxX = min(imageWidth - 1, Int((rect.maxX * scaleX).rounded(.up)))
        let minY = max(0, Int((rect.minY * scaleY).rounded(.down)))
        let maxY = min(imageHeight - 1, Int((rect.maxY * scaleY).rounded(.up)))
        var highlighted = 0
        var total = 0

        for y in minY...maxY {
            for x in minX...maxX {
                let offset = (y * imageWidth + x) * 4
                let red = Int(pixels[offset])
                let green = Int(pixels[offset + 1])
                let blue = Int(pixels[offset + 2])
                let maxChannel = max(red, green, blue)
                let minChannel = min(red, green, blue)
                if maxChannel > 110 && maxChannel - minChannel > 24 {
                    highlighted += 1
                }
                total += 1
            }
        }

        guard total > 0 else { return 0 }
        return Double(highlighted) / Double(total)
    }
    #endif

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func attachScreenshot(_ screenshot: XCUIScreenshot, name: String) {
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
