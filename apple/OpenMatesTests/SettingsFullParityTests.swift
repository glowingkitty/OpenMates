// Unit guardrails for the full native settings parity specification.
// These tests intentionally use static inventories and small metadata fixtures
// only, so they never access private accounts, purchases, invoices, API keys,
// recovery credentials, provider APIs, or network state.

import XCTest
@testable import OpenMates

@MainActor
final class SettingsFullParityTests: XCTestCase {
    func testNativeSettingsRouteInventoryCoversWebBaseRoutes() {
        let missing = SettingsRouteInventory.webBaseRoutes.subtracting(SettingsRouteInventory.coveredWebBaseRoutes)
        XCTAssertTrue(missing.isEmpty, "Missing native settings route coverage: \(missing.sorted())")

        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("app_store"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("billing"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("server"))
        XCTAssertTrue(SettingsRouteInventory.nativeEquivalentOrPlannedRoutes.contains("app_store/all"))
        XCTAssertTrue(SettingsRouteInventory.nativeEquivalentOrPlannedRoutes.contains("account/security/recovery-key"))
    }

    func testAppMetadataDecoderPreservesWebFields() throws {
        let data = Data(Self.metadataFixture.utf8)
        let response = try JSONDecoder().decode(SettingsAppsFullView.AppsMetadataResponse.self, from: data)

        let weather = try XCTUnwrap(response.apps["weather"])
        XCTAssertEqual(weather.id, "weather")
        XCTAssertEqual(weather.category, "personal")
        XCTAssertEqual(weather.providers, ["OpenWeather"])
        XCTAssertEqual(weather.lastUpdated, "2026-05-01")
        XCTAssertEqual(weather.skills.first?.id, "forecast")
        XCTAssertEqual(weather.skills.first?.providers, ["OpenWeather"])
        XCTAssertNotNil(weather.skills.first?.pricing?["per_call"])
        XCTAssertEqual(weather.focusModes.first?.id, "travel_weather")
        XCTAssertEqual(weather.settingsAndMemories.first?.id, "home_location")
    }

    func testAppStoreCategoryFilterSortAndAIExclusionContracts() throws {
        let data = Data(Self.metadataFixture.utf8)
        let response = try JSONDecoder().decode(SettingsAppsFullView.AppsMetadataResponse.self, from: data)
        let weather = try XCTUnwrap(response.apps["weather"])
        let docs = try XCTUnwrap(response.apps["docs"])

        XCTAssertEqual(SettingsAppsFullView.appStoreCategory(for: weather), "for_everyday_life")
        XCTAssertEqual(SettingsAppsFullView.appStoreCategory(for: docs), "for_work")
        XCTAssertEqual(
            SettingsAppsFullView.webAppStoreCategoryKeys,
            ["top_picks", "most_used", "new_apps", "for_work", "for_everyday_life"]
        )
        XCTAssertEqual(SettingsAppsFullView.allAppsFilterKeys, ["all", "settings_memories", "focus_modes", "skills"])
        XCTAssertEqual(SettingsAppsFullView.allAppsSortKeys, ["newest", "name"])
        XCTAssertTrue(SettingsAppsFullView.appStoreExcludedAppIDs.contains("ai"))
    }

    func testAppleCreditProductsMatchKnownCreditTiers() {
        XCTAssertEqual(
            StoreManager.productIDs,
            [
                "org.openmates.credits.1000",
                "org.openmates.credits.10000",
                "org.openmates.credits.21000",
                "org.openmates.credits.54000",
            ]
        )
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.1000"], 1_000)
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.10000"], 10_000)
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.21000"], 21_000)
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.54000"], 54_000)
    }

    private static let metadataFixture = """
    {
      "apps": {
        "weather": {
          "id": "weather",
          "name": "Weather",
          "description": "Forecasts and weather alerts",
          "category": "personal",
          "providers": ["OpenWeather"],
          "last_updated": "2026-05-01",
          "skills": [
            {
              "id": "forecast",
              "name": "Weather Forecast",
              "description": "Get a forecast",
              "pricing": {"per_call": 1},
              "providers": ["OpenWeather"]
            }
          ],
          "focus_modes": [
            {
              "id": "travel_weather",
              "name": "Travel Weather",
              "description": "Plan around weather"
            }
          ],
          "settings_and_memories": [
            {
              "id": "home_location",
              "name": "Home Location",
              "description": "Remember a location"
            }
          ]
        },
        "docs": {
          "id": "docs",
          "name": "Docs",
          "description": "Document work",
          "category": "work",
          "providers": [],
          "last_updated": "2026-03-01",
          "skills": [],
          "focus_modes": [],
          "settings_and_memories": []
        }
      }
    }
    """
}
