// Timeline and pinned run detail for the Workflow workspace.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/workflows/WorkflowRunHistory.svelte
// CSS: WorkflowRunHistory.svelte .run-marker, .status-pill, .run-detail
// Logic: frontend/packages/ui/src/components/workflows/workflowRunTimeline.ts
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.mvp.run-history, workflows.privacy.run-retention, workflows.execution.lifecycle-visible

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
        runs.sorted { left, right in
            let current: (WorkflowRunSummary) -> Bool = {
                !WorkflowRunSummary.terminalStatuses.contains($0.status) || $0.deliveryState() == .pending
            }
            let leftCurrent = current(left), rightCurrent = current(right)
            if leftCurrent != rightCurrent { return leftCurrent }
            return (leftCurrent ? left.startedAt ?? 0 : left.finishedAt ?? left.startedAt ?? 0)
                > (rightCurrent ? right.startedAt ?? 0 : right.finishedAt ?? right.startedAt ?? 0)
        }
    }

    private var nextRunAt: Int? {
        guard workflow.enabled, let next = workflow.nextRunAt,
              next > Int(Date().timeIntervalSince1970) else { return nil }
        return next
    }

    private var selected: WorkflowRunSummary? {
        guard selectedRunId != upcomingId else { return nil }
        if let selectedRunId {
            return orderedRuns.first { $0.id == selectedRunId } ?? orderedRuns.first
        }
        return orderedRuns.first
    }

    private var isUpcoming: Bool {
        nextRunAt != nil && (selectedRunId == upcomingId || orderedRuns.isEmpty)
    }

    private var selectedStatus: String {
        guard let selected else { return "" }
        guard let detail, detail.id == selected.id else { return selected.status }
        // A later terminal summary must not revive cancellation while an older
        // detail response is hydrating; individual node records stay untouched.
        if WorkflowRunSummary.terminalStatuses.contains(selected.status),
           !WorkflowRunSummary.terminalStatuses.contains(detail.status) { return selected.status }
        return detail.status
    }
    private var canCancel: Bool { !isUpcoming && ["queued", "running", "waiting"].contains(selectedStatus) }
    private var canDelete: Bool { !isUpcoming && ["completed", "failed", "cancelled", "skipped", "skipped_by_user"].contains(selectedStatus) }

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
                if isUpcoming || selected != nil {
                    Menu {
                        if let nextRunAt {
                            Button("\(tr(.next)): \(date(nextRunAt)), \(time(nextRunAt))") { select(upcomingId) }
                        }
                        ForEach(orderedRuns) { run in
                            Button("\(date(run.startedAt)), \(time(run.startedAt))") { select(run.id) }
                        }
                    } label: {
                        HStack(spacing: 5) {
                            Text("\(tr(.run)): \(date(isUpcoming ? nextRunAt : selected?.startedAt)), \(time(isUpcoming ? nextRunAt : selected?.startedAt))")
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
                GeometryReader { timeline in
                ScrollView(.horizontal) {
                    HStack(spacing: 0) {
                        if let nextRunAt {
                            marker(id: upcomingId, timestamp: nextRunAt, status: "next", selected: isUpcoming,
                                   width: timeline.size.width <= 730 ? 96 : 112)
                        }
                        ForEach(orderedRuns) { run in
                            marker(id: run.id, timestamp: run.startedAt, status: run.displayStatus(detail: detail),
                                   selected: !isUpcoming && selected?.id == run.id,
                                   width: timeline.size.width <= 730 ? 96 : 112)
                        }
                    }
                    .padding(.horizontal, 13)
                    .frame(minWidth: timeline.size.width, alignment: timeline.size.width <= 730 ? .leading : .center)
                    .background(alignment: .bottom) {
                        Canvas { context, size in
                            for x in stride(from: CGFloat(0), to: size.width, by: 8) {
                                context.fill(Path(CGRect(x: x, y: 0, width: 1, height: 10)), with: .color(Color.grey40.opacity(0.5)))
                            }
                        }
                        .frame(height: 10)
                        .padding(.bottom, 14)
                        .allowsHitTesting(false)
                    }
                }
                .background(Color.grey10)
                }
                .frame(height: 100)
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
                            WorkflowGraphView(graph: pinnedGraph, readOnly: true, nodeRuns: detail.nodeRuns, executionStatus: selectedStatus)
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
        .frame(maxWidth: .infinity)
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-runs")
    }

    private func marker(id: String, timestamp: Int?, status: String, selected: Bool, width: CGFloat) -> some View {
        Button { select(id) } label: {
            VStack(spacing: 2) {
                HStack(spacing: 3) {
                    Icon(status == "completed" ? "lucide-circle-check" : status == "failed" ? "lucide-triangle-alert" : status == "cancelled" ? "lucide-circle-x" : "lucide-clock", size: status == "completed" ? 18 : 13)
                    if status != "completed" {
                        Text(tr(status == "next" ? .next : statusText(status)))
                            .lineLimit(1)
                    }
                }
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(status == "completed" ? Color.chatRainbowGreen : status == "next" || status == "failed" ? Color.fontButton : Color.fontSecondary)
                .padding(.horizontal, 6)
                .frame(minHeight: 24)
                .background(status == "next" ? Color(hex: 0x4867CD) : status == "failed" ? Color.error : Color.clear, in: Capsule())

                Text(date(timestamp))
                Text(time(timestamp))
            }
            .font(.omSmall.weight(.semibold))
            .foregroundStyle(selected ? Color(hex: 0x4867CD) : Color.fontSecondary)
            .padding(.top, 7)
            .frame(width: width, height: 100, alignment: .top)
            .overlay(alignment: .bottom) {
                Rectangle().fill(selected ? Color(hex: 0x4867CD) : Color.fontPrimary)
                    .frame(width: selected ? 2 : 1, height: 24)
                    .padding(.bottom, 8)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(date(timestamp)), \(time(timestamp)): \(tr(status == "next" ? .next : statusText(status)))")
        .accessibilityValue(selected ? AppStrings.localized("workflows.builder.selected") : "")
        .accessibilityIdentifier(id == upcomingId ? "workflow-next-run-marker" : "workflow-run-marker")
    }
}
