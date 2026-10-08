// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/settings/account/SettingsStorage.svelte
//         frontend/packages/ui/src/components/settings/SettingsTeams.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsProgressBar.svelte
// CSS: frontend/packages/ui/src/styles/settings.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.cold.discoverable-bounded, storage.surface.semantic-parity
import SwiftUI

@MainActor
enum StorageDisplay {
    private static let decimalFormatter: NumberFormatter = {
        let formatter = NumberFormatter(); formatter.locale = .autoupdatingCurrent
        formatter.minimumFractionDigits = 1; formatter.maximumFractionDigits = 1
        return formatter
    }()
    static func bytes(_ value: Int) -> String {
        guard value > 0 else { return "0 B" }
        let units = ["B", "KiB", "MiB", "GiB", "TiB"]
        let index = min(4, Int(log2(Double(value)) / 10))
        let amount = Double(value) / pow(1024, Double(index))
        let formatted = index < 2 ? String(Int(amount.rounded())) : decimalFormatter.string(from: NSNumber(value: amount)) ?? String(amount)
        return "\(formatted) \(units[index])"
    }
    private static let utcFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = .autoupdatingCurrent
        formatter.dateStyle = .medium; formatter.timeStyle = .short
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        return formatter
    }()
    static func utc(_ seconds: Int) -> String {
        utcFormatter.string(from: Date(timeIntervalSince1970: Double(seconds))) + " UTC"
    }
}

// Reused unchanged by the real account page and the isolated preview.
struct StoragePersonalSummaryView: View {
    let value: StorageOverview
    var body: some View {
        Group {
            OMSettingsCard {
                OMSettingsProgressBar(value: min(100, Double(value.totalBytes) / Double(max(value.freeBytes, 1)) * 100), warning: value.totalBytes > value.freeBytes)
                OMSettingsDetailRow(label: AppStrings.storage, value: StorageDisplay.bytes(value.totalBytes), highlight: true)
                OMSettingsDetailRow(label: AppStrings.storageFreeTier, value: StorageDisplay.bytes(value.freeBytes))
                    .accessibilityIdentifier("personal-storage-free-tier")
                if let measuredAt = value.measurementAt {
                    OMSettingsDetailRow(label: AppStrings.storageMeasuredAt, value: StorageDisplay.utc(measuredAt))
                }
            }
            OMSettingsInfoBox(message: AppStrings.storagePersonalPolicy, identifier: "storage-pricing-policy")
            if value.totalBytes <= value.freeBytes {
                OMSettingsInfoBox(kind: .success, message: AppStrings.storageWithinFreeTier)
            } else {
                OMSettingsCard {
                    OMSettingsDetailRow(label: AppStrings.storageBillable, value: "\(Int(value.billableGb)) GiB")
                    OMSettingsDetailRow(label: AppStrings.storageWeeklyCost, value: AppStrings.storageCreditsPerWeek(Int(value.weeklyCostCredits)), highlight: true)
                    if let date = value.nextBillingDate { OMSettingsDetailRow(label: AppStrings.storageNextBilling, value: StorageDisplay.utc(date)) }
                    if let date = value.lastBilledAt { OMSettingsDetailRow(label: AppStrings.storageLastBilled, value: StorageDisplay.utc(date)) }
                }
            }
            if let categories = value.meteringCategories, !categories.isEmpty {
                OMSettingsSectionHeading(title: AppStrings.storageLogicalBreakdown, icon: "storage")
                OMSettingsCard {
                    ForEach(categories.keys.sorted(), id: \.self) { category in
                        if let bytes = categories[category], bytes > 0 {
                            OMSettingsDetailRow(label: AppStrings.storageLogicalCategory(category), value: StorageDisplay.bytes(bytes))
                        }
                    }
                }
            }

        }
    }
}

struct StorageNoticeView: View {
    @ObservedObject var controller: StorageNoticeController
    var team = false
    var body: some View {
        Group {
            OMSettingsSectionHeading(title: AppStrings.storageNoticeHeading(team: team), icon: "storage")
            if let notice = controller.notice, notice.episodeId != nil {
                OMSettingsInfoBox(kind: .warning, message: AppStrings.storageNoticePolicy(team: team), identifier: team ? "team-storage-active-notice" : "storage-active-notice")
                OMSettingsCard {
                    OMSettingsDetailRow(label: AppStrings.storageWarnings, value: "\(notice.warningCount) / 4")
                        .accessibilityIdentifier("storage-notice-warning-count")
                    if let deadline = notice.deadlineAt {
                        OMSettingsDetailRow(label: AppStrings.storageDeadline, value: StorageDisplay.utc(deadline))
                            .accessibilityIdentifier("storage-notice-deadline")
                    }
                }
                if notice.manualReview {
                    OMSettingsInfoBox(kind: .warning, message: AppStrings.storageReview(team: team))
                }
                ForEach(notice.units) { unit in
                    StorageAffectedUnitView(unit: unit)
                }
                if notice.hasMore {
                    Button(AppStrings.storageNoticeMore) { Task { await controller.load(more: true) } }
                        .buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
                        .disabled(controller.loading)
                        .accessibilityIdentifier(team ? "team-storage-load-more" : "storage-load-more")
                }
            } else if controller.notice != nil && !controller.failed {
                OMSettingsInfoBox(message: AppStrings.storageNoticeEmpty(team: team))
            }
            if controller.failed {
                OMSettingsInfoBox(kind: .warning, message: AppStrings.storageNoticeError(team: team))
                Button(AppStrings.retry) { Task { await controller.load(more: controller.notice?.hasMore == true) } }
                    .buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
            } else if controller.loading {
                OMSettingsInfoBox(message: AppStrings.storageLoading)
            }
        }
    }
}

struct StorageAffectedUnitView: View {
    let unit: StorageAffectedUnit
    var body: some View {
        OMSettingsCard {
            OMSettingsDetailRow(label: AppStrings.storageUnitType, value: AppStrings.storageUnitLabel(unit.kind.rawValue))
            OMSettingsDetailRow(label: AppStrings.storageUnitOldest, value: StorageDisplay.utc(unit.oldestAt))
            OMSettingsDetailRow(label: AppStrings.storageUnitSize, value: StorageDisplay.bytes(unit.bytes))
        }.accessibilityIdentifier("storage-affected-unit-\(unit.unitId)")
    }
}

struct TeamStorageStatusView: View {
    let value: TeamStorageOverview
    @ObservedObject var noticeController: StorageNoticeController
    var body: some View {
        Group {
            OMSettingsInfoBox(message: AppStrings.teamStoragePolicy, identifier: "team-storage-policy")
            OMSettingsCard {
                OMSettingsDetailRow(label: AppStrings.storage, value: StorageDisplay.bytes(value.totalBytes), highlight: true)
                OMSettingsDetailRow(label: AppStrings.storageMeasuredAt, value: StorageDisplay.utc(value.measurementAt))
                OMSettingsDetailRow(label: AppStrings.teamStorageFreeTier, value: StorageDisplay.bytes(value.freeBytes))
                    .accessibilityIdentifier("team-storage-free-tier")
                OMSettingsDetailRow(label: AppStrings.storageBillable, value: "\(value.billableGib) GiB")
                OMSettingsDetailRow(label: AppStrings.storageWeeklyCost, value: AppStrings.storageCreditsPerWeek(value.weeklyCostCredits))
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("team-storage-summary")
            if !value.categories.isEmpty {
                OMSettingsCard {
                    ForEach(value.categories.keys.sorted(), id: \.self) { category in
                        if let bytes = value.categories[category], bytes > 0 {
                            OMSettingsDetailRow(label: AppStrings.storageLogicalCategory(category), value: StorageDisplay.bytes(bytes))
                        }
                    }
                }
            }
            if value.billingStatus == .disabledPendingValidation {
                OMSettingsInfoBox(message: AppStrings.teamStoragePreview, identifier: "team-storage-preview")
            } else {
                if value.billingStatus == .unpaid {
                    OMSettingsInfoBox(kind: .warning, message: AppStrings.teamStoragePaymentDue, identifier: "team-storage-payment-due")
                } else if value.billingStatus == .manualReview {
                    OMSettingsInfoBox(kind: .warning, message: AppStrings.storageReview(team: true), identifier: "team-storage-manual-review")
                }
                OMSettingsCard {
                    OMSettingsDetailRow(label: AppStrings.storageOutstanding, value: String(value.billing.outstandingCredits))
                    OMSettingsDetailRow(label: AppStrings.storageWarnings, value: "\(value.billing.warningCount) / 4")
                    if let deadline = value.billing.deadlineAt {
                        OMSettingsDetailRow(label: AppStrings.storageDeadline, value: StorageDisplay.utc(deadline))
                    }
                }
                if value.billing.expiryDue {
                    OMSettingsInfoBox(kind: .warning, message: AppStrings.storageExpiryDue)
                }
                if value.billing.expiryEnabled == false {
                    OMSettingsInfoBox(message: AppStrings.storageExpiryDisabled)
                }
                ForEach(value.billing.invoices) { invoice in
                    OMSettingsCard {
                        OMSettingsDetailRow(label: AppStrings.storageInvoicePeriod, value: StorageDisplay.utc(invoice.periodStartAt))
                        OMSettingsDetailRow(label: AppStrings.storage, value: StorageDisplay.bytes(invoice.measuredBytes))
                        OMSettingsDetailRow(label: AppStrings.credits, value: String(invoice.creditsDue))
                        OMSettingsDetailRow(label: AppStrings.storageInvoiceStatus, value: AppStrings.storageInvoiceState(invoice.state))
                    }
                }
                if value.billing.hasMoreInvoices == true {
                    OMSettingsInfoBox(message: AppStrings.storageMoreInvoices)
                }
                StorageNoticeView(controller: noticeController, team: true)
                // The summary's first bounded set remains visible if notice paging
                // is unavailable; never turn a partial list into deletion authority.
                if noticeController.notice == nil && noticeController.failed {
                    ForEach(value.billing.affectedUnits) { StorageAffectedUnitView(unit: $0) }
                    if value.billing.hasMoreAffectedUnits == true {
                        OMSettingsInfoBox(message: AppStrings.storageMoreUnits)
                    }
                }
            }
        }
    }
}
