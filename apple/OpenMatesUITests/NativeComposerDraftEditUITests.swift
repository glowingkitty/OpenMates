// UI coverage for reachable native composer draft/edit behavior.
// Uses debug-only deterministic fixtures without private chat data or network calls.
// Assertions target accessibility identifiers exposed by production composer surfaces.
// Encrypted draft restoration has no UI-test key fixture, so it remains unit-tested.
// Screenshots are retained as simulator evidence for cancel/save edit semantics.

import XCTest

@MainActor
final class NativeComposerDraftEditUITests: XCTestCase {
    private let originalContent = "Original message content"
    private let updatedSuffix = " updated"

    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership
    func testEditCancelRestoresTheOriginalMessageContent() throws {
        let app = launchMessageEditFixture()

        let editor = editor(in: app, identifier: "native-message-edit-editor")
        appendUpdatedSuffix(to: editor)
        XCTAssertEqual(editor.value as? String, originalContent + updatedSuffix)

        let cancel = element(in: app, identifier: "native-message-edit-cancel")
        XCTAssertTrue(cancel.waitForExistence(timeout: 5))
        cancel.tap()

        let message = element(in: app, identifier: "native-message-edit-fixture-content")
        XCTAssertTrue(message.waitForExistence(timeout: 5))
        XCTAssertEqual(message.label, originalContent)
        XCTAssertFalse(element(in: app, identifier: "native-message-edit").exists)

        attachScreenshot(name: "Native composer edit cancel restores original content")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership
    func testEditSaveCommitsOnlyTheEditedMessageContent() throws {
        let app = launchMessageEditFixture()

        let editor = editor(in: app, identifier: "native-message-edit-editor")
        appendUpdatedSuffix(to: editor)

        let save = element(in: app, identifier: "native-message-edit-save")
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        XCTAssertTrue(save.isEnabled)
        save.tap()

        let message = element(in: app, identifier: "native-message-edit-fixture-content")
        XCTAssertTrue(message.waitForExistence(timeout: 5))
        XCTAssertEqual(message.label, originalContent + updatedSuffix)
        XCTAssertFalse(element(in: app, identifier: "native-message-edit").exists)

        attachScreenshot(name: "Native composer edit save commits edited content")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testPendingInlineEmbedFixtureExposesOneAccessibleAtomAfterColdLaunch() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "chat-opening",
            "--ui-test-seed-pending-composer-embed"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        let atomIdentifier = "native-composer-embed-composer:embed:ui-test"
        let atom = element(in: app, identifier: atomIdentifier)
        XCTAssertTrue(atom.waitForExistence(timeout: 12))
        XCTAssertEqual(
            app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier == %@", atomIdentifier))
                .count,
            1,
            "The pending embed fixture must remain one inline atom after a cold launch"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence,message-input.embeds.gated-send,drafts.draft-only.presentation,message-input.focus.workspace-suppression
    func testWelcomeImageAudioAutosaveKeepsSameComposerAndPreviews() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-window-drafts", "--ui-test-welcome-draft-attachments"]
        app.launch()
        let probe = app.staticTexts["welcome-draft-attachment-probe"]
        XCTAssertTrue(probe.waitForExistence(timeout: 15))
        XCTAssertFalse(app.staticTexts["composer-pii-regex-fallback"].exists,
                       "Fallback processing must not add an unsolicited welcome composer paragraph")
        let input = app.textViews["message-editor"].firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        guard RealAccountUITestSupport.focusForTextEntry(input, in: app, identifier: "message-editor") else { return }
        input.typeText("Synthetic attachment draft text")
        func assertSaved() {
            let saved = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                let values = Dictionary(probe.label.split(separator: ";").compactMap { part in
                    let pair = part.split(separator: "=", maxSplits: 1)
                    return pair.count == 2 ? (String(pair[0]), String(pair[1])) : nil
                }, uniquingKeysWith: { _, last in last })
                return values["nodes"] == "2" && values["resolved"] == "2"
                    && values["saved"] == values["revision"] && values["saved"] != "-1"
            }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [saved], timeout: 12), .completed)
            XCTAssertTrue(app.descendants(matching: .any)["chat-workspace-welcome"].exists)
            XCTAssertFalse(app.staticTexts["chat-header-title"].exists)
            XCTAssertGreaterThanOrEqual(app.descendants(matching: .any).matching(NSPredicate(format:
                "identifier BEGINSWITH %@", "native-composer-embed-")).count, 2)
        }
        assertSaved()
        input.typeText(" and later text")
        assertSaved()
        let greeting = app.descendants(matching: .any)["welcome-workspace-greeting"].firstMatch
        XCTAssertFalse(greeting.exists, "Active editing suppresses the surrounding welcome workspace")
        let backdrop = app.buttons["welcome-composer-workspace-backdrop"]
        XCTAssertTrue(backdrop.waitForExistence(timeout: 5))
        app.buttons["new-chat-draft-dismiss-button"].tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 12))
        XCTAssertTrue(greeting.waitForExistence(timeout: 5))
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        assertSaved()
        guard RealAccountUITestSupport.focusForTextEntry(input, in: app, identifier: "message-editor") else { return }
        XCTAssertFalse(greeting.exists)
        // The attachment editor covers the backdrop's central region.
        // Resolve its actual exposed gutter before sending an outside tap.
        let outsideBounds = backdrop.frame.intersection(app.windows.firstMatch.frame)
        let gutterWidth = input.frame.minX - outsideBounds.minX
        XCTAssertGreaterThan(gutterWidth, 0)
        let outsidePoint = CGPoint(x: outsideBounds.minX + gutterWidth / 2,
                                   y: max(outsideBounds.minY, input.frame.minY) + 24)
        XCTAssertTrue(outsideBounds.contains(outsidePoint))
        XCTAssertFalse(input.frame.contains(outsidePoint))
        app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: outsidePoint.x, dy: outsidePoint.y)).tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 12))
        XCTAssertTrue(greeting.waitForExistence(timeout: 5))
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        assertSaved()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.workspace-suppression,message-input.layout.responsive-parity,message-input.drafts.preview-persistence
    func testChatFocusAndExpansionDimTranscriptAndOutsideCancelRestoreDraft() {
        let app = launchComposerSendFixture(outcome: "accepted")
        let editor = editor(in: app)
        let history = app.scrollViews["chat-history-container"].firstMatch
        XCTAssertTrue(history.waitForExistence(timeout: 8))
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor") else { return }
        let field = element(in: app, identifier: "message-field")
        let mic = app.buttons["record-audio-button"]
        XCTAssertGreaterThan(mic.frame.midX, field.frame.midX)
        XCTAssertGreaterThan(mic.frame.midY, field.frame.midY)
        let backdrop = app.buttons["chat-composer-workspace-backdrop"]
        XCTAssertTrue(backdrop.waitForExistence(timeout: 5))
        XCTAssertEqual(backdrop.value as? String, "background-opacity=0.35;background-interactive=false")
        XCTAssertTrue(!history.exists || !history.isEnabled)
        let fullscreen = app.buttons["message-input-fullscreen-button"]
        XCTAssertFalse(fullscreen.exists, "An empty focused editor has no overflow action")
        let shortDraft = "Synthetic preserved chat draft"
        editor.typeText(shortDraft)
        XCTAssertFalse(fullscreen.exists, "A single short line must not expose Expand")
        let continuation = "\nSecond line\nThird line\nFourth line\nFifth line"
        let draft = shortDraft + continuation
        editor.typeText(continuation)
        XCTAssertEqual(editor.value as? String, draft)
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5)); XCTAssertTrue(fullscreen.isHittable)
        NativeComposerRenderedLayoutAssertions.assertBeside(fullscreen, field: field, editor: editor)
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(fullscreen, field: field, editor: editor)
        let collapsedEditorHeight = editor.frame.height
        fullscreen.tap()
        expectation(for: NSPredicate { _, _ in editor.frame.height > collapsedEditorHeight }, evaluatedWith: editor)
        waitForExpectations(timeout: 3)
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(fullscreen, field: field, editor: editor, requiresScroll: false)
        let cancel = app.buttons["chat-composer-cancel"]
        XCTAssertEqual(cancel.frame.width, field.frame.width, accuracy: 1)
        XCTAssertEqual(cancel.frame.minX, field.frame.minX, accuracy: 1)
        XCTAssertTrue(backdrop.exists, "Expansion keeps the whole transcript suppressed even after keyboard blur")
        XCTAssertGreaterThanOrEqual(backdrop.frame.height, 48,
                                    "Expanded editing must retain an actual outside tap lane")
        backdrop.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 5))
        XCTAssertTrue(history.waitForExistence(timeout: 5)); XCTAssertTrue(history.isEnabled)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        XCTAssertEqual(editor.value as? String, draft)
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor") else { return }
        app.buttons["chat-composer-cancel"].tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 5))
        XCTAssertTrue(history.isEnabled)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        XCTAssertEqual(editor.value as? String, draft)
        attachScreenshot(name: "Chat outside Cancel restores transcript with draft intact")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership,message-input.layout.responsive-parity
    func testAcceptedSendClosesExpandedComposerAndDismissesKeyboard() {
        let app = launchComposerSendFixture(outcome: "accepted")
        let editor = editor(in: app)
        editor.tap()
        let fullscreen = app.buttons["message-input-fullscreen-button"]
        XCTAssertFalse(fullscreen.exists, "An empty focused editor has no overflow action")
        let shortDraft = "Synthetic composer send"
        editor.typeText(shortDraft)
        XCTAssertFalse(fullscreen.exists, "A single short line must not expose Expand")
        let continuation = "\nSecond line\nThird line\nFourth line\nFifth line"
        let draft = shortDraft + continuation
        editor.typeText(continuation)
        XCTAssertEqual(editor.value as? String, draft)
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5)); XCTAssertTrue(fullscreen.isHittable)
        let collapsedEditorHeight = editor.frame.height
        fullscreen.tap()
        expectation(for: NSPredicate { _, _ in editor.frame.height > collapsedEditorHeight }, evaluatedWith: editor)
        waitForExpectations(timeout: 3)
        editor.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        let field = element(in: app, identifier: "message-field")
        let expandedHeight = field.frame.height
        NativeComposerRenderedLayoutAssertions.assertBeside(fullscreen, field: field, editor: editor)
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(fullscreen, field: field, editor: editor, requiresScroll: false)
        let send = app.buttons["send-button"]
        XCTAssertTrue(send.isHittable)
        send.tap()

        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: fullscreen)
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: app.keyboards.firstMatch)
        waitForExpectations(timeout: 8)
        XCTAssertLessThan(field.frame.height, expandedHeight - 40)
        XCTAssertFalse(app.menuItems["Copy"].exists, "An accepted send must leave no selected text menu")
        attachScreenshot(name: "Accepted composer send closes expansion and keyboard")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership,message-input.layout.responsive-parity
    func testRejectedSendRetainsDraftExpansionAndKeyboardFocus() {
        let app = launchComposerSendFixture(outcome: "rejected")
        let editor = editor(in: app)
        editor.tap()
        let fullscreen = app.buttons["message-input-fullscreen-button"]
        XCTAssertFalse(fullscreen.exists, "An empty focused editor has no overflow action")
        let shortDraft = "Synthetic rejected draft"
        editor.typeText(shortDraft)
        XCTAssertFalse(fullscreen.exists, "A single short line must not expose Expand")
        let continuation = "\nSecond line\nThird line\nFourth line\nFifth line"
        let draft = shortDraft + continuation
        editor.typeText(continuation)
        XCTAssertEqual(editor.value as? String, draft)
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5)); XCTAssertTrue(fullscreen.isHittable)
        let collapsedEditorHeight = editor.frame.height
        fullscreen.tap()
        expectation(for: NSPredicate { _, _ in editor.frame.height > collapsedEditorHeight }, evaluatedWith: editor)
        waitForExpectations(timeout: 3)
        editor.tap()
        let field = element(in: app, identifier: "message-field")
        let expandedHeight = field.frame.height
        NativeComposerRenderedLayoutAssertions.assertBeside(fullscreen, field: field, editor: editor)
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(fullscreen, field: field, editor: editor, requiresScroll: false)
        app.buttons["send-button"].tap()

        let outcome = element(in: app, identifier: "composer-send-fixture-outcome")
        expectation(for: NSPredicate(format: "label == %@", "rejected"), evaluatedWith: outcome)
        expectation(for: NSPredicate(format: "value == %@", draft), evaluatedWith: editor)
        waitForExpectations(timeout: 8)
        XCTAssertTrue(fullscreen.exists)
        XCTAssertGreaterThanOrEqual(field.frame.height, expandedHeight - 8)
        XCTAssertTrue(app.keyboards.firstMatch.exists)
        editor.typeText(" retained")
        XCTAssertEqual(editor.value as? String, draft + " retained")
        attachScreenshot(name: "Rejected composer send retains editable expanded draft")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership,message-input.layout.responsive-parity,message-input.focus.workspace-suppression
    func testAcceptedFollowUpClosesComposerAndDismissesKeyboard() throws {
        let app = launchComposerSendFixture(outcome: "accepted")
        let editor = editor(in: app)
        editor.tap()
        let fullscreen = app.buttons["message-input-fullscreen-button"]
        XCTAssertFalse(fullscreen.exists, "An empty focused editor has no overflow action")
        let shortDraft = "Synthetic draft before follow-up"
        editor.typeText(shortDraft)
        XCTAssertFalse(fullscreen.exists, "A single short line must not expose Expand")
        let continuation = "\nSecond line\nThird line\nFourth line\nFifth line"
        let draft = shortDraft + continuation
        editor.typeText(continuation)
        XCTAssertEqual(editor.value as? String, draft)
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
        let suppressed = app.buttons.matching(identifier: "follow-up-suggestion-item")
        XCTAssertTrue(suppressed.allElementsBoundByIndex.allSatisfy { !$0.exists || !$0.isEnabled },
            "Transcript follow-ups cannot be used while composing")
        let backdrop = app.buttons["chat-composer-workspace-backdrop"]
        XCTAssertTrue(backdrop.waitForExistence(timeout: 5))
        XCTAssertEqual(backdrop.value as? String, "background-opacity=0.35;background-interactive=false")
        app.buttons["chat-composer-cancel"].tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5))
        XCTAssertEqual(editor.value as? String, draft)
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 5))
        let history = app.scrollViews["chat-history-container"].firstMatch
        XCTAssertTrue(history.waitForExistence(timeout: 5))
        let suggestions = app.buttons.matching(identifier: "follow-up-suggestion-item")
        if let latest = NativeUITestElementResolution.visible(
            app.buttons.matching(identifier: "scroll-to-bottom-button"), in: app) {
            latest.tap()
        }
        for _ in 0..<4 {
            if NativeUITestElementResolution.visible(suggestions, in: app) != nil { break }
            history.swipeUp()
        }
        let suggestion = try NativeUITestElementResolution.requireVisible(suggestions, in: app, timeout: 5)
        suggestion.tap()

        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: fullscreen)
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: app.keyboards.firstMatch)
        waitForExpectations(timeout: 8)
        attachScreenshot(name: "Accepted follow-up closes composer and keyboard")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership,chats.streaming.progressive-presentation
    func testAuthoritativeProcessingCompletionRestoresComposerAfterStaleReplay() {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "chat-opening", "--ui-test-composer-send", "accepted",
            "--ui-test-composer-processing-recovery"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()
        let banner = element(in: app, identifier: "streaming-banner")
        let stop = app.buttons["stop-processing-button"]
        XCTAssertTrue(banner.waitForExistence(timeout: 12))
        XCTAssertTrue(stop.waitForExistence(timeout: 5))
        XCTAssertTrue(stop.isHittable)
        let recover = app.buttons["composer-processing-recover"]
        XCTAssertTrue(recover.waitForExistence(timeout: 5))
        XCTAssertTrue(recover.isHittable)
        recover.tap()

        expectation(for: NSPredicate(format: "value == %@", "completed"), evaluatedWith: recover)
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: banner)
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: stop)
        waitForExpectations(timeout: 8)
        XCTAssertEqual(recover.value as? String, "completed", "Synthetic recovery action receipt")
        let receipt = XCTAttachment(string: "recovery-receipt=\(recover.value as? String ?? "missing")\n\(app.debugDescription)")
        receipt.name = "Synthetic processing recovery action and hierarchy"
        receipt.lifetime = .keepAlways
        add(receipt)
        let editor = editor(in: app)
        editor.tap()
        editor.typeText("Synthetic draft after completed processing")
        let send = app.buttons["send-button"]
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        XCTAssertTrue(send.isEnabled)
        XCTAssertTrue(send.isHittable)
        XCTAssertFalse(banner.exists)
        XCTAssertFalse(stop.exists)
        attachScreenshot(name: "Authoritative processing completion restores composer after stale replay")
    }

    private func launchComposerSendFixture(outcome: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-composer-send", outcome]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()
        XCTAssertTrue(app.textViews["message-editor"].firstMatch.waitForExistence(timeout: 12))
        return app
    }

    private func launchMessageEditFixture() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer-draft-edit"]
        app.launchEnvironment["DEV_PREVIEW"] = "composer-draft-edit"
        app.launch()

        let cancel = element(in: app, identifier: "native-message-edit-cancel")
        XCTAssertTrue(
            cancel.waitForExistence(timeout: 8),
            "Expected native edit fixture. Visible hierarchy: \(app.debugDescription)"
        )
        XCTAssertTrue(app.textViews["native-message-edit-editor"].firstMatch.waitForExistence(timeout: 5))
        return app
    }

    private func editor(in app: XCUIApplication, identifier: String = "message-editor") -> XCUIElement {
        let editor = app.textViews[identifier].firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        return editor
    }

    private func appendUpdatedSuffix(to editor: XCUIElement) {
        editor.typeText(updatedSuffix)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)[identifier]
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
