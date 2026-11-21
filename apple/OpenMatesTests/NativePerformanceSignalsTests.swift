// Proves the Apple metadata diagnostics added for TASK-1410: administrator
// all-level forwarding payloads, main-thread stall and frame-window entries,
// and MetricKit scalar summaries that never carry text.

import XCTest
@testable import OpenMates

final class NativePerformanceSignalsTests: XCTestCase {
    override func setUp() {
        super.setUp()
        NativeClientLogCollector.shared.resetForTests()
        NativePerformanceMonitor.shared.resetForTests()
        NativeLogForwarder.shared.resetForTests()
    }

    override func tearDown() {
        NativeLogForwarder.shared.resetForTests()
        super.tearDown()
    }

    private func messages(_ minimumLevel: NativeClientLogLevel? = nil) -> [String] {
        NativeClientLogCollector.shared.entriesSnapshot(limit: 500, minimumLevel: minimumLevel).map(\.message)
    }

    // contract-test: direct surface=gui.apple assertions=issue-reporting.logs.role-aware-forwarding
    func testAdminPayloadCarriesEveryLevelWithoutSecretsAndDefaultTelemetryKeepsWarningsOnly() throws {
        let collector = NativeClientLogCollector.shared
        collector.record(level: .info, category: "network", message: "event=socket_opened generation=2")
        collector.record(level: .warning, category: "sync", message: "warning for user@example.org")
        collector.record(level: .error, category: "api", message: "token=secret")
        let entries = collector.entriesSnapshot(limit: 50)

        let payload = try XCTUnwrap(NativeLogForwarder.adminPayload(entries: entries))
        let logs = try XCTUnwrap(payload["logs"] as? [[String: Any]])
        XCTAssertEqual(logs.compactMap { $0["level"] as? String }, ["info", "warn", "error"])
        XCTAssertNotNil(payload["metadata"] as? [String: String])
        XCTAssertNil(payload["session_pseudonym"], "admin batches use the admin endpoint, not the anonymous one")
        let text = String(describing: payload)
        XCTAssertFalse(text.contains("user@example.org"))
        XCTAssertFalse(text.contains("token=secret"))
        XCTAssertNil(NativeLogForwarder.adminPayload(entries: []))

        let telemetry = try XCTUnwrap(NativeLogForwarder.defaultTelemetryPayload(
            entries: collector.entriesSnapshot(limit: 50, minimumLevel: .warning),
            sessionPseudonym: "11111111-2222-4333-8444-555555555555"))
        let telemetryLevels = (telemetry["logs"] as? [[String: Any]])?.compactMap { $0["level"] as? String }
        XCTAssertEqual(telemetryLevels, ["warn", "error"])
    }

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.role-aware-forwarding
    func testAdminForwardingStartsOnceStopsAndReportsItsStatus() {
        let forwarder = NativeLogForwarder.shared
        XCTAssertFalse(forwarder.isAdminForwardingRunning())
        forwarder.startAdminForwarding(intervalNanoseconds: 60_000_000_000)
        forwarder.startAdminForwarding(intervalNanoseconds: 60_000_000_000)
        XCTAssertTrue(forwarder.isAdminForwardingRunning())
        XCTAssertEqual(forwarder.statusSnapshot()["admin_forwarding_running"] as? Bool, true)
        forwarder.stopAdminForwarding()
        XCTAssertFalse(forwarder.isAdminForwardingRunning())
        XCTAssertEqual(forwarder.statusSnapshot()["admin_forwarding_running"] as? Bool, false)
    }

    // contract-test: direct surface=gui.apple assertions=issue-reporting.logs.native-performance-metadata
    func testStallIsRecordedWithDurationButNormalFramesAndSuspensionsAreNot() {
        let monitor = NativePerformanceMonitor.shared
        monitor.recordFrame(durationMS: 16, uptime: 1)
        monitor.recordFrame(durationMS: 249, uptime: 1.3)
        monitor.recordFrame(durationMS: 412, uptime: 1.8)
        monitor.recordFrame(durationMS: 45_000, uptime: 47)

        let stalls = messages(.warning).filter { $0.contains("event=main_thread_stall") }
        XCTAssertEqual(stalls, ["event=main_thread_stall duration_ms=412"])
    }

    // contract-test: direct surface=gui.apple assertions=issue-reporting.logs.native-performance-metadata
    func testFrameWindowReportsHitchRateWorstFrameAndMemoryOncePerMinute() throws {
        let monitor = NativePerformanceMonitor.shared
        for index in 0..<98 { monitor.recordFrame(durationMS: 16, uptime: Double(index) * 0.5) }
        monitor.recordFrame(durationMS: 80, uptime: 49.5)
        XCTAssertTrue(messages().filter { $0.contains("event=perf_window") }.isEmpty)
        monitor.recordFrame(durationMS: 120, uptime: 60.5)

        let windows = messages().filter { $0.contains("event=perf_window") }
        let window = try XCTUnwrap(windows.first)
        XCTAssertEqual(windows.count, 1)
        XCTAssertTrue(window.contains("frames=100"), window)
        XCTAssertTrue(window.contains("hitch_frames=2"), window)
        XCTAssertTrue(window.contains("hitch_permille=20"), window)
        XCTAssertTrue(window.contains("worst_frame_ms=120"), window)
        XCTAssertTrue(window.contains("memory_mb="), window)
        XCTAssertNotNil(NativePerformanceSignals.memoryFootprintMB())
    }

    // contract-test: direct surface=gui.apple assertions=issue-reporting.logs.native-performance-metadata
    func testMetricKitReportsBecomeScalarEntriesAndSummaries() {
        let metrics = NativePerformanceSignals.recordMetricReport(
            launch: [.init(startMS: 0, endMS: 500, count: 3), .init(startMS: 500, endMS: 1000, count: 1)],
            resume: [],
            hang: [.init(startMS: 250, endMS: 500, count: 2)],
            peakMemoryMB: 412,
            exits: ["fg_watchdog_exits": 1, "bg_memory_limit_exits": 0])
        XCTAssertEqual(metrics["launch_count"], 4)
        XCTAssertEqual(metrics["launch_p50_ms"], 500)
        XCTAssertEqual(metrics["launch_max_ms"], 1000)
        XCTAssertEqual(metrics["hang_count"], 2)
        XCTAssertEqual(metrics["peak_memory_mb"], 412)
        XCTAssertEqual(metrics["fg_watchdog_exits"], 1)
        XCTAssertNil(metrics["bg_memory_limit_exits"], "zero exit counters are left out")
        XCTAssertNil(metrics["resume_count"])

        let diagnostics = NativePerformanceSignals.recordDiagnosticReport(
            hangDurationsMS: [1800, 3200], crashes: [.init(exceptionType: 1, signal: 11)],
            launchDurationsMS: [], cpuExceptions: 0, diskWriteExceptions: 1)
        XCTAssertEqual(diagnostics["hang_count"], 2)
        XCTAssertEqual(diagnostics["hang_max_ms"], 3200)
        XCTAssertEqual(diagnostics["crash_count"], 1)

        let all = messages()
        XCTAssertTrue(all.contains("event=metrickit_hang duration_ms=1800"))
        XCTAssertTrue(all.contains("event=metrickit_hang duration_ms=3200"))
        XCTAssertTrue(all.contains("event=metrickit_crash exception_type=1 signal=11"))
        XCTAssertTrue(all.contains { $0.hasPrefix("event=metrickit_metrics ") && $0.contains("launch_p50_ms=500") })
        XCTAssertTrue(all.contains { $0.hasPrefix("event=metrickit_diagnostics ") && $0.contains("disk_write_exception_count=1") })
        XCTAssertEqual(NativeClientLogCollector.shared.entriesSnapshot(limit: 50, minimumLevel: .error).count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.logs.native-performance-metadata
    func testHistogramWithoutSamplesAddsNothing() {
        XCTAssertTrue(NativePerformanceSignals.histogramCounts([], prefix: "launch").isEmpty)
        XCTAssertTrue(NativePerformanceSignals.histogramCounts([.init(startMS: 0, endMS: 10, count: 0)], prefix: "x").isEmpty)
    }
}
