// Failure recovery contracts for the native Apple composer boundary.
// Synthetic content proves errors never partially mutate canonical source.
// Lifecycle failures remain typed no-ops under stable node identities.
// Tests contain no user data, credentials, paths, or encryption material.
// Send eligibility remains blocked while recoverable embed errors exist.

import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerFailureRecoveryTests: XCTestCase {
    func testMissingEmbedMutationPreservesOriginalMarkdown() throws {
        let source = "Synthetic source before a missing node operation."
        let session = NativeComposerSession(canonicalMarkdown: source)

        XCTAssertThrowsError(
            try session.resolveEmbed(
                nodeID: "composer:embed:missing",
                durableEmbedID: "synthetic-missing",
                referenceType: "image",
                status: AppleComposerEmbedLifecycleState.finished.rawValue
            )
        )
        XCTAssertEqual(session.canonicalMarkdown, source)
        XCTAssertEqual(session.controller.document.nodes.count, 1)
    }

    func testForbiddenAndStaleLifecycleCallbacksAreTypedNoOps() {
        let lifecycle = ComposerEmbedLifecycle()
        let original = lifecycle.register(nodeId: "composer:embed:fixture")

        XCTAssertEqual(
            lifecycle.transition(nodeId: original.nodeId, generation: 99, to: .finished),
            .ignored(.staleGeneration)
        )
        XCTAssertEqual(
            lifecycle.retry(nodeId: original.nodeId, generation: original.generation, to: .uploading),
            .ignored(.forbiddenTransition)
        )
        XCTAssertEqual(lifecycle.record(nodeId: original.nodeId), original)
    }

    func testErrorAtomBlocksSendUntilExplicitRemoval() throws {
        let session = NativeComposerSession(canonicalMarkdown: "Sendable text")
        try session.insertPendingEmbed(
            nodeID: "composer:embed:error",
            embedType: "image",
            title: "Synthetic image"
        )
        try session.updateEmbed(
            nodeID: "composer:embed:error",
            status: AppleComposerEmbedLifecycleState.error.rawValue
        )

        XCTAssertTrue(session.hasBlockingEmbeds)
        try session.removeEmbed(nodeID: "composer:embed:error")
        XCTAssertFalse(session.hasBlockingEmbeds)
        XCTAssertEqual(session.canonicalMarkdown, "Sendable text")
    }
}
