// Provider-family inventory, catalog filtering and availability preference proofs.
// Uses generated public metadata and isolated disposable UserDefaults only.
import XCTest
@testable import OpenMates

@MainActor
final class SettingsAIProviderParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testProviderFamiliesUseCanonicalBrandsAndExcludeHostingServers() throws {
        let catalog = try NativeModelCatalog.load(bundle: .main)
        let families = SettingsAIFullView.providerFamilies(catalog: catalog)
        XCTAssertEqual(families.map(\.id), ["openai", "anthropic", "mistral", "deepseek", "google", "alibaba", "moonshot", "zai"])
        XCTAssertEqual(families.map(\.brandName), ["ChatGPT", "Claude", "Mistral", "DeepSeek", "Gemini", "Qwen", "Kimi", "GLM"])
        XCTAssertEqual(families.first?.companyName, "OpenAI")
        let refreshedModel = try XCTUnwrap(catalog.models.first { $0.id == "gpt-6.1-sol" })
        XCTAssertEqual(refreshedModel.name, "GPT-6.1 Sol")
        XCTAssertEqual(refreshedModel.provider_id, "openai")
        XCTAssertEqual(refreshedModel.release_date, "2026-09-29")
        XCTAssertEqual(refreshedModel.capability_level, "high")
        XCTAssertEqual(refreshedModel.tier, "premium")
        XCTAssertEqual(refreshedModel.servers.map(\.id), ["openai"])
        XCTAssertFalse(families.contains { ["aws_bedrock", "openrouter", "cerebras"].contains($0.id) })
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell,chats.surface.semantic-parity
    func testProviderModelFilteringKeepsCurrentCatalogOrderAndNeverCrossesFamilies() throws {
        let catalog = try NativeModelCatalog.load(bundle: .main)
        let expected = catalog.models.filter { $0.provider_id == "openai" && $0.for_app_skill == "ai.ask" }
        XCTAssertFalse(expected.isEmpty)
        let models = SettingsAIFullView.providerModels(catalog: catalog, providerID: "openai")
        XCTAssertEqual(models.map(\.id), expected.map(\.id))
        let exact = SettingsAIFullView.providerModels(catalog: catalog, providerID: "openai", query: "  " + expected[0].name.uppercased() + "  ")
        XCTAssertTrue(exact.contains { $0.id == expected[0].id })
        XCTAssertTrue(exact.allSatisfy { $0.provider_id == "openai" })
        XCTAssertTrue(SettingsAIFullView.providerModels(catalog: catalog, providerID: "openai", query: "Claude").isEmpty)
        XCTAssertTrue(SettingsAIFullView.providerModels(catalog: catalog, providerID: "unavailable").isEmpty)
        XCTAssertTrue(SettingsAIFullView.providerModels(catalog: nil, providerID: "openai").isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSessionProfileDecodesThirdTierWithoutBreakingOlderProfiles() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let data = Data(#"{"id":"fixture-account","username":"Fixture","default_ai_model_most_demanding":"openai/gpt-6.1-sol"}"#.utf8)
        let profile = try decoder.decode(UserProfile.self, from: data)
        XCTAssertEqual(profile.defaultAiModelMostDemanding, "openai/gpt-6.1-sol")
        let older = try decoder.decode(UserProfile.self, from: Data(#"{"id":"fixture-account","username":"Fixture"}"#.utf8))
        XCTAssertNil(older.defaultAiModelMostDemanding)
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.preferences.exclusive-tier-defaults,ai-model-routing.catalog.capability-recommendation-variants
    func testTierSelectionsEncodeOnlyTheirExclusiveFieldAndAutoNull() throws {
        for tier in AIRequestTier.allCases {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let data = try encoder.encode(AITierSelectionRequest(tier: tier, selection: nil))
            let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            XCTAssertEqual(Set(object.keys), [tier.preferenceField])
            XCTAssertTrue(object[tier.preferenceField] is NSNull)
            let exact = try encoder.encode(AITierSelectionRequest(tier: tier, selection: "openai/gpt-6.1-sol"))
            let value = try XCTUnwrap(JSONSerialization.jsonObject(with: exact) as? [String: Any])
            XCTAssertEqual(value[tier.preferenceField] as? String, "openai/gpt-6.1-sol")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.catalog.capability-recommendation-variants
    func testTierRecommendationUsesCapabilityAndAvailabilityBeforeStableTieBreak() throws {
        let catalog = try NativeModelCatalog.load(bundle: .main)
        let models = catalog.models.filter { $0.for_app_skill == "ai.ask" && $0.provider_id == "anthropic" }
        for tier in AIRequestTier.allCases {
            let recommended = try XCTUnwrap(tier.recommendedModel(in: models))
            let ranks = ["low": 0, "medium": 1, "high": 2, "max": 3]
            let target = try XCTUnwrap(ranks[tier.capability])
            let distance = abs(try XCTUnwrap(ranks[try XCTUnwrap(recommended.capability_level)]) - target)
            XCTAssertTrue(models.allSatisfy { abs((ranks[$0.capability_level ?? ""] ?? 0) - target) >= distance })
        }
        let disabled = Set(models.map(\.id))
        let eligible = AIRequestTier.eligibleModels(catalog: catalog, routing: catalog.routing(disabledModels: disabled, health: nil))
        XCTAssertFalse(eligible.contains { $0.provider_id == "anthropic" })
        XCTAssertTrue(eligible.allSatisfy { $0.for_app_skill == "ai.ask" && !$0.servers.isEmpty })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAvailabilityTogglePersistsOnlyForItsAccountAndServerFixture() throws {
        let suite = "SettingsAIProviderParityTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let preferences = NativeModelDisabledPreferences(defaults: defaults)
        let server = "https://api.example.invalid"
        var value = preferences.read(server: server, user: "fixture-account")
        value.disabled_ai_models.insert("fixture-model")
        try preferences.write(value, server: server, user: "fixture-account")
        XCTAssertTrue(preferences.read(server: server, user: "fixture-account").disabled_ai_models.contains("fixture-model"))
        XCTAssertTrue(preferences.read(server: server, user: "other-account").disabled_ai_models.isEmpty)
        XCTAssertTrue(preferences.read(server: "https://other.example.invalid", user: "fixture-account").disabled_ai_models.isEmpty)
        value.disabled_ai_models.remove("fixture-model")
        try preferences.write(value, server: server, user: "fixture-account")
        XCTAssertTrue(preferences.read(server: server, user: "fixture-account").disabled_ai_models.isEmpty)
    }
}
