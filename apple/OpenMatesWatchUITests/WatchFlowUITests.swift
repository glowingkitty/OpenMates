// Network-free simulator coverage for the Watch's iPhone-first pairing and
// read-only Tasks/Workflows concept. Uses production views with seeded data.

import XCTest
import CoreGraphics
import ImageIO

final class WatchFlowUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testPairInitiationFailureOffersSelfHostedServerBeforeAnyTokenExists() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-initiation-failed"]
        app.launch()
        let selfHost = app.buttons["watch-pair-self-host-button"]
        XCTAssertTrue(selfHost.waitForExistence(timeout: 12))
        XCTAssertTrue(selfHost.isHittable)
        XCTAssertTrue(app.buttons["watch-pair-refresh-button"].isHittable)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        XCTAssertFalse(app.textFields["watch-pair-pin-input"].exists)
        selfHost.tap()
        XCTAssertTrue(app.staticTexts["watch-pair-self-host-prompt"].waitForExistence(timeout: 5))
        assertBottomKeyboardTray(app.buttons["watch-pair-self-host-keyboard"], in: app)
        XCTAssertFalse(app.buttons["watch-pair-refresh-button"].exists)
        keepScreenshot("Watch server recovery before pair initiation")
        app.buttons["watch-pair-back-button"].tap()
        XCTAssertTrue(selfHost.waitForExistence(timeout: 5))
        XCTAssertTrue(selfHost.isHittable)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testSelfHostedInitiationFailureOffersCloudRecoveryWithoutPairURL() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-selfhost-initiation-failed"]
        app.launch()
        let cloud = app.buttons["watch-pair-use-production-button"]
        XCTAssertTrue(cloud.waitForExistence(timeout: 12))
        XCTAssertTrue(cloud.isHittable)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        cloud.tap()
        let selfHost = app.buttons["watch-pair-self-host-button"]
        XCTAssertTrue(selfHost.waitForExistence(timeout: 5))
        XCTAssertTrue(selfHost.isHittable)
        XCTAssertTrue(app.buttons["watch-pair-refresh-button"].exists)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        keepScreenshot("Watch custom server failure offers Cloud recovery")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testPairingStartsWithIPhoneApprovalAndRevealsShortURL() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-waiting"]
        app.launch()

        XCTAssertTrue(app.staticTexts["watch-pair-confirm-iphone-title"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.buttons["watch-pair-login-without-iphone-button"].exists)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        keepScreenshot("Watch iPhone-first pairing")

        app.buttons["watch-pair-login-without-iphone-button"].tap()
        let shortURL = app.staticTexts["watch-pair-url"]
        XCTAssertTrue(shortURL.waitForExistence(timeout: 5))
        XCTAssertEqual(shortURL.label.replacingOccurrences(of: "\n", with: ""), "openmates.org/#pair=WATCH42")
        XCTAssertFalse(app.buttons["watch-pair-show-qr-button"].exists)
        keepScreenshot("Watch Cloud short URL pairing")

        app.buttons["watch-pair-self-host-button"].tap()
        XCTAssertTrue(app.staticTexts["watch-pair-self-host-prompt"].waitForExistence(timeout: 5))
        assertBottomKeyboardTray(app.buttons["watch-pair-self-host-keyboard"], in: app)
        keepScreenshot("Watch self-host domain entry")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testSelfHostedShortURLUsesItsDomainAndOffersCloud() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-selfhost-short-url"]
        app.launch()

        let shortURL = app.staticTexts["watch-pair-url"]
        XCTAssertTrue(shortURL.waitForExistence(timeout: 12))
        XCTAssertEqual(shortURL.label.replacingOccurrences(of: "\n", with: ""), "mydomain.org/#pair=WATCH42")
        XCTAssertTrue(app.buttons["watch-pair-use-production-button"].exists)
        XCTAssertFalse(app.buttons["watch-pair-show-qr-button"].exists)
        keepScreenshot("Watch self-host short URL pairing")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testApprovedPairingShowsCodeEntry() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-code-entry"]
        app.launch()

        XCTAssertTrue(app.staticTexts["watch-pair-code-prompt"].waitForExistence(timeout: 12))
        assertBottomKeyboardTray(app.buttons["watch-pair-pin-keyboard"], in: app)
        XCTAssertFalse(app.buttons["watch-pair-show-qr-button"].exists)
        keepScreenshot("Watch pair code entry")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.hub.compact-navigation,apple-watch.lists.read-only-private,apple-watch.handoff.exact-private
    func testHubShowsTaskAndWorkflowRowsAndRequestsExactItem() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-hub-lists"]
        app.launch()

        XCTAssertTrue(app.buttons["watch-hub-select-chat"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.buttons["watch-hub-select-tasks"].exists)
        XCTAssertTrue(app.buttons["watch-hub-select-workflows"].exists)
        keepScreenshot("Watch Chat Tasks Workflows selector")

        app.buttons["watch-hub-select-tasks"].tap()
        let board = app.otherElements["watch-task-board"]
        XCTAssertTrue(app.buttons["watch-task-row-backlog-0"].waitForExistence(timeout: 5))
        let sectionSelector = app.buttons["watch-hub-section-selector"]
        // Swipe through the same five status pages as iPhone. Vertical scroll
        // must leave the active page intact and keep the section header fixed.
        let backlog = app.scrollViews["watch-task-column-backlog"]
        let lastBacklogTask = app.buttons["watch-task-row-backlog-11"]
        for _ in 0..<8 where !lastBacklogTask.isHittable { backlog.swipeUp() }
        XCTAssertTrue(lastBacklogTask.isHittable)
        XCTAssertTrue(backlog.exists)
        XCTAssertTrue(sectionSelector.isHittable)
        board.swipeLeft()
        XCTAssertTrue(app.buttons["watch-task-row-task-two"].waitForExistence(timeout: 5))
        board.swipeLeft()
        let task = app.buttons["watch-task-row-task-one"]
        XCTAssertTrue(task.waitForExistence(timeout: 5))
        task.tap()
        XCTAssertTrue(app.staticTexts["watch-task-detail-title"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["watch-task-detail-description"].label,
                       "Compare motors that safely carry two people.")
        let detail = app.scrollViews["watch-task-detail-scroll"]
        detail.swipeUp()
        XCTAssertTrue(app.staticTexts["watch-task-detail-context"].exists)
        detail.swipeUp()
        XCTAssertTrue(app.staticTexts["watch-task-detail-progress"].exists)
        let openOnPhone = app.buttons["watch-task-detail-open-on-phone"]
        for _ in 0..<3 where !openOnPhone.isHittable { detail.swipeUp() }
        XCTAssertTrue(openOnPhone.isHittable)
        XCTAssertFalse(app.staticTexts["watch-ui-test-open-request"].exists)
        openOnPhone.tap()
        let openedItem = app.staticTexts["watch-ui-test-open-request"]
        XCTAssertTrue(openedItem.waitForExistence(timeout: 3))
        XCTAssertEqual(openedItem.label, "task:task-one")
        keepScreenshot("Watch read-only Task details")
        app.buttons["watch-task-detail-back"].tap()
        XCTAssertTrue(task.waitForExistence(timeout: 5))
        board.swipeLeft()
        let blocked = app.buttons["watch-task-row-task-blocked"]
        XCTAssertTrue(blocked.waitForExistence(timeout: 5))
        blocked.tap()
        XCTAssertTrue(app.staticTexts["watch-task-detail-blocked-reason"].waitForExistence(timeout: 5))
        app.buttons["watch-task-detail-back"].tap()
        board.swipeLeft()
        XCTAssertTrue(app.buttons["watch-task-row-task-done"].waitForExistence(timeout: 5))
        board.swipeRight()
        XCTAssertTrue(blocked.waitForExistence(timeout: 5))
        keepScreenshot("Watch separate Blocked Kanban page")

        sectionSelector.tap()
        XCTAssertTrue(app.buttons["watch-hub-select-chat"].waitForExistence(timeout: 3))
        keepScreenshot("Watch section menu reopened above Tasks")
        app.buttons["watch-hub-select-workflows"].tap()
        let workflow = app.buttons["watch-workflow-row-workflow-one"]
        XCTAssertTrue(workflow.waitForExistence(timeout: 5))
        keepScreenshot("Watch read-only Workflows list")
        workflow.tap()
        XCTAssertTrue(app.staticTexts["watch-workflow-detail-title"].waitForExistence(timeout: 5))
        XCTAssertEqual(openedItem.label, "task:task-one", "Opening details must not immediately hand off to iPhone.")
        let workflowDetail = app.scrollViews["watch-workflow-detail-scroll"]
        let workflowOnPhone = app.buttons["watch-workflow-detail-open-on-phone"]
        for _ in 0..<8 where !workflowOnPhone.isHittable { workflowDetail.swipeUp() }
        XCTAssertTrue(workflowOnPhone.isHittable)
        workflowOnPhone.tap()
        XCTAssertEqual(openedItem.label, "workflow:workflow-one")
        app.buttons["watch-workflow-detail-back"].tap()
        XCTAssertTrue(workflow.waitForExistence(timeout: 5))

        sectionSelector.tap()
        let chatOption = app.buttons["watch-hub-select-chat"]
        XCTAssertTrue(chatOption.waitForExistence(timeout: 3))
        chatOption.tap()
        let chatsHeading = app.buttons["watch-chats-heading"]
        XCTAssertTrue(chatsHeading.waitForExistence(timeout: 5))
        app.swipeUp()
        XCTAssertTrue(chatsHeading.isHittable)
        chatsHeading.tap()
        XCTAssertTrue(app.buttons["watch-hub-select-tasks"].waitForExistence(timeout: 3))
        keepScreenshot("Watch fixed Chats header and reopened menu")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.lists.read-only-private,apple-watch.hub.compact-navigation
    func testDigitalCrownScrollsActiveKanbanColumnWithoutChangingPage() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-hub-lists"]
        app.launch()
        let tasksOption = app.buttons["watch-hub-select-tasks"]
        XCTAssertTrue(tasksOption.waitForExistence(timeout: 12))
        tasksOption.tap()

        let firstTask = app.buttons["watch-task-row-backlog-0"]
        let lastTask = app.buttons["watch-task-row-backlog-11"]
        let todoTask = app.buttons["watch-task-row-task-two"]
        let backlog = app.scrollViews["watch-task-column-backlog"]
        let sectionSelector = app.buttons["watch-hub-section-selector"]
        XCTAssertTrue(firstTask.waitForExistence(timeout: 5))
        XCTAssertTrue(firstTask.isHittable)
        XCTAssertFalse(lastTask.isHittable)
        let headerY = sectionSelector.frame.minY
        let firstTaskY = firstTask.frame.minY
        keepScreenshot("Watch Backlog before Crown input")

        // Public Watch XCTest Crown API: -1 is one full downward rotation.
        // Crown input alone must reveal the last row in this long column.
        for _ in 0..<12 where !lastTask.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: -1)
            XCTAssertTrue(backlog.exists)
            XCTAssertFalse(todoTask.isHittable)
            XCTAssertTrue(sectionSelector.isHittable)
            XCTAssertEqual(sectionSelector.frame.minY, headerY, accuracy: 0.5)
        }
        keepScreenshot("Watch Backlog after downward Crown input")
        let layout = XCTAttachment(string: app.debugDescription)
        layout.name = "Synthetic Watch Crown layout after downward rotations"
        layout.lifetime = .keepAlways
        add(layout)
        XCTAssertTrue(lastTask.isHittable,
                      "Crown did not reveal the final task; first row y before=\(firstTaskY), after=\(firstTask.frame.minY)")
        XCTAssertFalse(firstTask.isHittable)
        keepScreenshot("Watch Crown scrolled Backlog to final task")

        // Positive rotations scroll upward; they must preserve the same page.
        for _ in 0..<12 where !firstTask.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: 1)
            XCTAssertTrue(backlog.exists)
            XCTAssertFalse(todoTask.isHittable)
            XCTAssertTrue(sectionSelector.isHittable)
            XCTAssertEqual(sectionSelector.frame.minY, headerY, accuracy: 0.5)
        }
        XCTAssertTrue(firstTask.isHittable)
        XCTAssertFalse(lastTask.isHittable)
        keepScreenshot("Watch Crown returned Backlog to first task")

        app.otherElements["watch-task-board"].swipeLeft()
        XCTAssertTrue(todoTask.waitForExistence(timeout: 5))
        XCTAssertTrue(todoTask.isHittable)
        XCTAssertTrue(sectionSelector.isHittable)
        keepScreenshot("Watch horizontal paging after Crown scrolling")
    }

    @MainActor
    // Standalone synthetic ScrollView diagnoses simulator Crown delivery, without a product route.
    // contract-test: tooling
    func testDigitalCrownNativeScrollControl() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-native-crown"]
        app.launch()
        let firstRow = app.staticTexts["watch-native-crown-row-0"]
        let lastRow = app.staticTexts["watch-native-crown-row-11"]
        XCTAssertTrue(firstRow.waitForExistence(timeout: 12))
        XCTAssertTrue(firstRow.isHittable)
        XCTAssertFalse(lastRow.isHittable)
        let initialY = firstRow.frame.minY
        keepScreenshot("Native Watch ScrollView before Crown diagnostic")
        for _ in 0..<12 where !lastRow.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: -1)
        }
        keepScreenshot("Native Watch ScrollView after Crown diagnostic")
        let layout = XCTAttachment(string: app.debugDescription)
        layout.name = "Synthetic standalone native Crown layout"
        layout.lifetime = .keepAlways
        add(layout)
        XCTAssertTrue(lastRow.isHittable,
                      "Native ScrollView Crown delivery failed; first row y before=\(initialY), after=\(firstRow.frame.minY)")
        XCTAssertFalse(firstRow.isHittable)
        for _ in 0..<12 where !firstRow.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: 1)
        }
        XCTAssertTrue(firstRow.isHittable)
        XCTAssertFalse(lastRow.isHittable)
    }

    @MainActor
    // contract-test: tooling
    func testFocusedDigitalCrownBindingReceivesNativeInput() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-crown-binding"]
        app.launch()
        let focus = app.staticTexts["watch-crown-binding-focus"]
        XCTAssertTrue(focus.waitForExistence(timeout: 12))
        expectation(for: NSPredicate(format: "label == 'true'"), evaluatedWith: focus)
        waitForExpectations(timeout: 5)
        let events = app.staticTexts["watch-crown-binding-events"]
        let rotation = app.staticTexts["watch-crown-binding-rotation"]
        let initialRotation = rotation.label
        XCTAssertEqual(events.label, "0")
        XCUIDevice.shared.rotateDigitalCrown(delta: -0.25)
        expectation(for: NSPredicate(format: "label != '0'"), evaluatedWith: events)
        waitForExpectations(timeout: 5)
        keepScreenshot("Focused native Crown binding after input")
        let layout = XCTAttachment(string: app.debugDescription)
        layout.name = "Focused Crown binding delivery diagnostic"
        layout.lifetime = .keepAlways
        add(layout)
        XCTAssertGreaterThan(Int(events.label) ?? 0, 0)
        XCTAssertNotEqual(rotation.label, initialRotation)
        XCTAssertEqual(focus.label, "true")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.embeds.read-only-fullscreen
    func testRecordedAudioPlaysFromMemoryInPreviewAndFullscreen() {
        assertRecordedAudioPlayback(processing: false)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.embeds.read-only-fullscreen
    func testProcessingRecordedAudioCanPlayAndOpenFullscreen() {
        assertRecordedAudioPlayback(processing: true)
    }

    @MainActor
    private func assertRecordedAudioPlayback(processing: Bool) {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-embed-family", "audioRecording", "--ui-test-watch-local-audio"]
        if processing { app.launchArguments.append("--ui-test-watch-audio-processing") }
        app.launch()
        let preview = app.buttons["watch-embed-preview-audioRecording"]
        XCTAssertTrue(preview.waitForExistence(timeout: 12))
        let play = app.buttons["watch-audio-preview-playback"]
        revealRecordingElement(play, in: app)
        if !play.exists || !play.isHittable {
            keepScreenshot(processing ? "Processing recording before missing preview playback assertion" : "Ready recording before missing preview playback assertion")
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Synthetic Watch recording playback AX hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
        XCTAssertTrue(play.isHittable)
        let visual = app.descendants(matching: .any)["watch-embed-visual-canvas-watch-mobile-preview"].firstMatch
        let title = app.staticTexts["watch-embed-title-watch-mobile-preview"]
        XCTAssertTrue(visual.exists)
        XCTAssertTrue(title.exists)
        XCTAssertLessThanOrEqual(play.frame.maxY, visual.frame.maxY, "Playback stays inside the visual")
        XCTAssertLessThanOrEqual(play.frame.maxY, title.frame.minY, "Playback must not cover recording metadata")
        XCTAssertFalse(app.staticTexts["watch-embed-fullscreen-unavailable"].exists)
        assertDarkRecordingSurface(visual, in: app)
        keepScreenshot(processing ? "Processing Watch recording permits local playback" : "Dark Watch recording with native local playback control")
        play.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "playing"), object: play)], timeout: 3), .completed, "AVAudioPlayer must actually start")
        play.tap()
        XCTAssertEqual(play.value as? String, "stopped")
        openRecordingThroughVisibleCard(in: app)
        let full = app.buttons["watch-audio-fullscreen-playback"]
        XCTAssertTrue(full.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["watch-embed-fullscreen-unavailable"].exists)
        XCTAssertFalse(app.staticTexts["watch-audio-fullscreen-metadata-unavailable"].exists)
        let close = app.buttons["watch-embed-continuation-close"]
        XCTAssertFalse(full.frame.intersects(close.frame), "Fullscreen playback must remain clear of the pinned close button's hit target")
        full.tap()
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "playing"), object: full)], timeout: 3) == .completed)
        keepScreenshot(processing ? "Processing Watch recording fullscreen plays actual WAV" : "Watch fullscreen recording playing actual synthetic WAV")
        app.buttons["watch-embed-continuation-close"].tap()
        XCTAssertTrue(play.waitForExistence(timeout: 5))
        XCTAssertEqual(play.value as? String, "stopped", "Closing fullscreen releases its player")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.embeds.read-only-fullscreen
    func testLegacyRecordingWithoutFileMetadataOffersPreciseUnavailableState() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-embed-family", "audioRecording"]
        app.launch()
        let preview = app.buttons["watch-embed-preview-audioRecording"]
        XCTAssertTrue(preview.waitForExistence(timeout: 12))
        openRecordingThroughVisibleCard(in: app)
        XCTAssertTrue(app.staticTexts["watch-audio-fullscreen-metadata-unavailable"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["watch-embed-fullscreen-unavailable"].exists)
        XCTAssertFalse(app.buttons["watch-audio-fullscreen-playback"].exists)
        XCTAssertTrue(app.buttons["watch-embed-open-device"].exists)
        keepScreenshot("Legacy recording preserves transcript and explains missing audio metadata")
    }

    @MainActor
    private func recordingViewport(in app: XCUIApplication) -> CGRect {
        var frame = app.scrollViews["watch-chat-shell"].frame.intersection(app.frame)
        let header = app.descendants(matching: .any)["watch-chat-thread"].firstMatch
        // Pinned header/back and fixed composer can obscure descendants
        // which XCUI nevertheless calls hittable.
        if header.exists {
            let top = max(frame.minY, header.frame.maxY)
            frame = CGRect(x: frame.minX, y: top, width: frame.width, height: max(0, frame.maxY - top))
        }
        let composer = app.textFields["watch-message-input"]
        if composer.exists { frame.size.height = max(0, min(frame.maxY, composer.frame.minY) - frame.minY) }
        return frame.insetBy(dx: 2, dy: 2)
    }

    @MainActor
    private func revealRecordingElement(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<16 {
            guard element.exists else { return }
            let viewport = recordingViewport(in: app)
            if viewport.contains(element.frame) { return }
            // Scroll with the native Crown away from sibling playback actions.
            // Compare edges, not centers: a center can be visible while the
            // bottom is still covered. Small steps avoid overshooting the narrow
            // fully visible interval between the pinned header and composer.
            if element.frame.maxY > viewport.maxY {
                XCUIDevice.shared.rotateDigitalCrown(delta: -0.05)
            } else if element.frame.minY < viewport.minY {
                XCUIDevice.shared.rotateDigitalCrown(delta: 0.05)
            } else { return }
        }
    }

    @MainActor
    private func openRecordingThroughVisibleCard(in app: XCUIApplication) {
        let preview = app.buttons["watch-embed-preview-audioRecording"]
        let visible = preview.frame.intersection(recordingViewport(in: app))
        let playback = app.buttons["watch-audio-preview-playback"]
        let candidates = [
            CGPoint(x: visible.maxX - 8, y: visible.minY + 8),
            CGPoint(x: visible.minX + 8, y: visible.minY + 8),
            CGPoint(x: visible.minX + 8, y: visible.maxY - 8),
        ]
        let point = candidates.first { visible.contains($0) && (!playback.exists || !playback.frame.contains($0)) }
        if visible.isNull || visible.width < 16 || visible.height < 16 || point == nil {
            keepScreenshot("Recording open action before visible card assertion")
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Synthetic recording visible open-action AX hierarchy"; hierarchy.lifetime = .keepAlways; add(hierarchy)
        }
        XCTAssertTrue(preview.exists)
        XCTAssertFalse(visible.isNull)
        XCTAssertGreaterThanOrEqual(visible.width, 16)
        XCTAssertGreaterThanOrEqual(visible.height, 16)
        guard let point else { return XCTFail("No visible recording card area outside playback") }
        // Open the actual native Button through its visible card area. Its AX
        // center and the lower app bar can be beneath the fixed composer.
        app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: point.x - app.frame.minX, dy: point.y - app.frame.minY)).tap()
    }

    @MainActor
    private func assertDarkRecordingSurface(_ visual: XCUIElement, in app: XCUIApplication) {
        let image = app.screenshot().image
        guard let cgImage = image.cgImage else { return XCTFail("Missing Watch screenshot") }
        // Crop first, then sample all pixels in that small crop. A full-image
        // CGContext Y flip previously sampled an unrelated black region and
        // allowed the visibly white recording card to pass.
        let point = CGPoint(x: visual.frame.minX + 6, y: visual.frame.minY + 20)
        let transcript = app.scrollViews["watch-chat-shell"].frame
        XCTAssertTrue(transcript.contains(point), "Dark surface sample must be inside the visible visual")
        XCTAssertTrue(app.frame.contains(point))
        let scaleX = CGFloat(cgImage.width) / app.frame.width
        let scaleY = CGFloat(cgImage.height) / app.frame.height
        let cropRect = CGRect(x: (point.x - app.frame.minX) * scaleX,
                              y: (point.y - app.frame.minY) * scaleY, width: 3, height: 3).integral
        guard let crop = cgImage.cropping(to: cropRect) else { return XCTFail("Missing recording surface crop") }
        let png = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(png, "public.png" as CFString, 1, nil) else {
            return XCTFail("Cannot encode actual recording surface crop")
        }
        CGImageDestinationAddImage(destination, crop, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let evidence = XCTAttachment(data: png as Data, uniformTypeIdentifier: "public.png")
        evidence.name = "Actual visible recording surface pixels"; evidence.lifetime = .keepAlways; add(evidence)
        var rgba = [UInt8](repeating: 0, count: crop.width * crop.height * 4)
        let rendered = rgba.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(data: bytes.baseAddress, width: crop.width, height: crop.height,
                bitsPerComponent: 8, bytesPerRow: crop.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.draw(crop, in: CGRect(x: 0, y: 0, width: crop.width, height: crop.height)); return true
        }
        XCTAssertTrue(rendered)
        guard rendered else { return }
        for offset in stride(from: 0, to: rgba.count, by: 4) {
            XCTAssertLessThan(max(rgba[offset], rgba[offset + 1], rgba[offset + 2]), 160,
                              "Actual recording canvas must be dark, never a white fallback")
        }
    }

    @MainActor
    private func keepScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    private func assertBottomKeyboardTray(_ tray: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(tray.waitForExistence(timeout: 5))
        XCTAssertTrue(tray.isHittable)
        XCTAssertGreaterThan(tray.frame.maxY, app.frame.maxY - 16)
        XCTAssertGreaterThan(tray.frame.width, app.frame.width * 0.85)

        // XCUI can report a hittable frame even when SwiftUI paints the tray
        // below the visible Watch viewport. Sample a quiet part of its grey
        // background near the physical bottom of the screenshot.
        guard let screenshot = XCUIScreen.main.screenshot().image.cgImage else {
            XCTFail("Could not decode Watch screenshot")
            return
        }
        let width = screenshot.width
        let height = screenshot.height
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        let rendered = rgba.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(
                data: buffer.baseAddress,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ) else { return false }
            context.draw(screenshot, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        XCTAssertTrue(rendered)
        guard rendered else { return }
        let x = width * 7 / 10
        let bottomInset = min(40, height / 8)
        let nearBottom = (height - bottomInset) * width * 4 + x * 4
        let nearTop = bottomInset * width * 4 + x * 4
        let trayBrightness = max(rgba[nearBottom], rgba[nearTop])
        XCTAssertGreaterThan(trayBrightness, 35, "Keyboard tray has no visible grey pixels at the Watch bottom")
    }
}
