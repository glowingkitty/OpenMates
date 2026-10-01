// Synthetic authenticated state drives the production Teams controls.
// All fixture teams/invites stay in memory; no live account/team/email mutations.
import XCTest

@MainActor
final class SettingsTeamsParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated,settings-ui.navigation.parent-return,settings-ui.parity.web-apple-shell
    func testCreateTeamDetailInviteAndParentReturnWithSyntheticState() {
        let app = launchTeams()
        XCTAssertTrue(element("settings-teams-empty", app).waitForExistence(timeout: 5))
        XCTAssertFalse(app.tables.firstMatch.exists)
        attachScreenshot("Teams empty overview", app: app)
        let name = scrollTo("settings-team-name", app)
        let create = scrollTo("settings-team-create", app)
        XCTAssertFalse(create.isEnabled, "A blank team name must disable creation")
        scrollTo("settings-team-name", app).tap()
        name.typeText("Synthetic parity team\n")
        let enabledCreate = scrollTo("settings-team-create", app)
        XCTAssertTrue(enabledCreate.isEnabled); enabledCreate.tap()
        XCTAssertTrue(element("settings-team-detail-card", app).waitForExistence(timeout: 8))
        XCTAssertFalse(element("settings-teams-empty", app).exists)
        XCTAssertTrue(app.staticTexts["Synthetic parity team"].firstMatch.exists)
        attachScreenshot("Teams created team detail before invite", app: app)
        let email = scrollTo("settings-team-invite-email", app)
        email.tap(); email.typeText("teammate@example.com\n")
        let invite = scrollTo("settings-team-send-invite", app)
        XCTAssertTrue(invite.isEnabled); invite.tap()
        XCTAssertTrue(element("settings-team-invite-result", app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Invite sent"].exists)
        attachScreenshot("Teams detail with invite result", app: app)
        let back = app.buttons["settings-destination-back"]
        XCTAssertTrue(back.isHittable); back.tap()
        let joined = scrollTo("settings-team-ui-test-created-team", app)
        XCTAssertTrue(joined.isHittable); joined.tap()
        XCTAssertTrue(element("settings-team-detail-card", app).waitForExistence(timeout: 5))
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(element("settings-menu", app).waitForExistence(timeout: 5))
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Teams synthetic create detail invite and return"
        attachment.lifetime = .keepAlways; add(attachment)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability,teams.membership.role-gated
    func testGuestTeamsLinksRequireAuthentication() {
        for path in ["teams", "teams/synthetic-private-team"] {
            let app = XCUIApplication()
            app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-link-fixture"]
            app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = path
            app.launch()
            let link = element("ui-test-settings-link", app)
            XCTAssertTrue(link.waitForExistence(timeout: 15)); XCTAssertTrue(link.isHittable); link.tap()
            let signup = app.buttons["auth-signup-tab"]
            XCTAssertTrue(signup.waitForExistence(timeout: 8)); XCTAssertTrue(signup.isHittable)
            XCTAssertFalse(element("settings-team-create", app).exists)
            XCTAssertFalse(element("settings-team-detail-card", app).exists)
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.parent-return
    func testMissingTeamLinkShowsExplicitUnavailableStateAndReturns() {
        let app = launchTeams(path: "teams/synthetic-unavailable-team")
        XCTAssertTrue(element("settings-team-unavailable", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-team-detail-card", app).exists)
        let back = app.buttons["settings-destination-back"]
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(element("settings-team-create", app).waitForExistence(timeout: 5))
    }

    private func launchTeams(path: String = "teams") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-authenticated-chat-navigation",
                               "--ui-test-teams-settings-fixture", "--ui-test-app-link-fixture"]
        app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = path
        app.launch()
        let link = element("ui-test-settings-link", app)
        XCTAssertTrue(link.waitForExistence(timeout: 15)); XCTAssertTrue(link.isHittable); link.tap()
        XCTAssertTrue(element("settings-teams-page", app).waitForExistence(timeout: 8))
        return app
    }
    private func element(_ id: String, _ app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }
    private func attachScreenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    @discardableResult private func scrollTo(_ id: String, _ app: XCUIApplication) -> XCUIElement {
        let target = element(id, app)
        for _ in 0..<6 {
            if target.exists && target.isHittable { break }
            app.swipeDown()
        }
        for _ in 0..<12 {
            if target.exists && target.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(target.exists, id); XCTAssertTrue(target.isHittable, id)
        XCTAssertGreaterThan(target.frame.width, 0); XCTAssertGreaterThan(target.frame.height, 0)
        XCTAssertTrue(app.frame.intersects(target.frame), id)
        return target
    }
}
