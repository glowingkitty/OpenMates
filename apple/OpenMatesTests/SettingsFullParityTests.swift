// Unit guardrails for the full native settings parity specification.
// These tests intentionally use static inventories and small metadata fixtures
// only, so they never access private accounts, purchases, invoices, API keys,
// recovery credentials, provider APIs, or network state.

import XCTest
@testable import OpenMates
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

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
        let response = try Self.metadataDecoder.decode(SettingsAppsFullView.AppsMetadataResponse.self, from: data)

        let weather = try XCTUnwrap(response.apps["weather"])
        XCTAssertEqual(weather.id, "weather")
        XCTAssertEqual(weather.category, "personal")
        XCTAssertEqual(weather.providers?.map(\.displayName), ["OpenWeather"])
        XCTAssertEqual(weather.lastUpdated, "2026-05-01")
        XCTAssertEqual(weather.skills.first?.id, "forecast")
        XCTAssertEqual(weather.skills.first?.providers?.map(\.displayName), ["OpenWeather"])
        XCTAssertNotNil(weather.skills.first?.pricing?["per_call"])
        XCTAssertEqual(weather.focusModes.first?.id, "travel_weather")
        XCTAssertEqual(weather.settingsAndMemories.first?.id, "home_location")
    }

    func testAppStoreCategoryFilterSortAndAIExclusionContracts() throws {
        let data = Data(Self.metadataFixture.utf8)
        let response = try Self.metadataDecoder.decode(SettingsAppsFullView.AppsMetadataResponse.self, from: data)
        let weather = try XCTUnwrap(response.apps["weather"])
        let docs = try XCTUnwrap(response.apps["docs"])

        XCTAssertEqual(SettingsAppsFullView.appStoreCategory(for: weather), "for_everyday_life")
        XCTAssertEqual(SettingsAppsFullView.appStoreCategory(for: docs), "for_work")
        XCTAssertEqual(
            SettingsAppsFullView.webAppStoreCategoryKeys,
            ["top_picks", "most_used", "new_apps", "for_work", "for_everyday_life"]
        )
        XCTAssertEqual(SettingsAppsFullView.allAppsFilterKeys, ["all", "settings_memories", "focus_modes", "skills"])
        XCTAssertEqual(SettingsAppsFullView.allAppsSortKeys, ["newest", "name_asc", "name_desc"])
        XCTAssertTrue(SettingsAppsFullView.appStoreExcludedAppIDs.contains("ai"))

        let categorized = Dictionary(uniqueKeysWithValues: SettingsAppsFullView.categorizeApps([
            SettingsAppsFullView.appInfo(from: weather),
            SettingsAppsFullView.appInfo(from: docs),
        ]).map { ($0.key, $0.apps.map(\.id)) })
        XCTAssertTrue(categorized["top_picks"]?.contains("weather") == true)
        XCTAssertTrue(categorized["new_apps"]?.contains("weather") == true)
        XCTAssertTrue(categorized["for_everyday_life"]?.contains("weather") == true)
        XCTAssertTrue(categorized["for_work"]?.contains("docs") == true)
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

    func testIssueReportPayloadUsesSettingsEndpointShapeAndRedactsSensitiveContext() {
        let payload = IssueReportPayloadBuilder.makePayload(
            title: " Broken <b>button</b> ",
            issueType: .bugReport,
            userFlow: "Opened https://example.org/share/chat/abc#key=secret as user@example.org",
            expectedBehaviour: "token=secret should not leak",
            actualBehaviour: "file:///Users/alice/private.txt appeared",
            screenshotData: Data([1, 2, 3]),
            consoleLogs: "email=user@example.org password=secret #key=secret",
            runtimeDebugState: ["platform": "apple_native"],
            language: "en"
        )

        XCTAssertEqual(payload["title"] as? String, "Broken button")
        XCTAssertEqual(payload["issue_type"] as? String, "bug_report")
        XCTAssertEqual(payload["language"] as? String, "en")
        XCTAssertEqual(payload["screenshot_png_base64"] as? String, Data([1, 2, 3]).base64EncodedString())
        XCTAssertNotNil(payload["device_info"] as? [String: Any])
        XCTAssertNotNil(payload["runtime_debug_state"] as? [String: Any])

        let description = payload["description"] as? String ?? ""
        let logs = payload["console_logs"] as? String ?? ""
        XCTAssertFalse(description.contains("user@example.org"))
        XCTAssertFalse(description.contains("#key=secret"))
        XCTAssertFalse(description.contains("file:///Users"))
        XCTAssertFalse(logs.contains("password=secret"))
        XCTAssertTrue(logs.contains("<email>"))
    }

    func testIssueReportPayloadIncludesNativeDeviceDiagnostics() throws {
        let payload = IssueReportPayloadBuilder.makePayload(
            title: "Simulator diagnostics",
            issueType: .bugReport,
            userFlow: "Opened report issue",
            expectedBehaviour: "Device context is included",
            actualBehaviour: "Need native diagnostics",
            screenshotData: nil,
            consoleLogs: "native simulator log",
            runtimeDebugState: IssueReportPayloadBuilder.runtimeDebugState(),
            language: "en"
        )

        let deviceInfo = try XCTUnwrap(payload["device_info"] as? [String: Any])
        XCTAssertEqual(deviceInfo["userAgent"] as? String, "OpenMates-Apple/iOS")
        XCTAssertEqual(deviceInfo["isTouchEnabled"] as? Bool, true)
        XCTAssertNotNil(deviceInfo["systemVersion"] as? String)

        if ProcessInfo.processInfo.environment["SIMULATOR_DEVICE_NAME"] != nil {
            XCTAssertEqual(deviceInfo["isSimulator"] as? Bool, true)
            XCTAssertNotNil(deviceInfo["simulatorDeviceName"] as? String)
        }
    }

    func testNativeClientLogCollectorBuildsIssueLogPayloadWithRedaction() {
        NativeClientLogCollector.shared.resetForTests()
        NativeClientLogCollector.shared.record(
            level: .error,
            category: "sync",
            message: "Failed for person@example.org with api_key=secret"
        )

        let payload = NativeClientLogCollector.shared.issueLogPayload(
            issueId: "issue-123",
            pageURL: "apple://settings/report_issue#key=secret"
        )

        XCTAssertEqual(payload["issue_id"] as? String, "issue-123")
        XCTAssertEqual(payload["page_url"] as? String, "apple://settings/report_issue#key=<redacted>")
        let logs = payload["logs_text"] as? String ?? ""
        XCTAssertTrue(logs.contains("<email>"))
        XCTAssertTrue(logs.contains("api_key=<redacted>"))
        XCTAssertFalse(logs.contains("person@example.org"))
        XCTAssertFalse(logs.contains("api_key=secret"))
    }

    func testReconnectBannerHasDebounceBeforeUserFacingWarning() {
        XCTAssertGreaterThanOrEqual(NetworkStatusBanner.reconnectDelayNanoseconds, 1_000_000_000)
    }

    func testHeaderAndReferralAssetsAreBundled() {
        #if os(iOS)
        XCTAssertNotNil(UIImage(named: "openmates"))
        XCTAssertNotNil(UIImage(named: "gift"))
        #elseif os(macOS)
        XCTAssertNotNil(NSImage(named: "openmates"))
        XCTAssertNotNil(NSImage(named: "gift"))
        #endif
    }

    private static let metadataFixture = """
    {
      "apps": {
        "weather": {
          "id": "weather",
          "name": "Weather",
          "description": "Forecasts and weather alerts",
          "category": "personal",
          "providers": [
            {"name": "OpenWeather", "display_name": "OpenWeather", "no_api_key": false}
          ],
          "last_updated": "2026-05-01",
          "skills": [
            {
              "id": "forecast",
              "name": "Weather Forecast",
              "description": "Get a forecast",
              "pricing": {"per_call": 1},
              "providers": [
                {"name": "OpenWeather", "display_name": "OpenWeather", "no_api_key": false}
              ]
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

    private static let metadataDecoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()
}
