// Synthetic assets and PCM only; no model weights or inference.
// Specification: specifications/features/apple-local-model-lab/specification.yml
import XCTest
@testable import OpenMates
final class LocalNeuralTTSTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.local-execution
    func testSupertonicChunkingPreservesAbbreviationsAndDefaultBound() {
        #if canImport(OnnxRuntimeBindings)
        XCTAssertEqual(ST3splitSentences("Dr. Smith speaks. Hello world."),
                       ["Dr. Smith speaks. ", "Hello world."])
        let chunks = ST3chunkText(String(repeating: "Hello world. ", count: 50))
        XCTAssertGreaterThan(chunks.count, 1)
        XCTAssertTrue(chunks.allSatisfy { $0.count <= 300 })
        #endif
    }
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.local-execution
    func testSupertonicChunkingBoundsUnspacedCJKWithoutLosingCharacters() {
        #if canImport(OnnxRuntimeBindings)
        let text = String(repeating: "日本語", count: 121)
        let chunks = ST3chunkText(text, maxLen: 120)
        XCTAssertEqual(chunks.map(\.count), [120, 120, 120, 3])
        XCTAssertEqual(chunks.joined(), text)
        #endif
    }
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.local-execution
    func testSupertonicChunkingPreservesOversizedWordGraphemeBoundaries() {
        #if canImport(OnnxRuntimeBindings)
        let graphemes = "e\u{301}👨‍👩‍👧‍👦"
        let text = String(repeating: graphemes, count: 180)
        let chunks = ST3chunkText(text)
        XCTAssertEqual(chunks.map(\.count), [300, 60])
        XCTAssertEqual(chunks[0], String(repeating: graphemes, count: 150))
        XCTAssertEqual(chunks[1], String(repeating: graphemes, count: 30))
        XCTAssertEqual(chunks.joined(), text)
        #endif
    }
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.local-execution
    func testSupertonicChunkingCountsAndPreservesCommaSeparatorsAtBoundary() {
        #if canImport(OnnxRuntimeBindings)
        for text in ["aaaaa, bbbb, c", "short, " + String(repeating: "x", count: 21) + ", end"] {
            let chunks = ST3chunkText(text, maxLen: 10)
            XCTAssertTrue(chunks.allSatisfy { !$0.isEmpty && $0.count <= 10 })
            XCTAssertEqual(chunks.joined(), text)
        }
        #endif
    }
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.local-execution
    func testWAVHeaderClampsSamplesAndReportsMonoRate() throws {
        let data = try LocalTTSWAV.encode(samples: [-2, 0, 2], sampleRate: 24_000)
        XCTAssertEqual(data.count, 50)
        XCTAssertEqual(String(data: data.prefix(4), encoding: .ascii), "RIFF")
        XCTAssertEqual(Array(data[24..<28]), [0xc0, 0x5d, 0, 0])
        XCTAssertEqual(Array(data[44..<50]), [1, 128, 0, 0, 255, 127])
    }
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.local-execution
    func testInvalidPCMIsRejectedBeforeCreatingOutput() {
        let invalid: [[Float]] = [[], [.nan], [.infinity]]
        for samples in invalid {
            XCTAssertThrowsError(try LocalTTSWAV.encode(samples: samples, sampleRate: 24_000))
        }
        XCTAssertThrowsError(try LocalTTSWAV.encode(samples: [0], sampleRate: 0))
        XCTAssertThrowsError(try LocalTTSWAV.encode(samples: [Float](repeating: 0, count: 960_001), sampleRate: 8_000))
    }
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.availability,apple-local-model-lab.local-execution
    func testSelectedExactModelsValidateVoicesLanguagesAndInputBounds() throws {
        try LocalTTSSynthesisInput(text: "Hallo Welt", voice: "F1", language: "de", steps: 8).validate(for: .supertonic3)
        XCTAssertThrowsError(try LocalTTSSynthesisInput(text: "Hello", voice: "../F1", language: "en", steps: 8).validate(for: .supertonic3))
        XCTAssertThrowsError(try LocalTTSSynthesisInput(text: "Hello", voice: "F1", language: "en", steps: 0).validate(for: .supertonic3))
        XCTAssertThrowsError(try LocalTTSSynthesisInput(text: String(repeating: "x", count: 2_001), voice: "F1", language: "en", steps: 8).validate(for: .supertonic3))
    }
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads,apple-local-model-lab.availability
    func testApprovedTTSManifestUsesOnlyPinnedExactModelAssets() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "catalog", withExtension: "json"))
        let models = try JSONDecoder().decode(LocalModelCatalog.self, from: Data(contentsOf: url)).validated()
        XCTAssertEqual(Set(models.map(\.id)), [.whisper, .privacyFilter, .supertonic3])
        let supertonic = try XCTUnwrap(models.first { $0.id == .supertonic3 })
        XCTAssertEqual(supertonic.revision, "aafc6e32416a594460b32413efc49d7fe4ce6d46")
        XCTAssertEqual(supertonic.estimatedSizeBytes, 401_291_751)
        XCTAssertEqual(supertonic.files.filter { $0.path.hasSuffix(".onnx") }.count, 4)
    }
}
