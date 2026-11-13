// Slides deck viewer state and colour mapping. Deck parsing itself is proven by
// the Rust test `view_slides` in the apple-bindings crate.
import XCTest
@testable import OpenMates

@MainActor
final class SlidesDeckRendererTests: XCTestCase {
    private func element(id: String, step: UInt32) -> SlideElementRecord {
        SlideElementRecord(
            id: id, kind: .shape, x: 0, y: 0, w: 10, h: 10, step: step, animate: nil, hidden: false,
            runs: [], fontSize: 40, bold: false, italic: false, align: "left", color: nil,
            fontFamily: nil, isHeading: false, embedRef: nil, videoProvider: nil, alt: "", fit: nil,
            shapeKind: "rect", stroke: nil, title: "", text: "", href: "", items: [])
    }

    private func deck(steps: [[UInt32]]) -> SlideDeckRecord {
        SlideDeckRecord(
            title: "Demo", aspect: "16:9", width: 1920, height: 1080, template: "builtin:plain",
            slides: steps.enumerated().map { offset, list in
                SlideRecord(
                    id: "s\(offset)", transition: nil, notes: "",
                    elements: list.enumerated().map { element(id: "e\($0.offset)", step: $0.element) })
            })
    }

    // contract-test: supporting surface=gui.apple assertions=slides.render.preview-and-fullscreen
    func testNavigationWalksBuildStepsThenSlides() {
        var navigation = SlidesDeckNavigation(deck: deck(steps: [[0, 1], [0]]))
        XCTAssertEqual(navigation.positionLabel, "1 / 2")
        XCTAssertFalse(navigation.canGoPrevious)
        navigation.next()
        XCTAssertEqual(navigation.step, 1)
        navigation.next()
        XCTAssertEqual(navigation.positionLabel, "2 / 2")
        XCTAssertFalse(navigation.canGoNext)
        navigation.previous()
        XCTAssertEqual(navigation.positionLabel, "1 / 2")
        XCTAssertEqual(navigation.step, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=slides.render.preview-and-fullscreen
    func testSelectResetsStepAndIgnoresOutOfRange() {
        var navigation = SlidesDeckNavigation(deck: deck(steps: [[1], [0], [0]]))
        navigation.select(2)
        XCTAssertEqual(navigation.positionLabel, "3 / 3")
        navigation.select(9)
        XCTAssertEqual(navigation.index, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=slides.render.preview-and-fullscreen
    func testHexColorParsing() {
        XCTAssertNotNil(SlideTemplateColors.hex("#ff8800"))
        XCTAssertNotNil(SlideTemplateColors.hex("#f80"))
        XCTAssertNil(SlideTemplateColors.hex("ff8800"))
        XCTAssertNil(SlideTemplateColors.color(nil))
    }

    // contract-test: supporting surface=gui.apple assertions=slides.render.preview-and-fullscreen
    func testCountLabel() {
        XCTAssertEqual(SlidesDeckContent.countLabel(0), "")
    }
}
