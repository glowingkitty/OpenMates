// The production compact disclosure is exercised without opening audio or network.
import XCTest

@MainActor
final class WatchVoiceCallConsentUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.privacy.first-call-warning,apple-watch.chats.input-actions
    func testCustomConsentButtonsAreVisibleReachableAndCancelFinishesRequest() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-voice-consent"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["watch-voice-consent"].waitForExistence(timeout: 10))
        let accept = app.buttons["watch-voice-consent-accept"]
        for _ in 0..<6 where !accept.isHittable { app.swipeUp() }
        XCTAssertTrue(accept.isHittable)
        let cancel = app.buttons["watch-voice-consent-cancel"]
        for _ in 0..<6 where !cancel.isHittable { app.swipeUp() }
        XCTAssertTrue(cancel.isHittable)
        let image = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        image.name = "Watch custom voice processing disclosure"; image.lifetime = .keepAlways; add(image)
        cancel.tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-voice-consent-fixture-finished"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["watch-voice-consent-accept"].exists)
    }
}
