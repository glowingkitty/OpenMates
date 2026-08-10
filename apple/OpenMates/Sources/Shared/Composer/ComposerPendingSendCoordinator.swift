// FIFO coordinator for immutable native composer send snapshots.
// Queue entries retain canonical plaintext only while the active session needs it.
// Dispatching is committed before awaiting the send boundary to prevent duplicates.
// Retry replaces blocker generations explicitly and stale callbacks cannot unblock.
// Termination invalidates entries and releases their document snapshots immediately.

import Foundation

struct ComposerEmbedBlocker: Hashable, Sendable {
    let nodeId: String
    let generation: Int
}

struct ComposerSendSnapshot: Equatable, Sendable {
    let requestId: String
    let messageId: String
    let destinationId: String
    let documentRevision: Int
    let document: ComposerDocumentV1
    var blockers: [ComposerEmbedBlocker]
}

enum ComposerPendingSendStatus: Equatable, Sendable {
    case queued
    case dispatching
    case completed
    case failed
    case invalidated
}

actor ComposerPendingSendCoordinator {
    private struct Entry: Sendable {
        var snapshot: ComposerSendSnapshot
    }

    private var entries: [String: Entry] = [:]
    private var queues: [String: [String]] = [:]
    private var statuses: [String: ComposerPendingSendStatus] = [:]
    private var nodeStates: [ComposerEmbedBlocker: AppleComposerEmbedLifecycleState] = [:]

    func enqueue(_ snapshot: ComposerSendSnapshot) -> Bool {
        guard statuses[snapshot.requestId] == nil else { return false }
        entries[snapshot.requestId] = Entry(snapshot: snapshot)
        queues[snapshot.destinationId, default: []].append(snapshot.requestId)
        statuses[snapshot.requestId] = .queued
        return true
    }

    func status(requestId: String) -> ComposerPendingSendStatus? {
        statuses[requestId]
    }

    func updateNode(
        nodeId: String,
        generation: Int,
        state: AppleComposerEmbedLifecycleState
    ) {
        nodeStates[ComposerEmbedBlocker(nodeId: nodeId, generation: generation)] = state
    }

    func replaceBlockerGeneration(
        requestId: String,
        nodeId: String,
        generation: Int
    ) {
        guard var entry = entries[requestId], statuses[requestId] == .queued else { return }
        entry.snapshot.blockers = entry.snapshot.blockers.map { blocker in
            blocker.nodeId == nodeId
                ? ComposerEmbedBlocker(nodeId: nodeId, generation: generation)
                : blocker
        }
        entries[requestId] = entry
    }

    func invalidate(requestId: String) {
        guard let entry = entries.removeValue(forKey: requestId) else { return }
        queues[entry.snapshot.destinationId]?.removeAll { $0 == requestId }
        statuses[requestId] = .invalidated
    }

    func invalidateAllForTermination() {
        for requestId in entries.keys {
            statuses[requestId] = .invalidated
        }
        entries.removeAll()
        queues.removeAll()
        nodeStates.removeAll()
    }

    func retryFailed(requestId: String) -> Bool {
        guard let entry = entries[requestId], statuses[requestId] == .failed else {
            return false
        }
        queues[entry.snapshot.destinationId, default: []].append(requestId)
        statuses[requestId] = .queued
        return true
    }

    func resumeReady(
        dispatch: @MainActor @Sendable (ComposerSendSnapshot) async throws -> Void
    ) async {
        for destinationId in Array(queues.keys) {
            while let requestId = queues[destinationId]?.first,
                  let entry = entries[requestId],
                  isReady(entry.snapshot) {
                statuses[requestId] = .dispatching
                queues[destinationId]?.removeFirst()
                do {
                    try await dispatch(entry.snapshot)
                    entries.removeValue(forKey: requestId)
                    statuses[requestId] = .completed
                } catch {
                    statuses[requestId] = .failed
                }
            }
            if queues[destinationId]?.isEmpty == true {
                queues.removeValue(forKey: destinationId)
            }
        }
    }

    private func isReady(_ snapshot: ComposerSendSnapshot) -> Bool {
        snapshot.blockers.allSatisfy { blocker in
            guard let state = nodeStates[blocker] else { return false }
            return state == .finished || state == .processing
        }
    }
}
