// Tests of the small embed card parity fixes: event provider badges, ground
// transport route labels and the video AI-generated badge rule.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedPreview.svelte
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/app-skills/videos-generate/specification.yml
// Assertions: videos-generate.provenance.ai-label, events-search.surface-parity, travel-search.realtime.source-faithful
import XCTest
@testable import OpenMates

final class EmbedCardParityFixesTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=events-search.surface-parity
    func testProviderBadgeUsesIconOrInitialNeverEmpty() {
        XCTAssertTrue(EventProviderBadgeModel.hasIcon("web"))
        XCTAssertFalse(EventProviderBadgeModel.hasIcon("my_provider"))
        XCTAssertEqual(EventProviderBadgeModel.initial(for: "my_provider"), "M")
        XCTAssertEqual(EventProviderBadgeModel.initial(for: "google_events"), "G")
    }

    // contract-test: supporting surface=gui.apple assertions=travel-search.realtime.source-faithful
    func testGroundTransportShowsPlaceNotStopCode() {
        XCTAssertEqual(TravelValue.routeLabel(from: "Vienna Erdberg (VIB)", transportMethod: "bus"), "Vienna Erdberg")
        XCTAssertEqual(TravelValue.routeLabel(from: "Munich (MUC)", transportMethod: "airplane"), "MUC")
        XCTAssertEqual(TravelValue.routeLabel(from: "Munich (MUC)", transportMethod: nil), "MUC")
    }

    // contract-test: supporting surface=gui.apple assertions=videos-generate.provenance.ai-label
    func testVideoBadgeOnlyForGenerativeClips() {
        XCTAssertTrue(VideoAuthenticityBadge.isGenerative(madeBy: nil))
        XCTAssertTrue(VideoAuthenticityBadge.isGenerative(madeBy: "generative"))
        XCTAssertFalse(VideoAuthenticityBadge.isGenerative(madeBy: "composed"))
    }
}
