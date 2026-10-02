// Native Workflow home, sidebar, editor, versions and run history.
// Web source: frontend/apps/web_app/src/routes/workflows/+page.svelte
//             frontend/packages/ui/src/components/workspace/WorkflowSidebar.svelte
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.mvp.list, workflows.mvp.editor, workflows.mvp.run-history

import SwiftUI

struct WorkflowWorkspaceView: View {
    @ObservedObject var store: WorkflowStore
    @ObservedObject var authManager: AuthManager
    let onReportIssue: () -> Void
    let chatChoices: [WorkflowChatChoice]

    var body: some View {
        // Keep workspace and destination accessibility containers distinct.
        // Group forwards its identifier onto the selected child root.
        VStack(spacing: 0) {
            if let workflow = store.selectedWorkflow {
                WorkflowEditorView(store: store, authManager: authManager,
                                   authoring: store.authoring, workflow: workflow,
                                   onReportIssue: onReportIssue, chatChoices: chatChoices)
                    .id(workflow.id)
            } else {
                WorkflowHomeView(store: store, authManager: authManager,
                                 authoring: store.authoring, onReportIssue: onReportIssue)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task {
            guard !ProcessInfo.processInfo.arguments.contains("--ui-test-workflows-fixture") else { return }
            await store.load()
        }
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflows-workspace")
    }
}

struct WorkflowSidebarView: View {
    @ObservedObject var store: WorkflowStore
    let onSelect: (WorkflowSummary) -> Void

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .spacing5) {
                HStack {
                    Text(AppStrings.workflows)
                        .font(.omSmall.weight(.heavy))
                        .textCase(.uppercase)
                        .tracking(1.1)
                    Spacer()
                    Text("\(store.workflows.count)")
                        .font(.omSmall)
                        .frame(minWidth: 29, minHeight: 29)
                        .background(Color.grey10, in: Circle())
                }
                .foregroundStyle(Color.fontSecondary)

                if store.isLoading && store.workflows.isEmpty {
                    Text(AppStrings.workflowSidebarLoading)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                } else if store.workflows.isEmpty {
                    Text(AppStrings.workflowSidebarEmpty)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                } else {
                    ForEach(store.workflows) { workflow in
                        Button { onSelect(workflow) } label: {
                            VStack(alignment: .leading, spacing: .spacing2) {
                                Text(workflow.title)
                                    .font(.omSmall.weight(.semibold))
                                    .foregroundStyle(Color.fontPrimary)
                                    .lineLimit(1)
                                Text("\(workflow.enabled ? AppStrings.enabled : AppStrings.workflowBuilder(.draft)) · \(workflow.triggerSummary ?? AppStrings.workflowSidebarManual)")
                                    .font(.omSmall)
                                    .foregroundStyle(Color.fontSecondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.spacing4)
                            .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius8))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("workflow-sidebar-row")
                    }
                }
            }
            .padding(.spacing6)
        }
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflows-sidebar")
    }
}

private struct WorkflowEditorView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ObservedObject var store: WorkflowStore
    @ObservedObject var authManager: AuthManager
    @ObservedObject var authoring: WorkflowAIAuthoringController
    let workflow: WorkflowDetail
    let onReportIssue: () -> Void
    let chatChoices: [WorkflowChatChoice]
    @State private var tab: WorkflowDetailTab = .template
    @State private var selectedVersionId: String?
    @State private var confirmDelete = false
    @State private var editorInstruction = ""
    @State private var showSharingSoon = false
    @State private var showingVoiceInput = false
    @State private var revealedEditorId: String?

    private var canActivate: Bool {
        !workflow.graph.triggerNodeId.isEmpty && workflow.graph.nodes.count > 1
    }

    var body: some View {
        VStack(spacing: 0) {
        GeometryReader { viewport in
        ScrollViewReader { scrollProxy in
        ScrollView {
            VStack(spacing: 0) {
                WorkflowDetailHeader(
                    title: workflow.title, description: workflow.description,
                    category: workflow.category ?? "general_knowledge", icon: workflow.icon ?? "",
                    enabled: workflow.enabled, canEnable: canActivate, canRun: canActivate,
                    createdAt: workflow.createdAt, nextRunAt: workflow.nextRunAt,
                    saving: store.isLoading, tab: $tab,
                    onUpdateIdentity: { title, description in
                        await store.save(title: title, description: description, graph: workflow.graph)
                    },
                    onToggleEnabled: { Task { await store.setEnabled(!workflow.enabled) } },
                    onRun: { Task { await store.runSelected(); tab = .runs } },
                    onDelete: { confirmDelete = true },
                    onBack: { store.clearSelection() },
                    onShare: { showSharingSoon = true },
                    onReportIssue: onReportIssue
                )
                .confirmationDialog(AppStrings.workflowBuilder(.delete_workflow), isPresented: $confirmDelete) {
                    Button(AppStrings.workflowBuilder(.delete_workflow), role: .destructive) {
                        Task { await store.deleteSelected() }
                    }
                }

                if tab == .template {
                    VStack(spacing: .spacing4) {
                        WorkflowAIAuthoringStatusView(authoring: authoring, workflowId: workflow.id) {
                            Task { await store.undoInstruction() }
                        }

                        if !store.versions.isEmpty {
                            Menu {
                                ForEach(store.versions) { version in
                                    Button {
                                        selectedVersionId = version.versionId
                                    } label: {
                                        Text("\(AppStrings.workflowVersionHistory) \(version.versionNumber)")
                                    }
                                }
                            } label: {
                                HStack {
                                    Text(AppStrings.workflowVersionHistory)
                                    Icon("dropdown", size: 14)
                                }
                                .font(.omSmall.weight(.semibold))
                                .foregroundStyle(Color.fontSecondary)
                            }
                            .accessibilityIdentifier("workflow-version-history")
                            .confirmationDialog(AppStrings.workflowVersionRestore, isPresented: Binding(
                                get: { selectedVersionId != nil },
                                set: { if !$0 { selectedVersionId = nil } }
                            )) {
                                if let id = selectedVersionId {
                                    Button(AppStrings.workflowVersionRestore) {
                                        Task { await store.restoreVersion(id); selectedVersionId = nil }
                                    }
                                }
                            }
                        }
                        if let error = store.errorMessage {
                            Text(error).font(.omSmall).foregroundStyle(Color.error)
                        }
                        WorkflowGraphView(
                            graph: workflow.graph, skills: store.skills,
                            workflowId: workflow.id, accountId: store.accountId,
                            chatChoices: chatChoices,
                            onSave: { graph in
                                await store.save(title: workflow.title, description: workflow.description, graph: graph)
                            },
                            previewAskAIVerdict: store.previewAskAIVerdict
                        )

                    }
                    .frame(maxWidth: 960)
                    .frame(maxWidth: .infinity)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("workflow-editor")
                } else {
                    WorkflowRunTimelineView(
                        workflow: workflow, runs: store.runs, detail: store.selectedRunDetail,
                        pinnedGraph: store.pinnedRunGraph, loadingDetail: store.isLoadingRun,
                        onSelect: { runId in Task { await store.selectRun(runId) } },
                        onOpenEditor: { tab = .template },
                        onCancel: { runId in await store.cancelRun(runId) },
                        onDelete: { runId in await store.deleteRun(runId) }
                    )
                    .task(id: tab) {
                        guard !ProcessInfo.processInfo.arguments.contains("--ui-test-workflows-fixture") else { return }
                        while !Task.isCancelled && tab == .runs {
                            await store.refreshRuns()
                            try? await Task.sleep(for: .seconds(5))
                        }
                    }
                }
            }
        }
        .coordinateSpace(name: WorkflowEditorScrollTarget.coordinateSpace)
        .onPreferenceChange(WorkflowEditorScrollTargetKey.self) { target in
            revealEditor(target, viewportHeight: viewport.size.height, using: scrollProxy)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-management")
        }
        }
        // Keep the actual scroll viewport separate from the composer. Its
        // measured height now excludes the dock, including for editor reveal.
            if tab == .template { dockedComposer }
        }
        .task {
            guard !ProcessInfo.processInfo.arguments.contains("--ui-test-workflows-fixture") else { return }
            await store.loadCapabilities()
            await store.loadVersions()
        }
        .overlay(alignment: .top) {
            if showSharingSoon {
                Text(AppStrings.workflowBuilder(.sharing_soon))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.spacing4)
                    .background(Color.grey10, in: Capsule())
                    .shadow(radius: 4)
                    .padding(.top, .spacing4)
                    .accessibilityIdentifier("workflow-sharing-soon")
                    .task {
                        try? await Task.sleep(for: .seconds(4))
                        showSharingSoon = false
                    }
            }
        }
    }

    private var dockedComposer: some View {
        WorkflowPromptComposerView(
            text: $editorInstruction,
            placeholder: AppStrings.workflowBuilder(.ai_edit_placeholder),
            submitLabel: AppStrings.workflowBuilder(.ai_edit_submit),
            submittingLabel: AppStrings.workflowBuilder(.ai_edit_submitting),
            disabled: store.isLoading || authoring.pendingSession != nil,
            submitting: authoring.isSubmitting,
            identifier: "workflow-ai-editor-composer",
            inputIdentifier: "workflow-ai-edit-textarea",
            submitIdentifier: "workflow-ai-edit-submit",
            micIdentifier: "workflow-ai-edit-mic",
            onSubmit: { submitted in
                Task {
                    if await store.submitInstruction(submitted, selectedWorkflowId: workflow.id) {
                        editorInstruction = ""
                    }
                }
            },
            onMic: { showingVoiceInput = true }
        )
        .padding(.horizontal, .spacing8)
        .padding(.top, .spacing6)
        .padding(.bottom, .spacing6)
        .background(LinearGradient(colors: [.clear, .grey10], startPoint: .top, endPoint: .bottom))
        .sheet(isPresented: $showingVoiceInput) {
            WorkflowVoiceInputView(
                authManager: authManager, expectedAccountID: store.accountId,
                onSubmit: { submitted in
                    Task {
                        if await store.submitInstruction(submitted, selectedWorkflowId: workflow.id) {
                            editorInstruction = ""
                        }
                    }
                },
                onReview: { editorInstruction = $0 },
                onClose: { showingVoiceInput = false }
            )
            .modifier(WorkflowVoiceSheetLayout())
        }
    }

    private func revealEditor(_ target: WorkflowEditorScrollTarget?, viewportHeight: CGFloat,
                              using proxy: ScrollViewProxy) {
        guard let target else { revealedEditorId = nil; return }
        guard target.id != revealedEditorId, viewportHeight > 0, target.bounds.height > 0 else { return }
        revealedEditorId = target.id

        // Web scrollEditorIntoView uses block: nearest. Keep the current viewport
        // when the editor fits inside it or already spans both viewport edges.
        let above = target.bounds.minY < 0
        let below = target.bounds.maxY > viewportHeight
        guard above != below else { return }
        let fits = target.bounds.height <= viewportHeight
        let anchor: UnitPoint = above ? (fits ? .top : .bottom) : (fits ? .bottom : .top)
        if reduceMotion {
            proxy.scrollTo(target.id, anchor: anchor)
        } else {
            withAnimation(.easeInOut(duration: 0.25)) {
                proxy.scrollTo(target.id, anchor: anchor)
            }
        }
    }
}
