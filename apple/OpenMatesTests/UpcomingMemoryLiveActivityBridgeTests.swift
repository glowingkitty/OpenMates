import XCTest
@testable import OpenMates

@MainActor
final class UpcomingMemoryLiveActivityBridgeTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testSnapshotRequiresAccountServerTeamAndRuntimeFenceMatch() {
        let token = UUID()
        let current = scope(account: "disposable-account", server: .development, token: token, team: "disposable-team", epoch: 2)
        let snapshot = SettingsMemoryLiveActivitySnapshot(scope: current, entries: [], revision: 10)
        XCTAssertTrue(UpcomingMemorySnapshotBindingPolicy.accepts(snapshot, currentScope: current, after: 9))
        XCTAssertFalse(UpcomingMemorySnapshotBindingPolicy.accepts(snapshot, currentScope: nil, after: 0))
        let mismatches = [
            scope(account: "other-account", server: .development, token: token, team: "disposable-team", epoch: 2),
            scope(account: "disposable-account", server: .production, token: token, team: "disposable-team", epoch: 2),
            scope(account: "disposable-account", server: .development, token: UUID(), team: "disposable-team", epoch: 2),
            scope(account: "disposable-account", server: .development, token: token, team: "other-team", epoch: 2),
            scope(account: "disposable-account", server: .development, token: token, team: "disposable-team", epoch: 3)
        ]
        for mismatch in mismatches {
            XCTAssertFalse(UpcomingMemorySnapshotBindingPolicy.accepts(snapshot, currentScope: mismatch, after: 0))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testOlderFullReadCannotReplaceNewerMutationReceipt() {
        let current = scope(account: "disposable-account", server: .development, token: UUID(), team: nil, epoch: 0)
        let beforeRead = SettingsMemoryLiveActivitySnapshot.nextRevision()
        let afterMutation = SettingsMemoryLiveActivitySnapshot.nextRevision()
        XCTAssertGreaterThan(afterMutation, beforeRead)
        let stale = SettingsMemoryLiveActivitySnapshot(scope: current, entries: [], revision: beforeRead)
        XCTAssertFalse(UpcomingMemorySnapshotBindingPolicy.accepts(stale, currentScope: current, after: afterMutation))
        let replay = SettingsMemoryLiveActivitySnapshot(scope: current, entries: [], revision: afterMutation)
        XCTAssertFalse(UpcomingMemorySnapshotBindingPolicy.accepts(replay, currentScope: current, after: afterMutation))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testPersistedOwnerSurvivesRuntimeFenceChangeButSeparatesServerAndTeam() {
        let owner = scope(account: "disposable-account", server: .development, token: UUID(), team: "team", epoch: 1)
        let relaunched = scope(account: "disposable-account", server: .development, token: UUID(), team: "team", epoch: 99)
        XCTAssertNotEqual(owner, relaunched)
        XCTAssertEqual(owner.ownerIdentity, relaunched.ownerIdentity)
        XCTAssertNotEqual(owner.ownerIdentity,
                          scope(account: "disposable-account", server: .production, token: UUID(), team: "team", epoch: 1).ownerIdentity)
        XCTAssertNotEqual(owner.ownerIdentity,
                          scope(account: "disposable-account", server: .development, token: UUID(), team: nil, epoch: 1).ownerIdentity)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testRetainedSnapshotExcludesExamplesTitlesNotesAndPrivateValues() {
        let saved = SettingsMemoryEntry(id: "disposable-memory", appId: "events", categoryId: "saved_events",
            key: "Disposable private title", value: "Disposable private record", createdAt: 123, updatedAt: 456,
            version: 2, isExample: false, fields: ["title": .string("Private title"), "notes": .string("Private notes"),
                "embed_id": .string("disposable-embed"), "date_start": .string("2026-10-03T14:00:00+02:00"),
                "status": .string("cancelled"), "completed": .bool(true)])
        let example = SettingsMemoryEntry(id: "example", appId: saved.appId, categoryId: saved.categoryId, key: saved.key,
            value: saved.value, createdAt: 0, updatedAt: 0, version: 0, isExample: true, fields: saved.fields)
        let entries = UpcomingMemorySnapshotBindingPolicy.sanitizedEntries([saved, example])
        XCTAssertEqual(entries.count, 1)
        XCTAssertEqual(entries[0].id, saved.id)
        XCTAssertEqual(entries[0].key, "")
        XCTAssertEqual(entries[0].value, "")
        XCTAssertNil(entries[0].fields["title"])
        XCTAssertNil(entries[0].fields["notes"])
        XCTAssertEqual(entries[0].fields["embed_id"], .string("disposable-embed"))
        XCTAssertEqual(entries[0].fields["status"], .string("cancelled"))
        XCTAssertEqual(entries[0].fields["completed"], .bool(true))
        XCTAssertEqual(entries[0].createdAt, 0)
        XCTAssertEqual(entries[0].updatedAt, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testMutationReceiptCannotRestoreADeletedSiblingFromAnotherService() {
        let owner = scope(account: "disposable-account", server: .development, token: UUID(), team: nil, epoch: 0)
        func entry(_ id: String) -> SettingsMemoryEntry {
            .init(id: id, appId: "events", categoryId: "saved_events", key: "Private title", value: "Private record",
                  createdAt: 0, updatedAt: 0, version: 1, isExample: false, fields: ["embed_id": .string("embed-" + id)])
        }
        let deleted = entry("deleted"), retained = entry("retained")
        let oldServiceEntries = [deleted, retained]
        let remove = SettingsMemoryLiveActivitySnapshot(scope: owner, entries: [retained], revision: 2, change: .removed(deleted.id))
        let current = UpcomingMemorySnapshotBindingPolicy.applying(remove, to: oldServiceEntries)
        let unrelatedSave = SettingsMemoryLiveActivitySnapshot(scope: owner, entries: oldServiceEntries,
                                                               revision: 3, change: .upsert(retained))
        let final = UpcomingMemorySnapshotBindingPolicy.applying(unrelatedSave, to: current)
        XCTAssertEqual(final.map(\.id), [retained.id])
        XCTAssertEqual(final[0].key, "")
        XCTAssertEqual(final[0].value, "")
    }

    private func scope(account: String, server: ServerProfile, token: UUID, team: String?, epoch: UInt64) -> UpcomingMemorySnapshotScope {
        .init(accountID: account, server: server, scope: token, team: .init(epoch: epoch, teamID: team))
    }
}
