// Specification: specifications/features/apple-tasks-widget/specification.yml
// Assertions: apple-tasks-widget.status-filter, apple-tasks-widget.links, apple-tasks-widget.private-cache

import CryptoKit
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
