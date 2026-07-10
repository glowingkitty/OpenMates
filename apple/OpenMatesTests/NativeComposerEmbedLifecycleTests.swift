// Contract tests for native composer embed lifecycle and deferred sends.
// Stable node identity is separate from retry generation and durable embed IDs.
// Stale, duplicate, terminal, and remove-then-complete callbacks have no effects.
// Queued snapshots dispatch FIFO and at most once after all blockers finish.
// Error remains blocking while processing is intentionally non-blocking.

import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerEmbedLifecycleTests: XCTestCase {
    func testEveryAllowedTransitionAndBlockingClassification() throws {
        let allowed: [(AppleComposerEmbedLifecycleState, AppleComposerEmbedLifecycleState)] = [
            (.draft, .uploading), (.draft, .processing), (.draft, .finished),
            (.draft, .cancelled), (.draft, .error),
            (.uploading, .processing), (.uploading, .transcribing), (.uploading, .finished),
            (.uploading, .cancelled), (.uploading, .error),
            (.processing, .transcribing), (.processing, .finished),
            (.processing, .cancelled), (.processing, .error),
            (.transcribing, .finished), (.transcribing, .cancelled), (.transcribing, .error),
        ]

        for (index, transition) in allowed.enumerated() {
            let lifecycle = ComposerEmbedLifecycle()
            let nodeId = "allowed-node-\(index)"
            lifecycle.register(nodeId: nodeId, state: transition.0)
            let result = lifecycle.transition(
                nodeId: nodeId,
                generation: 1,
                to: transition.1
            )
            guard case .applied(let record) = result else {
                return XCTFail("Expected allowed transition \(transition.0) -> \(transition.1)")
            }
            XCTAssertEqual(record.state, transition.1)
        }

        XCTAssertTrue(ComposerEmbedLifecycle.isBlocking(.draft))
        XCTAssertTrue(ComposerEmbedLifecycle.isBlocking(.uploading))
        XCTAssertTrue(ComposerEmbedLifecycle.isBlocking(.transcribing))
        XCTAssertTrue(ComposerEmbedLifecycle.isBlocking(.error))
        XCTAssertFalse(ComposerEmbedLifecycle.isBlocking(.processing))
        XCTAssertFalse(ComposerEmbedLifecycle.isBlocking(.finished))
        XCTAssertFalse(ComposerEmbedLifecycle.isBlocking(.cancelled))
    }

    func testForbiddenDuplicateStaleAndRemoveThenCompleteCallbacksAreIgnored() throws {
        let lifecycle = ComposerEmbedLifecycle()
        lifecycle.register(nodeId: "node-1", state: .draft)

        XCTAssertEqual(
            lifecycle.transition(nodeId: "node-1", generation: 1, to: .uploading),
            .applied(.init(nodeId: "node-1", generation: 1, state: .uploading, durableEmbedId: nil))
        )
        XCTAssertEqual(
            lifecycle.transition(nodeId: "node-1", generation: 1, to: .uploading),
            .ignored(.duplicate)
        )
        XCTAssertEqual(
            lifecycle.transition(nodeId: "node-1", generation: 1, to: .draft),
            .ignored(.forbiddenTransition)
        )
        XCTAssertEqual(
            lifecycle.transition(nodeId: "node-1", generation: 2, to: .finished),
            .ignored(.staleGeneration)
        )
        XCTAssertEqual(
            lifecycle.remove(nodeId: "node-1", generation: 1),
            .applied(.init(nodeId: "node-1", generation: 1, state: .cancelled, durableEmbedId: nil))
        )
        XCTAssertEqual(
            lifecycle.transition(nodeId: "node-1", generation: 1, to: .finished),
            .ignored(.terminalGeneration)
        )
    }

    func testRetryPreservesNodeIdentityAdvancesGenerationAndRejectsOldCompletion() throws {
        let lifecycle = ComposerEmbedLifecycle()
        lifecycle.register(nodeId: "node-retry", state: .draft)
        _ = lifecycle.transition(nodeId: "node-retry", generation: 1, to: .error)

        let retry = lifecycle.retry(nodeId: "node-retry", generation: 1, to: .uploading)
        XCTAssertEqual(
            retry,
            .applied(.init(nodeId: "node-retry", generation: 2, state: .uploading, durableEmbedId: nil))
        )
        XCTAssertEqual(
            lifecycle.transition(nodeId: "node-retry", generation: 1, to: .finished),
            .ignored(.staleGeneration)
        )
        XCTAssertEqual(lifecycle.record(nodeId: "node-retry")?.nodeId, "node-retry")
    }

    func testQueuedSnapshotsDispatchFIFOAtMostOnceAndErrorsRemainBlocking() async throws {
        let coordinator = ComposerPendingSendCoordinator()
        let recorder = ComposerDispatchRecorder()
        let first = snapshot(requestId: "request-1", nodeId: "node-1", generation: 1)
        let second = snapshot(requestId: "request-2", nodeId: nil, generation: nil)

        XCTAssertTrue(await coordinator.enqueue(first))
        XCTAssertTrue(await coordinator.enqueue(second))
        XCTAssertFalse(await coordinator.enqueue(first))

        await coordinator.updateNode(nodeId: "node-1", generation: 1, state: .error)
        await coordinator.resumeReady { snapshot in
            await recorder.append(snapshot.requestId)
        }
        XCTAssertEqual(await recorder.values(), [])

        await coordinator.updateNode(nodeId: "node-1", generation: 1, state: .finished)
        await coordinator.resumeReady { snapshot in
            await recorder.append(snapshot.requestId)
        }
        await coordinator.resumeReady { snapshot in
            await recorder.append(snapshot.requestId)
        }

        XCTAssertEqual(await recorder.values(), ["request-1", "request-2"])
        XCTAssertEqual(await coordinator.status(requestId: "request-1"), .completed)
        XCTAssertEqual(await coordinator.status(requestId: "request-2"), .completed)
    }

    func testRetryReplacesExpectedGenerationAndTerminationInvalidatesPlaintextSnapshots() async {
        let coordinator = ComposerPendingSendCoordinator()
        let recorder = ComposerDispatchRecorder()
        let queued = snapshot(requestId: "request-retry", nodeId: "node-retry", generation: 1)
        XCTAssertTrue(await coordinator.enqueue(queued))

        await coordinator.replaceBlockerGeneration(
            requestId: queued.requestId,
            nodeId: "node-retry",
            generation: 2
        )
        await coordinator.updateNode(nodeId: "node-retry", generation: 1, state: .finished)
        await coordinator.resumeReady { snapshot in
            await recorder.append(snapshot.requestId)
        }
        XCTAssertEqual(await recorder.values(), [])

        await coordinator.invalidateAllForTermination()
        await coordinator.updateNode(nodeId: "node-retry", generation: 2, state: .finished)
        await coordinator.resumeReady { snapshot in
            await recorder.append(snapshot.requestId)
        }
        XCTAssertEqual(await recorder.values(), [])
        XCTAssertEqual(await coordinator.status(requestId: queued.requestId), .invalidated)
    }

    private func snapshot(
        requestId: String,
        nodeId: String?,
        generation: Int?
    ) -> ComposerSendSnapshot {
        let blockers: [ComposerEmbedBlocker]
        if let nodeId, let generation {
            blockers = [.init(nodeId: nodeId, generation: generation)]
        } else {
            blockers = []
        }
        return ComposerSendSnapshot(
            requestId: requestId,
            destinationId: "synthetic-chat",
            documentRevision: 13,
            document: .init(version: 1, nodes: [.text(id: "text-1", source: requestId)]),
            blockers: blockers
        )
    }
}

private actor ComposerDispatchRecorder {
    private var requestIds: [String] = []

    func append(_ requestId: String) {
        requestIds.append(requestId)
    }

    func values() -> [String] {
        requestIds
    }
}
