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
        scrollTo("team-create-open", app).tap()
        let name = scrollTo("settings-team-name", app)
        let create = scrollTo("team-create-continue", app)
        XCTAssertFalse(create.isEnabled, "A blank team name must disable creation")
        scrollTo("settings-team-name", app).tap()
        name.typeText("Synthetic parity team\n")
        let enabledCreate = scrollTo("team-create-continue", app)
        XCTAssertTrue(enabledCreate.isEnabled); enabledCreate.tap()
        XCTAssertTrue(element("team-avatar-preview", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-team-detail-card", app).exists, "Continue must not create a Team")
        XCTAssertTrue(scrollTo("team-avatar-upload", app).isHittable)
        scrollTo("team-avatar-regenerate", app).tap()
        XCTAssertTrue(scrollTo("team-avatar-icon", app).isHittable)
        attachScreenshot("Teams creation avatar step before submit", app: app)
        scrollTo("team-create-submit", app).tap()
        XCTAssertTrue(element("settings-team-detail-card", app).waitForExistence(timeout: 8))
        XCTAssertFalse(element("settings-teams-empty", app).exists)
        XCTAssertTrue(app.staticTexts["Synthetic parity team"].firstMatch.exists)
        XCTAssertFalse(element("settings-teams-account-info", app).exists)
        XCTAssertFalse(element("settings-team-personal-boundary", app).exists)
        XCTAssertTrue(element("team-members-open", app).exists)
        XCTAssertTrue(app.buttons["team-members-open"].firstMatch.exists, "Detail actions retain their individual Button identity")
        XCTAssertTrue(element("team-security-open", app).exists)
        XCTAssertTrue(element("team-name-open", app).exists)
        XCTAssertTrue(element("team-avatar-open", app).exists)
        attachScreenshot("Teams created team detail before invite", app: app)
        scrollTo("team-members-open", app).tap()
        XCTAssertTrue(element("team-invite-members-guidance", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-team-send-invite", app).exists, "Web hides the invite CTA until an email is entered")
        XCTAssertTrue(element("team-invite-sharing-guidance", app).exists)
        let email = scrollTo("settings-team-invite-email", app)
        email.tap(); email.typeText("teammate@example.com\n")
        let invite = scrollTo("settings-team-send-invite", app)
        XCTAssertTrue(invite.isEnabled); invite.tap()
        XCTAssertTrue(element("settings-team-invite-result", app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Invite ready; awaiting acceptance"].exists)
        XCTAssertTrue(element("team-invite-open-email", app).exists)
        XCTAssertTrue(element("team-invite-copy-secure-link", app).exists)
        XCTAssertTrue(element("team-invite-share-link-info", app).exists)
        XCTAssertFalse(element("settings-team-send-invite", app).exists, "Successful invite clears its field and hides its CTA")
        attachScreenshot("Teams detail with invite result", app: app)
        let back = app.buttons["settings-destination-back"]
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(element("settings-team-detail-card", app).waitForExistence(timeout: 5))
        back.tap()
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

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled,settings-ui.parity.web-apple-shell
    func testOwnerProtectionAndAvatarControlsUseProductionSettingsShell() {
        let app = launchTeams()
        scrollTo("team-create-open", app).tap()
        let name = scrollTo("settings-team-name", app); name.tap(); name.typeText("Avatar parity team\n")
        scrollTo("team-create-continue", app).tap()
        scrollTo("team-create-submit", app).tap()
        XCTAssertTrue(element("settings-team-detail-card", app).waitForExistence(timeout: 8))
        scrollTo("team-members-open", app).tap()
        XCTAssertTrue(element("team-member-avatar-generated-synthetic-owner", app).waitForExistence(timeout: 5))
        scrollTo("team-member-row", app).tap()
        XCTAssertTrue(element("team-member-avatar-generated-synthetic-owner", app).exists)
        XCTAssertFalse(element("team-member-remove", app).exists, "Owner removal must remain unavailable")
        XCTAssertFalse(element("team-member-detail-role", app).exists, "Owner role must remain immutable")
        attachScreenshot("Teams owner protection", app: app)
        app.buttons["settings-destination-back"].tap()
        app.buttons["settings-destination-back"].tap()
        scrollTo("team-avatar-open", app).tap()
        XCTAssertTrue(scrollTo("team-avatar-upload", app).isHittable)
        XCTAssertFalse(element("team-avatar-icon", app).exists)
        scrollTo("team-avatar-regenerate", app).tap()
        XCTAssertTrue(scrollTo("team-avatar-icon", app).isHittable)
        XCTAssertTrue(scrollTo("team-avatar-color", app).isHittable)
        let save = scrollTo("team-avatar-save", app); XCTAssertTrue(save.isEnabled); save.tap()
        XCTAssertTrue(element("settings-team-detail-card", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("team-action-error", app).exists)
        attachScreenshot("Teams avatar editor and upload control", app: app)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,settings-ui.navigation.parent-return
    func testCreationAvatarBackPreservesNameAndHasNoTeamBeforeSubmit() {
        let app = launchTeams()
        scrollTo("team-create-open", app).tap()
        let name = scrollTo("settings-team-name", app); name.tap(); name.typeText("Back-preserved team\n")
        scrollTo("team-create-continue", app).tap()
        XCTAssertTrue(element("team-avatar-preview", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-team-detail-card", app).exists)
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(element("settings-team-name", app).waitForExistence(timeout: 5))
        XCTAssertEqual(element("settings-team-name", app).value as? String, "Back-preserved team")
        scrollTo("team-create-continue", app).tap()
        XCTAssertTrue(element("team-create-submit", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-team-detail-card", app).exists)
        attachScreenshot("Teams creation name retained after avatar back", app: app)
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
            XCTAssertFalse(element("team-create-submit", app).exists)
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
        XCTAssertTrue(element("team-create-open", app).waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.parent-return
    func testDirectNewTeamRouteStartsNameThenAvatarWithoutUnavailableTeam() {
        let app = launchTeams(path: "teams/new")
        XCTAssertTrue(element("settings-team-name", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-team-unavailable", app).exists)
        XCTAssertFalse(element("team-avatar-preview", app).exists)
        let name = scrollTo("settings-team-name", app)
        name.tap(); name.typeText("Direct route parity team\n")
        scrollTo("team-create-continue", app).tap()
        XCTAssertTrue(element("team-avatar-preview", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-team-detail-card", app).exists)
        app.buttons["settings-destination-back"].firstMatch.tap()
        XCTAssertTrue(element("settings-team-name", app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("team-avatar-preview", app).exists)
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
