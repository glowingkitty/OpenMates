// Web counterpart: frontend/packages/ui/src/components/FocusPhaseNotice.svelte
// Specification: specifications/features/focus-modes/specification.yml
// Assertions: focus-modes.phases, focus-modes.history-events, focus-modes.history-side-effects, focus-modes.project-authoring-click
// Specification: specifications/features/rules/specification.yml — rules.transparency.applied-set
// Specification: specifications/features/chats/specification.yml — chats.direction.reviewed-correction
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/AgentContextMessage.svelte
// CSS: .context-message, summary, .rule-guides, .actions — generated small typography, spacing and neutral colors.
// ────────────────────────────────────────────────────────────────────
import SwiftUI

struct FocusPhaseNoticeView: View {
    let event: FocusPhaseEvent
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: .spacing1) {
            Text(L(event.direction == "backward" ? "focus_phases.returned" : "focus_phases.switched"))
            if let path = event.detailPath {
                Button {
                    if let url = URL(string: "openmates://settings/\(path)") {
                        NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
                    }
                } label: { Text(event.phaseTitle).underline().foregroundStyle(Color.buttonPrimary) }
                .buttonStyle(.plain).accessibilityIdentifier("focus-phase-details-link")
            } else { Text(event.phaseTitle) }
        }
        .font(.omSmall).foregroundStyle(Color.fontSecondary)
        .accessibilityIdentifier("focus-phase-notice")
    }
}


/// Quiet, expandable receipts. Reading or expanding one performs no work.
struct AgentContextNoticeView: View {
    let event: AgentContextEvent
    let onAuthoring: ((ProjectAuthoringRecommendation) async throws -> Void)?
    @ObservedObject private var authoring = NativeProjectAuthoringClient.shared
    @State private var expanded = false
    @State private var pending: String?
    @State private var submitted = Set<String>()
    @State private var startFailed = false

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            switch event {
            case .rulesLoaded(_, let guides):
                disclosure(LocalizationManager.shared.text("rules.loaded", replacements: ["count": String(guides.count)]),
                           identifier: "loaded-rules-details")
                if expanded {
                    VStack(alignment: .leading, spacing: .spacing5) {
                        ForEach(guides) { guide in
                            VStack(alignment: .leading, spacing: .spacing3) {
                                Text(guide.title).font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                                Text([L("rules.source_\(guide.source)"), guide.appID, guide.projectID].compactMap { $0 }.joined(separator: " · "))
                                Text("\(L("rules.revision")) \(guide.revision)")
                                    .font(.omSmall.monospaced()).textSelection(.enabled)
                                    .accessibilityIdentifier("applied-rule-revision")
                                instruction(guide.body, identifier: "applied-rule-body")
                            }
                            .padding(.spacing5)
                            .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius4))
                            .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(Color.grey25, lineWidth: 1))
                            .accessibilityIdentifier("applied-rule-guide")
                        }
                    }
                }
            case .directionCorrection(let notice, let instruction, _):
                disclosure(notice, identifier: "direction-correction-details")
                if expanded { self.instruction(instruction, identifier: "direction-correction-instruction") }
            case .authoring(let recommendations):
                Text(L("rules.authoring_suggestions")).font(.omSmall)
                ForEach(recommendations) { recommendation in
                    let job = authoring.jobs[recommendation.id]
                    Button {
                        guard let onAuthoring, pending == nil, !submitted.contains(recommendation.id), !recommendation.isExpired else { return }
                        pending = recommendation.id; startFailed = false
                        Task { @MainActor in
                            defer { pending = nil }
                            do { try await onAuthoring(recommendation); submitted.insert(recommendation.id) }
                            catch { startFailed = true }
                        }
                    } label: {
                        Text(pending == recommendation.id ? L("common.loading") : job != nil || submitted.contains(recommendation.id)
                            ? L("rules.authoring_started") : L(recommendation.localizationKey) + (recommendation.title.map { " · " + $0 } ?? ""))
                            .font(.omSmall).foregroundStyle(Color.fontPrimary)
                            .padding(.vertical, .spacing3).padding(.horizontal, .spacing5)
                            .frame(minHeight: 44)
                            .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius4))
                            .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(Color.grey30, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .disabled(onAuthoring == nil || pending != nil || job != nil || submitted.contains(recommendation.id) || recommendation.isExpired)
                    .accessibilityIdentifier("project-authoring-action")
                    if let job { NativeProjectAuthoringJobView(job: job, client: authoring) }
                }
                if startFailed {
                    Text(L("rules.authoring_failed")).foregroundStyle(Color.error)
                        .accessibilityIdentifier("project-authoring-error")
                }
            }
        }
        .font(.omSmall).foregroundStyle(Color.fontSecondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("agent-context-message")
    }

    private func disclosure(_ label: String, identifier: String) -> some View {
        Button { expanded.toggle() } label: {
            HStack(alignment: .firstTextBaseline, spacing: .spacing3) {
                Icon(expanded ? "up" : "down", size: 12)
                Text(label).multilineTextAlignment(.leading)
            }
            .padding(.vertical, .spacing3).frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain).accessibilityIdentifier(identifier)
        .accessibilityValue(expanded ? L("rules.expanded") : L("rules.collapsed"))
    }

    private func instruction(_ body: String, identifier: String) -> some View {
        ScrollView(.vertical) {
            Text(body).font(.omSmall).foregroundStyle(Color.fontPrimary).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading).padding(.spacing4)
        }
        // Web AgentContextMessage pre has max-height:32rem.
        .frame(maxHeight: 512)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius4))
        .accessibilityIdentifier(identifier)
    }
}
