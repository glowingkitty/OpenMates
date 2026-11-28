// Project Overview Checks section: the Project's Checks as cards (status, stale badge,
// per-group chips, last run), a detail sheet with the sources, "Run" and Confirm/Reject
// for pending human sources. Renders nothing while the Project has no Check; load and
// action failures are shown with the web's messages and a retry.
// Specification: specifications/features/checks/specification.yml
// Assertions: checks.surface.semantic-parity, checks.human.explicit-confirmation
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/projects/ProjectChecksPanel.svelte
//          frontend/packages/ui/src/components/embeds/checks/CheckEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/checks/CheckEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/checks/CheckStatusBadge.svelte
// CSS:     ProjectChecksPanel.svelte <style>: .project-checks, .check-grid, .check-error
//          CheckStatusBadge.svelte <style>: .cb, .cb-passed, .cb-failed
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import SwiftUI

extension AppStrings {
    private static func check(_ suffix: String) -> String { localized("checks.\(suffix)") }
    static var checksProjectHeading: String { check("project.heading") }
    static var checksProjectLoadError: String { check("project.load_error") }
    static var checksProjectActionError: String { check("project.action_error") }
    static var checksProjectRetry: String { check("project.retry") }
    static var checksStale: String { check("stale") }
    static var checksLastRun: String { check("last_run") }
    static var checksNoRun: String { check("no_run") }
    static var checksSources: String { check("sources") }
    static var checksRun: String { check("action.run") }
    static var checksHumanConfirm: String { check("human.confirm") }
    static var checksHumanReject: String { check("human.reject") }
    static var checksHumanPending: String { check("result.human_pending") }
    static var checksResultPending: String { check("result.pending") }
    static var checksTitle: String { check("title") }
    static func checksStatus(_ status: String) -> String { check("status.\(status)") }
    static func checksKind(_ group: String) -> String { check("kind.\(group)") }
    static func checksRole(_ role: String) -> String { check("role.\(role)") }
}

struct ProjectChecksPanel: View {
    @ObservedObject var model: ProjectChecksModel
    var width: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            if model.loadFailed {
                VStack(alignment: .leading, spacing: .spacing4) {
                    Text(AppStrings.checksProjectLoadError).foregroundStyle(Color.error)
                    Button(AppStrings.checksProjectRetry) { Task { await model.load() } }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("project-checks-retry")
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("project-checks-error")
            } else if !model.items.isEmpty {
                VStack(alignment: .leading, spacing: .spacing8) {
                    Text(AppStrings.checksProjectHeading).font(.omH3).foregroundStyle(Color.fontPrimary)
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: min(300, max(1, width - 32)), maximum: 300),
                                                 spacing: .spacing8)],
                              alignment: .leading, spacing: .spacing8) {
                        ForEach(model.items) { check in
                            Button { model.open(check.id) } label: { ProjectCheckCard(check: check) }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("project-check-\(check.id)")
                        }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("project-checks-section")
            }
            if model.actionFailed, model.openedId == nil {
                actionError
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task { await model.load() }
    }

    var actionError: some View {
        Text(AppStrings.checksProjectActionError)
            .font(.omSmall).foregroundStyle(Color.error)
            .accessibilityIdentifier("project-checks-action-error")
    }
}

/// The detail sheet; mounted by the Projects workspace above its content so it covers the page.
struct ProjectCheckDetailSheet: View {
    @ObservedObject var model: ProjectChecksModel

    var body: some View {
        OMSheet(isPresented: Binding(get: { model.openedId != nil }, set: { if !$0 { model.close() } }),
                title: model.opened?.title ?? AppStrings.checksTitle) {
            if let check = model.opened { detail(check) }
        }
    }

    private func detail(_ check: ProjectCheck) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                HStack(spacing: .spacing4) {
                    ProjectCheckStatusBadge(status: check.aggregate, label: AppStrings.checksStatus(check.aggregate))
                        .accessibilityIdentifier("check-fullscreen-status")
                    if check.stale {
                        ProjectCheckStatusBadge(status: "stale", label: AppStrings.checksStale)
                    }
                }
                if let description = check.description, !description.isEmpty {
                    Text(description).font(.omP).foregroundStyle(Color.fontSecondary)
                }
                Button(AppStrings.checksRun) { Task { await model.run(check.id) } }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(model.busy || check.aggregate == "running" || check.aggregate == "queued")
                    .accessibilityIdentifier("check-fullscreen-run")
                if model.actionFailed {
                    Text(AppStrings.checksProjectActionError)
                        .font(.omSmall).foregroundStyle(Color.error)
                        .accessibilityIdentifier("project-checks-action-error")
                }
                Text(AppStrings.checksSources).font(.omH4).foregroundStyle(Color.fontPrimary)
                ForEach(check.sources) { source in sourceRow(check, source) }
            }
            .padding(.vertical, .spacing4)
        }
        .frame(maxHeight: 560)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("check-fullscreen")
    }

    private func sourceRow(_ check: ProjectCheck, _ source: ProjectCheckSource) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing4) {
                Text(source.title).font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            let status = source.result?.status
            ProjectCheckStatusBadge(status: status ?? "queued",
                                    label: status.map(AppStrings.checksStatus) ?? AppStrings.checksResultPending)
                .accessibilityIdentifier("check-source-status-\(source.id)")
            Text("\(AppStrings.checksKind(ProjectCheckGroupSummary.group(of: source.kind))) · \(AppStrings.checksRole(source.role))")
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
            if !source.ref.isEmpty {
                Text(source.ref).font(.omSmall).foregroundStyle(Color.fontSecondary).textSelection(.enabled)
            }
            if let detail = source.result?.detail, !detail.isEmpty {
                Text(detail).font(.omSmall).foregroundStyle(Color.fontPrimary).textSelection(.enabled)
            }
            if source.awaitsHuman {
                HStack(spacing: .spacing4) {
                    Button(AppStrings.checksHumanConfirm) {
                        Task { await model.confirm(check.id, bindingId: source.id, decision: .confirmed) }
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .accessibilityIdentifier("check-source-confirm-\(source.id)")
                    Button(AppStrings.checksHumanReject) {
                        Task { await model.confirm(check.id, bindingId: source.id, decision: .rejected) }
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("check-source-reject-\(source.id)")
                }
                .disabled(model.busy)
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("check-source-\(source.id)")
    }
}

/// Card of one Check (web CheckEmbedPreview details: title, status, stale, chips, last run).
struct ProjectCheckCard: View {
    let check: ProjectCheck

    private var lastRun: String {
        guard let seconds = check.lastRunAt else { return AppStrings.checksNoRun }
        let date = Date(timeIntervalSince1970: TimeInterval(seconds))
        return "\(AppStrings.checksLastRun): \(date.formatted(date: .numeric, time: .shortened))"
    }

    private func chip(_ summary: ProjectCheckGroupSummary) -> String {
        let kind = AppStrings.checksKind(summary.id)
        switch summary.id {
        case "ai": return "\(kind) \(summary.failed > 0 ? "✗" : summary.pending > 0 ? "…" : "✓")"
        case "human":
            return summary.failed > 0 ? "\(kind) ✗" : summary.pending > 0 ? "\(kind) \(AppStrings.checksHumanPending)" : "\(kind) ✓"
        default: return "\(kind) \(summary.passed)/\(summary.total)"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(check.title.isEmpty ? AppStrings.checksTitle : check.title)
                .font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                .lineLimit(2)
                .accessibilityIdentifier("check-preview-title")
            HStack(spacing: .spacing3) {
                ProjectCheckStatusBadge(status: check.aggregate, label: AppStrings.checksStatus(check.aggregate))
                    .accessibilityIdentifier("check-preview-status")
                if check.stale {
                    ProjectCheckStatusBadge(status: "stale", label: AppStrings.checksStale)
                        .accessibilityIdentifier("check-preview-stale")
                }
            }
            FlowChips(items: ProjectCheckGroupSummary.summaries(check).map { (id: $0.id, text: chip($0), state: $0.state) })
            Text(lastRun).font(.omXs).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("check-preview-last-run")
        }
        .padding(.spacing6)
        .frame(maxWidth: 300, minHeight: 200, alignment: .topLeading)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: .radius5))
        .accessibilityElement(children: .contain)
    }
}

private struct FlowChips: View {
    let items: [(id: String, text: String, state: String)]

    var body: some View {
        HStack(spacing: .spacing2) {
            ForEach(items, id: \.id) { item in
                Text(item.text)
                    .font(.omXs).fontWeight(.medium)
                    .foregroundStyle(item.state == "failed" ? Color.error : Color.fontPrimary)
                    .padding(.horizontal, .spacing3).padding(.vertical, .spacing1)
                    .background(Color.grey10, in: Capsule())
                    .accessibilityIdentifier("check-preview-chip-\(item.id)")
            }
        }
    }
}

/// Web CheckStatusBadge: grey pill, code-app colour when passed, error colours when failed.
struct ProjectCheckStatusBadge: View {
    let status: String
    let label: String

    var body: some View {
        let failed = status == "failed" || status == "error"
        Text(label)
            .font(.omSmall).fontWeight(.semibold)
            .foregroundStyle(status == "passed" ? AnyShapeStyle(LinearGradient.appCode)
                             : failed ? AnyShapeStyle(Color.error)
                             : ["waiting_for_confirmation", "stale"].contains(status) ? AnyShapeStyle(Color.fontPrimary)
                             : AnyShapeStyle(Color.fontSecondary))
            .lineLimit(1)
            .padding(.horizontal, .spacing4).padding(.vertical, .spacing1)
            .background(failed ? Color.error.opacity(0.12) : Color.grey10, in: Capsule())
    }
}
