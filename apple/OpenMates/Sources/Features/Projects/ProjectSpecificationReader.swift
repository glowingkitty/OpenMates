// Specification reader: the opened revision's document (summary, Outcome, scope,
// assumptions, design decisions, linked Specifications, chapters with requirements and
// their proof, user flows, edge cases and models), the status strip, revision history and
// the Approve action. Approval names exactly the viewed revision and its content hash and
// asks for confirmation first; older revisions are read-only.
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.revision.exact-approval, contracts.ui.human-readable-default, contracts.surface.semantic-parity
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/specifications/SpecificationEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/specifications/SpecificationRevisionPanel.svelte
// CSS:     SpecificationEmbedFullscreen.svelte <style>: .spec-document, .major-section, .requirement, .proof-detail
//          SpecificationRevisionPanel.svelte <style>: .status-strip, .revisions, .marker, .approval, .confirm
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import SwiftUI

/// Mounted by the Projects workspace above its content so it covers the page.
struct ProjectSpecificationReader: View {
    @ObservedObject var model: ProjectSpecificationsModel

    var body: some View {
        OMSheet(isPresented: Binding(get: { model.opened != nil }, set: { if !$0 { model.close() } }),
                title: model.opened?.document.title ?? AppStrings.specificationsProjectHeading) {
            if let opened = model.opened {
                ScrollView {
                    VStack(alignment: .leading, spacing: .spacing10) {
                        Text(AppStrings.specificationsSubtitle(category: opened.document.category,
                                                               project: opened.document.project))
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        if !opened.document.role.isEmpty {
                            Text(AppStrings.specificationsRole(opened.document.role))
                                .font(.omXs).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                                .padding(.horizontal, .spacing4).padding(.vertical, .spacing1)
                                .background(Color.grey10, in: Capsule())
                                .accessibilityIdentifier("spec-role")
                        }
                        if !opened.document.summary.isEmpty {
                            Text(opened.document.summary).font(.omP).foregroundStyle(Color.fontPrimary)
                        }
                        ProjectSpecificationRevisionPanel(model: model, opened: opened)
                        ProjectSpecificationDocumentView(document: opened.document)
                    }
                    .padding(.vertical, .spacing4)
                }
                .frame(maxHeight: 620)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("specification-fullscreen")
            }
        }
    }
}

/// Web SpecificationRevisionPanel: status strip, read-only note, revisions, approval.
struct ProjectSpecificationRevisionPanel: View {
    @ObservedObject var model: ProjectSpecificationsModel
    let opened: ProjectSpecificationOpened
    @State private var confirming = false

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            statusStrip
            if !opened.isCurrent {
                Text(AppStrings.specificationsRevisionsReadOnly).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("specification-read-only")
            }
            Text(AppStrings.specificationsRevisionsHeading).font(.omH4).foregroundStyle(Color.fontPrimary)
            if opened.revisions.isEmpty {
                Text(AppStrings.specificationsRevisionsEmpty).font(.omSmall).foregroundStyle(Color.fontSecondary)
            } else {
                VStack(alignment: .leading, spacing: .spacing3) {
                    ForEach(opened.sortedRevisions) { revision in revisionRow(revision) }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("specification-revisions")
            }
            approval
            if model.actionFailed {
                Text(AppStrings.specificationsProjectActionError).font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("project-specifications-action-error")
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius5))
        .onChange(of: opened.viewedRevisionId) { _, _ in confirming = false }
    }

    private var statusStrip: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack(spacing: .spacing4) {
                ProjectSpecificationBadge(status: opened.approvalState)
                if let viewed = opened.viewed {
                    Text(AppStrings.specificationsRevision(viewed.number)).font(.omSmall).fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                        .accessibilityIdentifier("specification-viewed-revision")
                }
            }
            if opened.approvalState == "approved", let at = opened.approvedAt {
                Text(AppStrings.specificationsApprovedAt(AppStrings.specificationsDate(at)))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            if opened.approvalState == "stale", let approved = opened.approvedRevision {
                Text(AppStrings.specificationsApprovalStale(approved.number))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("specification-status-strip")
        .accessibilityValue(opened.approvalState)
    }

    private func revisionRow(_ revision: ProjectSpecificationRevision) -> some View {
        let viewing = revision.id == opened.viewedRevisionId
        return Button { Task { await model.selectRevision(revision.id) } } label: {
            VStack(alignment: .leading, spacing: .spacing1) {
                HStack(spacing: .spacing3) {
                    Text(AppStrings.specificationsRevision(revision.number)).font(.omSmall).fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                    if revision.id == opened.currentRevisionId { marker(AppStrings.specificationsRevisionsCurrent, approved: false) }
                    if revision.id == opened.approvedRevisionId { marker(AppStrings.specificationsRevisionsApproved, approved: true) }
                    if viewing { marker(AppStrings.specificationsRevisionsViewing, approved: false) }
                    Spacer(minLength: 0)
                }
                if revision.createdAt > 0 {
                    Text(AppStrings.specificationsDate(revision.createdAt)).font(.omXs).foregroundStyle(Color.fontSecondary)
                }
                if !revision.summary.isEmpty {
                    Text(revision.summary).font(.omXs).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.leading)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(viewing ? Color.grey0 : Color.clear, in: RoundedRectangle(cornerRadius: .radius3))
            .overlay(RoundedRectangle(cornerRadius: .radius3).stroke(viewing ? Color.grey30 : Color.grey20, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .disabled(model.busy)
        .accessibilityLabel(AppStrings.specificationsRevisionSelect(revision.number))
        .accessibilityIdentifier("specification-revision-\(revision.id)")
    }

    private func marker(_ text: String, approved: Bool) -> some View {
        Text(text).font(.omXs).fontWeight(.semibold)
            .foregroundStyle(approved ? Color.fontButton : Color.fontSecondary)
            .padding(.horizontal, .spacing3).padding(.vertical, .spacing1)
            .background(approved ? Color.chatRainbowGreen : Color.grey20, in: Capsule())
    }

    @ViewBuilder private var approval: some View {
        if confirming, let viewed = opened.viewed {
            VStack(alignment: .leading, spacing: .spacing4) {
                Text(AppStrings.specificationsApproveConfirmTitle(viewed.number)).font(.omP).fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                Text(AppStrings.specificationsApproveConfirmBody).font(.omSmall).foregroundStyle(Color.fontSecondary)
                HStack(spacing: .spacing4) {
                    Button(AppStrings.specificationsApproveConfirm) {
                        confirming = false
                        Task { await model.approveViewed() }
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .accessibilityIdentifier("specification-approve-confirm-button")
                    Button(AppStrings.specificationsApproveCancel) { confirming = false }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("specification-approve-cancel")
                }
            }
            .padding(.spacing6)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("specification-approve-confirm")
        } else {
            VStack(alignment: .leading, spacing: .spacing3) {
                Button(AppStrings.specificationsApprove) { confirming = true }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(!opened.canApprove || model.busy)
                    .accessibilityIdentifier("specification-approve")
                if opened.isApproved {
                    Text(AppStrings.specificationsAlreadyApproved).font(.omSmall).foregroundStyle(Color.fontSecondary)
                } else if !opened.isCurrent {
                    Text(AppStrings.specificationsOnlyCurrent).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
            }
        }
    }
}

/// The readable document (web `.spec-document` sections after the revision panel).
struct ProjectSpecificationDocumentView: View {
    let document: ProjectSpecificationDocument

    private func heading(_ key: String) -> some View {
        Text(AppStrings.specificationsFullscreen(key)).font(.omH3).foregroundStyle(Color.fontPrimary)
    }

    private func bullets(_ items: [String], testId: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                Text("• \(item)").font(.omP).foregroundStyle(Color.fontPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier(testId ?? "")
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing10) {
            section {
                heading("outcome")
                Text(document.outcome).font(.omP).foregroundStyle(Color.fontPrimary)
            }
            section {
                heading("scope")
                Text(AppStrings.specificationsFullscreen("included")).font(.omH4).foregroundStyle(Color.fontPrimary)
                bullets(document.scopeIncluded)
                Text(AppStrings.specificationsFullscreen("excluded")).font(.omH4).foregroundStyle(Color.fontPrimary)
                bullets(document.scopeExcluded)
            }
            if !document.assumptions.isEmpty {
                section {
                    heading("assumptions")
                    Text(AppStrings.specificationsFullscreen("assumptions_hint")).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    bullets(document.assumptions, testId: "spec-assumption")
                }
                .accessibilityIdentifier("spec-assumptions")
            }
            if !document.designDecisions.isEmpty {
                section {
                    heading("design_decisions")
                    bullets(document.designDecisions)
                }
                .accessibilityIdentifier("spec-design-decisions")
            }
            if !document.related.isEmpty {
                section {
                    heading("related")
                    ForEach(Array(document.related.enumerated()), id: \.offset) { _, link in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(link.title).font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                            if !link.role.isEmpty {
                                Text(AppStrings.specificationsRole(link.role)).font(.omXs).foregroundStyle(Color.fontSecondary)
                            }
                            if !link.relation.isEmpty {
                                Text(link.relation).font(.omXs).foregroundStyle(Color.fontSecondary)
                            }
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("spec-related-item")
                    }
                }
                .accessibilityIdentifier("spec-related")
            }
            ForEach(document.displayChapters(otherTitle: AppStrings.specificationsFullscreen("other_requirements"))) { chapter in
                chapterView(chapter)
            }
        }
    }

    private func section<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) { content() }
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .contain)
    }

    private func chapterView(_ chapter: ProjectSpecChapter) -> some View {
        let requirements = chapter.requirementIds.compactMap { id in document.requirements.first { $0.id == id } }
        let flows = document.flows.filter { chapter.flowIds.contains($0.id) }
        let models = chapter.modelIds.compactMap { id in document.models.first { $0.id == id } }
        return section {
            if !chapter.title.isEmpty {
                Text(chapter.title).font(.omH3).foregroundStyle(Color.fontPrimary)
            }
            if !chapter.introduction.isEmpty {
                Text(chapter.introduction).font(.omP).foregroundStyle(Color.fontSecondary)
            }
            if !requirements.isEmpty {
                Text(AppStrings.specificationsFullscreen("requirements")).font(.omH4).foregroundStyle(Color.fontPrimary)
                ForEach(requirements) { ProjectSpecRequirementRow(requirement: $0) }
            }
            let userFlows = flows.filter { $0.kind == "user_flow" }
            let edgeCases = flows.filter { $0.kind == "edge_case" }
            if !userFlows.isEmpty {
                Text(AppStrings.specificationsFullscreen("user_flows")).font(.omH4).foregroundStyle(Color.fontPrimary)
                ForEach(userFlows) { ProjectSpecFlowCard(flow: $0) }
            }
            if !edgeCases.isEmpty {
                Text(AppStrings.specificationsFullscreen("edge_cases")).font(.omH4).foregroundStyle(Color.fontPrimary)
                ForEach(edgeCases) { ProjectSpecFlowCard(flow: $0) }
            }
            if !models.isEmpty {
                Text(AppStrings.specificationsFullscreen("models")).font(.omH4).foregroundStyle(Color.fontPrimary)
                ForEach(models) { model in
                    VStack(alignment: .leading, spacing: .spacing2) {
                        Text(model.id).font(.omSmall).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                        if !model.description.isEmpty {
                            Text(model.description).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                        ForEach(Array(model.fields.enumerated()), id: \.offset) { _, field in
                            Text("\(field.name) · \(field.type) — \(field.description)").font(.omXs)
                                .foregroundStyle(Color.fontSecondary)
                        }
                    }
                    .padding(.spacing4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
                }
            }
        }
        .accessibilityIdentifier("spec-chapter")
    }
}

/// One requirement with its proof state and expandable proof / example details.
struct ProjectSpecRequirementRow: View {
    let requirement: ProjectSpecRequirement
    @State private var showProof = false
    @State private var showExample = false

    private var state: String { requirement.proofState ?? "open" }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if !requirement.appliesTo.isEmpty {
                Text("\(AppStrings.specificationsFullscreen("applies_to")) \(requirement.appliesTo.joined(separator: ", "))")
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            HStack(alignment: .top, spacing: .spacing4) {
                ZStack {
                    Circle().stroke(state == "passed" ? Color.chatRainbowGreen : Color.grey30, lineWidth: 2)
                    if state == "passed" {
                        Icon("check", size: 12).foregroundStyle(Color.chatRainbowGreen)
                    }
                }
                .frame(width: 20, height: 20)
                .accessibilityIdentifier("spec-proof-mark")
                .accessibilityValue(state)
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(requirement.statement).font(.omP).foregroundStyle(Color.fontPrimary)
                    Button { showProof.toggle() } label: {
                        HStack(spacing: .spacing3) {
                            Text(AppStrings.specificationsFullscreen(state == "passed" ? "proof_passed"
                                                                     : state == "stale" ? "proof_stale" : "proof_open"))
                                .font(.omXs).foregroundStyle(Color.fontSecondary)
                            Text(requirement.proofTitle ?? AppStrings.specificationsFullscreen("proof_none_title"))
                                .font(.omXs).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                                .padding(.horizontal, .spacing3).padding(.vertical, .spacing1)
                                .background(Color.grey10, in: Capsule())
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("spec-proof")
                    if showProof {
                        Text(requirement.proofExplanation ?? AppStrings.specificationsFullscreen("proof_none_explanation"))
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                    Button { showExample.toggle() } label: {
                        Text(AppStrings.specificationsFullscreen("example_and_id")).font(.omXs)
                            .foregroundStyle(Color.fontSecondary).underline()
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("spec-requirement-details")
                    if showExample {
                        if !requirement.example.isEmpty {
                            Text(requirement.example).font(.omSmall).foregroundStyle(Color.fontPrimary)
                        }
                        Text(requirement.id).font(.omXs).monospaced().foregroundStyle(Color.fontSecondary)
                            .textSelection(.enabled)
                    }
                }
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20, lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("spec-requirement")
    }
}

/// A flow card that expands to its numbered steps (web flow preview + flow fullscreen).
struct ProjectSpecFlowCard: View {
    let flow: ProjectSpecFlow
    @State private var expanded = false

    var body: some View {
        Button { expanded.toggle() } label: {
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(flow.title).font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                let steps = expanded ? flow.steps : Array(flow.steps.prefix(3))
                ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                    Text("\(index + 1). \(step)").font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .multilineTextAlignment(.leading)
                }
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius5))
            .contentShape(RoundedRectangle(cornerRadius: .radius5))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("spec-flow-\(flow.id)")
    }
}
