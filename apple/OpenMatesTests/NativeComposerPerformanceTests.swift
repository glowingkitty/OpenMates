// Deterministic performance guardrails for the native Apple composer core.
// Thresholds are intentionally broad enough for shared CI simulator hardware.
// Tests catch accidental quadratic parsing, controller replacement, and preview
// recreation while avoiding wall-clock-sensitive UI animation measurements.
// Synthetic documents contain no private content or provider data.

import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerPerformanceTests: XCTestCase {
    private let longDocumentThreshold: TimeInterval = 1.0
    private let rapidTypingThreshold: TimeInterval = 1.0
    private let lifecycleUpdateThreshold: TimeInterval = 1.0

    func testLongCanonicalDocumentParsesWithinCandidateThreshold() throws {
        let source = Array(repeating: "Synthetic paragraph with emoji 👍 and RTL مرحبا.\n", count: 2_000)
            .joined()
        let started = ProcessInfo.processInfo.systemUptime

        let document = try ComposerMarkdownAdapter.parse(source)
        let serialized = try ComposerMarkdownAdapter.serialize(document)

        XCTAssertLessThan(ProcessInfo.processInfo.systemUptime - started, longDocumentThreshold)
        XCTAssertEqual(serialized, source)
    }

    func testRapidTypingKeepsOneControllerWithinCandidateThreshold() throws {
        let session = NativeComposerSession(canonicalMarkdown: "")
        let controller = session.controller
        let started = ProcessInfo.processInfo.systemUptime

        for _ in 0..<250 {
            try session.replaceSelection(with: "a")
        }

        XCTAssertLessThan(ProcessInfo.processInfo.systemUptime - started, rapidTypingThreshold)
        XCTAssertTrue(session.controller === controller)
        XCTAssertEqual(session.canonicalMarkdown.count, 250)
    }

    func testLifecycleUpdatesReuseAttachmentWithinCandidateThreshold() throws {
        let session = NativeComposerSession(canonicalMarkdown: "")
        let nodeID = "composer:embed:performance"
        try session.insertPendingEmbed(nodeID: nodeID, embedType: "image", title: "Synthetic image")
        let originalAttachment = try XCTUnwrap(
            session.controller.attributedString.attribute(
                .attachment,
                at: 0,
                effectiveRange: nil
            ) as? ComposerTextAttachment
        )
        let started = ProcessInfo.processInfo.systemUptime

        for index in 0..<250 {
            let status = index.isMultiple(of: 2)
                ? AppleComposerEmbedLifecycleState.uploading.rawValue
                : AppleComposerEmbedLifecycleState.draft.rawValue
            try session.updateEmbed(nodeID: nodeID, status: status)
        }

        let retainedAttachment = try XCTUnwrap(
            session.controller.attributedString.attribute(
                .attachment,
                at: 0,
                effectiveRange: nil
            ) as? ComposerTextAttachment
        )
        XCTAssertLessThan(ProcessInfo.processInfo.systemUptime - started, lifecycleUpdateThreshold)
        XCTAssertTrue(retainedAttachment === originalAttachment)
    }
}
