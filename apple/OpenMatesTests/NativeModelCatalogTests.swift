import XCTest
@testable import OpenMates
final class NativeModelCatalogTests: XCTestCase {
    private let fixture = #"{"schemaVersion":2,"sourceDigest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","providers":[{"id":"owner","brandName":"Product","companyName":"Owner","order":3,"logoSvg":"icons/owner.svg"}],"models":[{"id":"family/model","name":"Fixture","provider_id":"owner","provider_name":"Owner","logo_svg":"icons/owner.svg","for_app_skill":"ai.ask","release_date":"2026-09-01","capability_level":"high","servers":[{"id":"host"}]}]}"#
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.catalog.public-read-only,ai-model-routing.catalog.capability-recommendation-variants
    func testGeneratedSchemaAndServingAliasDecode() throws {
        let catalog = try NativeModelCatalog.load(data: Data(fixture.utf8))
        XCTAssertEqual(catalog.routing(health: nil).canonical("host/family/model"), "owner/family/model")
        XCTAssertEqual(catalog.models.first?.logo_svg, "icons/owner.svg")
        XCTAssertEqual(catalog.pickerProviders.first?.brandName, "Product")
        XCTAssertEqual(catalog.pickerProviders.first?.companyName, "Owner")
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.catalog.public-read-only,ai-model-routing.catalog.capability-recommendation-variants
    func testHealthFailureAndMissingProviderFailOpenButDegradedDoesNot() throws {
        let catalog = try NativeModelCatalog.load(data: Data(fixture.utf8))
        XCTAssertTrue(catalog.routing(health: nil).usable("owner/family/model"))
        let empty = try JSONDecoder().decode(ProviderHealthSnapshot.self, from: Data(#"{"providers":{}}"#.utf8))
        XCTAssertTrue(catalog.routing(health: empty).usable("owner/family/model"))
        let degraded = try JSONDecoder().decode(ProviderHealthSnapshot.self, from: Data(#"{"providers":{"host":{"status":"degraded"}}}"#.utf8))
        XCTAssertFalse(catalog.routing(health: degraded).usable("owner/family/model"))
        XCTAssertFalse(catalog.routing(disabledModels: ["family/model"], health: nil).usable("owner/family/model"))
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.catalog.public-read-only,ai-model-routing.catalog.capability-recommendation-variants
    func testUnknownSchemaFails() {
        XCTAssertThrowsError(try NativeModelCatalog.load(data: Data(fixture.replacingOccurrences(of: "schemaVersion\":2", with: "schemaVersion\":3").utf8)))
    }
}
