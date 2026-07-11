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

        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("apps"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("apps/all"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("projects"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("billing"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("server"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("account/security/recovery-key"))
        XCTAssertEqual(SettingsRouteInventory.webBaseRoutes, SettingsRouteInventory.nativeRoutes)
    }

    func testEnhancedPIIModelSettingsLifecycle() async {
        let manifest = EnhancedPIIModelManifest(
            version: "2026-07-privacy-filter-q4",
            sizeBytes: 771_740_000,
            remoteURL: URL(string: "https://example.invalid/openmates/privacy-filter.onnx")!,
            sha256: String(repeating: "a", count: 64)
        )
        let downloader = MockEnhancedPIIModelDownloader()
        let controller = EnhancedPIIModelDownloadController(manifest: manifest, downloader: downloader)

        XCTAssertEqual(controller.status, .notDownloaded)
        XCTAssertTrue(controller.statusCopy.contains("Download"))
        XCTAssertTrue(controller.statusCopy.contains("local"))
        XCTAssertTrue(controller.sizeCopy.contains("735.99 MB"))

        await controller.download()
        XCTAssertEqual(controller.status, .ready(version: manifest.version, sizeBytes: manifest.sizeBytes))
        XCTAssertEqual(downloader.downloadedManifests, [manifest])

        controller.markUpdateAvailable(version: "2026-08-privacy-filter-q4", sizeBytes: 800_000_000)
        XCTAssertEqual(
            controller.status,
            .updateAvailable(currentVersion: manifest.version, newVersion: "2026-08-privacy-filter-q4", sizeBytes: 800_000_000)
        )

        await controller.remove()
        XCTAssertEqual(controller.status, .notDownloaded)

        let failing = EnhancedPIIModelDownloadController(manifest: nil, downloader: downloader)
        await failing.download()
        XCTAssertEqual(failing.status, .failed(reason: .modelNotConfigured))
        XCTAssertFalse(failing.statusCopy.contains("example.invalid"))
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

    func testAppMetadataDecoderPreservesProductionDetailActions() throws {
        let data = Data(Self.metadataFixture.utf8)
        let response = try Self.metadataDecoder.decode(SettingsAppsFullView.AppsMetadataResponse.self, from: data)
        let weather = try XCTUnwrap(response.apps["weather"])
        let skill = try XCTUnwrap(weather.skills.first)

        XCTAssertEqual(skill.providerDetails?.first?.id, "openweather")
        XCTAssertEqual(skill.models?.first?.id, "forecast-v2")
        XCTAssertEqual(weather.contentTypes.first?.contentTypeId, "weather_day")
        XCTAssertEqual(weather.focusModes.first?.processBullets, ["Check the forecast", "Recommend timing"])
        XCTAssertEqual(weather.focusModes.first?.systemPrompt, "Prioritize weather-aware travel planning.")
        XCTAssertEqual(weather.settingsAndMemories.first?.valueType, "single")
        XCTAssertEqual(
            SettingsAppsFullView.mentionSyntax(appId: "weather", itemId: "forecast", kind: .skill),
            "@skill:weather:forecast"
        )
        XCTAssertEqual(
            SettingsAppsFullView.mentionSyntax(appId: "weather", itemId: "travel_weather", kind: .focus),
            "@focus:weather:travel_weather"
        )
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
        ], mostUsedAppIDs: ["docs"]).map { ($0.key, $0.apps.map(\.id)) })
        XCTAssertTrue(categorized["top_picks"]?.contains("weather") == true)
        XCTAssertEqual(categorized["most_used"], ["docs"])
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

    @MainActor
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

    @MainActor
    func testIssueReportPayloadIncludesNativeDiagnosticsContextAndStrongRedaction() throws {
        NativeClientLogCollector.shared.resetForTests()
        NativeActionTracker.shared.resetForTests()
        NativePerformanceMonitor.shared.resetForTests()
        NativeMetricKitReporter.shared.resetForTests()
        NativeSyncDiagnosticsStore.shared.resetForTests()
        NativeLogForwarder.shared.resetForTests()

        NativeActionTracker.shared.recordRoute("chat/detail")
        NativeActionTracker.shared.recordControl("settings/report_issue/open")
        NativeActionTracker.shared.recordTextInput("my private typed composer text")
        NativePerformanceMonitor.shared.recordFrame(durationMS: 16)
        NativePerformanceMonitor.shared.recordFrame(durationMS: 82)
        NativeMetricKitReporter.shared.recordSummary([
            "report_type": "metric",
            "category": "hang",
            "details": "person@example.org token=secret",
        ])
        NativeClientLogCollector.shared.record(
            level: .warning,
            category: "diagnostics",
            message: "share https://example.org/share/chat/abc#key=secret file:///Users/alice/private.txt blob=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )

        let context = NativeIssueContextProvider.shared.context()
        let payload = IssueReportPayloadBuilder.makePayload(
            title: "Diagnostics regression",
            issueType: .bugReport,
            userFlow: "Opened chat and report issue #key=secret",
            expectedBehaviour: "No secrets leak",
            actualBehaviour: "token=secret /Users/alice/private.txt appeared",
            screenshotData: nil,
            consoleLogs: context.consoleLogs,
            runtimeDebugState: context.runtimeDebugState,
            actionHistory: context.actionHistory,
            language: "en"
        )

        let runtime = try XCTUnwrap(payload["runtime_debug_state"] as? [String: Any])
        let diagnostics = try XCTUnwrap(runtime["native_diagnostics"] as? [String: Any])
        XCTAssertNotNil(diagnostics["offline_inspection"] as? [String: Any])
        XCTAssertNotNil(diagnostics["frame_metrics"] as? [String: Any])
        XCTAssertNotNil(diagnostics["metric_kit"] as? [[String: Any]])
        XCTAssertNotNil(diagnostics["device_state"] as? [String: Any])
        XCTAssertNotNil(diagnostics["sync_summary"] as? [String: Any])
        XCTAssertNotNil(diagnostics["forwarder_status"] as? [String: Any])

        let actionHistory = payload["action_history"] as? String ?? ""
        XCTAssertTrue(actionHistory.contains("chat/detail"))
        XCTAssertTrue(actionHistory.contains("settings/report_issue/open"))
        XCTAssertFalse(actionHistory.contains("my private typed composer text"))

        let serialized = try XCTUnwrap(String(data: JSONSerialization.data(withJSONObject: payload), encoding: .utf8))
        XCTAssertFalse(serialized.contains("person@example.org"))
        XCTAssertFalse(serialized.contains("token=secret"))
        XCTAssertFalse(serialized.contains("#key=secret"))
        XCTAssertFalse(serialized.contains("/Users/alice"))
        XCTAssertFalse(serialized.contains("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))
        XCTAssertFalse(serialized.contains("my private typed composer text"))
    }

    func testNativeSyncPerfLogBridgesIntoDiagnosticsAndPreservesWarningsUnderChurn() {
        NativeClientLogCollector.shared.resetForTests()
        NativeSyncDiagnosticsStore.shared.resetForTests()
        NativeSyncPerfLog.warning("phase=importantWarning email=person@example.org")
        NativeSyncPerfLog.info("phase=offlineColdLoad elapsedMs=321 chatCount=20")
        NativeSyncPerfLog.warning("phase=embedDedup duplicateEntries=64 chatCount=9")
        for index in 0..<260 {
            NativeClientLogCollector.shared.record(level: .debug, category: "noise", message: "debug entry \(index)")
        }
        NativeSyncPerfLog.info("phase=loadSyncedChatFirstPaint chat=12345678 token=secret")

        let logs = NativeClientLogCollector.shared.logsAsText(limit: 300)
        XCTAssertTrue(logs.contains("phase=importantWarning"))
        XCTAssertTrue(logs.contains("phase=loadSyncedChatFirstPaint"))
        XCTAssertTrue(logs.contains("<email>"))
        XCTAssertFalse(logs.contains("person@example.org"))
        XCTAssertFalse(logs.contains("token=secret"))

        let syncSummary = NativeSyncDiagnosticsStore.shared.summary()
        XCTAssertGreaterThanOrEqual(syncSummary["phase_count"] as? Int ?? 0, 4)
        XCTAssertEqual(syncSummary["slowest_elapsed_ms"] as? Int, 321)
        XCTAssertGreaterThanOrEqual(syncSummary["duplicate_warning_count"] as? Int ?? 0, 1)
        let phases = syncSummary["recent_phases"] as? [[String: Any]] ?? []
        XCTAssertTrue(phases.contains { ($0["phase"] as? String) == "offlineColdLoad" })
        XCTAssertTrue(phases.contains { ($0["duplicate_entries"] as? Int) == 64 })
        XCTAssertFalse(String(describing: syncSummary).contains("person@example.org"))
    }

    func testNativeActionTrackerRecordsStableActionsAndSuppressesTypedText() {
        NativeActionTracker.shared.resetForTests()
        NativeActionTracker.shared.recordRoute("settings/privacy")
        NativeActionTracker.shared.recordControl("settings/debug_logs/toggle")
        NativeActionTracker.shared.recordTextInput("raw issue text should not be logged")

        let actions = NativeActionTracker.shared.actionsAsText(limit: 10)
        XCTAssertTrue(actions.contains("settings/privacy"))
        XCTAssertTrue(actions.contains("settings/debug_logs/toggle"))
        XCTAssertFalse(actions.contains("raw issue text should not be logged"))
    }

    func testNativeLogForwarderBuildsDebugAndDefaultTelemetryPayloads() throws {
        NativeClientLogCollector.shared.resetForTests()
        NativeClientLogCollector.shared.record(level: .info, category: "chat", message: "informational message")
        NativeClientLogCollector.shared.record(level: .warning, category: "sync", message: "warning for user@example.org")
        NativeClientLogCollector.shared.record(level: .error, category: "api", message: "token=secret")

        let debugPayload = NativeLogForwarder.debugSessionPayload(debuggingID: "dbg-abc123")
        XCTAssertEqual(debugPayload["debugging_id"] as? String, "dbg-abc123")
        XCTAssertNotNil(debugPayload["metadata"] as? [String: String])
        let debugLogs = try XCTUnwrap(debugPayload["logs"] as? [[String: Any]])
        XCTAssertEqual(debugLogs.count, 3)
        XCTAssertTrue(debugLogs.allSatisfy { ($0["timestamp"] as? Int ?? 0) > 0 })
        XCTAssertTrue(debugLogs.contains { ($0["level"] as? String) == "warn" })
        XCTAssertFalse(String(describing: debugPayload).contains("user@example.org"))
        XCTAssertFalse(String(describing: debugPayload).contains("token=secret"))

        XCTAssertNil(NativeLogForwarder.defaultTelemetryPayload(isAuthenticated: false, optedOut: false))
        XCTAssertNil(NativeLogForwarder.defaultTelemetryPayload(isAuthenticated: true, optedOut: true))
        let telemetryPayload = try XCTUnwrap(NativeLogForwarder.defaultTelemetryPayload(
            isAuthenticated: true,
            optedOut: false,
            installPseudonym: "11111111-2222-4333-8444-555555555555"
        ))
        let telemetryLogs = try XCTUnwrap(telemetryPayload["logs"] as? [[String: Any]])
        XCTAssertEqual(telemetryLogs.count, 2)
        XCTAssertFalse(telemetryLogs.contains { ($0["level"] as? String) == "info" })
        XCTAssertTrue(telemetryLogs.contains { ($0["level"] as? String) == "warn" })
        XCTAssertTrue(telemetryLogs.contains { ($0["level"] as? String) == "error" })
        XCTAssertEqual(telemetryPayload["session_pseudonym"] as? String, "11111111-2222-4333-8444-555555555555")
        XCTAssertEqual((telemetryPayload["metadata"] as? [String: String])?["tabId"], "11111111-2222-4333-8444-555555555555")
        XCTAssertFalse(String(describing: telemetryPayload).contains("user@example.org"))
        XCTAssertFalse(String(describing: telemetryPayload).contains("token=secret"))
        XCTAssertFalse(String(describing: telemetryPayload).contains("user_id"))
    }

    func testNativeLogForwarderStartsAndStopsDefaultTelemetryLoop() {
        NativeLogForwarder.shared.resetForTests()
        XCTAssertFalse(NativeLogForwarder.shared.isDefaultTelemetryRunningForTests())

        NativeLogForwarder.shared.startDefaultTelemetry(intervalNanoseconds: 60_000_000_000)
        XCTAssertTrue(NativeLogForwarder.shared.isDefaultTelemetryRunningForTests())

        NativeLogForwarder.shared.stopDefaultTelemetry()
        XCTAssertFalse(NativeLogForwarder.shared.isDefaultTelemetryRunningForTests())
    }

    func testNativeLogForwarderStatusSnapshotAndIssueFlushWithoutLogs() async throws {
        NativeClientLogCollector.shared.resetForTests()
        NativeLogForwarder.shared.resetForTests()
        NativeLogForwarder.shared.startDefaultTelemetry(intervalNanoseconds: 60_000_000_000)

        var status = NativeLogForwarder.shared.statusSnapshot()
        XCTAssertEqual(status["default_telemetry_running"] as? Bool, true)
        XCTAssertEqual(status["debug_session_active"] as? Bool, false)

        await NativeLogForwarder.shared.flushForIssueReport()
        status = NativeLogForwarder.shared.statusSnapshot()
        XCTAssertEqual(status["last_default_flush_status"] as? String, "empty")
        XCTAssertEqual(status["last_default_flush_count"] as? Int, 0)
        XCTAssertNotEqual(status["last_default_flush_at"] as? String, "never")

        NativeLogForwarder.shared.stopDefaultTelemetry()
    }

    @MainActor
    func testNativePerformanceAndMetricKitSummariesExposeAvailabilityAndFrameMetrics() throws {
        NativePerformanceMonitor.shared.resetForTests()
        NativeMetricKitReporter.shared.resetForTests()

        let absentMetricKit = NativeMetricKitReporter.shared.latestSummaries()
        XCTAssertEqual(absentMetricKit.first?["status"] as? String, "unavailable")
        let deviceState = NativeRuntimeSnapshotProvider.snapshot()["native_diagnostics"] as? [String: Any]
        XCTAssertNotNil(deviceState?["device_state"] as? [String: Any])

        NativePerformanceMonitor.shared.recordFrame(durationMS: 17)
        NativePerformanceMonitor.shared.recordFrame(durationMS: 70)
        let frameSummary = NativePerformanceMonitor.shared.summary()
        XCTAssertEqual(frameSummary["sample_count"] as? Int, 2)
        XCTAssertEqual(frameSummary["jank_count"] as? Int, 1)
        XCTAssertEqual(frameSummary["worst_frame_ms"] as? Int, 70)
        XCTAssertNotNil(frameSummary["average_fps"] as? Double)

        NativeMetricKitReporter.shared.recordSummary(["report_type": "diagnostic", "category": "cpu"])
        let metricKit = NativeMetricKitReporter.shared.latestSummaries()
        XCTAssertEqual(metricKit.first?["report_type"] as? String, "diagnostic")
    }

    func testNativeMetricKitAndDisplayLinkLifecycleHooksStart() {
        NativeMetricKitReporter.shared.resetForTests()
        NativeMetricKitReporter.shared.start()
        XCTAssertTrue(NativeMetricKitReporter.shared.isStartedForTests())

        NativePerformanceMonitor.shared.startSampling()
        #if os(iOS)
        let isSampling = NativePerformanceMonitor.shared.isSamplingForTests()
        XCTAssertTrue(isSampling)
        #endif
        NativePerformanceMonitor.shared.stopSampling()
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
              ],
              "provider_details": [
                {"id": "openweather", "name": "OpenWeather", "description": "Weather provider"}
              ],
              "models": [
                {"id": "forecast-v2", "name": "Forecast V2", "provider_id": "openweather", "provider_name": "OpenWeather"}
              ]
            }
          ],
          "focus_modes": [
            {
              "id": "travel_weather",
              "name": "Travel Weather",
              "description": "Plan around weather",
              "process": ["Check the forecast", "Recommend timing"],
              "system_prompt": "Prioritize weather-aware travel planning."
            }
          ],
          "settings_and_memories": [
            {
              "id": "home_location",
              "name": "Home Location",
              "description": "Remember a location",
              "type": "single"
            }
          ],
          "content_types": [
            {
              "id": "weather.weather_day",
              "content_type_id": "weather_day",
              "frontend_type": "weather-day",
              "backend_type": "weather_day",
              "name": "Weather day",
              "description": "A daily forecast",
              "example_key": "weather.weather_day",
              "order": 10
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
          "settings_and_memories": [],
          "content_types": []
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

private final class MockEnhancedPIIModelDownloader: EnhancedPIIModelDownloading, @unchecked Sendable {
    private(set) var downloadedManifests: [EnhancedPIIModelManifest] = []

    func download(_ manifest: EnhancedPIIModelManifest, progress: @MainActor @Sendable (Double) async -> Void) async throws -> URL {
        downloadedManifests.append(manifest)
        await progress(0.25)
        await progress(1.0)
        return URL(fileURLWithPath: "/tmp/openmates-privacy-filter.onnx")
    }
}
