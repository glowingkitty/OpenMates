// The one place un-migrated Swift features get the core's socket grant and
// master key (plan apple-client-core-migration A4 lane 1). Both are frozen
// remainders of the binding: `legacySocketGrant()` (session id and `ws_token`
// for `WebSocketManager`, removed with step A4a) and `legacyMasterKey()` (for
// the remaining `CryptoManager` callers, removed with step A3b). The core owns
// both; this type only holds them in memory between session events and drops
// them when the core signs out, expires or asks for verification. No other
// Swift code keeps a copy of the `ws_token` or the master key. Nothing new may
// use them.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.credentials.snapshot-boundary, client-core.apple.strangler-order

import CryptoKit
import Foundation

@MainActor
enum CoreLegacyAccess {
    /// Session id of the core's session as of the last socket grant; `nil`
    /// while signed out or before the first grant.
    private(set) static var sessionID: String?
    private static var masterKeyCache: (accountID: String, key: SymmetricKey)?
    #if DEBUG
    /// Synthetic keys of UI-test fixtures that run without any core session.
    private static var fixtureMasterKeys: [String: SymmetricKey] = [:]
    #endif

    /// The core's session id and current `ws_token`. Ask again after every
    /// `Session(Admitted)`: the token rotates.
    ///
    /// Throws the core's error: `Authentication` while signed out (also when
    /// no core exists), `Expired` for a lapsed pairing.
    static func socketGrant() async throws -> LegacySocketGrantRecord {
        guard let session = CoreSession.shared else { throw CoreError.Authentication }
        let grant = try await session.perform { core, _ in try await core.legacySocketGrant() }
        sessionID = grant.sessionId
        return grant
    }

    /// The master key of `accountID` when it is the core's signed-in account,
    /// else `nil` (signed out, another account, no core in this process).
    /// Throws the core's other errors (`Expired`, `Internal`) unchanged.
    static func masterKey(for accountID: String) async throws -> SymmetricKey? {
        #if DEBUG
        if let fixture = fixtureMasterKeys[accountID] { return fixture }
        #endif
        if let cached = masterKeyCache, cached.accountID == accountID { return cached.key }
        guard let session = CoreSession.shared else { return nil }
        do {
            let info = try await session.perform { core, _ in try await core.sessionInfo() }
            guard let info, info.userId == accountID else { return nil }
            let bytes = try await session.perform { core, _ in try await core.legacyMasterKey() }
            let key = SymmetricKey(data: bytes)
            masterKeyCache = (accountID, key)
            return key
        } catch CoreError.Authentication {
            // Signed out in the core: there is no key, which callers already
            // handle as "no unlocked account".
            return nil
        }
    }

    /// Called by `CoreSession` for every `Session` event before it is published.
    static func sessionDidChange(_ event: SessionEventRecord) {
        switch event {
        case .restored, .admitted, .accessDenied(.chatUnavailable):
            return
        case .signedOut, .expired, .accessDenied(.expired), .accessDenied(.scopeRevoked), .verificationRequired:
            sessionID = nil
            masterKeyCache = nil
        }
    }

    #if DEBUG
    /// UI-test fixtures with a synthetic offline identity and no core session.
    static func installFixtureMasterKey(_ key: SymmetricKey, for accountID: String) {
        fixtureMasterKeys[accountID] = key
    }

    static func removeFixtureMasterKey(for accountID: String) {
        fixtureMasterKeys[accountID] = nil
    }
    #endif
}
