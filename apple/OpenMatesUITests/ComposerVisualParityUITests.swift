// Visual contract smoke coverage for the shared Apple message composer.
// Uses deterministic dev-preview surfaces to assert shared identifiers and the
// web 629pt max-width contract without credentials, network calls, private chat
// records, or system picker automation.
// Screenshots are attached as review artifacts; assertions stay deterministic.

import XCTest
import UIKit

@MainActor
final class ComposerVisualParityUITests: XCTestCase {
    private let maxComposerWidth: CGFloat = 629
    private let widthTolerance: CGFloat = 8
    private let welcomeComposerButtonIds = [
        "composer-attachment-toggle",
        "record-audio-button",
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testActiveFocusPillHasHumanLabelAndOperableSettingsAndUndoToggle() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "focus", "--dev-preview-width", "390"]
        app.launch()
        let label = app.staticTexts["focus-pill-label"]
        XCTAssertTrue(label.waitForExistence(timeout: 12))
        XCTAssertEqual(label.label, "Clarify workflows")
        let open = app.buttons["focus-pill-body"]
        // OMToggle exposes the native Switch role in the accessibility tree.
        let toggle = app.switches["focus-pill-toggle"]
        XCTAssertTrue(open.waitForExistence(timeout: 5), "Missing production focus settings button: \(app.debugDescription)")
        XCTAssertTrue(toggle.waitForExistence(timeout: 5), "Missing production focus toggle: \(app.debugDescription)")
        XCTAssertTrue(open.isHittable)
        XCTAssertTrue(toggle.isHittable)
        attachScreenshot(name: "Active focus indicator parity")
        open.tap()
        let action = app.descendants(matching: .any)["dev-preview-local-action"].firstMatch
        expectation(for: NSPredicate(format: "label == %@", "focus-settings-opened"), evaluatedWith: action)
        waitForExpectations(timeout: 3)
        toggle.tap()
        toggle.tap()
        let disappears = expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: label)
        disappears.isInverted = true
        wait(for: [disappears], timeout: 1.2)
        toggle.tap()
        expectation(for: NSPredicate(format: "label == %@", "focus-deactivated"), evaluatedWith: action)
        waitForExpectations(timeout: 4)
        XCTAssertFalse(label.exists)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testUserCanonicalMentionsRenderHumanLabelsAndPreserveSurroundingText() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", "mentions", "--dev-preview-width", "390"]
        app.launch()
        XCTAssertTrue(app.staticTexts["@Workflows-Clarify-Workflows"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.staticTexts["@Web-Search"].exists)
        XCTAssertTrue(app.staticTexts["@sophia"].exists)
        XCTAssertTrue(app.staticTexts["@Best"].exists)
        XCTAssertFalse(app.staticTexts["@focus:workflows:clarify_workflows"].exists)
        attachScreenshot(name: "User canonical mention gradient labels")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity
    func testChatPreviewComposerUsesSharedIdentifiersAndWidthCap() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }

        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        let editor = waitForMessageEditor(in: app)

        XCTAssertLessThanOrEqual(editor.frame.width, maxComposerWidth + widthTolerance)

        let latest = app.textViews.matching(NSPredicate(format: "value CONTAINS %@",
            "Latest assistant response visible after bounded open")).firstMatch
        XCTAssertTrue(latest.waitForExistence(timeout: 12), "Wait for actual chat load/reset before focusing")
        let currentEditor = try NativeUITestElementResolution.requireVisible(
            app.textViews.matching(identifier: "message-editor"), in: app)
        currentEditor.tap()
        let focusedAfterSingleTap = app.buttons["chat-composer-cancel"].waitForExistence(timeout: 5)
        if !focusedAfterSingleTap {
            let field = element(in: app, identifier: "message-field")
            let diagnostic = XCTAttachment(string: String(describing: field.value))
            diagnostic.name = "Single native editor tap geometry"
            diagnostic.lifetime = .keepAlways
            add(diagnostic)
        }
        XCTAssertTrue(focusedAfterSingleTap,
            "One real native-editor tap must focus the production composer")
        // Prove the same compact host can be dismissed and focused again by
        // exactly one native editor tap; no coordinate or shell-tap fallback.
        app.buttons["chat-composer-cancel"].tap()
        XCTAssertTrue(waitForAbsence(app.buttons["chat-composer-cancel"]),
            "Cancel must return the production chat composer to its compact state")
        let reopenedEditor = try NativeUITestElementResolution.requireVisible(
            app.textViews.matching(identifier: "message-editor"), in: app)
        reopenedEditor.tap()
        XCTAssertTrue(app.buttons["chat-composer-cancel"].waitForExistence(timeout: 5),
            "One real native-editor tap must refocus the retained production composer")
        let field = element(in: app, identifier: "message-field")
        let fullscreenButton = app.buttons["message-input-fullscreen-button"]
        XCTAssertFalse(fullscreenButton.exists, "Empty focused text has no expand action")
        currentEditor.typeText("First line")
        XCTAssertFalse(fullscreenButton.exists, "Short text has no expand action")
        currentEditor.typeText("\nSecond line\nThird line")
        XCTAssertFalse(fullscreenButton.exists, "Three visible lines do not need fullscreen")
        currentEditor.typeText("\nFourth line\nFifth line")
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertTrue(
            fullscreenButton.waitForExistence(timeout: 5),
            "Expected the focused production composer to expose fullscreen. Visible UI: \(app.debugDescription)"
        )
        // The focused row animates out of the compact bottom bar. An existing
        // expand element can still occupy its old presentation position mid-flight.
        XCTAssertTrue(waitForFocusedChatComposer(app: app),
            "Expected settled focused field/editor/control geometry before a real expand tap")
        assertExpandControlBesideNativeText(fullscreenButton, editor: editor)
        let collapsedPortraitHeight = field.frame.height
        let focusedEditorHeight = editor.frame.height
        let focusedLabel = fullscreenButton.label

        app.buttons["message-input-fullscreen-button"].tap()
        let expanded = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.buttons["message-input-fullscreen-button"].label != focusedLabel
        }, object: app)
        let expansionResult = XCTWaiter.wait(for: [expanded], timeout: 5)
        if expansionResult != .completed {
            attachScreenshot(name: "Chat real expand action did not change presentation")
            let dump = XCTAttachment(string: app.debugDescription); dump.lifetime = .keepAlways; add(dump)
        }
        XCTAssertEqual(expansionResult, .completed, "The real expand tap must enter fullscreen")
        XCTAssertTrue(waitForHeight(field, atLeast: collapsedPortraitHeight + 80))
        XCTAssertTrue(waitForHeight(editor, atLeast: focusedEditorHeight + 80),
            "Portrait fullscreen must grow the actual native editable viewport")
        assertExpandControlBesideNativeText(fullscreenButton, editor: editor)
        let cancel = app.buttons["chat-composer-cancel"]
        XCTAssertTrue(cancel.isHittable)
        assertDismissWidth(cancel, field: field)
        XCTAssertGreaterThanOrEqual(cancel.frame.minY, field.frame.maxY)
        XCTAssertLessThanOrEqual(cancel.frame.maxY, app.windows.firstMatch.frame.maxY)
        XCTAssertGreaterThan(field.frame.minY, app.windows.firstMatch.frame.minY + 20,
            "Fullscreen must leave a real outside dismissal gutter")

        XCUIDevice.shared.orientation = .landscapeLeft
        let rotated = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.windows.firstMatch.frame.width > app.windows.firstMatch.frame.height
        }, object: app.windows.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [rotated], timeout: 5), .completed)
        XCTAssertTrue(fullscreenButton.waitForExistence(timeout: 5))
        let window = app.windows.firstMatch.frame
        XCTAssertGreaterThanOrEqual(field.frame.minY, window.minY)
        XCTAssertLessThanOrEqual(field.frame.maxY, window.maxY)
        assertExpandControlBesideNativeText(fullscreenButton, editor: editor)
        let expandedLandscapeHeight = field.frame.height
        let expandedLandscapeEditorHeight = editor.frame.height
        let expandedLabel = fullscreenButton.label
        fullscreenButton.tap()
        expectation(for: NSPredicate { _, _ in fullscreenButton.label != expandedLabel
            && editor.frame.height < expandedLandscapeEditorHeight }, evaluatedWith: fullscreenButton)
        waitForExpectations(timeout: 3)
        XCTAssertLessThan(field.frame.height, expandedLandscapeHeight)
        XCTAssertLessThan(editor.frame.height, expandedLandscapeEditorHeight)
        if expandedLandscapeHeight > collapsedPortraitHeight + 80 {
            XCTAssertLessThan(field.frame.height, expandedLandscapeHeight - 80)
        }
        editor.tap()
        editor.typeText("Synthetic microphone placement")
        let typedMic = app.buttons["record-audio-button"]
        let typedSend = app.buttons["send-button"]
        XCTAssertTrue(typedMic.isHittable); XCTAssertTrue(typedSend.exists)
        XCTAssertLessThan(typedSend.frame.midX, typedMic.frame.midX)
        XCTAssertGreaterThan(typedMic.frame.midY, field.frame.midY)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product composer UI must not render default List/table chrome")

        attachScreenshot(name: "Shared composer chat preview width cap")
        let typed = editor.value as? String ?? ""
        editor.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: typed.count))
        XCTAssertTrue(waitForAbsence(fullscreenButton), "Cleared text removes expand without dismissing focus")
        XCTAssertTrue(app.buttons["chat-composer-cancel"].exists)
        XCTAssertEqual(editor.value as? String, "")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.actions.visibility,message-input.layout.responsive-parity
    func testFocusedWelcomeComposerScreenshotShowsActionButtons() throws {
        let app = launchFocusedWelcomeComposer()

        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))
        let screenshot = XCUIScreen.main.screenshot()
        for identifier in welcomeComposerButtonIds {
            assertButtonIsVisibleInScreenshot(app.buttons[identifier], identifier: identifier, in: app, screenshot: screenshot)
        }
        attachScreenshot(screenshot, name: "Focused welcome composer action buttons visible")

        app.buttons["composer-attachment-toggle"].tap()
        let menu = element(in: app, identifier: "composer-attachment-menu")
        XCTAssertTrue(menu.waitForExistence(timeout: 5))
        for identifier in ["composer-attachment-drawing", "composer-attachment-location", "composer-attachment-camera", "composer-attachment-files"] {
            let action = app.buttons[identifier]
            XCTAssertTrue(action.waitForExistence(timeout: 5), "Missing attachment menu action: \(identifier)")
            XCTAssertTrue(action.isHittable, "Attachment menu action is obscured: \(identifier)")
            assertButtonIsVisibleInScreenshot(
                action,
                identifier: identifier,
                in: app,
                screenshot: screenshot,
                leadingIconOnly: true
            )
        }
        attachScreenshot(name: "Focused welcome composer attachment menu open")

        let outsideMenu = app.windows.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.2))
        outsideMenu.tap()
        XCTAssertFalse(app.buttons["composer-attachment-drawing"].exists, "Outside tap should dismiss the attachment menu")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity
    func testCollapsedComposerGrowsThroughThreeLinesThenScrollsAboveActions() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-welcome-seed-suggestions"]
        )
        let editor = waitForMessageEditor(in: app)
        let field = element(in: app, identifier: "message-field")
        let suggestions = element(in: app, identifier: "new-chat-suggestions")
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertTrue(suggestions.waitForExistence(timeout: 5))
        let initialHeight = field.frame.height

        editor.typeText("First line")
        XCTAssertTrue(
            waitForSuggestions(suggestions, above: field),
            "Welcome suggestions must settle above the active composer"
        )
        let oneLineSuggestionsMaxY = suggestions.frame.maxY
        XCTAssertLessThanOrEqual(
            oneLineSuggestionsMaxY,
            field.frame.minY,
            "Welcome suggestions must remain above the active composer"
        )

        editor.typeText("\nSecond line\nThird line")
        XCTAssertTrue(
            waitForSuggestions(
                suggestions,
                above: field,
                maxYLessThan: oneLineSuggestionsMaxY - 20
            ),
            "Welcome suggestions must follow the growing composer upward"
        )

        let threeLineHeight = field.frame.height
        XCTAssertGreaterThan(
            threeLineHeight,
            initialHeight + 20,
            "The collapsed composer should expand upward to reveal three recent lines"
        )
        XCTAssertLessThan(
            suggestions.frame.maxY,
            oneLineSuggestionsMaxY - 20,
            "Welcome suggestions should move upward as the multiline composer grows"
        )
        XCTAssertLessThanOrEqual(
            suggestions.frame.maxY,
            field.frame.minY,
            "Three visible lines must not overlap the welcome suggestions"
        )
        let sendButton = app.buttons["send-button"]
        XCTAssertTrue(sendButton.waitForExistence(timeout: 5))
        let mic = app.buttons["record-audio-button"]
        XCTAssertTrue(mic.exists)
        XCTAssertLessThan(sendButton.frame.midX, mic.frame.midX,
            "Typed Welcome microphone must stay to the right of Send")
        XCTAssertFalse(app.buttons["message-input-fullscreen-button"].exists,
            "The expand icon stays absent through the full three-line boundary")
        XCTAssertLessThanOrEqual(
            editor.frame.maxY,
            sendButton.frame.minY + 2,
            "Multiline text must remain above the bottom action controls"
        )

        editor.typeText("\nFourth line\nFifth line")
        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))
        assertExpandControlBesideNativeText(app.buttons["message-input-fullscreen-button"], editor: editor)
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(
            app.buttons["message-input-fullscreen-button"], field: field, editor: editor)

        XCTAssertEqual(
            field.frame.height,
            threeLineHeight,
            accuracy: 4,
            "After three visible lines, the editor should scroll instead of growing over the controls"
        )
        XCTAssertLessThanOrEqual(
            suggestions.frame.maxY,
            field.frame.minY,
            "Scrollable fourth and fifth lines must keep suggestions above the composer"
        )
        XCTAssertTrue(
            (editor.value as? String)?.contains("Fifth line") == true,
            "The newest line should remain in the scrollable editor value"
        )
        attachScreenshot(name: "Collapsed composer three-line scrolling cap")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testFocusedWelcomeComposerActionButtonsAreNotNoOpsWhenSignedOut() throws {
        assertSignedOutWelcomeActionShowsSignupCTA("composer-attachment-files")
        assertSignedOutWelcomeActionShowsSignupCTA("composer-attachment-drawing")
        assertSignedOutWelcomeActionShowsSignupCTA("composer-attachment-camera")

        let locationApp = launchFocusedWelcomeComposer()
        locationApp.buttons["composer-attachment-toggle"].tap()
        let locationButton = locationApp.buttons["composer-attachment-location"]
        XCTAssertTrue(locationButton.waitForExistence(timeout: 5), "Expected location action to exist")
        XCTAssertTrue(locationButton.isHittable, "Expected location action to be hittable")
        locationButton.tap()
        XCTAssertTrue(
            locationApp.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier == %@", "location-overlay"))
                .firstMatch
                .waitForExistence(timeout: 5),
            "Expected location action to open the location composer overlay"
        )
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testFocusedWelcomeLocationSelectionInsertsMapsEmbedPreview() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-location-preselected"],
            environment: ["UI_TEST_LOCATION_PRESELECTED": "1"]
        )
        app.buttons["composer-attachment-toggle"].tap()
        let locationButton = app.buttons["composer-attachment-location"]
        XCTAssertTrue(locationButton.waitForExistence(timeout: 5))
        locationButton.tap()

        XCTAssertTrue(app.buttons["send-button"].waitForExistence(timeout: 5))
        let editor = waitForMessageEditor(in: app)
        XCTAssertTrue(
            element(in: app, identifier: "native-composer-preview-maps-finished").waitForExistence(timeout: 5),
            "Expected selected location to insert a maps embed preview; value=\(String(describing: editor.value))"
        )
        XCTAssertFalse(
            (editor.value as? String)?.localizedCaseInsensitiveContains("Selected location (") == true,
            "Location selection must not append plain coordinate text"
        )
    }

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity,message-input.embeds.gated-send
    func testSeededImageAndAudioPreviewsStayLeftAlignedAcrossRotation() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launchFocusedWelcomeComposer(extraArguments: ["--ui-test-welcome-seed-pending-content"])
        let editor = app.textViews["message-editor"]
        let field = element(in: app, identifier: "message-field")
        let expand = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "message-input-fullscreen-button"), in: app)
        XCTAssertTrue(expand.isHittable)
        let compactLabel = expand.label
        expand.tap()
        expectation(for: NSPredicate { _, _ in expand.label != compactLabel }, evaluatedWith: expand)
        waitForExpectations(timeout: 3)
        func assertCard(_ type: String, _ orientation: String) throws {
            let card = try revealComposerCard(type: type, app: app, editor: editor)
            let info = card.descendants(matching: .any)["native-composer-\(type == "image" ? "image" : "audio")-info-bar"].firstMatch
            assertEmbed(card, isLeftAlignedIn: field)
            XCTAssertEqual(card.frame.width, 300, accuracy: 3)
            XCTAssertEqual(card.frame.height, 200, accuracy: 3)
            XCTAssertEqual(info.frame.height, 61, accuracy: 3)
            XCTAssertEqual(info.frame.maxY, card.frame.maxY, accuracy: 3)
            XCTAssertTrue(editor.frame.insetBy(dx: -3, dy: -3).contains(info.frame),
                "Each real fixed footer must be wholly visible after native editor scrolling")
            if type == "recording" {
                XCTAssertTrue((field.value as? String)?.hasPrefix("native-top-fade=active;") == true,
                    "The actual scrolled native editor must enable its transparent top mask")
            }
            if type == "image" && orientation == "landscape" {
                XCTAssertTrue((field.value as? String)?.hasPrefix("native-top-fade=active;") == true)
                assertActualScrolledImageFade(editor: editor, card: card)
            }
            let visibleCard = card.frame.intersection(editor.frame)
            XCTAssertGreaterThan(visibleCard.height, 0)
            XCTAssertFalse(visibleCard.intersects(expand.frame.insetBy(dx: -4, dy: -4)),
                "Actual media may share a wide row but never intersect the expand hit target")
            XCTAssertLessThanOrEqual(info.frame.maxY, element(in: app, identifier: "action-buttons").frame.minY + 3)
            attachScreenshot(editor.screenshot(), name: "Actual \(orientation) \(type) native scroll fade viewport")
            if type == "image" {
                let pixels = card.descendants(matching: .any)["native-composer-image-content"].firstMatch
                XCTAssertTrue(pixels.exists)
                XCTAssertLessThanOrEqual(pixels.frame.minX, card.frame.minX + 3)
                XCTAssertLessThanOrEqual(pixels.frame.minY, card.frame.minY + 3)
                XCTAssertGreaterThanOrEqual(pixels.frame.maxX, card.frame.maxX - 3)
                XCTAssertGreaterThanOrEqual(pixels.frame.maxY, card.frame.maxY - 3)
                XCTAssertEqual(info.frame.width, card.frame.width, accuracy: 3)
                XCTAssertEqual(info.frame.minX, card.frame.minX, accuracy: 3)
                XCTAssertFalse(card.buttons["native-composer-preview-action-close"].exists)
                XCTAssertFalse(card.buttons["native-composer-preview-action-visible"].exists)
            }
            XCTAssertTrue(app.buttons["composer-attachment-toggle"].isHittable)
            let mic = app.buttons["record-audio-button"]
            let submit = app.buttons["send-button"]
            XCTAssertTrue(mic.isHittable); XCTAssertTrue(submit.isHittable)
            XCTAssertLessThan(submit.frame.midX, mic.frame.midX)
            XCTAssertGreaterThan(mic.frame.midY, field.frame.midY)
            attachScreenshot(name: "\(orientation) native editor scrolled to complete \(type) footer")
        }
        try assertCard("image", "portrait")
        try assertCard("recording", "portrait")
        XCUIDevice.shared.orientation = .landscapeLeft
        let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.windows.firstMatch.frame.width > app.windows.firstMatch.frame.height
        }, object: app.windows.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 5), .completed)
        try assertCard("image", "landscape")
        try assertCard("recording", "landscape")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity
    func testWelcomeComposerExpandsAndCollapsesAcrossRotation() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }

        let app = launchFocusedWelcomeComposer()
        let editor = waitForMessageEditor(in: app)
        let field = element(in: app, identifier: "message-field")
        let button = app.buttons["message-input-fullscreen-button"]
        XCTAssertFalse(button.exists, "Empty Welcome has no expand affordance")
        editor.typeText("First line\nSecond line\nThird line")
        XCTAssertFalse(button.exists, "Boundary three-line text has no expand affordance")
        editor.typeText("\nFourth line\nFifth line")
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertTrue(button.waitForExistence(timeout: 5))
        attachScreenshot(name: "Welcome composer fullscreen button hit testing")
        XCTAssertTrue(
            button.isHittable,
            "Fullscreen button must be hittable. button=\(button.debugDescription) field=\(field.debugDescription) UI=\(app.debugDescription)"
        )

        let collapsedPortraitHeight = field.frame.height
        let focusedEditorHeight = editor.frame.height
        assertExpandControlBesideNativeText(button, editor: editor)
        let expandLabel = button.label
        button.tap()

        XCTAssertNotEqual(button.label, expandLabel)
        assertExpandControlBesideNativeText(button, editor: editor)
        XCTAssertTrue(waitForHeight(field, atLeast: collapsedPortraitHeight + 80))
        XCTAssertTrue(waitForHeight(editor, atLeast: focusedEditorHeight + 80))

        button.tap()
        XCTAssertEqual(button.label, expandLabel)
        XCTAssertLessThanOrEqual(field.frame.height, collapsedPortraitHeight + 8)

        button.tap()
        XCUIDevice.shared.orientation = .landscapeLeft
        let rotated = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.windows.firstMatch.frame.width > app.windows.firstMatch.frame.height
        }, object: app.windows.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [rotated], timeout: 5), .completed)
        XCTAssertTrue(button.waitForExistence(timeout: 5))
        XCTAssertTrue(button.isHittable)
        let window = app.windows.firstMatch.frame
        XCTAssertGreaterThanOrEqual(field.frame.minY, window.minY)
        XCTAssertLessThanOrEqual(field.frame.maxY, window.maxY)
        assertExpandControlBesideNativeText(button, editor: editor)
        let viewportReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard let payload = NativeComposerRenderedLayoutAssertions.payload(field),
                  let bounds = NativeComposerRenderedLayoutAssertions.localRect("bounds", in: payload) else { return false }
            return bounds.height > 0
        }, object: field)
        XCTAssertEqual(XCTWaiter.wait(for: [viewportReady], timeout: 3), .completed,
            "Actual TextKit viewport must survive landscape rotation")
        XCTAssertTrue(app.keyboards.firstMatch.exists, "Rotation must preserve the software keyboard")
        let header = element(in: app, identifier: "main-app-web-header")
        if UIDevice.current.userInterfaceIdiom == .phone {
            // Retained generic AX groups may report hittable while transparent.
            // Hidden production buttons must be absent or explicitly disabled.
            for control in header.buttons.allElementsBoundByIndex {
                XCTAssertFalse(control.isEnabled, "Hidden header control remains enabled: \(control.identifier)")
            }
            attachScreenshot(name: "Welcome landscape header hidden while keyboard and native editor remain active")
        }
        let expandedLandscapeHeight = field.frame.height
        let expandedLandscapeEditorHeight = editor.frame.height
        button.tap()
        expectation(for: NSPredicate { _, _ in button.label == expandLabel
            && editor.frame.height < expandedLandscapeEditorHeight }, evaluatedWith: button)
        waitForExpectations(timeout: 3)
        XCTAssertEqual(button.label, expandLabel)
        XCTAssertLessThan(field.frame.height, expandedLandscapeHeight)
        XCTAssertLessThan(editor.frame.height, expandedLandscapeEditorHeight)
        if expandedLandscapeHeight > collapsedPortraitHeight + 80 {
            XCTAssertLessThan(field.frame.height, expandedLandscapeHeight - 80)
        }
        XCTAssertGreaterThan(editor.frame.height, 0)
        XCTAssertLessThanOrEqual(field.frame.maxY, app.windows.firstMatch.frame.maxY)
        let cancel = app.buttons["new-chat-draft-dismiss-button"]
        XCTAssertTrue(cancel.isHittable)
        assertDismissWidth(cancel, field: field)
        XCTAssertLessThanOrEqual(cancel.frame.maxY, app.keyboards.firstMatch.frame.minY + 2,
            "Full-width Save remains above the software keyboard")
        editor.typeText("\nSixth line after rotation")
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(button, field: field, editor: editor)
        XCTAssertTrue((editor.value as? String)?.contains("Fifth line\nSixth line after rotation") == true,
            "The retained editor keeps the draft and insertion point")
        attachScreenshot(name: "Welcome landscape positive native viewport and selected caret")
        cancel.tap()
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            header.exists && header.frame.height > 0 && !app.keyboards.firstMatch.exists
        }, object: header)
        XCTAssertEqual(XCTWaiter.wait(for: [restored], timeout: 5), .completed,
            "Dismissal restores the existing header and closes the keyboard")
        attachScreenshot(name: "Welcome landscape header restored after Save")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,message-input.layout.responsive-parity
    func testSketchToolExposesWebControlsInLandscape() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-welcome-sketch-enabled"]
        )
        defer { XCUIDevice.shared.orientation = .portrait }
        app.buttons["composer-attachment-toggle"].tap()
        let sketchButton = app.buttons["composer-attachment-drawing"]
        XCTAssertTrue(sketchButton.waitForExistence(timeout: 5))
        XCTAssertTrue(
            sketchButton.isHittable,
            "Sketch button must be hittable before opening the tool. button=\(sketchButton.debugDescription) UI=\(app.debugDescription)"
        )
        sketchButton.tap()

        let canvas = element(in: app, identifier: "sketch-canvas")
        XCTAssertTrue(canvas.waitForExistence(timeout: 5), "Sketch canvas must render after the action. UI=\(app.debugDescription)")
        XCUIDevice.shared.orientation = .landscapeLeft
        attachScreenshot(name: "Landscape sketch overlay after action")
        XCTAssertTrue(
            canvas.waitForExistence(timeout: 5),
            "Sketch canvas must survive rotation. UI=\(app.debugDescription)"
        )
        for identifier in ["sketch-eraser-button", "sketch-fullscreen-button"] {
            let control = app.buttons[identifier]
            XCTAssertTrue(control.waitForExistence(timeout: 2), "Missing web-parity drawing control: \(identifier)")
            XCTAssertTrue(control.isHittable, "Drawing control is clipped: \(identifier)")
        }

        let toolbar = app.scrollViews["sketch-toolbar-scroll"]
        let undo = app.buttons["sketch-undo-button"]
        let save = app.buttons["sketch-save-button"]
        XCTAssertTrue(toolbar.waitForExistence(timeout: 2))
        XCTAssertTrue(undo.waitForExistence(timeout: 2))
        XCTAssertTrue(save.waitForExistence(timeout: 2))
        XCTAssertFalse(undo.isEnabled, "Undo must stay disabled until the canvas has a stroke")
        XCTAssertFalse(save.isEnabled, "Save must stay disabled until the canvas has a stroke")

        let strokeStart = canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.35))
        let strokeEnd = canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.65, dy: 0.65))
        strokeStart.press(forDuration: 0.1, thenDragTo: strokeEnd)

        toolbar.swipeLeft()
        for identifier in ["sketch-zoom-in-button", "sketch-clear-button"] {
            let control = app.buttons[identifier]
            XCTAssertTrue(control.waitForExistence(timeout: 2), "Missing web-parity drawing control: \(identifier)")
            XCTAssertTrue(control.isHittable, "Drawing control remains unreachable after scrolling: \(identifier)")
        }
        XCTAssertTrue(waitForEnabled(undo), "Undo must become actionable after drawing")
        XCTAssertTrue(waitForEnabled(save), "Save must become actionable after drawing")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
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

    private func textContaining(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.staticTexts
            .matching(NSPredicate(format: "label CONTAINS[c] %@", text))
            .firstMatch
    }

    private func waitForAbsence(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let predicate = NSPredicate(format: "exists == false")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    private func waitForHeight(
        _ element: XCUIElement,
        atLeast minimumHeight: CGFloat,
        timeout: TimeInterval = 5
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.frame.height >= minimumHeight { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }

    private func waitForSuggestions(
        _ suggestions: XCUIElement,
        above field: XCUIElement,
        maxYLessThan upperBound: CGFloat? = nil,
        timeout: TimeInterval = 5
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let suggestionsMaxY = suggestions.frame.maxY
            if suggestionsMaxY <= field.frame.minY,
               upperBound.map({ suggestionsMaxY < $0 }) ?? true {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }

    private func waitForEnabled(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let predicate = NSPredicate(format: "isEnabled == true")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    private func assertEmbed(
        _ embed: XCUIElement,
        isLeftAlignedIn field: XCUIElement,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertGreaterThan(embed.frame.width, 100, file: file, line: line)
        XCTAssertGreaterThan(embed.frame.height, 100, file: file, line: line)
        XCTAssertEqual(embed.frame.minX, field.frame.minX + 10, accuracy: 12, file: file, line: line)
        XCTAssertTrue(field.frame.intersects(embed.frame), file: file, line: line)
    }

    private func waitForMessageEditor(in app: XCUIApplication) -> XCUIElement {
        let candidates = [
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

    private func launchFocusedWelcomeComposer(
        extraArguments: [String] = [],
        environment: [String: String] = [:]
    ) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"] + extraArguments
        for (key, value) in environment {
            app.launchEnvironment[key] = value
        }
        app.launch()

        let skip = app.buttons["guest-interest-skip"]
        if skip.waitForExistence(timeout: 12) {
            skip.tap()
        }

        let editor = try? NativeUITestElementResolution.requireVisible(
            app.textViews.matching(identifier: "message-editor"), in: app)
        editor?.tap()
        return app
    }

    private func assertActualScrolledImageFade(editor: XCUIElement, card: XCUIElement,
                                                file: StaticString = #filePath, line: UInt = #line) {
        // The seeded one-pixel image is opaque black. Landscape native scrolling
        // clips its body above the viewport while preserving the real footer.
        XCTAssertLessThan(card.frame.minY, editor.frame.minY, file: file, line: line)
        XCTAssertGreaterThan(card.frame.maxY - 61, editor.frame.minY + 24, file: file, line: line)
        guard let image = editor.screenshot().image.cgImage else {
            XCTFail("Expected actual native viewport pixels", file: file, line: line); return
        }
        let scaleX = CGFloat(image.width) / editor.frame.width
        let scaleY = CGFloat(image.height) / editor.frame.height
        let x = (card.frame.midX - editor.frame.minX) * scaleX
        func brightness(y: CGFloat) -> Int? {
            guard let sample = image.cropping(to: CGRect(x: x, y: y * scaleY, width: 1, height: 1)) else { return nil }
            var pixel = [UInt8](repeating: 0, count: 4)
            guard let context = CGContext(data: &pixel, width: 1, height: 1, bitsPerComponent: 8,
                bytesPerRow: 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
            context.draw(sample, in: CGRect(x: 0, y: 0, width: 1, height: 1))
            return Int(pixel[0]) + Int(pixel[1]) + Int(pixel[2])
        }
        guard let top = brightness(y: 1), let opaqueBody = brightness(y: 18) else {
            XCTFail("Expected actual clipped image samples", file: file, line: line); return
        }
        XCTAssertGreaterThan(top, opaqueBody + 30,
            "Transparent top fade must reveal the blue field instead of abruptly clipping the black image", file: file, line: line)
    }

    private func assertDismissWidth(_ dismiss: XCUIElement, field: XCUIElement,
                                    file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(dismiss.frame.width, field.frame.width, accuracy: 1, file: file, line: line)
        XCTAssertEqual(dismiss.frame.minX, field.frame.minX, accuracy: 1, file: file, line: line)
    }

    private func waitForFocusedChatComposer(app: XCUIApplication) -> Bool {
        var previousFrames: [CGRect] = []
        var stableSince: Date?
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            // Re-resolve every snapshot instead of tapping an animation-era element.
            guard let field = NativeUITestElementResolution.visible(
                app.descendants(matching: .any).matching(identifier: "message-field"), in: app, actionable: false),
                  let editor = NativeUITestElementResolution.visible(
                app.descendants(matching: .any).matching(identifier: "message-editor"), in: app, actionable: false),
                  let control = NativeUITestElementResolution.visible(
                app.buttons.matching(identifier: "message-input-fullscreen-button"), in: app, actionable: false),
                  let cancel = NativeUITestElementResolution.visible(
                app.buttons.matching(identifier: "chat-composer-cancel"), in: app, actionable: false) else {
                previousFrames = []; stableSince = nil; return false
            }
            guard field.frame.width > 0, editor.frame.height > 0,
                  control.frame.height > 0, cancel.frame.height > 0,
                  field.frame.insetBy(dx: -2, dy: -2).contains(control.frame),
                  control.frame.minY >= field.frame.minY + 8,
                  NativeComposerRenderedLayoutAssertions.isBeside(control, field: field, editor: editor),
                  field.frame.insetBy(dx: -2, dy: -2).contains(editor.frame),
                  cancel.frame.minY >= field.frame.maxY,
                  app.windows.firstMatch.frame.contains(cancel.frame),
                  control.isHittable, cancel.isHittable else {
                previousFrames = []; stableSince = nil; return false
            }
            // The compact inline New Chat target must have left this row's hit
            // region; a separate top navigation target is outside this band.
            let compactTargets = app.buttons.matching(identifier: "new-chat-button").allElementsBoundByIndex
            guard !compactTargets.contains(where: { target in
                target.exists && target.frame.height > 0
                    && NativeUITestElementResolution.isOnScreen(target, in: app)
                    && target.frame.maxY > field.frame.minY && target.frame.minY < field.frame.maxY
                    && target.isEnabled && target.isHittable
            }) else { previousFrames = []; stableSince = nil; return false }
            let frames = [field.frame, editor.frame, control.frame, cancel.frame]
            if frames != previousFrames {
                previousFrames = frames; stableSince = Date(); return false
            }
            return stableSince.map { Date().timeIntervalSince($0) >= 0.3 } ?? false
        }, object: app)
        let result = XCTWaiter.wait(for: [ready], timeout: 5)
        if result != .completed {
            attachScreenshot(name: "Chat focus geometry did not settle")
            let dump = XCTAttachment(string: app.debugDescription); dump.lifetime = .keepAlways; add(dump)
            let geometry = XCTAttachment(string: String(describing: element(in: app, identifier: "message-field").value))
            geometry.name = "Actual native composer geometry after real typing"
            geometry.lifetime = .keepAlways
            add(geometry)
        }
        return result == .completed
    }

    private func revealComposerCard(type: String, app: XCUIApplication, editor: XCUIElement) throws -> XCUIElement {
        XCTAssertTrue(editor.exists)
        XCTAssertGreaterThanOrEqual(editor.frame.height, 61,
            "The bounded native viewport must fit a complete fixed media footer")
        let identifier = "native-composer-preview-\(type)-finished"
        let infoID = "native-composer-\(type == "image" ? "image" : "audio")-info-bar"
        for _ in 0..<12 {
            // Re-resolve after each real TextKit scroll; offscreen attachment views
            // may be recycled rather than retaining an AX frame.
            let card = editor.descendants(matching: .any)[identifier].firstMatch
            let info = card.descendants(matching: .any)[infoID].firstMatch
            if card.exists, card.frame.height > 100, info.exists, info.frame.height > 0,
               editor.frame.insetBy(dx: -3, dy: -3).contains(info.frame) { return card }
            let hasFooterFrame = info.exists && info.frame.height > 0
            // Offscreen native attachment children can have a zero AX frame.
            // Use the real raw card only to steer; completion still requires
            // the actual visible fixed footer above, never a predicted frame.
            let hasCardFrame = card.exists && card.frame.height > 100
            let targetFooter = hasFooterFrame ? info.frame
                : (hasCardFrame ? CGRect(x: card.frame.minX, y: card.frame.maxY - 61,
                    width: card.frame.width, height: 61) : .zero)
            let hasTarget = hasFooterFrame || hasCardFrame
            let downward = hasTarget ? targetFooter.minY < editor.frame.minY : type == "image"
            let remaining = hasTarget
                ? (downward ? editor.frame.minY - targetFooter.minY : targetFooter.maxY - editor.frame.maxY)
                : editor.frame.height * 0.4
            // A 6pt footer overrun formerly produced a 9.5pt drag in landscape:
            // below the native pan threshold. Cross that threshold with 28pt.
            let distance = min(0.45, max(28 / max(1, editor.frame.height),
                (remaining + 4) / max(1, editor.frame.height)))
            editor.coordinate(withNormalizedOffset: CGVector(dx: 0.85, dy: downward ? 0.25 : 0.75))
                .press(forDuration: 0.05, thenDragTo: editor.coordinate(withNormalizedOffset:
                    CGVector(dx: 0.85, dy: downward ? 0.25 + distance : 0.75 - distance)),
                    withVelocity: .slow, thenHoldForDuration: 0.1)
        }
        attachScreenshot(name: "Missing actual \(type) footer after bounded native editor scroll")
        let dump = XCTAttachment(string: app.debugDescription); dump.lifetime = .keepAlways; add(dump)
        XCTFail("Native scrolling did not reveal full200pt \(type) card/fixed61pt footer")
        return editor.descendants(matching: .any)[identifier].firstMatch
    }

    private func assertExpandControlAboveCard(_ control: XCUIElement, card: XCUIElement,
                                             file: StaticString = #filePath, line: UInt = #line) {
        let separate = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            control.exists && card.exists && control.frame.height > 0 && card.frame.height > 0
                && card.frame.minY >= control.frame.maxY + 4
        }, object: control)
        XCTAssertEqual(XCTWaiter.wait(for: [separate], timeout: 3), .completed,
            "The complete production inline card must start below the expand hit target. control=\(control.frame) card=\(card.frame)", file: file, line: line)
        XCTAssertFalse(control.frame.intersects(card.frame), file: file, line: line)
    }

    private func assertExpandControlBesideNativeText(_ control: XCUIElement, editor: XCUIElement,
                                               file: StaticString = #filePath, line: UInt = #line) {
        let app = XCUIApplication()
        let field = element(in: app, identifier: "message-field")
        NativeComposerRenderedLayoutAssertions.assertBeside(control, field: field, editor: editor,
            file: file, line: line)
    }

    private func assertSignedOutWelcomeActionShowsSignupCTA(
        _ identifier: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let app = launchFocusedWelcomeComposer()
        app.buttons["composer-attachment-toggle"].tap()
        let button = app.buttons[identifier]
        XCTAssertTrue(button.waitForExistence(timeout: 5), "Expected \(identifier) to exist", file: file, line: line)
        XCTAssertTrue(button.isHittable, "Expected \(identifier) to be hittable", file: file, line: line)
        XCTAssertFalse(app.buttons["send-button"].exists, "Signup CTA should not be visible before an action", file: file, line: line)

        button.tap()

        let sendButton = app.buttons["send-button"]
        if !sendButton.waitForExistence(timeout: 2) {
            button.tap()
        }
        XCTAssertTrue(
            sendButton.waitForExistence(timeout: 5),
            "Expected \(identifier) to surface the signup CTA instead of no-oping",
            file: file,
            line: line
        )
    }

    private func assertButtonIsVisibleInScreenshot(
        _ button: XCUIElement,
        identifier: String,
        in app: XCUIApplication,
        screenshot: XCUIScreenshot,
        leadingIconOnly: Bool = false,
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

        let sampleWidth = leadingIconOnly ? min(cgImage.width, Int(54 * image.scale)) : cgImage.width
        let highlightedPixelRatio = highlightedPixelRatio(
            in: CGRect(x: 0, y: 0, width: sampleWidth, height: cgImage.height),
            pixels: pixels,
            imageWidth: cgImage.width,
            imageHeight: cgImage.height,
            scaleX: 1,
            scaleY: 1
        )
        XCTAssertGreaterThan(
            highlightedPixelRatio,
            leadingIconOnly ? 0.01 : 0.02,
            "Expected \(identifier) screenshot region to contain colored icon pixels, ratio \(highlightedPixelRatio)",
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

// Actual retained native TextKit coordinates, rather than an empty SwiftUI box.
// The DEBUG payload contains only rectangles/offset, never message text.
enum NativeComposerRenderedLayoutAssertions {
    // XCTest predicate expectations defer their first AX evaluation. Probe now
    // and charge that probe against the SAME deadline, so a valid two-second
    // snapshot does not lose a three-second budget to an initial poll delay.
    static func waitForRenderedCondition(timeout: TimeInterval, object: Any?,
                                         condition: @escaping () -> Bool) -> XCTWaiter.Result {
        let deadline = Date().addingTimeInterval(timeout)
        guard timeout > 0 else { return .timedOut }
        let readyNow = condition()
        let remaining = deadline.timeIntervalSinceNow
        guard remaining > 0 else { return .timedOut }
        if readyNow { return .completed }
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in condition() }, object: object)
        return XCTWaiter.wait(for: [ready], timeout: remaining)
    }
    static func payload(_ field: XCUIElement) -> [String: Any]? {
        guard let value = field.value as? String,
              let split = value.range(of: ";native-layout="),
              let data = String(value[split.upperBound...]).data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    static func localRect(_ key: String, in payload: [String: Any]) -> CGRect? {
        guard let values = payload[key] as? [NSNumber], values.count == 4 else { return nil }
        return CGRect(x: values[0].doubleValue, y: values[1].doubleValue,
            width: values[2].doubleValue, height: values[3].doubleValue)
    }
    static func viewport(_ payload: [String: Any]) -> CGRect? {
        guard let rect = localRect("viewport", in: payload),
              rect.minX.isFinite, rect.minY.isFinite, rect.width.isFinite, rect.height.isFinite,
              rect.width > 0, rect.height > 0 else { return nil }
        return rect
    }
    static func rect(_ key: String, in payload: [String: Any]) -> CGRect? {
        guard let local = localRect(key, in: payload),
              let bounds = localRect("bounds", in: payload), let viewport = viewport(payload),
              local.minX.isFinite, local.minY.isFinite, local.width.isFinite, local.height.isFinite,
              bounds.minX.isFinite, bounds.minY.isFinite else { return nil }
        return local.offsetBy(dx: viewport.minX - bounds.minX, dy: viewport.minY - bounds.minY)
    }
    static func rightEdge(_ payload: [String: Any]) -> CGFloat? {
        guard let right = payload["right"] as? NSNumber,
              let bounds = localRect("bounds", in: payload), let viewport = viewport(payload),
              right.doubleValue.isFinite, bounds.minX.isFinite else { return nil }
        return viewport.minX + CGFloat(right.doubleValue) - bounds.minX
    }
    static func isBeside(_ control: XCUIElement, field: XCUIElement, editor: XCUIElement) -> Bool {
        guard editor.exists, let data = payload(field) else { return false }
        let fieldFrame = field.frame
        let controlFrame = control.frame
        guard let viewport = viewport(data), fieldFrame.contains(viewport),
              let first = rect("first", in: data), let right = rightEdge(data), first.height > 0 else { return false }
        return fieldFrame.contains(controlFrame) && viewport.minY <= controlFrame.minY
            && first.minY < controlFrame.maxY && first.maxY > controlFrame.minY
            && first.minY - viewport.minY < controlFrame.height / 2
            && first.maxX + 4 <= controlFrame.minX && right + 4 <= controlFrame.minX
    }
    // Geometry math consumes one captured value/frame pair. It must not query AX
    // again for every converted coordinate inside the three-second readiness poll.
    static func selectedCaretClears(_ data: [String: Any], fieldFrame: CGRect,
                                    controlFrame: CGRect, requiresScroll: Bool) -> Bool {
        guard let viewport = viewport(data), fieldFrame.contains(viewport),
              let selected = rect("selected", in: data),
              let offset = data["offset"] as? NSNumber, offset.doubleValue.isFinite,
              let right = rightEdge(data) else { return false }
        return (!requiresScroll || offset.doubleValue > 0) && viewport.insetBy(dx: -2, dy: -2).contains(selected)
            && selected.maxX + 4 <= controlFrame.minX && right + 4 <= controlFrame.minX
    }
    static func assertBeside(_ control: XCUIElement, field: XCUIElement, editor: XCUIElement,
                             file: StaticString = #filePath, line: UInt = #line) {
        let result = waitForRenderedCondition(timeout: 3, object: field) {
            control.exists && field.exists && isBeside(control, field: field, editor: editor)
        }
        XCTAssertEqual(result, .completed,
            "Actual first line must start at top-left beside the icon with a clear native right lane. field=\(field.frame) editor=\(editor.frame) control=\(control.frame) value=\(String(describing: field.value))", file: file, line: line)
    }
    static func assertSelectedCaretClears(_ control: XCUIElement, field: XCUIElement, editor: XCUIElement,
                                          requiresScroll: Bool = true, file: StaticString = #filePath, line: UInt = #line) {
        let result = waitForRenderedCondition(timeout: 3, object: field) {
            guard editor.exists, field.exists, let data = payload(field) else { return false }
            return selectedCaretClears(data, fieldFrame: field.frame, controlFrame: control.frame,
                                       requiresScroll: requiresScroll)
        }
        XCTAssertEqual(result, .completed,
            "Real native multiline scrolling must keep the selected caret visible and outside the sticky icon lane", file: file, line: line)
    }
}

// Pure geometry coverage: no application launch, fixture, credential, or inference.
final class NativeComposerRenderedGeometryTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testRenderedConditionProbesImmediatelyAndRetainsItsDeadline() {
        var probes = 0
        XCTAssertEqual(NativeComposerRenderedLayoutAssertions.waitForRenderedCondition(timeout: 3, object: nil) {
            probes += 1
            return true
        }, .completed)
        XCTAssertEqual(probes, 1)
        XCTAssertEqual(NativeComposerRenderedLayoutAssertions.waitForRenderedCondition(timeout: 0, object: nil) {
            XCTFail("An expired deadline must never start another readiness query")
            return true
        }, .timedOut)
    }
    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testCapturedCaretGeometryPreservesVisibilityScrollAndStickyLaneChecks() {
        let data: [String: Any] = [
            "viewport": [8, 332.66666666666663, 386, 104.66666666666663],
            "bounds": [0, 128.33333333333334, 386, 104.66666666666666],
            "selected": [99.66666666666667, 192.33333333333334, 2, 27.333333333333332],
            "offset": 128.33333333333334, "right": 318.0
        ]
        let field = CGRect(x: 8, y: 320, width: 386, height: 170)
        let control = CGRect(x: 335, y: 342.6666666666667, width: 44, height: 44)
        func clears(_ payload: [String: Any], fieldFrame: CGRect? = nil,
                    controlFrame: CGRect? = nil, requiresScroll: Bool = true) -> Bool {
            NativeComposerRenderedLayoutAssertions.selectedCaretClears(payload, fieldFrame: fieldFrame ?? field,
                controlFrame: controlFrame ?? control, requiresScroll: requiresScroll)
        }
        XCTAssertTrue(clears(data), "Retained ui-phone11 caret is inside its real viewport and clears the native lane")
        var changed = data
        changed["offset"] = 0.0
        XCTAssertFalse(clears(changed), "Collapsed proof still requires actual native scrolling")
        XCTAssertTrue(clears(changed, requiresScroll: false), "Expanded proof alone allows no scroll")
        changed = data
        changed["selected"] = [330.0, 192.33333333333334, 2.0, 27.333333333333332]
        XCTAssertFalse(clears(changed), "A caret inside the icon lane remains a failure")
        changed = data
        changed["selected"] = [99.66666666666667, 260.0, 2.0, 27.333333333333332]
        XCTAssertFalse(clears(changed), "A caret below the viewport remains a failure")
        changed = data
        changed["right"] = 330.0
        XCTAssertFalse(clears(changed), "Native text right edge must retain its four-point icon gap")
        XCTAssertFalse(clears(data, fieldFrame: CGRect(x: 8, y: 350, width: 386, height: 100)),
                       "A viewport outside the field remains a failure")
    }
}
