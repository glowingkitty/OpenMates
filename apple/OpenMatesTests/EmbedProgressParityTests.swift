import XCTest
@testable import OpenMates

/// Presentation glue for the core's embed progress: JSON decoding, seq ordering, translation.
@MainActor
final class EmbedProgressParityTests: XCTestCase {
    private func frame(total: Int, done: Int, results: Int, seq: Int) -> [String: AnyCodable] {
        ["progress": AnyCodable([
            "sources_total": total, "sources_done": done, "result_count": results, "seq": seq,
        ] as [String: Any])]
    }

    // contract-test: supporting surface=gui.apple assertions=app-skills.progress.live-status
    func testHigherSeqReplacesAndLowerSeqIsIgnored() {
        var tracker = EmbedProgressTracker()
        XCTAssertTrue(tracker.update(from: frame(total: 4, done: 1, results: 3, seq: 2)))
        XCTAssertTrue(tracker.update(from: frame(total: 4, done: 2, results: 3, seq: 3)))
        XCTAssertFalse(tracker.update(from: frame(total: 4, done: 0, results: 0, seq: 2)))
        XCTAssertEqual(tracker.current?.sourcesDone, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=app-skills.progress.live-status
    func testMissingOrMalformedProgressShowsNothing() {
        var tracker = EmbedProgressTracker()
        XCTAssertFalse(tracker.update(from: nil))
        XCTAssertFalse(tracker.update(from: ["progress": AnyCodable("nope")]))
        XCTAssertFalse(tracker.update(from: frame(total: 0, done: 0, results: 0, seq: 1)))
        XCTAssertNil(tracker.presentation)
    }

    // contract-test: supporting surface=gui.apple assertions=app-skills.progress.live-status
    func testPresentationPrefixesDoneOverTotalBeforeResults() {
        let line = EmbedProgressLineRecord(
            key: "embeds.progress_results", valueNames: ["count"], valueNumbers: [17], prefix: "2/4 · ")
        let text = EmbedProgressTracker.present(line).text
        XCTAssertTrue(text.hasPrefix("2/4 · "))
        XCTAssertFalse(text.contains("{count}"))
    }
}
