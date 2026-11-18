// Apple body embed slots follow the shared core rule for skill-invocation embeds.
// Specification: specifications/architecture/app-skill-execution/specification.yml
import XCTest
@testable import OpenMates

final class BodyEmbedSlotProjectionTests: XCTestCase {
    private func record(_ id: String, type: String, status: EmbedStatus = .finished, children: [String]? = nil) -> EmbedRecord {
        EmbedRecord(id: id, type: type, status: status, data: .raw([:]), parentEmbedId: nil,
            appId: "web", skillId: "search", embedIds: children?.joined(separator: "|"), createdAt: nil)
    }

    private func project(_ group: [EmbedRecord], all: [EmbedRecord]) -> [BodyEmbedSlotView] {
        BodyEmbedSlotProjection.project(embeds: group, allEmbedRecords: Dictionary(uniqueKeysWithValues: all.map { ($0.id, $0) }))
    }

    // contract-test: direct surface=gui.apple assertions=app-skills.answer.only-result-embeds-in-body
    func testInvocationWithKnownChildrenRendersActivityAndChildCards() {
        let parent = record("call", type: "app-skill-use", children: ["r1", "r2"])
        let r1 = record("r1", type: "website"), r2 = record("r2", type: "website")
        let slots = project([parent], all: [parent, r1, r2])
        XCTAssertEqual(slots, [.activity(parent), .card(r1), .card(r2)])
    }

    // contract-test: direct surface=gui.apple assertions=app-skills.answer.only-result-embeds-in-body
    func testInvocationWithUnknownChildrenKeepsActivityThenHiddenPlaceholder() {
        let parent = record("call", type: "app-skill-use", status: .processing, children: nil)
        let slots = project([parent], all: [parent])
        XCTAssertEqual(slots, [.activity(parent)])
        let again = BodyEmbedSlotProjection.project(
            embeds: [parent], allEmbedRecords: [parent.id: parent], activityIds: ["call"])
        XCTAssertEqual(again, [.hidden(embedId: "call")])
    }

    // contract-test: direct surface=gui.apple assertions=app-skills.answer.only-result-embeds-in-body
    func testRunningInvocationKeepsResultsPendingEvenWithEarlyChildIds() {
        let parent = record("call", type: "app-skill-use", status: .processing, children: ["r1"])
        let r1 = record("r1", type: "website")
        XCTAssertEqual(project([parent], all: [parent, r1]), [.activity(parent)])
    }

    // contract-test: direct surface=gui.apple assertions=app-skills.answer.only-result-embeds-in-body
    func testNonInvocationEmbedStaysACard() {
        let image = record("img", type: "image")
        XCTAssertEqual(project([image], all: [image]), [.card(image)])
    }
}
