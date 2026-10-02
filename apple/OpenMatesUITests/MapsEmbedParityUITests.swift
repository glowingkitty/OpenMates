// Standalone Maps preview and fullscreen match their web registry surfaces.
import XCTest
import UIKit

@MainActor
final class MapsEmbedParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testStaticSVGLocationPreviewIsLoadedAndBoundedWithoutLiveMap() {
        let app = launch(key: "maps-place", surface: "preview", orientation: .portrait)
        defer { XCUIDevice.shared.orientation = .portrait }
        let image = app.descendants(matching: .any)["maps-preview-image"].firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 10))
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "loaded"), object: image)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 15), .completed)
        let card = app.buttons["embed-preview"]
        XCTAssertEqual(card.frame.width, 300, accuracy: 1)
        XCTAssertEqual(card.frame.height, 200, accuracy: 1)
        XCTAssertTrue(card.frame.contains(image.frame))
        XCTAssertFalse(app.descendants(matching: .any)["embed-location-map"].exists)
        XCTAssertTrue(app.staticTexts["Location"].exists)
        attach("Maps static SVG preview loaded")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPlaceFullscreenNarrowShowsMapDetailsWebsiteAndClose() {
        verifyFullscreen(key: "maps-place", orientation: .portrait)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPlaceFullscreenWideBoundsMapAndFloatingDetailCard() {
        verifyFullscreen(key: "maps-place", orientation: .landscapeLeft)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLocationFullscreenNarrowShowsMapAddressActionsAndClose() {
        verifyFullscreen(key: "maps", orientation: .portrait)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLocationFullscreenWideShowsMapAddressActionsAndClose() {
        verifyFullscreen(key: "maps", orientation: .landscapeLeft)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFullscreenWithImageAndCoordinatesLoadsStaticImageWithoutMountingMapKit() {
        let app = launch(key: "maps", surface: "fullscreen", orientation: .portrait,
                         variant: "staticWithCoordinates")
        defer { XCUIDevice.shared.orientation = .portrait }
        waitForFullscreenReady(app)
        let image = app.descendants(matching: .any)["maps-fullscreen-static-map"].firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 10))
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "loaded"), object: image)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 15), .completed,
                       "The shared production image loader must finish the supplied SVG before capture")
        XCTAssertEqual(image.frame.height, 150, accuracy: 1)
        XCTAssertFalse(app.descendants(matching: .any)["embed-location-map"].exists,
                       "Coordinates must not mount a second map behind the valid static image")
        XCTAssertFalse(app.descendants(matching: .any)["embed-location-zoom-controls"].exists)
        XCTAssertTrue(app.staticTexts["maps-location-address"].exists)
        XCTAssertTrue(app.buttons["maps-open-google-maps"].isHittable)
        attach("Maps fullscreen prioritizes supplied static image over coordinates")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFullscreenInvalidStaticImageFallsBackToInteractiveMapWithCoordinates() {
        let app = launch(key: "maps", surface: "fullscreen", orientation: .portrait,
                         variant: "invalidStaticWithCoordinates")
        defer { XCUIDevice.shared.orientation = .portrait }
        waitForFullscreenReady(app)
        let map = app.descendants(matching: .any)["embed-location-map"].firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 15),
                      "The shared loader must reject the unsafe SVG and select MapKit fallback")
        let rendered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "rendered"), object: map)
        XCTAssertEqual(XCTWaiter.wait(for: [rendered], timeout: 20), .completed)
        XCTAssertEqual(map.frame.height, 150, accuracy: 1)
        XCTAssertFalse(app.descendants(matching: .any)["maps-fullscreen-static-map"].exists,
                       "Failed static image must be unmounted when the interactive fallback starts")
        let marker = app.descendants(matching: .any)["embed-location-marker"].firstMatch
        XCTAssertTrue(marker.waitForExistence(timeout: 5))
        XCTAssertTrue(map.frame.intersects(marker.frame))
        let zoom = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Zoom in")).firstMatch
        XCTAssertTrue(zoom.isHittable)
        XCTAssertTrue(app.buttons["maps-open-google-maps"].isHittable)
        attach("Maps fullscreen rejected static image uses interactive fallback")
    }

    private func verifyFullscreen(key: String, orientation: UIDeviceOrientation) {
        let app = launch(key: key, surface: "fullscreen", orientation: orientation)
        defer { XCUIDevice.shared.orientation = .portrait }
        let ready = app.descendants(matching: .any)["embed-presentation-state"].firstMatch
        XCTAssertTrue(ready.waitForExistence(timeout: 10))
        let settled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: ready)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 10), .completed)
        let map = app.descendants(matching: .any)["embed-location-map"].firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 10))
        let rendered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "rendered"), object: map)
        XCTAssertEqual(XCTWaiter.wait(for: [rendered], timeout: 20), .completed)
        XCTAssertGreaterThanOrEqual(map.frame.height, 149)
        XCTAssertLessThanOrEqual(map.frame.maxY, app.frame.maxY + 1)
        let marker = app.descendants(matching: .any)["embed-location-marker"].firstMatch
        XCTAssertTrue(marker.waitForExistence(timeout: 5))
        XCTAssertTrue(map.frame.intersects(marker.frame))
        let action = app.buttons["maps-open-google-maps"]
        XCTAssertTrue(action.isHittable)
        XCTAssertEqual(action.label, "Open on Google Maps")
        XCTAssertEqual(map.frame.minY, action.frame.midY, accuracy: 1)
        let zoom = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Zoom in")).firstMatch
        XCTAssertTrue(zoom.isHittable)
        zoom.tap()
        XCTAssertTrue(action.isHittable)
        let address = app.staticTexts["maps-location-address"]
        XCTAssertTrue(address.exists)
        XCTAssertTrue(address.label.contains(key == "maps-place" ? "Müllerstraße 23" : "Europaplatz 1"))
        if key == "maps-place" {
            XCTAssertEqual(app.staticTexts["maps-location-title"].label, "Man vs. Machine Coffee Roasters")
            let website = app.buttons["maps-place-website"]
            XCTAssertTrue(website.exists)
            if !website.isHittable && map.frame.width > 600 {
                // The wide detail card scrolls inside the remaining viewport.
                let cardScroll = app.scrollViews.containing(.staticText, identifier: "maps-location-title").firstMatch
                cardScroll.swipeUp()
            }
            XCTAssertTrue(website.isHittable)
            XCTAssertEqual(website.label, "mvsm.coffee")
        }
        if map.frame.width <= 600 {
            XCTAssertEqual(map.frame.height, 150, accuracy: 1)
            XCTAssertGreaterThanOrEqual(address.frame.minY, map.frame.maxY)
        } else {
            XCTAssertGreaterThanOrEqual(address.frame.minX, map.frame.minX + 24)
            XCTAssertLessThanOrEqual(address.frame.maxX, map.frame.minX + 369)
        }
        let copy = app.buttons["embed-copy-button"]
        if !copy.exists {
            let more = app.buttons["embed-more-button"]
            XCTAssertTrue(more.isHittable)
            more.tap()
            XCTAssertTrue(copy.waitForExistence(timeout: 5))
        }
        XCTAssertTrue(copy.isHittable)
        copy.tap()
        let feedback = app.staticTexts["Copied to clipboard"]
        XCTAssertTrue(feedback.waitForExistence(timeout: 3))
        let dismissFeedback = app.buttons["notification-dismiss"].firstMatch
        XCTAssertTrue(dismissFeedback.isHittable)
        dismissFeedback.tap()
        let feedbackGone = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == false"), object: feedback)
        XCTAssertEqual(XCTWaiter.wait(for: [feedbackGone], timeout: 5), .completed,
                       "The copy notification overlays the narrow Close control until dismissed")
        let close = app.buttons["embed-minimize"]
        XCTAssertTrue(close.isHittable)
        attach("\(key) \(orientation == .portrait ? "narrow" : "wide") map and actions")
        close.tap()
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.buttons["maps-open-google-maps"])
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 8), .completed)
    }

    private func waitForFullscreenReady(_ app: XCUIApplication) {
        let ready = app.descendants(matching: .any)["embed-presentation-state"].firstMatch
        XCTAssertTrue(ready.waitForExistence(timeout: 10))
        let settled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: ready)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 10), .completed)
    }

    private func launch(key: String, surface: String, orientation: UIDeviceOrientation, variant: String = "default") -> XCUIApplication {
        XCUIDevice.shared.orientation = orientation
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "maps",
            "--embed-registry-key", key, "--embed-surface", surface, "--embed-variant", variant,
            "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        return app
    }

    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
