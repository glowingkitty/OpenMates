// Public synthetic URLs only; fragments never enter test diagnostics.
// Specification: specifications/features/workflows/specification.yml
import Combine
import XCTest
@testable import OpenMates

@MainActor
final class ExternalLinkDeliveryTests: XCTestCase {
    private let host = "app.dev.openmates.org"
    private let shortURL = URL(string: "https://app.dev.openmates.org/s/Abc123XY#Zz99qq")!

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testColdAndWarmSceneDeliveryKeepsLatestURLUntilExactlyOneConsumerTakesIt() {
        let center = ExternalLinkDeliveryCenter()
        let first = URL(string: "openmates://new-chat")!
        center.receive(first)
        XCTAssertEqual(center.pendingURL, first)
        XCTAssertEqual(center.takePendingURL(), first)
        XCTAssertNil(center.takePendingURL())

        center.receive(first)
        center.receive(shortURL)
        XCTAssertEqual(center.takePendingURL(), shortURL)
        XCTAssertNil(center.pendingURL)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testPostAssignmentDeliveryEventCanBeTakenSynchronously() {
        let center = ExternalLinkDeliveryCenter()
        var observedURL: URL?
        let subscription = center.didReceiveURL.sink { _ in
            observedURL = MainActor.assumeIsolated { center.takePendingURL() }
        }
        center.receive(shortURL)
        XCTAssertEqual(observedURL, shortURL)
        XCTAssertNil(center.pendingURL)
        withExtendedLifetime(subscription) {}
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testBrowsingWebActivityExtractsURLWithoutChangingHandoffRouting() {
        let browsing = NSUserActivity(activityType: NSUserActivityTypeBrowsingWeb)
        browsing.webpageURL = shortURL
        XCTAssertEqual(SceneExternalURLRouting.browsingWebURL(from: browsing), shortURL)

        let handoff = NSUserActivity(activityType: HandoffManager.viewChatActivityType)
        handoff.webpageURL = shortURL
        XCTAssertNil(SceneExternalURLRouting.browsingWebURL(from: handoff))
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testBrowserStartsOnlyWithSelectedHostShortShareAndStaysOnSharedWebPaths() {
        XCTAssertTrue(SharedLinkBrowserView.permitsInitialURL(shortURL, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsSharedNavigation(shortURL, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsSharedNavigation(
            URL(string: "https://\(host)/s/#Abc123XY-Zz99qq")!, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsSharedNavigation(
            URL(string: "https://\(host)/share/chat/public-chat#key=public")!, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsSharedNavigation(
            URL(string: "https://\(host)/share/embed/public-embed#key=public")!, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsSharedNavigation(
            URL(string: "https://\(host)/#share-chat-id=public-chat&key=public")!, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsSharedNavigation(
            URL(string: "https://\(host)/#embed-id=public-embed&fullscreen=true&key=public")!, selectedHost: host))

        let rejected = [
            "https://other.example/s/Abc123XY#Zz99qq",
            "https://user@\(host)/s/Abc123XY#Zz99qq",
            "http://\(host)/s/Abc123XY#Zz99qq",
            "https://\(host)/settings",
            "https://\(host)/s/Abc123XY/extra#Zz99qq",
            "https://\(host)/share/chat/" + String(repeating: "a", count: 129),
            "https://\(host)/#share-chat-id=" + String(repeating: "a", count: 129),
            "https://\(host)/#embed-id=public-embed&fullscreen=true",
            "https://\(host)/#embed-id=public-embed&fullscreen=false&key=public",
            "https://\(host)/#embed-id=" + String(repeating: "a", count: 129) + "&fullscreen=true&key=public",
        ]
        for text in rejected {
            let url = URL(string: text)!
            XCTAssertFalse(SharedLinkBrowserView.permitsInitialURL(url, selectedHost: host))
            XCTAssertFalse(SharedLinkBrowserView.permitsSharedNavigation(url, selectedHost: host))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testKnownCrossProfileHostsAndSelectedCustomHostCanOpenOnlyValidPublicLinks() {
        let production = URL(string: "https://app.openmates.org/s/Abc123XY#Zz99qq")!
        let productionRoot = URL(string: "https://openmates.org/s/Abc123XY#Zz99qq")!
        let dev = shortURL
        let custom = URL(string: "https://selfhost.example/s/Abc123XY#Zz99qq")!
        let workflow = URL(string: "https://app.openmates.org/share/workflow-template/wt_public#key=" +
            String(repeating: "A", count: 43))!

        XCTAssertTrue(SharedLinkBrowserView.permitsInitialURL(production, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsInitialURL(productionRoot, selectedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsInitialURL(dev, selectedHost: "app.openmates.org"))
        XCTAssertTrue(SharedLinkBrowserView.permitsInitialURL(custom, selectedHost: "selfhost.example"))
        XCTAssertTrue(SharedLinkBrowserView.permitsInitialURL(workflow, selectedHost: host))
        XCTAssertFalse(SharedLinkBrowserView.permitsInitialURL(custom, selectedHost: host))
        XCTAssertFalse(SharedLinkBrowserView.permitsInitialURL(
            URL(string: "https://unknown.example/s/Abc123XY#Zz99qq")!, selectedHost: host))
        XCTAssertFalse(SharedLinkBrowserView.permitsSharedNavigation(production, selectedHost: host),
                       "Once opened, the Mac web view must stay on the incoming link's host")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testTrustedSharePageCanRenderMediaSubframesWithoutOpeningThemAsMainPages() {
        let sharedPage = URL(string: "https://\(host)/share/embed/public-embed#key=public")!
        let video = URL(string: "https://www.youtube-nocookie.com/embed/abcdefghijk")!
        let blank = URL(string: "about:blank")!
        let srcdoc = URL(string: "about:srcdoc")!
        let localBlob = URL(string: "blob:https://\(host)/public-object")!

        XCTAssertTrue(SharedLinkBrowserView.permitsMediaSubframeNavigation(video,
            trustedMainURL: sharedPage, pinnedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsMediaSubframeNavigation(blank,
            trustedMainURL: sharedPage, pinnedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsMediaSubframeNavigation(srcdoc,
            trustedMainURL: sharedPage, pinnedHost: host))
        XCTAssertTrue(SharedLinkBrowserView.permitsMediaSubframeNavigation(localBlob,
            trustedMainURL: sharedPage, pinnedHost: host))
        XCTAssertFalse(SharedLinkBrowserView.permitsSharedNavigation(video, selectedHost: host),
            "The same media URL must not become a top-level page")
        XCTAssertFalse(SharedLinkBrowserView.permitsMediaSubframeNavigation(video,
            trustedMainURL: URL(string: "https://other.example/share/embed/public-embed")!, pinnedHost: host))
        XCTAssertFalse(SharedLinkBrowserView.permitsMediaSubframeNavigation(
            URL(string: "http://www.youtube-nocookie.com/embed/abcdefghijk")!,
            trustedMainURL: sharedPage, pinnedHost: host))
    }
}
