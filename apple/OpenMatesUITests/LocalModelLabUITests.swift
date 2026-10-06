// Native-only local model lab navigation and privacy/scope controls.
// These tests never download production weights or claim actual inference/model quality.
import XCTest

@MainActor
final class LocalModelLabUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.composition.canonical-and-accessible,apple-local-model-lab.optional-downloads,apple-local-model-lab.isolated-scope,apple-local-model-lab.availability
    func testLabOpensFromDevelopersWithExplicitLocalOnlyScope() throws {
        let app = try openLab()
        XCTAssertTrue(try settingsPane(in: app).descendants(matching: .any)["local-model-lab-local-only"].exists)
        XCTAssertTrue(try settingsPane(in: app).descendants(matching: .any)["local-model-lab-production-scope"].exists)
        XCTAssertFalse(app.webViews.firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists)
        XCTAssertFalse(try settingsPane(in: app).descendants(matching: .any)["local-model-privacyFilter-card"].exists,
                       "Enhanced PII downloads belong exclusively to Privacy")
        for id in ["whisper"] {
            let card = try settingsPane(in: app).descendants(matching: .any)["local-model-\(id)-card"]
            try scrollTo(card, in: app, actionable: false)
            XCTAssertTrue(card.exists, id)
            let download = try settingsPane(in: app).buttons["local-model-\(id)-download"]
            // Availability is asserted below, so expose the download control
            // without requiring it to be tappable before that assertion.
            print("Before availability scroll: " + targetDiagnostics(download, in: app))
            try scrollTo(download, in: app, actionable: false)
            print("After availability scroll: " + targetDiagnostics(download, in: app))
            XCTAssertTrue(download.exists, "A clean test container must offer the optional \(id) download")
            #if arch(arm64)
            let hardwareSupported = true
            #else
            let hardwareSupported = false
            #endif
            let supported = hardwareSupported
            if download.isEnabled != supported || (supported && !download.isHittable) {
                captureLabFailure(in: app, context: targetDiagnostics(download, in: app))
            }
            XCTAssertEqual(download.isEnabled, supported, "Unsupported runtimes must be blocked before downloading")
            if supported {
                XCTAssertTrue(download.isHittable)
                XCTAssertFalse(try settingsPane(in: app).descendants(matching: .any)["local-model-\(id)-unavailable"].exists,
                               "The supported arm64 runtime must not show an unavailable reason")
            } else {
                let warning = try settingsPane(in: app).descendants(matching: .any)["local-model-\(id)-unavailable"]
                try scrollTo(warning, in: app)
                XCTAssertTrue(warning.exists)
                XCTAssertTrue(warning.isHittable, "The reason must be visible before installing assets")
            }
            XCTAssertFalse(try settingsPane(in: app).buttons["local-model-\(id)-run"].exists,
                           "Tests must remain unavailable before assets are installed")
        }
        XCTAssertFalse(try settingsPane(in: app).descendants(matching: .any)["local-model-kokoro-card"].exists,
                       "The removed unsafe adapter must not leave an unavailable card")
        XCTAssertFalse(try settingsPane(in: app).descendants(matching: .any)["local-model-lab-system-speech-card"].exists)
        let privacy = try settingsPane(in: app).descendants(matching: .any)["local-model-lab-privacy"]
        try scrollTo(privacy, in: app, actionable: false)
        XCTAssertTrue(privacy.exists)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Local model lab optional downloads and ephemeral input policy"
        attachment.lifetime = .keepAlways
        add(attachment)
        try settingsPane(in: app).descendants(matching: .any)["settings-developers-back"].firstMatch.tap()
        XCTAssertTrue(try settingsPane(in: app).descendants(matching: .any)["settings-developers-local-models-row"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.availability,apple-local-model-lab.isolated-scope
    func testRejectedSpeechAdaptersHaveNoLabControlsOrFallback() throws {
        let app = try openLab()
        let pane = try settingsPane(in: app)
        XCTAssertTrue(pane.descendants(matching: .any)["local-model-whisper-card"].exists)
        for removed in ["pocketTTS", "appleSpeech", "kokoro"] {
            XCTAssertFalse(pane.descendants(matching: .any)["local-model-\(removed)-card"].exists)
            XCTAssertFalse(pane.buttons["local-model-\(removed)-download"].exists)
            XCTAssertFalse(pane.buttons["local-model-\(removed)-run"].exists)
        }
        XCTAssertFalse(pane.descendants(matching: .any)["local-model-lab-system-speech-card"].exists)
        XCTAssertFalse(pane.descendants(matching: .any)["local-model-privacyFilter-card"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.isolated-scope
    func testLabSwitchCanBeChangedAndReturnedWithoutCloudOrBillingNavigation() throws {
        let app = try openLab()
        // OMToggle exposes the native Switch role through its toggle trait.
        let toggle = try NativeUITestElementResolution.requireVisible(
            try settingsPane(in: app).switches.matching(identifier: "local-model-lab-toggle"), in: app)
        XCTAssertTrue(toggle.isHittable)
        let before = try XCTUnwrap(toggle.value as? String)
        XCTAssertTrue(["On", "Off"].contains(before), "The real lab switch exposes its current state")
        let changed = before == "On" ? "Off" : "On"
        toggle.tap()
        let transitioned = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", changed), object: toggle)
        XCTAssertEqual(XCTWaiter.wait(for: [transitioned], timeout: 5), .completed)
        XCTAssertEqual(toggle.value as? String, changed)
        XCTAssertTrue(try settingsPane(in: app).descendants(matching: .any)["settings-local-models-page"].exists)
        XCTAssertFalse(try settingsPane(in: app).descendants(matching: .any)["settings-billing-page"].exists)
        toggle.tap()
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", before), object: toggle)
        XCTAssertEqual(XCTWaiter.wait(for: [restored], timeout: 5), .completed)
        XCTAssertEqual(toggle.value as? String, before)
    }

    #if os(iOS)
    // contract-test: direct surface=gui.apple assertions=apple-live-activities.download.progress,apple-live-activities.download.completion
    func testPrivacyDownloadRequestsNativeLiveActivityAndUpdatesAfterBackgrounding() throws {
        let app = try openLab(privacyDiagnostics: true, extraArguments: ["--ui-test-local-lab-progress-fixture", "--ui-test-local-lab-live-activity"])
        let remove = try settingsPane(in: app).buttons["local-model-privacyFilter-remove"]
        try scrollTo(remove, in: app)
        remove.tap()
        let download = try settingsPane(in: app).buttons["local-model-privacyFilter-download"]
        XCTAssertTrue(download.waitForExistence(timeout: 5))
        try scrollTo(download, in: app)
        XCTAssertTrue(download.isEnabled && download.isHittable)
        download.tap()
        let receipt = try settingsPane(in: app).staticTexts["local-model-privacyFilter-live-activity-receipt"]
        XCTAssertTrue(receipt.waitForExistence(timeout: 5))
        let requested = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "requests=1"), object: receipt)
        XCTAssertEqual(XCTWaiter.wait(for: [requested], timeout: 5), .completed,
                       "The store must successfully request native ActivityKit, without waiting for push/notification authorization")
        XCTAssertFalse(receipt.label.hasPrefix("ended"))
        XCUIDevice.shared.press(.home)
        XCTAssertTrue(app.wait(for: .runningBackground, timeout: 5))
        // A bounded background interval exercises updates while the process can
        // run; it makes no claim that local code runs during OS suspension.
        let interval = XCTestExpectation(description: "bounded background observation interval")
        XCTAssertEqual(XCTWaiter.wait(for: [interval], timeout: 4), .timedOut)
        app.activate()
        XCTAssertTrue(receipt.waitForExistence(timeout: 5))
        let updated = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label MATCHES %@",
            ".*requests=1;updates=[1-9][0-9]*;background=[1-9][0-9]*.*"), object: receipt)
        XCTAssertEqual(XCTWaiter.wait(for: [updated], timeout: 5), .completed,
                       "A real coordinator update must reach its native ActivityKit driver while backgrounded")
        let status = try settingsPane(in: app).staticTexts["local-model-privacyFilter-status"]
        try waitForStage("verification", on: status, timeout: 12)
        try waitForStage("ready", on: status, timeout: 12)
        let ended = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label BEGINSWITH %@", "ended;requests=1"), object: receipt)
        XCTAssertEqual(XCTWaiter.wait(for: [ended], timeout: 5), .completed,
                       "The verified install must end its activity")
    }
    #endif

    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testDownloadShowsAdvancingTransferAndSeparateVerification() throws {
        let app = try openLab(extraArguments: ["--ui-test-local-lab-progress-fixture"])
        let download = try settingsPane(in: app).buttons["local-model-whisper-download"]
        try scrollTo(download, in: app)
        XCTAssertTrue(download.isEnabled && download.isHittable)
        download.tap()
        let status = try settingsPane(in: app).staticTexts["local-model-whisper-status"]
        try waitForStage("transfer", on: status)
        let initialLabel = status.label
        let advances = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label != %@ AND label BEGINSWITH %@", initialLabel, "Downloading "), object: status)
        XCTAssertEqual(XCTWaiter.wait(for: [advances], timeout: 5), .completed,
                       "Download progress must advance before verification")
        try waitForStage("verification", on: status)
        XCTAssertTrue(status.isHittable, "Verification must be shown as a separate visible stage")
        let cancel = try settingsPane(in: app).buttons["local-model-whisper-cancel-download"]
        XCTAssertTrue(cancel.isEnabled && cancel.isHittable)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Local asset verification is separate from transfer"
        attachment.lifetime = .keepAlways
        add(attachment)
        try waitForStage("ready", on: status)
        XCTAssertFalse(cancel.exists)
        XCTAssertTrue(try settingsPane(in: app).buttons["local-model-whisper-remove"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads,apple-local-model-lab.local-execution,apple-local-model-lab.serialized-cancellation
    func testExistingDownloadCanBeCancelledDuringInferenceAndCleanupKeepsRunDisabled() throws {
        let app = try openLab(extraArguments: ["--ui-test-local-lab-progress-fixture", "--ui-test-local-lab-hold-download"])
        try enableLab(in: app)
        // Start the existing asset transfer before text input raises the
        // keyboard; the held fixture keeps it active throughout inference.
        let download = try settingsPane(in: app).buttons["local-model-whisper-download"]
        try scrollTo(download, in: app)
        XCTAssertTrue(download.isEnabled && download.isHittable)
        download.tap()
        let transfer = try settingsPane(in: app).staticTexts["local-model-whisper-status"]
        try waitForStage("transfer", on: transfer)
        // Transfers belong to the shared store and survive destination changes.
        try settingsPane(in: app).buttons["settings-destination-back"].tap()
        try openPrivacyDiagnostics(in: app)
        let input = try settingsPane(in: app).textFields["local-model-lab-privacy-input"]
        try scrollTo(input, in: app)
        XCTAssertTrue(input.isHittable)
        input.tap()
        input.typeText("Disposable local test input.")
        let run = try settingsPane(in: app).buttons["local-model-privacyFilter-run"]
        try scrollTo(run, in: app)
        XCTAssertTrue(run.isEnabled && run.isHittable)
        run.tap()
        let running = try settingsPane(in: app).staticTexts["local-model-lab-running"]
        try waitForStage("modelLoading", on: running)
        try waitForStage("inference", on: running, timeout: 12)
        XCTAssertFalse(run.isEnabled)
        let cancelDownload = try settingsPane(in: app).buttons["local-model-whisper-cancel-download"]
        try scrollTo(cancelDownload, in: app)
        XCTAssertTrue(cancelDownload.isEnabled && cancelDownload.isHittable,
                      "An existing download must stay cancellable during another model's inference")
        cancelDownload.tap()
        try waitForStage("notDownloaded", on: transfer)
        try scrollTo(running, in: app)
        XCTAssertTrue(running.label.hasPrefix("Detecting personal data"), "Cancelling assets must not cancel independent inference")
        let cancelRun = try settingsPane(in: app).buttons["local-model-lab-cancel-run"]
        try scrollTo(cancelRun, in: app)
        XCTAssertTrue(cancelRun.isEnabled && cancelRun.isHittable)
        cancelRun.tap()
        try waitForStage("cleanup", on: running)
        XCTAssertFalse(run.isEnabled, "A native operation keeps ownership until resources unload")
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: run)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 12), .completed)
        XCTAssertFalse(try settingsPane(in: app).descendants(matching: .any)["local-model-lab-pii-highlighted-text"].exists,
                       "Cancellation must suppress late success output")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testInterruptedPrivacyDownloadShowsWaitingRetryAndResumesProgress() throws {
        let app = try openLab(privacyDiagnostics: true, extraArguments: ["--ui-test-local-lab-progress-fixture", "--ui-test-local-lab-interrupted-download"])
        let status = try settingsPane(in: app).staticTexts["local-model-privacyFilter-status"]
        try scrollTo(status, in: app)
        try waitForStage("ready", on: status)
        let remove = try settingsPane(in: app).buttons["local-model-privacyFilter-remove"]
        try scrollTo(remove, in: app)
        XCTAssertTrue(remove.isEnabled && remove.isHittable)
        remove.tap()
        try waitForStage("notDownloaded", on: status)
        let download = try settingsPane(in: app).buttons["local-model-privacyFilter-download"]
        XCTAssertTrue(download.isEnabled && download.isHittable)
        download.tap()
        try waitForStage("waitingForConnection", on: status)
        XCTAssertTrue(status.label.contains("50%"), "Waiting must retain already transferred progress")
        XCTAssertTrue(status.isHittable)
        let cancel = try settingsPane(in: app).buttons["local-model-privacyFilter-cancel-download"]
        XCTAssertTrue(cancel.isEnabled && cancel.isHittable)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Interrupted Privacy download retains progress while waiting"
        attachment.lifetime = .keepAlways
        add(attachment)
        try waitForStage("retrying", on: status)
        XCTAssertTrue(status.label.contains("50%"), "Retry must preserve the transferred bytes")
        XCTAssertTrue(cancel.isEnabled)
        try waitForStage("transfer", on: status)
        let resumed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label MATCHES %@", "Downloading (75|100)%"), object: status)
        XCTAssertEqual(XCTWaiter.wait(for: [resumed], timeout: 5), .completed,
                       "The resumed transfer must continue above its interruption point")
        try waitForStage("verification", on: status)
        try waitForStage("ready", on: status)
        XCTAssertFalse(cancel.exists)
        XCTAssertTrue(try settingsPane(in: app).buttons["local-model-privacyFilter-remove"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads,apple-local-model-lab.local-execution,apple-local-model-lab.ephemeral-state,apple-local-model-lab.isolated-scope
    func testNeuralSpeechLabPlaysLocalFixtureAndClearsItWhenDisabled() throws {
        let app = try openLab(extraArguments: ["--ui-test-neural-tts-fixture"])
        try enableLab(in: app)
        for id in ["supertonic3"] {
            let input = try settingsPane(in: app).descendants(matching: .any)["local-model-\(id)-text"].firstMatch
            try scrollTo(input, in: app)
            input.tap(); input.typeText("Disposable local speech text")
            let run = try settingsPane(in: app).buttons["local-model-\(id)-run"]
            try scrollTo(run, in: app); XCTAssertTrue(run.isEnabled && run.isHittable); run.tap()
            let play = try settingsPane(in: app).buttons["local-model-\(id)-play"]
            XCTAssertTrue(play.waitForExistence(timeout: 10)); try scrollTo(play, in: app)
            XCTAssertTrue(play.isEnabled && play.isHittable)
            let beforePlayback = XCTAttachment(string: targetDiagnostics(play, in: app) + "\n" + app.debugDescription)
            beforePlayback.name = "\(id) visible local playback target before tap"
            beforePlayback.lifetime = .keepAlways; add(beforePlayback)
            let beforePlaybackShot = XCTAttachment(screenshot: app.screenshot())
            beforePlaybackShot.name = "\(id) local playback target before tap"
            beforePlaybackShot.lifetime = .keepAlways; add(beforePlaybackShot)
            let synthesisTiming = try settingsPane(in: app).staticTexts["local-model-lab-phase-timing-5"]
            try scrollTo(synthesisTiming, in: app)
            XCTAssertTrue(synthesisTiming.label.hasPrefix("Generating speech"))
            XCTAssertFalse(synthesisTiming.label.contains("personal data"))
            try scrollTo(play, in: app)
            play.tap()
            let playing = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Stop playback"), object: play)
            let playbackTransition = XCTWaiter.wait(for: [playing], timeout: 3)
            if playbackTransition != .completed {
                // Synthetic-only case: retain evidence before the assertion stops
                // execution; never pad the transient-state observation timeout.
                let details = XCTAttachment(string: """
                    model=\(id);play-label=\(play.label);play-frame=\(play.frame);play-hittable=\(play.isHittable)
                    \(app.debugDescription)
                    """)
                details.name = "\(id) local fixture playback transition failure"
                details.lifetime = .keepAlways; add(details)
                let shot = XCTAttachment(screenshot: app.screenshot())
                shot.name = "\(id) local playback transition failure screen"
                shot.lifetime = .keepAlways; add(shot)
            }
            XCTAssertEqual(playbackTransition, .completed)
            let remove = try settingsPane(in: app).buttons["local-model-\(id)-remove"]
            XCTAssertFalse(remove.isEnabled, "Playback retains private output ownership")
            play.tap()
            let stopped = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Play local result"), object: play)
            XCTAssertEqual(XCTWaiter.wait(for: [stopped], timeout: 3), .completed)
            let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "\(id) synthetic local speech result"; shot.lifetime = .keepAlways; add(shot)
            let toggle = try settingsPane(in: app).switches["local-model-lab-toggle"]
            // This switch precedes the model cards in the lazy settings stack.
            // Return toward the header while its offscreen AX child is absent.
            try scrollTo(toggle, in: app, searchTowardTop: true)
            toggle.tap(); try waitForValue("Off", on: toggle)
            XCTAssertFalse(play.exists)
            toggle.tap(); try waitForValue("On", on: toggle)
            try scrollTo(input, in: app)
            XCTAssertFalse((input.value as? String ?? "").contains("Disposable local speech text"), "Leaving the lab clears private speech text")
        }
    }

    private func waitForStage(_ stage: String, on element: XCUIElement, timeout: TimeInterval = 5) throws {
        // The app displays localized status copy; test launches explicitly use English.
        let prefixes = [
            "transfer": "Downloading ",
            "verification": "Verifying downloaded files", "ready": "Ready for offline tests",
            "notDownloaded": "Not downloaded", "modelLoading": "Loading model",
            "inference": "Detecting personal data", "cleanup": "Cancelling and unloading",
            "waitingForConnection": "Waiting for connection", "retrying": "Retrying interrupted download"
        ]
        let prefix = try XCTUnwrap(prefixes[stage])
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label BEGINSWITH %@", prefix), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: timeout), .completed)
    }
    private func waitForValue(_ value: String, on element: XCUIElement) throws {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", value), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed)
    }
    private func enableLab(in app: XCUIApplication) throws {
        let toggle = try NativeUITestElementResolution.requireVisible(
            try settingsPane(in: app).switches.matching(identifier: "local-model-lab-toggle"), in: app)
        if toggle.value as? String == "Off" { toggle.tap() }
        try waitForValue("On", on: toggle)
    }
    private func openLab(privacyDiagnostics: Bool = false, extraArguments: [String] = []) throws -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture", "-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-app_language", "en"] + extraArguments
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        _ = try NativeUITestElementResolution.requireVisible(
            app.descendants(matching: .any).matching(identifier: "workspace-settings"),
            in: app, timeout: 10, actionable: false)
        if privacyDiagnostics {
            try openPrivacyDiagnostics(in: app)
            return app
        }
        let developers = try settingsPane(in: app).descendants(matching: .any)["settings-developers-row"].firstMatch
        try scrollTo(developers, in: app)
        XCTAssertTrue(developers.exists, "Settings must expose the Developers destination")
        XCTAssertTrue(developers.isHittable, "Developers must be visible in the settings scroll container")
        developers.tap()
        let row = try settingsPane(in: app).descendants(matching: .any)["settings-developers-local-models-row"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        XCTAssertTrue(row.isHittable)
        row.tap()
        XCTAssertTrue(try settingsPane(in: app).descendants(matching: .any)["settings-local-models-page"].waitForExistence(timeout: 5))
        return app
    }
    private func openPrivacyDiagnostics(in app: XCUIApplication) throws {
        let privacy = try settingsPane(in: app).buttons["settings-privacy-row"]
        try scrollTo(privacy, in: app)
        XCTAssertTrue(privacy.isHittable)
        privacy.tap()
        let hide = try settingsPane(in: app).buttons["settings-hide-personal-data-row"]
        XCTAssertTrue(hide.waitForExistence(timeout: 5) && hide.isHittable)
        hide.tap()
        let diagnostics = try settingsPane(in: app).buttons["settings-enhanced-pii-model-diagnostics"]
        try scrollTo(diagnostics, in: app)
        XCTAssertTrue(diagnostics.isEnabled && diagnostics.isHittable)
        diagnostics.tap()
        XCTAssertTrue(try settingsPane(in: app).descendants(matching: .any)["privacy-model-diagnostic-scope"].waitForExistence(timeout: 5))
        XCTAssertFalse(try settingsPane(in: app).switches["local-model-lab-toggle"].exists,
                       "Privacy diagnostics must work independently of the Developers experiment switch")
    }

    private func settingsPane(in app: XCUIApplication) throws -> XCUIElement {
        try NativeUITestElementResolution.requireVisible(
            app.descendants(matching: .any).matching(identifier: "workspace-settings"),
            in: app, actionable: false)
    }

    private func scrollTo(_ element: XCUIElement, in app: XCUIApplication, actionable: Bool = true, searchTowardTop: Bool = false) throws {
        // description preserves the query; identifier dereferences a snapshot
        // and can itself fail after a lazy child has left the viewport.
        let queryDescription = element.description
        let pane = try settingsPane(in: app)
        let scrollView = try NativeUITestElementResolution.requireVisible(
            pane.scrollViews.matching(NSPredicate(format: "identifier IN %@",
                ["local-model-lab-scroll", "settings-local-models-page", "settings-menu", "settings-privacy-page", "settings-hide-personal-data-page"])), in: app, actionable: false)
        let content = scrollView.children(matching: .other).firstMatch
        var scrollForward = !searchTowardTop
        for _ in 0..<48 {
            // The settings panel is smaller than the window. A focused input
            // can also cover its lower portion with the system keyboard.
            var viewport = scrollView.frame.intersection(app.windows.firstMatch.frame)
            // Sticky banner and child navigation are siblings of the scroll.
            // AX may report an underlying control hittable through these rows;
            // only the exposed content area is safe for real taps and drags.
            let stickyControls = pane.descendants(matching: .any).matching(
                NSPredicate(format: "identifier IN %@", ["settings-banner-shell",
                    "settings-developers-back", "settings-privacy-diagnostics-back"]))
            for control in stickyControls.allElementsBoundByIndex {
                let frame = control.frame
                let overlap = viewport.intersection(frame)
                if !overlap.isNull, overlap.width > 0, overlap.height > 0 {
                    let bottom = viewport.maxY
                    viewport.origin.y = max(viewport.minY, frame.maxY)
                    viewport.size.height = max(0, bottom - viewport.minY)
                }
            }
            #if os(iOS)
            let keyboard = app.keyboards.firstMatch
            if keyboard.exists && keyboard.frame.intersects(viewport) {
                viewport.size.height = max(0, min(viewport.maxY, keyboard.frame.minY) - viewport.minY)
            }
            #endif
            XCTAssertGreaterThan(viewport.height, 60, "The real settings scroll viewport must allow a gesture")
            guard viewport.height > 60 else { return }
            if element.exists && !element.frame.isEmpty {
                let target = element.frame
                if actionable {
                    // Match the effective 152 gesture check: the visible
                    // control center must be hittable within the panel.
                    if viewport.contains(CGPoint(x: target.midX, y: target.midY)) && element.isHittable { return }
                } else {
                    // A noninteractive group can be taller than the viewport.
                    // Its visible portion proves presence; its child controls
                    // retain the visible-center/hittability checks above.
                    let visible = viewport.intersection(target)
                    if !visible.isNull && visible.width > 0 && visible.height >= min(44, target.height) { return }
                }
                if target.midY < viewport.midY { scrollForward = false }
                else { scrollForward = true }
            }
            let before = content.exists ? content.frame.minY : nil
            #if os(iOS)
            // Full swipes jumped ~680pt across a 461pt viewport in the failure
            // evidence. Slow, held 30% drags expose each control before reversal.
            // Keep the gesture in the left gutter. The right gutter is the
            // vertical scrollbar's touch region and can jump the scroll offset.
            let x = viewport.minX + min(12, viewport.width * 0.04)
            let upper = CGPoint(x: x, y: viewport.minY + viewport.height * 0.35)
            let lower = CGPoint(x: x, y: viewport.minY + viewport.height * 0.65)
            let origin = app.coordinate(withNormalizedOffset: .zero)
            let start = scrollForward ? lower : upper
            let end = scrollForward ? upper : lower
            origin.withOffset(CGVector(dx: start.x, dy: start.y)).press(forDuration: 0.05,
                thenDragTo: origin.withOffset(CGVector(dx: end.x, dy: end.y)),
                withVelocity: .slow, thenHoldForDuration: 0.2)
            #else
            if scrollForward { scrollView.swipeUp(velocity: .slow) }
            else { scrollView.swipeDown(velocity: .slow) }
            #endif
            // An absent lazy child gives no target geometry. For a known header
            // control, keep returning toward the top until it reenters AX. Lazy
            // content geometry alone can appear stationary before reaching it.
            // Other searches still explore the current edge before reversing.
            if !searchTowardTop, let before, content.exists, abs(content.frame.minY - before) < 1 {
                scrollForward.toggle()
            }
        }
        let diagnostic = targetDiagnostics(element, in: app)
        print(diagnostic)
        captureLabFailure(in: app, context: diagnostic)
        XCTFail("Could not expose query \(queryDescription) inside the settings scroll viewport. \(diagnostic)")
    }

    private func targetDiagnostics(_ element: XCUIElement, in app: XCUIApplication) -> String {
        let scroll = app.scrollViews.matching(NSPredicate(format: "identifier IN %@",
            ["local-model-lab-scroll", "settings-local-models-page", "settings-menu", "settings-privacy-page", "settings-hide-personal-data-page"])).firstMatch
        let viewport = scroll.exists ? scroll.frame.intersection(app.windows.firstMatch.frame) : .null
        guard element.exists else {
            return "Lab target query=\(element.description) exists=false viewport=\(viewport)"
        }
        return "Lab target query=\(element.description) exists=true frame=\(element.frame) enabled=\(element.isEnabled) hittable=\(element.isHittable) viewport=\(viewport)"
    }

    private func captureLabFailure(in app: XCUIApplication, context: String) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Local model lab failure viewport"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = XCTAttachment(string: context + "\n" + app.debugDescription)
        hierarchy.name = "Local model lab failure target and accessibility hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }
}
