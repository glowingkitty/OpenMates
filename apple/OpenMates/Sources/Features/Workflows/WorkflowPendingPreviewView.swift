// Read-only preview while an AI-authored Workflow is being saved.
// Web source: frontend/packages/ui/src/components/workflows/WorkflowPendingPreview.svelte

import SwiftUI

extension AppStrings {
    static var workflowAIPreviewLabel: String { localized("workflows.builder.ai_preview_label") }
    static var workflowAIPreviewSaving: String { localized("workflows.builder.ai_preview_saving") }
    static var workflowAIPreviewPending: String { localized("workflows.builder.ai_preview_pending") }
    static var workflowAIPreviewSteps: String { localized("workflows.builder.ai_preview_steps") }
}

struct WorkflowPendingPreviewView: View {
    enum Mode { case landing, editor }

    let workflow: WorkflowDetail
    let mode: Mode

    private var steps: [WorkflowNode] {
        workflow.graph.nodes.filter { $0.type != .end }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing5) {
                Text(AppStrings.workflowAIPreviewSaving)
                    .font(.omSmall.weight(.bold))
                    .foregroundStyle(Color.fontButton)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing3)
                    .background(Color.buttonPrimary, in: Capsule())
                    .accessibilityIdentifier("workflow-ai-saving-pill")
                Text(AppStrings.workflowAIPreviewLabel)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }

            Text(workflow.title)
                .font(.omH3)
                .foregroundStyle(Color.fontPrimary)
                .accessibilityIdentifier("workflow-ai-preview-title")

            if let description = workflow.description, !description.isEmpty {
                Text(description)
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("workflow-ai-preview-description")
            }

            Text(AppStrings.workflowAIPreviewPending)
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)

            if !steps.isEmpty {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(AppStrings.workflowAIPreviewSteps)
                        .font(.omP.weight(.semibold))
                    ForEach(Array(steps.enumerated()), id: \.element.id) { index, node in
                        Text("\(index + 1). \(node.title ?? node.type.rawValue.replacingOccurrences(of: "_", with: " "))")
                            .font(.omP)
                            .padding(.leading, .spacing5)
                    }
                }
                .padding(.top, .spacing4)
                .accessibilityIdentifier("workflow-ai-preview-steps")
            }

            if mode == .editor {
                WorkflowGraphView(graph: workflow.graph, readOnly: true)
                    .padding(.top, .spacing8)
                    .accessibilityIdentifier("workflow-ai-preview-graph")
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: mode == .editor ? 896 : 672, alignment: .leading)
        .frame(maxWidth: .infinity)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.buttonPrimary, lineWidth: 1))
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing8)
        .accessibilityIdentifier("workflow-ai-pending-preview")
    }
}

struct WorkflowAIAuthoringStatusView: View {
    @ObservedObject var authoring: WorkflowAIAuthoringController
    let workflowId: String?
    let onUndo: () -> Void

    private var change: WorkflowInputChange? {
        guard let workflowId else { return nil }
        return authoring.completedSession?.changes?.first { $0.workflowId == workflowId }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            if let pending = authoring.pendingSession {
                HStack(spacing: .spacing4) {
                    ProgressView()
                    Text(pending.message ?? AppStrings.workflowAISaving)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                    if !authoring.isSubmitting {
                        Button(AppStrings.workflowBuilder(.ai_check_status)) {
                            Task { await authoring.resumePending() }
                        }
                        .buttonStyle(OMSecondaryButtonStyle())
                    }
                }
                .accessibilityIdentifier("workflow-ai-pending")
                if let preview = pending.previewWorkflow,
                   (workflowId == nil || preview.id == workflowId) {
                    WorkflowPendingPreviewView(
                        workflow: preview, mode: workflowId == nil ? .landing : .editor
                    )
                }
            }

            if let assumptions = authoring.completedSession?.assumptions, !assumptions.isEmpty {
                Text(assumptions.joined(separator: " "))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("workflow-ai-assumptions")
            }

            if let change {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(AppStrings.workflowBuilder(.ai_changes_saved))
                        .font(.omP.weight(.semibold))
                    if !change.removedNodes.isEmpty {
                        Text("\(AppStrings.workflowBuilder(.ai_removed)) \(change.removedNodes.map(\.title).joined(separator: ", "))")
                    }
                    if !change.addedNodeIds.isEmpty {
                        Text("\(change.addedNodeIds.count) \(AppStrings.workflowBuilder(.ai_added_nodes))")
                    }
                    if !change.editedNodeIds.isEmpty {
                        Text("\(change.editedNodeIds.count) \(AppStrings.workflowBuilder(.ai_edited_nodes))")
                    }
                }
                .font(.omSmall)
                .accessibilityIdentifier("workflow-ai-changes")
            }

            if authoring.completedSession?.undoAvailable == true {
                Button(AppStrings.workflowBuilder(.ai_undo), action: onUndo)
                    .buttonStyle(OMSecondaryButtonStyle())
                    .disabled(authoring.isSubmitting || authoring.isUndoing)
                    .accessibilityIdentifier(workflowId == nil ? "workflow-ai-created-undo" : "workflow-ai-undo")
            }

            if let error = authoring.errorMessage {
                Text(error)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("workflow-ai-error")
            }
        }
    }
}
