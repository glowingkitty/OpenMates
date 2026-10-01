// Timeline and pinned run detail for the Workflow workspace.
// Web source: frontend/packages/ui/src/components/workflows/WorkflowRunHistory.svelte
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.mvp.run-history, workflows.privacy.run-retention

import SwiftUI

struct WorkflowRunTimelineView: View {
    let workflow: WorkflowDetail
    let runs: [WorkflowRunSummary]
    let detail: WorkflowRunDetail?
    let pinnedGraph: WorkflowGraph?
    let loadingDetail: Bool
    let onSelect: (String?) -> Void
    let onOpenEditor: () -> Void
    let onCancel: (String) async -> Void
    let onDelete: (String) async -> Void

    @State private var selectedRunId: String?
    @State private var showCancelConfirmation = false
    @State private var showDeleteConfirmation = false

    private let upcomingId = "__upcoming__"

    private var orderedRuns: [WorkflowRunSummary] {
        runs.sorted { ($0.startedAt ?? 0) > ($1.startedAt ?? 0) }
    }

    private var nextRunAt: Int? {
        guard workflow.enabled, let next = workflow.nextRunAt,
              next > Int(Date().timeIntervalSince1970) else { return nil }
        return next
    }

    private var selected: WorkflowRunSummary? {
        if let selectedRunId, selectedRunId != upcomingId {
            return orderedRuns.first { $0.id == selectedRunId }
        }
        return orderedRuns.first
    }

    private var isUpcoming: Bool {
        nextRunAt != nil && (selectedRunId == upcomingId || orderedRuns.isEmpty)
    }

    private var selectedStatus: String { detail?.status ?? selected?.status ?? "" }
    private var canCancel: Bool { ["queued", "running", "waiting"].contains(selectedStatus) }
    private var canDelete: Bool { ["completed", "failed", "cancelled", "skipped", "skipped_by_user"].contains(selectedStatus) }

    private func tr(_ key: AppStrings.WorkflowRunCopy) -> String {
        AppStrings.workflowRun(key)
    }

    private func statusText(_ status: String) -> AppStrings.WorkflowRunCopy {
        switch status {
        case "completed": return .status_completed
        case "failed": return .status_failed
        case "cancelled": return .status_cancelled
        case "skipped", "skipped_by_user": return .status_skipped
        case "queued": return .status_queued
        case "planned": return .status_planned
        case "running": return .status_running
        case "waiting": return .status_waiting
        case "cancellation_requested": return .status_cancellation_requested
        default: return .status_unavailable
        }
    }

    private func date(_ timestamp: Int?) -> String {
        guard let timestamp else { return tr(.time_unavailable) }
        return Date(timeIntervalSince1970: TimeInterval(timestamp)).formatted(.dateTime.month(.abbreviated).day())
    }

    private func time(_ timestamp: Int?) -> String {
        guard let timestamp else { return "" }
        return Date(timeIntervalSince1970: TimeInterval(timestamp)).formatted(.dateTime.hour().minute())
    }

    private func select(_ runId: String) {
        selectedRunId = runId
        onSelect(runId == upcomingId ? nil : runId)
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Button(action: onOpenEditor) {
                    Icon("back", size: 18)
                }
                .accessibilityIdentifier("workflow-runs-back-to-editor")

                Spacer()
                if isUpcoming, let nextRunAt {
                    Text("\(tr(.run)): \(date(nextRunAt)), \(time(nextRunAt))")
                        .font(.omP.weight(.semibold))
                } else if let selected {
                    Menu {
                        if let nextRunAt {
                            Button("\(tr(.next)): \(date(nextRunAt)), \(time(nextRunAt))") { select(upcomingId) }
                        }
                        ForEach(orderedRuns) { run in
                            Button("\(date(run.startedAt)), \(time(run.startedAt))") { select(run.id) }
                        }
                    } label: {
                        HStack(spacing: 5) {
                            Text("\(tr(.run)): \(date(selected.startedAt)), \(time(selected.startedAt))")
                            Icon("dropdown", size: 14)
                        }
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)
                    }
                    .accessibilityIdentifier("workflow-run-select")
                }
                Spacer()

                if canCancel, let id = selected?.id {
                    Button(tr(.cancel)) { showCancelConfirmation = true }
                        .accessibilityIdentifier("workflow-run-cancel")
                        .confirmationDialog(tr(.cancel_title), isPresented: $showCancelConfirmation) {
                            Button(tr(.cancel), role: .destructive) { Task { await onCancel(id) } }
                        } message: { Text(tr(.cancel_explanation)) }
                }
                if let id = selected?.id {
                    Button { showDeleteConfirmation = true } label: { Icon("delete", size: 17) }
                        .disabled(!canDelete)
                        .accessibilityIdentifier("workflow-delete-run")
                        .confirmationDialog(AppStrings.workflowBuilder(.delete_run), isPresented: $showDeleteConfirmation) {
                            Button(AppStrings.workflowBuilder(.delete_run), role: .destructive) { Task { await onDelete(id) } }
                        }
                }
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color.fontSecondary)
            .padding(.horizontal, 16)
            .frame(height: 45)

            if nextRunAt != nil || !orderedRuns.isEmpty {
                ScrollView(.horizontal) {
                    HStack(spacing: 0) {
                        if let nextRunAt {
                            marker(id: upcomingId, timestamp: nextRunAt, status: "next", selected: isUpcoming)
                        }
                        ForEach(orderedRuns) { run in
                            marker(id: run.id, timestamp: run.startedAt, status: run.status,
                                   selected: !isUpcoming && selected?.id == run.id)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, 13)
                }
                .background(Color.grey10)
                .accessibilityIdentifier("workflow-run-timeline")
            } else {
                Text(tr(.empty))
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.vertical, 32)
                    .accessibilityIdentifier("workflow-runs-empty")
            }

            Group {
                if isUpcoming, let nextRunAt {
                    Label("\(tr(.next)) \(date(nextRunAt)), \(time(nextRunAt))", systemImage: "clock")
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.top, 16)
                    WorkflowGraphView(graph: workflow.graph, readOnly: true)
                        .accessibilityIdentifier("workflow-upcoming-run-graph")
                } else if loadingDetail {
                    Text(tr(.loading))
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(32)
                        .accessibilityIdentifier("workflow-run-loading")
                } else if let detail {
                    if !detail.contentAvailable {
                        Text(tr(.content_unavailable))
                            .font(.omP)
                            .foregroundStyle(Color.fontSecondary)
                            .padding(16)
                            .accessibilityIdentifier("workflow-run-content-unavailable")
                    }
                    if let pinnedGraph {
                        VStack {
                            WorkflowGraphView(graph: pinnedGraph, readOnly: true, nodeRuns: detail.nodeRuns)
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("workflow-run-graph")
                    }
                    if detail.errorSummary != nil {
                        Text(tr(.execution_failed))
                            .font(.omP)
                            .foregroundStyle(Color.error)
                    }
                }
            }
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: 960)
        .frame(maxWidth: .infinity)
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-runs")
    }

    private func marker(id: String, timestamp: Int?, status: String, selected: Bool) -> some View {
        Button { select(id) } label: {
            VStack(spacing: 2) {
                HStack(spacing: 3) {
                    Icon(status == "completed" ? "check" : status == "failed" ? "warning" : "lucide-clock", size: 13)
                    Text(tr(status == "next" ? .next : statusText(status)))
                        .lineLimit(1)
                }
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(status == "next" ? Color.fontButton : selected ? Color(hex: 0x4867CD) : Color.fontSecondary)
                .padding(.horizontal, 6)
                .frame(minHeight: 24)
                .background(status == "next" ? Color(hex: 0x4867CD) : Color.clear, in: Capsule())

                Text(date(timestamp))
                Text(time(timestamp))
            }
            .font(.omSmall.weight(.semibold))
            .foregroundStyle(selected ? Color(hex: 0x4867CD) : Color.fontSecondary)
            .frame(width: 112, height: 100, alignment: .top)
            .overlay(alignment: .bottom) {
                Rectangle().fill(selected ? Color(hex: 0x4867CD) : Color.fontPrimary)
                    .frame(width: selected ? 2 : 1, height: 24)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(id == upcomingId ? "workflow-next-run-marker" : "workflow-run-marker")
    }
}
