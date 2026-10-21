import CryptoKit
import Foundation
import Security
import XCTest
@testable import OpenMates

final class NotificationReplyContextTests: XCTestCase {
    private let owner = "11111111-1111-4111-8111-111111111111"
    private let nonce = "22222222-2222-4222-8222-222222222222"
    private let chat = "33333333-3333-4333-8333-333333333333"
    private let message = "44444444-4444-4444-8444-444444444444"
    private let notification = "55555555-5555-5555-8555-555555555555"
    private let fingerprint = String(repeating: "a", count: 64)

    private func context(owner: String? = nil, nonce: String? = nil,
                         workspace: NotificationReplyContext.Workspace = .init(kind: "personal", hashedTeamID: nil)) -> NotificationReplyContext {
        .init(version: 1, registrationContextID: nonce ?? self.nonce, recipientAccountID: owner ?? self.owner,
              notificationID: notification, chatID: chat, messageID: message, workspace: workspace)
    }
    private var binding: NotificationReplyBinding {
        .init(registrationContextID: nonce, accountID: owner, serverURL: "https://fixture.invalid",
              keyFingerprint: fingerprint)
    }
    private final class MemoryKeychain {
        struct Item { let bytes: Data; let accessible: CFString }
        var items: [String: Item] = [:]
        var unlocked = true
        var failWrites = false
        var queries: [[CFString: Any]] = []
        var operations: NotificationReplyStore.Operations {
            .init(copy: { [self] query in
                queries.append(query)
                if let account = query[kSecAttrAccount] as? String {
                    guard let item = items[account] else { return (errSecItemNotFound, nil) }
                    guard unlocked || item.accessible != kSecAttrAccessibleWhenUnlockedThisDeviceOnly else {
                        return (errSecInteractionNotAllowed, nil)
                    }
                    return (errSecSuccess, item.bytes)
                }
                let rows = items.map { account, item -> [CFString: Any] in
                    [kSecAttrAccount: account, kSecValueData: item.bytes]
                }
                return (errSecSuccess, rows)
            }, add: { [self] query in
                queries.append(query)
                if failWrites { return errSecNotAvailable }
                guard let account = query[kSecAttrAccount] as? String,
                      let bytes = query[kSecValueData] as? Data,
                      let accessible = query[kSecAttrAccessible] else { return errSecParam }
                guard items[account] == nil else { return errSecDuplicateItem }
                items[account] = Item(bytes: bytes, accessible: accessible as! CFString)
                return errSecSuccess
            }, delete: { [self] query in
                queries.append(query)
                if let account = query[kSecAttrAccount] as? String { items.removeValue(forKey: account) }
                else { items.removeAll() }
                return errSecSuccess
            })
        }
        var store: NotificationReplyStore { .init(accessGroup: "FIXTURE.org.openmates.app", operations: operations) }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.payload.privacy-safe
    func testOnlyACKCreatesSplitAccessibilityRegistrationAndEditorAuthority() throws {
        let memory = MemoryKeychain(); let store = memory.store
        XCTAssertNil(try store.registration())
        XCTAssertNil(try store.unlockedBinding())
        try store.acknowledge(binding)
        XCTAssertEqual(try store.unlockedBinding(), binding)
        XCTAssertEqual(memory.items["registration"]?.accessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly)
        XCTAssertEqual(memory.items["editor-unlocked"]?.accessible, kSecAttrAccessibleWhenUnlockedThisDeviceOnly)
        for query in memory.queries {
            XCTAssertEqual(query[kSecAttrService] as? String, "org.openmates.notification-reply.v1")
            XCTAssertEqual(query[kSecAttrAccessGroup] as? String, "FIXTURE.org.openmates.app")
            XCTAssertEqual(query[kSecAttrSynchronizable] as? Bool, false)
        }
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        let originalTarget = try XCTUnwrap(store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        memory.unlocked = false
        XCTAssertEqual(try store.registration(), binding, "Service routing survives device lock")
        XCTAssertThrowsError(try store.unlockedBinding(), "The editor requires an accessible WhenUnlocked marker")
        XCTAssertThrowsError(try store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        memory.unlocked = true
        XCTAssertEqual(try store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint), originalTarget,
                       "Unlock may restore only the exact retained OS request and ciphertext target")
        XCTAssertNil(try store.validatedTarget(requestID: "another-os-request", payloadDigest: fingerprint))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.action.routing-coherent
    func testMissingMarkerCannotAuthorizeEditorDespiteRegistrationAndTarget() throws {
        let memory = MemoryKeychain(); let store = memory.store
        try store.acknowledge(binding)
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        memory.items.removeValue(forKey: "editor-unlocked")
        XCTAssertNil(try store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        XCTAssertNotNil(try store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint, requireUnlocked: false))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.payload.privacy-safe
    func testOwnerNonceKeyAndExactOSRequestMustMatch() throws {
        let memory = MemoryKeychain(); let store = memory.store
        try store.acknowledge(binding)
        for invalid in [context(owner: chat), context(nonce: message)] {
            XCTAssertThrowsError(try store.saveValidatedTarget(invalid, requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint))
        }
        XCTAssertThrowsError(try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint,
            keyFingerprint: String(repeating: "b", count: 64)))
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        XCTAssertNil(try store.validatedTarget(requestID: "different-os-request", payloadDigest: fingerprint))
        XCTAssertNil(try store.validatedTarget(requestID: "os-request", payloadDigest: String(repeating: "b", count: 64)))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.action.routing-coherent
    func testWorkspaceMustBeExplicitAndCannotFallBackToPersonal() throws {
        let encoder = JSONEncoder()
        var fields = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(context())) as? [String: Any])
        fields.removeValue(forKey: "workspace")
        XCTAssertThrowsError(try JSONDecoder().decode(NotificationReplyContext.self,
            from: JSONSerialization.data(withJSONObject: fields)))
        let teamHash = NotificationReplyStore.digest(Data(chat.utf8))
        XCTAssertTrue(context(workspace: .init(kind: "team", hashedTeamID: teamHash)).isValid)
        XCTAssertFalse(context(workspace: .init(kind: "team", hashedTeamID: nil)).isValid)
        XCTAssertFalse(context(workspace: .init(kind: "personal", hashedTeamID: teamHash)).isValid)
        XCTAssertFalse(context(workspace: .init(kind: "team", hashedTeamID: String(repeating: "A", count: 64))).isValid)
        XCTAssertFalse(context(workspace: .init(kind: "unknown", hashedTeamID: nil)).isValid)
        XCTAssertTrue(context().workspace.matches(teamID: nil))
        XCTAssertFalse(context().workspace.matches(teamID: chat))
        XCTAssertTrue(context(workspace: .init(kind: "team", hashedTeamID: teamHash)).workspace.matches(teamID: chat))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.delivery.idempotent-visible
    func testExpansionAndEmptySendProduceNoSubmission() throws {
        let memory = MemoryKeychain(); let store = memory.store
        try store.acknowledge(binding)
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        let target = try XCTUnwrap(store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        XCTAssertTrue(try store.submissions().isEmpty, "Target lookup/expansion has no submission side effects")
        XCTAssertThrowsError(try store.submit(target, content: " \n\t"))
        XCTAssertTrue(try store.submissions().isEmpty)
        memory.failWrites = true
        XCTAssertThrowsError(try store.submit(target, content: "explicit reply"))
        XCTAssertTrue(try store.submissions().isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.delivery.idempotent-visible
    func testExplicitSendIsImmutableAndConflictingDuplicateFails() throws {
        let memory = MemoryKeychain(); let store = memory.store
        try store.acknowledge(binding)
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        let target = try XCTUnwrap(store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        let original = try store.submit(target, content: "  exact editor bytes \n")
        let originalBytes = memory.items[original.id]?.bytes
        XCTAssertEqual(try store.submit(target, content: original.content), original)
        XCTAssertEqual(memory.items[original.id]?.bytes, originalBytes)
        XCTAssertThrowsError(try store.submit(target, content: "different reply"))
        XCTAssertEqual(memory.items[original.id]?.bytes, originalBytes)
        XCTAssertEqual(try store.submissions(), [original])
        XCTAssertEqual(try store.submission(requestID: "os-request", payloadDigest: fingerprint), original)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.delivery.idempotent-visible
    func testCrashBeforeForwardingRecoversExactSubmissionThroughLedger() throws {
        let memory = MemoryKeychain()
        do {
            let extensionStore = memory.store
            try extensionStore.acknowledge(binding)
            try extensionStore.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
            let target = try XCTUnwrap(extensionStore.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
            _ = try extensionStore.submit(target, content: "explicit reply")
        }
        let appStore = memory.store
        let submission = try XCTUnwrap(appStore.submissions().first)
        let request = NotificationReplyRequest(id: submission.id, chatId: submission.target.context.chatID,
            content: submission.content, accountId: submission.target.binding.accountID,
            serverURL: submission.target.binding.serverURL, target: submission.target)
        var ledger = NotificationReplyLedger()
        ledger.enqueue(request); ledger.enqueue(request)
        let persisted = try JSONEncoder().encode(ledger)
        var recovered = try JSONDecoder().decode(NotificationReplyLedger.self, from: persisted)
        XCTAssertEqual(recovered.pending, [request])
        XCTAssertEqual(recovered.pending.first?.target?.context.messageID, message)
        recovered.complete(submission.id); recovered.enqueue(request)
        XCTAssertTrue(recovered.pending.isEmpty, "ACKed sends must not replay when an immutable handoff remains")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.registration.lifecycle
    func testLogoutAccountProfileAndKeyRotationInvalidateOldTargets() throws {
        let memory = MemoryKeychain(); let store = memory.store
        try store.acknowledge(binding)
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        let target = try XCTUnwrap(store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        _ = try store.submit(target, content: "explicit reply")
        store.revoke()
        XCTAssertNil(try store.registration()); XCTAssertNil(try store.unlockedBinding())
        XCTAssertNil(try store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        XCTAssertTrue(try store.submissions().isEmpty)
        let replacement = NotificationReplyBinding(registrationContextID: chat, accountID: owner,
            serverURL: "https://replacement.invalid", keyFingerprint: String(repeating: "b", count: 64))
        try store.acknowledge(replacement)
        XCTAssertThrowsError(try store.submit(target, content: "late stale send"))
        XCTAssertThrowsError(try store.saveValidatedTarget(context(), requestID: "new-os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.delivery.idempotent-visible
    func testCompletedSubmissionNeverReimportsAfterLedgerRecentIDsExpire() throws {
        let memory = MemoryKeychain(); let store = memory.store
        try store.acknowledge(binding)
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        let target = try XCTUnwrap(store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        let submission = try store.submit(target, content: "explicit reply")
        var ledger = NotificationReplyLedger()
        ledger.complete(submission.id)
        for index in 0..<129 { ledger.complete("later-\(index)") }
        XCTAssertFalse(ledger.completedIds.contains(submission.id), "Exercise expiration of the existing recent ACK window")
        try store.complete(target) // Called only after the actual pipeline ACK.
        XCTAssertTrue(try store.submissions().isEmpty)
        XCTAssertNil(try store.submission(requestID: "os-request", payloadDigest: fingerprint))
        XCTAssertNil(try store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        XCTAssertThrowsError(try store.submit(target, content: "late duplicate"))
        XCTAssertNil(memory.items[submission.id], "Acknowledged reply text is removed after durable tombstone persistence")
        XCTAssertNotNil(memory.items["completed-" + submission.id])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.registration.lifecycle
    func testRegistrationRequiresExactDurableNonceEchoBeforeEditorAuthority() {
        XCTAssertFalse(binding.isAcknowledged(by: ["success": true]))
        XCTAssertFalse(binding.isAcknowledged(by: ["success": false, "reply_context_id": nonce]))
        XCTAssertFalse(binding.isAcknowledged(by: ["success": true, "reply_context_id": chat]))
        XCTAssertFalse(binding.isAcknowledged(by: ["success": true, "reply_context_id": NSNull()]))
        XCTAssertTrue(binding.isAcknowledged(by: ["success": true, "reply_context_id": nonce]))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.delivery.idempotent-visible
    func testRevocationAfterDurableImportPreservesOwnerFencedOutboxIntent() throws {
        let memory = MemoryKeychain(); let store = memory.store
        try store.acknowledge(binding)
        try store.saveValidatedTarget(context(), requestID: "os-request", payloadDigest: fingerprint, keyFingerprint: fingerprint)
        let target = try XCTUnwrap(store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        let submission = try store.submit(target, content: "explicit reply")
        var ledger = NotificationReplyLedger()
        ledger.enqueue(.init(id: submission.id, chatId: target.context.chatID, content: submission.content,
            accountId: target.binding.accountID, serverURL: target.binding.serverURL, target: target))
        let durableOutbox = try JSONEncoder().encode(ledger)
        store.revoke()
        XCTAssertTrue(try store.submissions().isEmpty, "Revocation prevents new extension imports")
        XCTAssertNil(try store.validatedTarget(requestID: "os-request", payloadDigest: fingerprint))
        let recovered = try JSONDecoder().decode(NotificationReplyLedger.self, from: durableOutbox)
        let drain = recovered.requests(accountId: owner, serverURL: binding.serverURL)
        XCTAssertEqual(drain.count, 1, "Previously imported explicit Send remains normal outbox intent")
        XCTAssertEqual(drain.first?.target, target)
        XCTAssertEqual(drain.first?.content, submission.content)
        XCTAssertTrue(recovered.requests(accountId: chat, serverURL: binding.serverURL).isEmpty)
        XCTAssertTrue(recovered.requests(accountId: owner, serverURL: "https://another.invalid").isEmpty)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.action.routing-coherent
    func testExplicitReplyResolvesExactTeamFromPersonalOrAnotherTeam() async throws {
        for initialTeam in [nil, "team-a" as String?] {
            let fixture = NotificationReplyWorkspaceFixture()
            defer { fixture.cleanup() }
            let first = fixture.team("team-a"), target = fixture.team("team-b")
            fixture.service.memberships = [first, target]
            await fixture.context.load(accountID: fixture.accountID)
            if let initialTeam { await fixture.context.selectTeam(initialTeam) }
            let listCount = fixture.service.listCount
            fixture.service.detailRequests = []
            let workspace = NotificationReplyContext.Workspace(kind: "team",
                hashedTeamID: NotificationReplyStore.digest(Data(target.id.utf8)))
            try await NotificationReplyWorkspaceRestorer.restore(workspace, accountID: fixture.accountID,
                context: fixture.context, validateOwner: fixture.requireOwner)
            XCTAssertEqual(fixture.context.teamID, target.id)
            XCTAssertEqual(fixture.service.listCount, listCount + 1, "Every Team Send refreshes membership")
            XCTAssertEqual(fixture.service.detailRequests, [target.id], "Only the exact authorized Team is selected")
            XCTAssertTrue(fixture.context.selectedTeam?.canContribute == true)
        }
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.action.routing-coherent
    func testTeamReplyNeverFallsBackForMissingViewerOrOfflineMembership() async throws {
        for failure in ["missing", "viewer", "offline"] {
            let fixture = NotificationReplyWorkspaceFixture()
            defer { fixture.cleanup() }
            let target = fixture.team("team-b", role: failure == "viewer" ? .viewer : .member)
            fixture.service.memberships = [fixture.team("team-a"), target]
            await fixture.context.load(accountID: fixture.accountID)
            await fixture.context.selectTeam("team-a")
            fixture.service.detailRequests = []
            if failure == "missing" { fixture.service.memberships = [fixture.team("team-a")] }
            if failure == "offline" { fixture.service.listError = URLError(.notConnectedToInternet) }
            let workspace = NotificationReplyContext.Workspace(kind: "team",
                hashedTeamID: NotificationReplyStore.digest(Data(target.id.utf8)))
            do {
                try await NotificationReplyWorkspaceRestorer.restore(workspace, accountID: fixture.accountID,
                    context: fixture.context, validateOwner: fixture.requireOwner)
                XCTFail("Missing, read-only or cached membership cannot authorize Send")
            } catch { }
            XCTAssertEqual(fixture.context.teamID, "team-a")
            XCTAssertTrue(fixture.service.detailRequests.isEmpty)
        }
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.action.routing-coherent
    func testFreshTeamDetailDenialCannotDeliverInPersonalFallback() async throws {
        let fixture = NotificationReplyWorkspaceFixture()
        defer { fixture.cleanup() }
        fixture.service.memberships = [fixture.team("team-b")]
        await fixture.context.load(accountID: fixture.accountID)
        fixture.service.detailError = APIError.httpError(status: 403, message: "Fixture membership denied")
        let workspace = NotificationReplyContext.Workspace(kind: "team",
            hashedTeamID: NotificationReplyStore.digest(Data("team-b".utf8)))
        do {
            try await NotificationReplyWorkspaceRestorer.restore(workspace, accountID: fixture.accountID,
                context: fixture.context, validateOwner: fixture.requireOwner)
            XCTFail("A denied fresh Team detail must leave the reply pending")
        } catch { }
        XCTAssertNil(fixture.context.teamID, "Revocation may clear selection, but never authorizes a Personal send")
        XCTAssertFalse(workspace.matches(teamID: fixture.context.teamID))
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.action.routing-coherent
    func testOwnerProfileOrGenerationChangesDuringRosterCannotSelectTeam() async throws {
        for change in ["owner", "profile", "generation"] {
            let fixture = NotificationReplyWorkspaceFixture()
            defer { fixture.cleanup() }
            fixture.service.memberships = [fixture.team("team-b")]
            await fixture.context.load(accountID: fixture.accountID)
            fixture.service.beforeList = {
                if change == "owner" { fixture.accountID = "replacement-account" }
                if change == "profile" { fixture.server = .production }
                if change == "generation" { fixture.scope = UUID() }
            }
            let workspace = NotificationReplyContext.Workspace(kind: "team",
                hashedTeamID: NotificationReplyStore.digest(Data("team-b".utf8)))
            do {
                try await NotificationReplyWorkspaceRestorer.restore(workspace, accountID: owner,
                    context: fixture.context, validateOwner: fixture.requireOwner)
                XCTFail("Changed owner/profile/generation cannot restore the old notification workspace")
            } catch { }
            XCTAssertNil(fixture.context.teamID)
            XCTAssertTrue(fixture.service.detailRequests.isEmpty)
        }
    }

    private func encrypted(_ envelope: [String: Any], recipient: Curve25519.KeyAgreement.PrivateKey) throws -> [AnyHashable: Any] {
        let ephemeral = Curve25519.KeyAgreement.PrivateKey()
        let secret = try ephemeral.sharedSecretFromKeyAgreement(with: recipient.publicKey)
        let key = secret.hkdfDerivedSymmetricKey(using: SHA256.self, salt: Data(),
            sharedInfo: Data("openmates-apns-notification-v1".utf8), outputByteCount: 32)
        let box = try AES.GCM.seal(JSONSerialization.data(withJSONObject: envelope), using: key)
        func encoded(_ data: Data) -> String {
            data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        }
        return ["encrypted_notification": ["version": NotificationPreviewCrypto.encryptionVersion,
            "ephemeral_public_key": encoded(ephemeral.publicKey.rawRepresentation),
            "nonce": encoded(box.nonce.withUnsafeBytes { Data($0) }), "ciphertext": encoded(box.ciphertext + box.tag)]]
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.payload.privacy-safe
    func testAuthenticatedEnvelopeSeparatesPreviewAndRouteOnlyContext() throws {
        let recipient = Curve25519.KeyAgreement.PrivateKey()
        let fields = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(context())) as? [String: Any])
        for preview in [nil, "Readable message" as String?] {
            var plaintext: [String: Any] = ["reply_context": fields]
            plaintext["preview"] = preview
            let payload = try encrypted(plaintext, recipient: recipient)
            let envelope = try XCTUnwrap(NotificationPreviewCrypto.decryptEnvelope(userInfo: payload, privateKeyData: recipient.rawRepresentation))
            XCTAssertEqual(envelope.replyContext, context())
            XCTAssertTrue(envelope.hasReplyContext)
            XCTAssertEqual(envelope.display?.body, preview)
            XCTAssertEqual(envelope.keyFingerprint, NotificationReplyStore.digest(recipient.publicKey.rawRepresentation))
            XCTAssertNil(NotificationPreviewCrypto.decryptEnvelope(userInfo: payload,
                privateKeyData: Curve25519.KeyAgreement.PrivateKey().rawRepresentation))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.direct-reply,apple-notifications.payload.privacy-safe
    func testLegacyDisplayCompatibilityAndMalformedExplicitContextFailClosed() throws {
        let recipient = Curve25519.KeyAgreement.PrivateKey()
        let legacy = try encrypted(["preview": "Legacy display"], recipient: recipient)
        let old = try XCTUnwrap(NotificationPreviewCrypto.decryptEnvelope(userInfo: legacy, privateKeyData: recipient.rawRepresentation))
        XCTAssertFalse(old.hasReplyContext); XCTAssertNil(old.replyContext)
        XCTAssertEqual(old.display?.body, "Legacy display")
        let malformed = try encrypted(["preview": "Must remain hidden on invalid route", "reply_context": ["version": 1]], recipient: recipient)
        let invalid = try XCTUnwrap(NotificationPreviewCrypto.decryptEnvelope(userInfo: malformed, privateKeyData: recipient.rawRepresentation))
        XCTAssertTrue(invalid.hasReplyContext); XCTAssertNil(invalid.replyContext)
        XCTAssertNil(NotificationReplyStore.payloadDigest(userInfo: ["chat_id": chat]), "Outer legacy IDs cannot authorize an editor")
        XCTAssertNotEqual(NotificationReplyStore.payloadDigest(userInfo: legacy), NotificationReplyStore.payloadDigest(userInfo: malformed))
    }
}

@MainActor
private final class NotificationReplyWorkspaceFixture {
    var accountID = "11111111-1111-4111-8111-111111111111"
    var server = ServerProfile.development
    var scope = UUID()
    let service = NotificationReplyWorkspaceService()
    private let suite = "NotificationReplyWorkspaceTests.\(UUID().uuidString)"
    private lazy var defaults = UserDefaults(suiteName: suite)!
    private lazy var originalScope = scope
    lazy var context = TeamWorkspaceContext(service: service, environment: .init(
        currentAccountID: { [self] in await accountID }, scopeGeneration: { [self] in scope },
        serverProfile: { [self] in server }), defaults: defaults, revocationCleanup: { _, _, _ in })

    func requireOwner() throws {
        guard accountID == "11111111-1111-4111-8111-111111111111", server == .development,
              scope == originalScope else { throw NotificationReplyError.accountChanged }
    }
    func cleanup() { defaults.removePersistentDomain(forName: suite) }
    func team(_ id: String, role: TeamWorkspaceRole = .member) -> TeamWorkspaceTeam {
        .init(id: id, name: id, description: "", role: role, status: "active",
            profileImageMetadata: .generated, zeroBalance: 0, createdAt: 0, updatedAt: 0,
            key: SymmetricKey(data: Data(repeating: 7, count: 32)))
    }
}

@MainActor
private final class NotificationReplyWorkspaceService: TeamWorkspaceServing {
    var memberships: [TeamWorkspaceTeam] = []
    var listCount = 0
    var detailRequests: [String] = []
    var listError: Error?
    var detailError: Error?
    var beforeList: (() -> Void)?
    func cachedTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { memberships }
    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        listCount += 1
        beforeList?()
        try await fence.check()
        if let listError { throw listError }
        return memberships
    }
    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        detailRequests.append(id)
        try await fence.check()
        if let detailError { throw detailError }
        guard let team = memberships.first(where: { $0.id == id }) else { throw TeamWorkspaceError.unavailableTeam }
        return team
    }
}
