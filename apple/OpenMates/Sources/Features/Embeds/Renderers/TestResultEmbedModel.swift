// Payload decoding and view-model mapping for recorded test-run embeds
// (`test_result`, rendered as `code-test-result`). Reads only the embed's
// decrypted content; evidence bytes are never fetched here.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/code/testResultContent.ts
//          frontend/packages/ui/src/components/embeds/code/TestResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/code/TestResultEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/code/TestResultStatusBadge.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.tests.recorded-evidence, code-run.tests.project-snapshot
import Foundation

enum TestResultKind: String {
    case unit, browser, cli
}

enum TestResultRunStatus: String {
    case passed, failed, error, cancelled
    case timedOut = "timed_out"

    /// Translation key of the status label, shared with the web app.
    var labelKey: String { "embeds.code.test_result.status_\(rawValue)" }
}

enum TestResultRowStatus: String {
    case passed, failed, skipped, error

    var labelKey: String { "embeds.code.test_result.status_\(rawValue)" }

    /// Anything that is not passed, skipped or error counts as failed (web `rowStatus`).
    static func from(_ status: String) -> TestResultRowStatus {
        TestResultRowStatus(rawValue: status) ?? .failed
    }
}

struct TestResultStep: Equatable {
    let name: String
    let startMs: Double
    let endMs: Double
    let status: String
    let error: String?
    let isPreview: Bool
    let command: String?
    let output: String?

    var rowStatus: TestResultRowStatus { .from(status) }
}

struct TestResultTest: Equatable {
    let name: String
    let status: String
    let durationMs: Double?
    let error: String?

    var rowStatus: TestResultRowStatus { .from(status) }
}

struct TestResultEvidence: Equatable {
    let kind: String
    let path: String
    let mimeType: String?
    let assetId: String?
    let atStep: Int?
}

struct TestResultView: Equatable {
    let kind: TestResultKind
    let target: String
    let runStatus: TestResultRunStatus
    let exitCode: Int?
    let durationMs: Double?
    let passed: Int
    let failed: Int
    let skipped: Int
    let error: String?
    let previewStepIndex: Int?
    let tests: [TestResultTest]
    let steps: [TestResultStep]
    let evidence: [TestResultEvidence]
    let isCurrent: Bool
    let staleReason: String?

    init(data: [String: AnyCodable]?) {
        self.init(content: data?.mapValues { $0.value } ?? [:])
    }

    init(content dc: [String: Any]) {
        kind = (dc["kind"] as? String).flatMap(TestResultKind.init(rawValue:)) ?? .unit
        runStatus = (dc["run_status"] as? String).flatMap(TestResultRunStatus.init(rawValue:)) ?? .error
        target = Self.string(dc["target"]) ?? ""
        exitCode = Self.number(dc["exit_code"]).map { Int($0) }
        durationMs = Self.number(dc["duration_ms"])
        passed = Self.number(dc["passed"]).map { Int($0) } ?? 0
        failed = Self.number(dc["failed"]).map { Int($0) } ?? 0
        skipped = Self.number(dc["skipped"]).map { Int($0) } ?? 0
        error = Self.string(dc["error"])
        previewStepIndex = Self.number(dc["preview_step_index"]).map { Int($0) }
        tests = Self.records(dc["tests"]).map { item in
            TestResultTest(
                name: Self.string(item["name"]) ?? "",
                status: Self.string(item["status"]) ?? "passed",
                durationMs: Self.number(item["duration_ms"]),
                error: Self.string(item["error"])
            )
        }
        steps = Self.records(dc["steps"]).map { item in
            TestResultStep(
                name: Self.string(item["name"]) ?? "",
                startMs: Self.number(item["start_ms"]) ?? 0,
                endMs: Self.number(item["end_ms"]) ?? 0,
                status: Self.string(item["status"]) ?? "passed",
                error: Self.string(item["error"]),
                isPreview: item["is_preview"] as? Bool == true,
                command: Self.string(item["command"]),
                output: item["output"] as? String
            )
        }
        evidence = Self.records(dc["evidence"]).map { item in
            TestResultEvidence(
                kind: Self.string(item["kind"]) ?? "",
                path: Self.string(item["path"]) ?? "",
                mimeType: Self.string(item["mime_type"]),
                assetId: Self.string(item["asset_id"]),
                atStep: Self.number(item["at_step"]).map { Int($0) }
            )
        }
        isCurrent = dc["is_current"] as? Bool != false
        staleReason = Self.string(dc["stale_reason"])
    }

    /// Run title: the target, or the generic title when no target is recorded.
    @MainActor var title: String {
        target.isEmpty ? AppStrings.localized("embeds.code.test_result.title") : target
    }

    /// True only for a green run on the current files; a stale result never counts as passing.
    var isGreenForCurrentFiles: Bool { runStatus == .passed && isCurrent }

    /// Index of the step playing at `currentMs` (last step that has started), -1 before the first.
    func activeStepIndex(at currentMs: Double) -> Int {
        var active = -1
        for (index, step) in steps.enumerated() where step.startMs <= currentMs { active = index }
        return active
    }

    /// Evidence of a kind; the preview frame prefers the recorded preview step.
    func evidence(kind wanted: String) -> TestResultEvidence? {
        let matches = evidence.filter { $0.kind == wanted }
        if wanted == "preview_frame", let previewStepIndex {
            return matches.first { $0.atStep == previewStepIndex } ?? matches.first
        }
        return matches.first
    }

    /// Duration as shown beside the status ("850 ms", "2.5 s", "1 min 5 s").
    static func formatDuration(_ ms: Double?) -> String {
        guard let ms else { return "" }
        if ms < 1000 { return "\(Int(ms.rounded())) ms" }
        let seconds = ms / 1000
        if seconds < 60 { return String(format: "%.1f s", seconds) }
        return "\(Int(seconds / 60)) min \(Int((seconds.truncatingRemainder(dividingBy: 60)).rounded())) s"
    }

    private static func string(_ value: Any?) -> String? {
        guard let value = value as? String, !value.isEmpty else { return nil }
        return value
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? Double { return value.isFinite ? value : nil }
        if let value = value as? Int { return Double(value) }
        if let value = value as? Int64 { return Double(value) }
        if let value = value as? NSNumber { return value.doubleValue }
        return nil
    }

    private static func records(_ value: Any?) -> [[String: Any]] {
        guard let items = value as? [Any] else { return [] }
        return items.compactMap { $0 as? [String: Any] }
    }
}
