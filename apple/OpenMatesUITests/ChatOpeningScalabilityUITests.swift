// UI tests for deterministic native chat opening.
// Launches the debug-only seeded chat preview and verifies ChatView opens the
// latest bounded window without rendering the full synthetic history.
// No credentials, private chat IDs, or network-backed user data are used here.
// The live-dev seeded chat test can extend this target once the seed endpoint exists.

import XCTest
#if os(iOS)
import UIKit
#endif

@MainActor
final class ChatOpeningScalabilityUITests: XCTestCase {
    private let boundedLaunchLimit: TimeInterval = 20
    private let interactionLimit: TimeInterval = 5

    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,pii.composer.detect-redact-exclude
    @MainActor
    func testDarkChatHasReadableSelectableMessagesAndNoPIIFallbackParagraph() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--dev-preview-theme", "dark"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        // Environment configuration has precedence over launch arguments.
        app.launchEnvironment["DEV_PREVIEW_THEME"] = "dark"
        app.launch()
        let latest = latestAssistantText(in: app)
        XCTAssertTrue(latest.waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertEqual(latest.label, "Latest assistant response visible after bounded open")
        XCTAssertTrue(latest.isHittable)
        #if os(iOS)
        let user = app.textViews.matching(NSPredicate(format: "label == %@", "Seeded user message 249")).firstMatch
        XCTAssertTrue(user.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertTrue(user.isHittable)
        try assertReadableDarkText(in: latest.frame)
        try assertReadableDarkText(in: user.frame)
        #endif
        XCTAssertFalse(app.staticTexts["composer-pii-regex-fallback"].exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Basic pattern detection")).firstMatch.exists)
        XCTAssertTrue(app.textViews["message-editor"].firstMatch.exists)
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "Dark selectable chat without fallback paragraph"
        shot.lifetime = .keepAlways
        add(shot)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSeededLargeChatOpensWithinBoundedWork() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"

        let start = Date()
        app.launch()

        let initialWindow = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "initial-window-count=50"))
            .firstMatch
        XCTAssertTrue(initialWindow.waitForExistence(timeout: 12))
        XCTAssertTrue(initialWindow.label.contains("initial-window-count=50"))
        XCTAssertTrue(initialWindow.label.contains("total-message-count=250"))

        let latestMessage = latestAssistantText(in: app)
        XCTAssertTrue(latestMessage.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(latestMessage.label, "Latest assistant response visible after bounded open")
        XCTAssertTrue(latestMessage.isHittable)
        XCTAssertFalse(app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Seeded user message 1")).firstMatch.exists)
        XCTAssertLessThan(Date().timeIntervalSince(start), boundedLaunchLimit)

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Seeded large chat opened at latest bounded window"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSeededLargeChatCapturesFrameMetricsAndInputReactionTime() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-performance-metrics"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_PERFORMANCE_METRICS"] = "1"
        app.launchEnvironment["UI_TEST_CHAT_MESSAGE_COUNT"] = "1000"

        let launchStart = Date()
        app.launch()

        let latestMessage = latestAssistantText(in: app)
        XCTAssertTrue(latestMessage.waitForExistence(timeout: 16), app.debugDescription)
        XCTAssertEqual(latestMessage.label, "Latest assistant response visible after bounded open")
        XCTAssertTrue(latestMessage.isHittable)
        let latestVisibleSeconds = Date().timeIntervalSince(launchStart)
        if latestVisibleSeconds >= boundedLaunchLimit {
            let probe = app.staticTexts
                .containing(NSPredicate(format: "label CONTAINS %@", "performance-metrics=chat-opening"))
                .firstMatch
            attachText("latest-visible-seconds=\(formatSeconds(latestVisibleSeconds)); \(probe.exists ? probe.label : "metrics-unavailable")",
                       name: "Over-budget chat launch diagnostics")
        }
        XCTAssertLessThan(latestVisibleSeconds, boundedLaunchLimit)

        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "performance-metrics=chat-opening"))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 5))
        let metricsBeforeInput = metrics.label
        XCTAssertTrue(metricsBeforeInput.contains("total-messages=1000"))
        XCTAssertNotNil(metricsBeforeInput.range(of: "frame-samples=[1-9][0-9]*", options: .regularExpression),
                        "Performance proof requires real frame samples from the preview host")

        // Capture a real bounded scroll phase separately from launch/input.
        let history = app.scrollViews["chat-history-container"]
        XCTAssertTrue(history.waitForExistence(timeout: interactionLimit))
        XCTAssertTrue(history.isHittable)
        let metricsBeforeSwipe = metrics.label
        let framesBeforeSwipe = try frameSampleCount(metricsBeforeSwipe)
        history.swipeDown()
        XCTAssertTrue(waitUntil(timeout: interactionLimit) {
            app.buttons["scroll-to-bottom-button"].exists
        }, "The gesture must actually move away from the newest message")
        XCTAssertTrue(waitUntil(timeout: interactionLimit) {
            ((try? self.frameSampleCount(metrics.label)) ?? 0) > framesBeforeSwipe
        }, "The real swipe phase must contribute additional sampled frames")
        let metricsAfterSwipe = metrics.label
        let framesAfterSwipe = try frameSampleCount(metricsAfterSwipe)
        XCTAssertGreaterThan(framesAfterSwipe, framesBeforeSwipe)
        attachText("before-swipe=\(metricsBeforeSwipe); after-swipe=\(metricsAfterSwipe)",
                   name: "Chat opening actual swipe frame metrics")

        let editor = try waitForMessageEditor(in: app, timeout: 5)
        let inputStart = Date()
        editor.tap()
        app.typeText("p")
        let sendButton = app.buttons["send-button"]
        XCTAssertTrue(sendButton.waitForExistence(timeout: interactionLimit))
        XCTAssertTrue(waitUntil(timeout: interactionLimit) { sendButton.isEnabled && sendButton.isHittable })
        let automationSeconds = Date().timeIntervalSince(inputStart)
        XCTAssertEqual(editor.value as? String, "p", "Actual native input must reach the visible editor")
        XCTAssertTrue(waitUntil(timeout: interactionLimit) { metrics.label.contains("input-render-status=presented") })
        let metricsAfterInput = metrics.label
        let elapsedField = metricsAfterInput.split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { $0.hasPrefix("input-render-ms=") }
        let renderMS = try XCTUnwrap(elapsedField.flatMap { Double($0.dropFirst("input-render-ms=".count)) })
        XCTAssertTrue(renderMS.isFinite && renderMS >= 0)
        let inputReactionSeconds = renderMS / 1000
        XCTAssertLessThan(inputReactionSeconds, interactionLimit,
                          "Accepted input event to displayed ready send button must remain below the same five-second bound")

        attachText(
            "latest-visible-seconds=\(formatSeconds(latestVisibleSeconds)); automation-seconds=\(formatSeconds(automationSeconds)); input-reaction-seconds=\(formatSeconds(inputReactionSeconds)); \(metricsBeforeInput); \(metricsAfterInput)",
            name: "Chat opening performance metrics"
        )
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    @MainActor
    func testMiddleAnchorScrollsToActualNewestAndOldestWithBoundedRows() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-history-window-metrics"]
        app.launchEnvironment["UI_TEST_CHAT_MESSAGE_COUNT"] = "120"
        app.launchEnvironment["UI_TEST_CHAT_ANCHOR_INDEX"] = "60"
        app.launch()
        let history = app.scrollViews["chat-history-container"]
        let content = app.descendants(matching: .any)["chat-history-content"].firstMatch
        XCTAssertTrue(history.waitForExistence(timeout: 15))
        XCTAssertTrue(waitUntil(timeout: 5) { self.windowValues(content)["first"] == "seeded-message-52" })
        XCTAssertEqual(windowValues(content)["last"], "seeded-message-101")
        XCTAssertEqual(app.buttons["scroll-to-bottom-button"].value as? String, "19")
        XCTAssertTrue(app.buttons["scroll-to-bottom-button"].isHittable,
                      "Newer history count and navigation stay visible from a saved middle window")
        let savedRow = app.descendants(matching: .any)["chat-history-message-seeded-message-60"].firstMatch
        XCTAssertTrue(waitUntil(timeout: 5) { self.isVisible(savedRow, in: history) })
        assertBoundedRows(app: app, content: content)

        // Test scrolling itself, not merely a direct jump or endpoint metadata.
        let latest = app.descendants(matching: .any)["chat-history-message-seeded-message-120"].firstMatch
        for _ in 0..<40 {
            if isVisible(latest, in: history) && !app.buttons["scroll-to-bottom-button"].exists { break }
            history.swipeUp()
            assertBoundedRows(app: app, content: content)
        }
        XCTAssertTrue(isVisible(latest, in: history))
        XCTAssertEqual(windowValues(content)["newer"], "false")
        XCTAssertFalse(app.buttons["scroll-to-bottom-button"].exists)

        let oldest = app.descendants(matching: .any)["chat-history-message-seeded-message-1"].firstMatch
        for _ in 0..<40 {
            if isVisible(oldest, in: history) && !app.buttons["scroll-to-top-button"].exists { break }
            history.swipeDown()
            assertBoundedRows(app: app, content: content)
        }
        XCTAssertTrue(isVisible(oldest, in: history))
        XCTAssertEqual(windowValues(content)["older"], "false")
        XCTAssertFalse(app.buttons["scroll-to-top-button"].exists)

        // Direct endpoints must replace the source window before scrolling.
        for _ in 0..<3 {
            app.buttons["scroll-to-bottom-button"].tap()
            XCTAssertTrue(waitUntil(timeout: interactionLimit) { self.isVisible(latest, in: history) })
            XCTAssertEqual(windowValues(content)["last"], "seeded-message-120")
            assertBoundedRows(app: app, content: content)
            app.buttons["scroll-to-top-button"].tap()
            XCTAssertTrue(waitUntil(timeout: interactionLimit) { self.isVisible(oldest, in: history) })
            XCTAssertEqual(windowValues(content)["first"], "seeded-message-1")
            assertBoundedRows(app: app, content: content)
        }
        let editor = try waitForMessageEditor(in: app, timeout: interactionLimit)
        editor.tap()
        app.typeText("still responsive")
        XCTAssertTrue(waitUntil(timeout: interactionLimit) { app.buttons["send-button"].isEnabled })
    }

    @MainActor
    private func windowValues(_ content: XCUIElement) -> [String: String] {
        guard let value = content.value as? String else { return [:] }
        return Dictionary(value.split(separator: ";").compactMap { item -> (String, String)? in
            let pair = item.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2 else { return nil }
            return (String(pair[0]), String(pair[1]))
        }, uniquingKeysWith: { _, new in new })
    }

    @MainActor
    private func assertBoundedRows(app: XCUIApplication, content: XCUIElement,
                                   file: StaticString = #filePath, line: UInt = #line) {
        let count = Int(windowValues(content)["rendered"] ?? "") ?? -1
        XCTAssertTrue((1...50).contains(count), "Every committed window stays bounded", file: file, line: line)
        let rowIDs = Set(app.descendants(matching: .any).matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "chat-history-message-")
        ).allElementsBoundByIndex.map(\.identifier))
        XCTAssertEqual(rowIDs.count, count, "Metrics must describe actual mounted message rows", file: file, line: line)
    }

    @MainActor
    private func isVisible(_ row: XCUIElement, in history: XCUIElement) -> Bool {
        guard row.exists, !row.frame.isEmpty else { return false }
        let visibleFrame = row.frame.intersection(history.frame)
        return !visibleFrame.isNull && visibleFrame.height > 1 && visibleFrame.width > 1
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLargeShellFixtureCapturesSidebarReactionTime() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-shell-metrics",
            "--ui-test-shell-performance-fixture"
        ]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launchEnvironment["UI_TEST_SHELL_PERFORMANCE_FIXTURE"] = "1"
        app.launchEnvironment["UI_TEST_SHELL_CHAT_COUNT"] = "600"
        app.launch()

        let metrics = app.descendants(matching: .any)["shell-responsive-metrics"]
        XCTAssertTrue(metrics.waitForExistence(timeout: 15))
        XCTAssertTrue(metrics.label.contains("shell-performance=true"))
        XCTAssertTrue(metrics.label.contains("seeded-chat-count=600"))

        let sidebarToggle = app.buttons["sidebar-toggle"]
        XCTAssertTrue(sidebarToggle.waitForExistence(timeout: 10))
        let sidebarStart = Date()
        sidebarToggle.tap()
        XCTAssertTrue(waitUntil(timeout: interactionLimit) { metrics.label.contains("chat-panel-open=true") })
        let sidebarReactionSeconds = Date().timeIntervalSince(sidebarStart)
        XCTAssertLessThan(sidebarReactionSeconds, interactionLimit)

        attachText(
            "sidebar-reaction-seconds=\(formatSeconds(sidebarReactionSeconds)); \(metrics.label)",
            name: "Large shell sidebar performance metrics"
        )
    }

    private func latestAssistantText(in app: XCUIApplication) -> XCUIElement {
        app.textViews.matching(NSPredicate(format: "label == %@", "Latest assistant response visible after bounded open")).firstMatch
    }

    #if os(iOS)
    /// Verify actual native text pixels; a dark launch flag or accessibility
    /// label alone cannot prove that app theme or foreground conversion worked.
    private func assertReadableDarkText(in frame: CGRect) throws {
        let image = XCUIScreen.main.screenshot().image
        let cgImage = try XCTUnwrap(image.cgImage)
        let visible = frame.intersection(CGRect(origin: .zero, size: image.size))
        XCTAssertFalse(visible.isEmpty)
        let scale = CGFloat(cgImage.width) / image.size.width
        let crop = try XCTUnwrap(cgImage.cropping(to: visible.applying(CGAffineTransform(scaleX: scale, y: scale))))
        var bytes = [UInt8](repeating: 0, count: crop.width * crop.height * 4)
        let counts = try bytes.withUnsafeMutableBytes { buffer -> (dark: Int, light: Int, total: Int) in
            let context = try XCTUnwrap(CGContext(data: buffer.baseAddress, width: crop.width, height: crop.height,
                bitsPerComponent: 8, bytesPerRow: crop.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.draw(crop, in: CGRect(x: 0, y: 0, width: CGFloat(crop.width), height: CGFloat(crop.height)))
            let pixels = buffer.bindMemory(to: UInt8.self)
            var dark = 0, light = 0
            for offset in stride(from: 0, to: pixels.count, by: 4) {
                let maximum = max(pixels[offset], max(pixels[offset + 1], pixels[offset + 2]))
                let minimum = min(pixels[offset], min(pixels[offset + 1], pixels[offset + 2]))
                if maximum < 120 { dark += 1 }
                if minimum > 180 { light += 1 }
            }
            return (dark, light, crop.width * crop.height)
        }
        XCTAssertGreaterThan(Double(counts.dark) / Double(counts.total), 0.6,
            "The native message text region must have a dark background")
        XCTAssertGreaterThan(counts.light, 20,
            "The native message must render light, readable glyphs against its dark background")
    }
    #endif

    @MainActor
    private func waitForMessageEditor(in app: XCUIApplication, timeout: TimeInterval) throws -> XCUIElement {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            let editor = app.descendants(matching: .any)["message-editor"]
            if editor.exists { return editor }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        } while Date() < deadline
        XCTFail("Expected message editor to appear")
        return app.descendants(matching: .any)["message-editor"]
    }

    @MainActor
    private func waitUntil(timeout: TimeInterval, condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        } while Date() < deadline
        return condition()
    }

    @MainActor
    private func attachText(_ text: String, name: String) {
        let attachment = XCTAttachment(string: text)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func frameSampleCount(_ label: String) throws -> Int {
        let field = label.split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { $0.hasPrefix("frame-total=") }
        return try XCTUnwrap(field.flatMap { Int($0.dropFirst("frame-total=".count)) })
    }

    private func formatSeconds(_ value: TimeInterval) -> String {
        String(format: "%.3f", value)
    }
}
