// Logged-out landing onboarding parity coverage.
// Launches the native app without cached auth and verifies the web contract's
// durable product story order, active-app intro rails, manual navigation, and
// final signup CTA on the real new-chat welcome surface.
//
// Web source: frontend/apps/web_app/tests/landing-page-onboarding-refresh.spec.ts
// Contract: contracts/features/landing-onboarding/contract.yml

import XCTest

@MainActor
final class LandingOnboardingParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-sequence,landing-onboarding.intro-active-apps-only,landing-onboarding.coordinated-story-progress,landing-onboarding.manual-navigation,landing-onboarding.actionable-demo-faithful,landing-onboarding.privacy-mates-platform-stories,landing-onboarding.signup-cta,landing-onboarding.apple-web-parity
    func testLoggedOutLandingOnboardingMatchesContractSequenceAndSignupCTA() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"]
        app.launch()

        XCTAssertTrue(waitForStory("openmates-intro", in: app, timeout: 15))
        XCTAssertTrue(app.descendants(matching: .any)["daily-inspiration-card"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["message-editor"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.descendants(matching: .any)["landing-intro-expanded"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["landing-intro-headline"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["landing-intro-request"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["daily-inspiration-carousel-progress"].exists)

        for appId in ["health", "events", "code", "news"] {
            XCTAssertTrue(app.descendants(matching: .any)["landing-intro-app-icon-\(appId)"].exists, "Missing intro app icon \(appId)")
        }
        XCTAssertFalse(app.descendants(matching: .any)["landing-intro-app-icon-ai"].exists)

        tapNext(in: app)
        XCTAssertTrue(waitForStory("openmates-actionable-events", in: app))
        XCTAssertTrue(app.descendants(matching: .any)["landing-actionable-demo"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["landing-actionable-event-cta"].exists)

        tapNext(in: app)
        XCTAssertTrue(waitForStory("openmates-privacy-safety", in: app))
        XCTAssertTrue(app.descendants(matching: .any)["landing-product-story-openmates-privacy-safety"].exists)

        let previous = app.buttons["daily-inspiration-previous"]
        XCTAssertTrue(previous.exists)
        previous.tap()
        XCTAssertTrue(waitForStory("openmates-actionable-events", in: app))

        tapNext(in: app)
        XCTAssertTrue(waitForStory("openmates-privacy-safety", in: app))
        tapNext(in: app)
        XCTAssertTrue(waitForStory("openmates-mates-focus", in: app))
        XCTAssertTrue(app.descendants(matching: .any)["landing-product-story-openmates-mates-focus"].exists)
        tapNext(in: app)
        XCTAssertTrue(waitForStory("openmates-provider-cross-platform", in: app))
        XCTAssertTrue(app.descendants(matching: .any)["landing-product-story-openmates-provider-cross-platform"].exists)
        tapNext(in: app)
        XCTAssertTrue(waitForStory("openmates-signup-cta", in: app))

        XCTAssertFalse(app.buttons["daily-inspiration-next"].exists, "Signup is the terminal landing slide")
        XCTAssertTrue(app.descendants(matching: .any)["landing-signup-benefits"].exists)
        let signupCTA = app.buttons["landing-signup-cta"]
        XCTAssertTrue(signupCTA.waitForExistence(timeout: 5))
        signupCTA.tap()

        XCTAssertTrue(
            app.buttons["auth-signup-tab"].waitForExistence(timeout: 8) || app.buttons["auth-login-tab"].waitForExistence(timeout: 2),
            "Landing signup CTA must open the existing auth interface"
        )
        XCTAssertFalse(app.tables.firstMatch.exists, "Product landing UI must not render default List/table chrome")
        attachScreenshot(name: "Logged-out landing onboarding parity")
    }

    private func tapNext(in app: XCUIApplication) {
        let next = app.buttons["daily-inspiration-next"]
        XCTAssertTrue(next.waitForExistence(timeout: 5))
        next.tap()
    }

    private func waitForStory(_ storyId: String, in app: XCUIApplication, timeout: TimeInterval = 5) -> Bool {
        let marker = app.staticTexts["landing-story-id"]
        let expected = "landing-story-id=\(storyId)"
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if marker.exists && marker.label == expected {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return marker.exists && marker.label == expected
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
