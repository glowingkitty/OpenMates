// Tests of the recorded test-run embed payload decoding and the application
// card facts mapping. Pure decoding of the embed's decrypted content; the
// recorded run itself is produced and proven by the code-run backend suites.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/code/testResultContent.ts
//          frontend/packages/ui/src/components/embeds/code/ApplicationEmbedPreview.svelte
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.tests.recorded-evidence, code-run.tests.project-snapshot
import XCTest
@testable import OpenMates

final class ApplicationTestRunEmbedTests: XCTestCase {
    private let browserRun: [String: Any] = [
        "kind": "browser",
        "target": "Checkout flow",
        "run_status": "failed",
        "duration_ms": 65_000,
        "passed": 2, "failed": 1,
        "preview_step_index": 1,
        "steps": [
            ["name": "Open page", "start_ms": 0, "end_ms": 900, "status": "passed"],
            ["name": "Pay", "start_ms": 1000, "end_ms": 2000, "status": "timed_out", "error": "no button"],
        ],
        "evidence": [
            ["kind": "video", "path": "run.webm", "asset_id": "emb-video"],
            ["kind": "preview_frame", "path": "a.png", "asset_id": "emb-a", "at_step": 0],
            ["kind": "preview_frame", "path": "b.png", "asset_id": "emb-b", "at_step": 1],
        ],
        "is_current": false,
        "stale_reason": "files changed",
    ]

    // contract-test: direct surface=gui.apple assertions=code-run.tests.recorded-evidence
    func testBrowserRunDecodesStepsEvidenceAndPreviewFrame() {
        let view = TestResultView(content: browserRun)
        XCTAssertEqual(view.kind, .browser)
        XCTAssertEqual(view.runStatus, .failed)
        XCTAssertEqual(view.steps.count, 2)
        XCTAssertEqual(view.steps[1].rowStatus, .failed, "unknown statuses count as failed")
        XCTAssertEqual(view.evidence(kind: "video")?.assetId, "emb-video")
        XCTAssertEqual(view.evidence(kind: "preview_frame")?.assetId, "emb-b")
        XCTAssertEqual(view.activeStepIndex(at: 500), 0)
        XCTAssertEqual(view.activeStepIndex(at: 1500), 1)
    }

    // contract-test: direct surface=gui.apple assertions=code-run.tests.project-snapshot
    func testStaleResultIsNeverGreenForCurrentFiles() {
        XCTAssertFalse(TestResultView(content: browserRun).isGreenForCurrentFiles)
        let stalePassed = TestResultView(content: ["run_status": "passed", "is_current": false])
        XCTAssertFalse(stalePassed.isGreenForCurrentFiles)
        XCTAssertEqual(stalePassed.staleReason, nil)
        XCTAssertTrue(TestResultView(content: ["run_status": "passed"]).isGreenForCurrentFiles)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.tests.recorded-evidence
    func testMissingFieldsFallBackToSafeDefaults() {
        let view = TestResultView(content: [:])
        XCTAssertEqual(view.kind, .unit)
        XCTAssertEqual(view.runStatus, .error)
        XCTAssertEqual(view.passed, 0)
        XCTAssertTrue(view.isCurrent)
        XCTAssertTrue(view.steps.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.tests.recorded-evidence
    func testDurationFormattingMatchesWeb() {
        XCTAssertEqual(TestResultView.formatDuration(nil), "")
        XCTAssertEqual(TestResultView.formatDuration(850), "850 ms")
        XCTAssertEqual(TestResultView.formatDuration(2500), "2.5 s")
        XCTAssertEqual(TestResultView.formatDuration(65_000), "1 min 5 s")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.tests.recorded-evidence
    func testRowStatusAndTimedOutRunStatus() {
        XCTAssertEqual(TestResultRowStatus.from("skipped"), .skipped)
        XCTAssertEqual(TestResultRowStatus.from("weird"), .failed)
        XCTAssertEqual(TestResultView(content: ["run_status": "timed_out"]).runStatus, .timedOut)
        XCTAssertEqual(TestResultRunStatus.timedOut.labelKey, "embeds.code.test_result.status_timed_out")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.tests.recorded-evidence
    func testEmbedTypeNormalizesTestResult() {
        XCTAssertEqual(EmbedType.normalized(rawValue: "test_result"), .codeTestResult)
        XCTAssertEqual(EmbedType.codeTestResult.appId, "code")
    }
}
