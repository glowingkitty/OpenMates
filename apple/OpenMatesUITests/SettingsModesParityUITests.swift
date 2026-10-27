// Native settings mode flow UI coverage for deterministic guest/test state.
// Mirrors web Incognito and Learning Mode settings identifiers and verifies
// controls are rendered and clickable without private account credentials.
// Real-account API behavior remains covered by unit contract tests.
// Screenshots and labels contain synthetic fixture state only.

import XCTest

@MainActor
final class SettingsModesParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.contextual-availability
    func testGuestLearningSetupCanBeEnabledAndDisabledThroughOwnedRoute() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-link-fixture"]
        app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = "learning-mode/setup"
        app.launch()
        let link = app.descendants(matching: .any)["ui-test-settings-link"]
        XCTAssertTrue(link.waitForExistence(timeout: 15))
        XCTAssertTrue(link.isHittable)
        link.tap()

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-settings-page"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-age-group-dropdown"].exists)
        let enable = app.buttons["learning-mode-enable-button"].firstMatch
        XCTAssertTrue(enable.exists && enable.isHittable)
        enable.tap()

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-status-enabled"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["learning-mode-disable-button"].firstMatch.tap()
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-status-disabled"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.composition.canonical-and-accessible
    func testAccountLearningModeRendersPasscodeProtectedManagement() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-account-settings-fixture"])
        let learningRow = app.descendants(matching: .any)["learning-mode-toggle-wrapper"]
        XCTAssertTrue(learningRow.waitForExistence(timeout: 5))
        tapToggle("learning-mode-toggle-wrapper", in: app)

        XCTAssertTrue(app.secureTextFields["learning-mode-passcode-input"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["learning-mode-enable-button"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,message-input.privacy-context
    func testIncognitoFirstActivationUsesExplainerAndHandledActivationEvent() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-authenticated-chat-navigation", "--ui-test-account-settings-fixture", "--ui-test-reset-incognito-explainer"])

        let row = app.descendants(matching: .any)["incognito-toggle-wrapper"]
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        tapToggle("incognito-toggle-wrapper", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["incognito-info-page"].waitForExistence(timeout: 5))

        let activate = app.buttons["incognito-activate-button"].firstMatch
        scrollToHittable(activate, in: app)
        activate.tap()

        XCTAssertTrue(app.descendants(matching: .any)["incognito-mode-banner"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.descendants(matching: .any)["settings-menu"].exists)

        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 5))
        tapToggle("incognito-toggle-wrapper", in: app)
        tapToggle("incognito-toggle-wrapper", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["incognito-info-page"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["incognito-mode-banner"].waitForExistence(timeout: 8))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell,settings-ui.composition.canonical-and-accessible,settings-ui.shell.lifecycle-and-routing
    func testRootQuickActionsAreSingleLineOrderedAndLabelsInvokeTheirActions() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-authenticated-chat-navigation", "--ui-test-account-settings-fixture", "--ui-test-reset-incognito-explainer", "--ui-test-teams-home-roster-fixture"])
        let teams = app.buttons["team-quick-open"].firstMatch
        let incognito = app.buttons["incognito-toggle-wrapper-action"].firstMatch
        let learning = app.buttons["learning-mode-toggle-wrapper-action"].firstMatch
        XCTAssertTrue(teams.waitForExistence(timeout: 5)); XCTAssertTrue(teams.isHittable)
        XCTAssertTrue(incognito.exists && incognito.isHittable)
        XCTAssertTrue(learning.exists && learning.isHittable)
        XCTAssertLessThan(teams.frame.midY, incognito.frame.midY)
        XCTAssertLessThan(incognito.frame.midY, learning.frame.midY)
        XCTAssertTrue(app.buttons["team-quick-context-dropdown"].firstMatch.exists)
        XCTAssertTrue(app.switches["team-quick-toggle"].firstMatch.exists)
        XCTAssertEqual(incognito.label, "Incognito", "Quick action must expose its single title without a status subtitle")
        XCTAssertEqual(learning.label, "Learning", "Quick action must expose its single title without a status subtitle")
        XCTAssertLessThanOrEqual(app.buttons["incognito-toggle-wrapper-action"].firstMatch.staticTexts.count, 1)
        XCTAssertLessThanOrEqual(app.buttons["learning-mode-toggle-wrapper-action"].firstMatch.staticTexts.count, 1)
        learning.tap()
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-settings-page"].waitForExistence(timeout: 5))
        app.buttons["settings-destination-back"].firstMatch.tap()
        XCTAssertTrue(app.buttons["incognito-toggle-wrapper-action"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["incognito-toggle-wrapper-action"].firstMatch.tap()
        // The workspace wrapper owns the rendered ScrollView's AX identifier.
        // Its real Incognito controls identify this specific explainer surface.
        let explainers = app.scrollViews.containing(.button, identifier: "incognito-activate-button")
        let explainer = explainers.firstMatch
        XCTAssertTrue(explainer.waitForExistence(timeout: 5))
        XCTAssertEqual(explainers.count, 1, "Incognito label must open one real explainer ScrollView")
        XCTAssertTrue(explainer.frame.intersects(app.windows.firstMatch.frame))
        XCTAssertTrue(explainer.staticTexts["Incognito"].firstMatch.isHittable,
                      "The actual explainer title must be visible inside its ScrollView")
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Root quick-action label invokes Incognito explainer"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,settings-ui.parity.web-apple-shell,settings-ui.navigation.parent-return
    func testKnownEmptyHomeRosterOffersCreateWithoutSelectorOrToggle() {
        let app = launchTeamsHome(variant: "zero")
        let create = app.buttons["team-quick-create"].firstMatch
        XCTAssertTrue(create.waitForExistence(timeout: 5))
        XCTAssertTrue(create.isEnabled && create.isHittable)
        XCTAssertEqual(create.frame.width, 70, accuracy: 2)
        XCTAssertEqual(create.frame.height, 42, accuracy: 2)
        XCTAssertFalse(app.buttons["team-quick-context-dropdown"].exists)
        XCTAssertFalse(app.switches["team-quick-toggle"].exists)
        attachTeamsHomeScreenshot("Teams home known-empty orange Create", app)
        create.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-team-name"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,teams.membership.role-gated,settings-ui.parity.web-apple-shell
    func testUnknownAndLoadingHomeRosterNeverAdvertiseZeroMembership() {
        for variant in ["unknown", "loading", "refreshing"] {
            let app = launchTeamsHome(variant: variant)
            XCTAssertTrue(app.buttons["team-quick-open"].firstMatch.isHittable)
            XCTAssertFalse(app.buttons["team-quick-context-dropdown"].exists)
            XCTAssertFalse(app.switches["team-quick-toggle"].exists)
            let create = app.buttons["team-quick-create"].firstMatch
            if variant == "refreshing" {
                XCTAssertTrue(create.exists)
                XCTAssertFalse(create.isEnabled, "A known-empty roster refresh retains its disabled CTA")
            } else {
                XCTAssertFalse(create.exists, "Unresolved membership cannot prove that the account has no teams")
            }
            attachTeamsHomeScreenshot("Teams home " + variant + " membership", app)
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,settings-ui.parity.web-apple-shell,settings-ui.composition.canonical-and-accessible
    func testJoinedAndOfflineHomeMenusFitTheirContentAndCloseThroughTrigger() {
        for variant in ["joined", "offline"] {
            let app = launchTeamsHome(variant: variant)
            let trigger = app.buttons["team-quick-context-dropdown"].firstMatch
            XCTAssertTrue(trigger.waitForExistence(timeout: 5))
            XCTAssertTrue(trigger.isEnabled && trigger.isHittable)
            XCTAssertFalse(app.buttons["team-quick-create"].exists)
            XCTAssertTrue(app.switches["team-quick-toggle"].firstMatch.isHittable)
            trigger.tap()
            let menu = app.descendants(matching: .any)["team-context-menu"].firstMatch
            XCTAssertTrue(menu.waitForExistence(timeout: 5))
            XCTAssertFalse(app.buttons["team-context-personal"].exists)
            XCTAssertFalse(app.descendants(matching: .any)["profile-team-context-switcher"].exists)
            let newTeam = app.buttons["team-context-new-team"].firstMatch
            XCTAssertTrue(newTeam.isHittable)
            XCTAssertTrue(app.buttons["team-context-option-synthetic-home-one"].firstMatch.isHittable)
            XCTAssertTrue(app.buttons["team-context-option-synthetic-home-two"].firstMatch.isHittable)
            // Query after opening animation by waiting for stable expected bounds.
            let settled = NSPredicate { _, _ in abs(menu.frame.height - 157) < 2 && abs(menu.frame.width - 185) < 2 }
            expectation(for: settled, evaluatedWith: menu)
            waitForExpectations(timeout: 5)
            XCTAssertEqual(menu.frame.height, 157, accuracy: 2)
            XCTAssertGreaterThanOrEqual(newTeam.frame.minY, app.buttons["team-context-option-synthetic-home-two"].frame.maxY)
            XCTAssertLessThanOrEqual(menu.frame.maxY - newTeam.frame.maxY, 20,
                "Content must end at the web bottom padding without a blank region")
            attachTeamsHomeScreenshot("Teams home " + variant + " fitted menu", app)
            trigger.tap()
            XCTAssertTrue(menu.waitForNonExistence(timeout: 5))
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,settings-ui.parity.web-apple-shell
    func testPersonalQuickActionRemembersTeamChoiceUntilToggleAndNeverAddsPersonalOption() {
        let app = launchTeamsHome(variant: "personal")
        XCTAssertFalse(app.descendants(matching: .any)["profile-team-context-switcher"].exists)
        let trigger = app.buttons["team-quick-context-dropdown"].firstMatch
        let toggle = app.switches["team-quick-toggle"].firstMatch
        XCTAssertTrue(trigger.isHittable && toggle.isHittable)
        XCTAssertEqual(trigger.value as? String, "xHain")
        XCTAssertEqual(toggle.value as? String, "Off")
        trigger.tap()
        XCTAssertFalse(app.buttons["team-context-personal"].exists)
        app.buttons["team-context-option-synthetic-home-two"].tap()
        XCTAssertEqual(trigger.value as? String, "OpenMates")
        XCTAssertEqual(toggle.value as? String, "Off", "Picker selection must leave Personal active")
        toggle.tap()
        let on = NSPredicate(format: "value == 'On'")
        expectation(for: on, evaluatedWith: toggle); waitForExpectations(timeout: 5)
        toggle.tap()
        let off = NSPredicate(format: "value == 'Off'")
        expectation(for: off, evaluatedWith: toggle); waitForExpectations(timeout: 5)
        XCTAssertEqual(trigger.value as? String, "OpenMates")
        toggle.tap()
        expectation(for: on, evaluatedWith: toggle); waitForExpectations(timeout: 5)
        trigger.tap()
        app.buttons["team-context-option-synthetic-home-one"].tap()
        XCTAssertEqual(trigger.value as? String, "xHain")
        XCTAssertEqual(toggle.value as? String, "On")
        attachTeamsHomeScreenshot("Personal picker remembers team and toggle activates it", app)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,settings-ui.parity.web-apple-shell
    func testSingleTeamMenuIsTeamsOnlyAndLoadingJoinedDisablesSelection() {
        let app = launchTeamsHome(variant: "single")
        let trigger = app.buttons["team-quick-context-dropdown"].firstMatch
        XCTAssertEqual(trigger.value as? String, "SocialHub")
        trigger.tap()
        let menu = app.descendants(matching: .any)["team-context-menu"].firstMatch
        let settled = NSPredicate { _, _ in abs(menu.frame.height - 106) < 2 }
        expectation(for: settled, evaluatedWith: menu); waitForExpectations(timeout: 5)
        XCTAssertFalse(app.buttons["team-context-personal"].exists)
        XCTAssertTrue(app.buttons["team-context-option-synthetic-home-one"].isHittable)
        XCTAssertTrue(app.buttons["team-context-new-team"].isHittable)
        attachTeamsHomeScreenshot("SocialHub only team menu", app)
        trigger.tap()
        app.switches["team-quick-toggle"].tap()
        XCTAssertEqual(app.switches["team-quick-toggle"].value as? String, "1")
        app.terminate()
        let loading = launchTeamsHome(variant: "loadingJoined")
        XCTAssertFalse(loading.buttons["team-quick-context-dropdown"].isEnabled)
        XCTAssertFalse(loading.switches["team-quick-toggle"].isEnabled)
        XCTAssertFalse(loading.buttons["team-quick-create"].exists)
        attachTeamsHomeScreenshot("Loading joined roster keeps disabled team controls", loading)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testManyTeamMenuShowsFiveChoicesThenExpandsAndRemainsScrollable() {
        let app = launchTeamsHome(variant: "many")
        app.buttons["team-quick-context-dropdown"].tap()
        XCTAssertFalse(app.buttons["team-context-option-synthetic-home-6"].exists)
        let more = app.buttons["team-context-show-more"].firstMatch
        XCTAssertTrue(more.isHittable); more.tap()
        XCTAssertFalse(more.exists)
        let menu = app.scrollViews["team-context-menu"].firstMatch
        let last = app.buttons["team-context-option-synthetic-home-7"].firstMatch
        for _ in 0..<3 where !last.isHittable { menu.swipeUp() }
        XCTAssertTrue(last.isHittable)
        XCTAssertFalse(app.buttons["team-context-personal"].exists)
        attachTeamsHomeScreenshot("Expanded recent team menu remains bounded", app)
    }

    private func launchTeamsHome(variant: String) -> XCUIApplication {
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-authenticated-chat-navigation",
            "--ui-test-account-settings-fixture", "--ui-test-teams-settings-fixture", "--ui-test-teams-home-roster-fixture"]
        app.launchEnvironment["UI_TEST_TEAMS_HOME_ROSTER"] = variant
        app.launch()
        let settings = app.buttons["settings-button"].firstMatch
        XCTAssertTrue(settings.waitForExistence(timeout: 15)); settings.tap()
        XCTAssertTrue(RealAccountUITestSupport.waitForVisibleSettingsHome(in: app),
                      "The opened settings pane and home ScrollView must be enabled and visible")
        return app
    }

    private func attachTeamsHomeScreenshot(_ name: String, _ app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }

    private func launchSettingsFixture(extraArguments: [String] = []) -> XCUIApplication {
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"] + extraArguments
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.otherElements["workspace-settings"].firstMatch.exists,
                      "Workspace identity must belong to its containing group, preserving destination and control identities")
        return app
    }

    private func tapToggle(_ identifier: String, in app: XCUIApplication) {
        let toggle = app.switches.matching(identifier: identifier).firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        XCTAssertTrue(toggle.isHittable)
        toggle.tap()
    }

    private func scrollToHittable(_ element: XCUIElement, in app: XCUIApplication) {
        let identifiedScrollView = app.scrollViews["incognito-info-page"].firstMatch
        for _ in 0..<6 where !element.isHittable {
            if identifiedScrollView.exists {
                identifiedScrollView.swipeUp()
            } else if app.scrollViews.count > 0 {
                app.scrollViews.element(boundBy: app.scrollViews.count - 1).swipeUp()
            }
        }
        XCTAssertTrue(element.exists)
        XCTAssertTrue(element.isHittable)
    }
}
