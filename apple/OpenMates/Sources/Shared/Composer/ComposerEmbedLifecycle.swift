// Deterministic lifecycle reducer for native composer embed atoms.
// Visible node identity remains stable while explicit retry advances generation.
// Every asynchronous callback is validated by node ID and generation.
// Invalid, stale, duplicate, and terminal callbacks produce no side effects.
// Blocking classification mirrors the authoritative web deferred-send contract.

import Foundation

struct ComposerEmbedLifecycleRecord: Equatable, Sendable {
    let nodeId: String
    let generation: Int
    let state: AppleComposerEmbedLifecycleState
    let durableEmbedId: String?
}

enum ComposerEmbedIgnoredReason: Equatable, Sendable {
    case missingNode
    case staleGeneration
    case duplicate
    case terminalGeneration
    case forbiddenTransition
}

enum ComposerEmbedTransitionResult: Equatable, Sendable {
    case applied(ComposerEmbedLifecycleRecord)
    case ignored(ComposerEmbedIgnoredReason)
}

@MainActor
final class ComposerEmbedLifecycle {
    private var records: [String: ComposerEmbedLifecycleRecord] = [:]

    @discardableResult
    func register(
        nodeId: String,
        state: AppleComposerEmbedLifecycleState = .draft,
        durableEmbedId: String? = nil
    ) -> ComposerEmbedLifecycleRecord {
        if let existing = records[nodeId] {
            return existing
        }
        let record = ComposerEmbedLifecycleRecord(
            nodeId: nodeId,
            generation: 1,
            state: state,
            durableEmbedId: durableEmbedId
        )
        records[nodeId] = record
        return record
    }

    func record(nodeId: String) -> ComposerEmbedLifecycleRecord? {
        records[nodeId]
    }

    func transition(
        nodeId: String,
        generation: Int,
        to nextState: AppleComposerEmbedLifecycleState,
        durableEmbedId: String? = nil
    ) -> ComposerEmbedTransitionResult {
        guard let current = records[nodeId] else { return .ignored(.missingNode) }
        guard generation == current.generation else { return .ignored(.staleGeneration) }
        guard current.state != nextState else { return .ignored(.duplicate) }
        guard current.state != .finished, current.state != .cancelled else {
            return .ignored(.terminalGeneration)
        }
        guard Self.canTransition(from: current.state, to: nextState) else {
            return .ignored(.forbiddenTransition)
        }
        let updated = ComposerEmbedLifecycleRecord(
            nodeId: nodeId,
            generation: generation,
            state: nextState,
            durableEmbedId: durableEmbedId ?? current.durableEmbedId
        )
        records[nodeId] = updated
        return .applied(updated)
    }

    func retry(
        nodeId: String,
        generation: Int,
        to nextState: AppleComposerEmbedLifecycleState
    ) -> ComposerEmbedTransitionResult {
        guard let current = records[nodeId] else { return .ignored(.missingNode) }
        guard generation == current.generation else { return .ignored(.staleGeneration) }
        guard current.state == .error,
              [.uploading, .processing, .transcribing].contains(nextState) else {
            return .ignored(.forbiddenTransition)
        }
        let updated = ComposerEmbedLifecycleRecord(
            nodeId: nodeId,
            generation: generation + 1,
            state: nextState,
            durableEmbedId: current.durableEmbedId
        )
        records[nodeId] = updated
        return .applied(updated)
    }

    func remove(nodeId: String, generation: Int) -> ComposerEmbedTransitionResult {
        guard let current = records[nodeId] else { return .ignored(.missingNode) }
        guard generation == current.generation else { return .ignored(.staleGeneration) }
        guard current.state != .finished, current.state != .cancelled else {
            return .ignored(.terminalGeneration)
        }
        let updated = ComposerEmbedLifecycleRecord(
            nodeId: nodeId,
            generation: generation,
            state: .cancelled,
            durableEmbedId: current.durableEmbedId
        )
        records[nodeId] = updated
        return .applied(updated)
    }

    nonisolated static func isBlocking(_ state: AppleComposerEmbedLifecycleState) -> Bool {
        switch state {
        case .draft, .uploading, .transcribing, .error:
            true
        case .processing, .finished, .cancelled:
            false
        }
    }

    private static func canTransition(
        from current: AppleComposerEmbedLifecycleState,
        to next: AppleComposerEmbedLifecycleState
    ) -> Bool {
        switch current {
        case .draft:
            [.uploading, .processing, .finished, .cancelled, .error].contains(next)
        case .uploading:
            [.processing, .transcribing, .finished, .cancelled, .error].contains(next)
        case .processing:
            [.transcribing, .finished, .cancelled, .error].contains(next)
        case .transcribing:
            [.finished, .cancelled, .error].contains(next)
        case .error, .finished, .cancelled:
            false
        }
    }
}
