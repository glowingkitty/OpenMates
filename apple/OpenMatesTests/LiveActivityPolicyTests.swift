import XCTest
import CryptoKit
@testable import OpenMates

final class LiveActivityPolicyTests: XCTestCase {
    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming
    func testApplicationDeclaresActivityKitCapability() {
        XCTAssertEqual(Bundle.main.object(forInfoDictionaryKey: "NSSupportsLiveActivities") as? Bool, true,
            "ActivityKit cannot publish without the application capability")
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.download.progress
    func testAggregateDownloadIncludesVerificationAndRejectsStaleOperation() {
        var policy = LocalModelLiveActivityPolicy()
        let first = UUID(), replacement = UUID(), second = UUID()
        _ = policy.consume(.started(model: .whisper, operation: first, totalBytes: 100))
        _ = policy.consume(.started(model: .privacyFilter, operation: second, totalBytes: 100))
        _ = policy.consume(.progress(model: .whisper, operation: first, value: progress(bytes: 100, verified: 50, sequence: 2)))
        XCTAssertEqual(policy.items.count, 2)
        XCTAssertEqual(policy.progress, 0.375)
        _ = policy.consume(.progress(model: .whisper, operation: first, value: progress(bytes: 20, verified: 0, sequence: 1)))
        XCTAssertEqual(policy.progress, 0.375)
        _ = policy.consume(.started(model: .whisper, operation: replacement, totalBytes: 100))
        _ = policy.consume(.progress(model: .whisper, operation: first, value: progress(bytes: 100, verified: 100, sequence: 3)))
        XCTAssertEqual(policy.progress, 0)
        XCTAssertNil(policy.consume(.finished(model: .whisper, operation: first, outcome: .verified)))
        XCTAssertEqual(policy.items[.whisper]?.operation, replacement)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.download.completion
    func testVerifiedCompletionIsOnceAndCancellationFailureNeverSucceed() {
        var policy = LocalModelLiveActivityPolicy()
        let operation = UUID()
        _ = policy.consume(.started(model: .whisper, operation: operation, totalBytes: 100))
        XCTAssertNotNil(policy.consume(.finished(model: .whisper, operation: operation, outcome: .verified)))
        XCTAssertNil(policy.consume(.finished(model: .whisper, operation: operation, outcome: .verified)))
        for outcome in [LocalModelDownloadOutcome.cancelled, .failed] {
            let operation = UUID()
            _ = policy.consume(.started(model: .whisper, operation: operation, totalBytes: 100))
            XCTAssertNil(policy.consume(.finished(model: .whisper, operation: operation, outcome: outcome)))
            XCTAssertTrue(policy.items.isEmpty)
        }
    }

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.download.progress,apple-live-activities.download.completion
    @MainActor
    func testPrivacyDownloadRequestsCoordinatorAndUpdatesWhileBackgroundedBeforeVerifiedEnd() async throws {
        let suite = "LiveActivityPolicyTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let driver = DownloadActivityEffectProbe()
        var time: TimeInterval = 0
        let coordinator = LocalModelLiveActivityCoordinator(defaults: defaults, driver: driver,
            clock: { time }, completionNotificationsEnabled: false)
        let bytes = Data("public fixture weights".utf8)
        let revision = String(repeating: "a", count: 40)
        let file = LocalModelFile(path: "fixture.bin",
            url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/fixture.bin")!,
            sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), sizeBytes: Int64(bytes.count))
        let manifest = LocalModelManifest(id: .privacyFilter, revision: revision,
            estimatedSizeBytes: file.sizeBytes, files: [file])
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let started = AsyncStream<Void>.makeStream(), transferGate = AsyncStream<Void>.makeStream()
        let verificationGate = AsyncStream<Void>.makeStream()
        let downloading = CoordinatorFixtureDownloader(bytes: bytes, started: started.continuation, gate: transferGate.stream)
        let initialProgress = expectation(description: "store delivered initial transfer progress")
        let verificationObserved = expectation(description: "store delivered verification activity")
        let backgroundProgress = expectation(description: "store delivered background transfer progress")
        let verification = expectation(description: "store reached verification")
        var observedBackgroundProgress = false
        var observedVerification = false
        let store = LocalModelStore(catalog: try JSONEncoder().encode(LocalModelCatalog(models: [manifest])),
            root: root, storageReserveBytes: 0, downloader: downloading, verifyExisting: false,
            activityEvents: { event in
                coordinator.handle(event)
                if case let .progress(_, _, value) = event {
                    if value.phase == .transfer, value.transferredBytes == file.sizeBytes / 4 { initialProgress.fulfill() }
                    if value.phase == .transfer, value.transferredBytes >= file.sizeBytes / 2, !observedBackgroundProgress {
                        observedBackgroundProgress = true
                        backgroundProgress.fulfill()
                    }
                    if value.phase == .verification, !observedVerification {
                        observedVerification = true
                        verificationObserved.fulfill()
                    }
                }
            }, beforeVerification: {
                verification.fulfill()
                for await _ in verificationGate.stream { break }
            })
        let install = Task { await store.download(.privacyFilter) }
        for await _ in started.stream { break }
        await fulfillment(of: [initialProgress], timeout: 5)
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requests.count, 1, "The real store start must request its coordinator, independent of push/UN permission")
        XCTAssertEqual(driver.requests.first?.totalBytes, file.sizeBytes)
        XCTAssertEqual(driver.requests.first?.title, AppStrings.offlineAIModelsEnhancedAnonymization,
                       "Download Live Activities identify the capability without exposing its model")
        driver.foreground = false
        time = 2
        await downloading.advance(file.sizeBytes / 2)
        await fulfillment(of: [backgroundProgress], timeout: 5)
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.backgroundUpdates.last?.completedBytes, file.sizeBytes / 2)
        XCTAssertEqual(driver.requests.count, 1, "Background progress updates the foreground-created activity")
        transferGate.continuation.yield(())
        await fulfillment(of: [verification, verificationObserved], timeout: 5)
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.updates.last?.phase, "verification")
        XCTAssertLessThan(try XCTUnwrap(driver.updates.last?.progress), 1)
        XCTAssertEqual(driver.ends, 0, "Unverified bytes cannot end as a successful install")
        verificationGate.continuation.yield(())
        await install.value
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(store.state(for: .privacyFilter), .ready)
        XCTAssertEqual(driver.ends, 1)
        XCTAssertFalse(driver.hasExistingActivity)
    }

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.download.progress,apple-live-activities.download.completion
    @MainActor
    func testSequentialPackKeepsActivityBetweenModelsWhileBackgrounded() async throws {
        let suite = "LiveActivityPolicyTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let driver = DownloadActivityEffectProbe()
        let coordinator = LocalModelLiveActivityCoordinator(defaults: defaults, driver: driver, completionNotificationsEnabled: false)
        let stt = UUID(), tts = UUID()
        coordinator.setPackActive(true)
        coordinator.handle(.started(model: .whisper, operation: stt, totalBytes: 100))
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requests.count, 1)
        driver.foreground = false
        coordinator.handle(.finished(model: .whisper, operation: stt, outcome: .verified))
        coordinator.refreshPresentation()
        await coordinator.waitForPendingEffects()
        XCTAssertTrue(driver.hasExistingActivity, "An existing activity bridges the model transition")
        XCTAssertEqual(driver.ends, 0)
        coordinator.handle(.started(model: .supertonic3, operation: tts, totalBytes: 200))
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requestAttempts, 1, "Background transition updates the same OS activity")
        XCTAssertEqual(driver.backgroundUpdates.last?.totalBytes, 200)
        coordinator.handle(.finished(model: .supertonic3, operation: tts, outcome: .verified))
        coordinator.setPackActive(false)
        await coordinator.waitForPendingEffects()
        XCTAssertFalse(driver.hasExistingActivity)
        XCTAssertEqual(driver.ends, 1)
    }

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.download.progress,apple-live-activities.lifecycle.isolation
    @MainActor
    func testActivityAuthorizationForegroundRetryAndUserDismissalAreIndependentOfPushSettings() async throws {
        let suite = "LiveActivityPolicyTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let driver = DownloadActivityEffectProbe()
        driver.activitiesEnabled = false
        let coordinator = LocalModelLiveActivityCoordinator(defaults: defaults, driver: driver, completionNotificationsEnabled: false)
        coordinator.handle(.started(model: .privacyFilter, operation: UUID(), totalBytes: 100))
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requestAttempts, 0)
        driver.activitiesEnabled = true
        driver.foreground = false
        coordinator.refreshPresentation()
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requestAttempts, 0, "A new activity must wait for foreground")
        driver.foreground = true
        driver.failNextRequest = true
        coordinator.refreshPresentation()
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requestAttempts, 1)
        XCTAssertTrue(driver.requests.isEmpty)
        coordinator.refreshPresentation()
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requests.count, 1, "A failed ActivityKit request must not latch dismissal")
        driver.hasExistingActivity = false // OS/user dismissed a successfully requested activity.
        coordinator.refreshPresentation()
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requestAttempts, 2, "A successful dismissed batch must not be recreated")
    }

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.download.progress,apple-live-activities.lifecycle.isolation
    @MainActor
    func testColdRelaunchRestoresWatermarkAndDoesNotRecreateDismissedOperation() async throws {
        let suite = "LiveActivityPolicyTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let operation = UUID(), driver = DownloadActivityEffectProbe()
        let original = LocalModelLiveActivityCoordinator(defaults: defaults, driver: driver,
            clock: { 2 }, completionNotificationsEnabled: false)
        original.handle(.started(model: .privacyFilter, operation: operation, totalBytes: 100))
        original.handle(.progress(model: .privacyFilter, operation: operation,
            value: progress(bytes: 80, verified: 20, sequence: 2)))
        await original.waitForPendingEffects()
        let restoredDriver = DownloadActivityEffectProbe()
        restoredDriver.hasExistingActivity = true
        restoredDriver.foreground = false
        let restored = LocalModelLiveActivityCoordinator(defaults: defaults, driver: restoredDriver,
            completionNotificationsEnabled: false)
        restored.handle(.started(model: .privacyFilter, operation: operation, totalBytes: 100))
        await restored.waitForPendingEffects()
        XCTAssertEqual(restoredDriver.updates.first?.completedBytes, 80)
        XCTAssertEqual(restoredDriver.updates.first?.progress, 0.5)
        restored.handle(.progress(model: .privacyFilter, operation: operation,
            value: .init(phase: .retrying, transferredBytes: 10, verifiedBytes: 0, totalBytes: 100, sequence: 1, retryAttempt: 1)))
        await restored.waitForPendingEffects()
        XCTAssertEqual(restoredDriver.updates.last?.progress, 0.5, "A reattached task cannot regress its durable watermark")
        restoredDriver.hasExistingActivity = false
        restoredDriver.foreground = true
        let dismissed = LocalModelLiveActivityCoordinator(defaults: defaults, driver: restoredDriver, completionNotificationsEnabled: false)
        dismissed.handle(.started(model: .privacyFilter, operation: operation, totalBytes: 100))
        await dismissed.waitForPendingEffects()
        XCTAssertEqual(restoredDriver.requestAttempts, 0)
    }

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.lifecycle.isolation,apple-live-activities.download.completion
    @MainActor
    func testResetFencesQueuedStartAndCancellationEndsExistingActivity() async throws {
        let suite = "LiveActivityPolicyTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let driver = DownloadActivityEffectProbe()
        let coordinator = LocalModelLiveActivityCoordinator(defaults: defaults, driver: driver, completionNotificationsEnabled: false)
        coordinator.handle(.started(model: .whisper, operation: UUID(), totalBytes: 100))
        await coordinator.reset()
        await coordinator.waitForPendingEffects()
        XCTAssertTrue(driver.requests.isEmpty, "A queued start from the previous account generation cannot escape reset")
        let operation = UUID()
        coordinator.handle(.started(model: .privacyFilter, operation: operation, totalBytes: 100))
        await coordinator.waitForPendingEffects()
        XCTAssertEqual(driver.requests.count, 1)
        coordinator.handle(.finished(model: .privacyFilter, operation: operation, outcome: .cancelled))
        await coordinator.waitForPendingEffects()
        XCTAssertFalse(driver.hasExistingActivity)
        XCTAssertEqual(driver.ends, 2)
    }

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.download.progress
    func testDurableTransferWatermarkBoundsReattachmentRetryAndCompletion() {
        XCTAssertEqual(LocalModelTransferWatermark.advance(previous: 80, reported: 10, total: 100), 80)
        XCTAssertEqual(LocalModelTransferWatermark.advance(previous: 80, reported: 90, total: 100), 90)
        XCTAssertEqual(LocalModelTransferWatermark.advance(previous: 90, reported: 120, total: 100), 100)
        XCTAssertEqual(LocalModelTransferWatermark.advance(previous: -10, reported: -1, total: 100), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming
    func testTypedTimestampsUseOffsetsAndFourHourBoundary() {
        let now = UpcomingMemoryActivityPolicy.parseTimestamp("2026-10-03T10:00:00Z")!
        let entries = [entry("event", app: "events", category: "saved_events", fields: ["date_start": .string("2026-10-03T16:00:00+02:00")]),
                       entry("appointment", app: "health", category: "appointments", fields: ["appointment_time": .string("2026-10-03T11:00:00Z")]),
                       entry("connection", app: "travel", category: "saved_connections", fields: ["departure": .string("2026-10-03T18:00:00+02:00")])]
        let candidates = UpcomingMemoryActivityPolicy.candidates(from: entries, now: now)
        XCTAssertEqual(candidates.map(\.memoryID), ["appointment", "event", "connection"])
        XCTAssertEqual(candidates[1].activityStartsAt, now)
        XCTAssertEqual(candidates[2].activityStartsAt, now.addingTimeInterval(2 * 3_600))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testUpcomingExcludesUnlinkedPastCancelledExamplesAndUnspecifiedTimes() {
        let now = UpcomingMemoryActivityPolicy.parseTimestamp("2026-10-03T10:00:00Z")!
        let valid: [String: SettingsMemoryValue] = ["date_start": .string("2026-10-03T11:00:00Z")]
        var example = entry("example", app: "events", category: "saved_events", fields: valid)
        example = .init(id: example.id, appId: example.appId, categoryId: example.categoryId,
                        key: "", value: "", createdAt: 0, updatedAt: 0, version: 1, isExample: true, fields: example.fields)
        let entries = [example,
            entry("cancelled", app: "events", category: "saved_events", fields: valid.merging(["status": .string("cancelled")]) { _, b in b }),
            entry("deleted", app: "events", category: "saved_events", fields: valid.merging(["deleted": .bool(true)]) { _, b in b }),
            entry("unlinked", app: "events", category: "saved_events", fields: valid.merging(["embed_id": .null]) { _, b in b }),
            entry("past", app: "events", category: "saved_events", fields: ["date_start": .string("2026-10-03T09:00:00Z")]),
            entry("date-only", app: "health", category: "appointments", fields: ["date": .string("2026-10-03")]),
            entry("naive", app: "events", category: "saved_events", fields: ["date_start": .string("2026-10-03T11:00:00")]),
            entry("invalid-end", app: "events", category: "saved_events", fields: valid.merging(["date_end": .string("2026-10-03T09:00:00Z")]) { _, b in b })]
        XCTAssertTrue(UpcomingMemoryActivityPolicy.candidates(from: entries, now: now).isEmpty)
        XCTAssertNil(UpcomingMemoryActivityPolicy.parseTimestamp("private notes at 11:00"))
        XCTAssertNil(UpcomingMemoryActivityPolicy.parseTimestamp("2026-02-30T11:00:00Z"))
    }

    private func progress(bytes: Int64, verified: Int64, sequence: UInt64) -> LocalModelInstallProgress {
        .init(phase: .verification, transferredBytes: bytes, verifiedBytes: verified,
              totalBytes: 100, sequence: sequence, retryAttempt: 0)
    }
    private func entry(_ id: String, app: String, category: String, fields: [String: SettingsMemoryValue]) -> SettingsMemoryEntry {
        .init(id: id, appId: app, categoryId: category, key: "", value: "private canary omitted", createdAt: 0,
              updatedAt: 0, version: 1, isExample: false, fields: ["embed_id": .string("embed-" + id)].merging(fields) { _, b in b })
    }
}

@MainActor
private final class DownloadActivityEffectProbe: LocalModelLiveActivityDriving {
    var activitiesEnabled = true
    var foreground = true
    var hasExistingActivity = false
    var failNextRequest = false
    private(set) var requestAttempts = 0
    private(set) var requests: [LocalModelActivityPresentation] = []
    private(set) var updates: [LocalModelActivityPresentation] = []
    private(set) var backgroundUpdates: [LocalModelActivityPresentation] = []
    private(set) var ends = 0
    func request(_ state: LocalModelActivityPresentation) throws {
        requestAttempts += 1
        if failNextRequest { failNextRequest = false; throw LocalModelInstallError.invalidResponse }
        requests.append(state)
        hasExistingActivity = true
    }
    func update(_ state: LocalModelActivityPresentation) async {
        updates.append(state)
        if !foreground { backgroundUpdates.append(state) }
    }
    func end() async { ends += 1; hasExistingActivity = false }
}

private actor CoordinatorFixtureDownloader: LocalModelFileDownloading {
    let bytes: Data
    let started: AsyncStream<Void>.Continuation
    let gate: AsyncStream<Void>
    private var report: (@Sendable (Int64) -> Void)?
    init(bytes: Data, started: AsyncStream<Void>.Continuation, gate: AsyncStream<Void>) {
        self.bytes = bytes; self.started = started; self.gate = gate
    }
    func advance(_ bytes: Int64) { report?(bytes) }
    func download(_ file: LocalModelFile, to destination: URL, progress: @escaping @Sendable (Int64) -> Void) async throws {
        report = progress
        progress(file.sizeBytes / 4)
        started.yield(())
        for await _ in gate { break }
        try Task.checkCancellation()
        progress(file.sizeBytes)
        try bytes.write(to: destination)
    }
}
