import SwiftUI

/// PlanDetailPage.svelte: encrypted plan overview and review actions.
struct PlanDetailView: View {
    @ObservedObject var store: TasksWorkspaceStore
    let plan: UserPlanItem
    var onOpenProject: (String) -> Void = { _ in }
    var onOpenChat: (String) -> Void = { _ in }
    var onReportIssue: () -> Void = {}

    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var detail: UserPlanDetailState?
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var detailError: String?
    @State private var isEditing = false
    @State private var title = ""
    @State private var goal = ""
    @State private var assumptionText = ""
    @State private var criterionText = ""
    @State private var checkTitle = ""
    @State private var checkCommand = ""
    @State private var evidenceSummary = ""
    @State private var selectedVerificationID: String?

    private var current: UserPlanItem { store.selectedPlan ?? plan }

    var body: some View {
            ScrollView {
                VStack(spacing: 0) {
                    header
                    VStack(alignment: .leading, spacing: 16) {
                    if let detail {
                        overview(detail)
                        assumptions(detail)
                        criteria(detail)
                        checks(detail)
                        referencePatterns(detail)
                    } else if isLoading {
                        ProgressView(AppStrings.loading)
                            .frame(maxWidth: .infinity, minHeight: 180)
                    } else if let detailError {
                        VStack(spacing: 12) {
                            Text(detailError).foregroundStyle(Color.error)
                            Button(AppStrings.retry) { Task { await load() } }
                        }
                            .frame(maxWidth: .infinity, minHeight: 160)
                    }
                    }
                    .padding(16)
                }
            }
            .background(Color.grey0)
            .safeAreaInset(edge: .top, spacing: 0) {
                HStack {
                    Button(AppStrings.tasks) { dismiss() }
                    Spacer()
                    Button(action: onReportIssue) {
                        Icon("bug", size: 21)
                            .foregroundStyle(Color(hex: 0x4867CD))
                            .frame(width: 40, height: 40)
                            .background(Color.grey0, in: Circle())
                            .shadow(color: .black.opacity(0.1), radius: 4, y: 2)
                    }
                    .accessibilityLabel(AppStrings.reportIssue)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, 16)
                .frame(height: 56)
                .frame(maxWidth: .infinity)
                .background(Color.grey0)
            }
            .task(id: plan.id) { await load() }
            .accessibilityIdentifier("plan-detail-page")
    }

    private var header: some View {
        VStack(spacing: 0) {
            ZStack {
                LinearGradient.primary
                if horizontalSizeClass != .compact {
                    HStack {
                        Icon("task", size: 100).rotationEffect(.degrees(-10))
                        Spacer()
                        Icon("task", size: 100).rotationEffect(.degrees(10))
                    }
                    .foregroundStyle(.white.opacity(0.28))
                    .padding(.horizontal, 45)
                    .allowsHitTesting(false)
                }
                VStack(spacing: 8) {
                    Icon("task", size: 38)
                    if isEditing {
                        TextField(AppStrings.tasksPlan, text: $title)
                            .font(.omLg.weight(.bold))
                            .multilineTextAlignment(.center)
                        TextField(AppStrings.tasksPlanGoal, text: $goal, axis: .vertical)
                            .lineLimit(2...5)
                            .multilineTextAlignment(.center)
                        Button(AppStrings.save) { saveHeader() }
                            .disabled(isSaving || store.isSaving)
                            .buttonStyle(.bordered)
                    } else {
                        Button {
                            title = current.title
                            goal = current.goal
                            isEditing = true
                        } label: {
                            VStack(spacing: 8) {
                                Text(current.title).font(.omLg.weight(.bold))
                                Text(current.goal).font(.omSmall)
                            }
                            .multilineTextAlignment(.center)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .foregroundStyle(.white)
                .frame(maxWidth: 760)
                .padding(.horizontal, 24)
            }
            .frame(maxWidth: .infinity)
            .frame(minHeight: 190)
            .clipShape(.rect(bottomLeadingRadius: 14, bottomTrailingRadius: 14))
            .shadow(color: .black.opacity(0.16), radius: 12, y: 6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityIdentifier("plan-detail-overview")
    }

    private func overview(_ detail: UserPlanDetailState) -> some View {
        Group {
            if horizontalSizeClass == .compact {
                VStack(spacing: 12) { summaryCards(detail) }
            } else {
                HStack(spacing: 12) { summaryCards(detail) }
            }
        }
    }

    @ViewBuilder private func summaryCards(_ detail: UserPlanDetailState) -> some View {
        summaryCount(detail.assumptions.filter { $0.status != "confirmed" }.count,
                     title: AppStrings.tasksPlanOpenAssumptions)
        summaryCount(detail.criteria.filter { $0.subtitle.hasPrefix("uncovered") }.count,
                     title: AppStrings.tasksPlanUncoveredCriteria)
        summaryCount(detail.verifications.filter { $0.status == "failed" }.count,
                     title: AppStrings.tasksPlanFailedChecks)
    }

    private func summaryCount(_ count: Int, title: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(count)").font(.system(size: 32, weight: .bold))
            Text(title).font(.omXs).foregroundStyle(Color.fontSecondary)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
        .padding(12)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(Color.grey20, lineWidth: 1))
    }

    private func assumptions(_ detail: UserPlanDetailState) -> some View {
        planSection(AppStrings.tasksPlanAssumptions, count: detail.assumptions.count,
                    identifier: "plan-assumptions-section") {
            inlineForm(text: $assumptionText, placeholder: AppStrings.tasksPlanAssumptionPlaceholder,
                       buttonTitle: AppStrings.tasksPlanAddAssumption, buttonID: "plan-assumption-add-button") {
                let text = assumptionText.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return }
                mutate {
                    let updated = try await store.createPlanAssumption(text, plan: current)
                    assumptionText = ""
                    self.detail = updated
                }
            }
            ForEach(detail.assumptions) { item in
                itemRow(item, identifier: "plan-assumption-item") {
                    if item.status != "confirmed" {
                        Button(AppStrings.confirm) {
                            mutate { self.detail = try await store.confirmPlanAssumption(item.id, plan: current) }
                        }
                        .buttonStyle(PlanActionButtonStyle())
                    }
                }
            }
        }
    }

    private func criteria(_ detail: UserPlanDetailState) -> some View {
        planSection(AppStrings.tasksPlanCriteria, count: detail.criteria.count,
                    identifier: "plan-criteria-section") {
            inlineForm(text: $criterionText, placeholder: AppStrings.tasksPlanCriterionPlaceholder,
                       buttonTitle: AppStrings.tasksPlanAddCriterion, buttonID: "plan-criterion-add-button") {
                let text = criterionText.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return }
                mutate {
                    self.detail = try await store.createPlanCriterion(text, plan: current)
                    criterionText = ""
                }
            }
            ForEach(detail.criteria) { item in
                itemRow(item, identifier: "plan-criterion-item") { EmptyView() }
            }
        }
    }

    private func checks(_ detail: UserPlanDetailState) -> some View {
        planSection(AppStrings.tasksPlanChecks, count: detail.verifications.count,
                    identifier: "plan-checks-section") {
            VStack(spacing: 8) {
                TextField(AppStrings.tasksPlanCheckDescription, text: $checkTitle)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("plan-check-title-input")
                TextField(AppStrings.tasksPlanOptionalCommand, text: $checkCommand)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("plan-check-command-input")
                Button(AppStrings.tasksPlanAddCheck) {
                    let title = checkTitle.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !title.isEmpty else { return }
                    mutate {
                        self.detail = try await store.createPlanVerification(
                            title: title, command: checkCommand,
                            covering: detail.criteria.map(\.id), plan: current)
                        checkTitle = ""; checkCommand = ""
                    }
                }
                .disabled(checkTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
                .buttonStyle(PlanActionButtonStyle())
                .accessibilityIdentifier("plan-check-add-button")
            }
            ForEach(detail.verifications) { item in
                itemRow(item, identifier: "plan-check-item") { EmptyView() }
            }
            if !detail.verifications.isEmpty {
                Picker(AppStrings.tasksPlanChecks, selection: $selectedVerificationID) {
                    ForEach(detail.verifications) { item in Text(item.title).tag(Optional(item.id)) }
                }
                .accessibilityIdentifier("plan-evidence-check-select")
                TextField(AppStrings.tasksPlanChecks, text: $evidenceSummary)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("plan-evidence-summary-input")
                Button(AppStrings.tasksComplete) {
                    guard let id = selectedVerificationID ?? detail.verifications.first?.id else { return }
                    let summary = evidenceSummary.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !summary.isEmpty else { return }
                    mutate {
                        self.detail = try await store.addPlanVerificationEvidence(
                            summary, verificationID: id, plan: current)
                        evidenceSummary = ""
                    }
                }
                .disabled(evidenceSummary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
                .buttonStyle(PlanActionButtonStyle())
                .accessibilityIdentifier("plan-evidence-add-button")
            }
        }
    }

    private func referencePatterns(_ detail: UserPlanDetailState) -> some View {
        planSection(AppStrings.tasksPlanPatterns, count: detail.referencePatterns.count,
                    identifier: "plan-reference-patterns-section") {
            ForEach(detail.referencePatterns) { item in
                itemRow(item, identifier: "plan-reference-pattern-item") { EmptyView() }
            }
        }
    }

    private func planSection<Content: View>(_ title: String, count: Int, identifier: String,
                                            @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(title).font(.omP).fontWeight(.bold)
                Spacer()
                Text("\(count)").font(.omXs)
                    .frame(width: 28, height: 28)
                    .background(Color.grey10, in: Circle())
            }
            content()
        }
        .padding(16)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(Color.grey20, lineWidth: 1))
        .shadow(color: .black.opacity(0.06), radius: 8, y: 4)
        .accessibilityIdentifier(identifier)
    }

    private func itemRow<Accessory: View>(_ item: UserPlanDetailEntry, identifier: String,
                                          @ViewBuilder accessory: () -> Accessory) -> some View {
        Group {
            if horizontalSizeClass == .compact {
                VStack(alignment: .leading, spacing: 12) {
                    itemText(item)
                    accessory()
                }
            } else {
                HStack(alignment: .top, spacing: 12) {
                    itemText(item)
                    Spacer(minLength: 0)
                    accessory()
                }
            }
        }
        .padding(12)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: 18))
        .accessibilityIdentifier(identifier)
    }

    private func itemText(_ item: UserPlanDetailEntry) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(item.title).font(.omSmall).fontWeight(.bold)
            Text(item.subtitle).font(.omXs).foregroundStyle(Color.fontSecondary)
            if !item.evidence.isEmpty {
                Text(item.evidence).font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
    }

    private func inlineForm(text: Binding<String>, placeholder: String, buttonTitle: String, buttonID: String,
                            action: @escaping () -> Void) -> some View {
        Group {
            if horizontalSizeClass == .compact {
                VStack(alignment: .leading, spacing: 10) {
                    planInput(text, placeholder: placeholder)
                    addButton(text: text, title: buttonTitle, buttonID: buttonID, action: action)
                }
            } else {
                HStack(spacing: 10) {
                    planInput(text, placeholder: placeholder)
                    addButton(text: text, title: buttonTitle, buttonID: buttonID, action: action)
                }
            }
        }
    }

    private func planInput(_ text: Binding<String>, placeholder: String) -> some View {
        TextField(placeholder, text: text)
            .textFieldStyle(.plain)
            .padding(.horizontal, 13).padding(.vertical, 11)
            .background(Color.grey0, in: Capsule())
            .overlay(Capsule().stroke(Color.grey30, lineWidth: 1))
    }

    private func addButton(text: Binding<String>, title: String, buttonID: String,
                           action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .buttonStyle(PlanActionButtonStyle())
            .disabled(text.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
            .accessibilityIdentifier(buttonID)
    }

    private func mutate(_ work: @escaping @MainActor () async throws -> Void) {
        guard !isSaving else { return }
        isSaving = true
        Task {
            defer { isSaving = false }
            do { try await work(); detailError = nil }
            catch { detailError = error.localizedDescription }
        }
    }

    private func saveHeader() {
        isEditing = false
        Task { await store.savePlan(current, title: title, goal: goal) }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            detail = try await store.planDetail(current)
            selectedVerificationID = detail?.verifications.first?.id
            detailError = nil
        } catch { detailError = error.localizedDescription }
    }
}

private struct PlanActionButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omSmall)
            .foregroundStyle(Color.fontButton)
            .padding(.horizontal, 16).padding(.vertical, 11)
            .background(Color.buttonPrimary, in: Capsule())
            .opacity(isEnabled ? (configuration.isPressed ? 0.8 : 1) : 0.55)
    }
}
