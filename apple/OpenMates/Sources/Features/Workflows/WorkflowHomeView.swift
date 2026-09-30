// Workflow landing surface mapped to WorkspaceHomeShell(surface="workflows").
// The owner-scoped WorkflowStore supplies recent cards and all mutations.

import SwiftUI

struct WorkflowHomeView: View {
    @ObservedObject var store: WorkflowStore
    @ObservedObject var authManager: AuthManager
    @ObservedObject var authoring: WorkflowAIAuthoringController
    let onReportIssue: () -> Void

    @State private var instruction = ""
    @State private var showingVoiceInput = false
    @State private var showingAll = false
    @State private var newStarterIDs: Set<String> = []

    private struct HomeCard: Identifiable {
        let id: String
        let title: String
        let summary: String
        let badge: String
        let category: String
        let icon: String
        let isNew: Bool
        let isStarter: Bool
    }

    private var greetingName: String {
        let name = authManager.currentUser?.username.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? AppStrings.workflowHomeFallbackName : name
    }

    private var newlyCreatedIDs: Set<String> {
        newStarterIDs.union(authoring.completedSession?.committedWorkflows.map(\.id) ?? [])
    }

    private var sortedWorkflows: [WorkflowSummary] {
        store.workflows.sorted { $0.updatedAt > $1.updatedAt }
    }

    private var recentCards: [HomeCard] {
        let recent = Array(sortedWorkflows.prefix(6))
        let appended = sortedWorkflows.filter { workflow in
            newlyCreatedIDs.contains(workflow.id) && !recent.contains(where: { $0.id == workflow.id })
        }
        return (recent + appended).map(recentCard)
    }

    private var landingCards: [HomeCard] {
        guard store.accountId != nil else { return [] }
        return recentCards + starterCards
    }
    private var allCards: [HomeCard] { sortedWorkflows.map(recentCard) }

    private var starterCards: [HomeCard] {
        [
            HomeCard(id: "starter-rain", title: AppStrings.workflowStarterRainTitle,
                     summary: AppStrings.workflowStarterRainSummary,
                     badge: AppStrings.workflowStarterBadge, category: "weather",
                     icon: "cloud-rain", isNew: false, isStarter: true),
            HomeCard(id: "starter-news", title: AppStrings.workflowStarterNewsTitle,
                     summary: AppStrings.workflowStarterNewsSummary,
                     badge: AppStrings.workflowStarterBadge, category: "technology",
                     icon: "calendar-days", isNew: false, isStarter: true),
            HomeCard(id: "starter-apartments", title: AppStrings.workflowStarterApartmentsTitle,
                     summary: AppStrings.workflowStarterApartmentsSummary,
                     badge: AppStrings.workflowStarterBadge, category: "productivity",
                     icon: "house", isNew: false, isStarter: true)
        ]
    }

    private var workflowInspiration: DailyInspirationData {
        DailyInspirationData(
            inspirationId: "hardcoded-workflow-trigger",
            text: AppStrings.workflowInspirationPhrase,
            title: AppStrings.workflowInspirationTitle,
            category: "productivity",
            feature: DailyInspirationFeature(
                iconName: "workflow", title: AppStrings.workflowInspirationFeatureTitle,
                description: AppStrings.workflowInspirationFeatureDescription
            )
        )
    }

    var body: some View {
        GeometryReader { geometry in
            let narrow = geometry.size.width < 550
            let tallCards = geometry.size.width >= 550 && geometry.size.height >= 800
            ZStack(alignment: .bottom) {
                VStack(spacing: 0) {
                    if !showingAll {
                        InspirationCard(
                            inspiration: workflowInspiration,
                            containerSize: geometry.size,
                            heightOverride: geometry.size.width < 730
                                ? 190 : max(240, min(420, geometry.size.height * 0.35)),
                            ctaTitle: AppStrings.localized("daily_inspiration.click_to_open_settings"),
                            tapHint: AppStrings.workflowInspirationPhrase
                        ) {
                            if store.accountId != nil { instruction = workflowInspiration.text }
                        }
                        .accessibilityIdentifier("workflows-daily-inspiration-area")
                    }
                    topControls(showingAll: showingAll)
                    Spacer(minLength: 0)
                }

                if showingAll {
                    allWorkflowsView(width: geometry.size.width, height: geometry.size.height)
                        .position(x: geometry.size.width / 2,
                                  y: geometry.size.height / 2 + (geometry.size.width <= 730 ? 72 : 0))
                } else {
                    homeCenter(width: geometry.size.width, tallCards: tallCards)
                        .position(x: geometry.size.width / 2,
                                  y: geometry.size.height / 2 + (narrow ? 72 : geometry.size.height * 0.175))
                }

                VStack(spacing: 8) {
                    WorkflowPromptComposerView(
                        text: $instruction,
                        placeholder: AppStrings.workflowBuilder(.new_workflow_placeholder),
                        submitLabel: AppStrings.workflowBuilder(.ai_create_submit),
                        submittingLabel: AppStrings.workflowBuilder(.ai_create_submitting),
                        disabled: store.accountId == nil || store.isLoading || authoring.pendingSession != nil,
                        submitting: authoring.isSubmitting,
                        identifier: "workflow-input-composer",
                        inputIdentifier: "workflow-input-textarea",
                        submitIdentifier: "workflow-input-submit",
                        micIdentifier: "workflow-input-mic",
                        onSubmit: submitInstruction,
                        onMic: { showingVoiceInput = true }
                    )
                    WorkflowAIAuthoringStatusView(authoring: authoring, workflowId: nil) {
                        Task { await store.undoInstruction() }
                    }
                }
                .frame(maxWidth: narrow ? .infinity : 629)
                .padding(.horizontal, narrow ? 0 : 15)
                .padding(.bottom, narrow ? 5 : 15)
            }
            // Attach the home container to its real multi-child content.
            // GeometryReader otherwise forwards the workspace's identifier
            // onto this destination when the workspace has one child.
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("workflows-home")
            .background(Color.grey20.ignoresSafeArea())
            .sheet(isPresented: $showingVoiceInput) {
                WorkflowVoiceInputView(
                    authManager: authManager, expectedAccountID: store.accountId,
                    onSubmit: submitInstruction,
                    onReview: { instruction = $0 },
                    onClose: { showingVoiceInput = false }
                )
                .modifier(WorkflowVoiceSheetLayout())
            }
            .onChange(of: store.accountId) { _, _ in
                instruction = ""
                showingAll = false
                showingVoiceInput = false
                newStarterIDs = []
            }
        }
    }

    private func topControls(showingAll: Bool) -> some View {
        HStack(spacing: 20) {
            Button(action: onReportIssue) {
                Icon("bug", size: 23)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 42, height: 42)
                    .background(Color.grey0, in: Circle())
                    .shadow(color: .black.opacity(0.13), radius: 6, y: 3)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.settingsReportIssue)
            .accessibilityIdentifier("workflows-home-report-issue")
            if showingAll {
                Button {
                    self.showingAll = false
                } label: {
                    HStack(spacing: 8) {
                        LucideNativeIcon("grid-2x2", size: 18)
                        Text(AppStrings.workflowHomeBackToRecent)
                    }
                }
                .accessibilityIdentifier("workflows-back-to-recent")
                Button(action: searchUnavailable) {
                    HStack(spacing: 8) {
                        LucideNativeIcon("search", size: 18)
                        Text(AppStrings.workflowHomeSearch)
                    }
                }
                .accessibilityIdentifier("workflows-search")
            }
            Spacer(minLength: 0)
        }
        .font(.omP.weight(.bold))
        .foregroundStyle(Color.grey60)
        .padding(.horizontal, 15)
        .padding(.top, 10)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(showingAll ? "workflows-all-toolbar" : "workflows-home-controls")
    }

    private func homeCenter(width: CGFloat, tallCards: Bool) -> some View {
        VStack(spacing: tallCards ? 10 : 22) {
            VStack(spacing: 8) {
                Text(AppStrings.workflowHomeGreeting(greetingName))
                    .font(.omH2.weight(.semibold))
                    .foregroundStyle(Color.grey80)
                    .frame(height: tallCards ? 68 : 46)
                    .background {
                        Icon("workflow", size: tallCards ? 128 : 76)
                            .foregroundStyle(Color.grey30)
                            .accessibilityHidden(true)
                    }
                Text(AppStrings.workflowHomeSubtitle)
                    .font(.omP.weight(.semibold))
                    .foregroundStyle(Color.grey60)
            }
            .multilineTextAlignment(.center)
            .accessibilityIdentifier("workflows-home-greeting")

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 16) {
                    ForEach(landingCards) { card in
                        VStack(spacing: 7) {
                            if card.isNew {
                                Text(AppStrings.workflowHomeBadgeNew)
                                    .font(.omSmall.weight(.bold))
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, 13).padding(.vertical, 4)
                                    .background(Color.buttonPrimary, in: Capsule())
                            }
                            homeCard(card, tall: tallCards)
                        }
                    }
                }
                .padding(.horizontal, max(0, (width - 300) / 2))
                .padding(.vertical, tallCards ? 12 : 6)
            }
            .accessibilityIdentifier("workflow-mixed-row")

            HStack(spacing: 12) {
                if !store.workflows.isEmpty {
                    Button {
                        showingAll = true
                    } label: {
                        HStack(spacing: 8) {
                            Icon("workflow", size: 14)
                            Text(AppStrings.workflowHomeShowAll)
                        }
                    }
                    .accessibilityIdentifier("workflows-show-all")
                }
                Button(action: searchUnavailable) {
                    HStack(spacing: 8) {
                        LucideNativeIcon("search", size: 18)
                        Text(AppStrings.workflowHomeSearch)
                    }
                }
                .accessibilityIdentifier("workflows-search")
            }
            .font(.omP.weight(.bold))
            .foregroundStyle(Color.grey60)

            if let error = store.errorMessage {
                Text(error).font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("workflows-error")
            }
        }
        .frame(width: width)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflows-start-screen")
    }

    private func allWorkflowsView(width: CGFloat, height: CGFloat) -> some View {
        let narrow = width <= 730
        let viewWidth = min(width - (narrow ? 20 : 32), 1120)
        let innerWidth = viewWidth - 16
        let columnCount = max(1, Int((innerWidth + 16) / (narrow ? 246 : 316)))
        let columnWidth = narrow
            ? (innerWidth - CGFloat(columnCount - 1) * 16) / CGFloat(columnCount) : 300
        let rows = max(1, (allCards.count + columnCount - 1) / columnCount)
        let contentHeight = CGFloat(rows * 200 + (rows - 1) * 16 + 68)
        let gridWidth = narrow ? innerWidth : CGFloat(columnCount * 300 + (columnCount - 1) * 16)
        let scrollHeight = min(contentHeight, narrow ? min(height * 0.56, 560) : min(height * 0.58, 620))
        let fade = min(0.5, 34 / max(scrollHeight, 1))
        return ScrollView {
            LazyVGrid(columns: Array(repeating: GridItem(.fixed(columnWidth), spacing: 16,
                                                         alignment: narrow ? .leading : .center), count: columnCount), spacing: 16) {
                ForEach(allCards) { card in homeCard(card, tall: true) }
            }
            .frame(width: gridWidth)
            .frame(width: innerWidth, alignment: narrow ? .leading : .center)
            .padding(.horizontal, 8)
            .padding(.vertical, 34)
        }
        .frame(width: viewWidth, height: scrollHeight)
        .mask(LinearGradient(stops: [
            .init(color: .clear, location: 0),
            .init(color: .black, location: fade),
            .init(color: .black, location: 1 - fade),
            .init(color: .clear, location: 1)
        ], startPoint: .top, endPoint: .bottom))
        .accessibilityIdentifier("all-workflows-view")
    }

    private func homeCard(_ card: HomeCard, tall: Bool) -> some View {
        Button {
            activate(card)
        } label: {
            Group {
                if tall {
                    ZStack {
                        WorkflowIconView(title: card.title, icon: card.icon, category: card.category, size: 80)
                            .rotationEffect(.degrees(-15))
                            .foregroundStyle(.white.opacity(0.3))
                            .position(x: 30, y: 168)
                            .accessibilityHidden(true)
                        WorkflowIconView(title: card.title, icon: card.icon, category: card.category, size: 80)
                            .rotationEffect(.degrees(15))
                            .foregroundStyle(.white.opacity(0.3))
                            .position(x: 270, y: 168)
                            .accessibilityHidden(true)
                        VStack(spacing: 8) {
                            if !card.isNew {
                                Text(card.badge).font(.omSmall.weight(.bold))
                                    .padding(.horizontal, 7).padding(.vertical, 3)
                                    .background(.white.opacity(0.18), in: Capsule())
                            }
                            WorkflowIconView(title: card.title, icon: card.icon, category: card.category, size: 32)
                            Text(card.title).font(.omP.weight(.bold)).lineLimit(2)
                            Text(card.summary).font(.omSmall.weight(.medium))
                                .foregroundStyle(.white.opacity(0.85)).lineLimit(2)
                        }
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20)
                    }
                    .frame(width: 300, height: 200)
                } else {
                    HStack(spacing: 12) {
                        WorkflowIconView(title: card.title, icon: card.icon, category: card.category, size: 18)
                        Text(card.title).font(.omP.weight(.semibold)).lineLimit(1)
                        Spacer(minLength: 0)
                        LucideNativeIcon("chevron-right", size: 16)
                    }
                    .padding(.horizontal, 20)
                    .frame(width: 300, height: 44)
                }
            }
            .foregroundStyle(.white)
            .background(cardGradient(for: card.category, tall: tall), in: RoundedRectangle(cornerRadius: tall ? 30 : 32))
            .clipShape(RoundedRectangle(cornerRadius: tall ? 30 : 32))
            .shadow(color: .black.opacity(tall ? 0.16 : 0.11), radius: tall ? 12 : 8, y: tall ? 8 : 5)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(card.title)
        .accessibilityIdentifier("workflow-landing-card")
    }

    private func cardGradient(for category: String, tall: Bool) -> LinearGradient {
        if CategoryMapping.isKnownCategory(category) {
            return CategoryMapping.gradient(for: category)
        }
        // CSS 135deg follows a 45-degree axis even on a 300×200 or 300×44 card.
        // A simple topLeading→bottomTrailing SwiftUI gradient changes angle with aspect ratio.
        let width: CGFloat = 300
        let height: CGFloat = tall ? 200 : 44
        let startX = (width - height) / (4 * width)
        let startY = (height - width) / (4 * height)
        return LinearGradient(
            colors: [Color(hex: 0x4867CD), Color(hex: 0xA0BEFF)],
            startPoint: UnitPoint(x: startX, y: startY),
            endPoint: UnitPoint(x: 1 - startX, y: 1 - startY)
        )
    }

    private func recentCard(_ workflow: WorkflowSummary) -> HomeCard {
        let isNew = newlyCreatedIDs.contains(workflow.id)
        let retention = workflow.runContentRetention == .none
            ? AppStrings.workflowHomeRetentionNone : AppStrings.workflowHomeRetentionLast5
        let trigger = workflow.triggerSummary ?? AppStrings.workflowSidebarManual
        return HomeCard(
            id: workflow.id, title: workflow.title,
            summary: "\(trigger) - \(retention)",
            badge: isNew ? AppStrings.workflowHomeBadgeNew
                : workflow.enabled ? AppStrings.workflowHomeBadgeEnabled : AppStrings.workflowHomeBadgePaused,
            category: workflow.category ?? "productivity",
            icon: workflow.icon ?? "workflow", isNew: isNew, isStarter: false
        )
    }

    private func activate(_ card: HomeCard) {
        guard store.accountId != nil else { return }
        if card.isStarter {
            switch card.id {
            case "starter-rain": createStarter(.rainAlert)
            case "starter-news": createStarter(.newsBrief)
            case "starter-apartments": createStarter(.hourlyApartments)
            default: break
            }
        } else {
            Task { await store.select(id: card.id) }
        }
    }

    private func createStarter(_ kind: WorkflowStarterKind) {
        let accountID = store.accountId
        let previousIDs = Set(store.workflows.map(\.id))
        Task {
            await store.createStarter(kind)
            guard store.accountId == accountID else { return }
            newStarterIDs.formUnion(store.workflows.map(\.id).filter { !previousIDs.contains($0) })
        }
    }

    private func submitInstruction(_ submitted: String) {
        Task {
            if await store.submitInstruction(submitted) { instruction = "" }
        }
    }

    private func searchUnavailable() {
        ToastManager.shared.show(AppStrings.workflowHomeSearchUnavailable, type: .info)
    }
}
