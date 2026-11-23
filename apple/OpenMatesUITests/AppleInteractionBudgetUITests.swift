// Interaction budgets for the native app: chat open, scroll, tap reaction, sidebar open.
// Limits use in-app measured timings (systemUptime, frame sampler, composer metrics)
// so simulator launch time never counts; only the sidebar uses a tap-to-state wall clock.
// Every test prints one `PERF_BUDGET metric=<name> value=<n> limit=<n>` line for CI logs.
// Only synthetic dev-preview fixtures are used: no accounts, no network.

import XCTest

/// Every budget limit in one place; tighten as the app gets faster, never loosen to pass.
/// Limits are set from the hosted macos-26 simulator baseline (2026-11-21) plus margin,
/// so they catch regressions on that runner; a real iPhone is several times faster.
struct InteractionBudget {
    /// Max in-app ms from preview appearance to the latest message window laid out (baseline 1738).
    static let chatOpenMS = 2500.0
    /// Max janky frames per 1000 sampled frames during the scroll phase (baseline 0).
    static let scrollHitchPerMille = 100.0
    /// Max in-app ms from accepted key input to the rendered ready send button
    /// (baseline 226 and 440 ms in two runs: the hosted simulator varies about 2x).
    static let inputRenderMS = 650.0
    /// Max wall-clock seconds from sidebar tap to the chat panel being open, 600 chats (baseline 1.57, 1.59).
    static let sidebarOpenSeconds = 2.5
    /// Minimum frames the scroll phase must add, so an idle frame clock cannot pass.
    static let minScrollFrames = 30.0
}

@MainActor
final class AppleInteractionBudgetUITests: XCTestCase {
    private static var simulatorWarmed = false

    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        // A fresh hosted simulator can time out on its first app launch; absorb that
        // once here so it never counts against (or breaks) a measured test.
        if !Self.simulatorWarmed {
            Self.simulatorWarmed = true
            let warm = XCUIApplication()
            warm.launchArguments = ["--dev-preview", "chat-opening"]
            warm.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
            warm.launch()
            warm.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testChatOpenStaysWithinInAppBudget() throws {
        let app = launchSeededChat()
        let metrics = try metricsElement(in: app)
        XCTAssertTrue(waitUntil(timeout: 10) { (self.field("open-ms", in: metrics.label) ?? -1) >= 0 },
                      "open-ms was never recorded: \(metrics.label)")
        let openMS = try XCTUnwrap(field("open-ms", in: metrics.label))
        report("chat_open_ms", openMS, InteractionBudget.chatOpenMS)
        XCTAssertLessThanOrEqual(openMS, InteractionBudget.chatOpenMS,
                                 "metric chat_open_ms value \(openMS) exceeds limit \(InteractionBudget.chatOpenMS)")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testScrollStaysWithinHitchBudget() throws {
        let app = launchSeededChat()
        let metrics = try metricsElement(in: app)
        let history = app.scrollViews["chat-history-container"]
        XCTAssertTrue(history.waitForExistence(timeout: 10))
        let before = metrics.label
        let framesBefore = try XCTUnwrap(field("frame-total", in: before))
        let jankBefore = try XCTUnwrap(field("jank-count", in: before))
        for _ in 0..<3 {
            history.swipeDown()
            history.swipeDown()
            history.swipeUp()
        }
        _ = waitUntil(timeout: 3) { (self.field("frame-total", in: metrics.label) ?? 0) - framesBefore >= InteractionBudget.minScrollFrames }
        let after = metrics.label
        let frameDelta = (try XCTUnwrap(field("frame-total", in: after))) - framesBefore
        let jankDelta = (try XCTUnwrap(field("jank-count", in: after))) - jankBefore
        let worst = try XCTUnwrap(field("worst-frame-ms", in: after))
        XCTAssertGreaterThanOrEqual(frameDelta, InteractionBudget.minScrollFrames,
                                    "scroll phase added only \(frameDelta) frames; frame clock idle?")
        let hitch = max(jankDelta, 0) / max(frameDelta, 1) * 1000
        report("scroll_hitch_per_mille", hitch, InteractionBudget.scrollHitchPerMille)
        // The monitor's worst frame covers the whole run including launch, so it
        // is reported for context only; the hitch rate is the scroll-phase budget.
        print("PERF_INFO metric=worst_frame_since_launch_ms value=\(String(format: "%.2f", worst))")
        XCTAssertLessThanOrEqual(hitch, InteractionBudget.scrollHitchPerMille,
                                 "metric scroll_hitch_per_mille value \(hitch) exceeds limit \(InteractionBudget.scrollHitchPerMille)")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTapReactionStaysWithinInputRenderBudget() throws {
        let app = launchSeededChat()
        let metrics = try metricsElement(in: app)
        let editor = app.descendants(matching: .any)["message-editor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        editor.tap()
        app.typeText("p")
        XCTAssertTrue(waitUntil(timeout: 5) { metrics.label.contains("input-render-status=presented") },
                      "input render never presented: \(metrics.label)")
        let renderMS = try XCTUnwrap(field("input-render-ms", in: metrics.label))
        report("input_render_ms", renderMS, InteractionBudget.inputRenderMS)
        XCTAssertLessThanOrEqual(renderMS, InteractionBudget.inputRenderMS,
                                 "metric input_render_ms value \(renderMS) exceeds limit \(InteractionBudget.inputRenderMS)")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSidebarOpenWith600ChatsStaysWithinBudget() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-shell-metrics",
                               "--ui-test-shell-performance-fixture"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launchEnvironment["UI_TEST_SHELL_PERFORMANCE_FIXTURE"] = "1"
        app.launchEnvironment["UI_TEST_SHELL_CHAT_COUNT"] = "600"
        app.launch()
        let metrics = app.descendants(matching: .any)["shell-responsive-metrics"]
        XCTAssertTrue(metrics.waitForExistence(timeout: 15))
        XCTAssertTrue(metrics.label.contains("seeded-chat-count=600"))
        let toggle = app.buttons["sidebar-toggle"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 10))
        let start = Date()
        toggle.tap()
        let opened = waitUntil(timeout: 5) { metrics.label.contains("chat-panel-open=true") }
        let seconds = Date().timeIntervalSince(start)
        report("sidebar_open_seconds", seconds, InteractionBudget.sidebarOpenSeconds)
        XCTAssertTrue(opened, "sidebar never opened within 5 s: \(metrics.label)")
        XCTAssertLessThanOrEqual(seconds, InteractionBudget.sidebarOpenSeconds,
                                 "metric sidebar_open_seconds value \(seconds) exceeds limit \(InteractionBudget.sidebarOpenSeconds)")
    }

    private func launchSeededChat() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-performance-metrics"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_PERFORMANCE_METRICS"] = "1"
        app.launchEnvironment["UI_TEST_CHAT_MESSAGE_COUNT"] = "1000"
        app.launch()
        return app
    }

    private func metricsElement(in app: XCUIApplication) throws -> XCUIElement {
        let latest = app.textViews.matching(NSPredicate(format: "label == %@", "Latest assistant response visible after bounded open")).firstMatch
        XCTAssertTrue(latest.waitForExistence(timeout: 20), app.debugDescription)
        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "performance-metrics=chat-opening"))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 10))
        return metrics
    }

    /// Numeric `name=<value>` field of a `;`-separated metrics label.
    private func field(_ name: String, in label: String) -> Double? {
        label.split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { $0.hasPrefix("\(name)=") }
            .flatMap { Double($0.dropFirst(name.count + 1)) }
    }

    private func report(_ metric: String, _ value: Double, _ limit: Double) {
        let line = "PERF_BUDGET metric=\(metric) value=\(String(format: "%.2f", value)) limit=\(String(format: "%.2f", limit))"
        print(line)
        let attachment = XCTAttachment(string: line)
        attachment.name = "Interaction budget \(metric)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func waitUntil(timeout: TimeInterval, condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        } while Date() < deadline
        return condition()
    }
}
