// Storage metadata shared by personal and owner/admin Team settings.
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.cold.discoverable-bounded, storage.cold.shared-team-authorized, storage.surface.semantic-parity
import Foundation

// The backend owns settlement, delivery and expiry. These values describe state;
// a listed unit or an elapsed deadline is never evidence of completed deletion.
enum StorageBillingStatus: String, Decodable, Equatable {
    case disabledPendingValidation = "disabled_pending_validation"
    case current, unpaid
    case manualReview = "manual_review"
}

struct StorageAffectedUnit: Decodable, Equatable, Identifiable {
    enum Kind: String, Decodable { case upload; case coldChat = "cold_chat"; case artifactHistory = "artifact_history" }
    let unitId: String
    let kind: Kind
    let resourceId: String
    let oldestAt: Int
    let bytes: Int
    let fingerprint: String?
    var id: String { unitId }
}

struct StorageNotice: Decodable, Equatable {
    let episodeId: String?
    let warningCount: Int
    let deadlineAt: Int?
    let manualReview: Bool
    let unitSelectionHash: String?
    var units: [StorageAffectedUnit]
    let hasMore: Bool
    let nextAfterUnitId: String?
}

struct StorageInvoice: Decodable, Equatable, Identifiable {
    let id: String
    let periodStartAt: Int
    let measuredBytes: Int
    let creditsDue: Int
    let state: String
    let policyVersion: String?
}

struct StorageBillingState: Decodable, Equatable {
    let status: StorageBillingStatus
    let warningCount: Int
    let deadlineAt: Int?
    let expiryDue: Bool
    let expiryEnabled: Bool?
    let outstandingCredits: Int
    let invoices: [StorageInvoice]
    let hasMoreInvoices: Bool?
    let affectedUnits: [StorageAffectedUnit]
    let hasMoreAffectedUnits: Bool?
}

struct TeamStorageOverview: Decodable, Equatable {
    let totalBytes: Int
    let legacyUploadBytes: Int
    let logicalS3Bytes: Int
    let categories: [String: Int]
    let measurementAt: Int
    let meteringSourceVersion: String
    let meteringPolicyVersion: String
    let freeBytes: Int
    let creditsPerStartedExcessGibPerWeek: Int
    let billableGib: Int
    let weeklyCostCredits: Int
    let billingStatus: StorageBillingStatus
    let billing: StorageBillingState
}

struct TeamStorageResponse: Decodable { let storage: TeamStorageOverview }

enum StorageStatusError: Error { case invalidPage, changedEpisode, staleWallet }

enum StorageNoticePaging {
    static func isCursor(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }

    static func path(base: String, limit: Int, after: String?) throws -> String {
        guard (1...100).contains(limit), after.map(isCursor) ?? true else { throw StorageStatusError.invalidPage }
        return base + "?limit=\(limit)" + (after.map { "&after_unit_id=\($0)" } ?? "")
    }

    // Exclusive, ascending stable identity pagination. A changed warning episode
    // or selection must restart at the first page rather than mix warned scopes.
    static func merge(_ page: StorageNotice, previous: StorageNotice?, after: String?, limit: Int) throws -> StorageNotice {
        guard page.units.count <= limit, (0...4).contains(page.warningCount),
              page.episodeId != nil || (page.units.isEmpty && !page.hasMore),
              page.units.allSatisfy({ isCursor($0.unitId) && $0.bytes >= 0 && $0.oldestAt >= 0 }),
              !page.hasMore || (page.nextAfterUnitId == page.units.last?.unitId && !page.units.isEmpty),
              page.nextAfterUnitId.map(isCursor) ?? true else { throw StorageStatusError.invalidPage }
        var prior = after
        for unit in page.units {
            if let prior, unit.unitId <= prior { throw StorageStatusError.invalidPage }
            prior = unit.unitId
        }
        if let after {
            guard let previous, previous.hasMore, previous.nextAfterUnitId == after else { throw StorageStatusError.invalidPage }
            guard previous.episodeId == page.episodeId, previous.unitSelectionHash == page.unitSelectionHash else {
                throw StorageStatusError.changedEpisode
            }
            var merged = page
            merged.units = previous.units + page.units
            return merged
        }
        return page
    }
}
