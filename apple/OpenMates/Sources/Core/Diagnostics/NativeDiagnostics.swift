// Native diagnostics primitives for issue reports, debug sessions, and telemetry.
// Centralizes privacy-safe Apple logging so support reports include useful
// runtime context without collecting message plaintext, keys, tokens, cookies,
// request/response bodies, private file paths, or raw typed text.
// Mirrors the web log collector/action tracker shape with native-only signals.

import Foundation
import OSLog

enum NativeClientLogLevel: String {
    case debug
    case info
    case warning
    case error
}

struct NativeClientLogEntry: Equatable {
    let timestamp: Date
    let level: NativeClientLogLevel
    let category: String
    let message: String

    func payload() -> [String: Any] {
        [
            "timestamp": NativeDiagnosticsDateFormatter.string(from: timestamp),
            "level": level.rawValue,
            "category": category,
            "message": message,
            "source": "apple_native",
        ]
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

    private init() {}

    func record(level: NativeClientLogLevel, category: String, message: String) {
        let entry = NativeClientLogEntry(
            timestamp: Date(),
            level: level,
            category: Self.sanitize(category),
            message: Self.sanitize(message)
        )
        lock.lock()
        entries.append(entry)
        pruneLocked()
        lock.unlock()
    }

    func resetForTests() {
        lock.lock()
        entries.removeAll()
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

final class NativeIssueContextProvider {
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

final class NativeMetricKitReporter: @unchecked Sendable {
    static let shared = NativeMetricKitReporter()
    private static let maxSummaries = 12

    private let lock = NSLock()
    private var summaries: [[String: Any]] = []

    private init() {}

    func recordSummary(_ summary: [String: Any]) {
        let sanitized = NativeClientLogCollector.sanitizeValue(summary) as? [String: Any] ?? [:]
        lock.lock()
        summaries.append(sanitized)
        if summaries.count > Self.maxSummaries {
            summaries.removeFirst(summaries.count - Self.maxSummaries)
        }
        lock.unlock()
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
        lock.unlock()
    }
}

enum NativeLogForwarder {
    static func debugSessionPayload(debuggingID: String) -> [String: Any] {
        [
            "debugging_id": NativeClientLogCollector.sanitize(debuggingID),
            "logs": NativeClientLogCollector.shared.entriesSnapshot(limit: 50).map { $0.payload() },
            "metadata": defaultMetadata(pageURL: "apple://native"),
        ]
    }

    static func defaultTelemetryPayload(
        isAuthenticated: Bool,
        optedOut: Bool,
        installPseudonym: String = NativeInstallPseudonym.value
    ) -> [String: Any]? {
        guard isAuthenticated, !optedOut else { return nil }
        let logs = NativeClientLogCollector.shared.entriesSnapshot(limit: 50, minimumLevel: .warning).map { $0.payload() }
        guard !logs.isEmpty else { return nil }
        return [
            "logs": logs,
            "metadata": [
                "source": "apple_native",
                "userAgent": NativeDeviceInfo.userAgent,
                "installPseudonym": NativeClientLogCollector.sanitize(installPseudonym),
            ],
        ]
    }

    private static func defaultMetadata(pageURL: String) -> [String: String] {
        [
            "userAgent": NativeDeviceInfo.userAgent,
            "pageUrl": NativeClientLogCollector.sanitize(pageURL),
            "tabId": NativeInstallPseudonym.value,
        ]
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

private enum NativeInstallPseudonym {
    static let value = "apple-" + String(UUID().uuidString.prefix(8))
}

private enum NativeDiagnosticsDateFormatter {
    static func string(from date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}
