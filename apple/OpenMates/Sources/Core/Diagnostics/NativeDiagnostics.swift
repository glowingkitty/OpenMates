// Native diagnostics primitives for issue reports, debug sessions, and telemetry.
// Centralizes privacy-safe Apple logging so support reports include useful
// runtime context without collecting message plaintext, keys, tokens, cookies,
// request/response bodies, private file paths, or raw typed text.
// Mirrors the web log collector/action tracker shape with native-only signals.

import Foundation
import OSLog
#if os(iOS)
import UIKit
#endif
#if canImport(MetricKit)
import MetricKit
#endif

enum NativeClientLogLevel: String {
    case debug
    case info
    case warning
    case error
}

struct NativeClientLogEntry: Equatable {
    let sequence: Int
    let timestamp: Date
    let level: NativeClientLogLevel
    let category: String
    let message: String

    func forwardingPayload() -> [String: Any] {
        [
            "timestamp": Int(timestamp.timeIntervalSince1970 * 1000),
            "level": level.forwardingValue,
            "message": "[\(category)] \(message)",
            "source": "apple_native",
        ]
    }
}

private extension NativeClientLogLevel {
    var forwardingValue: String {
        switch self {
        case .debug: return "debug"
        case .info: return "info"
        case .warning: return "warn"
        case .error: return "error"
        }
    }
}

enum NativeDiagnostics {
    private static let logger = Logger(subsystem: "org.openmates.app", category: "NativeDiagnostics")

    static func debug(_ message: String, category: String = "app") {
        record(level: .debug, category: category, message: message)
    }

    static func info(_ message: String, category: String = "app") {
        record(level: .info, category: category, message: message)
    }

    static func warning(_ message: String, category: String = "app") {
        record(level: .warning, category: category, message: message)
    }

    static func error(_ message: String, category: String = "app") {
        record(level: .error, category: category, message: message)
    }

    static func record(level: NativeClientLogLevel, category: String, message: String) {
        let safeCategory = NativeClientLogCollector.sanitize(category)
        let sanitized = NativeClientLogCollector.sanitize(message)
        switch level {
        case .debug:
            logger.debug("[\(safeCategory, privacy: .public)] \(sanitized, privacy: .public)")
        case .info:
            logger.info("[\(safeCategory, privacy: .public)] \(sanitized, privacy: .public)")
        case .warning:
            logger.warning("[\(safeCategory, privacy: .public)] \(sanitized, privacy: .public)")
        case .error:
            logger.error("[\(safeCategory, privacy: .public)] \(sanitized, privacy: .public)")
        }
        NativeClientLogCollector.shared.record(level: level, category: safeCategory, message: sanitized)
    }
}

final class NativeClientLogCollector: @unchecked Sendable {
    static let shared = NativeClientLogCollector()
    private static let maxEntries = 200
    private static let maxImportantCarryover = 40
    private static let maxStringLength = 320

    private let lock = NSLock()
    private var entries: [NativeClientLogEntry] = []
    private var nextSequence = 1

    private init() {}

    func record(level: NativeClientLogLevel, category: String, message: String) {
        lock.lock()
        let entry = NativeClientLogEntry(
            sequence: nextSequence,
            timestamp: Date(),
            level: level,
            category: Self.sanitize(category),
            message: Self.sanitize(message)
        )
        nextSequence += 1
        entries.append(entry)
        pruneLocked()
        lock.unlock()
    }

    func resetForTests() {
        lock.lock()
        entries.removeAll()
        nextSequence = 1
        lock.unlock()
    }

    func entriesSnapshot(limit: Int, minimumLevel: NativeClientLogLevel? = nil) -> [NativeClientLogEntry] {
        lock.lock()
        let snapshot = entries
        lock.unlock()

        let filtered = snapshot.filter { entry in
            guard let minimumLevel else { return true }
            return Self.priority(entry.level) >= Self.priority(minimumLevel)
        }
        return Array(filtered.suffix(max(0, limit)))
    }

    func entriesAfter(sequence: Int, limit: Int, minimumLevel: NativeClientLogLevel? = nil) -> [NativeClientLogEntry] {
        lock.lock()
        let snapshot = entries
        lock.unlock()

        let filtered = snapshot.filter { entry in
            guard entry.sequence > sequence else { return false }
            guard let minimumLevel else { return true }
            return Self.priority(entry.level) >= Self.priority(minimumLevel)
        }
        return Array(filtered.prefix(max(0, limit)))
    }

    func logsAsText(limit: Int) -> String {
        entriesSnapshot(limit: limit).map { entry in
            "[\(NativeDiagnosticsDateFormatter.string(from: entry.timestamp))] [\(entry.level.rawValue.uppercased())] [\(entry.category)] \(entry.message)"
        }.joined(separator: "\n")
    }

    func issueLogPayload(issueId: String, pageURL: String) -> [String: Any] {
        [
            "issue_id": Self.sanitize(issueId),
            "logs_text": logsAsText(limit: 150),
            "page_url": Self.sanitize(pageURL),
            "user_agent": NativeDeviceInfo.userAgent,
        ]
    }

    static func sanitize(_ value: String) -> String {
        var sanitized = value
        let replacements: [(String, String)] = [
            (#"#[A-Za-z0-9_-]*key=[^\s\]]+"#, "#key=<redacted>"),
            (#"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"#, "<email>"),
            (#"(?i)(authorization|password|token|secret|api[_-]?key)=([^\s&]+)"#, "$1=<redacted>"),
            (#"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"#, "Bearer <redacted>"),
            (#"file://[^\s\]]+"#, "file://<redacted>"),
            (#"/(Users|private|var/mobile)/[^\s\]]+"#, "/<redacted-path>"),
            (#"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"#, "<id>"),
            (#"\b[A-Za-z0-9+/=_-]{48,}\b"#, "<blob>"),
        ]
        for (pattern, replacement) in replacements {
            sanitized = sanitized.replacingOccurrences(
                of: pattern,
                with: replacement,
                options: [.regularExpression, .caseInsensitive]
            )
        }
        if sanitized.count > maxStringLength {
            sanitized = String(sanitized.prefix(maxStringLength)) + " <truncated>"
        }
        return sanitized
    }

    static func sanitizeValue(_ value: Any) -> Any {
        if let string = value as? String { return sanitize(string) }
        if let bool = value as? Bool { return bool }
        if let number = value as? NSNumber { return number }
        if let dictionary = value as? [String: Any] {
            return dictionary.reduce(into: [String: Any]()) { result, item in
                result[sanitize(item.key)] = sanitizeValue(item.value)
            }
        }
        if let array = value as? [Any] {
            return array.map(sanitizeValue)
        }
        return String(describing: value)
    }

    private func pruneLocked() {
        guard entries.count > Self.maxEntries else { return }
        let overflow = entries.count - Self.maxEntries
        let importantCarryover = entries
            .prefix(max(0, overflow))
            .filter { $0.level == .warning || $0.level == .error }
            .suffix(Self.maxImportantCarryover)
        let remainingCapacity = max(0, Self.maxEntries - importantCarryover.count)
        entries = Array(importantCarryover) + Array(entries.suffix(remainingCapacity))
    }

    private static func priority(_ level: NativeClientLogLevel) -> Int {
        switch level {
        case .debug: return 0
        case .info: return 1
        case .warning: return 2
        case .error: return 3
        }
    }
}

final class NativeActionTracker: @unchecked Sendable {
    static let shared = NativeActionTracker()
    private static let maxActions = 80

    private let lock = NSLock()
    private var actions: [NativeActionEntry] = []

    private init() {}

    func recordRoute(_ route: String) {
        record(type: "route", label: route)
    }

    func recordControl(_ control: String) {
        record(type: "control", label: control)
    }

    func recordTextInput(_ _: String) {
        record(type: "text_input", label: "<suppressed>")
    }

    func record(type: String, label: String) {
        guard type != "text_input" else { return }
        let entry = NativeActionEntry(
            timestamp: Date(),
            type: NativeClientLogCollector.sanitize(type),
            label: NativeClientLogCollector.sanitize(label)
        )
        lock.lock()
        actions.append(entry)
        if actions.count > Self.maxActions {
            actions.removeFirst(actions.count - Self.maxActions)
        }
        lock.unlock()
    }

    func actionsAsText(limit: Int = 50) -> String {
        lock.lock()
        let snapshot = Array(actions.suffix(max(0, limit)))
        lock.unlock()

        return snapshot.map { entry in
            "[\(NativeDiagnosticsDateFormatter.string(from: entry.timestamp))] [\(entry.type)] \(entry.label)"
        }.joined(separator: "\n")
    }

    func resetForTests() {
        lock.lock()
        actions.removeAll()
        lock.unlock()
    }
}

private struct NativeActionEntry: Equatable {
    let timestamp: Date
    let type: String
    let label: String
}

struct NativeIssueContext {
    let consoleLogs: String
    let runtimeDebugState: [String: Any]
    let actionHistory: String
}

struct NativeDebugSessionResponse: Decodable {
    let active: Bool
    let debuggingId: String?
}

final class NativeIssueContextProvider: @unchecked Sendable {
    static let shared = NativeIssueContextProvider()

    private init() {}

    func context() -> NativeIssueContext {
        let actions = NativeActionTracker.shared.actionsAsText(limit: 50)
        return NativeIssueContext(
            consoleLogs: NativeClientLogCollector.shared.logsAsText(limit: 150),
            runtimeDebugState: NativeRuntimeSnapshotProvider.snapshot(),
            actionHistory: actions.isEmpty ? "native:settings/report_issue" : actions
        )
    }
}

enum NativeRuntimeSnapshotProvider {
    static func snapshot() -> [String: Any] {
        [
            "platform": "apple_native",
            "bundle_id": Bundle.main.bundleIdentifier ?? "org.openmates.app",
            "app_version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "unknown",
            "native_diagnostics": [
                "generated_at": NativeDiagnosticsDateFormatter.string(from: Date()),
                "system_state": NativePerformanceMonitor.systemState(),
                "offline_inspection": NativeOfflineInspection.summary(),
                "frame_metrics": NativePerformanceMonitor.shared.summary(),
                "metric_kit": NativeMetricKitReporter.shared.latestSummaries(),
                "recent_warning_error_count": NativeClientLogCollector.shared.entriesSnapshot(limit: 200, minimumLevel: .warning).count,
            ],
        ]
    }
}

enum NativeOfflineInspection {
    static func summary() -> [String: Any] {
        [
            "mode": "counts_only",
            "chat_records": "not_inspected",
            "message_records": "not_inspected",
            "embed_records": "not_inspected",
            "encrypted_fields": "presence_and_lengths_only",
            "plaintext_excluded": true,
        ]
    }
}

final class NativePerformanceMonitor: @unchecked Sendable {
    static let shared = NativePerformanceMonitor()
    private static let maxSamples = 240
    private static let jankThresholdMS = 50

    private let lock = NSLock()
    private var frameDurationsMS: [Int] = []
    #if os(iOS)
    @MainActor private var displayLinkProbe: NativeDisplayLinkProbe?
    #endif

    private init() {}

    func recordFrame(durationMS: Int) {
        lock.lock()
        frameDurationsMS.append(max(0, durationMS))
        if frameDurationsMS.count > Self.maxSamples {
            frameDurationsMS.removeFirst(frameDurationsMS.count - Self.maxSamples)
        }
        lock.unlock()
    }

    func summary() -> [String: Any] {
        lock.lock()
        let samples = frameDurationsMS
        lock.unlock()

        guard !samples.isEmpty else {
            return [
                "sample_count": 0,
                "status": "no_recent_frame_samples",
            ]
        }
        let total = samples.reduce(0, +)
        let averageFrameMS = Double(total) / Double(samples.count)
        let averageFPS = averageFrameMS > 0 ? 1000 / averageFrameMS : 0
        return [
            "sample_count": samples.count,
            "average_fps": (averageFPS * 10).rounded() / 10,
            "worst_frame_ms": samples.max() ?? 0,
            "jank_count": samples.filter { $0 >= Self.jankThresholdMS }.count,
        ]
    }

    func resetForTests() {
        lock.lock()
        frameDurationsMS.removeAll()
        lock.unlock()
    }

    @MainActor
    func startSampling() {
        #if os(iOS)
        guard displayLinkProbe == nil else { return }
        let probe = NativeDisplayLinkProbe { [weak self] durationMS in
            self?.recordFrame(durationMS: durationMS)
        }
        displayLinkProbe = probe
        probe.start()
        #endif
    }

    @MainActor
    func stopSampling() {
        #if os(iOS)
        displayLinkProbe?.stop()
        displayLinkProbe = nil
        #endif
    }

    @MainActor
    func isSamplingForTests() -> Bool {
        #if os(iOS)
        return displayLinkProbe != nil
        #else
        return false
        #endif
    }

    static func systemState() -> [String: Any] {
        var state: [String: Any] = [
            "thermal_state": String(describing: ProcessInfo.processInfo.thermalState),
        ]
        #if os(iOS) || os(macOS)
        state["low_power_mode"] = ProcessInfo.processInfo.isLowPowerModeEnabled
        #endif
        return state
    }
}

#if os(iOS)
@MainActor
private final class NativeDisplayLinkProbe {
    private var displayLink: CADisplayLink?
    private var previousTimestamp: CFTimeInterval?
    private let onFrame: @Sendable (Int) -> Void

    init(onFrame: @escaping @Sendable (Int) -> Void) {
        self.onFrame = onFrame
    }

    func start() {
        guard displayLink == nil else { return }
        let link = CADisplayLink(target: self, selector: #selector(tick(_:)))
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    func stop() {
        displayLink?.invalidate()
        displayLink = nil
        previousTimestamp = nil
    }

    @objc private func tick(_ link: CADisplayLink) {
        defer { previousTimestamp = link.timestamp }
        guard let previousTimestamp else { return }
        let durationMS = Int((link.timestamp - previousTimestamp) * 1000)
        onFrame(durationMS)
    }
}
#endif

final class NativeMetricKitReporter: NSObject, @unchecked Sendable {
    static let shared = NativeMetricKitReporter()
    private static let maxSummaries = 12

    private let lock = NSLock()
    private var summaries: [[String: Any]] = []
    private var hasStarted = false

    private override init() {}

    func recordSummary(_ summary: [String: Any]) {
        let sanitized = NativeClientLogCollector.sanitizeValue(summary) as? [String: Any] ?? [:]
        lock.lock()
        summaries.append(sanitized)
        if summaries.count > Self.maxSummaries {
            summaries.removeFirst(summaries.count - Self.maxSummaries)
        }
        lock.unlock()
    }

    func start() {
        lock.lock()
        guard !hasStarted else {
            lock.unlock()
            return
        }
        hasStarted = true
        lock.unlock()

        #if canImport(MetricKit)
        MXMetricManager.shared.add(self)
        #endif
    }

    func stop() {
        lock.lock()
        let wasStarted = hasStarted
        hasStarted = false
        lock.unlock()

        #if canImport(MetricKit)
        if wasStarted {
            MXMetricManager.shared.remove(self)
        }
        #endif
    }

    func latestSummaries() -> [[String: Any]] {
        lock.lock()
        let snapshot = summaries
        lock.unlock()
        if snapshot.isEmpty {
            return [[
                "status": "unavailable",
                "reason": "no_recent_metric_kit_reports",
            ]]
        }
        return snapshot
    }

    func resetForTests() {
        lock.lock()
        summaries.removeAll()
        hasStarted = false
        lock.unlock()
    }

    func isStartedForTests() -> Bool {
        lock.lock()
        let started = hasStarted
        lock.unlock()
        return started
    }
}

#if canImport(MetricKit)
extension NativeMetricKitReporter: MXMetricManagerSubscriber {
    func didReceive(_ payloads: [MXMetricPayload]) {
        for payload in payloads {
            recordMetricKitPayload(type: "metric", payload: payload.dictionaryRepresentation())
        }
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        for payload in payloads {
            recordMetricKitPayload(type: "diagnostic", payload: payload.dictionaryRepresentation())
        }
    }

    private func recordMetricKitPayload(type: String, payload: [AnyHashable: Any]) {
        recordSummary([
            "report_type": type,
            "received_at": NativeDiagnosticsDateFormatter.string(from: Date()),
            "payload_keys": payload.keys.map { String(describing: $0) }.sorted(),
        ])
    }
}
#endif

final class NativeLogForwarder: @unchecked Sendable {
    static let shared = NativeLogForwarder()
    private static let defaultFlushIntervalNanoseconds: UInt64 = 30_000_000_000

    private let lock = NSLock()
    private var defaultTelemetryTask: Task<Void, Never>?
    private var debugSessionTask: Task<Void, Never>?
    private var lastDefaultTelemetrySequence = 0
    private var lastDebugSessionSequence = 0
    private let sessionPseudonym = UUID().uuidString.lowercased()

    private init() {}

    static func debugSessionPayload(debuggingID: String) -> [String: Any] {
        debugSessionPayload(
            debuggingID: debuggingID,
            entries: NativeClientLogCollector.shared.entriesSnapshot(limit: 50)
        )
    }

    static func debugSessionPayload(debuggingID: String, entries: [NativeClientLogEntry]) -> [String: Any] {
        [
            "debugging_id": NativeClientLogCollector.sanitize(debuggingID),
            "logs": entries.map { $0.forwardingPayload() },
            "metadata": defaultMetadata(pageURL: "apple://native"),
        ]
    }

    static func defaultTelemetryPayload(
        isAuthenticated: Bool,
        optedOut: Bool,
        installPseudonym: String = UUID().uuidString.lowercased()
    ) -> [String: Any]? {
        guard isAuthenticated, !optedOut else { return nil }
        let entries = NativeClientLogCollector.shared.entriesSnapshot(limit: 50, minimumLevel: .warning)
        return defaultTelemetryPayload(entries: entries, sessionPseudonym: installPseudonym)
    }

    static func defaultTelemetryPayload(entries: [NativeClientLogEntry], sessionPseudonym: String) -> [String: Any]? {
        let logs = entries.map { $0.forwardingPayload() }
        guard !logs.isEmpty else { return nil }
        let backendSessionID = backendUUID(sessionPseudonym)
        return [
            "logs": logs,
            "metadata": [
                "userAgent": NativeDeviceInfo.userAgent,
                "pageUrl": "apple://native",
                "tabId": backendSessionID,
            ],
            "session_pseudonym": backendSessionID,
        ]
    }

    func startDefaultTelemetry(intervalNanoseconds: UInt64 = defaultFlushIntervalNanoseconds) {
        lock.lock()
        if defaultTelemetryTask != nil {
            lock.unlock()
            return
        }
        defaultTelemetryTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.flushDefaultTelemetry()
                try? await Task.sleep(nanoseconds: intervalNanoseconds)
            }
        }
        lock.unlock()
    }

    func stopDefaultTelemetry() {
        lock.lock()
        defaultTelemetryTask?.cancel()
        defaultTelemetryTask = nil
        lock.unlock()
    }

    func startDebugSession(debuggingID: String, intervalNanoseconds: UInt64 = defaultFlushIntervalNanoseconds) {
        let safeDebuggingID = NativeClientLogCollector.sanitize(debuggingID)
        lock.lock()
        debugSessionTask?.cancel()
        debugSessionTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.flushDebugSession(debuggingID: safeDebuggingID)
                try? await Task.sleep(nanoseconds: intervalNanoseconds)
            }
        }
        lock.unlock()
    }

    func stopDebugSession() {
        lock.lock()
        debugSessionTask?.cancel()
        debugSessionTask = nil
        lock.unlock()
    }

    func syncActiveDebugSession() async {
        do {
            let response: NativeDebugSessionResponse = try await APIClient.shared.request(
                .get,
                path: "/v1/settings/debug-session"
            )
            if response.active, let debuggingID = response.debuggingId, !debuggingID.isEmpty {
                startDebugSession(debuggingID: debuggingID)
            } else {
                stopDebugSession()
            }
        } catch {
            NativeClientLogCollector.shared.record(
                level: .warning,
                category: "native_log_forwarder",
                message: "Checking active debug session failed: \(error.localizedDescription)"
            )
        }
    }

    func flushDefaultTelemetry() async {
        guard !NativeDiagnosticsPreferences.defaultTelemetryOptedOut else { return }
        let lastSequence = readLastDefaultTelemetrySequence()
        let entries = NativeClientLogCollector.shared.entriesAfter(sequence: lastSequence, limit: 50, minimumLevel: .warning)
        guard let payload = Self.defaultTelemetryPayload(entries: entries, sessionPseudonym: sessionPseudonym) else { return }
        await post(path: "/v1/client-logs", payload: payload)
        updateLastDefaultTelemetrySequence(entries.last?.sequence ?? lastSequence)
    }

    func flushDebugSession(debuggingID: String) async {
        let lastSequence = readLastDebugSessionSequence()
        let entries = NativeClientLogCollector.shared.entriesAfter(sequence: lastSequence, limit: 50)
        guard !entries.isEmpty else { return }
        let payload = Self.debugSessionPayload(debuggingID: debuggingID, entries: entries)
        await post(path: "/v1/settings/debug-logs", payload: payload)
        updateLastDebugSessionSequence(entries.last?.sequence ?? lastSequence)
    }

    func resetForTests() {
        lock.lock()
        defaultTelemetryTask?.cancel()
        debugSessionTask?.cancel()
        defaultTelemetryTask = nil
        debugSessionTask = nil
        lastDefaultTelemetrySequence = 0
        lastDebugSessionSequence = 0
        lock.unlock()
    }

    func isDefaultTelemetryRunningForTests() -> Bool {
        lock.lock()
        let running = defaultTelemetryTask != nil
        lock.unlock()
        return running
    }

    private func post(path: String, payload: [String: Any]) async {
        do {
            let data = try JSONSerialization.data(withJSONObject: payload)
            let _: Data = try await APIClient.shared.request(.post, path: path, body: JSONRawBody(data: data))
        } catch {
            NativeClientLogCollector.shared.record(
                level: .warning,
                category: "native_log_forwarder",
                message: "Forwarding to \(path) failed: \(error.localizedDescription)"
            )
        }
    }

    private func readLastDefaultTelemetrySequence() -> Int {
        lock.lock()
        let value = lastDefaultTelemetrySequence
        lock.unlock()
        return value
    }

    private func updateLastDefaultTelemetrySequence(_ sequence: Int) {
        lock.lock()
        lastDefaultTelemetrySequence = max(lastDefaultTelemetrySequence, sequence)
        lock.unlock()
    }

    private func readLastDebugSessionSequence() -> Int {
        lock.lock()
        let value = lastDebugSessionSequence
        lock.unlock()
        return value
    }

    private func updateLastDebugSessionSequence(_ sequence: Int) {
        lock.lock()
        lastDebugSessionSequence = max(lastDebugSessionSequence, sequence)
        lock.unlock()
    }

    private static func defaultMetadata(pageURL: String) -> [String: String] {
        [
            "userAgent": NativeDeviceInfo.userAgent,
            "pageUrl": NativeClientLogCollector.sanitize(pageURL),
            "tabId": NativeInstallPseudonym.value,
        ]
    }

    private static func backendUUID(_ value: String) -> String {
        UUID(uuidString: value)?.uuidString.lowercased() ?? UUID().uuidString.lowercased()
    }
}

private enum NativeInstallPseudonym {
    private static let key = "openmates.nativeInstallPseudonym"

    static var value: String {
        if let existing = UserDefaults.standard.string(forKey: key), UUID(uuidString: existing) != nil {
            return existing.lowercased()
        }
        let created = UUID().uuidString.lowercased()
        UserDefaults.standard.set(created, forKey: key)
        return created
    }
}

enum NativeDiagnosticsPreferences {
    private static let defaultTelemetryOptOutKey = "openmates.defaultTelemetryOptedOut"

    static var defaultTelemetryOptedOut: Bool {
        UserDefaults.standard.bool(forKey: defaultTelemetryOptOutKey)
    }

    static func setDefaultTelemetryOptedOut(_ optedOut: Bool) {
        UserDefaults.standard.set(optedOut, forKey: defaultTelemetryOptOutKey)
    }
}

private enum NativeDeviceInfo {
    static var userAgent: String {
        #if os(iOS)
        return "OpenMates-Apple/iOS"
        #elseif os(macOS)
        return "OpenMates-Apple/macOS"
        #else
        return "OpenMates-Apple"
        #endif
    }
}

private enum NativeDiagnosticsDateFormatter {
    static func string(from date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}
