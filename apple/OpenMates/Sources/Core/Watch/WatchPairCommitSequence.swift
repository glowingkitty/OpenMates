// Fences the Watch pair transaction across receiver, push, key and ack awaits.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.pairing.explicit-entry-back
import Foundation

@MainActor
enum WatchPairCommitSequence {
    static func run<Result>(isCurrent: @MainActor () -> Bool,
                    complete: @MainActor () async throws -> Result,
                    unregisterPush: @MainActor () async -> Void,
                    persistKey: @MainActor (Result) async throws -> Void,
                    persistMetadata: @MainActor (Result) throws -> Void,
                    acknowledge: @MainActor () async throws -> Void,
                    publish: @MainActor (Result) -> Void,
                    rollback: @MainActor (Result?) async -> Void) async throws {
        @MainActor func check() throws {
            try Task.checkCancellation()
            guard isCurrent() else { throw CancellationError() }
        }
        try check()
        var result: Result?
        do {
            result = try await complete()
            try check()
            guard let result else { throw CancellationError() }
            await unregisterPush()
            try check()
            try await persistKey(result)
            try check()
            try persistMetadata(result)
            try check()
            try await acknowledge()
            try check()
            publish(result)
        } catch {
            await rollback(result)
            throw error
        }
    }
}
