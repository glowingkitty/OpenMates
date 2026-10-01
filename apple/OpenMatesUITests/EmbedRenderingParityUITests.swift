// UI parity smoke coverage for native embed preview/fullscreen surfaces.
// Uses the debug-only embed gallery so assertions are deterministic and do not
// require credentials, private chat records, provider APIs, or AI calls. The
// paired web contract spec captures the browser source of truth; this simulator
// test exports native screenshots for agent visual review.

import XCTest
import UIKit

@MainActor
final class EmbedRenderingParityUITests: XCTestCase {
    private let canonicalRegistryKeys = [
        "app:audio:generate", "app:audio:speak", "app:business:company_financials",
        "app:calendar:create-event", "app:calendar:delete-event", "app:calendar:get-events",
        "app:calendar:list-calendars", "app:calendar:update-event", "app:code:get_docs",
        "app:code:search_repos", "app:design:search_icons", "app:electronics:search_components",
        "app:events:search", "app:finance:check_accounts", "app:fitness:search_classes",
        "app:fitness:search_locations", "app:health:search_appointments", "app:home:search",
        "app:images:generate", "app:images:generate_draft", "app:images:search",
        "app:mail:search", "app:maps:search", "app:math:calculate", "app:models3d:generate",
        "app:models3d:search", "app:music:generate", "app:news:search",
        "app:nutrition:search_recipes", "app:reminder:cancel-reminder",
        "app:reminder:list-reminders", "app:reminder:set-reminder",
        "app:shopping:search_products", "app:social_media:get-posts", "app:social_media:search",
        "app:tasks:create", "app:tasks:search", "app:travel:get_flight",
        "app:travel:price_calendar", "app:travel:search_connections", "app:travel:search_stays",
        "app:videos:create", "app:videos:generate", "app:videos:get_transcript",
        "app:videos:search", "app:weather:forecast", "app:weather:rain_radar",
        "app:web:read", "app:web:search", "app:workflows:create-or-modify",
        "app:workflows:search", "business-company-financial-result", "code-application",
        "code-code", "code-notebook", "code-repo", "design-icon-result", "docs-doc",
        "electronics-component", "electronics-pcb-schematic", "events-event", "file-file",
        "fitness-class", "fitness-location", "focus-mode-activation", "health-appointment",
        "home-listing", "image", "images-image-result", "mail-email", "maps", "maps-place",
        "math-plot", "mindmaps-mindmap", "models3d-model-result", "nutrition-recipe", "pdf",
        "recording", "sheets-sheet", "shopping-product", "social-media-post", "tasks-task",
        "travel-connection", "travel-stay", "videos-video", "weather-day", "web-website",
        "workflows-workflow"
    ]
    private let appSlugs = [
        "audio",
        "business",
        "calendar",
        "code",
        "design",
        "diagrams",
        "docs",
        "electronics",
        "events",
        "fitness",
        "health",
        "home",
        "images",
        "mail",
        "maps",
        "math",
        "mindmaps",
        "models3d",
        "music",
        "news",
        "nutrition",
        "pdf",
        "reminder",
        "sheets",
        "shopping",
        "social_media",
        "tasks",
        "travel",
        "videos",
        "weather",
        "web",
        "workflows"
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testFileArtifactFullscreenUsesFilenameMetadataAndSharedDownloadAction() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "code",
                               "--embed-registry-key", "file-file", "--embed-surface", "fullscreen",
                               "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let card = app.descendants(matching: .any)["file-embed-fullscreen"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["embed-header-title"].label, "berlin-weather.csv")
        XCTAssertEqual(app.staticTexts["embed-header-subtitle"].label, "text/csv · 24.0 KB")
        XCTAssertTrue(app.staticTexts["artifacts/reports/berlin-weather.csv"].exists)
        XCTAssertFalse(app.buttons["file-download-button"].exists,
                       "The file content card must not duplicate the shared toolbar download")
        XCTAssertGreaterThanOrEqual(card.frame.minX, 15)
        XCTAssertLessThanOrEqual(card.frame.maxX, app.frame.maxX - 15)
        attachScreenshot(name: "File artifact filename metadata and web card layout")
        let more = app.buttons["embed-more-button"]
        XCTAssertTrue(more.waitForExistence(timeout: 5))
        more.tap()
        XCTAssertTrue(app.buttons["embed-download-button"].waitForExistence(timeout: 5),
                      "An unexpired file link must remain available through More")
        attachScreenshot(name: "File artifact shared More download action")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,web-search.surface-parity
    func testGalleryProcessingVariantAndQuoteOpenUseSelectedState() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web",
                               "--embed-registry-key", "app:web:search", "--embed-surface", "preview",
                               "--embed-variant", "processing", "--dev-preview-theme", "dark"]
        app.launch()
        let marker = app.descendants(matching: .any)["dev-embed-canonical-preview"].firstMatch
        XCTAssertTrue(marker.waitForExistence(timeout: 10))
        XCTAssertEqual(marker.value as? String, "app:web:search|processing")
        let preview = app.buttons["embed-preview"].firstMatch
        XCTAssertTrue(preview.exists)
        XCTAssertEqual(preview.value as? String, "Loading")
        attachScreenshot(name: "Web search processing variant dark")
        app.terminate()

        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web",
                               "--embed-registry-key", "web-website", "--embed-surface", "quote",
                               "--embed-direction", "rtl", "--dev-preview-theme", "dark"]
        app.launch()
        let quote = app.buttons["dev-embed-quote-open"]
        XCTAssertTrue(quote.waitForExistence(timeout: 10))
        attachScreenshot(name: "Website quote dark RTL")
        quote.tap()
        XCTAssertTrue(app.descendants(matching: .any)["dev-embed-opened-fullscreen"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.descendants(matching: .any)["website-fullscreen-body"].waitForExistence(timeout: 10))
        attachScreenshot(name: "Website quote opened production fullscreen")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testGalleryLargeGroupCyclesDataVariants() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web",
                               "--embed-registry-key", "web-website", "--embed-surface", "group-large",
                               "--dev-preview-theme", "light"]
        app.launch()
        let group = app.descendants(matching: .any)["dev-embed-group-large"].firstMatch
        XCTAssertTrue(group.waitForExistence(timeout: 10))
        XCTAssertEqual(group.value as? String, "default")
        attachScreenshot(name: "Website large group default variant")
        app.buttons["dev-embed-large-next"].tap()
        XCTAssertEqual(group.value as? String, "richMetadata")
        XCTAssertFalse(app.descendants(matching: .any)["dev-embed-registry-missing"].exists)
        attachScreenshot(name: "Website large group rich metadata variant")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDoctorAppointmentCalendarActionUsesResponsiveHeaderAndExportsFile() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "health",
            "--embed-registry-key", "health-appointment", "--embed-surface", "fullscreen",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.buttons["external-provider-cta"].waitForExistence(timeout: 10))
        assertFullscreenSettled(app: app, key: "health-appointment")
        let header = app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch
        let map = app.descendants(matching: .any)["embed-location-map"].firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 5))
        let provider = app.buttons["external-provider-cta"]
        XCTAssertTrue(provider.isHittable, "The provider CTA must stay usable where it overlaps the map")
        XCTAssertEqual(provider.frame.height, 44, accuracy: 1)
        XCTAssertTrue(header.frame.contains(provider.frame), "The header must retain the entire provider button's hit bounds")
        XCTAssertEqual(map.frame.minY, provider.frame.midY, accuracy: 1,
                       "The map starts at the panel edge, under the middle of the overlapping provider CTA")
        XCTAssertEqual(header.frame.maxY - map.frame.minY, 22, accuracy: 1,
                       "The CTA's lower half is hit-test clearance, not an extra gap above the map")
        let calendar = app.buttons["embed-calendar-button"]
        if app.frame.width < 460 {
            let more = app.buttons["embed-more-button"]
            XCTAssertTrue(more.waitForExistence(timeout: 5))
            XCTAssertTrue(more.isHittable)
            XCTAssertFalse(calendar.exists)
            more.tap()
            XCTAssertTrue(app.buttons["embed-share-button"].waitForExistence(timeout: 5))
        } else {
            XCTAssertFalse(app.buttons["embed-more-button"].exists)
        }
        XCTAssertTrue(calendar.waitForExistence(timeout: 5))
        XCTAssertTrue(calendar.isHittable)
        XCTAssertEqual(calendar.label, "Add to calendar")
        attachScreenshot(name: "Appointment responsive calendar header action")
        calendar.tap()
        let export = app.otherElements["ShareSheet.RemoteContainerView"].firstMatch
        XCTAssertTrue(export.waitForExistence(timeout: 8), "The action must present the real ICS file export sheet")
        XCTAssertGreaterThan(export.frame.width, 0)
        XCTAssertTrue(app.frame.intersects(export.frame))
        // The system's share service exposes the file and actions from its remote process;
        // UIActivityViewController's host view is not an accessibility container.
        let filename = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "LP.CaptionBar.BottomCaption",
            "dr-sophie-m-ller-ophthalmologist-2026-04-03.ics")).firstMatch
        XCTAssertTrue(filename.waitForExistence(timeout: 5), "Export must contain the appointment's actual ICS file")
        for label in ["Copy", "Save to Files"] {
            let action = app.cells.matching(NSPredicate(format: "label == %@", label)).firstMatch
            XCTAssertTrue(action.waitForExistence(timeout: 5), "The file export must offer \(label)")
            XCTAssertTrue(action.isHittable, "The real \(label) export action must be usable")
        }
        attachScreenshot(name: "Appointment native calendar file export")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDoctorAppointmentFullscreenRendersLocationMapMarkerAndAddress() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "health",
            "--embed-registry-key", "health-appointment", "--embed-surface", "fullscreen",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let map = app.descendants(matching: .any)["embed-location-map"].firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 10), "Appointment with provider coordinates must show its map")
        XCTAssertGreaterThanOrEqual(map.frame.height, 150)
        let rendered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "rendered"), object: map)
        XCTAssertEqual(XCTWaiter.wait(for: [rendered], timeout: 20), .completed, "Real map tiles must finish rendering")
        let marker = app.descendants(matching: .any)["embed-location-marker"].firstMatch
        XCTAssertTrue(marker.waitForExistence(timeout: 5))
        XCTAssertTrue(marker.label.contains("Sophie Müller"))
        XCTAssertTrue(map.frame.intersects(marker.frame), "Doctor marker must be visible inside the actual map")
        XCTAssertGreaterThan(mapsGreenPixelCount(in: marker.screenshot().image), 20,
                             "The rendered pin must contain maps-start green (#11672D), not a black SVG")
        let address = app.staticTexts["health-appointment-address"]
        XCTAssertTrue(address.exists)
        XCTAssertTrue(address.label.contains("Maximilianstraße 12"))
        let zoom = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Zoom in")).firstMatch
        XCTAssertTrue(zoom.isHittable, "App-owned map controls remain usable")
        XCTAssertEqual(zoom.frame.width, 57, accuracy: 1,
                       "Deployed global Leaflet buttons use a 57pt pill")
        XCTAssertEqual(zoom.frame.height, 57, accuracy: 1)
        let zoomOut = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Zoom out")).firstMatch
        XCTAssertEqual(zoomOut.frame.minY, zoom.frame.maxY, accuracy: 1)
        XCTAssertEqual(zoomOut.frame.minX, zoom.frame.minX, accuracy: 1)
        attachScreenshot(name: "Doctor map green maps-start marker and primary gradient zoom pill")
        zoom.tap()
        XCTAssertTrue(marker.exists)
        attachScreenshot(name: "Rendered doctor practice map marker and provider address")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHealthSearchShowsDoctorSlotsAndAppointmentProviderLink() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "health",
            "--dev-health-search-route-preview",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let results = app.descendants(matching: .any)["health-search-results"].firstMatch
        XCTAssertTrue(results.waitForExistence(timeout: 10))
        let first = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Dr. Markus Reinholz")).firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        XCTAssertTrue(first.isHittable)
        XCTAssertFalse(app.staticTexts["health-appointment"].exists)
        attachScreenshot(name: "Health search doctor slots and provider metadata")
        first.tap()
        let route = app.staticTexts["dev-embed-active-route"].firstMatch
        XCTAssertTrue(waitForLabel(route, containing: "preview-health-search-fs-result-1", timeout: 5),
                      "The production doctor card must navigate to its actual child record")
        let details = app.descendants(matching: .any)["health-appointment-fullscreen"].firstMatch
        XCTAssertTrue(details.waitForExistence(timeout: 5))
        let provider = app.buttons["external-provider-cta"]
        XCTAssertTrue(provider.waitForExistence(timeout: 5))
        XCTAssertTrue(provider.isHittable)
        XCTAssertTrue(provider.label.contains("Jameda"))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Hautarzt")).firstMatch.exists)
        attachScreenshot(name: "Appointment date doctor specialty and booking provider CTA")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testCanonicalRegistryKeysRenderPreviewAndFullscreenWithoutGenericFallback() throws {
        // Collect every key's screenshot even if a preceding key fails. XCTest still
        // reports each assertion as a failure for the canonical parity gate.
        continueAfterFailure = true
        let requestedKey = ProcessInfo.processInfo.environment["EMBED_REGISTRY_KEY"]
        let requestedKeys = ProcessInfo.processInfo.environment["EMBED_REGISTRY_KEYS"]?
            .split(separator: ",")
            .map(String.init)
        let keys = requestedKeys ?? requestedKey.map { [$0] } ?? canonicalRegistryKeys
        XCTAssertEqual(canonicalRegistryKeys.count, 88, "The canonical native evidence inventory must track all generated registry keys.")

        captureCanonicalRegistryKeys(keys)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testMediaSearchRegistryKeysRenderPreviewAndFullscreen() {
        continueAfterFailure = true
        captureCanonicalRegistryKeys([
            "app:audio:generate", "app:audio:speak", "app:music:generate", "app:videos:generate",
            "app:videos:search", "app:web:search", "app:images:search", "image",
            "images-image-result", "pdf", "recording", "videos-video"
        ])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testRemotionVideoCreateControlsMatchNoMediaFixture() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "videos",
                               "--embed-registry-key", "app:videos:create",
                               "--embed-surface", "fullscreen"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["dev-embed-canonical-fullscreen"]
            .waitForExistence(timeout: 8))
        let video = app.buttons["video-create-tab-video"]
        let timeline = app.buttons["video-create-tab-timeline"]
        let code = app.buttons["video-create-tab-code"]
        let playback = app.buttons["video-create-playback"]
        XCTAssertTrue(video.exists)
        XCTAssertTrue(timeline.exists)
        XCTAssertTrue(code.exists)
        XCTAssertTrue(playback.exists)
        XCTAssertFalse(playback.isEnabled, "The canonical fullscreen fixture has no playable video")
        XCTAssertTrue(app.buttons["video-create-rerender"].exists)
        XCTAssertTrue(app.buttons["video-create-render-version"].exists)
        timeline.tap()
        let timelineSelected = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "selected"), object: timeline
        )
        XCTAssertEqual(XCTWaiter.wait(for: [timelineSelected], timeout: 3), .completed)
        XCTAssertFalse(app.buttons["video-create-playback"].exists)
        code.tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "ProductLaunch")).firstMatch
            .waitForExistence(timeout: 3))
        attachScreenshot(name: "Remotion create controls and source")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testImageGeneratePromptCopyUsesCanonicalPublicFixture() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "images",
                               "--embed-registry-key", "app:images:generate",
                               "--embed-surface", "fullscreen"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["dev-embed-canonical-fullscreen"]
            .waitForExistence(timeout: 8))
        let copy = app.buttons["image-generate-copy-prompt"]
        XCTAssertTrue(copy.waitForExistence(timeout: 5))
        copy.tap()
        // The app reads its own clipboard after writing it. Reading UIPasteboard
        // from the XCTest runner triggers iOS's cross-app paste permission alert.
        let copiedPrompt = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@",
                                   "A serene mountain landscape at sunset with vibrant orange and purple skies"),
            object: copy
        )
        XCTAssertEqual(XCTWaiter.wait(for: [copiedPrompt], timeout: 5), .completed)
        attachScreenshot(name: "Image generation prompt copy")
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testImageOriginalDownloadHeaderRequiresExplicitEncryptedOriginal() {
        for hasOriginal in [false, true] {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "images",
                                   "--embed-registry-key", "image", "--embed-surface", "fullscreen"]
            if hasOriginal { app.launchArguments.append("--dev-image-original-header") }
            app.launch()
            XCTAssertTrue(app.descendants(matching: .any)["dev-embed-canonical-fullscreen"]
                .waitForExistence(timeout: 8))
            let more = app.buttons["embed-more-button"]
            if hasOriginal {
                XCTAssertTrue(more.waitForExistence(timeout: 3))
                more.tap()
                XCTAssertTrue(app.buttons["embed-download-button"].waitForExistence(timeout: 3))
            } else {
                XCTAssertFalse(app.buttons["embed-download-button"].exists)
                XCTAssertFalse(more.exists)
            }
            attachScreenshot(name: "Image original download header \(hasOriginal ? "available" : "absent")")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testWebsitePreviewDescriptionUsesLoadedAndFailedImageWidths() {
        for (flag, expectedLoaded) in [
            ("--dev-website-loaded-preview", true),
            ("--dev-website-failed-preview", false)
        ] {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web",
                                   "--embed-registry-key", "web-website",
                                   "--embed-surface", "preview", flag]
            app.launch()
            XCTAssertTrue(app.descendants(matching: .any)["dev-embed-canonical-preview"]
                .waitForExistence(timeout: 8))
            let description = app.descendants(matching: .any)["website-preview-description"].firstMatch
            XCTAssertTrue(description.waitForExistence(timeout: 5))
            if expectedLoaded {
                let image = app.descendants(matching: .any)["website-preview-image"].firstMatch
                XCTAssertTrue(image.waitForExistence(timeout: 5))
                let decoded = XCTNSPredicateExpectation(
                    predicate: NSPredicate(format: "value == %@", "loaded"), object: image)
                XCTAssertEqual(XCTWaiter.wait(for: [decoded], timeout: 15), .completed,
                               "Public website preview image did not decode")
                XCTAssertLessThan(description.frame.width, 145,
                                  "Loaded image should retain the 40% description column")
            } else {
                let expanded = XCTNSPredicateExpectation(
                    predicate: NSPredicate { _, _ in description.frame.width > 220 }, object: nil)
                XCTAssertEqual(XCTWaiter.wait(for: [expanded], timeout: 15), .completed,
                               "Failed image kept reserving 60% of the preview card")
                XCTAssertFalse(app.descendants(matching: .any)["website-preview-image"].exists)
            }
            attachScreenshot(name: expectedLoaded
                ? "Website preview decoded image column"
                : "Website preview failed image full description")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testWebSearchPreviewShowsDecodedThumbnailStrip() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web",
                               "--embed-registry-key", "app:web:search",
                               "--embed-surface", "preview", "--dev-web-search-loaded-preview"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["dev-embed-canonical-preview"]
            .waitForExistence(timeout: 8))
        let strip = app.descendants(matching: .any)["web-search-thumbnail-strip"].firstMatch
        XCTAssertTrue(strip.waitForExistence(timeout: 5))
        let decoded = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "loaded"), object: strip)
        XCTAssertEqual(XCTWaiter.wait(for: [decoded], timeout: 15), .completed,
                       "Web search thumbnail strip did not decode a public image")
        attachScreenshot(name: "Web search decoded thumbnail strip")
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testWebSearchSVGThumbnailLoadsAndPaintsActualSource() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-preview", "--dev-preview-variant", "search-thumbnail",
                               "--dev-preview-theme", "light"]
        app.launch()
        let strip = app.descendants(matching: .any)["web-search-thumbnail-strip"].firstMatch
        XCTAssertTrue(strip.waitForExistence(timeout: 10))
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "loaded"), object: strip)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 20), .completed)
        XCTAssertEqual(strip.frame.height, 30, accuracy: 1)
        let screenshot = strip.screenshot()
        let bitmap = try XCTUnwrap(UIImage(data: screenshot.pngRepresentation)?.cgImage)
        var pixels = Data(count: bitmap.width * bitmap.height * 4)
        let bluePixels = try pixels.withUnsafeMutableBytes { buffer -> Int in
            let context = try XCTUnwrap(CGContext(data: buffer.baseAddress, width: bitmap.width, height: bitmap.height,
                bitsPerComponent: 8, bytesPerRow: bitmap.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.draw(bitmap, in: CGRect(x: 0, y: 0, width: CGFloat(bitmap.width), height: CGFloat(bitmap.height)))
            let bytes = buffer.bindMemory(to: UInt8.self)
            return stride(from: 0, to: bytes.count, by: 4).filter { index in
                let r = Int(bytes[index]), g = Int(bytes[index + 1]), b = Int(bytes[index + 2])
                return b > 150 && b - r > 40 && b - g > 20
            }.count
        }
        XCTAssertGreaterThan(bluePixels, 100, "The real selected favicon SVG must paint its blue gradient in the thumbnail strip")
        attachScreenshot(name: "Web search original SVG thumbnail loaded and painted")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testMediaFullscreenHeaderMetadataAndActions() {
        let cases: [(key: String, title: String, subtitle: String?, more: Bool)] = [
            ("image", "golden-gate-sunset.jpg", "JPEG · 2.3 MB", false),
            ("recording", "voice-memo-2026-03-10.webm", "0:42 · Voxtral Mini", false),
            ("videos-video", "Understanding Svelte 5 Runes — Complete Tutorial", nil, true)
        ]
        for item in cases {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web",
                                   "--embed-registry-key", item.key,
                                   "--embed-surface", "fullscreen"]
            app.launch()
            XCTAssertTrue(app.descendants(matching: .any)["dev-embed-canonical-fullscreen"]
                .waitForExistence(timeout: 8))
            let title = app.descendants(matching: .any)["embed-header-title"].firstMatch
            XCTAssertTrue(title.waitForExistence(timeout: 5))
            XCTAssertEqual(title.label, item.title)
            if let subtitle = item.subtitle {
                XCTAssertEqual(app.descendants(matching: .any)["embed-header-subtitle"].firstMatch.label,
                               subtitle)
            }
            XCTAssertEqual(app.buttons["embed-more-button"].exists, item.more)
            if !item.more { XCTAssertFalse(app.buttons["embed-share-button"].exists) }
            attachScreenshot(name: "Media fullscreen header|\(item.key)")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testVideosSearchFullscreenUsesThreePreviewCards() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "videos",
                               "--embed-registry-key", "app:videos:search",
                               "--embed-surface", "fullscreen"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["videos-search-fullscreen-results"]
            .waitForExistence(timeout: 8))
        for index in 1...3 {
            let card = app.descendants(matching: .any)["videos-search-result-preview-videos-search-result-\(index)"].firstMatch
            if !card.waitForExistence(timeout: 2) { app.swipeUp() }
            XCTAssertTrue(card.waitForExistence(timeout: 5))
            XCTAssertEqual(card.frame.width, 300, accuracy: 1)
            XCTAssertEqual(card.frame.height, 200, accuracy: 1)
        }
        let thirdCard = app.descendants(matching: .any)["videos-search-result-preview-videos-search-result-3"].firstMatch
        XCTAssertEqual(thirdCard.value as? String, "Building a Full App with SvelteKit 2")
        attachScreenshot(name: "Videos search three fullscreen cards")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
    func testCanonicalRegistryKeysRenderWideFullscreen() {
        continueAfterFailure = true
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        captureCanonicalRegistryKeys(canonicalRegistryKeys,
                                     surfaces: ["fullscreen"],
                                     viewportLabel: "ipad-landscape-light-ltr")
    }

    private func captureCanonicalRegistryKeys(
        _ keys: [String],
        surfaces: [String] = ["preview", "fullscreen"],
        viewportLabel: String = "iphone-light-ltr"
    ) {

        for key in keys {
            for surface in surfaces {
                let app = XCUIApplication()
                app.launchArguments = [
                    "--dev-preview", "embeds",
                    "--dev-preview-app", "web",
                    "--dev-preview-theme", "light",
                    "--embed-registry-key", key,
                    "--embed-surface", surface
                ]
                app.launchEnvironment["DEV_PREVIEW"] = "embeds"
                app.launchEnvironment["DEV_PREVIEW_APP"] = "web"
                app.launchEnvironment["DEV_PREVIEW_THEME"] = "light"
                app.launch()

                let identifier = "dev-embed-canonical-\(surface)"
                let canonical = app.descendants(matching: .any)[identifier]
                guard canonical.waitForExistence(timeout: 8) else {
                    XCTFail("Missing canonical \(surface) for \(key)")
                    attachScreenshot(name: "Embed parity missing|\(key)|\(surface)|\(viewportLabel)")
                    app.terminate()
                    continue
                }
                XCTAssertEqual(canonical.value as? String, "\(key)|default")
                XCTAssertFalse(app.descendants(matching: .any)["dev-embed-registry-missing"].exists, "Missing native fixture for \(key)")

                if key == "docs-doc" {
                    let canvas = app.descendants(matching: .any)["docs-document-\(surface)"]
                    if canvas.waitForExistence(timeout: 8) {
                        let painted = XCTNSPredicateExpectation(
                            predicate: NSPredicate(format: "value BEGINSWITH %@", "ready:"), object: canvas
                        )
                        XCTAssertEqual(XCTWaiter.wait(for: [painted], timeout: 12), .completed,
                                       "Document canvas did not finish painting for \(surface)")
                    } else {
                        XCTFail("Document canvas was absent for \(surface)")
                    }
                }

                if surface == "fullscreen" {
                    assertFullscreenSettled(app: app, key: key)
                } else {
                    let isAudioCard = ["app:audio:generate", "app:audio:speak", "recording"].contains(key)
                    let preview = key == "focus-mode-activation"
                        ? app.descendants(matching: .any)["focus-mode-bar"].firstMatch
                        : isAudioCard
                            ? app.descendants(matching: .any)["embed-preview-card"].firstMatch
                            : app.buttons["embed-preview"].firstMatch
                    if preview.waitForExistence(timeout: 3) {
                        let frame = preview.frame
                        let expectedWidth: CGFloat = key == "focus-mode-activation" ? 326 : 300
                        let expectedHeight: CGFloat = key == "focus-mode-activation" ? 61 : 200
                        XCTAssertEqual(frame.width, expectedWidth, accuracy: 1,
                                       "Preview width drift for \(key)")
                        XCTAssertEqual(frame.height, expectedHeight, accuracy: 1,
                                       "Preview height drift for \(key)")
                        let geometry = """
                        {"key":"\(key)","surface":"preview","viewportWidth":\(app.frame.width),"viewportHeight":\(app.frame.height),"x":\(frame.minX),"y":\(frame.minY),"width":\(frame.width),"height":\(frame.height)}
                        """
                        let attachment = XCTAttachment(string: geometry)
                        attachment.name = "Embed geometry|\(key)|preview|\(viewportLabel)"
                        attachment.lifetime = .keepAlways
                        add(attachment)
                    } else {
                        XCTFail("Missing measurable preview card for \(key)")
                    }
                }

                XCTAssertFalse(
                    app.staticTexts.matching(NSPredicate(format: "label == %@", key)).firstMatch.exists,
                    "\(key) rendered the generic raw-data fallback in \(surface)"
                )
                XCTAssertFalse(app.tables.firstMatch.exists, "\(key) rendered default List/table chrome")
                attachScreenshot(name: "Embed parity|\(key)|\(surface)|\(viewportLabel)")
                app.terminate()
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testEventSearchFullscreenPresentationReachesReady() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "web",
            "--embed-registry-key", "app:events:search", "--embed-surface", "fullscreen"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "web"
        app.launch()

        let canonical = app.descendants(matching: .any)["dev-embed-canonical-fullscreen"]
        XCTAssertTrue(canonical.waitForExistence(timeout: 8))
        XCTAssertEqual(canonical.value as? String, "app:events:search|default")
        assertFullscreenSettled(app: app, key: "app:events:search")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testTravelConnectionPreviewShowsCompactRouteAndTimes() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "travel",
            "--embed-registry-key", "travel-connection", "--embed-surface", "preview"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "travel"
        app.launch()

        let preview = app.descendants(matching: .any)["dev-embed-canonical-preview"]
        XCTAssertTrue(preview.waitForExistence(timeout: 8))
        XCTAssertTrue(app.staticTexts["connection-time"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["connection-route"].exists)
        XCTAssertEqual(app.staticTexts["embed-basic-info-title"].label, "MUC → LHR")
        attachScreenshot(name: "Travel connection compact route and times")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testAllEmbedPreviewAppsRenderProductChrome() throws {
        for appSlug in appSlugs {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", appSlug]
            app.launchEnvironment["DEV_PREVIEW"] = "embeds"
            app.launchEnvironment["DEV_PREVIEW_APP"] = appSlug
            app.launch()

            let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
            XCTAssertTrue(gallery.waitForExistence(timeout: 8), "\(appSlug) gallery did not load")

            let skillSection = app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "dev-preview-skill-"))
                .firstMatch
            XCTAssertTrue(skillSection.waitForExistence(timeout: 5), "\(appSlug) has no visible skill section")
            XCTAssertFalse(app.tables.firstMatch.exists, "Embed product UI must not render default List/table chrome")

            attachScreenshot(name: "Embed gallery \(appSlug)")
            app.terminate()
        }
    }

    // contract-test: direct surface=gui.apple assertions=code-run.surface-parity
    func testFinishedIndexHTMLRendersSourceInPreviewAndFullscreen() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "code",
                               "--dev-code-hydrated-index"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let sourcePreview = app.descendants(matching: .any)["code-embed-source-preview"].firstMatch
        XCTAssertTrue(sourcePreview.waitForExistence(timeout: 8), "Finished index.html remained in the processing preview")
        XCTAssertFalse(app.descendants(matching: .any)["code-embed-processing"].exists)

        let previewButton = app.buttons
            .matching(identifier: "embed-preview")
            .containing(.any, identifier: "code-embed-source-preview")
            .firstMatch
        XCTAssertTrue(previewButton.waitForExistence(timeout: 3), "Finished source was not inside a tappable embed preview")
        previewButton.tap()
        let sourcePanel = app.descendants(matching: .any)["code-source-panel"].firstMatch
        XCTAssertTrue(
            sourcePanel.waitForExistence(timeout: 5),
            "Fullscreen did not receive the hydrated index.html source"
        )
        XCTAssertFalse(app.staticTexts["Processing"].exists)
        attachScreenshot(name: "Finished index.html preview and fullscreen")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testSavedCodeRunOutputAppearsInPreview() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "code",
            "--dev-code-run-output-preview"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let output = app.descendants(matching: .any)["code-run-output-preview"].firstMatch
        XCTAssertTrue(output.waitForExistence(timeout: 8), "Saved run output did not replace source in the preview")
        XCTAssertTrue(output.label.contains("Run complete"))
        attachScreenshot(name: "Saved code run output preview")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.artifacts.chat-bound-versioned
    func testSavedCodeRunOutputReopensInFullscreenAndCanBeCopied() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "code",
            "--embed-registry-key", "code-code", "--embed-surface", "fullscreen",
            "--dev-code-run-output-preview"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let showOutput = app.buttons["embed-run-button"].firstMatch
        XCTAssertTrue(showOutput.waitForExistence(timeout: 8))
        showOutput.tap()
        let terminal = app.descendants(matching: .any)["code-run-terminal"].firstMatch
        XCTAssertTrue(terminal.waitForExistence(timeout: 5), "Saved output did not open in fullscreen")
        let savedText = app.descendants(matching: .any)
            .matching(identifier: "code-run-output-text")
            .matching(NSPredicate(format: "label CONTAINS %@", "Run complete"))
            .firstMatch
        XCTAssertTrue(savedText.waitForExistence(timeout: 3), "Saved output text was absent from the reopened terminal")
        let copy = app.buttons["code-run-copy-output"].firstMatch
        XCTAssertTrue(copy.isEnabled, "Saved output must remain copyable after reopening")
        copy.tap()
        attachScreenshot(name: "Reopened saved code output fullscreen")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testCodeFullscreenUsesSharedPIIRevealControl() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "code",
            "--embed-registry-key", "code-code", "--embed-surface", "fullscreen",
            "--dev-pii-embed-preview"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let toggle = app.buttons["embed-pii-toggle"].firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 8))
        XCTAssertEqual(toggle.value as? String, "false")
        let source = app.descendants(matching: .any)["code-source-panel"].firstMatch
        XCTAssertTrue(source.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "[HTML_NAME]")).firstMatch.exists)
        toggle.tap()
        XCTAssertEqual(toggle.value as? String, "true")
        XCTAssertTrue(source.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "OpenMates preview")).firstMatch.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testOwnerPIIMappingFollowsSelectedEmbedAndFailsClosedDuringNavigation() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "code",
            "--dev-owner-pii-navigation-preview"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let source = app.descendants(matching: .any)["code-source-panel"].firstMatch
        XCTAssertTrue(source.waitForExistence(timeout: 8))
        XCTAssertTrue(source.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Owner A")).firstMatch.waitForExistence(timeout: 3))

        app.buttons["embed-next"].tap()
        let header = app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch
        XCTAssertTrue(waitForValue(header, containing: "preview-owner-pii-b", timeout: 5),
                      "Next did not select the second embed")
        XCTAssertTrue(source.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "[COUNTERPARTY_1]")).firstMatch.waitForExistence(timeout: 3))
        XCTAssertFalse(source.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Owner A")).firstMatch.exists)

        app.buttons["dev-owner-pii-load-b"].tap()
        XCTAssertTrue(source.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Owner B")).firstMatch.waitForExistence(timeout: 3))
        XCTAssertFalse(source.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Owner A")).firstMatch.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.artifacts.chat-bound-versioned
    func testVersionedCodeEmbedFullscreenTimelineRendersAndRestores() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "code"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "code"
        app.launch()

        let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
        XCTAssertTrue(gallery.waitForExistence(timeout: 8), "Code embed gallery did not load")

        let timeline = app.descendants(matching: .any)["embed-version-timeline"]
        scrollUntilVisible(app: app, element: timeline)
        XCTAssertTrue(timeline.exists, "Versioned code embed timeline did not render")
        XCTAssertTrue(app.descendants(matching: .any)["embed-version-dot-1"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["embed-version-dot-3"].exists)

        app.descendants(matching: .any)["embed-version-dot-1"].tap()

        let historicalStatus = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Viewing historical version v1"))
            .firstMatch
        XCTAssertTrue(historicalStatus.waitForExistence(timeout: 3))

        let restoreButton = app.descendants(matching: .any)["embed-version-restore-button"]
        XCTAssertTrue(restoreButton.exists)
        restoreButton.tap()

        let confirmRestore = app.buttons
            .containing(NSPredicate(format: "label CONTAINS %@", "Confirm restore v1"))
            .firstMatch
        XCTAssertTrue(confirmRestore.waitForExistence(timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Embed timeline must not render default List/table chrome")

        attachScreenshot(name: "Versioned code embed timeline")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testSheetsPreviewAndFullscreenUseSpreadsheetChrome() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "sheets"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "sheets"
        app.launch()

        XCTAssertTrue(
            app.descendants(matching: .any)["sheet-preview-table"].waitForExistence(timeout: 8),
            "Sheets preview must render spreadsheet cells instead of a generic table card."
        )
        attachScreenshot(name: "Sheets preview")

        app.descendants(matching: .any)["embed-preview"].firstMatch.tap()

        XCTAssertTrue(
            app.descendants(matching: .any)["sheet-fullscreen-table"].waitForExistence(timeout: 5),
            "Sheets fullscreen must preserve spreadsheet-specific content."
        )
        XCTAssertFalse(app.tables.firstMatch.exists, "Sheets embed must not render default List/table chrome")
        attachScreenshot(name: "Sheets fullscreen")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCanonicalSheetFullscreenUsesWebFixtureAndEdgeToEdgeTable() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "sheets",
                               "--embed-registry-key", "sheets-sheet", "--embed-surface", "fullscreen",
                               "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let table = app.descendants(matching: .any)["sheet-fullscreen-table"].firstMatch
        XCTAssertTrue(table.waitForExistence(timeout: 10))
        let header = app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch
        // UICollectionViewCell retains button traits but XCTest may expose it
        // as a Cell; identify the actual control independently of SDK type.
        let filter = app.descendants(matching: .any)["sheet-filter-toggle"].firstMatch
        if !header.exists || !filter.exists {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Canonical sheet missing control accessibility hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            attachScreenshot(name: "Canonical sheet missing control")
        }
        XCTAssertTrue(header.exists)
        XCTAssertTrue(filter.exists)
        XCTAssertTrue(filter.isHittable)
        XCTAssertEqual(app.staticTexts["embed-header-title"].label, "Team Directory")
        XCTAssertEqual(app.staticTexts["embed-header-subtitle"].label, "8 rows × 6 columns")
        XCTAssertEqual(table.frame.minX, app.frame.minX, accuracy: 1)
        XCTAssertEqual(table.frame.width, app.frame.width, accuracy: 1)
        // The web spreadsheet clears its floating controls with one 70px gap.
        // Generic fullscreen padding must not add another gutter or top gap.
        XCTAssertEqual(filter.frame.minY - header.frame.maxY, 70, accuracy: 2)
        XCTAssertEqual(filter.frame.minX, app.frame.minX, accuracy: 1)
        // Sheet values are selectable UITextViews, matching web cell selection.
        let firstValue = app.textViews.matching(NSPredicate(format: "value == %@", "Alice Johnson")).firstMatch
        let lastValue = app.textViews.matching(NSPredicate(format: "value == %@", "Henry Davis")).firstMatch
        if !firstValue.exists || !lastValue.exists {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Canonical sheet cell accessibility hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            attachScreenshot(name: "Canonical sheet cell accessibility")
        }
        XCTAssertTrue(firstValue.isHittable)
        XCTAssertTrue(lastValue.isHittable)
        XCTAssertFalse(app.tables.firstMatch.exists)
        attachScreenshot(name: "Canonical sheet fullscreen web fixture and table geometry")
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testWebSearchPreviewShowsResultThumbnailStrip() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "web"
        app.launch()

        let strip = app.descendants(matching: .any)["web-search-thumbnail-strip"].firstMatch
        XCTAssertTrue(strip.waitForExistence(timeout: 8))
        scrollUntilHittable(app: app, element: strip)
        XCTAssertTrue(strip.isHittable)
        XCTAssertTrue(app.descendants(matching: .any)["web-search-thumbnail"].firstMatch.exists)
        attachScreenshot(name: "Web search thumbnail preview")
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testYouTubeWebSearchResultUsesVideoCardAndPlayer() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "web",
            "--dev-youtube-search-route-preview"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "web"
        app.launch()

        let route = app.staticTexts["dev-embed-active-route"].firstMatch
        XCTAssertTrue(route.waitForExistence(timeout: 8))
        XCTAssertTrue(route.isHittable, "YouTube search result route did not become visible")
        XCTAssertTrue(route.label.contains("preview-web-search-youtube-1"))

        let videoCard = app.descendants(matching: .any)["youtube-video-preview"].firstMatch
        XCTAssertTrue(videoCard.exists, "YouTube search result must use a video preview")
        let resultCard = app.buttons["embed-preview-preview-web-search-youtube-result-1"].firstMatch
        XCTAssertTrue(resultCard.waitForExistence(timeout: 5))
        XCTAssertTrue(resultCard.isHittable, "YouTube result was not tappable in the parent fullscreen grid")
        resultCard.tap()
        XCTAssertTrue(waitForLabel(route, containing: "preview-web-search-youtube-result-1", timeout: 5))

        let play = app.buttons["youtube-video-play"].firstMatch
        scrollUntilHittable(app: app, element: play)
        XCTAssertTrue(play.isHittable, "YouTube player must require a visible play action")
        play.tap()
        XCTAssertTrue(app.descendants(matching: .any)["youtube-video-player"].firstMatch.waitForExistence(timeout: 5))
        attachScreenshot(name: "YouTube web search video player")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testTaskWorkflowAndModelEmbedsUseSpecificNativeChrome() throws {
        let cases: [(appSlug: String, previewIdentifiers: [String], childFullscreenIdentifier: String)] = [
            ("tasks", ["task-create-embed-preview", "task-search-embed-preview", "task-embed-card"], "task-embed-fullscreen"),
            ("workflows", ["workflow-create-embed-preview", "workflow-search-embed-preview", "workflow-embed-card"], "workflow-embed-fullscreen"),
            ("models3d", ["models3d-search-preview", "models3d-result-card", "models3d-generate-preview"], "models3d-result-fullscreen")
        ]

        for testCase in cases {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", testCase.appSlug]
            app.launchEnvironment["DEV_PREVIEW"] = "embeds"
            app.launchEnvironment["DEV_PREVIEW_APP"] = testCase.appSlug
            app.launch()

            let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
            XCTAssertTrue(gallery.waitForExistence(timeout: 8), "\(testCase.appSlug) gallery did not load")

            for identifier in testCase.previewIdentifiers {
                let element = app.descendants(matching: .any)[identifier]
                scrollUntilVisible(app: app, element: element)
                XCTAssertTrue(element.exists, "\(testCase.appSlug) missing specific preview chrome: \(identifier)")
            }

            let routeHarness = app.descendants(matching: .any)["dev-embed-fullscreen-route-harness"]
            scrollUntilHittable(app: app, element: routeHarness)
            XCTAssertTrue(routeHarness.isHittable, "\(testCase.appSlug) fullscreen route harness did not become visible")

            let firstChildButton = app.buttons["dev-embed-route-open-first-child"]
            XCTAssertTrue(firstChildButton.waitForExistence(timeout: 3), "\(testCase.appSlug) has no parent-to-child fullscreen route")
            firstChildButton.tap()

            XCTAssertTrue(
                app.descendants(matching: .any)[testCase.childFullscreenIdentifier].waitForExistence(timeout: 5),
                "\(testCase.appSlug) child fullscreen did not render specific native chrome: \(testCase.childFullscreenIdentifier)"
            )
            XCTAssertFalse(app.tables.firstMatch.exists, "\(testCase.appSlug) embed product UI must not render default List/table chrome")
            attachScreenshot(name: "Embed specific chrome \(testCase.appSlug)")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.artifacts.parent-child-navigation
    func testFullscreenParentChildRouteStackReturnsToParentBeforeClosing() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "web"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "web"
        app.launch()

        let gallery = app.descendants(matching: .any)["dev-embed-preview-gallery"]
        XCTAssertTrue(gallery.waitForExistence(timeout: 8), "Web embed gallery did not load")

        let routeHarness = app.descendants(matching: .any)["dev-embed-fullscreen-route-harness"]
        scrollUntilHittable(app: app, element: routeHarness)
        XCTAssertTrue(routeHarness.isHittable, "Fullscreen route harness did not become visible")

        let routeLabel = app.staticTexts["dev-embed-active-route"]
        XCTAssertTrue(routeLabel.label.contains("preview-web-search-1"), "Parent fullscreen route was not active")

        let firstChildButton = app.buttons["dev-embed-route-open-first-child"]
        XCTAssertTrue(firstChildButton.isHittable, "First child route opener was not tappable")
        firstChildButton.tap()

        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-web-search-result-1", timeout: 5),
            "Opening a child from parent fullscreen did not make the child route active"
        )

        tapFirstHittableButton(app: app, identifier: "embed-minimize")
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-web-search-1", timeout: 5),
            "Closing child fullscreen did not return to the parent fullscreen route"
        )
        XCTAssertTrue(
            app.buttons["embed-minimize"].firstMatch.waitForExistence(timeout: 3),
            "Returning from a child must re-present the reused parent container"
        )
        XCTAssertTrue(
            app.buttons.matching(identifier: "embed-minimize").allElementsBoundByIndex.contains(where: { $0.isHittable }),
            "The returned parent controls must remain interactive"
        )

        tapFirstHittableButton(app: app, identifier: "embed-minimize")
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "none", timeout: 5),
            "Closing parent fullscreen did not return to the non-fullscreen state"
        )
        XCTAssertTrue(app.buttons["dev-embed-route-reset"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Embed fullscreen route stack must not render default List/table chrome")

        attachScreenshot(name: "Fullscreen parent child route stack")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testModels3DChildCloseRestoresInteractiveParentSurface() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "models3d"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "models3d"
        app.launch()

        let routeHarness = app.descendants(matching: .any)["dev-embed-fullscreen-route-harness"]
        scrollUntilHittable(app: app, element: routeHarness)
        XCTAssertTrue(routeHarness.isHittable, "3D model fullscreen route harness did not become visible")

        let routeLabel = app.staticTexts["dev-embed-active-route"]
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-models3d-search-1", timeout: 5),
            "The 3D model parent fullscreen route was not active"
        )

        let firstChildButton = app.buttons["dev-embed-route-open-first-child"]
        XCTAssertTrue(firstChildButton.waitForExistence(timeout: 3))
        firstChildButton.tap()
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-models3d-result-1", timeout: 5),
            "The 3D model child fullscreen route did not open"
        )

        tapFirstHittableButton(app: app, identifier: "embed-minimize")
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-models3d-search-1", timeout: 5),
            "Closing the 3D model child did not restore its parent"
        )
        XCTAssertTrue(
            app.buttons.matching(identifier: "embed-minimize").allElementsBoundByIndex.contains(where: { $0.isHittable }),
            "The restored 3D model parent fullscreen must remain interactive"
        )

        tapFirstHittableButton(app: app, identifier: "embed-minimize")
        let reset = app.buttons["dev-embed-route-reset"]
        XCTAssertTrue(reset.waitForExistence(timeout: 3))
        XCTAssertTrue(reset.isHittable, "Closing the parent must restore interaction to the underlying surface")
        reset.tap()
        XCTAssertTrue(
            waitForLabel(routeLabel, containing: "preview-models3d-search-1", timeout: 5),
            "The underlying surface remained unresponsive after closing 3D model fullscreen"
        )

        attachScreenshot(name: "3D model fullscreen dismissal remains interactive")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNewsSearchCentersPreviewAndOpensRegularArticleCardsWithImages() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-preview", "--dev-preview-variant", "news-search",
                               "--ui-test-embed-presentation"]
        app.launch()
        let query = app.staticTexts["news-search-query"]
        XCTAssertTrue(query.waitForExistence(timeout: 8))
        let provider = app.staticTexts["news-search-provider"]
        let details = app.descendants(matching: .any)["news-search-preview-details"].firstMatch
        XCTAssertTrue(provider.exists)
        XCTAssertGreaterThan(query.frame.minY, details.frame.minY + 20,
                             "The news details stack must be vertically centered below its thumbnail")
        XCTAssertLessThan(provider.frame.maxY, details.frame.maxY)
        attachScreenshot(name: "News search centered preview and search icon")
        let preview = app.buttons["embed-preview"].firstMatch
        XCTAssertTrue(preview.isHittable)
        preview.tap()
        let first = app.descendants(matching: .any)["embed-preview-preview-news-result-1"].firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 8))
        let articleButton = first.buttons["embed-preview"].firstMatch
        XCTAssertTrue(articleButton.waitForExistence(timeout: 3))
        XCTAssertEqual(first.frame.height, 200, accuracy: 1)
        XCTAssertEqual(first.frame.width, 320, accuracy: 1)
        let image = first.descendants(matching: .any)["news-preview-image"].firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 8))
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "loaded"), object: image)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 15), .completed)
        XCTAssertEqual(image.frame.width, 150, accuracy: 1)
        XCTAssertEqual(image.frame.height, 171, accuracy: 1)
        XCTAssertEqual(image.frame.maxX, first.frame.maxX, accuracy: 1)
        XCTAssertTrue(articleButton.label.contains("AI Advances Continue to Transform Software Development"))
        XCTAssertTrue(articleButton.isHittable)
        attachScreenshot(name: "News fullscreen regular image article cards")
        articleButton.tap()
        XCTAssertTrue(app.descendants(matching: .any)["website-fullscreen-body"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.staticTexts["embed-header-title"].label.contains("AI Advances Continue to Transform Software Development"))
        attachScreenshot(name: "News article drill down")
    }

    // contract-test: direct surface=gui.apple assertions=videos.transcript.surface-parity
    func testGroupedVideoTranscriptRendersPreviewAndFullscreenContent() throws {
        for surface in ["preview", "fullscreen"] {
            let app = XCUIApplication()
            app.launchArguments = [
                "--dev-preview", "embeds",
                "--dev-preview-app", "videos",
                "--embed-registry-key", "app:videos:get_transcript",
                "--embed-surface", surface
            ]
            app.launchEnvironment["DEV_PREVIEW"] = "embeds"
            app.launchEnvironment["DEV_PREVIEW_APP"] = "videos"
            app.launchEnvironment["DEV_TRANSCRIPT_METADATA_RESPONSE"] = """
                {"title":"Resolved transcript metadata fixture","channel_name":"Resolved fixture channel"}
                """
            app.launch()

            if surface == "preview" {
                XCTAssertTrue(app.descendants(matching: .any)["video-transcript-preview"].waitForExistence(timeout: 8))
                XCTAssertTrue(
                    app.staticTexts["Get Transcript"].waitForExistence(timeout: 5),
                    "The preview footer must use the localized web skill catalog name."
                )
                let title = app.staticTexts["video-transcript-title"]
                XCTAssertTrue(
                    waitForLabel(title, containing: "Resolved transcript metadata fixture", timeout: 5),
                    "Preview must resolve the real video title from the source URL when the transcript result contains no metadata."
                )
                XCTAssertTrue(
                    waitForLabel(app.staticTexts["video-transcript-subtitle"], containing: "Resolved fixture channel", timeout: 5),
                    "Preview must resolve the channel through the privacy-preserving preview endpoint."
                )
            } else {
                XCTAssertTrue(
                    app.staticTexts.matching(NSPredicate(
                        format: "label CONTAINS %@", "Resolved transcript metadata fixture"
                    )).firstMatch.waitForExistence(timeout: 8),
                    "Fullscreen must preserve metadata resolved from the transcript source URL."
                )
                XCTAssertTrue(
                    app.staticTexts.matching(NSPredicate(
                        format: "label CONTAINS %@", "Resolved fixture channel"
                    )).firstMatch.waitForExistence(timeout: 8),
                    "Fullscreen must preserve the resolved channel metadata."
                )
                XCTAssertTrue(
                    app.buttons["video-transcript-video-preview"].waitForExistence(timeout: 8),
                    "Fullscreen must include the linked web-style video preview above the transcript."
                )
                XCTAssertTrue(
                    waitForLabel(app.staticTexts["video-transcript-fullscreen-metadata"], containing: "words", timeout: 5),
                    "Fullscreen must show the transcript word count above the content."
                )
                let transcript = app.staticTexts["video-transcript-fullscreen-text"]
                XCTAssertTrue(transcript.waitForExistence(timeout: 8), "Grouped skill results must load the actual transcript in fullscreen.")
                XCTAssertTrue(transcript.label.contains("Grouped transcript fixture proof text"))
                XCTAssertFalse(app.descendants(matching: .any)["video-transcript-fullscreen-empty"].exists)
            }

            attachScreenshot(name: "Video transcript grouped result \(surface)")
            app.terminate()
        }
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func scrollUntilVisible(app: XCUIApplication, element: XCUIElement) {
        for _ in 0..<8 where !element.exists {
            app.swipeUp()
        }
    }

    private func scrollUntilHittable(app: XCUIApplication, element: XCUIElement) {
        for _ in 0..<10 where !element.isHittable {
            app.swipeUp()
        }
    }

    private func waitForLabel(_ element: XCUIElement, containing expected: String, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.label.contains(expected) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return element.label.contains(expected)
    }

    private func waitForValue(_ element: XCUIElement, containing expected: String, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if (element.value as? String)?.contains(expected) == true { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return (element.value as? String)?.contains(expected) == true
    }

    private func assertFullscreenSettled(app: XCUIApplication, key: String) {
        let header = app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch
        let close = app.buttons["embed-minimize"].firstMatch
        guard header.waitForExistence(timeout: 8) else {
            XCTFail("Fullscreen header missing for \(key)")
            return
        }
        guard close.waitForExistence(timeout: 3) else {
            XCTFail("Fullscreen close action missing for \(key)")
            return
        }

        let deadline = Date().addingTimeInterval(3)
        while Date() < deadline {
            let frame = header.frame
            if frame.width > 0,
               // The rendered banner reaches the top pixel; XCTest includes
               // up to 11pt of CTA/shadow inset in this grouped AX frame.
               frame.minY >= app.frame.minY - 1,
               frame.minY <= app.frame.minY + 12,
               close.isHittable {
                return
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTFail("Fullscreen did not settle visibly for \(key): header frame \(header.frame)")
    }

    private func tapFirstHittableButton(app: XCUIApplication, identifier: String) {
        let matches = app.buttons.matching(identifier: identifier).allElementsBoundByIndex
        if let button = matches.first(where: { $0.isHittable }) {
            button.tap()
            return
        }
        XCTFail("No hittable button found for identifier \(identifier)")
    }

    /// Inspect rendered annotation pixels, independent of its AX label or model
    /// color. Nearby map tiles are pale; the shared dark green pin is #11672D.
    private func mapsGreenPixelCount(in image: UIImage) -> Int {
        guard let source = image.cgImage else { return 0 }
        let width = source.width
        let height = source.height
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        return pixels.withUnsafeMutableBytes { bytes in
            guard let context = CGContext(data: bytes.baseAddress, width: width, height: height,
                bitsPerComponent: 8, bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)
            else { return 0 }
            context.draw(source, in: CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
            let rgba = bytes.bindMemory(to: UInt8.self)
            var count = 0
            for offset in stride(from: 0, to: rgba.count, by: 4) {
                let redMatches = abs(Int(rgba[offset]) - 17) <= 15
                let greenMatches = abs(Int(rgba[offset + 1]) - 103) <= 15
                let blueMatches = abs(Int(rgba[offset + 2]) - 45) <= 15
                if redMatches && greenMatches && blueMatches { count += 1 }
            }
            return count
        }
    }

}
