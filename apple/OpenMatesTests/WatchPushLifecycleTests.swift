// Portable Watch push tests. Actual APNs acceptance requires provider evidence.
import XCTest
@testable import OpenMates

final class WatchPushLifecycleTests: XCTestCase {
    private let identity = WatchPushIdentity(accountID: "fixture-account", serverScope: "fixture-server", generation: 4)

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testRevokedOfflineSessionClearsLocalVisibilityBeforeServerCleanup() {
        let registration = WatchPushRegistration(identity: identity, token: "fixture-token", deviceID: "watch-fixture")
        let revocation = WatchPushRevocation()
        var osRegistered = true
        var hasReceipt = true
        var deliveredAlerts = 2
        revocation.revoke(registration) {
            osRegistered = false
            hasReceipt = false
            deliveredAlerts = 0
        }
        XCTAssertFalse(osRegistered)
        XCTAssertFalse(hasReceipt)
        XCTAssertEqual(deliveredAlerts, 0)
        XCTAssertEqual(revocation.pendingCleanup, registration)
        XCTAssertNil(revocation.cleanupFor(identity: identity, online: false))
        XCTAssertNil(revocation.cleanupFor(identity: nil, online: false))
        XCTAssertNil(revocation.cleanupFor(identity: WatchPushIdentity(accountID: "another-account",
            serverScope: identity.serverScope, generation: 5), online: true))
        XCTAssertNil(revocation.cleanupFor(identity: WatchPushIdentity(accountID: identity.accountID,
            serverScope: "another-server", generation: 5), online: true))
        let restored = WatchPushIdentity(accountID: identity.accountID, serverScope: identity.serverScope, generation: 5)
        XCTAssertEqual(revocation.cleanupFor(identity: restored, online: true), registration)
        revocation.acknowledge(WatchPushRegistration(identity: identity, token: "another-token", deviceID: "watch-fixture"))
        XCTAssertEqual(revocation.pendingCleanup, registration)
        revocation.acknowledge(registration)
        XCTAssertNil(revocation.pendingCleanup)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testTemporaryOnlineVerificationPreservesVisibleChatButNewGenerationClearsIt() {
        var visibility = WatchNotificationVisibility()
        visibility.show("viewed", identity: identity)
        let registration = WatchPushRegistration(identity: identity, token: "fixture-token", deviceID: "watch-fixture")
        XCTAssertFalse(registration.isCurrent(identity: identity, token: "fixture-token", permission: true, online: false))
        visibility.invalidateUnlessMatching(identity)
        XCTAssertFalse(visibility.shouldPresent(chatID: "viewed", identity: identity, active: true))
        XCTAssertTrue(visibility.shouldPresent(chatID: "other", identity: identity, active: true))
        let changed = WatchPushIdentity(accountID: identity.accountID, serverScope: identity.serverScope, generation: 5)
        visibility.invalidateUnlessMatching(changed)
        XCTAssertNil(visibility.chatID)
        XCTAssertTrue(visibility.shouldPresent(chatID: "viewed", identity: changed, active: true))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testRegistrationRejectsRotationOfflinePermissionAndChangedSession() {
        let registration = WatchPushRegistration(identity: identity, token: "fixture-token", deviceID: "watch-fixture")
        XCTAssertTrue(registration.isCurrent(identity: identity, token: "fixture-token", permission: true, online: true))
        XCTAssertFalse(registration.isCurrent(identity: identity, token: "rotated-token", permission: true, online: true))
        XCTAssertFalse(registration.isCurrent(identity: identity, token: "fixture-token", permission: false, online: true))
        XCTAssertFalse(registration.isCurrent(identity: identity, token: "fixture-token", permission: true, online: false))
        XCTAssertFalse(registration.isCurrent(identity: nil, token: "fixture-token", permission: true, online: true))
        for changed in [
            WatchPushIdentity(accountID: "another-account", serverScope: identity.serverScope, generation: 4),
            WatchPushIdentity(accountID: identity.accountID, serverScope: "another-server", generation: 4),
            WatchPushIdentity(accountID: identity.accountID, serverScope: identity.serverScope, generation: 5),
        ] {
            XCTAssertFalse(registration.isCurrent(identity: changed, token: "fixture-token", permission: true, online: true))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testTapWaitsForVerifiedSameAccountProfileAndLifecycle() throws {
        let route = try XCTUnwrap(WatchNotificationRoute(chatID: "exact-chat", identity: identity))
        XCTAssertEqual(route.chatID, "exact-chat")
        XCTAssertTrue(route.permitsOpen(identity: identity, online: true))
        XCTAssertFalse(route.permitsOpen(identity: identity, online: false))
        XCTAssertFalse(route.permitsOpen(identity: nil, online: true))
        XCTAssertFalse(route.permitsOpen(identity: WatchPushIdentity(accountID: "another-account",
            serverScope: identity.serverScope, generation: 4), online: true))
        XCTAssertFalse(route.permitsOpen(identity: WatchPushIdentity(accountID: identity.accountID,
            serverScope: "another-server", generation: 4), online: true))
        XCTAssertFalse(route.permitsOpen(identity: WatchPushIdentity(accountID: identity.accountID,
            serverScope: identity.serverScope, generation: 5), online: true))
        XCTAssertNil(WatchNotificationRoute(chatID: " ", identity: identity))
        XCTAssertNil(WatchNotificationRoute(chatID: "chat\nother", identity: identity))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testOnlyActiveViewedChatSuppressesForegroundNotification() {
        XCTAssertFalse(WatchNotificationRoute.shouldPresent(chatID: "viewed", viewedChatID: "viewed", active: true))
        XCTAssertTrue(WatchNotificationRoute.shouldPresent(chatID: "other", viewedChatID: "viewed", active: true))
        XCTAssertTrue(WatchNotificationRoute.shouldPresent(chatID: "viewed", viewedChatID: "viewed", active: false))
        XCTAssertTrue(WatchNotificationRoute.shouldPresent(chatID: nil, viewedChatID: nil, active: true))
        XCTAssertTrue(WatchNotificationRoute.shouldPresent(chatID: "viewed", viewedChatID: nil, active: true))
    }
}
