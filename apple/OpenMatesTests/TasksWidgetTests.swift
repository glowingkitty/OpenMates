// Specification: specifications/features/apple-tasks-widget/specification.yml
// Assertions: apple-tasks-widget.status-filter, apple-tasks-widget.links, apple-tasks-widget.private-cache

// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.lifecycle.isolation
// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.private-cache

import CryptoKit
import LocalAuthentication
import Security
import XCTest
import WidgetKit
@testable import OpenMates

final class TasksWidgetTests: XCTestCase {
    private let tasks: [WidgetTaskSummary] = [
        .init(id: "00000000-0000-4000-8000-000000000001", title: "Todo fixture", status: .todo),
        .init(id: "00000000-0000-4000-8000-000000000002", title: "Progress fixture", status: .inProgress),
        .init(id: "00000000-0000-4000-8000-000000000003", title: "Blocked fixture", status: .blocked),
        .init(id: "00000000-0000-4000-8000-000000000004", title: "Backlog fixture", status: .backlog),
        .init(id: "00000000-0000-4000-8000-000000000005", title: "Done fixture", status: .done),
    ]

    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.status-filter,apple-tasks-widget.links
    func testLockScreenLayoutsKeepFilterBeforeOneRowAndCreationRoute() throws {
        let snapshot = WidgetTasksSnapshot(owner: "fixture", updatedAt: Date(), tasks: tasks)
        XCTAssertEqual(WidgetTasksLayout.rowLimit(for: .systemMedium), 3)
        XCTAssertEqual(WidgetTasksLayout.rowLimit(for: .systemLarge), 7)
        XCTAssertEqual(WidgetTasksLayout.rowLimit(for: .accessoryCircular), 0)
        XCTAssertEqual(WidgetTasksLayout.primaryURL(for: .accessoryCircular, tasks: tasks), WidgetTasksLinks.newTask)
        for status in WidgetTaskFilter.allCases {
            let visible = snapshot.tasks(matching: status, limit: WidgetTasksLayout.rowLimit(for: .accessoryRectangular))
            XCTAssertEqual(visible.count, 1)
            XCTAssertEqual(visible[0], tasks.first { status == .all || $0.status == status })
            XCTAssertEqual(WidgetTasksLayout.primaryURL(for: .accessoryRectangular, tasks: visible),
                try XCTUnwrap(WidgetTasksLinks.task(visible[0].id)))
        }
        XCTAssertEqual(WidgetTasksLayout.primaryURL(for: .accessoryRectangular, tasks: []), WidgetTasksLinks.workspace)
        XCTAssertEqual(WidgetTasksLayout.primaryURL(for: .accessoryCircular, tasks: []), WidgetTasksLinks.newTask)
        XCTAssertEqual(WidgetTasksLayout.primaryURL(for: .accessoryRectangular,
            tasks: [.init(id: "invalid", title: "Synthetic", status: .todo)]), WidgetTasksLinks.workspace)
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.status-filter
    func testAllStatusesFilterBeforeApplyingVisibleLimit() {
        let snapshot = WidgetTasksSnapshot(owner: "owner-a", updatedAt: Date(), tasks: tasks)
        XCTAssertEqual(snapshot.tasks(matching: .all, limit: 3), Array(tasks.prefix(3)))
        for filter in WidgetTaskFilter.allCases where filter != .all {
            let matching = snapshot.tasks(matching: filter, limit: 1)
            XCTAssertEqual(matching.count, 1)
            XCTAssertEqual(matching.first?.status, filter)
        }
        XCTAssertTrue(snapshot.tasks(matching: .all, limit: 0).isEmpty)
        XCTAssertTrue(WidgetTasksSnapshot(owner: "a", updatedAt: Date(), tasks: []).tasks(matching: .todo, limit: 7).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.status-filter,apple-tasks-widget.private-cache
    func testFilteredAccessoryCountUsesAcceptedInventoryBeforeProviderAndVisibleLimits() {
        let statuses: [WidgetTaskFilter] = [.todo, .inProgress, .blocked, .backlog, .done]
        let inventory = statuses.flatMap { status in
            (0..<12).map { WidgetTaskSummary(id: "\(status.rawValue)-\($0)", title: "Synthetic", status: status) }
        }
        let snapshot = WidgetTasksSnapshot(owner: "fixture", updatedAt: Date(), tasks: inventory)
        XCTAssertEqual(snapshot.taskCount(matching: .all), 60)
        XCTAssertEqual(snapshot.tasks(matching: .all, limit: 12).count, 12)
        for status in statuses {
            XCTAssertEqual(snapshot.taskCount(matching: status), 12)
            XCTAssertEqual(snapshot.tasks(matching: status, limit: 1).count, 1)
        }
        let empty = WidgetTasksSnapshot(owner: "fixture", updatedAt: Date(), tasks: [])
        XCTAssertEqual(empty.taskCount(matching: .all), 0)
        XCTAssertEqual(empty.taskCount(matching: .blocked), 0)
        // The count is calculated after authorized decryption; ciphertext and owner fences remain in the codec tests.
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.status-filter,apple-tasks-widget.private-cache
    func testBoundedSnapshotKeepsEveryStatusWhenDoneColumnIsLarge() {
        let statuses: [WidgetTaskFilter] = [.done, .todo, .inProgress, .blocked, .backlog]
        let inventory = statuses.flatMap { status in
            (0..<30).map { index in WidgetTaskSummary(id: "\(status.rawValue)-\(index)", title: "Fixture", status: status) }
        }
        let bounded = WidgetTasksSnapshotBuilder.bounded(inventory)
        XCTAssertEqual(bounded.count, 60)
        XCTAssertEqual(bounded.first?.id, "done-0")
        for status in statuses {
            let matching = bounded.filter { $0.status == status }
            XCTAssertEqual(matching.count, 12)
            XCTAssertEqual(matching.map(\.id), (0..<12).map { "\(status.rawValue)-\($0)" })
        }
        XCTAssertTrue(WidgetTasksSnapshotBuilder.bounded([]).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.links
    func testQuickLinkAndIndividualTaskURLsAreDistinctAndValidateIDs() {
        XCTAssertEqual(WidgetTasksLinks.newTask.absoluteString, "openmates://new-task")
        XCTAssertEqual(WidgetTasksLinks.workspace.absoluteString, "openmates://tasks")
        for task in tasks {
            XCTAssertEqual(WidgetTasksLinks.task(task.id)?.absoluteString, "openmates://task/\(task.id)")
        }
        XCTAssertNil(WidgetTasksLinks.task("../new-task?token=private"))
        XCTAssertNil(WidgetTasksLinks.task(""))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testSnapshotRequiresMatchingOwnerAndDedicatedKey() throws {
        let snapshot = WidgetTasksSnapshot(owner: "owner-a", updatedAt: Date(timeIntervalSince1970: 100), tasks: tasks)
        let key = SymmetricKey(size: .bits256)
        let encrypted = try WidgetTasksSnapshotCodec.seal(snapshot, key: key)
        XCTAssertNil(encrypted.range(of: Data(tasks[0].title.utf8)))
        XCTAssertEqual(try WidgetTasksSnapshotCodec.open(encrypted, owner: "owner-a", key: key), snapshot)
        XCTAssertThrowsError(try WidgetTasksSnapshotCodec.open(encrypted, owner: "owner-b", key: key))
        XCTAssertThrowsError(try WidgetTasksSnapshotCodec.open(encrypted, owner: "owner-a", key: SymmetricKey(size: .bits256)))
        var corrupted = encrypted
        corrupted[corrupted.count - 1] ^= 1
        XCTAssertThrowsError(try WidgetTasksSnapshotCodec.open(corrupted, owner: "owner-a", key: key))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testLateResultsCannotCrossAccountServerGenerationOrTeamContext() {
        let generation = UUID()
        let active = TasksWidgetPublicationContext(accountID: "account-a", scope: generation,
            server: .production, teamID: "team-a", teamEpoch: 4)
        XCTAssertTrue(active.allowsResult(active, current: active))
        let stale = [
            TasksWidgetPublicationContext(accountID: "account-b", scope: generation, server: .production, teamID: "team-a", teamEpoch: 4),
            TasksWidgetPublicationContext(accountID: "account-a", scope: UUID(), server: .production, teamID: "team-a", teamEpoch: 4),
            TasksWidgetPublicationContext(accountID: "account-a", scope: generation, server: .development, teamID: "team-a", teamEpoch: 4),
            TasksWidgetPublicationContext(accountID: "account-a", scope: generation, server: .production, teamID: nil, teamEpoch: 4),
            TasksWidgetPublicationContext(accountID: "account-a", scope: generation, server: .production, teamID: "team-a", teamEpoch: 2),
        ]
        for previous in stale {
            XCTAssertFalse(active.allowsResult(previous, current: active))
            XCTAssertFalse(active.allowsResult(active, current: previous))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testSnapshotSchemaContainsOnlyMinimalTaskFields() throws {
        let snapshot = WidgetTasksSnapshot(owner: "owner-a", updatedAt: Date(), tasks: tasks)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(snapshot)) as? [String: Any])
        let encodedTasks = try XCTUnwrap(json["tasks"] as? [[String: Any]])
        XCTAssertEqual(Set(encodedTasks[0].keys), ["id", "title", "status"])
        XCTAssertEqual(Set(json.keys), ["owner", "updatedAt", "tasks"])
    }
}

/// Synthetic Security statuses only: these tests never touch the real Keychain.
@MainActor
final class WidgetSnapshotKeychainTests: XCTestCase {
    private let bytes = Data(repeating: 0x71, count: 32)
    private let base: [CFString: Any] = [
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: "org.openmates.app.active-chats-widget",
        kSecAttrAccount: "active-chats-snapshot-v1",
        kSecAttrAccessGroup: "FIXTURE.org.openmates.app.shared",
        kSecAttrSynchronizable: false,
    ]
    @MainActor
    private final class SecurityFixture {
        var reads: [(OSStatus, Data?)] = []
        var queries: [[CFString: Any]] = []
        var insertions: [[CFString: Any]] = []
        var deletions: [[CFString: Any]] = []
        var addStatus = errSecSuccess
        var generations = 0
        var operations: WidgetSnapshotKeychain.Operations {
            .init(copy: { query in
                self.queries.append(query)
                guard !self.reads.isEmpty else { XCTFail("Unexpected read"); return (errSecParam, nil) }
                return self.reads.removeFirst()
            }, add: { query in self.insertions.append(query); return self.addStatus },
            delete: { query in self.deletions.append(query); return errSecSuccess })
        }
    }
    private func subject(_ fixture: SecurityFixture, usesMacOSNamespaces: Bool = true) -> WidgetSnapshotKeychain {
        .init(baseQuery: base, usesMacOSNamespaces: usesMacOSNamespaces, operations: fixture.operations, makeKey: {
            fixture.generations += 1
            return self.bytes
        })
    }
    private func assertNoUI(_ query: [CFString: Any], file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(query[kSecUseAuthenticationUI] as? String, kSecUseAuthenticationUIFail as String, file: file, line: line)
        XCTAssertEqual((query[kSecUseAuthenticationContext] as? LAContext)?.interactionNotAllowed, true, file: file, line: line)
        XCTAssertEqual(query[kSecAttrService] as? String, base[kSecAttrService] as? String, file: file, line: line)
        XCTAssertEqual(query[kSecAttrAccount] as? String, base[kSecAttrAccount] as? String, file: file, line: line)
        XCTAssertEqual(query[kSecAttrAccessGroup] as? String, base[kSecAttrAccessGroup] as? String, file: file, line: line)
        XCTAssertEqual(query[kSecAttrSynchronizable] as? Bool, false, file: file, line: line)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testPrimaryReadUsesNoninteractiveProtectedIdentity() throws {
        let fixture = SecurityFixture(); fixture.reads = [(errSecSuccess, bytes)]
        let key = try subject(fixture).load(create: false)
        XCTAssertEqual(key.withUnsafeBytes { Data($0) }, bytes)
        XCTAssertEqual(fixture.queries.count, 1)
        let query = try XCTUnwrap(fixture.queries.first); assertNoUI(query)
        XCTAssertEqual(query[kSecUseDataProtectionKeychain] as? Bool, true)
        XCTAssertEqual(query[kSecReturnData] as? Bool, true)
        XCTAssertEqual(query[kSecMatchLimit] as? String, kSecMatchLimitOne as String)
        XCTAssertTrue(fixture.insertions.isEmpty); XCTAssertEqual(fixture.generations, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testOrdinaryIOSPolicyNeverReadsOrDeletesLegacyNamespace() throws {
        for create in [false, true] {
            let fixture = SecurityFixture(); fixture.reads = [(errSecItemNotFound, nil)]
            let keychain = subject(fixture, usesMacOSNamespaces: false)
            if create { XCTAssertEqual(try keychain.load(create: true).withUnsafeBytes { Data($0) }, bytes) }
            else { XCTAssertThrowsError(try keychain.load(create: false)) }
            XCTAssertEqual(fixture.queries.count, 1)
            assertNoUI(fixture.queries[0]); XCTAssertNil(fixture.queries[0][kSecUseDataProtectionKeychain])
            XCTAssertEqual(fixture.generations, create ? 1 : 0)
            XCTAssertEqual(fixture.insertions.count, create ? 1 : 0)
            if create {
                assertNoUI(fixture.insertions[0])
                XCTAssertNil(fixture.insertions[0][kSecUseDataProtectionKeychain])
            }
            keychain.clear()
            XCTAssertEqual(fixture.deletions.count, 1)
            assertNoUI(fixture.deletions[0]); XCTAssertNil(fixture.deletions[0][kSecUseDataProtectionKeychain])
        }
        #if os(macOS)
        XCTAssertTrue(WidgetSnapshotKeychain.platformUsesMacOSNamespaces)
        #else
        XCTAssertFalse(WidgetSnapshotKeychain.platformUsesMacOSNamespaces)
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testPrimaryFailureOrMalformedDataNeverFallsBackOrCreates() {
        let responses: [(OSStatus, Data?)] = [(errSecInteractionNotAllowed, nil), (errSecAuthFailed, nil),
            (errSecMissingEntitlement, nil), (errSecSuccess, nil), (errSecSuccess, Data(count: 31)),
            (errSecSuccess, Data(count: 33))]
        for response in responses {
            let fixture = SecurityFixture(); fixture.reads = [response]
            XCTAssertThrowsError(try subject(fixture).load(create: true))
            XCTAssertEqual(fixture.queries.count, 1); XCTAssertTrue(fixture.insertions.isEmpty)
            XCTAssertEqual(fixture.generations, 0); XCTAssertTrue(fixture.deletions.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testLegacyMigrationPreservesExactKeyAndDoesNotDeleteLegacy() throws {
        let fixture = SecurityFixture(); fixture.reads = [(errSecItemNotFound, nil), (errSecSuccess, bytes)]
        let migrated = try subject(fixture).load(create: false)
        XCTAssertEqual(migrated.withUnsafeBytes { Data($0) }, bytes)
        XCTAssertEqual(fixture.queries.count, 2); fixture.queries.forEach { assertNoUI($0) }
        XCTAssertNil(fixture.queries[1][kSecUseDataProtectionKeychain])
        let insertion = try XCTUnwrap(fixture.insertions.first); assertNoUI(insertion)
        XCTAssertEqual(insertion[kSecUseDataProtectionKeychain] as? Bool, true)
        XCTAssertEqual(insertion[kSecAttrAccessible] as? String, kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
        XCTAssertEqual(insertion[kSecValueData] as? Data, bytes)
        XCTAssertNil(insertion[kSecReturnData]); XCTAssertNil(insertion[kSecMatchLimit])
        XCTAssertEqual(fixture.generations, 0); XCTAssertTrue(fixture.deletions.isEmpty)
        let snapshot = WidgetTasksSnapshot(owner: "fixture-owner", updatedAt: Date(timeIntervalSince1970: 100), tasks: [])
        let ciphertext = try WidgetTasksSnapshotCodec.seal(snapshot, key: SymmetricKey(data: bytes))
        XCTAssertEqual(try WidgetTasksSnapshotCodec.open(ciphertext, owner: snapshot.owner, key: migrated), snapshot)
        XCTAssertThrowsError(try WidgetTasksSnapshotCodec.open(ciphertext, owner: "other-owner", key: migrated))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testLegacyUnavailableOrMalformedNeverGeneratesOrOverwrites() {
        let responses: [(OSStatus, Data?)] = [(errSecInteractionNotAllowed, nil), (errSecAuthFailed, nil),
            (errSecParam, nil), (errSecSuccess, nil), (errSecSuccess, Data(count: 31)), (errSecSuccess, Data(count: 33))]
        for response in responses {
            let fixture = SecurityFixture(); fixture.reads = [(errSecItemNotFound, nil), response]
            XCTAssertThrowsError(try subject(fixture).load(create: true))
            XCTAssertEqual(fixture.queries.count, 2); XCTAssertTrue(fixture.insertions.isEmpty)
            XCTAssertEqual(fixture.generations, 0); XCTAssertTrue(fixture.deletions.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testRejectedMigrationInsertionNeverCreatesReplacementOrDeletesLegacy() {
        for addStatus in [errSecInteractionNotAllowed, errSecAuthFailed, errSecMissingEntitlement, errSecParam] {
            let fixture = SecurityFixture(); fixture.addStatus = addStatus
            fixture.reads = [(errSecItemNotFound, nil), (errSecSuccess, bytes)]
            XCTAssertThrowsError(try subject(fixture).load(create: true))
            XCTAssertEqual(fixture.queries.count, 2); XCTAssertEqual(fixture.insertions.count, 1)
            XCTAssertEqual(fixture.insertions[0][kSecValueData] as? Data, bytes)
            XCTAssertEqual(fixture.generations, 0); XCTAssertTrue(fixture.deletions.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testMigrationDuplicateRequiresNoninteractiveRereadOfIdenticalKey() throws {
        let responses: [(OSStatus, Data?)] = [(errSecSuccess, bytes), (errSecSuccess, Data(repeating: 0x72, count: 32)),
            (errSecSuccess, Data(count: 31)), (errSecInteractionNotAllowed, nil), (errSecItemNotFound, nil)]
        for response in responses {
            let fixture = SecurityFixture(); fixture.addStatus = errSecDuplicateItem
            fixture.reads = [(errSecItemNotFound, nil), (errSecSuccess, bytes), response]
            if response.0 == errSecSuccess && response.1 == bytes {
                XCTAssertEqual(try subject(fixture).load(create: true).withUnsafeBytes { Data($0) }, bytes)
            } else { XCTAssertThrowsError(try subject(fixture).load(create: true)) }
            XCTAssertEqual(fixture.queries.count, 3); assertNoUI(fixture.queries[2])
            XCTAssertEqual(fixture.queries[2][kSecUseDataProtectionKeychain] as? Bool, true)
            XCTAssertEqual(fixture.insertions.count, 1); XCTAssertEqual(fixture.generations, 0)
            XCTAssertTrue(fixture.deletions.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testCreationRequiresBothNamespacesAbsentAndExplicitRequest() throws {
        let readonly = SecurityFixture(); readonly.reads = [(errSecItemNotFound, nil), (errSecItemNotFound, nil)]
        XCTAssertThrowsError(try subject(readonly).load(create: false))
        XCTAssertEqual(readonly.generations, 0); XCTAssertTrue(readonly.insertions.isEmpty)
        for addStatus in [errSecSuccess, errSecInteractionNotAllowed, errSecDuplicateItem] {
            let fixture = SecurityFixture(); fixture.addStatus = addStatus
            fixture.reads = [(errSecItemNotFound, nil), (errSecItemNotFound, nil)]
            if addStatus == errSecDuplicateItem { fixture.reads.append((errSecSuccess, bytes)) }
            if addStatus == errSecInteractionNotAllowed { XCTAssertThrowsError(try subject(fixture).load(create: true)) }
            else { XCTAssertEqual(try subject(fixture).load(create: true).withUnsafeBytes { Data($0) }, bytes) }
            XCTAssertEqual(fixture.generations, 1); XCTAssertEqual(fixture.insertions.count, 1)
            assertNoUI(fixture.insertions[0]); XCTAssertTrue(fixture.deletions.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.private-cache
    func testExplicitClearDeletesNamespacesWithoutInteraction() {
        let fixture = SecurityFixture(); subject(fixture).clear()
        XCTAssertTrue(fixture.queries.isEmpty); XCTAssertTrue(fixture.insertions.isEmpty)
        fixture.deletions.forEach { assertNoUI($0); XCTAssertNil($0[kSecReturnData]); XCTAssertNil($0[kSecMatchLimit]) }
        XCTAssertEqual(fixture.deletions.count, 2)
        XCTAssertEqual(fixture.deletions[0][kSecUseDataProtectionKeychain] as? Bool, true)
        XCTAssertNil(fixture.deletions[1][kSecUseDataProtectionKeychain])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testRejectedKeyAccessPreservesExistingCiphertextAndOwnerFence() throws {
        let suite = "WidgetKeychainSynthetic-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let owner = String(repeating: "a", count: 64)
        let snapshot = WidgetActiveChatsSnapshot(owner: owner, teamID: nil,
            updatedAt: Date(timeIntervalSince1970: 100), chats: [])
        let ciphertext = try WidgetActiveChatsSnapshotCodec.seal(snapshot, key: SymmetricKey(data: bytes))
        defaults.set(owner, forKey: WidgetActiveChatsStorage.ownerKey)
        defaults.set(ciphertext, forKey: WidgetActiveChatsStorage.snapshotKey)
        let fixture = SecurityFixture()
        fixture.reads = [(errSecInteractionNotAllowed, nil), (errSecInteractionNotAllowed, nil)]
        let storage = WidgetActiveChatsStorage(defaults: defaults,
            loadKey: { create in try self.subject(fixture).load(create: create) }, deleteKey: {})
        XCTAssertNil(storage.load()); XCTAssertThrowsError(try storage.save(snapshot))
        XCTAssertEqual(defaults.data(forKey: WidgetActiveChatsStorage.snapshotKey), ciphertext)
        XCTAssertEqual(defaults.string(forKey: WidgetActiveChatsStorage.ownerKey), owner)
        let other = WidgetActiveChatsSnapshot(owner: String(repeating: "b", count: 64), teamID: nil,
            updatedAt: snapshot.updatedAt, chats: [])
        try storage.save(other) // wrong owner returns before any Keychain operation
        XCTAssertEqual(fixture.queries.count, 2); XCTAssertTrue(fixture.insertions.isEmpty)
        XCTAssertEqual(defaults.data(forKey: WidgetActiveChatsStorage.snapshotKey), ciphertext)
    }
}
