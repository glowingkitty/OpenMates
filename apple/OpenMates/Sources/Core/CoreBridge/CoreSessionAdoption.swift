// Hand-over of a session that a Swift login ceremony finished to the core
// (plan apple-client-core-migration A4 lane 1). The core does not perform
// passkey, recovery-key and backup-code login yet; their ceremonies stay in
// Swift, run while signed out through `APIClient`'s pre-session transport,
// and end here: the cookies the server set, the `ws_token` and the unwrapped
// master key go to `ViewModelCore.adoptSession`, which validates, stores and
// starts them. Afterwards the core alone owns the session; this file wipes
// the ceremony's in-memory cookies and session id. Nothing here persists.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.credentials.snapshot-boundary, client-core.apple.strangler-order

import CryptoKit
import Foundation

/// In-memory state of a sign-in ceremony that runs before the core holds a
/// session: one cookie jar (never the shared app-group jar) and the session
/// id the ceremony's requests carry, which the adopted session keeps.
enum CoreCeremonySession {
    // HTTPCookieStorage is internally synchronized; it is not marked Sendable.
    nonisolated(unsafe) static let cookieStorage: HTTPCookieStorage = {
        guard let storage = URLSessionConfiguration.ephemeral.httpCookieStorage else {
            preconditionFailure("an ephemeral URLSessionConfiguration always has a cookie storage")
        }
        return storage
    }()

    @MainActor private static var currentSessionID: String?

    /// Session id of the running ceremony, created on first use.
    @MainActor static var sessionID: String {
        if let currentSessionID { return currentSessionID }
        let created = UUID().uuidString
        currentSessionID = created
        return created
    }

    /// Forget the ceremony: its cookies and session id.
    @MainActor static func reset() {
        currentSessionID = nil
        for cookie in cookieStorage.cookies ?? [] { cookieStorage.deleteCookie(cookie) }
    }
}

/// What a finished Swift ceremony hands over. Secrets live only in memory.
struct CoreCeremonyResult {
    let response: LoginResponse
    let masterKey: SymmetricKey
    let hashedEmail: String
    let userEmailSalt: String
    let emailEncryptionKey: String?
    let sessionID: String
}

enum CoreSessionAdoptionError: Error, Equatable {
    /// No core exists in this process (unit-test host or failed launch).
    case coreUnavailable
    /// The ceremony's response set no session cookie for the API host.
    case missingSessionCookie
}

extension CoreSession {
    /// Adopt `result` into the core and wipe the ceremony state, also when
    /// the core refused it (the core's error is rethrown unchanged).
    func adoptCeremony(_ result: CoreCeremonyResult, apiBaseURL: URL) async throws {
        defer { CoreCeremonySession.reset() }
        let cookies = (CoreCeremonySession.cookieStorage.cookies(for: apiBaseURL) ?? [])
            .map { SessionCookieRecord(name: $0.name, value: $0.value) }
        guard cookies.contains(where: { $0.name == "auth_refresh_token" }) else {
            throw CoreSessionAdoptionError.missingSessionCookie
        }
        let record = AdoptedSessionRecord(
            sessionId: result.sessionID, cookies: cookies, wsToken: result.response.wsToken,
            masterKey: result.masterKey.withUnsafeBytes { Data($0) },
            hashedEmail: result.hashedEmail, userEmailSalt: result.userEmailSalt,
            emailEncryptionKey: result.emailEncryptionKey, pairedSessionExpiresAt: nil)
        try await adoptSession(record)
    }
}
