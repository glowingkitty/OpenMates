// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/settings/SettingsTeams.svelte
//         frontend/packages/ui/src/components/settings/account/SettingsStorage.svelte
// CSS: frontend/packages/ui/src/styles/settings.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.cold.discoverable-bounded, storage.cold.shared-team-authorized, storage.surface.semantic-parity
#if DEBUG
import Combine
import CryptoKit
import SwiftUI

// No network, account restoration, persisted keys, billing or deletion. This
// preview uses production summary/notice views and the selection controller.
struct DevStoragePreviewFixture: View {
    @StateObject private var state: DevStoragePreviewState
    init(variant: String) { _state = StateObject(wrappedValue: DevStoragePreviewState(variant: variant)) }
    var body: some View { DevStoragePreviewBody(state: state, controller: state.controller) }
}

private struct DevStoragePreviewBody: View {
    @ObservedObject var state: DevStoragePreviewState
    @ObservedObject var controller: SettingsTeamsController
    var body: some View {
        VStack(spacing: .spacing4) {
            HStack {
                Button("Personal") { Task { await state.personal() } }.accessibilityIdentifier("storage-fixture-personal")
                Button("Owner") { Task { await state.select("owner") } }.accessibilityIdentifier("storage-fixture-owner")
                Button("Admin") { Task { await state.select("admin") } }.accessibilityIdentifier("storage-fixture-admin")
                Button("Member") { Task { await state.select("member") } }.accessibilityIdentifier("storage-fixture-member")
            }.buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
            if state.service.pageSuspended {
                Text("Synthetic page suspended").font(.omSmall).accessibilityIdentifier("storage-fixture-pending-page")
            }
            OMSettingsPage(title: AppStrings.storage) {
                if state.isPersonal {
                    StoragePersonalSummaryView(value: state.personalOverview)
                } else if let team = controller.selected {
                    Text(team.name).font(.omP.weight(.bold)).accessibilityIdentifier("storage-fixture-selected-team")
                    if let value = controller.storage {
                        TeamStorageStatusView(value: value, noticeController: controller.storageNotice)
                    } else if !team.canViewBilling {
                        // A fixture label only; restricted roles render no storage controls.
                        Text("Member storage is restricted").font(.omP).accessibilityIdentifier("storage-fixture-restricted")
                    } else if controller.storageLoading {
                        OMSettingsInfoBox(message: AppStrings.storageLoading)
                    }
                }
            }
            // Real settings navigation recreates its page for each team route.
            // Mirror that parent scroll reset when fixture selectors change it.
            .id(state.isPersonal ? "personal" : controller.selectedID ?? "none")
        }
        .task { await state.start() }
    }
}

@MainActor private final class DevStoragePreviewState: ObservableObject {
    @Published var isPersonal: Bool
    let service: DevStoragePreviewService
    let controller: SettingsTeamsController
    private var pageObservation: AnyCancellable?
    let personalOverview = StorageOverview(totalBytes: 1_073_741_824, totalFiles: 0, freeBytes: 1_073_741_824,
        billableGb: 0, creditsPerGbPerWeek: 3, weeklyCostCredits: 0, nextBillingDate: nil, lastBilledAt: nil,
        breakdown: [], logicalS3Bytes: 1_073_741_824, meteringCategories: [:],
        meteringSourceVersion: "synthetic", meteringPolicyVersion: "synthetic", measurementAt: 1_800_000_000)
    init(variant: String) {
        isPersonal = variant == "default" || variant == "personal"
        service = DevStoragePreviewService(variant: variant)
        let epoch = UUID()
        controller = SettingsTeamsController(service: service, environment: TeamWorkspaceEnvironment(
            currentAccountID: { "storage-preview-account" }, scopeGeneration: { epoch }, serverProfile: { .development }))
        pageObservation = service.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
    }
    func start() async {
        await controller.load(accountID: "storage-preview-account")
        if !isPersonal { await controller.select("owner") }
    }
    func personal() async {
        await controller.select(nil); isPersonal = true; service.releasePage()
    }
    func select(_ id: String) async {
        isPersonal = false
        await controller.select(id)
        service.releasePage()
    }
}

@MainActor private final class DevStoragePreviewService: ObservableObject, SettingsTeamsServing {
    let variant: String
    @Published var pageSuspended = false
    private var pendingPage: CheckedContinuation<StorageNotice, Never>?
    private let teams: [TeamWorkspaceTeam] = [(TeamWorkspaceRole.owner, "owner", "Owner Team"), (TeamWorkspaceRole.admin, "admin", "Admin Team"), (TeamWorkspaceRole.member, "member", "Member Team")].map { role, id, name in
        TeamWorkspaceTeam(id: id, name: name, description: "", role: role, status: "active", profileImageMetadata: .generated,
            zeroBalance: 0, createdAt: 1, updatedAt: 1, key: SymmetricKey(size: .bits256))
    }
    init(variant: String) { self.variant = variant }
    private var status: StorageBillingStatus {
        switch variant { case "disabled": .disabledPendingValidation; case "manual-review": .manualReview
        case "unpaid", "selection-fencing": .unpaid; default: .current }
    }
    private var warned: Bool { status == .unpaid || status == .manualReview }
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { try await fence.check(); return teams }
    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails {
        try await fence.check(); return SettingsTeamDetails(credits: 0, memoryCount: 0, balanceVersion: 1)
    }
    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam { throw SettingsTeamsError.permissionDenied }
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool { throw SettingsTeamsError.permissionDenied }
    func storage(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> TeamStorageOverview {
        try await fence.check(); guard team.canViewBilling else { throw SettingsTeamsError.permissionDenied }
        return TeamStorageOverview(totalBytes: 1_073_741_825, legacyUploadBytes: 0, logicalS3Bytes: 1_073_741_825,
            categories: [:], measurementAt: 1_800_000_000, meteringSourceVersion: "synthetic", meteringPolicyVersion: "synthetic",
            freeBytes: 1_073_741_824, creditsPerStartedExcessGibPerWeek: 3, billableGib: 1, weeklyCostCredits: 3,
            billingStatus: status, billing: StorageBillingState(status: status, warningCount: warned ? 4 : 0,
                deadlineAt: warned ? 1_800_000_000 : nil, expiryDue: false, expiryEnabled: true,
                outstandingCredits: warned ? 3 : 0, invoices: [], hasMoreInvoices: false, affectedUnits: [], hasMoreAffectedUnits: false))
    }
    func storageNotice(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence, after: String?) async throws -> StorageNotice {
        try await fence.check(); guard team.canViewBilling else { throw SettingsTeamsError.permissionDenied }
        if after != nil, variant == "selection-fencing" {
            pageSuspended = true
            return await withCheckedContinuation { pendingPage = $0 }
        }
        return page(more: after != nil)
    }
    func releasePage() {
        let pending = pendingPage; pendingPage = nil; pageSuspended = false
        pending?.resume(returning: page(more: true))
    }
    private func page(more: Bool) -> StorageNotice {
        let id = String(repeating: more ? "b" : "a", count: 64)
        return StorageNotice(episodeId: warned ? "synthetic-episode" : nil, warningCount: warned ? 4 : 0,
            deadlineAt: warned ? 1_800_000_000 : nil, manualReview: status == .manualReview, unitSelectionHash: "synthetic-selection",
            units: warned ? [StorageAffectedUnit(unitId: id, kind: more ? .artifactHistory : .coldChat,
                resourceId: more ? "synthetic-artifact" : "synthetic-chat", oldestAt: 1_700_000_000, bytes: 1024, fingerprint: "synthetic")] : [],
            hasMore: warned && !more, nextAfterUnitId: warned && !more ? id : nil)
    }
}
#endif
