// Keychain-backed credential store of the Rust view-model core
// (`ViewModelCore`, plan apple-client-core-migration A2 lane L8). The core
// hands over one opaque payload (the serialized core session, secret); this
// type only stores, returns and deletes it in the Keychain and acknowledges
// each stored revision. It never parses, logs or shows the payload. The core
// calls it on its own threads, never on the main thread. Not used by app
// screens yet (step A4).
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.credentials.snapshot-boundary

import Foundation
import Security

final class KeychainCredentialStore: CredentialStore, @unchecked Sendable {
    /// Keychain account of the core session payload.
    static let defaultAccount = "openmates.coreSession"

    private let account: String
    /// Serial queue for writes, so `credentialsChanged` never blocks the core
    /// and revisions are stored in the order the core produced them.
    private let writes = DispatchQueue(label: "org.openmates.core.credentials")
    private let lock = NSLock()
    private weak var acknowledger: ViewModelCore?

    init(account: String = KeychainCredentialStore.defaultAccount) {
        self.account = account
    }

    /// The core that receives acknowledgements; set once after creating it.
    func attach(core: ViewModelCore) {
        lock.lock()
        acknowledger = core
        lock.unlock()
    }

    func load() throws -> Data? {
        do {
            return try KeychainHelper.load(key: account)
        } catch let error as KeychainError {
            throw Self.coreError(error)
        }
    }

    func credentialsChanged(snapshot: CredentialSnapshotRecord) {
        writes.async { [self] in
            do {
                try KeychainHelper.save(key: account, data: snapshot.payload)
            } catch {
                // No acknowledgement: the core times out and fails the save
                // with `Locked` instead of claiming durability.
                NativeDiagnostics.warning("core_credentials_store_failed", category: "core_bridge")
                return
            }
            lock.lock()
            let core = acknowledger
            lock.unlock()
            do {
                try core?.acknowledgeCredentials(revision: snapshot.revision)
            } catch CoreError.Cancelled {
                // A newer revision superseded this one (or the save timed
                // out); the core asks for the newer payload separately.
            } catch {
                NativeDiagnostics.warning("core_credentials_ack_failed", category: "core_bridge")
            }
        }
    }

    func delete() throws {
        do {
            try KeychainHelper.delete(key: account)
        } catch let error as KeychainError {
            throw Self.coreError(error)
        }
    }

    /// A locked device (data protection) is `Locked`; every other Keychain
    /// status is a store failure.
    private static func coreError(_ error: KeychainError) -> CoreError {
        switch error {
        case .loadFailed(let status), .saveFailed(let status), .deleteFailed(let status):
            return status == errSecInteractionNotAllowed ? .Locked : .Io
        }
    }
}
