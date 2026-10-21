// Native proof of persistent query position while result thumbnails hydrate.
import XCTest
import UIKit

@MainActor
final class AppSkillInputPreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testSearchQueryRemainsVisibleCenteredAndFixedThroughResultHydration() {
        XCUIDevice.shared.orientation = .portrait
        for domain in ["images", "web", "news"] {
            var initialQueryFrame: CGRect?
            var initialCardFrame: CGRect?
            for variant in ["input-loading", "input-partial", "input-complete"] {
                let app = XCUIApplication()
                app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", domain,
                    "--embed-registry-key", "app:\(domain):search", "--embed-surface", "preview",
                    "--embed-variant", variant, "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
                app.launch()
                let query = app.staticTexts["\(domain)-search-query"]
                XCTAssertTrue(query.waitForExistence(timeout: 10))
                XCTAssertEqual(query.label, "Golden Gate Bridge")
                let card = app.buttons["embed-preview"]
                XCTAssertTrue(card.isHittable)
                XCTAssertTrue(card.frame.contains(query.frame))
                XCTAssertGreaterThan(query.frame.minY, card.frame.minY + 30)
                let geometry = XCTAttachment(string: "domain=\(domain) variant=\(variant) card=\(card.frame) query=\(query.frame) relativeQueryY=\(query.frame.minY - card.frame.minY)")
                geometry.name = "\(domain) \(variant) card and input geometry"
                geometry.lifetime = .keepAlways; add(geometry)
                if let initialCardFrame {
                    XCTAssertEqual(card.frame.minX, initialCardFrame.minX, accuracy: 1, "Gallery placement must stay fixed across input variants")
                    XCTAssertEqual(card.frame.minY, initialCardFrame.minY, accuracy: 1, "Gallery placement must stay fixed across input variants")
                    XCTAssertEqual(card.frame.width, initialCardFrame.width, accuracy: 1)
                    XCTAssertEqual(card.frame.height, initialCardFrame.height, accuracy: 1)
                } else { initialCardFrame = card.frame }
                if let initialQueryFrame {
                    XCTAssertEqual(query.frame.minX, initialQueryFrame.minX, accuracy: 1)
                    XCTAssertEqual(query.frame.minY, initialQueryFrame.minY, accuracy: 1,
                                   "Thumbnail/result arrival must not move the input text")
                    XCTAssertEqual(query.frame.height, initialQueryFrame.height, accuracy: 1)
                    if let initialCardFrame {
                        XCTAssertEqual(query.frame.minY - card.frame.minY,
                                       initialQueryFrame.minY - initialCardFrame.minY, accuracy: 1,
                                       "Input position within the fixed card must survive thumbnail and summary hydration")
                    }
                } else { initialQueryFrame = query.frame }
                if variant != "input-loading" {
                    let thumbnailID = domain == "images" ? "images-search-thumbnail" : "web-search-thumbnail"
                    let thumbnail = app.descendants(matching: .any)[thumbnailID].firstMatch
                    XCTAssertTrue(thumbnail.waitForExistence(timeout: 5))
                    XCTAssertLessThanOrEqual(thumbnail.frame.maxY, query.frame.minY + 1)
                }
                let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                attachment.name = "\(domain) \(variant) fixed input position"
                attachment.lifetime = .keepAlways; add(attachment)
                app.terminate()
            }
        }
    }
}
