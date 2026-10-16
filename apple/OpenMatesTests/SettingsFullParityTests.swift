// Unit guardrails for the full native settings parity specification.
// These tests intentionally use static inventories and small metadata fixtures
// only, so they never access private accounts, purchases, invoices, API keys,
// recovery credentials, provider APIs, or network state.

import XCTest
import CryptoKit
import ImageIO
import Combine
@testable import OpenMates
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

@MainActor
final class SettingsFullParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.contextual-availability
    func testSettingsDeepLinkKeepsChildRouteAndAccountRoleGates() {
        let language = SettingsDeepLinkRoute("#/settings/interface/language/")
        XCTAssertEqual(language.path, "interface/language")
        XCTAssertEqual(language.childPath, "language")
        XCTAssertTrue(language.hasNativeChild)
        XCTAssertTrue(language.canOpen(authenticated: false, admin: false))

        for path in ["settings_memories", "privacy"] {
            let publicOverview = SettingsDeepLinkRoute(path)
            XCTAssertTrue(publicOverview.canOpen(authenticated: false, admin: false), path)
            XCTAssertTrue(publicOverview.hasNativeChild, path)
        }
        XCTAssertTrue(SettingsDeepLinkRoute("ai/provider/openai").hasNativeChild)
        XCTAssertFalse(SettingsDeepLinkRoute("ai/provider/openai/unknown").hasNativeChild)
        for path in ["teams", "teams/synthetic-team", "ai/tier/simple", "ai/tier/complex/provider/openai", "ai/tier/most-demanding"] {
            let route = SettingsDeepLinkRoute(path)
            XCTAssertTrue(route.hasNativeChild, path)
            XCTAssertFalse(route.canOpen(authenticated: false, admin: false), path)
            XCTAssertTrue(route.canOpen(authenticated: true, admin: false), path)
        }
        XCTAssertFalse(SettingsDeepLinkRoute("teams/synthetic-team/unknown").hasNativeChild)
        XCTAssertFalse(SettingsDeepLinkRoute("ai/tier/unknown").hasNativeChild)

        for path in ["account/security/password", "privacy/connected-accounts", "billing/invoices",
                     "developers/api-keys/create", "account/storage/images"] {
            let route = SettingsDeepLinkRoute(path)
            XCTAssertTrue(route.hasNativeChild, path)
            XCTAssertFalse(route.canOpen(authenticated: false, admin: false), path)
            XCTAssertTrue(route.canOpen(authenticated: true, admin: false), path)
        }
        let admin = SettingsDeepLinkRoute("server/stats")
        XCTAssertFalse(admin.canOpen(authenticated: true, admin: false))
        XCTAssertTrue(admin.canOpen(authenticated: true, admin: true))
        XCTAssertFalse(SettingsDeepLinkRoute("billing/buy-credits/confirmation").hasNativeChild,
                       "An incoming link cannot fabricate a completed purchase")
        XCTAssertFalse(SettingsDeepLinkRoute("interface/unknown").hasNativeChild)
        XCTAssertFalse(SettingsDeepLinkRoute("apps/web/skills/search").hasNativeChild)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.local-execution,apple-local-model-lab.isolated-scope
    func testLocalModelLabIsExplicitNativeOnlyAuthenticatedRoute() {
        let route = SettingsDeepLinkRoute("developers/local-models")
        XCTAssertTrue(route.hasNativeChild)
        XCTAssertFalse(route.canOpen(authenticated: false, admin: false))
        XCTAssertTrue(route.canOpen(authenticated: true, admin: false))
        XCTAssertEqual(SettingsRouteInventory.nativeOnlyRoutes, ["developers/local-models", "ai/localmodels"])
        XCTAssertFalse(SettingsRouteInventory.coveredWebBaseRoutes.contains(route.path))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads,settings-ui.shell.lifecycle-and-routing
    func testOfflineModelHeaderDestinationIsAnAuthenticatedAIChild() {
        let route = SettingsDeepLinkRoute("#/settings/ai/localmodels/")
        XCTAssertEqual(route.path, "ai/localmodels")
        XCTAssertEqual(route.topLevel, "ai")
        XCTAssertTrue(route.hasNativeChild)
        XCTAssertFalse(route.canOpen(authenticated: false, admin: false))
        XCTAssertTrue(route.canOpen(authenticated: true, admin: false))
        XCTAssertTrue(SettingsRouteInventory.nativeOnlyRoutes.contains(route.path))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains(route.path))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing
    func testProjectSettingsDeepLinkRoutesStayWithinSelectedTeamAndReloadScope() {
        let personal = SettingsProjectsRoute(teamID: nil)
        XCTAssertEqual(personal.list, "/v1/projects")
        XCTAssertEqual(personal.sources("project-1"), "/v1/projects/project-1/sources")

        let team = SettingsProjectsRoute(teamID: "team/with space")
        XCTAssertEqual(team.list, "/v1/projects?team_id=team%2Fwith%20space")
        XCTAssertEqual(team.settings("project/1"),
                       "/v1/projects/project%2F1/settings?team_id=team%2Fwith%20space")

        let scope = UUID()
        let current = SettingsProjectsLoadIdentity(accountID: "account-a", teamID: "team-a",
                                                   projectID: "project-1", serverURL: "https://api.dev.example",
                                                   scope: scope)
        XCTAssertNotEqual(current, SettingsProjectsLoadIdentity(accountID: "account-a", teamID: "team-b",
                                                                 projectID: "project-1", serverURL: current.serverURL,
                                                                 scope: scope))
        XCTAssertNotEqual(current, SettingsProjectsLoadIdentity(accountID: "account-a", teamID: "team-a",
                                                                 projectID: "project-2", serverURL: current.serverURL,
                                                                 scope: scope))
        XCTAssertNotEqual(current, SettingsProjectsLoadIdentity(accountID: "account-a", teamID: "team-a",
                                                                 projectID: "project-1", serverURL: current.serverURL,
                                                                 scope: UUID()))
        XCTAssertNotEqual(current, SettingsProjectsLoadIdentity(accountID: "account-b", teamID: "team-a",
                                                                 projectID: "project-1", serverURL: current.serverURL,
                                                                 scope: scope))
        XCTAssertNotEqual(current, SettingsProjectsLoadIdentity(accountID: "account-a", teamID: "team-a",
                                                                 projectID: "project-1", serverURL: "https://api.example",
                                                                 scope: scope))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageModelSettingsTargetResolvesCanonicalDetail() {
        XCTAssertEqual(
            SettingsAIFullView.catalogModel(id: "gemini-3-flash-preview")?.name,
            "Gemini 3 Flash"
        )
        XCTAssertNil(SettingsAIFullView.catalogModel(id: "unknown-model"))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testApiKeyDeviceAccessTypeLabelsMatchWebContract() {
        XCTAssertEqual(apiKeyDeviceAccessTypeLabel("cli"), "CLI")
        XCTAssertEqual(apiKeyDeviceAccessTypeLabel("npm"), "SDK")
        XCTAssertEqual(apiKeyDeviceAccessTypeLabel("pip"), "SDK")
        XCTAssertEqual(apiKeyDeviceAccessTypeLabel("rest_api"), "REST API")
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.parity.web-apple-shell
    func testAccountImportDefersToEncryptedWebFlow() throws {
        XCTAssertFalse(ChatImportView.nativeImportEnabled)
        let url = try XCTUnwrap(ChatImportView.webImportURL(baseURL: URL(string: "https://app.example.invalid")!))
        XCTAssertEqual(url.host, "app.example.invalid")
        XCTAssertEqual(url.fragment, "settings/account/import")
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testNativeSettingsRouteInventoryCoversWebBaseRoutes() {
        let missing = SettingsRouteInventory.webBaseRoutes.subtracting(SettingsRouteInventory.intentionallyExcludedWebRoutes).subtracting(SettingsRouteInventory.coveredWebBaseRoutes)
        XCTAssertTrue(missing.isEmpty, "Missing native settings route coverage: \(missing.sorted())")

        XCTAssertFalse(SettingsRouteInventory.nativeRoutes.contains("apps"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("apps/all"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("projects"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("billing"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("server"))
        XCTAssertTrue(SettingsRouteInventory.nativeRoutes.contains("account/security/recovery-key"))
        XCTAssertEqual(SettingsRouteInventory.webBaseRoutes.subtracting(SettingsRouteInventory.intentionallyExcludedWebRoutes), SettingsRouteInventory.nativeRoutes.subtracting(SettingsRouteInventory.nativeOnlyRoutes))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell,pii.apple.enhanced-local-detection
    func testEnhancedPIIModelSettingsLifecycle() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("privacy-settings-test-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let bytes = Data("disposable privacy asset".utf8)
        let revision = String(repeating: "a", count: 40)
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let manifest = LocalModelManifest(id: .privacyFilter, revision: revision,
            estimatedSizeBytes: Int64(bytes.count), files: [
                LocalModelFile(path: "model.pte",
                    url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/model.pte")!,
                    sha256: digest, sizeBytes: Int64(bytes.count))
            ])
        let downloader = MockPrivacySettingsAssetDownloader(bytes: bytes)
        let catalog = try JSONEncoder().encode(LocalModelCatalog(models: [manifest]))
        let store = LocalModelStore(catalog: catalog, root: root, downloader: downloader, verifyExisting: false)
        let controller = EnhancedPIIModelDownloadController(store: store)

        XCTAssertEqual(controller.status, .notDownloaded)
        XCTAssertFalse(controller.isActionDisabled)
        XCTAssertFalse(controller.sizeCopy.isEmpty)
        let initialRequests = await downloader.requestCount
        XCTAssertEqual(initialRequests, 0, "Settings must never force the optional asset download")

        await controller.download()
        XCTAssertEqual(store.state(for: .privacyFilter), .ready)
        XCTAssertEqual(controller.status, .ready(version: revision, sizeBytes: bytes.count))
        let completedRequests = await downloader.requestCount
        XCTAssertEqual(completedRequests, 1)
        XCTAssertNoThrow(try store.installedDirectory(.privacyFilter))

        // A new settings controller must reflect the same store installation.
        let reopened = EnhancedPIIModelDownloadController(store: store)
        await reopened.refresh()
        XCTAssertEqual(reopened.status, controller.status)
        await reopened.remove()
        await controller.refresh()
        XCTAssertEqual(store.state(for: .privacyFilter), .notDownloaded)
        XCTAssertEqual(controller.status, .notDownloaded)
        XCTAssertThrowsError(try store.installedDirectory(.privacyFilter))

        let emptyCatalog = try JSONEncoder().encode(LocalModelCatalog(models: []))
        let unconfiguredStore = LocalModelStore(catalog: emptyCatalog,
            root: root.appendingPathComponent("unconfigured"), downloader: downloader, verifyExisting: false)
        let failing = EnhancedPIIModelDownloadController(store: unconfiguredStore)
        XCTAssertTrue(failing.isActionDisabled)
        await failing.download()
        XCTAssertEqual(failing.status, .failed(reason: .modelNotConfigured))
        XCTAssertFalse(failing.statusCopy.contains("huggingface.co"))
        let finalRequests = await downloader.requestCount
        XCTAssertEqual(finalRequests, 1, "Missing configuration must fail before requesting assets")
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,settings-ui.composition.canonical-and-accessible
    func testPrivacyStatusIgnoresOtherModelUpdatesAndDuplicateDerivedStates() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("privacy-publication-test-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let bytes = Data("synthetic model installation".utf8)
        let revision = String(repeating: "b", count: 40)
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        func manifest(_ id: LocalModelID) -> LocalModelManifest {
            LocalModelManifest(id: id, revision: revision, estimatedSizeBytes: Int64(bytes.count), files: [
                LocalModelFile(path: "model.pte", url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/model.pte")!,
                    sha256: digest, sizeBytes: Int64(bytes.count))
            ])
        }
        let catalog = try JSONEncoder().encode(LocalModelCatalog(models: [manifest(.privacyFilter), manifest(.supertonic3)]))
        let store = LocalModelStore(catalog: catalog, root: root,
            downloader: MockPrivacySettingsAssetDownloader(bytes: bytes), verifyExisting: false)
        let controller = EnhancedPIIModelDownloadController(store: store)
        var statuses: [EnhancedPIIModelStatus] = []
        let observation = controller.$status.dropFirst().sink { statuses.append($0) }
        defer { observation.cancel() }

        await store.download(.supertonic3)
        await Task.yield()
        XCTAssertEqual(store.state(for: .supertonic3), .ready)
        XCTAssertTrue(statuses.isEmpty, "Another model's download must not invalidate privacy controls in every chat")
        await controller.refresh()
        XCTAssertTrue(statuses.isEmpty, "Refreshing the same status must not publish it again")

        await controller.download()
        await Task.yield()
        let ready = EnhancedPIIModelStatus.ready(version: revision, sizeBytes: bytes.count)
        XCTAssertEqual(statuses.last, ready, "Completion must still be published immediately")
        XCTAssertEqual(statuses.filter { $0 == ready }.count, 1)
        for pair in zip(statuses, statuses.dropFirst()) {
            XCTAssertNotEqual(pair.0, pair.1, "Transfer/verification changes with identical displayed progress are redundant")
        }
        let publishedCount = statuses.count
        await controller.refresh()
        XCTAssertEqual(statuses.count, publishedCount)
        await controller.remove()
        XCTAssertEqual(Array(statuses.suffix(2)), [.removing, .notDownloaded])
    }

    // contract-test: supporting surface=gui.apple assertions=app-skills.surface.semantic-parity,settings-ui.parity.web-apple-shell
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

    // contract-test: supporting surface=gui.apple assertions=app-skills.surface.semantic-parity,settings-ui.parity.web-apple-shell
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

    // contract-test: supporting surface=gui.apple assertions=app-skills.surface.semantic-parity,settings-ui.parity.web-apple-shell
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

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.submission.confirmed-and-durable,issue-reporting.logs.authenticated-capture
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

    // contract-test: direct surface=gui.apple assertions=issue-reporting.submission.confirmed-and-durable
    func testIssueReportScreenshotBundleIncludesEverySelectedImage() throws {
        let onePixelPNG = try XCTUnwrap(Data(base64Encoded:
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        ))
        let composite = try XCTUnwrap(IssueReportScreenshotBundle.makePNG(
            from: [onePixelPNG, onePixelPNG, onePixelPNG]
        ))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(composite as CFData, nil))
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))

        XCTAssertEqual(image.width, 1)
        XCTAssertEqual(image.height, 3, "Each selected screenshot must occupy its own row in the submitted composite.")
        XCTAssertLessThanOrEqual(composite.count, IssueReportScreenshotBundle.maximumOutputBytes)
        XCTAssertThrowsError(try IssueReportScreenshotBundle.makePNG(
            from: Array(repeating: onePixelPNG, count: IssueReportScreenshotBundle.maximumAttachments + 1)
        ))
    }

    // contract-test: direct surface=gui.apple assertions=issue-reporting.input.long-title-preserved
    func testIssueReportPayloadPreservesLongUserWrittenTitle() {
        let longTitle = String(repeating: "Detailed issue context ", count: 40)
        let payload = IssueReportPayloadBuilder.makePayload(
            title: longTitle,
            issueType: .bugReport,
            userFlow: "",
            expectedBehaviour: "",
            actualBehaviour: "",
            screenshotData: nil,
            consoleLogs: "",
            runtimeDebugState: ["diagnostics_consent": "not_granted"],
            language: "en"
        )

        XCTAssertGreaterThan(longTitle.count, 500)
        let expectedTitle = longTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        XCTAssertEqual(payload["title"] as? String, expectedTitle)
        XCTAssertFalse((payload["title"] as? String)?.hasSuffix(" ") == true)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

    // contract-test: direct surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
    func testIssueDiagnosticsRequireExplicitPerReportConsent() {
        NativeClientLogCollector.shared.resetForTests()
        NativeClientLogCollector.shared.record(
            level: .warning,
            category: "sync",
            message: "event=sync_failed email=private@example.org token=secret"
        )

        let excluded = NativeIssueContextProvider.shared.context(includeDiagnostics: false)
        XCTAssertEqual(excluded.consoleLogs, "")
        XCTAssertEqual(excluded.runtimeDebugState["diagnostics_consent"] as? String, "not_granted")
        XCTAssertNil(excluded.runtimeDebugState["native_diagnostics"])

        let included = NativeIssueContextProvider.shared.context(includeDiagnostics: true)
        XCTAssertEqual(included.runtimeDebugState["diagnostics_consent"] as? String, "granted_for_issue")
        XCTAssertNotNil(included.runtimeDebugState["native_diagnostics"])
        XCTAssertTrue(included.consoleLogs.contains("<email>"))
        XCTAssertFalse(included.consoleLogs.contains("private@example.org"))
        XCTAssertFalse(included.consoleLogs.contains("token=secret"))
    }

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
    func testStructuredNativeDiagnosticEventsAcceptSafeScalarsOnly() {
        NativeClientLogCollector.shared.resetForTests()
        NativeDiagnostics.event(
            "retry_scheduled",
            category: "sync",
            level: .warning,
            flags: ["offline": true],
            counts: ["retry_count": 2]
        )

        let logs = NativeClientLogCollector.shared.logsAsText(limit: 10)
        XCTAssertTrue(logs.contains("event=retry_scheduled"))
        XCTAssertTrue(logs.contains("offline=true"))
        XCTAssertTrue(logs.contains("retry_count=2"))

        let unsafe = "https://private.example.org/path alice@internal-host 192.168.1.14"
        let sanitized = NativeClientLogCollector.sanitize(unsafe)
        XCTAssertEqual(sanitized, "<url> <user-at-host> <ip-address>")
    }

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.entry.device-shake
    func testDeviceShakeReportTriggerDebouncesAndBuildsSafePrefill() {
        var gate = DeviceShakeReportGate()
        XCTAssertTrue(gate.shouldActivate(at: 10))
        XCTAssertFalse(gate.shouldActivate(at: 10.5))
        XCTAssertTrue(gate.shouldActivate(at: 10 + DeviceShakeReportGate.minimumInterval))

        let prefill = ReportIssuePrefill.deviceShake()
        XCTAssertEqual(DeviceShakeReportTesting.triggerLaunchArgument, "--ui-test-trigger-device-shake-report")
        XCTAssertEqual(prefill.origin, .deviceShake)
        XCTAssertEqual(prefill.category, "bug")
        XCTAssertTrue(prefill.title.isEmpty)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

        let context = NativeIssueContextProvider.shared.context(includeDiagnostics: true)
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

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
    func testNativeLogForwarderStartsAndStopsDefaultTelemetryLoop() {
        NativeLogForwarder.shared.resetForTests()
        XCTAssertFalse(NativeLogForwarder.shared.isDefaultTelemetryRunningForTests())

        NativeLogForwarder.shared.startDefaultTelemetry(intervalNanoseconds: 60_000_000_000)
        XCTAssertTrue(NativeLogForwarder.shared.isDefaultTelemetryRunningForTests())

        NativeLogForwarder.shared.stopDefaultTelemetry()
        XCTAssertFalse(NativeLogForwarder.shared.isDefaultTelemetryRunningForTests())
    }

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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
    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.authenticated-capture
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

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testReconnectBannerHasDebounceBeforeUserFacingWarning() {
        XCTAssertGreaterThanOrEqual(NetworkStatusBanner.reconnectDelayNanoseconds, 1_000_000_000)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    @MainActor
    func testNotificationStackRetainsNewestThreeAndIndependentTimers() async throws {
        let manager = ToastManager()
        defer { manager.dismissAll() }
        manager.show("Oldest retained", duration: 0)
        manager.show("Timed middle", duration: 0.01)
        manager.show("Persistent connection", type: .connection, duration: 0, dedupeKey: "connection")
        let connectionID = manager.currentToast?.id
        manager.show("Latest", duration: 0)
        XCTAssertEqual(manager.visibleNotifications.map(\.message), ["Latest", "Persistent connection", "Timed middle"])
        manager.show("Connection updated", type: .connection, duration: 0, isProcessing: true, dedupeKey: "connection")
        XCTAssertEqual(manager.notifications.first(where: { $0.dedupeKey == "connection" })?.id, connectionID)
        try await Task.sleep(for: .milliseconds(50))
        XCTAssertEqual(manager.visibleNotifications.map(\.message), ["Latest", "Connection updated", "Oldest retained"])
        manager.dismiss()
        XCTAssertEqual(manager.currentToast?.message, "Connection updated")
        XCTAssertEqual(manager.notifications.count, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    @MainActor
    func testSupersededNotificationTimerCannotDismissPersistentReplacement() async throws {
        let manager = ToastManager()
        defer { manager.dismissAll() }
        manager.show("Synthetic timed notice", duration: 0.01, dedupeKey: "connection")
        manager.show("Synthetic persistent notice", type: .connection, duration: 0, dedupeKey: "connection")
        try await Task.sleep(for: .milliseconds(50))
        XCTAssertEqual(manager.currentToast?.message, "Synthetic persistent notice")
        XCTAssertEqual(manager.currentToast?.duration, 0)
        manager.dismiss()
        XCTAssertNil(manager.currentToast)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
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

private actor MockPrivacySettingsAssetDownloader: LocalModelFileDownloading {
    let bytes: Data
    private(set) var requestCount = 0
    init(bytes: Data) { self.bytes = bytes }

    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        requestCount += 1
        try bytes.write(to: destination)
        progress(Int64(bytes.count))
    }
}
