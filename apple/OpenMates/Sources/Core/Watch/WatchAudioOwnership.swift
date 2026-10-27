// One process-wide Watch capture lease; no iOS speech-runtime dependency.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions, apple-watch.chats.local-transcription
import Foundation

@MainActor
final class WatchAudioOwnership {
    static let shared = WatchAudioOwnership()
    enum Owner: Equatable, Sendable { case recording, liveCall }
    struct Lease: Equatable, Sendable { let id: UUID; let owner: Owner }
    private(set) var currentLease: Lease?

    func acquire(owner: Owner) throws -> Lease {
        guard currentLease == nil else { throw WatchComposerActionError.busy }
        let lease = Lease(id: UUID(), owner: owner)
        currentLease = lease
        return lease
    }
    func isCurrent(_ lease: Lease) -> Bool { currentLease == lease }
    @discardableResult func release(_ lease: Lease) -> Bool {
        guard isCurrent(lease) else { return false }
        currentLease = nil
        return true
    }
}
