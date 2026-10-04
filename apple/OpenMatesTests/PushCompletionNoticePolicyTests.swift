import XCTest
@testable import OpenMates

@MainActor
final class PushCompletionNoticePolicyTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testCompletionNoticeRequiresOptInAndExactAccountServerGeneration() {
        let context = PushRegistrationContext(accountID: "fixture-account", profile: .development, scope: UUID())
        XCTAssertTrue(PushCompletionNoticePolicy.permits(expected: context, current: context, notificationsEnabled: true))
        XCTAssertFalse(PushCompletionNoticePolicy.permits(expected: context, current: context, notificationsEnabled: false))
        XCTAssertFalse(PushCompletionNoticePolicy.permits(expected: context, current: nil, notificationsEnabled: true))
        for changed in [
            PushRegistrationContext(accountID: "other", profile: context.profile, scope: context.scope),
            PushRegistrationContext(accountID: context.accountID, profile: .production, scope: context.scope),
            PushRegistrationContext(accountID: context.accountID, profile: context.profile, scope: UUID())] {
            XCTAssertFalse(PushCompletionNoticePolicy.permits(expected: context, current: changed, notificationsEnabled: true))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testOpaqueMessageReceiptSurvivesRelaunchButSeparatesAccountServerChatAndMessage() {
        let context = PushRegistrationContext(accountID: "fixture-account", profile: .development, scope: UUID())
        let receipt = PushCompletionNoticePolicy.receiptID(context: context, chatID: "fixture-chat", messageID: "fixture-message")
        let relaunched = PushRegistrationContext(accountID: context.accountID, profile: context.profile, scope: UUID())
        XCTAssertEqual(receipt, PushCompletionNoticePolicy.receiptID(context: relaunched, chatID: "fixture-chat", messageID: "fixture-message"))
        XCTAssertFalse(receipt.contains("fixture"))
        XCTAssertNotEqual(receipt, PushCompletionNoticePolicy.receiptID(context: context, chatID: "other-chat", messageID: "fixture-message"))
        XCTAssertNotEqual(receipt, PushCompletionNoticePolicy.receiptID(context: context, chatID: "fixture-chat", messageID: "other-message"))
        for changed in [PushRegistrationContext(accountID: "other-account", profile: context.profile, scope: context.scope),
                        PushRegistrationContext(accountID: context.accountID, profile: .production, scope: context.scope)] {
            XCTAssertNotEqual(receipt, PushCompletionNoticePolicy.receiptID(context: changed, chatID: "fixture-chat", messageID: "fixture-message"))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testAuthoritativePushPreferencePublishesOnlyPreferenceAndPreservesLocalProfile() throws {
        var cached: [UserProfile] = []
        let auth = AuthManager(profileCacheWriter: { cached.append($0) })
        auth.state = .authenticated
        auth.currentUser = try user(id: "fixture-account", enabled: false, selection: "local-chat", key: "new-local-wrapper")
        let received = try user(id: "fixture-account", enabled: true, selection: "old-server-chat", key: "old-wrapper")
        auth.applyAuthoritativePushNotificationPreference(received, accountID: "fixture-account", profile: ServerProfile.current(), scope: OfflineStore.shared.scopeGeneration)
        XCTAssertEqual(auth.currentUser?.pushNotificationEnabled, true)
        XCTAssertEqual(auth.currentUser?.lastOpened, "local-chat")
        XCTAssertEqual(auth.currentUser?.encryptedKey, "new-local-wrapper")
        XCTAssertEqual(cached.count, 1)
        auth.applyAuthoritativePushNotificationPreference(received, accountID: "fixture-account", profile: ServerProfile.current(), scope: OfflineStore.shared.scopeGeneration)
        XCTAssertEqual(cached.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testAuthoritativePreferenceRejectsStaleOwnerScopeAndAbsentPreference() throws {
        let auth = AuthManager(profileCacheWriter: { _ in XCTFail("Stale preferences must not be cached") })
        auth.state = .authenticated
        auth.currentUser = try user(id: "fixture-account", enabled: false)
        let received = try user(id: "fixture-account", enabled: true)
        auth.applyAuthoritativePushNotificationPreference(received, accountID: "fixture-account", profile: ServerProfile.current(), scope: UUID())
        auth.applyAuthoritativePushNotificationPreference(received, accountID: "other", profile: ServerProfile.current(), scope: OfflineStore.shared.scopeGeneration)
        let otherServer: ServerProfile = ServerProfile.current() == .production ? .development : .production
        auth.applyAuthoritativePushNotificationPreference(received, accountID: "fixture-account", profile: otherServer, scope: OfflineStore.shared.scopeGeneration)
        let absent = try user(id: "fixture-account", enabled: nil)
        auth.applyAuthoritativePushNotificationPreference(absent, accountID: "fixture-account", profile: ServerProfile.current(), scope: OfflineStore.shared.scopeGeneration)
        XCTAssertEqual(auth.currentUser?.pushNotificationEnabled, false)
    }

    private func user(id: String, enabled: Bool?, selection: String? = nil, key: String? = nil) throws -> UserProfile {
        var fields: [String: Any] = ["id": id, "username": "Disposable fixture"]
        fields["pushNotificationEnabled"] = enabled
        fields["lastOpened"] = selection
        fields["encryptedKey"] = key
        return try JSONDecoder().decode(UserProfile.self, from: JSONSerialization.data(withJSONObject: fields))
    }
}
