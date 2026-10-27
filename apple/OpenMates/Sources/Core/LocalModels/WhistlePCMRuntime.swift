// Local PCM evaluation alternative; the pinned model stays resident until process exit.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context
import Foundation

actor WhistlePCMRuntime: LocalPCMTranscribing {
    static let maximumSamples = 16_000 * 30
    private let ownerID = UUID()
    private let modelURL: URL
    private let engine: any WhistleNativeEngine
    private let onUnload: @Sendable () async -> Void
    private var generation: UInt64 = 0
    private var running = false
    private var loaded = false
    private var invalidated = false
    private var ownsLease = false
    private var drainWaiters: [CheckedContinuation<Void, Never>] = []
    private var unloadTask: Task<Void, Never>?
    private var sessionEndTask: Task<Void, Never>?

    init(modelURL: URL, engine: any WhistleNativeEngine = WhistleNativeBridge.shared,
         onUnload: @escaping @Sendable () async -> Void = {}) {
        self.modelURL = modelURL; self.engine = engine; self.onUnload = onUnload
    }

    static func bundled() throws -> WhistlePCMRuntime {
        WhistlePCMRuntime(modelURL: try WhistleBundledAsset.modelURL())
    }

    func transcribe(_ samples: [Float]) async throws -> String {
        guard !invalidated, !running else { throw LocalSpeechRuntimeError.busy }
        guard !samples.isEmpty, samples.count <= Self.maximumSamples,
              samples.allSatisfy({ $0.isFinite && (-1...1).contains($0) }) else {
            throw LocalSpeechRuntimeError.invalidRequest
        }
        try Task.checkCancellation()
        let token = generation
        running = true
        defer {
            running = false
            let waiters = drainWaiters; drainWaiters.removeAll()
            for waiter in waiters { waiter.resume() }
        }
        do {
            if !loaded {
                try LocalSpeechInferenceOwnership.shared.acquire(ownerID)
                ownsLease = true
                try await engine.load(modelURL: modelURL)
                try requireCurrent(token)
                loaded = true
            }
            let text = try await engine.transcribe(samples)
            try requireCurrent(token)
            return text
        } catch {
            invalidated = true
            await endSessionOnce()
            if error is CancellationError { throw CancellationError() }
            if let category = error as? LocalSpeechRuntimeError { throw category }
            throw LocalSpeechRuntimeError.invalidOutput
        }
    }

    private func requireCurrent(_ token: UInt64) throws {
        try Task.checkCancellation()
        guard !invalidated, generation == token else { throw CancellationError() }
    }

    private func endSessionOnce() async {
        if let sessionEndTask { await sessionEndTask.value; return }
        // An acquire failure must not reset another owner's process-global session.
        guard ownsLease else { return }
        let engine = self.engine, owner = ownerID, callback = onUnload
        let task = Task {
            await engine.endSession()
            LocalSpeechInferenceOwnership.shared.release(owner)
            await callback()
        }
        sessionEndTask = task
        await task.value
        ownsLease = false; loaded = false
    }

    /// Satisfies the portable seam by stopping this session and draining its call.
    /// This does not reclaim the pinned engine's resident model or prove scratch erasure.
    func unload() async { await requestStop().value }

    /// Request invalidation atomically, then let callers await the same drain task.
    /// Separating request from drain lets owners disable new work before waiting.
    func requestStop() -> Task<Void, Never> {
        if let unloadTask { return unloadTask }
        invalidated = true; generation &+= 1
        let task = Task {
            if running { await withCheckedContinuation { drainWaiters.append($0) } }
            await endSessionOnce()
        }
        unloadTask = task
        return task
    }

    func capability() async -> WhistleRuntimeCapability { await engine.capability() }
}
