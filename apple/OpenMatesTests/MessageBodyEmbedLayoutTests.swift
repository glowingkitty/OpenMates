import XCTest
@testable import OpenMates

final class MessageBodyEmbedLayoutTests: XCTestCase {
    private func group(_ id: String, type: String? = nil) -> MarkdownBlock {
        .embedGroup([MarkdownEmbedReference(value: id, isRef: true, isLargePreview: true, type: type)])
    }

    // contract-test: direct surface=gui.apple assertions=app-skills.answer.only-result-embeds-in-body
    func testSkillUseReferenceIsNeverShownInBody() {
        XCTAssertFalse(MessageBodyEmbedLayout.mayShow(reference: "x", type: "app-skill-use"))
        XCTAssertFalse(MessageBodyEmbedLayout.mayShow(reference: "generated-media-images-0123456789ab", type: nil))
        XCTAssertTrue(MessageBodyEmbedLayout.mayShow(reference: "slug", type: "image"))
    }

    // contract-test: direct surface=gui.apple assertions=app-skills.answer.only-result-embeds-in-body
    func testHiddenSkillGroupIsNotCounted() {
        let blocks: [MarkdownBlock] = [group("p", type: "app-skill-use"), group("a"), group("b")]
        let placed = MessageBodyEmbedLayout.place(blocks: blocks, typeFor: { _ in nil })
        XCTAssertEqual(placed.map(\.carouselIndex), [-1, 0, 1])
        XCTAssertEqual(placed.map(\.carouselTotal), [0, 2, 2])
    }

    // contract-test: supporting surface=gui.apple assertions=app-skills.answer.only-result-embeds-in-body
    func testConsecutiveEmbedsFormOneRunAndTextSplitsRuns() {
        let blocks: [MarkdownBlock] = [group("a"), .paragraph(""), group("b"), .paragraph("text"), group("c")]
        let placed = MessageBodyEmbedLayout.place(blocks: blocks, typeFor: { _ in nil })
        XCTAssertEqual(placed.map(\.sourceIndex), [0, 2, 3, 4])
        XCTAssertEqual(placed.map(\.carouselTotal), [2, 2, 0, 1])
    }
}
