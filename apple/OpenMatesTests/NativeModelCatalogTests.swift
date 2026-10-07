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
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.catalog.public-read-only
    func testCachePricingDecodesWithoutChangingLegacyCatalog() throws {
        XCTAssertNil(try NativeModelCatalog.load(data: Data(fixture.utf8)).models[0].cache_pricing)
        let priced = fixture.replacingOccurrences(of: "\"servers\":[", with: "\"pricing\":{\"input_tokens_per_credit\":1000,\"cache_read_tokens_per_credit\":10000,\"cache_write_tokens_per_credit\":500},\"cache_pricing\":{\"enabled\":true,\"write_billing\":\"separate\"},\"servers\":[")
        let model = try NativeModelCatalog.load(data: Data(priced.utf8)).models[0]
        XCTAssertEqual(model.pricing?.cache_read_tokens_per_credit, 10000)
        XCTAssertEqual(model.pricing?.cache_write_tokens_per_credit, 500)
        XCTAssertEqual(model.cache_pricing?.enabled, true)
        XCTAssertEqual(model.cache_pricing?.write_billing, "separate")
        XCTAssertFalse(model.cachePricesActive(today: "2026-10-07"))
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.catalog.public-read-only
    func testCachePriceDisplayRequiresCurrentVerifiedTariffAndKnownEligibleHost() throws {
        let policy: [String: Any] = [
            "enabled": true, "status": "verified_for_activation",
            "source_url": "https://example.invalid/tariff", "reviewed_on": "2026-10-06",
            "effective_from": "2026-10-07", "expires_on": "2026-10-08",
            "eligible_hosts": ["host"], "cache_write_1h_hosts": [],
            "write_billing": "included_in_input",
        ]
        func model(_ changes: [String: Any] = [:], host: String? = "host", rates: [String: Any] = [:]) throws -> NativeModelCatalog.Model {
            var root = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(fixture.utf8)) as? [String: Any])
            var models = try XCTUnwrap(root["models"] as? [[String: Any]])
            var cache = policy
            for (key, value) in changes { cache[key] = value }
            models[0]["cache_pricing"] = cache
            models[0]["default_server"] = host
            var pricing: [String: Any] = ["cache_read_tokens_per_credit": 10000]
            for (key, value) in rates { pricing[key] = value }
            models[0]["pricing"] = pricing
            root["models"] = models
            return try NativeModelCatalog.load(data: JSONSerialization.data(withJSONObject: root)).models[0]
        }
        let active = try model()
        XCTAssertTrue(active.cachePricesActive(today: "2026-10-07"))
        XCTAssertEqual(active.cache_pricing?.effective_from, "2026-10-07")
        XCTAssertEqual(active.cache_pricing?.eligible_hosts, ["host"])
        XCTAssertFalse(active.supportsOneHourCacheWrites)
        let oneHour = try model(["cache_write_1h_hosts": ["host"]], rates: ["cache_write_1h_tokens_per_credit": 350])
        XCTAssertTrue(oneHour.cachePricesActive(today: "2026-10-07"))
        XCTAssertTrue(oneHour.supportsOneHourCacheWrites)
        XCTAssertFalse(try model(["cache_write_1h_hosts": ["other"]]).supportsOneHourCacheWrites)
        XCTAssertFalse(active.cachePricesActive(today: "2026-10-06"))
        XCTAssertFalse(active.cachePricesActive(today: "2026-10-09"))
        XCTAssertFalse(try model(["status": "proposed_pending_provider_evidence"]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["reviewed_on": "2026-10-08"]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["reviewed_on": "2026-02-30"]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["effective_from": "2026-02-30"]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["expires_on": "2026-13-08"]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["expires_on": NSNull()]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["source_url": ""]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["eligible_hosts": ["other"]]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(host: nil).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["write_billing": NSNull()]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["write_billing": "invalid"]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(rates: ["cache_read_tokens_per_credit": 0]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["write_billing": "separate"]).cachePricesActive(today: "2026-10-07"))
        XCTAssertTrue(try model(["write_billing": "separate"], rates: ["cache_write_tokens_per_credit": 500]).cachePricesActive(today: "2026-10-07"))
        XCTAssertFalse(try model(["requires_cache_retention_metric": true]).cachePricesActive(today: "2026-10-07"))
        XCTAssertTrue(try model(["requires_cache_retention_metric": true], rates: ["cache_write_1h_tokens_per_credit": 350]).cachePricesActive(today: "2026-10-07"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAssistantIdentityResolvesOnlyCanonicalMateSettingsTargets() {
        let mateIDs: Set<String> = ["software_development", "science"]

        XCTAssertEqual(
            AssistantMessageIdentityRoutingPolicy.mateID(
                category: "software_development",
                availableMateIDs: mateIDs
            ),
            "software_development"
        )
        XCTAssertNil(AssistantMessageIdentityRoutingPolicy.mateID(
            category: "openmates_official",
            availableMateIDs: mateIDs
        ))
        XCTAssertNil(AssistantMessageIdentityRoutingPolicy.mateID(
            category: "imported_claude",
            availableMateIDs: mateIDs
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAssistantIdentityResolvesModelNameAndProviderAliasesToSettingsID() throws {
        let modelFixture = fixture.replacingOccurrences(of: "family/model", with: "fixture-model")
        let catalog = try NativeModelCatalog.load(data: Data(modelFixture.utf8))
        let models = catalog.models

        XCTAssertEqual(
            AssistantMessageIdentityRoutingPolicy.modelTarget(
                nameOrID: "owner/fixture-model",
                models: models
            ),
            .init(id: "fixture-model", displayName: "Fixture")
        )
        XCTAssertEqual(
            AssistantMessageIdentityRoutingPolicy.modelTarget(
                nameOrID: "FIXTURE",
                models: models
            ),
            .init(id: "fixture-model", displayName: "Fixture")
        )
        XCTAssertNil(AssistantMessageIdentityRoutingPolicy.modelTarget(
            nameOrID: "Unknown Model",
            models: models
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageModelSettingsDetailUsesCanonicalCatalogBeyondSettingsSnapshot() throws {
        let modelFixture = fixture
            .replacingOccurrences(of: "family/model", with: "gpt-6-sol")
            .replacingOccurrences(of: "Fixture", with: "GPT-6 Sol")
        let catalog = try NativeModelCatalog.load(data: Data(modelFixture.utf8))

        let detail = try XCTUnwrap(SettingsAIFullView.modelDetail(
            id: "gpt-6-sol",
            canonicalModels: catalog.models
        ))
        XCTAssertEqual(detail.id, "gpt-6-sol")
        XCTAssertEqual(detail.name, "GPT-6 Sol")
        XCTAssertEqual(detail.providerName, "Owner")
    }
}
