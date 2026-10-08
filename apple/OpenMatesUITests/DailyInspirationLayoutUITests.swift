// Layout regression proof uses real InspirationCard and EmbedPreviewCard.
import XCTest
import CoreGraphics
import ImageIO

@MainActor
final class DailyInspirationLayoutUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testInspirationSurvivesInactiveSceneAndKeepsContentAndActionGeometry() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "daily-inspiration", "--dev-preview-variant", "wide",
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let card = element(app, "daily-inspiration-card")
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        let phrase = element(app, "daily-inspiration-phrase")
        let originalPhrase = phrase.label
        let originalFrame = card.frame
        #if os(iOS)
        XCUIDevice.shared.press(.home)
        app.activate()
        #endif
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        XCTAssertEqual(phrase.label, originalPhrase)
        XCTAssertEqual(card.frame.width, originalFrame.width, accuracy: 1)
        XCTAssertEqual(card.frame.height, originalFrame.height, accuracy: 1)
        let cta = element(app, "daily-inspiration-cta-text")
        XCTAssertTrue(cta.exists); XCTAssertTrue(cta.isHittable)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testWikipediaInspirationShowsPreviewAndOpensArticleWithoutStartingChat() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "daily-inspiration", "--dev-preview-variant", "wiki",
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let banner = element(app, "daily-inspiration-card")
        XCTAssertTrue(banner.waitForExistence(timeout: 10))
        let wiki = element(app, "daily-inspiration-wiki-preview")
        XCTAssertTrue(wiki.waitForExistence(timeout: 15), "Wikipedia cards must join the real compact preview phase")
        XCTAssertTrue(wiki.isHittable)
        XCTAssertTrue(banner.frame.contains(wiki.frame))
        assertWikipediaStudyGradient(app, wiki: wiki)
        let snapshot = XCTAttachment(screenshot: app.screenshot())
        snapshot.name = "Wikipedia daily inspiration preview"
        snapshot.lifetime = .keepAlways
        add(snapshot)
        wiki.tap()
        XCTAssertTrue(element(app, "embed-fullscreen-header").waitForExistence(timeout: 5))
        XCTAssertEqual(element(app, "dev-preview-local-action").label, "ready",
            "Opening the Wikipedia preview must not start an inspiration chat")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testWideInspirationKeepsPhraseSeparateAndVideoFooterVisible() {
        checkLayout(variant: "wide", expectsSideBySide: true)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testLongVideoTitleKeepsEntireAppBadgeInsidePreview() {
        checkLayout(variant: "long-title", expectsSideBySide: true)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testShortInspirationFitsEntirePreviewAndKeepsStartActionHittable() {
        checkLayout(variant: "short", expectsSideBySide: true)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testNarrowInspirationAlternatesPreviewWithoutCoveredTextInteraction() {
        checkLayout(variant: "narrow", expectsSideBySide: false)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testReadOnlyInspirationKeepsLayoutAndDoesNotStartChatFromCTAOrVideo() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "daily-inspiration", "--dev-preview-variant", "read-only",
            "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let banner = element(app, "daily-inspiration-card")
        XCTAssertTrue(banner.waitForExistence(timeout: 10))
        let phrase = element(app, "daily-inspiration-phrase")
        let cta = element(app, "daily-inspiration-cta-text")
        let video = element(app, "daily-inspiration-video-preview")
        let footer = element(app, "embed-basic-info-title")
        let compact = banner.frame.width <= 730
        if compact {
            let phrasePhase = NSPredicate { _, _ in
                phrase.exists && cta.exists && !video.exists && !footer.exists
            }
            expectation(for: phrasePhase, evaluatedWith: banner)
            waitForExpectations(timeout: 15)
        }
        XCTAssertTrue(phrase.exists)
        XCTAssertTrue(cta.exists)
        XCTAssertTrue(banner.frame.contains(phrase.frame))
        XCTAssertTrue(banner.frame.contains(cta.frame))
        XCTAssertLessThanOrEqual(phrase.frame.maxY, cta.frame.minY + 1)
        // A readable AX container remains enabled even when its child controls
        // are disabled. It must not advertise a Button or deliver a tap action.
        XCTAssertNotEqual(banner.elementType, .button, "Read-only inspiration must not advertise a start action")
        XCTAssertFalse(cta.isEnabled, "The visible CTA must inherit the read-only state")
        assertReadOnlyTapDoesNotStartChat(app, target: banner)
        assertReadOnlyTapDoesNotStartChat(app, target: cta)

        if compact {
            let previewPhase = NSPredicate { _, _ in
                (banner.value as? String) == "How to Build a Great Developer Experience"
                    && video.exists && footer.exists && !phrase.exists && !cta.exists
            }
            expectation(for: previewPhase, evaluatedWith: banner)
            waitForExpectations(timeout: 15)
            XCTAssertFalse(phrase.exists)
            XCTAssertFalse(cta.exists)
        } else {
            XCTAssertLessThanOrEqual(phrase.frame.maxX + 13, video.frame.minX)
        }
        XCTAssertTrue(video.exists)
        XCTAssertTrue(footer.exists)
        XCTAssertTrue(banner.frame.contains(video.frame), "Read-only preview must retain its normal visible size")
        XCTAssertTrue(banner.frame.contains(footer.frame), "Read-only preview must retain the visible footer")
        XCTAssertFalse(video.isEnabled, "The video start target must inherit the read-only state")
        assertReadOnlyTapDoesNotStartChat(app, target: video)
    }

    private func assertReadOnlyTapDoesNotStartChat(_ app: XCUIApplication, target: XCUIElement) {
        let result = element(app, "dev-preview-local-action")
        XCTAssertTrue(result.waitForExistence(timeout: 5))
        XCTAssertEqual(result.label, "ready")
        // A disabled AX control may reject XCUIElement.tap(). Send a real
        // coordinate tap to its visible bounds to prove the action is blocked.
        let bounds = target.frame
        XCTAssertFalse(bounds.isEmpty)
        XCTAssertTrue(app.windows.firstMatch.frame.contains(bounds))
        target.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        let started = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@", "inspiration-started"), object: result)
        started.isInverted = true
        let outcome = XCTWaiter.wait(for: [started], timeout: 2)
        if outcome != .completed {
            let diagnostics = XCTAttachment(string: "target=\(target.identifier);tap-bounds=\(bounds);result=\(result.label)\n" + app.debugDescription)
            diagnostics.name = "Read-only inspiration unexpected action delivery"
            diagnostics.lifetime = .keepAlways
            add(diagnostics)
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Read-only inspiration unexpected action viewport"
            screenshot.lifetime = .keepAlways
            add(screenshot)
        }
        XCTAssertEqual(outcome, .completed, "An actual tap on read-only inspiration must not deliver its callback")
        XCTAssertEqual(result.label, "ready")
    }

    private func assertWikipediaStudyGradient(_ app: XCUIApplication, wiki: XCUIElement) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            (self.previewBounds(app, "circle")?.width ?? 0) > 0
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed)
        guard let card = previewBounds(app, "card"), let localCircle = previewBounds(app, "circle") else {
            return XCTFail("Production Wikipedia badge geometry must be available")
        }
        XCTAssertEqual(card.width, wiki.frame.width, accuracy: 1)
        XCTAssertEqual(card.height, wiki.frame.height, accuracy: 1)
        let circle = localCircle.offsetBy(dx: wiki.frame.minX - card.minX, dy: wiki.frame.minY - card.minY)
        XCTAssertTrue(wiki.frame.contains(circle), "Study circle must remain fully visible inside Wiki card")
        let screenshot = wiki.screenshot()
        guard let source = CGImageSourceCreateWithData(screenshot.pngRepresentation as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            return XCTFail("Missing rendered Wikipedia screenshot")
        }
        let window = wiki.frame
        func rgb(at fraction: CGFloat) -> [Int]? {
            // Sample inside opposite circle edges, outside the central white glyph.
            let point = CGPoint(x: circle.minX + circle.width * fraction, y: circle.midY)
            let rect = CGRect(x: (point.x - window.minX) * CGFloat(image.width) / window.width - 1,
                y: (point.y - window.minY) * CGFloat(image.height) / window.height - 1, width: 3, height: 3).integral
            guard let crop = image.cropping(to: rect) else { return nil }
            var rgba = [UInt8](repeating: 0, count: crop.width * crop.height * 4)
            let rendered = rgba.withUnsafeMutableBytes { bytes -> Bool in
                guard let context = CGContext(data: bytes.baseAddress, width: crop.width, height: crop.height,
                    bitsPerComponent: 8, bytesPerRow: crop.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
                context.draw(crop, in: CGRect(x: 0, y: 0, width: crop.width, height: crop.height))
                return true
            }
            guard rendered else { return nil }
            return (0..<3).map { channel in
                stride(from: channel, to: rgba.count, by: 4).reduce(0) { $0 + Int(rgba[$1]) } / (crop.width * crop.height)
            }
        }
        guard let left = rgb(at: 0.2), let right = rgb(at: 0.8) else {
            return XCTFail("Missing actual Study circle pixels")
        }
        for sample in [left, right] {
            XCTAssertGreaterThan(sample[0], 210, "Study badge must visibly render the web orange gradient")
            XCTAssertGreaterThan(sample[0] - sample[1], 90)
            XCTAssertGreaterThan(sample[0] - sample[2], 160, "Default blue must never replace Study")
            XCTAssertLessThan(sample[2], 30)
        }
        XCTAssertGreaterThan(left[0] - right[0], 6, "Badge must retain the Study gradient, not a flat orange fill")
        XCTAssertGreaterThan(left[1] - right[1], 10)
    }

    private func previewBounds(_ app: XCUIApplication, _ key: String) -> CGRect? {
        let probe = element(app, "inspiration-preview-\(key)-bounds")
        guard probe.exists else { return nil }
        let values = probe.label.split(separator: ",").compactMap { Double($0) }
        guard values.count == 4 else { return nil }
        return CGRect(x: values[0], y: values[1], width: values[2], height: values[3])
    }

    private func assertVideoBadgeContainedInCard(_ app: XCUIApplication) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            (self.previewBounds(app, "card")?.width ?? 0) > 0
                && (self.previewBounds(app, "circle")?.width ?? 0) > 0
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed)
        guard let card = previewBounds(app, "card"), let circle = previewBounds(app, "circle") else {
            XCTFail("Production card and badge geometry must be available")
            return
        }
        XCTAssertGreaterThan(circle.width, 20, "Verify the full app circle, not only its inner glyph")
        XCTAssertTrue(card.insetBy(dx: -1, dy: -1).contains(circle),
            "The entire video app badge must fit inside its card: card=\(card), circle=\(circle)")
    }

    private func checkLayout(variant: String, expectsSideBySide: Bool) {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "daily-inspiration", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let banner = element(app, "daily-inspiration-card")
        XCTAssertTrue(banner.waitForExistence(timeout: 10))
        let phrase = element(app, "daily-inspiration-phrase")
        let cta = element(app, "daily-inspiration-cta-text")
        let video = element(app, "daily-inspiration-video-preview")
        let sideBySide = expectsSideBySide && banner.frame.width > 730
        let videoTitle = variant == "long-title"
            ? "Mentorship in Software Engineering: Finding the Right Mentor for Your Next Project"
            : "How to Build a Great Developer Experience"
        if !sideBySide {
            // App launch/idling may span several real production phases.
            // Observe the next phrase phase, then prove its actual transition.
            let phrasePhase = NSPredicate { _, _ in
                phrase.exists && cta.exists && !video.exists
                    && !self.element(app, "embed-basic-info-title").exists
            }
            expectation(for: phrasePhase, evaluatedWith: banner)
            waitForExpectations(timeout: 15)
        }
        XCTAssertTrue(phrase.exists)
        XCTAssertTrue(cta.exists)
        XCTAssertTrue(banner.frame.contains(phrase.frame))
        XCTAssertTrue(banner.frame.contains(cta.frame))
        XCTAssertLessThanOrEqual(phrase.frame.maxY, cta.frame.minY + 1)
        XCTAssertTrue(banner.isHittable)

        if sideBySide {
            XCTAssertTrue(video.exists)
            XCTAssertLessThanOrEqual(phrase.frame.maxX + 13, video.frame.minX)
        } else {
            XCTAssertFalse(video.exists, "Inactive preview must not expose hidden card or footer controls")
            XCTAssertFalse(element(app, "embed-basic-info-title").exists)
            // Existence alone previously returned for an invisible retained
            // preview. Wait for the real production phase and both AX branches.
            let previewPhase = NSPredicate { _, _ in
                (banner.value as? String) == videoTitle
                    && video.exists && !phrase.exists && !cta.exists
            }
            expectation(for: previewPhase, evaluatedWith: banner)
            waitForExpectations(timeout: 15)
            XCTAssertFalse(phrase.exists, "Hidden phrase must leave the accessibility and interaction tree")
            XCTAssertFalse(cta.exists, "Inactive CTA must leave the accessibility and interaction tree")
        }
        let footerTitle = element(app, "embed-basic-info-title")
        XCTAssertTrue(footerTitle.exists)
        XCTAssertTrue(banner.frame.contains(footerTitle.frame), "Video footer title must remain inside the visible banner")
        XCTAssertTrue(banner.frame.contains(video.frame), "Entire preview must fit the banner")
        assertVideoBadgeContainedInCard(app)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Daily inspiration \(variant) layout"
        attachment.lifetime = .keepAlways
        add(attachment)
        // Exercise the real CTA Button when visible; the compact preview
        // phase exposes the finished video as its explicit start target.
        let startTarget = cta.exists ? cta : video
        XCTAssertTrue(startTarget.isHittable)
        let tapBounds = startTarget.frame, tapIdentifier = startTarget.identifier
        startTarget.tap()
        let result = element(app, "dev-preview-local-action")
        let started = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "inspiration-started"), object: result)
        let delivered = XCTWaiter.wait(for: [started], timeout: 5)
        if delivered != .completed {
            let diagnostics = XCTAttachment(string: "target=\(tapIdentifier);tap-bounds=\(tapBounds);banner=\(banner.frame);result=\(result.label)\n" + app.debugDescription)
            diagnostics.name = "Daily inspiration actual start tap delivery"
            diagnostics.lifetime = .keepAlways
            add(diagnostics)
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Daily inspiration missing start result viewport"
            screenshot.lifetime = .keepAlways
            add(screenshot)
        }
        XCTAssertEqual(delivered, .completed)
        XCTAssertEqual(result.label, "inspiration-started")
    }

    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
