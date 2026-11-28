// Project Overview Specifications section: the Project's Specifications as cards (kind,
// status, revision, updated date, requirement count, proof summary) and the empty state.
// Tapping a card opens the reader (ProjectSpecificationReader). Load and action failures
// are shown with the web's messages and a retry.
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.surface.semantic-parity, contracts.ui.human-readable-default
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/projects/ProjectSpecificationsPanel.svelte
//          frontend/packages/ui/src/components/projects/ProjectSpecificationsSection.svelte
//          frontend/packages/ui/src/components/embeds/specifications/SpecificationEmbedPreview.svelte
// CSS:     ProjectSpecificationsSection.svelte <style>: .project-specifications, .spec-grid, .empty
//          SpecificationEmbedPreview.svelte <style>: .spec-card, .badge[data-status], .meta, .proof
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import SwiftUI

extension AppStrings {
    private static func spec(_ suffix: String, _ values: [String: String] = [:]) -> String {
        values.isEmpty ? localized("specifications.\(suffix)")
            : LocalizationManager.shared.text("specifications.\(suffix)", replacements: values)
    }
    static var specificationsProjectHeading: String { spec("project.heading") }
    static var specificationsProjectEmpty: String { spec("project.empty") }
    static var specificationsProjectLoadError: String { spec("project.load_error") }
    static var specificationsProjectActionError: String { spec("project.action_error") }
    static var specificationsProjectRetry: String { spec("project.retry") }
    static func specificationsStatus(_ status: String) -> String { spec("status.\(status)") }
    static func specificationsRevision(_ number: UInt64) -> String { spec("preview.revision", ["number": "\(number)"]) }
    static func specificationsUpdated(_ time: String) -> String { spec("preview.updated", ["time": time]) }
    static func specificationsRequirements(_ count: UInt64) -> String { spec("preview.requirements", ["count": "\(count)"]) }
    static func specificationsProof(passed: UInt64, open: UInt64, stale: UInt64) -> String {
        spec("preview.proof", ["passed": "\(passed)", "open": "\(open)", "stale": "\(stale)"])
    }
    static func specificationsSubtitle(category: String, project: String) -> String {
        project.isEmpty ? spec("fullscreen.subtitle_no_project", ["category": category])
            : spec("fullscreen.subtitle", ["category": category, "project": project])
    }
    static func specificationsFullscreen(_ key: String) -> String { spec("fullscreen.\(key)") }
    static func specificationsRole(_ role: String) -> String { spec("role.\(role)") }
    static var specificationsRevisionsHeading: String { spec("revisions.heading") }
    static var specificationsRevisionsCurrent: String { spec("revisions.current") }
    static var specificationsRevisionsApproved: String { spec("revisions.approved") }
    static var specificationsRevisionsViewing: String { spec("revisions.viewing") }
    static var specificationsRevisionsReadOnly: String { spec("revisions.read_only") }
    static var specificationsRevisionsEmpty: String { spec("revisions.empty") }
    static func specificationsRevisionSelect(_ number: UInt64) -> String { spec("revisions.select", ["number": "\(number)"]) }
    static var specificationsApprove: String { spec("approval.approve") }
    static func specificationsApproveConfirmTitle(_ number: UInt64) -> String {
        spec("approval.confirm_title", ["number": "\(number)"])
    }
    static var specificationsApproveConfirmBody: String { spec("approval.confirm_body") }
    static var specificationsApproveConfirm: String { spec("approval.confirm") }
    static var specificationsApproveCancel: String { spec("approval.cancel") }
    static var specificationsAlreadyApproved: String { spec("approval.already_approved") }
    static var specificationsOnlyCurrent: String { spec("approval.only_current") }
    static func specificationsApprovedAt(_ time: String) -> String { spec("approval.approved_at", ["time": time]) }
    static func specificationsApprovalStale(_ number: UInt64) -> String { spec("approval.stale", ["number": "\(number)"]) }

    /// Medium date of a Unix timestamp, like web `toLocaleDateString(dateStyle: 'medium')`.
    static func specificationsDate(_ seconds: UInt64) -> String {
        seconds == 0 ? "" : Date(timeIntervalSince1970: TimeInterval(seconds)).formatted(date: .abbreviated, time: .omitted)
    }
}

struct ProjectSpecificationsPanel: View {
    @ObservedObject var model: ProjectSpecificationsModel
    var width: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            if model.loadFailed {
                VStack(alignment: .leading, spacing: .spacing4) {
                    Text(AppStrings.specificationsProjectLoadError).foregroundStyle(Color.error)
                    Button(AppStrings.specificationsProjectRetry) { Task { await model.load() } }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("project-specifications-retry")
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("project-specifications-error")
            } else if model.loaded {
                VStack(alignment: .leading, spacing: .spacing8) {
                    Text(AppStrings.specificationsProjectHeading).font(.omH3).foregroundStyle(Color.fontPrimary)
                    if model.items.isEmpty {
                        Text(AppStrings.specificationsProjectEmpty).font(.omP).foregroundStyle(Color.fontSecondary)
                            .accessibilityIdentifier("project-specifications-empty")
                    } else {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: min(300, max(1, width - 32)), maximum: 300),
                                                     spacing: .spacing8)],
                                  alignment: .leading, spacing: .spacing8) {
                            ForEach(model.items) { item in
                                Button { Task { await model.open(item.id) } } label: { ProjectSpecificationCard(item: item) }
                                    .buttonStyle(.plain)
                                    .disabled(model.busy)
                                    .accessibilityIdentifier("project-specification-\(item.id)")
                            }
                        }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("project-specifications-section")
            }
            if model.actionFailed, model.opened == nil {
                Text(AppStrings.specificationsProjectActionError)
                    .font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("project-specifications-action-error")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task { await model.load() }
    }
}

/// Web SpecificationEmbedPreview details: kind + status badge, title, meta row, proof summary.
struct ProjectSpecificationCard: View {
    let item: ProjectSpecificationListItem

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing4) {
                Text(item.kind).font(.omXs).fontWeight(.semibold).foregroundStyle(Color.fontSecondary).lineLimit(1)
                Spacer(minLength: 0)
                ProjectSpecificationBadge(status: item.status)
                    .accessibilityIdentifier("specification-status")
            }
            Text(item.title).font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary).lineLimit(2)
            VStack(alignment: .leading, spacing: .spacing1) {
                if item.revisionNumber > 0 {
                    Text(AppStrings.specificationsRevision(item.revisionNumber))
                        .accessibilityIdentifier("specification-revision")
                }
                if item.updatedAt > 0 {
                    Text(AppStrings.specificationsUpdated(AppStrings.specificationsDate(item.updatedAt)))
                }
                Text(AppStrings.specificationsRequirements(item.requirementCount))
            }
            .font(.omXs).foregroundStyle(Color.fontSecondary)
            Text(AppStrings.specificationsProof(passed: item.proofPassed, open: item.proofOpen, stale: item.proofStale))
                .font(.omXs).fontWeight(.semibold).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("specification-proof-summary")
            Spacer(minLength: 0)
        }
        .padding(.spacing6)
        .frame(maxWidth: 300, minHeight: 200, alignment: .topLeading)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: .radius5))
        .accessibilityElement(children: .contain)
    }
}

/// Web `.badge[data-status]`: approved green, changes-since-approval warning, superseded grey.
struct ProjectSpecificationBadge: View {
    /// "approved", "draft", "superseded" or "stale" (changes since approval).
    let status: String

    var body: some View {
        let label = status == "stale" ? AppStrings.specificationsStatus("changes_since_approval")
            : AppStrings.specificationsStatus(status)
        Text(label)
            .font(.omXs).fontWeight(.semibold)
            .foregroundStyle(status == "approved" || status == "stale" ? Color.fontButton
                             : status == "superseded" ? Color.fontSecondary : Color.fontPrimary)
            .lineLimit(1)
            .padding(.horizontal, .spacing4).padding(.vertical, .spacing1)
            .background(status == "approved" ? Color.chatRainbowGreen : status == "stale" ? Color.warning
                        : status == "superseded" ? Color.grey30 : Color.grey20, in: Capsule())
    }
}
