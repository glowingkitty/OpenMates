import XCTest

@MainActor
final class ChatSettingsParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testChatSettingsHeaderTabsTaskCreationAndCompletionAreVisibleAndOperable() {
        let app = launch("chat-settings")
        let header = app.descendants(matching: .any)["chat-settings-header"].firstMatch
        XCTAssertTrue(header.waitForExistence(timeout: 15))
        XCTAssertGreaterThan(header.frame.height, 150)
        XCTAssertTrue(app.staticTexts["Launch preparation"].exists)
        let tasks = app.buttons["chat-settings-tab-tasks"]
        XCTAssertTrue(tasks.isHittable); tasks.tap()
        let title = app.textFields["chat-settings-task-title-input"]
        XCTAssertTrue(title.waitForExistence(timeout: 3)); XCTAssertTrue(title.isHittable)
        title.tap(); title.typeText("Verify the synthetic release\n")
        let scroll = app.scrollViews["chat-settings-scroll"]
        let create = app.buttons["chat-settings-task-create-button"]
        reveal(create, in: scroll)
        create.tap()
        XCTAssertTrue(app.staticTexts["Verify the synthetic release"].waitForExistence(timeout: 3))
        // The checkbox retains toggle accessibility traits, which XCTest may
        // expose as a Switch rather than a Button.
        let createdRow = app.descendants(matching: .any)
            .matching(identifier: "chat-settings-task-row")
            .containing(.staticText, identifier: "Verify the synthetic release").firstMatch
        XCTAssertTrue(createdRow.waitForExistence(timeout: 3))
        let done = createdRow.descendants(matching: .any)["chat-settings-task-done-toggle"].firstMatch
        XCTAssertTrue(done.waitForExistence(timeout: 3))
        reveal(done, in: scroll)
        XCTAssertEqual(done.value as? String, "Off"); done.tap()
        let completed = NSPredicate(format: "value == %@", "On")
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: completed, object: done)], timeout: 3) == .completed)
        XCTAssertEqual(app.descendants(matching: .any)["chat-settings-task-progress"].firstMatch.value as? String, "50%")
        attach(app, "Chat Settings task creation and completion")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testShareUsesWebOptionsAndGeneratedURLDisclosure() {
        let app = launch("chat-settings")
        let share = app.buttons["chat-settings-tab-share"]
        XCTAssertTrue(share.waitForExistence(timeout: 15)); XCTAssertTrue(share.isHittable); share.tap()
        let scroll = app.scrollViews["chat-settings-scroll"]
        let password = app.descendants(matching: .any)["chat-settings-share-password"].firstMatch
        XCTAssertTrue(password.waitForExistence(timeout: 3)); reveal(password, in: scroll); password.tap()
        let input = app.secureTextFields["chat-settings-share-password-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 3)); reveal(input, in: scroll); input.tap(); input.typeText("example\n")
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 3), "Done must dismiss the share password keyboard")
        scroll.swipeUp()
        let generate = app.buttons["share-generate-link"]
        reveal(generate, in: scroll); generate.tap()
        let copy = app.buttons["share-copy-link"]
        XCTAssertTrue(copy.waitForExistence(timeout: 3)); reveal(copy, in: scroll)
        let showURL = app.buttons["chat-settings-share-show-url"]
        reveal(showURL, in: scroll); showURL.tap()
        let url = app.staticTexts["https://example.invalid/share/chat/preview-chat-settings#key=preview"]
        XCTAssertTrue(url.exists); reveal(url, in: scroll)
        XCTAssertTrue(url.isHittable)
        attach(app, "Chat Settings generated share disclosure")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testSharedChatSuppressesAllOwnerMutationControls() {
        let app = launch("chat-settings-shared")
        let share = app.buttons["chat-settings-tab-share"]
        XCTAssertTrue(share.waitForExistence(timeout: 15)); share.tap()
        XCTAssertTrue(app.descendants(matching: .any)["chat-settings-share-readonly"].firstMatch.waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["share-generate-link"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["chat-settings-share-password"].firstMatch.exists)
        app.buttons["chat-settings-tab-tasks"].tap()
        XCTAssertFalse(app.buttons["chat-settings-task-create-button"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["chat-settings-task-done-toggle"].firstMatch.exists)
        attach(app, "Shared Chat Settings read-only controls")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testPopulatedUsageShowsTotalProviderAndTimestamp() {
        let app = launch("chat-settings-usage")
        let total = app.descendants(matching: .any)["chat-settings-usage-total"].firstMatch
        XCTAssertTrue(total.waitForExistence(timeout: 15))
        let scroll = app.scrollViews["chat-settings-scroll"]
        reveal(total, in: scroll)
        XCTAssertEqual(total.value as? String, "24")
        let subtitle = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@", "Google AI Studio / US", "2026")).firstMatch
        XCTAssertTrue(subtitle.exists); reveal(subtitle, in: scroll)
        XCTAssertTrue(app.staticTexts["ai | ask"].exists)
        let aiIcon = app.images["chat-settings-usage-icon-preview-usage-ai"]
        XCTAssertTrue(aiIcon.exists); XCTAssertEqual(aiIcon.label, "ai")
        let webIcon = app.images["chat-settings-usage-icon-preview-usage-web"]
        XCTAssertTrue(webIcon.exists); XCTAssertEqual(webIcon.label, "web")
        attach(app, "Chat Settings populated Usage total provider and date")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testPublicUsageUsesBundledEntriesAndSuppressesOwnerPlanning() {
        let app = launch("chat-settings-public")
        let usage = app.buttons["chat-settings-tab-usage"]
        XCTAssertTrue(usage.waitForExistence(timeout: 15))
        let scroll = app.scrollViews["chat-settings-scroll"]
        let summary = app.staticTexts["chat-settings-summary"]
        let tabs = app.descendants(matching: .any)["chat-settings-tabs"].firstMatch
        XCTAssertTrue(summary.exists); XCTAssertTrue(tabs.exists)
        XCTAssertEqual(summary.frame.minY - scroll.frame.minY, 10, accuracy: 3)
        XCTAssertEqual(tabs.frame.minY - summary.frame.maxY, 12, accuracy: 3)
        XCTAssertEqual(tabs.frame.width, app.frame.width - (app.frame.width <= 730 ? 8 : 20), accuracy: 2)
        XCTAssertEqual(tabs.frame.height, 45, accuracy: 2)
        let headerCredits = app.descendants(matching: .any)["chat-settings-credits"].firstMatch
        XCTAssertTrue(headerCredits.exists); XCTAssertEqual(headerCredits.value as? String, "37")
        let files = app.buttons["chat-settings-tab-files"]
        XCTAssertTrue(files.exists); XCTAssertTrue(files.isHittable); files.tap()
        let selected = NSPredicate(format: "isSelected == true")
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: selected, object: files)], timeout: 3) == .completed,
                      "The Files tap must activate its tab before reading metadata")
        let filename = app.staticTexts["audio-speak-openmates-welcome-message.mp3"]
        XCTAssertTrue(filename.waitForExistence(timeout: 3)); reveal(filename, in: app.scrollViews["chat-settings-scroll"])
        XCTAssertTrue(app.staticTexts["Audio | 4.6s | 73 KB"].exists)
        XCTAssertTrue(app.staticTexts["1 downloadable item"].exists)
        XCTAssertLessThanOrEqual(filename.frame.height, 26)
        let fileRow = app.buttons["chat-settings-file-row"]
        XCTAssertLessThanOrEqual(fileRow.frame.height, 56)
        let fileIcon = app.images["chat-settings-file-icon-463ace0f-02f9-43c2-94ee-cf385162bb75"]
        XCTAssertTrue(fileIcon.exists); XCTAssertEqual(fileIcon.label, "audio")
        XCTAssertTrue(app.buttons["chat-settings-download-files"].isEnabled)
        XCTAssertTrue(app.buttons["chat-settings-tab-share"].exists)
        attach(app, "Chat Settings public audio Files metadata")
        reveal(usage, in: app.scrollViews["chat-settings-scroll"]); usage.tap()
        XCTAssertFalse(app.buttons["chat-settings-tab-tasks"].exists)
        XCTAssertFalse(app.buttons["chat-settings-tab-plan"].exists)
        let total = app.descendants(matching: .any)["chat-settings-usage-total"].firstMatch
        XCTAssertTrue(total.waitForExistence(timeout: 3)); reveal(total, in: app.scrollViews["chat-settings-scroll"])
        XCTAssertEqual(total.value as? String, "37")
        XCTAssertTrue(app.staticTexts["audio | speak"].exists)
        let audioIcon = app.images.matching(NSPredicate(format: "identifier BEGINSWITH %@ AND label == %@", "chat-settings-usage-icon-", "audio")).firstMatch
        XCTAssertTrue(audioIcon.exists)
        attach(app, "Chat Settings public static Usage")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testPublicAudioDownloadSavesNativeMP3WithExactFilenameAndByteCount() {
        let app = launch("chat-settings-public")
        let files = app.buttons["chat-settings-tab-files"]
        XCTAssertTrue(files.waitForExistence(timeout: 15)); XCTAssertTrue(files.isHittable); files.tap()
        let selected = NSPredicate(format: "isSelected == true")
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: selected, object: files)], timeout: 3) == .completed,
                      "The Files tap must activate its tab before accessing downloads")
        let filename = "audio-speak-openmates-welcome-message.mp3"
        let file = app.buttons["chat-settings-file-row"]
        XCTAssertTrue(file.waitForExistence(timeout: 3))
        XCTAssertTrue(file.label.contains(filename))
        reveal(file, in: app.scrollViews["chat-settings-scroll"]); file.tap()
        let page = app.descendants(matching: .any)["chat-settings-page"].firstMatch
        let exportStarted = NSPredicate(format: "value MATCHES %@", "export=(downloading|presenting|failed)")
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: exportStarted, object: page)], timeout: 3) == .completed,
                      "The file action must start its download before waiting for the exporter")
        let save = app.buttons["Save"].firstMatch
        let pickerAppeared = save.waitForExistence(timeout: 30)
        attach(app, "Public MP3 native exporter after actual download")
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "Public MP3 exporter hierarchy"; hierarchy.lifetime = .keepAlways; add(hierarchy)
        XCTAssertTrue(pickerAppeared, "Actual public audio download must open the native Save picker; phase=\(page.value as? String ?? "unavailable")")
        guard pickerAppeared else { return }
        XCTAssertTrue(save.isHittable); save.tap()
        // iOS26's destination picker has Save and no editable filename field.
        // Verify the actual completed file, not an assumed picker text field.
        let saved = NSPredicate(format: "value CONTAINS %@ AND value CONTAINS %@", "saved=\(filename);", "bytes=74440")
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: saved, object: page)], timeout: 15) == .completed,
                      "The written MP3 must retain its exact filename and downloaded byte count")
        XCTAssertTrue(save.waitForNonExistence(timeout: 3))
        XCTAssertTrue(files.isHittable)
        attach(app, "Public MP3 actual saved file receipt")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testNativeJSONExportControlSavesExpectedFilenameAndByteCount() {
        let app = launch("chat-settings-export-control")
        let open = app.buttons["native-export-control-open"]
        XCTAssertTrue(open.waitForExistence(timeout: 15)); open.tap()
        let started = NSPredicate(format: "value == %@ OR value BEGINSWITH %@", "presenting", "saved=")
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: started, object: open)], timeout: 3) == .completed,
                      "The isolated button must receive its tap before waiting for Files")
        let save = app.buttons["Save"].firstMatch
        let pickerAppeared = save.waitForExistence(timeout: 30)
        attach(app, "Isolated native JSON exporter control")
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "Isolated native JSON exporter hierarchy"; hierarchy.lifetime = .keepAlways; add(hierarchy)
        XCTAssertTrue(pickerAppeared, "The isolated JSON control must expose a writable export destination")
        guard pickerAppeared else { return }
        XCTAssertTrue(save.isHittable); save.tap()
        let saved = NSPredicate(format: "value == %@", "saved=parity-export-control.json;bytes=35")
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: saved, object: open)], timeout: 15) == .completed)
        XCTAssertTrue(save.waitForNonExistence(timeout: 3)); XCTAssertTrue(open.isHittable)
        attach(app, "Isolated native JSON actual saved file receipt")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testAllEightActivePlansRemainVisibleAndReachable() {
        let app = launch("chat-settings-plans")
        let finalPlan = app.staticTexts["Launch plan 8"]
        XCTAssertTrue(finalPlan.waitForExistence(timeout: 15))
        let titles = ["Prepare the launch"] + (2...8).map { "Launch plan \($0)" }
        for title in titles {
            let renderedTitle = app.staticTexts.matching(NSPredicate(format: "label == %@", title))
            XCTAssertEqual(renderedTitle.count, 1, "Expected exactly one rendered title for \(title)")
        }
        reveal(finalPlan, in: app.scrollViews["chat-settings-scroll"])
        if app.frame.width <= 730 {
            let header = app.descendants(matching: .any)["chat-settings-header"].firstMatch
            XCTAssertTrue(header.exists)
            // The header AX frame includes the status safe area; web height
            // measures content beginning at the Back button's top edge.
            let contentHeight = header.frame.maxY - app.buttons["banner-back-button"].frame.minY
            XCTAssertEqual(contentHeight, 88, accuracy: 3)
            XCTAssertTrue(finalPlan.isHittable)
        }
        attach(app, "Chat Settings eighth active plan")
    }
    private func reveal(_ element: XCUIElement, in scroll: XCUIElement) {
        for _ in 0..<6 where !element.isHittable {
            if element.exists && element.frame.maxY < scroll.frame.minY { scroll.swipeDown() }
            else { scroll.swipeUp() }
        }
        XCTAssertTrue(element.isHittable, "Expected the control to be visible after scrolling")
        XCTAssertTrue(scroll.frame.intersects(element.frame))
    }
    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", variant, "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch(); return app
    }
    private func attach(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
