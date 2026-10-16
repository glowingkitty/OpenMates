import XCTest

@MainActor
final class PCBSchematicActionsUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testPrepareLogsToggleAndArtifactOpensRealExport() {
        let app = launch("action-pcb")
        let prepare = app.buttons["pcb-schematic-prepare-files"].firstMatch
        XCTAssertTrue(prepare.waitForExistence(timeout: 5)); reveal(prepare, app: app); prepare.tap()
        let artifact = app.buttons["pcb-schematic-artifact-public-board"].firstMatch
        XCTAssertTrue(artifact.waitForExistence(timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)["pcb-schematic-logs"].firstMatch.exists)
        let logsButton = app.buttons["pcb-schematic-show-logs"].firstMatch
        reveal(logsButton, app: app); logsButton.tap()
        XCTAssertTrue(app.descendants(matching: .any)["pcb-schematic-logs"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(artifact.exists)
        logsButton.tap()
        XCTAssertTrue(artifact.waitForExistence(timeout: 5)); reveal(artifact, app: app); artifact.tap()
        XCTAssertTrue(app.descendants(matching: .any)["native-embed-file-export"].firstMatch.waitForExistence(timeout: 5), app.debugDescription)
        let requests = app.descendants(matching: .any)["pcb-fixture-requests"].firstMatch.label
        XCTAssertTrue(requests.contains("POST|/v1/electronics/pcb-schematic/embeds/public-pcb/prepare-files|{\"force\":false}"))
        XCTAssertTrue(requests.contains("GET|/v1/electronics/pcb-schematic/compile/public-compile/artifacts/public-board|"))
        let close = app.buttons["Close"].firstMatch
        XCTAssertTrue(close.waitForExistence(timeout: 5)); close.tap()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFailureShowsErrorAndLogsOnlyAfterExplicitToggle() {
        let app = launch("action-pcb-failed")
        let prepare = app.buttons["pcb-schematic-prepare-files"].firstMatch
        XCTAssertTrue(prepare.waitForExistence(timeout: 5)); reveal(prepare, app: app); prepare.tap()
        XCTAssertTrue(app.staticTexts["Public compiler error"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)["pcb-schematic-logs"].firstMatch.exists)
        let toggle = app.buttons["pcb-schematic-show-logs"].firstMatch
        reveal(toggle, app: app); toggle.tap()
        XCTAssertTrue(app.staticTexts["Public compile failed"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testRecipientCannotDispatchOwnerAuthorizedCompile() {
        let app = launch("action-pcb-recipient")
        let prepare = app.buttons["pcb-schematic-prepare-files"].firstMatch
        XCTAssertTrue(prepare.waitForExistence(timeout: 5))
        XCTAssertFalse(prepare.isEnabled)
        XCTAssertEqual(app.descendants(matching: .any)["pcb-fixture-requests"].firstMatch.label, "")
    }
    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant, "--dev-preview-width", "390"]
        app.launch(); return app
    }
    private func reveal(_ element: XCUIElement, app: XCUIApplication) {
        for _ in 0..<5 { if element.isHittable { return }; app.swipeUp() }
        XCTAssertTrue(element.isHittable, app.debugDescription)
    }
}
