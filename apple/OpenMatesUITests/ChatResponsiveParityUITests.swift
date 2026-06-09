// Responsive chat parity coverage for the native seeded ChatView preview.
// Runs against simulator form factors to prove native breakpoint decisions match
// the web-mapped chat thresholds without credentials, private data, or network.
// The same test should pass on compact iPhone and regular iPad destinations.

import XCTest

@MainActor
final class ChatResponsiveParityUITests: XCTestCase {
    private let assistantStackedBreakpoint = 500
    private let inlineNewChatCompactBreakpoint = 550

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testChatResponsiveMetricsMatchWebBreakpoints() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-responsive-metrics"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_RESPONSIVE_METRICS"] = "1"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        let metrics = element(in: app, identifier: "chat-responsive-metrics")
        XCTAssertTrue(metrics.waitForExistence(timeout: 5))

        let label = metrics.label
        let chatWidth = try intMetric("chat-width", in: label)
        XCTAssertGreaterThan(chatWidth, 0)
        XCTAssertEqual(
            try boolMetric("assistant-stacked", in: label),
            chatWidth <= assistantStackedBreakpoint,
            "Assistant stacked layout must follow the web <=500px container breakpoint."
        )
        XCTAssertEqual(
            try boolMetric("inline-new-chat-compact", in: label),
            chatWidth <= inlineNewChatCompactBreakpoint,
            "Inline new-chat compact state must follow the web <=550px container breakpoint."
        )

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Chat responsive parity metrics \(chatWidth)pt"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func intMetric(_ key: String, in label: String) throws -> Int {
        let value = try XCTUnwrap(metric(key, in: label), "Missing integer metric \(key) in: \(label)")
        return try XCTUnwrap(Int(value), "Invalid integer metric \(key) in: \(label)")
    }

    private func boolMetric(_ key: String, in label: String) throws -> Bool {
        let value = try XCTUnwrap(metric(key, in: label), "Missing boolean metric \(key) in: \(label)")
        return try XCTUnwrap(Bool(value), "Invalid boolean metric \(key) in: \(label)")
    }

    private func metric(_ key: String, in label: String) -> String? {
        label
            .split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { $0.hasPrefix("\(key)=") }?
            .dropFirst(key.count + 1)
            .description
    }
}
