// WorkflowViews.swift
//
// Native Workflows home, sidebar, focused editor, and run history. These views
// use the same server API contract as the web workspace without sharing chat
// state or introducing default Apple product chrome.
//
// Spec: docs/specs/workflows-v1/spec.yml
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/apps/web_app/src/routes/workflows/+page.svelte
//         frontend/packages/ui/src/components/workspace/WorkflowSidebar.svelte
// CSS:    frontend/apps/web_app/src/routes/workflows/+page.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct WorkflowWorkspaceView: View {
    @ObservedObject var store: WorkflowStore

    var body: some View {
        Group {
            if let workflow = store.selectedWorkflow {
                WorkflowEditorView(store: store, workflow: workflow)
            } else {
                WorkflowHomeView(store: store)
            }
        }
        .task {
            guard !ProcessInfo.processInfo.arguments.contains("--ui-test-workflows-fixture") else { return }
            await store.load()
        }
    }
}

struct WorkflowSidebarView: View {
    @ObservedObject var store: WorkflowStore
    let onSelect: (WorkflowSummary) -> Void

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .spacing3) {
                Text(AppStrings.workflows)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing5)
                    .padding(.top, .spacing5)

                ForEach(store.workflows) { workflow in
                    Button { onSelect(workflow) } label: {
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(workflow.title)
                                .font(.omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontPrimary)
                                .lineLimit(1)
                            Text(workflow.enabled ? AppStrings.enabled : AppStrings.disabled)
                                .font(.omTiny)
                                .foregroundStyle(Color.fontTertiary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.spacing4)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("workflow-sidebar-row")
                    .padding(.horizontal, .spacing3)
                }
            }
        }
        .background(Color.grey0)
        .accessibilityIdentifier("workflows-sidebar")
    }
}

private struct WorkflowHomeView: View {
    @ObservedObject var store: WorkflowStore
    @State private var title = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                Text(AppStrings.workflows)
                    .font(.omH2)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)

                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(AppStrings.workflows)
                        .font(.omSmall)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontSecondary)
                    Button { store.showFixture("editor") } label: {
                        Text(AppStrings.add)
                            .font(.omP)
                            .foregroundStyle(Color.fontButton)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, .spacing5)
                            .background(LinearGradient.primary)
                            .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                    .buttonStyle(.plain)
                }
                .padding(.spacing6)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .accessibilityIdentifier("workflow-recommendations")

                VStack(spacing: .spacing3) {
                    TextField(AppStrings.workflows, text: $title)
                        .textFieldStyle(OMTextFieldStyle())
                    Button {
                        let submittedTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !submittedTitle.isEmpty else { return }
                        Task { await store.createDraft(title: submittedTitle) }
                    } label: {
                        Text(AppStrings.add)
                            .font(.omP)
                            .foregroundStyle(Color.fontButton)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, .spacing5)
                            .background(LinearGradient.primary)
                            .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                    .buttonStyle(.plain)
                    .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isLoading)
                }
                .accessibilityIdentifier("workflow-input-composer")
            }
            .padding(.spacing8)
        }
        .background(Color.grey0)
        .accessibilityIdentifier("workflows-home")
    }
}

private struct WorkflowEditorView: View {
    @ObservedObject var store: WorkflowStore
    let workflow: WorkflowDetail
    @State private var title: String
    @State private var expandedNodeId: String?
    @State private var isDirty = false

    init(store: WorkflowStore, workflow: WorkflowDetail) {
        self.store = store
        self.workflow = workflow
        _title = State(initialValue: workflow.title)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing6) {
                TextField(AppStrings.workflows, text: $title)
                    .textFieldStyle(OMTextFieldStyle())
                    .onChange(of: title) { _, _ in isDirty = true }
                    .accessibilityIdentifier("workflow-title-input")

                HStack(spacing: .spacing3) {
                    Button { title = workflow.title; isDirty = false } label: {
                        Text(AppStrings.cancel)
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("workflow-editor-undo")

                    Button {
                        Task { await store.save(title: title, graph: workflow.graph) }
                        isDirty = false
                    } label: {
                        Text(AppStrings.save)
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(!isDirty || store.isLoading)
                    .accessibilityIdentifier("save-workflow")

                    Button {
                        Task { await store.setEnabled(!workflow.enabled) }
                    } label: {
                        Text(workflow.enabled ? AppStrings.disabled : AppStrings.enabled)
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                }

                VStack(spacing: .spacing4) {
                    ForEach(workflow.graph.nodes) { node in
                        Button { expandedNodeId = expandedNodeId == node.id ? nil : node.id } label: {
                            VStack(alignment: .leading, spacing: .spacing2) {
                                Text(node.title ?? AppStrings.workflows)
                                    .font(.omP)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(Color.fontPrimary)
                                Text(node.type.rawValue)
                                    .font(.omTiny)
                                    .foregroundStyle(Color.fontTertiary)
                                if expandedNodeId == node.id {
                                    Text(AppStrings.edit)
                                        .font(.omSmall)
                                        .foregroundStyle(Color.fontSecondary)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.spacing5)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius6))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("workflow-node-summary")
                    }
                }
                .accessibilityIdentifier("workflow-node-stack")

                WorkflowRunHistoryView(runs: store.runs, onRun: { Task { await store.runSelected() } })
            }
            .padding(.spacing8)
        }
        .background(Color.grey0)
        .accessibilityIdentifier("workflow-editor")
    }
}

private struct WorkflowRunHistoryView: View {
    let runs: [WorkflowRunDetail]
    let onRun: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Button(action: onRun) {
                Text(AppStrings.add)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            ForEach(runs) { run in
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(run.status)
                        .font(.omSmall)
                        .fontWeight(.semibold)
                    ForEach(run.nodeRuns) { nodeRun in
                        Text(nodeRun.status)
                            .font(.omTiny)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
                .padding(.spacing4)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
        }
        .accessibilityIdentifier("workflow-runs")
    }
}
