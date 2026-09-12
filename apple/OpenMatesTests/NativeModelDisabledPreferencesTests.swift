import XCTest
@testable import OpenMates
@MainActor final class NativeModelDisabledPreferencesTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.settings.hierarchy-canonical
    func testAccountServerIsolationAndDisabledRouting() throws {
        let suite = "fixture-model-disabled-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = NativeModelDisabledPreferences(defaults: defaults)
        let value = NativeModelDisabledPreferences.Value(disabled_ai_models: ["model"], disabled_ai_servers: [:])
        try store.write(value, server: "dev", user: "a")
        XCTAssertEqual(store.read(server: "dev", user: "a"), value)
        XCTAssertTrue(store.read(server: "dev", user: "b").disabled_ai_models.isEmpty)
        XCTAssertTrue(store.read(server: "production", user: "a").disabled_ai_models.isEmpty)
        let routing = ModelRoutingCatalog(entries: [.init(provider: "provider", modelID: "model", skill: "ai.ask", servers: ["host"])], disabledModels: value.disabled_ai_models)
        XCTAssertFalse(routing.usable("provider/model"))
    }
}
