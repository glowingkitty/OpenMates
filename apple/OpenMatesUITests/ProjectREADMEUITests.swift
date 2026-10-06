import CryptoKit
import XCTest

@MainActor
final class ProjectREADMEUITests: XCTestCase {
    // README is a document taller than the viewport. Its scroll container's
    // hit point and AX ancestry do not establish whether a Markdown block renders.
    private func readmeBlocks(in app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(NSPredicate(format:
            "identifier MATCHES %@", "^project-readme-(heading|paragraph|code|table|list)-[0-9]+(-[0-9]+)?$"))
    }

    private func hasVisibleReadmeBlock(in app: XCUIApplication, scroll: XCUIElement) -> Bool {
        guard scroll.exists, app.windows.firstMatch.exists else { return false }
        let viewport = scroll.frame.intersection(app.windows.firstMatch.frame)
        guard !viewport.isNull, viewport.width > 0, viewport.height > 0 else { return false }
        return readmeBlocks(in: app).allElementsBoundByIndex.contains { block in
            guard block.exists else { return false }
            let frame = block.frame
            guard frame.width > 0, frame.height > 0 else { return false }
            let visible = frame.intersection(viewport)
            guard !visible.isNull, visible.width >= 16, visible.height >= 8 else { return false }
            return block.isHittable
        }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.files.connected-embed-previews,projects.surface.semantic-parity
    func testPersonalProjectReadmeAndFilesReadOnly() throws {
        guard RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_READ_ONLY") == "1",
              let identityHash = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_IDENTITY_HASH"),
              let accountHash = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_ACCOUNT_HASH"),
              !accountHash.isEmpty,
              let projectID = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_READ_ONLY_PROJECT_ID"),
              UUID(uuidString: projectID) != nil else {
            throw XCTSkip("Explicit personal read-only identity, account and existing Project configuration is required")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        let normalizedEmail = credentials.email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let actualIdentityHash = SHA256.hash(data: Data(normalizedEmail.utf8)).prefix(8)
            .map { String(format: "%02x", $0) }.joined()
        guard actualIdentityHash == identityHash else {
            throw XCTSkip("Credentials do not match the approved personal identity")
        }
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true,
            extraArguments: ["--ui-test-open-login", "--ui-test-read-only-performance", "-AppleLanguages", "(en)"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        let accountProbe = app.descendants(matching: .any).matching(identifier: "read-only-responsiveness-metrics").firstMatch
        XCTAssertTrue(accountProbe.waitForExistence(timeout: 10))
        func fields(_ element: XCUIElement) -> [String: String] {
            Dictionary(element.label.split(separator: ";").compactMap { field in
                let pair = field.split(separator: "=", maxSplits: 1)
                return pair.count == 2 ? (String(pair[0]), String(pair[1])) : nil
            }, uniquingKeysWith: { _, last in last })
        }
        let verified = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let values = fields(accountProbe)
            return values["account-hash"] == accountHash && values["server-kind"] == "development"
                && (Double(values["samples"] ?? "") ?? 0) > 0
        }, object: nil)], timeout: 10) == .completed
        XCTAssertTrue(verified, "The authenticated account and development server must match the approved read-only context")
        guard verified else { return }
        let sync = app.descendants(matching: .any).matching(NSPredicate(format:
            "identifier == %@ AND value == %@", "chat-sync-complete", "true")).firstMatch
        XCTAssertTrue(sync.waitForExistence(timeout: 45))
        let picker = app.buttons["workspace-switcher"]
        if !app.buttons["projects-nav-link"].isHittable {
            XCTAssertTrue(picker.waitForExistence(timeout: 5)); picker.tap()
        }
        let projects = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "projects-nav-link"), in: app)
        projects.tap()
        let all = app.buttons["projects-show-all"]
        XCTAssertTrue(all.waitForExistence(timeout: 15)); all.tap()
        let card = app.buttons["project-card-" + projectID]
        let list = app.scrollViews["projects-browse-list"]
        for _ in 0..<12 where !card.isHittable {
            let more = app.buttons["projects-browse-load-more"]
            if more.isHittable { more.tap() } else { list.swipeUp() }
        }
        XCTAssertTrue(card.isHittable, "The configured existing Project must be reachable")
        guard card.isHittable else { return }
        card.tap()
        XCTAssertTrue(app.buttons["project-header-edit"].waitForExistence(timeout: 10))
        let diagnostic = app.descendants(matching: .any).matching(identifier: "project-read-only-diagnostics").firstMatch
        XCTAssertTrue(diagnostic.waitForExistence(timeout: 5))
        let overview = app.buttons["project-tab-overview"]
        XCTAssertTrue(overview.waitForExistence(timeout: 5)); overview.tap()
        let settledReadme = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            fields(diagnostic)["readme"] != "pending"
        }, object: nil)], timeout: 100) == .completed
        let readmeFields = fields(diagnostic)
        let content = app.descendants(matching: .any).matching(identifier: "project-readme-content").firstMatch
        let scroll = app.scrollViews["project-detail-scroll"]
        for _ in 0..<5 where !hasVisibleReadmeBlock(in: app, scroll: scroll) { scroll.swipeUp() }
        let renderedBlockVisible = hasVisibleReadmeBlock(in: app, scroll: scroll)
        let renderedBlockCount = readmeBlocks(in: app).count
        let readmeContentExists = content.exists
        let readmeContentHittable = content.isHittable
        let renderedReadme = settledReadme && readmeFields["readme"] == "ready"
            && renderedBlockVisible && renderedBlockCount > 0
        for _ in 0..<5 where !app.buttons["project-tab-files"].isHittable { scroll.swipeDown() }
        XCTAssertTrue(app.buttons["project-tab-files"].isHittable)
        app.buttons["project-tab-files"].tap()
        let settledFiles = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let value = fields(diagnostic)["files"]
            return value != nil && value != "pending"
        }, object: nil)], timeout: 60) == .completed
        let fileFields = fields(diagnostic)
        let entries = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "project-remote-entry-"))
        for _ in 0..<5 where !entries.firstMatch.isHittable { scroll.swipeUp() }
        let renderedFiles = settledFiles && fileFields["files"] == "ready"
            && (Int(fileFields["file-count"] ?? "") ?? 0) > 0 && entries.firstMatch.isHittable
        let safeReceipt: [String: Any] = ["readme": readmeFields, "files": fileFields,
            "readme-rendered": renderedReadme, "files-rendered": renderedFiles,
            "readme-content-exists": readmeContentExists, "readme-content-hittable": readmeContentHittable,
            "readme-block-count": renderedBlockCount, "readme-visible-block": renderedBlockVisible]
        let receipt = XCTAttachment(data: try JSONSerialization.data(withJSONObject: safeReceipt, options: [.sortedKeys]),
            uniformTypeIdentifier: "public.json")
        receipt.name = "personal-project-read-only-sanitized-result"; receipt.lifetime = .keepAlways; add(receipt)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "private-personal-project-read-only"; screenshot.lifetime = .keepAlways; add(screenshot)
        XCTAssertTrue(renderedReadme, "README must render; sanitized diagnostic category is attached")
        XCTAssertTrue(renderedFiles, "Existing remote file entries must render; sanitized diagnostic category is attached")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testConfirmedOfflineReadmeShowsClearMessageAndRetry() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "offlineConnectedSource", "-AppleLanguages", "(en)"]
        app.launch()
        let overview = app.buttons["project-tab-overview"]
        XCTAssertTrue(overview.waitForExistence(timeout: 8))
        overview.tap()
        let offline = app.staticTexts["project-readme-offline"]
        let scroll = app.scrollViews["project-detail-scroll"]
        for _ in 0..<4 where !offline.isHittable { scroll.swipeUp() }
        XCTAssertTrue(offline.waitForExistence(timeout: 5))
        XCTAssertEqual(offline.label, "Remote machine is offline")
        XCTAssertTrue(app.buttons["project-readme-retry"].isHittable)
        XCTAssertFalse(app.staticTexts["project-readme-error"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testReadmeReadFailureKeepsFailureAndRetryWithoutOfflineClaim() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "readme",
            "--ui-test-project-readme-failed", "-AppleLanguages", "(en)"]
        app.launch()
        let failure = app.staticTexts["project-readme-error"]
        XCTAssertTrue(failure.waitForExistence(timeout: 8))
        let scroll = app.scrollViews["project-detail-scroll"]
        for _ in 0..<4 where !failure.isHittable { scroll.swipeUp() }
        XCTAssertTrue(failure.isHittable)
        XCTAssertTrue(app.buttons["project-readme-retry"].isHittable)
        XCTAssertFalse(app.staticTexts["project-readme-offline"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.workspace.contract-plan-task-check-chain,projects.surface.semantic-parity
    func testProjectTasksOuterScrollPreservesViewportBottomComposer() {
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "tasks", "--ui-test-project-many-tasks", "-AppleLanguages", "(en)"]
        app.launch()
        let composer = app.descendants(matching: .any)["project-task-workspace-composer"].firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 8))
        let scroll = app.scrollViews["project-detail-scroll"]
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        let cards = scroll.descendants(matching: .any).matching(identifier: "task-card")
        XCTAssertGreaterThanOrEqual(cards.count, 20, "The linked fixture must mount enough real cards to overflow")
        XCTAssertGreaterThan(cards.allElementsBoundByIndex.map { $0.frame.maxY }.max() ?? 0, scroll.frame.maxY,
            "The board content must actually extend below the viewport before the scroll assertion")
        let originalY = composer.frame.minY
        let before = app.buttons["project-tab-tasks"].frame.minY
        scroll.swipeUp()
        XCTAssertEqual(composer.frame.minY, originalY, accuracy: 2,
                       "Project task composer belongs to the viewport, outside the vertical scroll")
        XCTAssertLessThan(app.buttons["project-tab-tasks"].frame.minY, before)
        XCTAssertLessThanOrEqual(scroll.frame.maxY, composer.frame.minY + 2)
        XCTAssertFalse(scroll.scrollViews.matching(identifier: "tasks-workspace-scroll").firstMatch.exists,
                       "The compact board must delegate vertical scrolling to the Project page")
        XCTAssertTrue(app.descendants(matching: .any)["project-task-workspace-input"].firstMatch.isHittable)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state,message-input.layout.responsive-parity,projects.surface.semantic-parity,message-input.focus.workspace-suppression
    func testProjectCreationFocusKeepsMicrophoneRightAndRestoresWorkspace() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "landing", "-AppleLanguages", "(en)"]
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        app.launch()
        let editor = app.textViews["project-input-textarea"]
        let composer = app.descendants(matching: .any)["project-input-composer"].firstMatch
        let card = app.buttons["project-card-preview-project"]
        XCTAssertTrue(editor.waitForExistence(timeout: 8))
        XCTAssertTrue(card.isHittable)
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "project-input-textarea") else { return }
        let mic = app.buttons["project-input-mic"]
        XCTAssertGreaterThan(mic.frame.midX, composer.frame.midX)
        let backdrop = app.buttons["project-home-prompt-backdrop"]
        XCTAssertTrue(backdrop.waitForExistence(timeout: 5))
        XCTAssertEqual(backdrop.value as? String, "background-opacity=0;background-interactive=false")
        XCTAssertTrue(!card.exists || !card.isEnabled, "Background project cards are disabled while composing")
        let cancel = app.buttons["project-input-composer-cancel"]
        let field = composer.descendants(matching: .any)["message-field"].firstMatch
        XCTAssertEqual(cancel.frame.width, field.frame.width, accuracy: 1)
        XCTAssertEqual(cancel.frame.minX, field.frame.minX, accuracy: 1)
        let expand = app.buttons["project-input-composer-expand"]
        XCTAssertFalse(expand.exists, "An empty focused editor has no overflow action")
        let shortDraft = "Synthetic Project draft\nSecond line\nThird line"
        editor.typeText(shortDraft)
        XCTAssertFalse(expand.exists, "Three short native lines fit without Expand")
        let continuation = "\nFourth line\nFifth line"
        let draft = shortDraft + continuation
        editor.typeText(continuation)
        XCTAssertEqual(editor.value as? String, draft)
        XCTAssertTrue(expand.waitForExistence(timeout: 5)); XCTAssertTrue(expand.isHittable)
        NativeComposerRenderedLayoutAssertions.assertBeside(expand, field: field, editor: editor)
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(expand, field: field, editor: editor)
        let collapsedEditorHeight = editor.frame.height
        expand.tap()
        XCTAssertEqual(expand.label, "Exit fullscreen")
        expectation(for: NSPredicate { _, _ in editor.frame.height > collapsedEditorHeight }, evaluatedWith: editor)
        waitForExpectations(timeout: 3)
        NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(expand, field: field, editor: editor, requiresScroll: false)
        XCTAssertEqual(cancel.frame.width, field.frame.width, accuracy: 1)
        XCTAssertEqual(cancel.frame.minX, field.frame.minX, accuracy: 1)
        cancel.tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 5))
        XCTAssertTrue(card.isHittable)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        XCTAssertEqual(editor.value as? String, draft)
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "project-input-textarea") else { return }
        backdrop.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 5))
        XCTAssertEqual(editor.value as? String, draft)
        XCTAssertTrue(card.isHittable)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Project focus outside Cancel restores workspace"; screenshot.lifetime = .keepAlways; add(screenshot)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state,message-input.drafts.preview-persistence,projects.surface.semantic-parity,message-input.focus.workspace-suppression
    func testProjectTaskPromptOutsideDismissRetainsDraft() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "tasks", "-AppleLanguages", "(en)"]
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        app.launch()
        let editor = app.textViews["project-task-workspace-input"]
        XCTAssertTrue(editor.waitForExistence(timeout: 8))
        XCTAssertTrue(editor.isHittable); editor.tap()
        let composer = app.descendants(matching: .any)["project-task-workspace-composer"].firstMatch
        let mic = app.buttons["project-task-workspace-mic"]
        XCTAssertGreaterThan(mic.frame.midX, composer.frame.midX)
        editor.typeText("Synthetic retained Project task draft")
        let backdrop = app.descendants(matching: .any).matching(identifier: "project-task-workspace-backdrop").firstMatch
        XCTAssertTrue(backdrop.waitForExistence(timeout: 5))
        XCTAssertEqual(backdrop.value as? String, "background-opacity=0;background-interactive=false")
        let background = app.scrollViews["project-detail-scroll"]
        XCTAssertTrue(!background.exists || !background.isEnabled)
        XCTAssertTrue(backdrop.isHittable); backdrop.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
        let hidden = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !backdrop.exists || !backdrop.isHittable
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [hidden], timeout: 5), .completed)
        XCTAssertEqual(editor.value as? String, "Synthetic retained Project task draft")
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        XCTAssertTrue(background.exists); XCTAssertTrue(background.isEnabled)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testReadmeRendersSeparateBlocksAndDecodedImage() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "readme",
            "--dev-preview-theme", "dark", "--dev-preview-width", "390", "--dev-preview-height", "844",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let first = app.descendants(matching: .any)["project-readme-heading-0"]
        XCTAssertTrue(first.waitForExistence(timeout: 8))
        let readmeScroll = app.scrollViews["project-detail-scroll"]
        for _ in 0..<5 where !hasVisibleReadmeBlock(in: app, scroll: readmeScroll) { readmeScroll.swipeUp() }
        XCTAssertTrue(hasVisibleReadmeBlock(in: app, scroll: readmeScroll),
                      "A visible Markdown block must establish rendering even when the document exceeds the viewport")
        let paragraph = app.descendants(matching: .any)["project-readme-paragraph-1"]
        let second = app.descendants(matching: .any)["project-readme-heading-2"]
        XCTAssertTrue(paragraph.exists)
        XCTAssertTrue(second.exists)
        XCTAssertGreaterThan(paragraph.frame.minY, first.frame.maxY)
        XCTAssertGreaterThan(second.frame.minY, paragraph.frame.maxY)
        XCTAssertTrue(app.descendants(matching: .any)["project-readme-list-3-0"].exists)
        let code = app.descendants(matching: .any)["project-readme-code-4"].firstMatch
        let imageParagraph = app.descendants(matching: .any)["project-readme-paragraph-5"].firstMatch
        let image = imageParagraph.descendants(matching: .image)["project-readme-image-rendered"].firstMatch
        for _ in 0..<6 where !code.exists || code.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(code.exists)
        XCTAssertGreaterThan(code.frame.height, 10)
        for _ in 0..<6 where !image.exists || image.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(imageParagraph.exists, "Image paragraphs retain their own accessibility container")
        XCTAssertTrue(image.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(image.frame.width, 20)
        XCTAssertGreaterThan(image.frame.height, 10)
        XCTAssertFalse(app.staticTexts["[Image: Project overview preview]"].exists)
        let list = app.descendants(matching: .any)["project-readme-list-6-0"].firstMatch
        for _ in 0..<6 where !list.exists || list.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(list.exists)
        XCTAssertTrue(list.descendants(matching: .image)["project-readme-image-rendered"].firstMatch.waitForExistence(timeout: 5),
                      "Reference images in list items must use the real image renderer")
        let table = app.descendants(matching: .any)["project-readme-table-7"].firstMatch
        for _ in 0..<6 where !table.exists || table.frame.minY >= app.frame.maxY { app.swipeUp() }
        XCTAssertTrue(table.exists)
        XCTAssertTrue(table.staticTexts["Documentation"].exists)
        XCTAssertTrue(table.staticTexts["Ready"].exists)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "README blocks and decoded project image"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
