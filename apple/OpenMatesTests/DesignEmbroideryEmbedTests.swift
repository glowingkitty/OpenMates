// Embroidery result mapping and image authenticity badge model tests.
// Specification: specifications/features/chats/specification.yml
import XCTest
@testable import OpenMates

@MainActor
final class DesignEmbroideryEmbedTests: XCTestCase {
    private func codable(_ raw: [String: Any]) -> [String: AnyCodable] { raw.mapValues { AnyCodable($0) } }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFinishedDesignMapsContentFields() {
        let model = EmbroideryDesignModel(data: codable([
            "title": "Fox Patch", "width_mm": 80.4, "height_mm": 60, "stitch_count": 5400, "estimated_minutes": 65.0,
            "thread_length_m": 0.5, "hoop": "100x100", "fits_hoop": "yes", "fabric": "stretchy", "border_mm": 3,
            "threads": [["colour_hex": "#aabbcc", "name": "Sky", "stitch_count": 10]],
            "files": ["preview": ["s3_key": "a/b.png", "aes_nonce": "n"], "dst": ["s3_key": ""]],
            "aes_key": "k", "s3_base_url": "https://s3.example.org",
        ]))
        XCTAssertEqual(model.status, .finished)
        XCTAssertEqual(model.sizeLabel, "80 × 60 mm")
        XCTAssertEqual(model.hoopLabel, "100 × 100 mm")
        XCTAssertEqual(model.borderMm, 3)
        XCTAssertEqual(model.fitsHoop, .yes)
        XCTAssertEqual(model.threads.count, 1)
        XCTAssertNotNil(model.file("preview"))
        XCTAssertNil(model.file("dst"))
        XCTAssertEqual(model.downloadBaseName, "fox-patch")
        XCTAssertFalse(model.showsGraphicSwitch)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testErrorAndStatusFallbacks() {
        let failed = EmbroideryDesignModel(data: codable(["status": "error", "error_code": "timeout"]))
        XCTAssertEqual(failed.status, .error)
        XCTAssertEqual(failed.errorKey, "embeds.design.embroidery.error.timeout")
        let unknown = EmbroideryDesignModel(data: codable(["status": "error", "error_code": "nope"]))
        XCTAssertEqual(unknown.errorKey, "embeds.design.embroidery.error.generic")
        XCTAssertEqual(EmbroideryDesignModel(data: nil, fallbackStatus: .processing).status, .processing)
        XCTAssertEqual(EmbroideryDesignModel(data: nil).downloadBaseName, "embroidery-design")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFormatting() {
        XCTAssertEqual(EmbroideryDesignModel.formatDuration(47), "47 min")
        XCTAssertEqual(EmbroideryDesignModel.formatDuration(65), "1 h 5 min")
        XCTAssertEqual(EmbroideryDesignModel.formatDuration(0.2), "1 min")
        XCTAssertEqual(EmbroideryDesignModel.formatThreadLength(0.8), "80 cm")
        XCTAssertEqual(EmbroideryDesignModel.formatThreadLength(0.05), "10 cm")
        XCTAssertEqual(EmbroideryDesignModel.formatThreadLength(4.5), "4.5 m")
        XCTAssertEqual(EmbroideryDesignModel.formatThreadLength(62.4), "62 m")
        XCTAssertEqual(EmbroideryDesignModel.noteKey("border_added"), "embeds.design.embroidery.note.border_added")
        XCTAssertNil(EmbroideryDesignModel.noteKey("free_text"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAuthenticityBadgeThresholds() {
        func model(_ raw: [String: Any], key: String = "aiDetection") -> ImageAuthenticityModel? {
            ImageAuthenticityModel(data: codable([key: raw]))
        }
        XCTAssertEqual(model(["ai_generated": 0.9, "provider": "sightengine"])?.status, .aiGenerated)
        XCTAssertEqual(model(["ai_generated": 0.2], key: "ai_detection")?.status, .authentic)
        XCTAssertNil(model(["ai_generated": 0.5]))
        XCTAssertEqual(model(["ai_generated": 0.5, "status": "failed"])?.status, .failed)
        XCTAssertNil(ImageAuthenticityModel(data: nil))
        XCTAssertNotNil(model(["ai_generated": 0.9])?.providerURL)
        XCTAssertNil(model(["ai_generated": 0.9, "provider": "other_provider"])?.providerURL)
    }
}
