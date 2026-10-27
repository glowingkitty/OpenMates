// Watch pairing persistence and receiver lease. Rollback restores prior owned
// values rather than deleting retained account materials from a signed-out scope.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.pairing.explicit-entry-back, apple-watch.guest.account-isolation
import Foundation
import CryptoKit

// Receiver-only task context. Main-app pairing leaves it nil. Watch records
// ownership at each actual write, before an await can expose successor state.
enum WatchPairReceiverAuthority {
    struct Context: @unchecked Sendable {
        let isCurrent: @MainActor () -> Bool
        let cookiesDidPublish: @MainActor () -> Void
        let verifiedDidPersist: @MainActor () -> Void
    }
    @TaskLocal static var current: Context?
}

@MainActor
struct WatchPairAuthenticationStorage {
    let standard: UserDefaults
    let shared: UserDefaults
    let cookies: HTTPCookieStorage
    let loadKey: @MainActor (String) async throws -> SymmetricKey?
    let saveKey: @MainActor (SymmetricKey, String) async throws -> Void
    let deleteKey: @MainActor (String) async throws -> Void
    let profile: @MainActor () -> ServerProfile
    let saveProfile: @MainActor (ServerProfile) -> Void
    let generation: @MainActor () -> UInt64
    let invalidate: @MainActor () -> Void
    let flush: @MainActor () throws -> Void

    static var live: Self {
        Self(standard: .standard, shared: OpenMatesSharedEnvironment.defaults,
            cookies: OpenMatesSharedEnvironment.cookieStorage,
            loadKey: { try await CryptoManager.shared.loadMasterKey(for: $0) },
            saveKey: { try await CryptoManager.shared.saveMasterKey($0, for: $1) },
            deleteKey: { try await CryptoManager.shared.deleteMasterKey(for: $0) },
            profile: { WatchServerProfileStore().currentProfile() },
            saveProfile: {
                WatchServerProfileStore().saveSuccessfulProfile($0)
                ServerConfiguration.current = $0.endpointConfiguration
            }, generation: { WatchChatAccountLifecycle.generation },
            invalidate: { WatchChatAccountLifecycle.invalidate() },
            flush: { try PairPendingAckStore.flushLocalPairState() })
    }
}

@MainActor
final class WatchPairAuthenticationTransaction {
    static let cachedUserKey = "openmates.apple.auth.cached_user"
    private(set) var isRunning = false
    var waitingCount: Int { waiters.count }
    private struct Waiter { let id: UUID; let continuation: CheckedContinuation<Void, Error> }
    private var waiters: [Waiter] = []
    private let storage: WatchPairAuthenticationStorage

    init(storage: WatchPairAuthenticationStorage) { self.storage = storage }

    private func acquire() async throws {
        try Task.checkCancellation()
        if !isRunning { isRunning = true; return }
        let id = UUID()
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                if Task.isCancelled { continuation.resume(throwing: CancellationError()) }
                else { waiters.append(Waiter(id: id, continuation: continuation)) }
            }
        }, onCancel: { [weak self] in
            Task { @MainActor in self?.cancelWaiter(id) }
        })
        // A successful resume owns the reserved lease. Cancellation after that
        // handoff must pass it on rather than strand another queued receiver.
        do { try Task.checkCancellation() } catch { release(); throw error }
    }
    private func cancelWaiter(_ id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.id == id }) else { return }
        waiters.remove(at: index).continuation.resume(throwing: CancellationError())
    }
    private func release() {
        if waiters.isEmpty { isRunning = false }
        else { waiters.removeFirst().continuation.resume() }
    }

    func run(serverProfile: ServerProfile, isCurrent: @escaping @MainActor () -> Bool,
             complete: @MainActor () async throws -> PairLoginResult,
             unregisterPush: @MainActor () async -> Void, acknowledge: @MainActor () async throws -> Void,
             publish: @MainActor (PairLoginResult) -> Void) async throws {
        try await acquire()
        defer { release() }
        try Task.checkCancellation()
        guard isCurrent() else { throw CancellationError() }
        let previousProfile = storage.profile()
        var ownedGeneration = storage.generation()
        var ownedProfile = previousProfile
        @MainActor func permitsContinuation() -> Bool {
            isCurrent() && self.storage.generation() == ownedGeneration && self.storage.profile() == ownedProfile
        }
        let slots = [Self.cachedUserKey, PairSessionDeadlineStore.userKey,
            PairSessionDeadlineStore.deadlineKey, PairPendingAckStore.key, PairVerifiedAccountStore.key]
        let standardBefore = DefaultsSnapshot(storage.standard, keys: slots)
        let sharedBefore = DefaultsSnapshot(storage.shared, keys: [Self.cachedUserKey])
        var standardOwned: [String: OwnedValue] = [:]
        var sharedOwned: [String: OwnedValue] = [:]
        let urls = [serverProfile.apiBaseURL, serverProfile.webBaseURL, serverProfile.uploadBaseURL]
        let cookiesBefore = CookieSnapshot(storage.cookies, urls: urls)
        var cookiesOwned = cookiesBefore
        var previousKey: SymmetricKey?
        var writtenKey: SymmetricKey?
        var keyUserID: String?
        var cleanupFailure: Error?
        let authority = WatchPairReceiverAuthority.Context(isCurrent: { permitsContinuation() },
            cookiesDidPublish: { [self] in cookiesOwned = CookieSnapshot(storage.cookies, urls: urls) },
            verifiedDidPersist: { [self] in
                standardOwned[PairVerifiedAccountStore.key] = OwnedValue(storage.standard.object(forKey: PairVerifiedAccountStore.key))
            })
        do {
            try await WatchPairCommitSequence.run(isCurrent: { permitsContinuation() }, complete: {
                try await WatchPairReceiverAuthority.$current.withValue(authority) { try await complete() }
            }, unregisterPush: unregisterPush, persistKey: { result in
                guard result.serverProfile == serverProfile, result.loginResponse.success,
                      let user = result.loginResponse.user else { throw AuthError.invalidCredentials }
                if result.loginResponse.needsDeviceVerification == true { throw AuthError.deviceVerificationRequired }
                let retained = try await storage.loadKey(user.id)
                try Task.checkCancellation()
                guard permitsContinuation() else { throw CancellationError() }
                previousKey = retained
                keyUserID = user.id
                try await storage.saveKey(result.masterKey, user.id)
                // A throwing save has not acquired ownership of an existing key.
                writtenKey = result.masterKey
            }, persistMetadata: { result in
                guard let user = result.loginResponse.user else { throw AuthError.invalidCredentials }
                let userData = try JSONEncoder().encode(user)
                guard permitsContinuation() else { throw CancellationError() }
                storage.invalidate(); ownedGeneration = storage.generation()
                storage.saveProfile(serverProfile); ownedProfile = serverProfile
                storage.standard.set(userData, forKey: Self.cachedUserKey)
                storage.shared.set(userData, forKey: Self.cachedUserKey)
                PairPendingAckStore.mark(userID: user.id, defaults: storage.standard)
                storage.standard.removeObject(forKey: PairSessionDeadlineStore.userKey)
                storage.standard.removeObject(forKey: PairSessionDeadlineStore.deadlineKey)
                if let deadline = result.loginResponse.pairExpiresAt {
                    storage.standard.set(user.id, forKey: PairSessionDeadlineStore.userKey)
                    storage.standard.set(deadline, forKey: PairSessionDeadlineStore.deadlineKey)
                }
                for key in slots { standardOwned[key] = OwnedValue(storage.standard.object(forKey: key)) }
                sharedOwned[Self.cachedUserKey] = OwnedValue(storage.shared.object(forKey: Self.cachedUserKey))
                try storage.flush()
            }, acknowledge: acknowledge, publish: { result in
                PairPendingAckStore.clear(defaults: storage.standard)
                publish(result)
            }, rollback: { _ in
                // Queue ownership blocks successor receiver completion while all
                // async cleanup runs. Compare written values as an extra fence
                // against an independently replaced account or credential.
                // Captured URL/value ownership remains valid when a later Login
                // selects another profile; profile ownership controls only profile restoration.
                cookiesBefore.restore(storage.cookies, urls: urls, owned: cookiesOwned)
                guard storage.generation() == ownedGeneration else { return }
                if let userID = keyUserID, let writtenKey {
                    do {
                        if let current = try await storage.loadKey(userID), storage.generation() == ownedGeneration, Self.equalKeys(current, writtenKey) {
                            if let previousKey { try await storage.saveKey(previousKey, userID) }
                            else { try await storage.deleteKey(userID) }
                        }
                    } catch { cleanupFailure = error }
                }
                guard storage.generation() == ownedGeneration else { return }
                standardBefore.restore(storage.standard, owned: standardOwned)
                sharedBefore.restore(storage.shared, owned: sharedOwned)
                if storage.profile() == serverProfile { storage.saveProfile(previousProfile) }
                do { try storage.flush() } catch { cleanupFailure = error }
            })
        } catch {
            if let cleanupFailure {
                NativeDiagnostics.error("phase=pair_login.rollback.failed errorType=\(type(of: cleanupFailure))", category: "watch_pair_login")
                throw cleanupFailure
            }
            throw error
        }
    }

    private static func equalKeys(_ lhs: SymmetricKey, _ rhs: SymmetricKey) -> Bool {
        lhs.withUnsafeBytes { left in rhs.withUnsafeBytes { right in Data(left) == Data(right) } }
    }
    private struct OwnedValue {
        let value: Any?
        init(_ value: Any?) { self.value = value }
        func matches(_ other: Any?) -> Bool {
            if value == nil && other == nil { return true }
            guard let value = value as? NSObject, let other else { return false }
            return value.isEqual(other)
        }
    }
    private struct DefaultsSnapshot {
        let values: [String: OwnedValue]
        init(_ defaults: UserDefaults, keys: [String]) {
            values = Dictionary(uniqueKeysWithValues: keys.map { ($0, OwnedValue(defaults.object(forKey: $0))) })
        }
        func restore(_ defaults: UserDefaults, owned: [String: OwnedValue]) {
            for (key, current) in owned where current.matches(defaults.object(forKey: key)) {
                if let value = values[key]?.value { defaults.set(value, forKey: key) }
                else { defaults.removeObject(forKey: key) }
            }
        }
    }
    private struct CookieSnapshot {
        let values: [String: HTTPCookie]
        private static func id(_ cookie: HTTPCookie) -> String { "\(cookie.domain)|\(cookie.path)|\(cookie.name)" }
        init(_ jar: HTTPCookieStorage, urls: [URL]) {
            values = Dictionary(urls.flatMap { jar.cookies(for: $0) ?? [] }
                .filter { $0.name == "auth_refresh_token" }.map { (Self.id($0), $0) }, uniquingKeysWith: { first, _ in first })
        }
        func restore(_ jar: HTTPCookieStorage, urls: [URL], owned: CookieSnapshot) {
            let current = CookieSnapshot(jar, urls: urls)
            for id in Set(values.keys).union(owned.values.keys) {
                guard current.values[id]?.value == owned.values[id]?.value else { continue }
                if let cookie = current.values[id] { jar.deleteCookie(cookie) }
                if let cookie = values[id] { jar.setCookie(cookie) }
            }
        }
    }
}
