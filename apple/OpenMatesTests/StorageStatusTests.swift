import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class StorageStatusTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ object: [String: Any]) throws -> T {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
    private func id(_ number: Int) -> String { String(format: "%064x", number) }
    private func page(_ ids: [Int], episode: String = "episode", selection: String = "selection", more: Bool = false) throws -> StorageNotice {
        try decode(StorageNotice.self, ["episode_id": episode, "warning_count": 4, "deadline_at": 1_800_000_000,
            "manual_review": false, "unit_selection_hash": selection,
            "units": ids.map { ["unit_id": id($0), "kind": "cold_chat", "resource_id": "synthetic-chat", "oldest_at": 1, "bytes": 100] },
            "has_more": more, "next_after_unit_id": more ? id(ids.last!) as Any : NSNull()])
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity
    func testLegacyPersonalResponseKeepsOptionalMeteringCompatibility() throws {
        let value = try decode(StorageOverview.self, ["total_bytes": 7, "total_files": 1, "free_bytes": 1_073_741_824,
            "billable_gb": 0, "credits_per_gb_per_week": 3, "weekly_cost_credits": 0, "breakdown": []])
        XCTAssertEqual(value.totalBytes, 7); XCTAssertNil(value.meteringCategories); XCTAssertNil(value.measurementAt)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity
    func testPersonalTotalDoesNotDiscardLogicalBytesOrRecalculateQuote() throws {
        let value = try decode(StorageOverview.self, ["total_bytes": 3_000_000_000, "total_files": 1, "free_bytes": 1_073_741_824,
            "billable_gb": 2, "credits_per_gb_per_week": 3, "weekly_cost_credits": 6, "breakdown": [],
            "logical_s3_bytes": 2_900_000_000, "metering_categories": ["sealed_recovery": 2_900_000_000],
            "measurement_at": 1_800_000_000, "metering_source_version": "fixture", "metering_policy_version": "fixture-policy"])
        XCTAssertEqual(value.totalBytes, 3_000_000_000); XCTAssertEqual(value.logicalS3Bytes, 2_900_000_000)
        XCTAssertEqual(value.weeklyCostCredits, 6); XCTAssertEqual(value.meteringCategories?["sealed_recovery"], 2_900_000_000)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.discoverable-bounded,storage.surface.semantic-parity
    func testExclusiveCursorPagesPreserveCompleteUnitsAndRejectDuplicates() throws {
        let first = try page([1, 2], more: true)
        let second = try page([3, 4])
        let merged = try StorageNoticePaging.merge(second, previous: first, after: id(2), limit: 20)
        XCTAssertEqual(merged.units.map(\.unitId), [1, 2, 3, 4].map(id)); XCTAssertFalse(merged.hasMore)
        XCTAssertThrowsError(try StorageNoticePaging.merge(page([2, 3]), previous: first, after: id(2), limit: 20))
        XCTAssertThrowsError(try StorageNoticePaging.merge(page([5, 4]), previous: first, after: id(2), limit: 20))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.discoverable-bounded
    func testMalformedOversizedOrNonAdvancingPagesFail() throws {
        XCTAssertThrowsError(try StorageNoticePaging.path(base: "/notice", limit: 101, after: nil))
        XCTAssertThrowsError(try StorageNoticePaging.path(base: "/notice", limit: 20, after: String(repeating: "A", count: 64)))
        XCTAssertEqual(try StorageNoticePaging.path(base: "/v1/settings/storage/notice", limit: 20, after: id(2)), "/v1/settings/storage/notice?limit=20&after_unit_id=\(id(2))")
        XCTAssertThrowsError(try StorageNoticePaging.merge(page([1, 2, 3]), previous: nil, after: nil, limit: 2))
        let malformed = try decode(StorageNotice.self, ["warning_count": 0, "manual_review": false, "units": [], "has_more": true])
        XCTAssertThrowsError(try StorageNoticePaging.merge(malformed, previous: nil, after: nil, limit: 20))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
    func testChangedEpisodeOrSelectionCannotMergeWarningScopes() throws {
        let first = try page([1], more: true)
        XCTAssertThrowsError(try StorageNoticePaging.merge(page([2], episode: "new"), previous: first, after: id(1), limit: 50))
        XCTAssertThrowsError(try StorageNoticePaging.merge(page([2], selection: "new"), previous: first, after: id(1), limit: 50))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.surface.semantic-parity
    func testResetDiscardsLateNoticeFromPreviousAccountOrTeam() async throws {
        let controller = StorageNoticeController()
        var continuation: CheckedContinuation<StorageNotice, Error>?
        let loading = Task { await controller.configure(limit: 20) { _ in
            try await withCheckedThrowingContinuation { continuation = $0 }
        } }
        for _ in 0..<100 where continuation == nil { await Task.yield() }
        XCTAssertNotNil(continuation)
        controller.reset()
        continuation?.resume(returning: try page([1]))
        await loading.value
        XCTAssertNil(controller.notice); XCTAssertFalse(controller.loading); XCTAssertFalse(controller.failed)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.discoverable-bounded,storage.surface.semantic-parity
    func testChangedWarningEpisodeRestartsOnlyFirstBoundedPage() async throws {
        let controller = StorageNoticeController()
        let first = try page([1], more: true), changed = try page([2], episode: "new"), refreshed = try page([3], episode: "new")
        var requests: [String?] = []
        await controller.configure(limit: 20) { after in
            requests.append(after)
            switch requests.count { case 1: return first; case 2: return changed; default: return refreshed }
        }
        await controller.load(more: true)
        XCTAssertEqual(requests.count, 3); XCTAssertNil(requests[0]); XCTAssertEqual(requests[1], id(1)); XCTAssertNil(requests[2])
        XCTAssertEqual(controller.notice?.units.map(\.unitId), [id(3)]); XCTAssertFalse(controller.failed)
    }
}

@MainActor
final class TeamStorageStatusTests: XCTestCase {
    private func team(_ id: String = "synthetic-team", role: TeamWorkspaceRole = .owner, updatedAt: Int = 1) -> TeamWorkspaceTeam {
        TeamWorkspaceTeam(id: id, name: "Synthetic team", description: "", role: role, status: "active",
            profileImageMetadata: .generated, zeroBalance: 0, createdAt: 1, updatedAt: updatedAt, key: SymmetricKey(size: .bits256))
    }
    private func summary(_ status: String, total: Int = 1_073_741_825) throws -> Data {
        let units: [[String: Any]] = [["unit_id": String(repeating: "a", count: 64), "kind": "artifact_history",
            "resource_id": "synthetic-artifact", "oldest_at": 1, "bytes": 50, "fingerprint": "fixture"]]
        return try JSONSerialization.data(withJSONObject: ["storage": ["total_bytes": total, "legacy_upload_bytes": 20,
            "logical_s3_bytes": total - 20, "categories": ["embed_versions": total - 20], "measurement_at": 1_800_000_000,
            "metering_source_version": "fixture", "metering_policy_version": "fixture", "free_bytes": 1_073_741_824,
            "credits_per_started_excess_gib_per_week": 3, "billable_gib": 1, "weekly_cost_credits": 3, "billing_status": status,
            "billing": ["status": status, "warning_count": 4, "deadline_at": 1_800_000_000, "expiry_due": true,
                "expiry_enabled": false, "outstanding_credits": 3, "invoices": [["id": "fixture-invoice", "period_start_at": 1,
                    "measured_bytes": total, "credits_due": 3, "state": "unpaid", "policy_version": "fixture"]],
                "has_more_invoices": true, "affected_units": units, "has_more_affected_units": true]]])
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.surface.semantic-parity
    func testEveryTeamRetainsSeparateAllowanceAndAllFourBackendStates() async throws {
        let scope = TeamStorageTestScope()
        let reader = TeamStorageTestReader(team: team())
        for status in ["disabled_pending_validation", "current", "unpaid", "manual_review"] {
            let bytes = try summary(status)
            let service = SettingsTeamsService(reader: reader, transport: { _, path, _, _ in
                XCTAssertEqual(path, "/v1/teams/synthetic-team/storage"); return bytes
            })
            let value = try await service.storage(team: reader.team, fence: scope.fence)
            XCTAssertEqual(value.freeBytes, 1_073_741_824); XCTAssertEqual(value.billingStatus.rawValue, status)
            XCTAssertEqual(value.weeklyCostCredits, 3); XCTAssertEqual(value.totalBytes, 1_073_741_825)
            XCTAssertEqual(value.billing.outstandingCredits, 3); XCTAssertEqual(value.billing.invoices.count, 1)
            XCTAssertTrue(value.billing.hasMoreInvoices == true); XCTAssertTrue(value.billing.hasMoreAffectedUnits == true)
            XCTAssertTrue(value.billing.expiryDue); XCTAssertEqual(value.billing.expiryEnabled, false)
        }
        reader.team = team("other-team")
        let bytes = try summary("current", total: 2_000_000_000)
        let service = SettingsTeamsService(reader: reader, transport: { _, path, _, _ in
            XCTAssertEqual(path, "/v1/teams/other-team/storage"); return bytes
        })
        let other = try await service.storage(team: reader.team, fence: scope.fence)
        XCTAssertEqual(other.freeBytes, 1_073_741_824); XCTAssertEqual(other.totalBytes, 2_000_000_000)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.cold.discoverable-bounded
    func testMembersAndViewersNeverRequestStorageOrNotices() async throws {
        let scope = TeamStorageTestScope()
        var calls = 0
        let service = SettingsTeamsService(transport: { _, _, _, _ in calls += 1; return Data() })
        for role in [TeamWorkspaceRole.member, .viewer] {
            do { _ = try await service.storage(team: team(role: role), fence: scope.fence); XCTFail("Forbidden storage read") }
            catch SettingsTeamsError.permissionDenied { }
            do { _ = try await service.storageNotice(team: team(role: role), fence: scope.fence, after: nil); XCTFail("Forbidden notice read") }
            catch SettingsTeamsError.permissionDenied { }
        }
        XCTAssertEqual(calls, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.cold.discoverable-bounded
    func testAdminNoticeUsesBoundedExclusiveCursorAndRetainsFingerprint() async throws {
        let scope = TeamStorageTestScope()
        let reader = TeamStorageTestReader(team: team(role: .admin))
        let after = String(repeating: "a", count: 64)
        let service = SettingsTeamsService(reader: reader, transport: { _, path, _, _ in
            XCTAssertEqual(path, "/v1/teams/synthetic-team/storage/notice?limit=50&after_unit_id=\(after)")
            return Data(#"{"episode_id":"fixture","warning_count":1,"manual_review":false,"units":[{"unit_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","kind":"upload","resource_id":"fixture-upload","oldest_at":1,"bytes":50,"fingerprint":"fixture-hash"}],"has_more":false}"#.utf8)
        })
        let value = try await service.storageNotice(team: reader.team, fence: scope.fence, after: after)
        XCTAssertEqual(value.units.first?.fingerprint, "fixture-hash"); XCTAssertEqual(reader.calls, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.surface.semantic-parity
    func testRoleRevocationDuringFetchRejectsLateTeamStorage() async throws {
        let scope = TeamStorageTestScope()
        let reader = TeamStorageTestReader(team: team())
        let original = reader.team
        let bytes = try summary("unpaid")
        let service = SettingsTeamsService(reader: reader, transport: { _, _, _, _ in
            reader.team = self.team(role: .member, updatedAt: 2); return bytes
        })
        do { _ = try await service.storage(team: original, fence: scope.fence); XCTFail("Revoked role applied a late response") }
        catch TeamWorkspaceError.staleContext { }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.surface.semantic-parity
    func testAccountEpochChangeRejectsLateTeamStorage() async throws {
        let scope = TeamStorageTestScope()
        let reader = TeamStorageTestReader(team: team())
        let bytes = try summary("current")
        let service = SettingsTeamsService(reader: reader, transport: { _, _, _, _ in scope.epoch = UUID(); return bytes })
        do { _ = try await service.storage(team: reader.team, fence: scope.fence); XCTFail("Old account epoch applied storage") }
        catch TeamWorkspaceError.staleContext { }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity
    func testNumericWalletWinsEncryptedAndLegacyAliasesIncludingZero() async throws {
        let scope = TeamStorageTestScope()
        let service = SettingsTeamsService(transport: { _, path, _, _ in
            path.hasSuffix("billing") ? Data(#"{"billing":{"balance_credits":0,"version":9,"credits":900,"balance":800,"encrypted_balance":"invalid-advisory"}}"#.utf8)
                : Data(#"{"memories":[]}"#.utf8)
        })
        let result = try await service.details(team: team(), fence: scope.fence)
        XCTAssertEqual(result.credits, 0); XCTAssertEqual(result.balanceVersion, 9)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity
    func testLowerVersionOrLegacySnapshotCannotReplaceAuthoritativeWallet() async throws {
        let scope = TeamStorageTestScope()
        var version: Int? = 9
        let service = SettingsTeamsService(transport: { _, path, _, _ in
            if !path.hasSuffix("billing") { return Data(#"{"memories":[]}"#.utf8) }
            var billing: [String: Any] = ["balance_credits": 50]
            if let version { billing["balance_version"] = version }
            return try JSONSerialization.data(withJSONObject: ["billing": billing])
        })
        let first = try await service.details(team: team(), fence: scope.fence)
        XCTAssertEqual(first.balanceVersion, 9)
        version = 8
        do { _ = try await service.details(team: team(), fence: scope.fence); XCTFail("Stale wallet replaced newer version") }
        catch StorageStatusError.staleWallet { }
        version = nil
        do { _ = try await service.details(team: team(), fence: scope.fence); XCTFail("Legacy snapshot replaced versioned wallet") }
        catch StorageStatusError.staleWallet { }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity
    func testMalformedVersionedWalletCannotUseEncryptedFallback() async throws {
        let scope = TeamStorageTestScope()
        let service = SettingsTeamsService(transport: { _, _, _, _ in
            Data(#"{"billing":{"balance_credits":-1,"version":2,"credits":700,"encrypted_balance":"invalid-advisory"}}"#.utf8)
        })
        do { _ = try await service.details(team: team(), fence: scope.fence); XCTFail("Malformed modern wallet accepted") }
        catch TeamWorkspaceError.invalidResponse { }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.surface.semantic-parity
    func testChangingTeamSelectionSuppressesSuspendedStorageResponse() async throws {
        let scope = TeamStorageTestScope()
        let reader = TeamStorageTestReader(team: team())
        let bytes = try summary("unpaid")
        var continuation: CheckedContinuation<Data, Error>?
        let service = SettingsTeamsService(reader: reader, transport: { _, path, _, _ in
            if path.hasSuffix("billing") { return Data(#"{"billing":{"balance_credits":0,"version":1}}"#.utf8) }
            if path.hasSuffix("memories") { return Data(#"{"memories":[]}"#.utf8) }
            return try await withCheckedThrowingContinuation { continuation = $0 }
        })
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: "synthetic-account")
        let request = Task { await controller.select("synthetic-team") }
        for _ in 0..<100 where continuation == nil { await Task.yield() }
        XCTAssertNotNil(continuation)
        await controller.select(nil)
        continuation?.resume(returning: bytes)
        await request.value
        XCTAssertNil(controller.storage); XCTAssertNil(controller.storageNotice.notice)
        XCTAssertFalse(controller.storageLoading); XCTAssertNil(controller.selectedID)
    }
}

@MainActor private final class TeamStorageTestScope {
    var epoch = UUID()
    var environment: TeamWorkspaceEnvironment {
        TeamWorkspaceEnvironment(currentAccountID: { "synthetic-account" }, scopeGeneration: { self.epoch }, serverProfile: { .development })
    }
    var fence: TeamWorkspaceFence { TeamWorkspaceFence(accountID: "synthetic-account", environment: environment) }
}

@MainActor private final class TeamStorageTestReader: TeamWorkspaceServing {
    var team: TeamWorkspaceTeam
    var calls = 0
    init(team: TeamWorkspaceTeam) { self.team = team }
    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { try await fence.check(); return [team] }
    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await fence.check(); calls += 1; return team
    }
}
