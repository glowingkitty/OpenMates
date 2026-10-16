// Exact scroll geometry must not invalidate the transcript within one control region.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.layout.responsive-history, chats.surface.semantic-parity

import Foundation
import XCTest
@testable import OpenMates

final class ChatTranscriptScrollStateTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history,chats.surface.semantic-parity
    func testPixelOffsetsWithinOneRegionKeepObservableProjectionEqual() {
        let state = ChatTranscriptScrollState()
        let initial = state.record(contentOffsetY: 20, isAtBottom: false, bannerHeight: 200)
        // Equal projections suppress onScrollGeometryChange's action publication.
        for offset in 21...135 {
            XCTAssertEqual(state.record(contentOffsetY: CGFloat(offset), isAtBottom: false,
                                        bannerHeight: 200), initial)
        }
        XCTAssertEqual(state.contentOffsetY, 135, "Banner resize must retain the latest exact geometry")
        XCTAssertEqual(state.bannerOverlap(bannerHeight: 198), false,
                       "A banner resize must use the retained offset even without a scroll publication")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history,chats.surface.semantic-parity
    func testOnlyControlTransitionsChangeObservableProjection() {
        let state = ChatTranscriptScrollState()
        let offsets: [(CGFloat, Bool)] = [(0, false), (8, false), (9, false),
                                         (135, false), (136, false), (500, false),
                                         (500, true), (501, true), (501, false), (0, false)]
        var previous: ChatScrollBoundaries?
        var published: [ChatScrollBoundaries] = []
        for (offset, bottom) in offsets {
            let next = state.record(contentOffsetY: offset, isAtBottom: bottom, bannerHeight: 200)
            if next != previous { published.append(next) }
            previous = next
        }
        XCTAssertEqual(published, [
            .init(isAtTop: true, isAtBottom: false, overlapsBanner: true),
            .init(isAtTop: false, isAtBottom: false, overlapsBanner: true),
            .init(isAtTop: false, isAtBottom: false, overlapsBanner: false),
            .init(isAtTop: false, isAtBottom: true, overlapsBanner: false),
            .init(isAtTop: false, isAtBottom: false, overlapsBanner: false),
            .init(isAtTop: true, isAtBottom: false, overlapsBanner: true),
        ])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history,chats.surface.semantic-parity
    func testChatOrAccountResetDropsExactOffsetAndRestoresInitialRegion() {
        let state = ChatTranscriptScrollState()
        let old = state.record(contentOffsetY: 300, isAtBottom: true, bannerHeight: 200)
        state.reset()
        XCTAssertEqual(state.contentOffsetY, 0)
        XCTAssertEqual(state.bannerOverlap(bannerHeight: 200), true)
        XCTAssertNil(state.bannerOverlap(bannerHeight: 0), "An absent banner must not change overlay state")
        let initial = state.record(contentOffsetY: -40, isAtBottom: false, bannerHeight: 200)
        XCTAssertNotEqual(initial, old)
        XCTAssertEqual(initial, .init(isAtTop: true, isAtBottom: false, overlapsBanner: true))
        XCTAssertEqual(state.contentOffsetY, 0, "Overscroll uses the existing nonnegative normalization")
        XCTAssertEqual(state.bannerOverlap(bannerHeight: 64), false)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history,chats.surface.semantic-parity
    func testResetRecomputesOverlapUsingAlreadyMeasuredUnchangedBanner() {
        let state = ChatTranscriptScrollState()
        for measuredHeight: CGFloat in [48, 64, 200] {
            _ = state.record(contentOffsetY: 300, isAtBottom: false, bannerHeight: measuredHeight)
            XCTAssertEqual(state.bannerOverlap(bannerHeight: measuredHeight), false)
            state.reset()
            // No new banner geometry event: reuse the existing measurement,
            // including short banners whose overlap must remain false at top.
            XCTAssertEqual(state.bannerOverlap(bannerHeight: measuredHeight), measuredHeight > 64)
        }
    }
}
