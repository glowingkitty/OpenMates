// Tests for the device-local "Prefer EU servers" setting (UserDefaults
// persistence and the stored-text mapping); the core is not needed here.
// Specification: specifications/features/ai-model-routing/specification.yml
// Assertions: ai-model-routing.settings.hierarchy-canonical

import XCTest
@testable import OpenMates

final class ServerRegionSettingTests: XCTestCase {
    private func makeDefaults() -> UserDefaults {
        let name = "server-region-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        // Captures only the suite name: the teardown block may be `@Sendable`.
        addTeardownBlock { UserDefaults(suiteName: name)?.removePersistentDomain(forName: name) }
        return defaults
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.settings.hierarchy-canonical
    @MainActor
    func testDefaultsToEUWhenNothingIsStored() {
        let setting = ServerRegionSetting(defaults: makeDefaults())
        XCTAssertEqual(setting.preference, .eu)
        XCTAssertTrue(setting.prefersEU)
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.settings.hierarchy-canonical
    @MainActor
    func testTheChoiceIsStoredAndRestoredByANewInstance() {
        let defaults = makeDefaults()
        let setting = ServerRegionSetting(defaults: defaults)
        setting.setPrefersEU(false)
        XCTAssertEqual(setting.preference, .global)
        XCTAssertEqual(defaults.string(forKey: ServerRegionSetting.storageKey), "global")
        XCTAssertEqual(ServerRegionSetting(defaults: defaults).preference, .global)
        setting.setPrefersEU(true)
        XCTAssertEqual(ServerRegionSetting(defaults: defaults).preference, .eu)
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.settings.hierarchy-canonical
    @MainActor
    func testOnlyGlobalSwitchesEUOff() {
        XCTAssertEqual(ServerRegionSetting.preference(fromStored: "global"), .global)
        XCTAssertEqual(ServerRegionSetting.preference(fromStored: "eu"), .eu)
        XCTAssertEqual(ServerRegionSetting.preference(fromStored: "anything"), .eu)
        XCTAssertEqual(ServerRegionSetting.preference(fromStored: nil), .eu)
    }
}
