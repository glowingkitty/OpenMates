// Real AES-GCM snapshots and production lifecycle hooks; detached defaults only.
import CryptoKit
import XCTest
import WidgetKit
@testable import OpenMates

@MainActor
final class ActiveChatsWidgetTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private func snapshot(count: Int = 9) -> WidgetActiveChatsSnapshot {
        .init(owner: String(repeating: "a", count: 64), teamID: "team", updatedAt: now,
            chats: (1...count).map { .init(id: "chat-\($0)", title: "Private title \($0)", expiresAt: now.addingTimeInterval(900)) })
    }
    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testAccessoryProjectionRoutesRemainFencedAndExpireBeforeFirstRowSelection() throws {
        let value = snapshot()
        XCTAssertEqual(WidgetActiveChatsProjection.rowLimit(for: .systemMedium), 3)
        XCTAssertEqual(WidgetActiveChatsProjection.rowLimit(for: .systemLarge), 7)
        let circular = WidgetActiveChatsProjection(snapshot: value, date: now,
            limit: WidgetActiveChatsProjection.rowLimit(for: .accessoryCircular))
        XCTAssertEqual(circular.total, 9); XCTAssertTrue(circular.rows.isEmpty)
        let all = try XCTUnwrap(WidgetActiveChatsLinks.route(WidgetActiveChatsProjection.primaryURL(
            for: .accessoryCircular, snapshot: value, date: now)))
        XCTAssertEqual(all.destination, .all); XCTAssertEqual(all.owner, value.owner); XCTAssertEqual(all.teamID, value.teamID)
        let rectangular = WidgetActiveChatsProjection(snapshot: value, date: now,
            limit: WidgetActiveChatsProjection.rowLimit(for: .accessoryRectangular))
        XCTAssertEqual(rectangular.rows.map(\.id), ["chat-1"]); XCTAssertEqual(rectangular.overflow, 8)
        let selected = try XCTUnwrap(WidgetActiveChatsLinks.route(WidgetActiveChatsProjection.primaryURL(
            for: .accessoryRectangular, snapshot: value, date: now)))
        XCTAssertEqual(selected.destination, .chat("chat-1")); XCTAssertEqual(selected.owner, value.owner)
        XCTAssertEqual(selected.teamID, value.teamID)
        let mixed = WidgetActiveChatsSnapshot(owner: value.owner, teamID: value.teamID, updatedAt: now,
            chats: [.init(id: "expired", title: "Synthetic", expiresAt: now)] + value.chats)
        XCTAssertEqual(WidgetActiveChatsLinks.route(WidgetActiveChatsProjection.primaryURL(
            for: .accessoryRectangular, snapshot: mixed, date: now))?.destination, .chat("chat-1"))
        XCTAssertEqual(WidgetActiveChatsLinks.route(WidgetActiveChatsProjection.primaryURL(
            for: .accessoryRectangular, snapshot: value, date: now.addingTimeInterval(900)))?.destination, .all)
        XCTAssertEqual(WidgetActiveChatsProjection.primaryURL(for: .accessoryRectangular, snapshot: nil, date: now),
            WidgetActiveChatsLinks.openApp)
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.activity.global-running,apple-live-activities.processing.widget
    func testAllRunsRemainAvailableWithBoundedOrderedRowsAndExpiry() {
        let value = snapshot()
        let medium = WidgetActiveChatsProjection(snapshot: value, date: now, limit: 3)
        XCTAssertEqual(medium.rows.map(\.id), ["chat-1", "chat-2", "chat-3"])
        XCTAssertEqual(medium.total, 9); XCTAssertEqual(medium.overflow, 6)
        XCTAssertEqual(WidgetActiveChatsProjection(snapshot: value, date: now, limit: 7).overflow, 2)
        XCTAssertEqual(value.chats.first?.staleAt, now.addingTimeInterval(90))
        XCTAssertEqual(value.active(at: now.addingTimeInterval(900)).count, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testCiphertextRequiresActualKeyAndExactOwnerAndRejectsTampering() throws {
        let value = snapshot(), key = SymmetricKey(size: .bits256)
        let bytes = try WidgetActiveChatsSnapshotCodec.seal(value, key: key)
        XCTAssertNil(String(data: bytes, encoding: .utf8)?.range(of: "Private title"))
        XCTAssertEqual(try WidgetActiveChatsSnapshotCodec.open(bytes, owner: value.owner, key: key), value)
        XCTAssertThrowsError(try WidgetActiveChatsSnapshotCodec.open(bytes, owner: String(repeating: "b", count: 64), key: key))
        XCTAssertThrowsError(try WidgetActiveChatsSnapshotCodec.open(bytes, owner: value.owner, key: SymmetricKey(size: .bits256)))
        var damaged = bytes; damaged[damaged.startIndex] ^= 1
        XCTAssertThrowsError(try WidgetActiveChatsSnapshotCodec.open(damaged, owner: value.owner, key: key))
    }
    // contract-test: supporting surface=gui.apple assertions=chat-navigation.activity.global-running,apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testNativeStartAliasCompletionCensusAndLogoutPublishThroughSameHook() {
        let suite = "ActiveChatsWidgetTests-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let key = SymmetricKey(size: .bits256)
        var deletions = 0, reloads = 0
        let storage = WidgetActiveChatsStorage(defaults: defaults, loadKey: { _ in key }, deleteKey: { deletions += 1 })
        var coordinator: ActiveChatsCoordinator!
        let bridge = ActiveChatsWidgetBridge(storage: storage, reload: { reloads += 1 }, currentScope: { coordinator.currentScope })
        coordinator = ActiveChatsCoordinator(publishWidgetSnapshot: { policy, scope, evidence in bridge.publish(policy, scope: scope, authoritative: evidence, now: self.now) })
        let runtime = UUID(), team = APIRequestTeamContext(epoch: 1, teamID: "team")
        coordinator.configure(accountID: "account", server: .development, scope: runtime, team: team, authenticated: true)
        let scope = coordinator.currentScope!
        XCTAssertNil(storage.load()) // configure alone is not an accepted census
        coordinator.started(chatID: "first", turnID: "client", scope: scope, now: now)
        coordinator.started(chatID: "second", turnID: "second-turn", scope: scope, now: now)
        XCTAssertEqual(storage.load()?.chats.map(\.id), ["first", "second"])
        coordinator.adoptServerTurn(chatID: "first", provisionalTurnID: "client", serverTurnID: "server", scope: scope, now: now)
        coordinator.finished(chatID: "first", turnID: "old", scope: scope)
        XCTAssertEqual(storage.load()?.chats.count, 2)
        coordinator.finished(chatID: "first", turnID: "server", scope: scope)
        XCTAssertEqual(storage.load()?.chats.map(\.id), ["second"])
        coordinator.reconcileActiveChats([], scope: scope, now: now)
        XCTAssertEqual(storage.load()?.chats.count, 0)
        coordinator.started(chatID: "third", turnID: "third-turn", scope: scope, now: now)
        coordinator.configure(accountID: "other", server: .development, scope: runtime, team: team, authenticated: true)
        XCTAssertNil(storage.load())
        coordinator.started(chatID: "late", turnID: "late-turn", scope: scope, now: now)
        XCTAssertNil(storage.load())
        coordinator.reconcileActiveChats([.init(chatID: "restored", turnID: "restore-turn")], scope: coordinator.currentScope!, now: now)
        XCTAssertEqual(storage.load()?.chats.map(\.id), ["restored"])
        coordinator.reset()
        XCTAssertNil(storage.load()); XCTAssertNil(defaults.data(forKey: WidgetActiveChatsStorage.snapshotKey))
        XCTAssertNil(defaults.string(forKey: WidgetActiveChatsStorage.ownerKey))
        XCTAssertGreaterThan(deletions, 0); XCTAssertGreaterThan(reloads, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testTeamEpochRuntimeAndServerChangesClearAcceptedInventoryAndFenceLateWrites() throws {
        let suite = "ActiveChatsWidgetFenceTests-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!; defer { defaults.removePersistentDomain(forName: suite) }
        let key = SymmetricKey(size: .bits256)
        let storage = WidgetActiveChatsStorage(defaults: defaults, loadKey: { _ in key }, deleteKey: {})
        var current = ActiveChatsScope(accountID: "a", server: .development, scope: UUID(), team: .init(epoch: 1, teamID: "t"))
        let bridge = ActiveChatsWidgetBridge(storage: storage, reload: {}, currentScope: { current })
        var policy = ActiveChatsPolicy(); policy.start(.init(chatID: "chat", turnID: "turn"), now: now)
        bridge.publish(policy, scope: current, authoritative: true, now: now)
        XCTAssertFalse(storage.load()!.chats[0].title.contains("Unknown private title"))
        let old = current
        for replacement in [ActiveChatsScope(accountID: "a", server: .development, scope: old.scope, team: .init(epoch: 2, teamID: "t")),
                            ActiveChatsScope(accountID: "a", server: .development, scope: UUID(), team: .init(epoch: 2, teamID: "t")),
                            ActiveChatsScope(accountID: "a", server: .development, scope: UUID(), team: .init(epoch: 2, teamID: "other-team")),
                            ActiveChatsScope(accountID: "a", server: .production, scope: UUID(), team: .init(epoch: 2, teamID: "t"))] {
            current = replacement
            bridge.publish(.init(), scope: current, authoritative: false, now: now)
            XCTAssertNil(storage.load())
            bridge.publish(policy, scope: old, authoritative: true, now: now)
            XCTAssertNil(storage.load())
        }
        storage.activate(owner: snapshot().owner)
        try storage.save(snapshot())
        storage.activate(owner: String(repeating: "b", count: 64))
        try storage.save(snapshot()) // delayed save for former account ignored
        XCTAssertNil(storage.load())
    }
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testProgressReloadIsBoundedButTitlesTurnReplacementAndCompletionPublishImmediately() {
        let suite = "ActiveChatsWidgetReloadTests-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!; defer { defaults.removePersistentDomain(forName: suite) }
        let key = SymmetricKey(size: .bits256)
        let storage = WidgetActiveChatsStorage(defaults: defaults, loadKey: { _ in key }, deleteKey: {})
        let scope = ActiveChatsScope(accountID: "a", server: .development, scope: UUID(), team: .init(epoch: 1, teamID: nil))
        var reloads = 0
        let bridge = ActiveChatsWidgetBridge(storage: storage, reload: { reloads += 1 }, currentScope: { scope })
        var title = "First private title", hidden = false
        bridge.setChatLookup { id in
            Chat(id: id, title: title, lastMessageAt: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                 isArchived: nil, isPinned: nil, appId: nil, encryptedTitle: nil, encryptedChatKey: nil, isHidden: hidden)
        }
        var policy = ActiveChatsPolicy(); policy.start(.init(chatID: "chat", turnID: "turn"), now: now)
        bridge.publish(policy, scope: scope, authoritative: true, now: now)
        let baseline = reloads
        for seconds in [5.0, 10.0, 20.0] {
            policy.progress(chatID: "chat", turnID: "turn", now: now.addingTimeInterval(seconds))
            bridge.publish(policy, scope: scope, authoritative: true, now: now.addingTimeInterval(seconds))
        }
        XCTAssertEqual(reloads, baseline)
        policy.progress(chatID: "chat", turnID: "turn", now: now.addingTimeInterval(30))
        bridge.publish(policy, scope: scope, authoritative: true, now: now.addingTimeInterval(30))
        XCTAssertEqual(reloads, baseline + 1)
        title = "Renamed title"
        bridge.publish(policy, scope: scope, authoritative: true, now: now.addingTimeInterval(31))
        XCTAssertEqual(storage.load()?.chats.first?.title, title)
        hidden = true
        bridge.publish(policy, scope: scope, authoritative: true, now: now.addingTimeInterval(32))
        XCTAssertFalse(storage.load()!.chats.first!.title.contains(title))
        policy.start(.init(chatID: "chat", turnID: "replacement"), now: now.addingTimeInterval(33))
        bridge.publish(policy, scope: scope, authoritative: true, now: now.addingTimeInterval(33))
        XCTAssertEqual(reloads, baseline + 4)
        policy.finish(chatID: "chat", turnID: "replacement")
        bridge.publish(policy, scope: scope, authoritative: true, now: now.addingTimeInterval(34))
        XCTAssertEqual(storage.load()?.chats.count, 0); XCTAssertEqual(reloads, baseline + 5)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testPersonalOfflineRouteDoesNotRequireTeamInventoryAndTeamRoutesDo() throws {
        let server = ServerProfile.development
        let personalOwner = WidgetActiveChatsOwner.identity(accountID: "fixture", apiBaseURL: server.apiBaseURL, teamID: nil)
        let personal = try XCTUnwrap(WidgetActiveChatsLinks.route(try XCTUnwrap(WidgetActiveChatsLinks.chat("cached-chat", owner: personalOwner, teamID: nil))))
        XCTAssertTrue(ActiveChatsWidgetNavigationPolicy.accepts(personal, accountID: "fixture", server: server, readableTeamIDs: []))
        XCTAssertFalse(ActiveChatsWidgetNavigationPolicy.accepts(personal, accountID: "another-account", server: server, readableTeamIDs: []))
        let teamOwner = WidgetActiveChatsOwner.identity(accountID: "fixture", apiBaseURL: server.apiBaseURL, teamID: "team")
        let team = try XCTUnwrap(WidgetActiveChatsLinks.route(try XCTUnwrap(WidgetActiveChatsLinks.chat("team-chat", owner: teamOwner, teamID: "team"))))
        XCTAssertFalse(ActiveChatsWidgetNavigationPolicy.accepts(team, accountID: "fixture", server: server, readableTeamIDs: []))
        XCTAssertTrue(ActiveChatsWidgetNavigationPolicy.accepts(team, accountID: "fixture", server: server, readableTeamIDs: ["team"]))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.activity.global-running,apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testTypedLinksKeepOwnerFenceAndNeverBypassOrdinaryChatRoute() throws {
        let api = URL(string: "https://api.example.invalid")!
        let owner = WidgetActiveChatsOwner.identity(accountID: "private-account", apiBaseURL: api, teamID: "team")
        let url = try XCTUnwrap(WidgetActiveChatsLinks.chat("chat-1", owner: owner, teamID: "team"))
        XCTAssertFalse(url.absoluteString.contains("private-account")); XCTAssertFalse(url.absoluteString.contains("Private title"))
        let route = try XCTUnwrap(WidgetActiveChatsLinks.route(url))
        XCTAssertEqual(route.destination, .chat("chat-1"))
        XCTAssertTrue(route.belongsTo(accountID: "private-account", apiBaseURL: api, teamID: "team"))
        XCTAssertFalse(route.belongsTo(accountID: "other", apiBaseURL: api, teamID: "team"))
        XCTAssertFalse(route.belongsTo(accountID: "private-account", apiBaseURL: api, teamID: nil))
        XCTAssertFalse(route.belongsTo(accountID: "private-account", apiBaseURL: URL(string: "https://other.invalid")!, teamID: "team"))
        let handler = DeepLinkHandler(); handler.handle(url: url)
        XCTAssertEqual(handler.pendingActiveChatsWidgetLink, route); XCTAssertNil(handler.pendingChatId)
        handler.handle(url: URL(string: "openmates://chat/chat-1?owner=invalid")!)
        XCTAssertNil(handler.pendingActiveChatsWidgetLink); XCTAssertNil(handler.pendingChatId)
        handler.handle(url: try XCTUnwrap(WidgetActiveChatsLinks.all(owner: owner, teamID: "team")))
        XCTAssertEqual(handler.pendingActiveChatsWidgetLink?.destination, .all)
        handler.clearPending(); XCTAssertNil(handler.pendingActiveChatsWidgetLink)
        handler.handle(url: URL(string: "openmates://chat/ordinary-chat")!)
        XCTAssertEqual(handler.pendingChatId, "ordinary-chat")
        XCTAssertNil(WidgetActiveChatsLinks.chat("../other", owner: owner, teamID: nil))
        XCTAssertNil(WidgetActiveChatsLinks.route(URL(string: url.absoluteString + "&owner=" + owner)!))
        XCTAssertNil(WidgetActiveChatsLinks.route(URL(string: url.absoluteString + "#fragment")!))
    }
}
