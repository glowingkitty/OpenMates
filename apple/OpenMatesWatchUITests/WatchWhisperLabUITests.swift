import XCTest

final class WatchWhisperLabUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.watch-tiny,apple-local-model-lab.isolated-scope
    func testDeveloperEntryEnablesExplicitDownloadAndShowsDisposableLocalResultAndMeasurements() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-hub-lists", "--watch-whisper-use-fixtures"]
        app.launch()
        let tasks = app.buttons["watch-hub-select-tasks"]
        XCTAssertTrue(tasks.waitForExistence(timeout: 12)); tasks.tap()
        XCTAssertTrue(app.buttons["watch-task-row-backlog-0"].waitForExistence(timeout: 3))
        expectation(for: NSPredicate { _, _ in !tasks.isHittable }, evaluatedWith: tasks)
        waitForExpectations(timeout: 3)
        let settings = app.buttons["watch-hub-settings"]
        XCTAssertTrue(settings.isHittable); settings.tap()
        XCTAssertTrue(app.otherElements["watch-hub-phone-popup"].waitForExistence(timeout: 3))
        let entry = app.buttons["watch-settings-developer-whisper"]
        XCTAssertTrue(entry.waitForExistence(timeout: 3)); XCTAssertTrue(entry.isHittable); entry.tap()
        XCTAssertTrue(app.staticTexts["watch-whisper-title"].waitForExistence(timeout: 3))
        let download = app.buttons["watch-whisper-download"]
        reveal(download, app: app); XCTAssertFalse(download.isEnabled)
        let enable = app.buttons["watch-whisper-enable"]
        reveal(enable, app: app); enable.tap()
        reveal(download, app: app); XCTAssertTrue(download.isEnabled); download.tap()
        let cancelDownload = app.buttons["watch-whisper-cancel-download"]
        XCTAssertTrue(cancelDownload.waitForExistence(timeout: 3))
        let remove = app.buttons["watch-whisper-remove"]
        XCTAssertTrue(remove.waitForExistence(timeout: 8))
        let imported = app.buttons["watch-whisper-import-fixture"]
        reveal(imported, app: app); imported.tap()
        XCTAssertTrue(app.staticTexts["watch-whisper-audio-duration"].waitForExistence(timeout: 3))
        let run = app.buttons["watch-whisper-run"]
        reveal(run, app: app); XCTAssertTrue(run.isEnabled); run.tap()
        let transcript = app.staticTexts["watch-whisper-transcript"]
        XCTAssertTrue(transcript.waitForExistence(timeout: 10))
        reveal(transcript, app: app); XCTAssertTrue(transcript.isHittable)
        XCTAssertEqual(transcript.label, "Disposable English and German fixture result.")
        let timings = app.staticTexts["watch-whisper-timings"]
        reveal(timings, app: app); XCTAssertTrue(timings.isHittable)
        XCTAssertTrue(timings.label.contains("s")); XCTAssertFalse(timings.label.contains("{load}"))
        let memory = app.staticTexts["watch-whisper-memory"]
        reveal(memory, app: app); XCTAssertTrue(memory.isHittable)
        XCTAssertFalse(memory.label.contains("{peak}"))
        screenshot("Watch tiny lab: disposable runtime fixture result and measured phases")
        reveal(remove, app: app); XCTAssertTrue(remove.isEnabled); remove.tap()
        XCTAssertTrue(download.waitForExistence(timeout: 5))
        app.buttons["watch-whisper-back"].tap()
        XCTAssertTrue(app.buttons["watch-hub-settings"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.staticTexts["watch-whisper-transcript"].exists)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.watch-tiny,apple-local-model-lab.serialized-cancellation,apple-local-model-lab.ephemeral-state
    func testCancelKeepsRunUnavailableDuringUnloadAndExitClearsInput() {
        let app = XCUIApplication()
        app.launchArguments = ["--watch-whisper-lab-fixture"]
        app.launch()
        let enable = app.buttons["watch-whisper-enable"]
        XCTAssertTrue(enable.waitForExistence(timeout: 12)); enable.tap()
        let download = app.buttons["watch-whisper-download"]
        reveal(download, app: app); download.tap()
        XCTAssertTrue(app.buttons["watch-whisper-remove"].waitForExistence(timeout: 8))
        let imported = app.buttons["watch-whisper-import-fixture"]
        reveal(imported, app: app); imported.tap()
        let run = app.buttons["watch-whisper-run"]
        reveal(run, app: app); run.tap()
        let cancel = app.buttons["watch-whisper-cancel-run"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 3)); reveal(cancel, app: app); cancel.tap()
        XCTAssertFalse(run.exists)
        XCTAssertFalse(cancel.isEnabled)
        XCTAssertFalse(app.staticTexts["watch-whisper-transcript"].exists)
        XCTAssertTrue(run.waitForExistence(timeout: 8))
        XCTAssertFalse(app.staticTexts["watch-whisper-transcript"].exists)
        app.buttons["watch-whisper-back"].tap()
        XCTAssertFalse(app.staticTexts["watch-whisper-audio-duration"].exists)
        reveal(run, app: app); XCTAssertFalse(run.isEnabled)
        screenshot("Watch tiny lab cancellation drained and private input cleared")
    }
    @MainActor private func reveal(_ element: XCUIElement, app: XCUIApplication) {
        let scroll = app.scrollViews["watch-whisper-scroll"]
        for _ in 0..<10 where !element.isHittable { scroll.swipeUp() }
        if !element.isHittable { for _ in 0..<10 where !element.isHittable { scroll.swipeDown() } }
        XCTAssertTrue(element.isHittable)
    }
    @MainActor private func screenshot(_ title: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = title; attachment.lifetime = .keepAlways; add(attachment)
    }
}
