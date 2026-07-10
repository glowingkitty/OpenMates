// Simulator smoke coverage for native composer inline embed preview families.
// Uses a debug-only synthetic gallery without accounts, providers, or AI calls.
// Every asserted state is non-sensitive and deterministic across test runs.
// The gallery proves product chrome, lifecycle states, and explicit registry use.
// Screenshots provide durable visual evidence for the web-to-native comparison.

import XCTest

@MainActor
final class NativeComposerInlineEmbedUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testRegistryFamiliesAndLifecycleStatesRenderWithoutGenericFallback() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer-embeds"]
        app.launchEnvironment["DEV_PREVIEW"] = "composer-embeds"
        app.launch()

        let gallery = app.descendants(matching: .any)["dev-native-composer-embed-gallery"]
        XCTAssertTrue(gallery.waitForExistence(timeout: 8))
        XCTAssertEqual(gallery.value as? String, "53")

        assertVisible(app: app, identifier: "native-composer-preview-recording-finished")
        assertVisible(app: app, identifier: "native-composer-preview-app-skill-use-queued")
        assertVisible(app: app, identifier: "native-composer-preview-electronics-pcb-schematic-error")
        assertVisible(app: app, identifier: "native-composer-preview-fitness-location-uploading")
        assertVisible(app: app, identifier: "native-composer-preview-recording-transcribing")
        assertVisible(app: app, identifier: "native-composer-preview-code-repo-group-cancelled")
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "{\"")).firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Native composer embed registry lifecycle gallery"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func assertVisible(app: XCUIApplication, identifier: String) {
        let element = app.descendants(matching: .any)[identifier]
        for _ in 0..<20 where !element.exists {
            app.swipeUp()
        }
        XCTAssertTrue(element.exists, "Missing composer preview: \(identifier)")
    }
}
