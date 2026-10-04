// Fixed footer allocation and calendar expansion preserve minimum readable lanes.
import XCTest
@testable import OpenMates

@MainActor
final class EmbedResponsiveGeometryTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testDetailsAllocateSpaceForEntireFooterAtCompactAndLargeSizes() {
        XCTAssertEqual(EmbedPreviewFooterLayout.height, 61)
        XCTAssertEqual(EmbedPreviewFooterLayout.detailsHeight(cardHeight: 200), 139)
        XCTAssertEqual(EmbedPreviewFooterLayout.detailsHeight(cardHeight: 400), 339)
        XCTAssertEqual(EmbedPreviewFooterLayout.detailsHeight(cardHeight: 40), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testWideCalendarFillsMeasuredContentWidthWithoutAWindowDefault() {
        let minimum: [CGFloat] = [88, 176, 88, 88, 88, 88, 88]
        for width in [CGFloat(900), 1200, 1560] {
            let columns = EmbedCalendarColumnLayout.widths(minimumWidths: minimum,
                availableWidth: width, hasTimeColumn: true)
            XCTAssertEqual(columns.reduce(0, +) + 44, width, accuracy: 0.001)
            for (actual, required) in zip(columns, minimum) { XCTAssertGreaterThanOrEqual(actual, required) }
        }
        let dateOnly = EmbedCalendarColumnLayout.widths(minimumWidths: minimum,
            availableWidth: 1200, hasTimeColumn: false)
        XCTAssertEqual(dateOnly.reduce(0, +), 1200, accuracy: 0.001)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testPhoneCalendarKeepsReadableOverlapsInScrollableGrid() {
        let minimum: [CGFloat] = [88, 440, 88, 88, 88, 88, 88]
        let columns = EmbedCalendarColumnLayout.widths(minimumWidths: minimum,
            availableWidth: 298, hasTimeColumn: true)
        XCTAssertEqual(columns, minimum)
        XCTAssertGreaterThan(columns.reduce(0, +) + 44, 298)
        XCTAssertEqual(columns[1] / 5 - 6, 82)
        XCTAssertTrue(EmbedCalendarColumnLayout.widths(minimumWidths: [],
            availableWidth: 1200, hasTimeColumn: false).isEmpty)
    }
}
