// Deterministic standalone local-model lab decoder proof; no checkpoint required.
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class LocalPrivacyFilterRuntimeTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pii-spans
    func testOverlappingWindowsCoverEveryTokenExactlyOnceIncludingShortTails() {
        for count in [0, 1, 63, 128, 255, 256, 257, 300, 383, 384, 385, 511, 512, 513, 1001] {
            var coverage = [Int](repeating: 0, count: count)
            for window in LocalPrivacyFilterDecoder.windows(tokenCount: count) {
                XCTAssertLessThanOrEqual(window.count, 256)
                XCTAssertGreaterThan(window.count, 0)
                for token in window.writeRange { coverage[window.start + token] += 1 }
            }
            XCTAssertTrue(coverage.allSatisfy { $0 == 1 }, "Coverage failed for \(count) tokens")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pii-spans
    func testViterbiRejectsIllegalArgmaxAndClosesSpanAtEnd() throws {
        let decoder = try LocalPrivacyFilterDecoder()
        var logits = [Float](repeating: -30, count: 2 * 33)
        logits[0] = 0
        logits[18] = 20 // I-person cannot begin a sequence.
        logits[17] = 10 // B-person is the valid start.
        logits[33 + 18] = 20 // I-person cannot end a sequence.
        logits[33 + 19] = 10
        logits[33] = 0
        XCTAssertEqual(try decoder.decode(logits), [17, 19])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pii-spans
    func testTransitionCalibrationChangesOptimalPath() throws {
        var logits = [Float](repeating: -30, count: 2 * 33)
        logits[0] = 0
        logits[33] = 0
        logits[33 + 20] = -1
        XCTAssertEqual(try LocalPrivacyFilterDecoder().decode(logits), [0, 0])
        let calibrated = try LocalPrivacyFilterDecoder(biases: [0, 3, 0, 0, 0, 0])
        XCTAssertEqual(try calibrated.decode(logits), [0, 20])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pii-spans
    func testGlobalGrammarRetainsEntityAcrossWindowOwnershipSeam() throws {
        var logits = [Float](repeating: -30, count: 300 * 33)
        for token in 0..<300 { logits[token * 33] = 0 }
        for token in 190...194 {
            let label = token == 190 ? 17 : (token == 194 ? 19 : 18)
            logits[token * 33 + label] = 20
        }
        let path = try LocalPrivacyFilterDecoder().decode(logits)
        XCTAssertEqual(Array(path[190...194]), [17, 18, 18, 18, 19])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pii-spans
    func testByteFragmentOffsetsPreserveEmojiGermanAndCombiningScalars() throws {
        let text = "👩🏽‍💻 Zoë e\u{301}"
        let map = LocalPrivacyFilterDecoder.utf16BoundaryMap(text)
        XCTAssertEqual(map.starts.count, text.utf8.count + 1)
        XCTAssertEqual(map.starts[1], 0)
        XCTAssertEqual(map.ends[1], 2) // Interior of the first emoji scalar rounds outward.
        XCTAssertEqual(map.starts.last, text.utf16.count)
        XCTAssertEqual(map.ends.last, text.utf16.count)
        let nameRange = (text as NSString).range(of: "Zoë")
        let prefix = String(text.prefix { $0 != "Z" }).utf8.count
        let byteRange = prefix..<(prefix + "Zoë".utf8.count)
        var logits = [Float](repeating: -30, count: 33)
        logits[20] = 20
        let spans = try LocalPrivacyFilterDecoder().spans(
            path: [20], emissions: logits, byteOffsets: [byteRange], text: text
        )
        XCTAssertEqual(spans.first?.range, nameRange)
        XCTAssertEqual((text as NSString).substring(with: try XCTUnwrap(spans.first).range), "Zoë")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pii-spans
    func testAdjacentSinglePeopleRemainSeparateEntities() throws {
        let text = "AdaBob"
        var logits = [Float](repeating: -30, count: 66)
        logits[20] = 20
        logits[53] = 20
        let spans = try LocalPrivacyFilterDecoder().spans(
            path: [20, 20], emissions: logits, byteOffsets: [0..<3, 3..<6], text: text
        )
        XCTAssertEqual(spans.map(\.range), [NSRange(location: 0, length: 3), NSRange(location: 3, length: 3)])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pii-spans
    func testMalformedLogitsAndCalibrationFailInsteadOfReportingCleanText() throws {
        let decoder = try LocalPrivacyFilterDecoder()
        XCTAssertThrowsError(try decoder.decode([0]))
        XCTAssertThrowsError(try decoder.decode([Float](repeating: .nan, count: 33)))
        XCTAssertThrowsError(try LocalPrivacyFilterDecoder(biases: [0]))
        XCTAssertThrowsError(try LocalPrivacyFilterDecoder(biases: [.infinity, 0, 0, 0, 0, 0]))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.serialized-cancellation
    func testCancelledRunNeverLoadsAssetsOrReportsNoPII() async throws {
        let runtime = LocalPrivacyFilterRuntime()
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try await runtime.run(.detectPII("Synthetic fixture"), directory: URL(fileURLWithPath: "/unused"))
        }
        do {
            _ = try await task.value
            XCTFail("Cancellation should propagate")
        } catch is CancellationError {
            // Expected; no download or inference took place.
        }
    }
}
