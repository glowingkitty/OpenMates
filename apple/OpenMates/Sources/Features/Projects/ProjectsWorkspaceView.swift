// Web source: frontend/packages/ui/src/components/projects/ProjectsPage.svelte,
// ProjectWorkspaceHeader.svelte, ProjectReadme.svelte, ProjectBrowserItem.svelte.
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.files.search-scoped,
// projects.workspace.contract-plan-task-check-chain
// Rendered reference: .runtime/build85-web-reference/projects-{overview,create-expanded,readme,files}.
import SwiftUI
import UniformTypeIdentifiers

/// Native Projects workspace. The shared app shell owns navigation and account lifecycle.
struct ProjectsWorkspaceView: View {
    @Environment(\.self) private var environment
    @ObservedObject var store: ProjectsWorkspaceStore
    var tasksStore: TasksWorkspaceStore? = nil
    var greetingName: String = "there"
    var previewInitialTab: ProjectWorkspaceTab? = nil
    var onOpenChat: (String) -> Void = { _ in }
    var onOpenWorkflow: (String) -> Void = { _ in }
    var onOpenPlan: (String) -> Void = { _ in }
    var onOpenTasks: (String) -> Void = { _ in }
    var onOpenEmbed: (ProjectWorkspaceItem) -> Void = { _ in }
    var onOpenSettings: (String) -> Void = { _ in }
    var onReportIssue: (String) -> Void = { _ in }

    @State private var selectedTab: ProjectWorkspaceTab = .overview
    @State private var currentFolderID: String?
    @State private var virtualPath: String?
    @State private var fileSearch = ""
    @State private var searchPageIndex = 0
    @State private var listMode = false
    @State private var oldestFirst = false
    @State private var showCreateProject = false
    @State private var pendingProjectName = ""
    @State private var projectNameInput = ""
    @State private var inspirationIndex = 0
    @State private var showVoiceUnavailable = false
    @State private var pendingWriteMode: ProjectWorkspaceWriteMode?
    @State private var showCreateFolder = false
    @State private var pendingFolderName = ""
    @State private var editingMetadata = false
    @State private var editedName = ""
    @State private var editedDescription = ""
    @State private var showDeleteConfirmation = false
    @State private var selectedRemoteFile: ProjectRemoteEntry?
    @State private var showsFileImporter = false
    @State private var showCreateMenu = false
    @State private var showProjectMenu = false
    @State private var selectingFiles = false
    @State private var selectedStoredIDs: Set<String> = []
    @State private var selectedRemotePaths: Set<String> = []
    @State private var stagedTransfer: TransferStage?

    private struct TransferStage {
        let projectID: String
        let sourceID: String?
        let storedItems: [ProjectWorkspaceItem]
        let remotePaths: [String]
        let move: Bool
    }

    var body: some View {
        Group {
            if let project = store.selectedProject {
                projectDetail(project)
            } else {
                projectsHome
            }
        }
        .background(Color.grey10.ignoresSafeArea())
        .buttonStyle(.plain)
        .overlay { OMSheet(isPresented: $showCreateProject, title: AppStrings.projectNew) { createProjectSheet } }
        .overlay { OMSheet(isPresented: $showCreateFolder, title: AppStrings.projectCreateFolder) { createFolderSheet } }
        .overlay { OMSheet(isPresented: $editingMetadata, title: AppStrings.projectEdit) { metadataSheet } }
        .overlay {
            if let entry = selectedRemoteFile {
                OMSheet(isPresented: Binding(get: { selectedRemoteFile != nil }, set: { if !$0 { selectedRemoteFile = nil } }), title: entry.name) {
                    remoteFileSheet(entry).frame(maxHeight: 560)
                }
            }
        }
        .overlay {
            if showVoiceUnavailable {
                OMConfirmDialog(title: AppStrings.projectVoiceUnavailable, message: "", confirmTitle: AppStrings.ok,
                    onConfirm: { showVoiceUnavailable = false }, onCancel: { showVoiceUnavailable = false })
            }
        }
        .fileImporter(isPresented: $showsFileImporter, allowedContentTypes: [.item]) { result in
            guard case .success(let url) = result else { return }
            Task { await store.uploadFile(url: url, folderID: currentFolderID) }
        }
        .overlay {
            if showDeleteConfirmation {
                OMConfirmDialog(title: AppStrings.projectDeletePrompt, message: AppStrings.projectDeleteExplanation,
                    confirmTitle: AppStrings.projectDelete, isDestructive: true,
                    onConfirm: { showDeleteConfirmation = false; Task { await store.deleteSelectedProject() } },
                    onCancel: { showDeleteConfirmation = false })
            }
        }
        .onChange(of: store.selectedProjectID) { _, _ in
            projectNameInput = ""
            selectedTab = previewInitialTab ?? .overview
            currentFolderID = nil
            virtualPath = nil
            fileSearch = ""
            searchPageIndex = 0
            selectingFiles = false
            selectedStoredIDs = []
            selectedRemotePaths = []
            stagedTransfer = nil
            showCreateMenu = false
            showProjectMenu = false
        }
        .onChange(of: currentFolderID) { _, _ in fileSearch = "" }
        .onChange(of: virtualPath) { _, _ in fileSearch = "" }
        .onAppear { if let previewInitialTab { selectedTab = previewInitialTab } }
    }

    private var projectsHome: some View {
        GeometryReader { geometry in
            let narrow = geometry.size.width < 550
            ZStack(alignment: .bottom) {
                VStack(spacing: 0) {
                    projectInspirationBanner(width: geometry.size.width, height: geometry.size.height)
                    HStack {
                        Button { onReportIssue("") } label: {
                            Icon("bug", size: 23)
                                .foregroundStyle(LinearGradient.primary)
                                .frame(width: 42, height: 42)
                                .background(Color.grey10, in: Circle())
                                .shadow(color: .black.opacity(0.13), radius: 6, y: 3)
                        }
                        .accessibilityLabel(AppStrings.settingsReportIssue)
                        .accessibilityIdentifier("projects-home-report-issue")
                        Spacer()
                    }
                    .padding(.horizontal, 15)
                    .padding(.top, 10)
                    Spacer(minLength: 0)
                }

                projectsHomeCenter(compact: narrow, width: geometry.size.width)
                    .position(x: geometry.size.width / 2,
                              y: geometry.size.height * (narrow ? 0.63 : 0.675) - (narrow ? 11 : 12))

                projectHomeComposer
                    .frame(maxWidth: narrow ? .infinity : 629)
                    .padding(.horizontal, narrow ? 0 : 15)
                    .padding(.bottom, narrow ? 5 : 15)
            }
            .background(Color.grey20.ignoresSafeArea())
        }
    }

    private func projectsHomeCenter(compact: Bool, width: CGFloat) -> some View {
        VStack(spacing: compact ? 22 : 10) {
            VStack(spacing: 8) {
                Text(AppStrings.projectGreeting(greetingName))
                    .font(.custom("Lexend Deca", size: 24).weight(.semibold))
                    .foregroundStyle(Color.grey80)
                    .frame(height: compact ? 46 : 68)
                    .background {
                        Icon("project", size: compact ? 76 : 128)
                            .foregroundStyle(Color.grey30)
                            .accessibilityHidden(true)
                    }
                Text(AppStrings.projectTagline)
                    .font(.omP).fontWeight(.semibold)
                    .foregroundStyle(Color.grey60)
            }
            .multilineTextAlignment(.center)
            .accessibilityIdentifier("projects-home-greeting")

            if store.isLoading {
                ProgressView(AppStrings.projectLoading)
                    .frame(width: 300, height: compact ? 44 : 200)
            } else if !store.projects.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 24) {
                        ForEach(store.projects) { project in
                            projectHomeCard(project, compact: compact)
                        }
                    }
                    .padding(.horizontal, max(0, (width - 300) / 2))
                    .padding(.vertical, 8)
                }
                .accessibilityIdentifier("projects-home-recent")
            }
            errorBanner
        }
        .frame(width: width)
    }

    private var projectHomeComposer: some View {
        WorkspacePromptComposerView(
            text: $projectNameInput,
            placeholder: AppStrings.projectNamePrompt,
            submitLabel: AppStrings.projectSidebarCreate,
            submittingLabel: AppStrings.projectCreating,
            disabled: store.isSaving,
            submitting: store.isSaving,
            identifier: "project-input-composer",
            inputIdentifier: "project-input-textarea",
            submitIdentifier: "project-input-submit",
            micIdentifier: "project-input-mic",
            onSubmit: { _ in requestProjectCreation() },
            onMic: { showVoiceUnavailable = true }
        )
    }

    private func requestProjectCreation() {
        let name = projectNameInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !store.isSaving else { return }
        pendingProjectName = name
        showCreateProject = true
    }

    private var projectInspirations: [DailyInspirationData] {
        [DailyInspirationData(inspirationId: "hardcoded-project-brief",
            text: AppStrings.projectInspirationBrief, title: AppStrings.projectInspirationBriefTitle,
            category: "productivity",
            feature: DailyInspirationFeature(iconName: "folder-kanban",
                title: AppStrings.projectInspirationBriefFeatureTitle,
                description: AppStrings.projectInspirationBriefFeatureDescription)),
         DailyInspirationData(inspirationId: "hardcoded-project-milestones",
            text: AppStrings.projectInspirationMilestones, title: AppStrings.projectInspirationMilestonesTitle,
            category: "software_development",
            feature: DailyInspirationFeature(iconName: "list-checks",
                title: AppStrings.projectInspirationMilestonesFeatureTitle,
                description: AppStrings.projectInspirationMilestonesFeatureDescription)),
         DailyInspirationData(inspirationId: "hardcoded-project-assets",
            text: AppStrings.projectInspirationAssets, title: AppStrings.projectInspirationAssetsTitle,
            category: "general_knowledge",
            feature: DailyInspirationFeature(iconName: "archive",
                title: AppStrings.projectInspirationAssetsFeatureTitle,
                description: AppStrings.projectInspirationAssetsFeatureDescription))]
    }

    private func projectInspirationBanner(width: CGFloat, height: CGFloat) -> some View {
        let inspiration = projectInspirations[inspirationIndex % projectInspirations.count]
        return ZStack {
            InspirationCard(inspiration: inspiration,
                containerSize: CGSize(width: width, height: height),
                heightOverride: width < 730 ? 190 : max(240, min(420, height * 0.35)),
                ctaTitle: AppStrings.projectInspirationCTA,
                tapHint: AppStrings.projectInspirationCTA) {
                    projectNameInput = inspiration.text
                }
            HStack {
                Button {
                    inspirationIndex = (inspirationIndex + projectInspirations.count - 1) % projectInspirations.count
                } label: {
                    Icon("back", size: 17)
                        .foregroundStyle(.white)
                        .frame(width: 36, height: 36)
                }
                .accessibilityLabel(AppStrings.projectPrevious)
                Spacer()
                Button {
                    inspirationIndex = (inspirationIndex + 1) % projectInspirations.count
                } label: {
                    Icon("back", size: 17).scaleEffect(x: -1)
                        .foregroundStyle(.white)
                        .frame(width: 36, height: 36)
                }
                .accessibilityLabel(AppStrings.nextInspiration)
            }
            .padding(.horizontal, 5)
        }
        .frame(maxWidth: .infinity)
    }

    private func projectHomeCard(_ project: ProjectWorkspaceProject, compact: Bool) -> some View {
        Button { Task { await store.selectProject(project.id) } } label: {
            Group {
                if compact {
                    HStack(spacing: 12) {
                        LucideNativeIcon(project.icon, size: 18)
                        Text(project.name).font(.omP).fontWeight(.semibold).lineLimit(1)
                        Spacer(minLength: 0)
                        Icon("back", size: 16).scaleEffect(x: -1)
                    }
                    .padding(.horizontal, 20)
                    .frame(height: 44)
                } else {
                    ZStack(alignment: .bottom) {
                        HStack {
                            LucideNativeIcon(project.icon, size: 80)
                                .rotationEffect(.degrees(-15))
                                .offset(x: -10)
                            Spacer()
                            LucideNativeIcon(project.icon, size: 80)
                                .rotationEffect(.degrees(15))
                                .offset(x: 10)
                        }
                        .foregroundStyle(.white.opacity(0.3))
                        .offset(y: 8)
                        .accessibilityHidden(true)
                        VStack(spacing: 10) {
                            LucideNativeIcon(project.icon, size: 32)
                            Text(project.name).font(.omP).fontWeight(.bold).lineLimit(2)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                    .frame(height: 200)
                }
            }
            .foregroundStyle(.white)
            .frame(width: 300)
            .background { ProjectContinueCardBackground(showOrbs: !compact, height: compact ? 44 : 200) }
            .clipShape(RoundedRectangle(cornerRadius: compact ? 32 : 30))
            .shadow(color: .black.opacity(0.16), radius: 12, y: 8)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("project-card-\(project.id)")
    }

    private func projectDetail(_ project: ProjectWorkspaceProject) -> some View {
        GeometryReader { geometry in
            let compact = geometry.size.width <= 800
            let panelWidth = min(1024, max(0, geometry.size.width - (compact ? 8 : min(40, max(16, geometry.size.width * 0.05)))))
            ScrollView {
                VStack(spacing: 0) {
                    header(project, width: geometry.size.width, height: geometry.size.height)
                    tabs.padding(.top, .spacing10)
                    Group {
                        switch selectedTab {
                        case .overview: overviewPanel(project, width: panelWidth)
                        case .files: filesPanel(project, compact: compact)
                        case .tasks: tasksPanel(project)
                        }
                    }
                    .frame(width: panelWidth)
                    .padding(.bottom, .spacing8)
                    errorBanner.padding(.horizontal, .spacing8)
                }
                .frame(maxWidth: .infinity)
            }
        }
    }

    private func header(_ project: ProjectWorkspaceProject, width: CGFloat, height: CGFloat) -> some View {
        ZStack {
            GeometryReader { geometry in
                projectHeaderBackground(size: geometry.size)
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
            VStack(spacing: 18) {
                HStack(alignment: .top) {
                    Button { onReportIssue(project.id) } label: {
                        HStack(spacing: 7) {
                            Icon("bug", size: 22)
                            if width >= 730 {
                                Text(AppStrings.settingsReportIssue).font(.omSmall).fontWeight(.bold)
                            }
                        }
                        .foregroundStyle(.white)
                        .frame(height: 44)
                        .padding(.horizontal, width >= 730 ? 11 : 11)
                        .background(.white.opacity(0.22), in: Capsule())
                    }
                    .accessibilityLabel(AppStrings.settingsReportIssue)
                    .accessibilityIdentifier("project-report-issue")
                    Button { showProjectMenu.toggle() } label: {
                        ZStack {
                            Circle().fill(.white.opacity(0.22))
                            Icon("more", size: 22)
                                .foregroundStyle(.white)
                                .allowsHitTesting(false)
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(.interaction, Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityElement(children: .ignore)
                    .accessibilityAddTraits(.isButton)
                    .accessibilityLabel(AppStrings.projectSettings)
                    .accessibilityValue(showProjectMenu ? "expanded" : "collapsed")
                    .accessibilityIdentifier("project-more-button")
                    Spacer()
                    Text(AppStrings.projectLabel).font(.omSmall).fontWeight(.bold)
                    Spacer()
                    Button { Task { await store.selectProject(nil) } } label: {
                        Icon("close", size: 22)
                            .foregroundStyle(.white)
                            .frame(width: 44, height: 44)
                            .background(.white.opacity(0.22), in: Circle())
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("project-close-button")
                }
                Spacer(minLength: 0)
                Button {
                    guard project.permissions.update else { return }
                    editedName = project.name
                    editedDescription = project.description
                    editingMetadata = true
                } label: {
                    VStack(spacing: 14) {
                        LucideNativeIcon(project.icon, size: 44)
                        Text(project.name).font(.omH2).fontWeight(.bold).multilineTextAlignment(.center)
                        if !project.description.isEmpty {
                            Text(project.description).font(.omP).fontWeight(.semibold)
                                .multilineTextAlignment(.center).lineLimit(4)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .foregroundStyle(.white)
                }
                .buttonStyle(.plain)
                .disabled(!project.permissions.update)
                .accessibilityIdentifier("project-header-edit")
                Spacer(minLength: 0)
                Text(projectStartedLabel(project.createdAt))
                    .font(.omSmall).fontWeight(.bold)
            }
            .foregroundStyle(.white)
            .padding(16)
        }
        .frame(maxWidth: .infinity)
        // ProjectWorkspaceHeader: clamp(18rem, 46vh, 26.25rem); mobile 16.25rem.
        .frame(height: width < 730 ? 260 : min(420, max(288, height * 0.46)))
        .clipShape(UnevenRoundedRectangle(topLeadingRadius: 0, bottomLeadingRadius: .radius5,
                                        bottomTrailingRadius: .radius5, topTrailingRadius: 0))
        .overlay(alignment: .topLeading) {
            if showProjectMenu {
                VStack(spacing: 0) {
                    if project.permissions.settings {
                        createMenuAction(AppStrings.projectSettings, icon: "settings", identifier: "project-menu-settings") {
                            showProjectMenu = false; onOpenSettings(project.id)
                        }
                    }
                    if project.permissions.update {
                        createMenuAction(AppStrings.projectEdit, icon: "edit", identifier: "project-menu-edit") {
                            showProjectMenu = false
                            editedName = project.name; editedDescription = project.description
                            editingMetadata = true
                        }
                    }
                    if project.permissions.delete {
                        createMenuAction(AppStrings.projectDelete, icon: "delete", identifier: "project-menu-delete") {
                            showProjectMenu = false; showDeleteConfirmation = true
                        }
                    }
                }
                .frame(width: 240)
                .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
                .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25))
                .shadow(color: .black.opacity(0.18), radius: 12, y: 4)
                .padding(.top, 64).padding(.leading, .spacing8)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("project-action-menu")
            }
        }
        .zIndex(3)
    }

    private func projectHeaderBackground(size: CGSize) -> some View {
        let weather = AppGradientPalette.colors(for: "weather")
        let primary = AppGradientPalette.colors(for: "primary")
        let base = cssGradientPoints(angle: 135, size: size)
        let shade = cssGradientPoints(angle: 115, size: size)
        let radialX = size.width * 0.75
        let radialY = size.height * 0.85
        let farX = max(radialX, size.width - radialX)
        let farY = max(radialY, size.height - radialY)
        let radius = sqrt(farX * farX + farY * farY) * 0.48
        return LinearGradient(colors: [mixed(weather.start, primary.start, weight: 0.78),
                                       mixed(weather.end, primary.end, weight: 0.55)],
                              startPoint: base.start, endPoint: base.end)
            .overlay {
                RadialGradient(colors: [weather.end.opacity(0.72), .clear],
                               center: .init(x: 0.75, y: 0.85), startRadius: 0, endRadius: radius)
            }
            .overlay {
                LinearGradient(stops: [.init(color: Color.grey100.opacity(0.12), location: 0),
                                       .init(color: .clear, location: 0.54)],
                               startPoint: shade.start, endPoint: shade.end)
            }
    }

    // CSS angles keep their physical direction on a rectangle. SwiftUI's
    // corner-to-corner UnitPoints instead stretch that direction with aspect ratio.
    private func cssGradientPoints(angle: Double, size: CGSize) -> (start: UnitPoint, end: UnitPoint) {
        let radians = angle * .pi / 180
        let dx = CGFloat(sin(radians)), dy = -CGFloat(cos(radians))
        let length = abs(size.width * dx) + abs(size.height * dy)
        let offsetX = dx * length / (2 * max(1, size.width))
        let offsetY = dy * length / (2 * max(1, size.height))
        return (.init(x: 0.5 - offsetX, y: 0.5 - offsetY),
                .init(x: 0.5 + offsetX, y: 0.5 + offsetY))
    }

    /// Mirror CSS color-mix(in srgb, ...); components come from generated tokens.
    private func mixed(_ first: Color, _ second: Color, weight: Double) -> Color {
        let a = first.resolve(in: environment)
        let b = second.resolve(in: environment)
        return Color(red: Double(a.red) * weight + Double(b.red) * (1 - weight),
                     green: Double(a.green) * weight + Double(b.green) * (1 - weight),
                     blue: Double(a.blue) * weight + Double(b.blue) * (1 - weight))
    }

    private func projectStartedLabel(_ timestamp: Int) -> String {
        let date = Date(timeIntervalSince1970: TimeInterval(timestamp))
        let time = date.formatted(date: .omitted, time: .shortened)
        if Calendar.current.isDateInToday(date) { return AppStrings.projectStartedToday(time) }
        return AppStrings.projectStarted(date.formatted(date: .abbreviated, time: .shortened))
    }

    private var tabs: some View {
        HStack(spacing: 0) {
            ForEach(ProjectWorkspaceTab.allCases) { tab in
                Button {
                    selectedTab = tab
                } label: {
                    Icon(tab == .overview ? "project" : tab == .files ? "files" : "projectmanagement", size: 21)
                        .foregroundStyle(selectedTab == tab ? Color.fontButton : Color.fontSecondary)
                        .frame(maxWidth: .infinity)
                        .frame(height: 44.8)
                        .background(selectedTab == tab ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.clear), in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(tab.title)
                .accessibilityAddTraits(selectedTab == tab ? .isSelected : [])
                .accessibilityIdentifier("project-tab-\(tab.rawValue)")
            }
        }
        .frame(width: 220)
        .background(Color.grey0, in: Capsule())
        .offset(y: 14)
        .zIndex(2)
    }

    private func overviewPanel(_ project: ProjectWorkspaceProject, width: CGFloat) -> some View {
        VStack(spacing: 18) {
            switch store.readme {
            case .loading:
                ProgressView(AppStrings.projectOverviewLoading)
                    .frame(maxWidth: .infinity, minHeight: 260)
            case .ready(let readme):
                VStack(alignment: .leading, spacing: 12) {
                    if readme.truncated {
                        Text(AppStrings.projectOverviewTruncated)
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                    Text(ProjectWorkspaceMarkdown.safeAttributed(readme.markdown))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("project-readme-content")
            case .empty:
                VStack(spacing: 24) {
                    Text(AppStrings.projectOverviewEmpty)
                        .font(.omP).foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("project-readme-empty")
                    HStack(spacing: 0) {
                        Button { showsFileImporter = true } label: {
                            VStack(spacing: 8) { Icon("upload", size: 25); Text(AppStrings.projectUpload) }
                                .frame(width: 122, height: 120)
                        }
                        .accessibilityIdentifier("project-overview-upload")
                        Divider().frame(height: 120)
                        Button { showCreateMenu.toggle() } label: {
                            VStack(spacing: 8) { Icon("create", size: 25); Text(AppStrings.projectCreateAction) }
                                .frame(width: 122, height: 120)
                        }
                        .accessibilityIdentifier("project-overview-create")
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Color.fontSecondary)
                }
                .frame(maxWidth: .infinity, minHeight: 270)
            case .unavailable:
                VStack(spacing: 12) {
                    Text(AppStrings.projectSourceNeeded)
                    Button(AppStrings.retry) { Task { await store.reloadSelected() } }.buttonStyle(OMSecondaryButtonStyle())
                }
                .frame(maxWidth: .infinity, minHeight: 270)
            case .failed:
                VStack(spacing: 12) {
                    Text(AppStrings.projectOverviewFailed)
                    Button(AppStrings.retry) { Task { await store.reloadSelected() } }.buttonStyle(OMSecondaryButtonStyle())
                }
                .frame(maxWidth: .infinity, minHeight: 270)
            }
        }
        .padding(width <= 800 ? .spacing8 : .spacing24)
        .frame(maxWidth: .infinity)
        .frame(minHeight: width <= 800 ? 288 : 448)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-overview-panel")
        .overlay(alignment: .bottom) {
            if showCreateMenu {
                projectCreateMenu(project).frame(maxWidth: 386)
                    .padding(.horizontal, .spacing6).padding(.bottom, .spacing8)
            }
        }
    }

    private func projectCreateMenu(_ project: ProjectWorkspaceProject) -> some View {
        VStack(spacing: 0) {
            createMenuAction(AppStrings.newChat, icon: "chat", subtitle: AppStrings.localized("projects.workspace_new_chat_description"), identifier: "project-create-chat") {
                showCreateMenu = false; onOpenChat(project.id)
            }
            Divider()
            createMenuAction(AppStrings.projectNewWorkflow, icon: "workflow", subtitle: AppStrings.localized("projects.workspace_new_workflow_description"), identifier: "project-create-workflow") {
                showCreateMenu = false; onOpenWorkflow(project.id)
            }
            Divider()
            createMenuAction(AppStrings.projectNewPlan, icon: "planning", subtitle: AppStrings.localized("projects.workspace_new_plan_description"), identifier: "project-create-plan") {
                showCreateMenu = false; onOpenPlan(project.id)
            }
        }
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25))
        .shadow(color: .black.opacity(0.18), radius: 12, y: 4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-create-menu")
    }

    private func createMenuAction(_ title: String, icon: String, subtitle: String? = nil,
                                  identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing6) {
                Icon(icon, size: 21)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(title).font(.omSmall).fontWeight(.semibold)
                    if let subtitle { Text(subtitle).font(.omXs).foregroundStyle(Color.fontSecondary) }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing6)
            .frame(minHeight: 41)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.fontPrimary)
        .accessibilityIdentifier(identifier)
    }

    private func tasksPanel(_ project: ProjectWorkspaceProject) -> some View {
        Group {
            if let tasksStore {
                TasksWorkspaceView(store: tasksStore, compactProjectBoard: true,
                    onOpenProject: { _ in },
                    onOpenChat: onOpenChat)
                    .frame(height: 720)
            } else {
                VStack(spacing: 14) {
                    Icon("projectmanagement", size: 38).foregroundStyle(Color.fontSecondary)
                    Text(AppStrings.projectTasksHeading).font(.omH3)
                    Button(AppStrings.projectOpenTasks) { onOpenTasks(project.id) }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .accessibilityIdentifier("project-open-tasks")
                }
                .frame(maxWidth: .infinity, minHeight: 300)
            }
        }
        .frame(maxWidth: .infinity)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: 22))
    }

    private var projectFileCount: String {
        store.searchActive
            ? AppStrings.projectCount(store.searchResults.count, key: "workspace_search_results_count")
            : store.activeRemoteSourceID == nil
            ? AppStrings.projectBrowserCount(folders: store.folders.count, files: store.items.count)
            : AppStrings.projectCount(store.remoteEntries.count, key: "workspace_remote_entries_count")
    }

    @ViewBuilder
    private func filesSummary(compact: Bool) -> some View {
        if compact {
            VStack(spacing: 20) {
                HStack {
                    Text(projectFileCount).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    Spacer()
                    projectFileSort(compact: true)
                }
                projectFileSearch(compact: true)
            }
        } else {
            GeometryReader { geometry in
                let searchWidth = min(320, max(192, geometry.size.width / 3))
                let sideWidth = max(0, (geometry.size.width - searchWidth - 32) / 2)
                HStack(spacing: 16) {
                    Text(projectFileCount).font(.omXs).fontWeight(.bold)
                        .frame(width: sideWidth, alignment: .leading)
                    projectFileSearch(compact: false).frame(width: searchWidth)
                    projectFileSort(compact: false).frame(width: sideWidth, alignment: .trailing)
                }
                .foregroundStyle(Color.fontSecondary)
            }
            .frame(height: 40)
        }
    }

    private func projectFileSearch(compact: Bool) -> some View {
        HStack(spacing: 6) {
            Icon("search", size: 20).foregroundStyle(Color.fontSecondary)
            TextField(compact ? AppStrings.projectSearchFiles : AppStrings.search, text: $fileSearch)
                .textFieldStyle(.plain)
                .font(compact ? .omSmall : .omXs)
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .autocorrectionDisabled()
                .accessibilityLabel(AppStrings.projectSearchFiles)
                .accessibilityIdentifier("project-files-search")
                .frame(maxWidth: compact ? .infinity : 80)
        }
        .padding(compact ? 12 : 0)
        .background(compact ? Color.grey10 : Color.clear, in: RoundedRectangle(cornerRadius: 14))
    }

    private func projectFileSort(compact: Bool) -> some View {
        let namesOnly = store.activeRemoteSourceID != nil || store.searchActive
        return Button { oldestFirst.toggle() } label: {
            HStack(spacing: 8) {
                if !compact {
                    Text(namesOnly ? AppStrings.projectSortName : oldestFirst
                         ? AppStrings.projectSortOldest : AppStrings.projectSortNewest)
                        .font(.omXs)
                }
                Icon("sort", size: 18)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: compact ? 44 : 40, height: compact ? 44 : 40)
                    .background(compact ? Color.clear : Color.grey10, in: Circle())
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(namesOnly)
        .accessibilityIdentifier("project-files-sort")
        .accessibilityLabel(namesOnly ? AppStrings.projectSortName
            : oldestFirst ? AppStrings.projectShowNewest : AppStrings.projectShowOldest)
    }

    @ViewBuilder
    private func fileSelectionToolbar(_ project: ProjectWorkspaceProject, compact: Bool) -> some View {
        if compact {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    projectEntryCount
                    Spacer()
                    fileSelectionActions(project)
                }
                fileViewModeControls
            }
        } else {
            HStack(spacing: 8) {
                projectEntryCount
                Spacer()
                fileSelectionActions(project)
                fileViewModeControls
            }
        }
    }

    private var projectEntryCount: some View {
        Text(AppStrings.projectCount(visibleEntryCount, key: "workspace_entries_count"))
            .font(.omSmall).fontWeight(.bold)
    }

    private func fileSelectionActions(_ project: ProjectWorkspaceProject) -> some View {
        HStack(spacing: 6) {
            if selectingFiles {
                Text(AppStrings.projectCount(selectedStoredIDs.count + selectedRemotePaths.count,
                    key: "workspace_selected_count"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                Button(AppStrings.projectCopy) { stageSelection(move: false, project: project) }
                    .disabled(selectedStoredIDs.isEmpty && selectedRemotePaths.isEmpty)
                Button(AppStrings.projectMove) { stageSelection(move: true, project: project) }
                    .disabled(selectedStoredIDs.isEmpty && selectedRemotePaths.isEmpty)
                Button(AppStrings.cancel) { cancelSelection() }
            } else {
                if let stagedTransfer, stagedTransfer.projectID == project.id,
                   stagedTransfer.sourceID == store.activeRemoteSourceID,
                   (stagedTransfer.sourceID != nil || virtualPath == nil) {
                    Button(stagedTransfer.move ? AppStrings.projectMoveHere : AppStrings.projectPaste) {
                        commitTransfer(stagedTransfer)
                    }
                    .disabled(store.isSaving)
                    .accessibilityIdentifier("project-file-commit-transfer")
                }
                Button(AppStrings.projectSelect) {
                    selectingFiles = true
                    selectedStoredIDs = []
                    selectedRemotePaths = []
                }
                .accessibilityIdentifier("project-file-select")
            }
        }
        .buttonStyle(ProjectFileSelectionButtonStyle())
    }

    private var fileViewModeControls: some View {
        HStack(spacing: .spacing2) {
            projectViewModeButton(AppStrings.projectTile, list: false)
            projectViewModeButton(AppStrings.projectList, list: true)
        }
        .padding(.spacing2)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius4))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-files-view-mode")
    }

    private func filesPanel(_ project: ProjectWorkspaceProject, compact: Bool) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            filesSummary(compact: compact)
            fileSelectionToolbar(project, compact: compact)
            if store.activeRemoteSourceID != nil || currentFolderID != nil || virtualPath != nil {
                HStack(spacing: 8) {
                    Button(AppStrings.projectFiles) { currentFolderID = nil; virtualPath = nil; store.closeRemoteSource() }
                    if let source = store.sources.first(where: { $0.id == store.activeRemoteSourceID }) {
                        Text("/")
                        Button(source.name) { Task { await store.browseRemote(path: ".") } }
                        if store.remotePath != "." {
                            Text("/")
                            Text(store.remotePath)
                        }
                    }
                    if let currentFolderID, let folder = store.folders.first(where: { $0.id == currentFolderID }) {
                        Text("/")
                        Text(folder.name)
                    }
                    if let virtualPath {
                        ForEach(Array(virtualPath.split(separator: "/").enumerated()), id: \.offset) { index, segment in
                            Text("/")
                            Button(String(segment)) {
                                self.virtualPath = virtualPath.split(separator: "/")
                                    .prefix(index + 1).joined(separator: "/")
                            }
                        }
                    }
                }
                .font(.omSmall)
            }

            if store.isLoadingDetail || (store.isLoadingRemote && !store.searchActive) {
                ProgressView(AppStrings.projectFilesLoading).frame(maxWidth: .infinity, minHeight: 240)
            } else if store.searchActive {
                searchResultsPanel(project)
            } else {
                let columns = [GridItem(.adaptive(minimum: listMode ? 320 : 260), spacing: 16)]
                if showCreateMenu { fileActions(project, compact: compact) }
                LazyVGrid(columns: columns, spacing: 16) {
                    if !showCreateMenu { fileActions(project, compact: compact) }
                    if store.activeRemoteSourceID != nil {
                        ForEach(store.remoteEntries) { entry in remoteEntryCard(entry) }
                    } else {
                        ForEach(visibleFolders) { folder in folderCard(folder) }
                        ForEach(visibleVirtualFolders, id: \.path) { folder in virtualFolderCard(folder) }
                        ForEach(visibleSources) { source in sourceCard(source) }
                        ForEach(visibleItems) { item in itemCard(item) }
                    }
                }
            }
            if let remoteError = store.remoteError {
                Text(remoteError).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("project-remote-error")
            }
        }
        .padding(compact ? .spacing8 : .spacing24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-files-panel")
        .task(id: fileSearch) {
            searchPageIndex = 0
            store.cancelSearch()
            guard !fileSearch.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return
            }
            try? await Task.sleep(for: .milliseconds(600))
            guard !Task.isCancelled else { return }
            await store.searchFiles(fileSearch,
                prioritySourceID: store.activeRemoteSourceID,
                priorityPath: store.remotePath)
        }
    }

    private func projectViewModeButton(_ title: String, list: Bool) -> some View {
        Button { listMode = list } label: {
            Text(title)
                .font(.omP.weight(.medium))
                .foregroundStyle(listMode == list ? Color.fontPrimary : Color.fontSecondary)
                .padding(.horizontal, .spacing5)
                .frame(minWidth: 112, minHeight: 41)
                // The inactive web button is transparent over grey10. Painting
                // that same effective color gives the plain native button an
                // opaque hit surface across its complete segment.
                .background(listMode == list ? Color.grey0 : Color.grey10,
                    in: RoundedRectangle(cornerRadius: .radius8))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        // buttons.css applies the shared drop-shadow filter to these controls.
        .shadow(color: .black.opacity(0.25), radius: 4, y: 4)
        .accessibilityIdentifier(list ? "project-files-view-list" : "project-files-view-tile")
        .accessibilityAddTraits(listMode == list ? .isSelected : [])
    }

    private var orderedSearchResults: [ProjectWorkspaceSearchEntry] {
        store.searchResults.filter(isCurrentSearchResult) +
            store.searchResults.filter { !isCurrentSearchResult($0) }
    }

    private var searchPage: [ProjectWorkspaceSearchEntry] {
        let start = searchPageIndex * 48
        guard start < orderedSearchResults.count else { return [] }
        return Array(orderedSearchResults[start..<min(start + 48, orderedSearchResults.count)])
    }

    private func isCurrentSearchResult(_ result: ProjectWorkspaceSearchEntry) -> Bool {
        switch result {
        case .remote(let sourceID, let entry):
            return sourceID == store.activeRemoteSourceID && parentPath(entry.path) == store.remotePath
        case .folder(let folder):
            return store.activeRemoteSourceID == nil && virtualPath == nil &&
                folder.parentHash == currentFolderID.map(store.folderHash)
        case .virtualFolder(let path, _):
            return store.activeRemoteSourceID == nil && currentFolderID == nil &&
                parentPath(path) == (virtualPath ?? ".")
        case .item(let item):
            guard store.activeRemoteSourceID == nil else { return false }
            if let currentFolderID { return item.folderHash == store.folderHash(currentFolderID) }
            guard item.folderHash == nil else { return false }
            if item.metadata["source"] == "hosted_project_file", let path = item.filePath {
                return parentPath(path) == (virtualPath ?? ".")
            }
            return virtualPath == nil
        }
    }

    private func parentPath(_ path: String) -> String {
        let parts = path.split(separator: "/")
        return parts.count > 1 ? parts.dropLast().joined(separator: "/") : "."
    }

    private func searchResultsPanel(_ project: ProjectWorkspaceProject) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if store.isSearching {
                ProgressView(AppStrings.projectSearching)
                    .accessibilityIdentifier("project-search-loading")
            }
            if let error = store.searchError {
                Text(error).font(.omSmall).foregroundStyle(Color.error)
            }
            Text(AppStrings.projectSearchCurrent).font(.omP).fontWeight(.bold)
                .accessibilityIdentifier("project-search-current-heading")
            let current = searchPage.filter(isCurrentSearchResult)
            if current.isEmpty && !store.isSearching && searchPageIndex == 0 {
                Text(AppStrings.projectSearchCurrentEmpty).font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
            searchCardGrid(current)
            Text(AppStrings.projectSearchAcross(project.name)).font(.omP).fontWeight(.bold)
                .accessibilityIdentifier("project-search-across-heading")
            let across = searchPage.filter { !isCurrentSearchResult($0) }
            if across.isEmpty && !store.isSearching && searchPageIndex == 0 {
                Text(AppStrings.projectSearchAcrossEmpty).font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
            searchCardGrid(across)
            if store.searchOmitted > 0 {
                Text(AppStrings.projectRemoteLimited).font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
            if orderedSearchResults.count > 48 {
                HStack {
                    Button(AppStrings.projectPrevious) { searchPageIndex -= 1 }
                        .disabled(searchPageIndex == 0)
                    Spacer()
                    Text("\(searchPageIndex + 1) / \((orderedSearchResults.count + 47) / 48)")
                        .font(.omSmall)
                    Spacer()
                    Button(AppStrings.projectNext) { searchPageIndex += 1 }
                        .disabled((searchPageIndex + 1) * 48 >= orderedSearchResults.count)
                }
            }
        }
    }

    private func searchCardGrid(_ entries: [ProjectWorkspaceSearchEntry]) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: listMode ? 320 : 260), spacing: 16)],
                  spacing: 16) {
            ForEach(entries) { entry in searchCard(entry) }
        }
    }

    @ViewBuilder
    private func searchCard(_ result: ProjectWorkspaceSearchEntry) -> some View {
        switch result {
        case .folder(let folder): folderCard(folder)
        case .item(let item): itemCard(item)
        case .virtualFolder(let path, let name):
            virtualFolderCard(VirtualFolder(name: name, path: path))
        case .remote(let sourceID, let entry):
            Button {
                let projectID = store.selectedProjectID
                Task {
                    await store.openRemoteSource(sourceID)
                    guard store.selectedProjectID == projectID,
                          store.activeRemoteSourceID == sourceID else { return }
                    if entry.kind == "directory" {
                        await store.browseRemote(path: entry.path)
                    } else {
                        selectedRemoteFile = entry
                        store.clearRemoteText()
                        if isTextPreviewable(entry.name) { await store.openRemoteText(entry.path) }
                    }
                    fileSearch = ""
                }
            } label: {
                VStack(alignment: .leading, spacing: 10) {
                    Icon(entry.kind == "directory" ? "files" : iconName(for: entry.name), size: 28)
                    Text(entry.name).font(.omP).fontWeight(.bold).lineLimit(2)
                    Text((store.sources.first(where: { $0.id == sourceID })?.name ?? sourceID) +
                         " / " + entry.path)
                        .font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(2)
                }
                .frame(maxWidth: .infinity, minHeight: listMode ? 78 : 190, alignment: .leading)
                .padding(16)
                .background(Color.grey10, in: RoundedRectangle(cornerRadius: 22))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("project-search-result-\(result.id)")
        }
    }

    private func fileActions(_ project: ProjectWorkspaceProject, compact: Bool) -> some View {
        Group {
            if showCreateMenu {
                if compact {
                    VStack(spacing: 0) {
                        fileActionTray(project, height: 128)
                        projectFileCreateOptions(project, height: 112)
                            .overlay(alignment: .top) { Color.grey30.frame(height: 1) }
                    }
                } else {
                    GeometryReader { geometry in
                        let actionsWidth = max(256, geometry.size.width / 3)
                        HStack(spacing: 0) {
                            fileActionTray(project, height: 160).frame(width: actionsWidth)
                            projectFileCreateOptions(project, height: 160)
                                .frame(width: max(0, geometry.size.width - actionsWidth))
                                .overlay(alignment: .leading) { Color.grey30.frame(width: 1) }
                        }
                    }
                    .frame(height: 160)
                }
            } else {
                fileActionTray(project, height: listMode ? 78 : compact ? 128 : 160)
            }
        }
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
    }

    private func fileActionTray(_ project: ProjectWorkspaceProject, height: CGFloat) -> some View {
        HStack(spacing: 0) {
            Button {
                Task {
                    if store.activeRemoteSourceID == nil { await store.reloadSelected() }
                    else { await store.browseRemote(path: store.remotePath) }
                }
            } label: {
                VStack(spacing: 8) {
                    Icon("reload", size: 28)
                    Text(AppStrings.projectSync).font(.omSmall).fontWeight(.bold)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .disabled(store.isSaving)
            .accessibilityIdentifier("project-files-sync")
            Divider().padding(.vertical, 30)
            Button { showsFileImporter = true } label: {
                VStack(spacing: 8) {
                    Icon("upload", size: 28)
                    Text(AppStrings.projectUpload).font(.omSmall).fontWeight(.bold)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .disabled(store.isSaving || !(project.permissions.manageOwnItems || project.permissions.manageAnyItems))
            .accessibilityIdentifier("project-upload-button")
            Divider().padding(.vertical, 30)
            Button { showCreateMenu.toggle() } label: {
                VStack(spacing: 8) {
                    Icon("create", size: 28)
                    Text(AppStrings.projectCreateAction).font(.omSmall).fontWeight(.bold)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
            }
            .accessibilityIdentifier("project-files-create")
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.fontSecondary)
        .frame(maxWidth: .infinity)
        .frame(height: height)
        .background(Color.grey10)
    }

    // Rendered ProjectsPage folder-create-menu: three equal columns, bare
    // 28-point icons above labels, no overview dropdown border or subtitles.
    private func projectFileCreateOptions(_ project: ProjectWorkspaceProject, height: CGFloat) -> some View {
        HStack(spacing: 0) {
            projectFileCreateOption(AppStrings.newChat, icon: "chat", identifier: "project-create-chat", height: height) {
                showCreateMenu = false; onOpenChat(project.id)
            }
            projectFileCreateOption(AppStrings.projectNewWorkflow, icon: "workflow", identifier: "project-create-workflow", height: height) {
                showCreateMenu = false; onOpenWorkflow(project.id)
            }
            .overlay(alignment: .leading) { Color.grey30.frame(width: 1) }
            projectFileCreateOption(AppStrings.projectNewPlan, icon: "planning", identifier: "project-create-plan", height: height) {
                showCreateMenu = false; onOpenPlan(project.id)
            }
            .overlay(alignment: .leading) { Color.grey30.frame(width: 1) }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-create-menu")
    }

    private func projectFileCreateOption(_ title: String, icon: String, identifier: String,
                                         height: CGFloat, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 8) {
                Icon(icon, size: 28)
                Text(title).font(.omP).fontWeight(.bold).multilineTextAlignment(.center)
            }
            .padding(12)
            .frame(maxWidth: .infinity)
            .frame(height: height)
            .background(Color.grey10)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.fontSecondary)
        .accessibilityIdentifier(identifier)
    }

    private var visibleFolders: [ProjectWorkspaceFolder] {
        let values = store.childFolders(parentID: currentFolderID)
        return filterAndSort(values, name: { $0.name }, timestamp: { $0.createdAt })
    }

    private var visibleSources: [ProjectWorkspaceSource] {
        guard currentFolderID == nil, virtualPath == nil else { return [] }
        return store.sources.filter { fileSearch.isEmpty || $0.name.localizedCaseInsensitiveContains(fileSearch) }
    }

    private var visibleItems: [ProjectWorkspaceItem] {
        let values = store.childItems(parentID: currentFolderID).filter { item in
            guard item.metadata["source"] == "hosted_project_file", let path = item.filePath,
                  currentFolderID == nil else { return virtualPath == nil }
            let prefix = virtualPath.map { $0 + "/" } ?? ""
            guard path.hasPrefix(prefix) else { return false }
            return !path.dropFirst(prefix.count).contains("/")
        }
        return filterAndSort(values, name: { $0.name }, timestamp: { $0.createdAt })
    }

    private struct VirtualFolder {
        let name: String
        let path: String
    }

    private var visibleVirtualFolders: [VirtualFolder] {
        guard currentFolderID == nil else { return [] }
        let prefix = virtualPath.map { $0 + "/" } ?? ""
        var result: [String: VirtualFolder] = [:]
        for item in store.items where item.folderHash == nil && item.metadata["source"] == "hosted_project_file" {
            guard let path = item.filePath, path.hasPrefix(prefix) else { continue }
            let remainder = String(path.dropFirst(prefix.count))
            guard let component = remainder.split(separator: "/").first,
                  remainder.contains("/") else { continue }
            let name = String(component)
            guard fileSearch.isEmpty || name.localizedCaseInsensitiveContains(fileSearch) else { continue }
            let folderPath = prefix + name
            result[folderPath] = VirtualFolder(name: name, path: folderPath)
        }
        return result.values.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    private var visibleEntryCount: Int {
        store.activeRemoteSourceID == nil ? visibleFolders.count + visibleVirtualFolders.count + visibleSources.count + visibleItems.count
            : store.remoteEntries.count
    }

    private func filterAndSort<T>(_ values: [T], name: (T) -> String, timestamp: (T) -> Int) -> [T] {
        values.filter { fileSearch.isEmpty || name($0).localizedCaseInsensitiveContains(fileSearch) }
            .sorted { oldestFirst ? timestamp($0) < timestamp($1) : timestamp($0) > timestamp($1) }
    }

    private func folderCard(_ folder: ProjectWorkspaceFolder) -> some View {
        let children = store.childFolders(parentID: folder.id)
        let files = store.childItems(parentID: folder.id)
        return Button { currentFolderID = folder.id } label: {
            VStack(alignment: .leading, spacing: 0) {
                if !listMode {
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(children.prefix(2)) { child in
                            HStack(spacing: 5) {
                                Icon("files", size: 14)
                                Text(child.name).lineLimit(1)
                                Spacer(minLength: 3)
                                Text(AppStrings.projectCount(store.childFolders(parentID: child.id).count +
                                    store.childItems(parentID: child.id).count, key: "workspace_items_count"))
                            }
                        }
                        ForEach(files.prefix(max(0, 3 - children.count))) { item in
                            HStack(spacing: 5) {
                                Icon(iconName(for: item.name), size: 14)
                                Text(item.name).lineLimit(1)
                                Spacer(minLength: 3)
                                if let size = item.metadata["size_bytes"].flatMap(Int.init) {
                                    Text(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))
                                } else if let kind = item.metadata["file_type"] {
                                    Text(kind)
                                }
                            }
                        }
                    }
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, 18)
                    .padding(.top, 18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Spacer(minLength: 0)
                }
                HStack(spacing: 10) {
                    Icon("files", size: 27)
                        .foregroundStyle(.white)
                        .frame(width: 48, height: 48)
                        .background(LinearGradient.appWeather, in: Circle())
                    VStack(alignment: .leading, spacing: 2) {
                        Text(folder.name).font(.omP).fontWeight(.bold).lineLimit(1)
                        Text(AppStrings.projectCount(children.count + files.count,
                            key: "workspace_files_count"))
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, listMode ? 9 : 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.grey10.opacity(0.55), in: RoundedRectangle(cornerRadius: 20))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: listMode ? 78 : 190)
            .background(Color.grey20, in: RoundedRectangle(cornerRadius: 22))
            .foregroundStyle(Color.fontPrimary)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("project-folder-\(folder.id)")
    }

    private func virtualFolderCard(_ folder: VirtualFolder) -> some View {
        Button {
            currentFolderID = nil
            virtualPath = folder.path
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                Icon("files", size: 27)
                Text(folder.name).font(.omP).fontWeight(.bold).lineLimit(2)
                Spacer(minLength: 0)
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: listMode ? 78 : 190)
            .background(Color.grey20, in: RoundedRectangle(cornerRadius: 22))
            .foregroundStyle(Color.fontPrimary)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("project-virtual-folder-\(folder.path)")
    }

    private func sourceCard(_ source: ProjectWorkspaceSource) -> some View {
        Button { Task { await store.openRemoteSource(source.id) } } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Icon("files", size: 28)
                    Spacer()
                    Icon("cloud", size: 16)
                        .frame(width: 27, height: 27)
                        .background(Color.grey0, in: Circle())
                        .accessibilityLabel(AppStrings.projectStoredRemotely)
                }
                Text(source.name).font(.omP).fontWeight(.bold).lineLimit(2)
                Text(AppStrings.projectSourceStatus(source.status))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                ForEach(store.sourceRootPreviews[source.id] ?? []) { entry in
                    HStack(spacing: 6) {
                        Icon(entry.kind == "directory" ? "files" : iconName(for: entry.name), size: 13)
                        Text(entry.name).lineLimit(1)
                    }
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                }
                Spacer(minLength: 0)
                Text(AppStrings.projectConnectedSource).font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: listMode ? 78 : 190)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(Color.grey20))
            .foregroundStyle(Color.fontPrimary)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("project-source-\(source.id)")
    }

    private func remoteEntryCard(_ entry: ProjectRemoteEntry) -> some View {
        Button {
            if selectingFiles {
                if selectedRemotePaths.contains(entry.path) { selectedRemotePaths.remove(entry.path) }
                else { selectedRemotePaths.insert(entry.path) }
                return
            }
            if entry.kind == "directory" {
                Task { await store.browseRemote(path: entry.path) }
            } else {
                selectedRemoteFile = entry
                store.clearRemoteText()
                if isTextPreviewable(entry.name) {
                    Task { await store.openRemoteText(entry.path) }
                }
            }
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Icon(entry.kind == "directory" ? "files" : iconName(for: entry.name), size: 30)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                    Icon("cloud", size: 14)
                        .frame(width: 24, height: 24)
                        .background(Color.grey0, in: Circle())
                        .accessibilityLabel(AppStrings.projectStoredRemotely)
                }
                Spacer(minLength: 0)
                Text(entry.name).font(.omP).fontWeight(.bold).lineLimit(2)
                if entry.kind == "directory" {
                    Text(AppStrings.projectCount(entry.childFileCount ?? 0,
                        key: entry.childSummaryTruncated ? "workspace_files_or_more" : "workspace_files_count"))
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                } else if let size = entry.sizeBytes {
                    Text(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: listMode ? 78 : 190)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(
                selectedRemotePaths.contains(entry.path) ? Color.buttonPrimary : Color.grey20,
                lineWidth: selectedRemotePaths.contains(entry.path) ? 2 : 1))
            .foregroundStyle(Color.fontPrimary)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("project-remote-entry-\(entry.path)")
    }

    private func isTextPreviewable(_ name: String) -> Bool {
        let lower = name.lowercased()
        return [".md", ".mdx", ".txt", ".rst", ".swift", ".ts", ".tsx", ".js", ".json",
                ".py", ".rs", ".svelte", ".html", ".css", ".yaml", ".yml", ".sh"]
            .contains(where: lower.hasSuffix)
    }

    private func remoteFileSheet(_ entry: ProjectRemoteEntry) -> some View {
        ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(entry.path).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    if let size = entry.sizeBytes {
                        Text(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))
                            .font(.omSmall)
                    }
                    if store.isLoadingRemote {
                        ProgressView(AppStrings.projectRemoteOpening)
                    } else if let remoteText = store.remoteText {
                        if remoteText.truncated {
                            Text(AppStrings.localized("projects.remote_preview_truncated"))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                        Text(remoteText.content)
                            .font(.omSmall.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else if let error = store.remoteError {
                        Text(error).foregroundStyle(Color.error)
                    } else {
                        Text(AppStrings.projectRemoteOnDemand)
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                    if let url = store.remoteDownloadURL {
                        ShareLink(item: url) {
                            HStack(spacing: 8) { Icon("share", size: 18); Text(AppStrings.projectShareDownload) }
                        }
                        .accessibilityIdentifier("project-remote-share-download")
                    } else {
                        Button {
                            Task { await store.downloadRemoteFile(entry.path) }
                        } label: {
                            HStack(spacing: 8) {
                                Icon("download", size: 18)
                                Text(AppStrings.projectDownloadOriginal)
                            }
                        }
                        .disabled(store.isLoadingRemote)
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("project-remote-download")
                    }
                    if let progress = store.remoteDownloadProgress {
                        Text(AppStrings.projectDownloading(downloaded: progress.0, total: progress.1))
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                }
                .padding(20)
            }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-remote-file-detail")
        .onDisappear { store.clearRemoteDownload() }
    }

    @ViewBuilder
    private func itemCard(_ item: ProjectWorkspaceItem) -> some View {
        if !listMode, let preview = store.itemEmbedPreviews[item.id] {
            EmbedPreviewCard(embed: preview) { handleItemTap(item) }
                .overlay(RoundedRectangle(cornerRadius: 30)
                    .strokeBorder(selectedStoredIDs.contains(item.id) ? Color.buttonPrimary : .clear,
                                  lineWidth: 2))
                .accessibilityIdentifier("project-item-\(item.id)")
                .task(id: item.id) { await store.loadItemEmbedPreview(item) }
        } else {
            Button { handleItemTap(item) } label: {
            VStack(alignment: .leading, spacing: 10) {
                Icon(iconName(for: item.name), size: 31)
                    .frame(width: 56, height: 56)
                    .background(LinearGradient.appFiles, in: Circle())
                    .foregroundStyle(.white)
                Text(item.name.isEmpty ? item.targetID : item.name)
                    .font(.omP).fontWeight(.bold).lineLimit(2)
                Spacer(minLength: 0)
                Text(item.kind.capitalized).font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: listMode ? 78 : 190)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(
                selectedStoredIDs.contains(item.id) ? Color.buttonPrimary : Color.grey20,
                lineWidth: selectedStoredIDs.contains(item.id) ? 2 : 1))
            .foregroundStyle(Color.fontPrimary)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("project-item-\(item.id)")
            .task(id: item.id) { await store.loadItemEmbedPreview(item) }
        }
    }

    private func handleItemTap(_ item: ProjectWorkspaceItem) {
        if selectingFiles {
            if selectedStoredIDs.contains(item.id) { selectedStoredIDs.remove(item.id) }
            else { selectedStoredIDs.insert(item.id) }
        } else {
            onOpenEmbed(item)
        }
    }

    private func iconName(for filename: String) -> String {
        let lower = filename.lowercased()
        if lower.hasSuffix(".pdf") { return "pdf" }
        if [".md", ".doc", ".docx", ".txt"].contains(where: lower.hasSuffix) { return "docs" }
        if [".png", ".jpg", ".jpeg", ".webp"].contains(where: lower.hasSuffix) { return "image" }
        if [".swift", ".ts", ".tsx", ".py", ".json", ".svelte"].contains(where: lower.hasSuffix) { return "coding" }
        return "files"
    }

    private func cancelSelection() {
        selectingFiles = false
        selectedStoredIDs = []
        selectedRemotePaths = []
    }

    private func stageSelection(move: Bool, project: ProjectWorkspaceProject) {
        let stored = store.items.filter { selectedStoredIDs.contains($0.id) }
        let remote = store.remoteEntries.filter { selectedRemotePaths.contains($0.path) }.map(\.path)
        guard !stored.isEmpty || !remote.isEmpty, stored.isEmpty || remote.isEmpty else { return }
        stagedTransfer = TransferStage(projectID: project.id,
            sourceID: remote.isEmpty ? nil : store.activeRemoteSourceID,
            storedItems: stored, remotePaths: remote, move: move)
        cancelSelection()
    }

    private func commitTransfer(_ stage: TransferStage) {
        guard store.selectedProjectID == stage.projectID else { return }
        if let sourceID = stage.sourceID {
            guard sourceID == store.activeRemoteSourceID else { return }
            Task {
                await store.transferRemote(stage.remotePaths, move: stage.move,
                    destinationPath: store.remotePath)
                if store.remoteError == nil, stagedTransfer?.projectID == stage.projectID {
                    stagedTransfer = nil
                }
            }
        } else {
            guard store.activeRemoteSourceID == nil, virtualPath == nil else { return }
            let folderID = currentFolderID
            Task {
                await store.transferStored(stage.storedItems, move: stage.move,
                    destinationFolderID: folderID)
                if store.errorMessage == nil, stagedTransfer?.projectID == stage.projectID {
                    stagedTransfer = nil
                }
            }
        }
    }

    private var createProjectSheet: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            TextField(AppStrings.projectNameField, text: $pendingProjectName).textFieldStyle(OMTextFieldStyle())
            Text(AppStrings.projectWritePermission).font(.omP).fontWeight(.semibold)
            Text(AppStrings.projectWritePrompt).font(.omSmall).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("project-write-policy-setup")
            ForEach(ProjectWorkspaceWriteMode.allCases) { mode in
                Button { pendingWriteMode = mode } label: {
                    HStack { Text(mode.title); Spacer(); if pendingWriteMode == mode { Icon("check", size: 18) } }
                        .padding(.spacing6).background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius5))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            HStack {
                Button(AppStrings.cancel) { showCreateProject = false }.buttonStyle(OMSecondaryButtonStyle())
                Spacer()
                Button(AppStrings.projectCreateAction) {
                    guard let mode = pendingWriteMode else { return }
                    let name = pendingProjectName
                    showCreateProject = false; pendingProjectName = ""; pendingWriteMode = nil
                    Task { await store.createProject(name: name, writeMode: mode) }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(pendingProjectName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || pendingWriteMode == nil)
            }
        }
    }

    private var createFolderSheet: some View {
        VStack(spacing: .spacing6) {
            TextField(AppStrings.projectFolderName, text: $pendingFolderName).textFieldStyle(OMTextFieldStyle())
            HStack {
                Button(AppStrings.cancel) { showCreateFolder = false }.buttonStyle(OMSecondaryButtonStyle())
                Spacer()
                Button(AppStrings.projectCreateAction) {
                    let name = pendingFolderName; let parent = currentFolderID
                    showCreateFolder = false
                    Task { await store.createFolder(name: name, parentID: parent) }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(pendingFolderName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private var metadataSheet: some View {
        VStack(spacing: .spacing6) {
            TextField(AppStrings.projectNameField, text: $editedName).textFieldStyle(OMTextFieldStyle())
            TextField(AppStrings.projectDescriptionField, text: $editedDescription, axis: .vertical)
                .lineLimit(3...6).textFieldStyle(OMTextFieldStyle())
            HStack {
                Button(AppStrings.cancel) { editingMetadata = false }.buttonStyle(OMSecondaryButtonStyle())
                Spacer()
                Button(AppStrings.save) {
                    let name = editedName; let description = editedDescription
                    editingMetadata = false
                    Task { await store.updateSelectedProject(name: name, description: description) }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(editedName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    @ViewBuilder
    private var errorBanner: some View {
        if let error = store.errorMessage {
            HStack {
                Text(error).font(.omSmall)
                Spacer()
                Button(AppStrings.retry) { Task { await store.reloadSelected() } }.buttonStyle(OMSecondaryButtonStyle())
            }
            .foregroundStyle(Color.error)
            .padding(14)
            .background(Color.error.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
        }
    }
}

enum ProjectWorkspaceMarkdown {
    static func safeAttributed(_ source: String) -> AttributedString {
        // Project README Markdown never receives raw HTML or untrusted image URLs.
        let withoutHTML = source.replacingOccurrences(of: "<[^>]*>", with: "", options: .regularExpression)
        let withoutImages = withoutHTML.replacingOccurrences(
            of: "!\\[([^\\]]*)\\]\\([^)]*\\)", with: "[Image: $1]", options: .regularExpression)
        let withoutLinks = withoutImages.replacingOccurrences(
            of: "\\[([^\\]]+)\\]\\((?!https?://|mailto:)[^)]*\\)", with: "$1", options: .regularExpression)
        return (try? AttributedString(markdown: withoutLinks,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .full)))
            ?? AttributedString(withoutLinks)
    }
}

extension AppStrings {
    static var projectSelect: String { localized("projects.workspace_select") }
    static var projectCopy: String { localized("projects.workspace_copy") }
    static var projectMove: String { localized("projects.workspace_move") }
    static var projectPaste: String { localized("projects.workspace_paste") }
    static var projectMoveHere: String { localized("projects.workspace_move_here") }
    static var projectSync: String { localized("projects.workspace_sync") }
    static func projectSourceStatus(_ status: String) -> String {
        switch status {
        case "connected": localized("projects.connected_source")
        case "pending", "connecting": localized("projects.workspace_source_pending")
        default: localized("projects.workspace_source_offline")
        }
    }
    static var projectDownloadOriginal: String { localized("projects.workspace_download_original") }
    static var projectShareDownload: String { localized("projects.workspace_share_download") }
    static func projectDownloading(downloaded: Int, total: Int) -> String {
        LocalizationManager.shared.text("projects.workspace_downloading", replacements: [
            "downloaded": ByteCountFormatter.string(fromByteCount: Int64(downloaded), countStyle: .file),
            "total": ByteCountFormatter.string(fromByteCount: Int64(total), countStyle: .file),
        ])
    }
}

// Web: WorkspaceContinueCard.svelte `.resume-large-orbs`. The compact pill
// keeps its flat gradient; the 300×200 card has three softly drifting blooms.
private struct ProjectContinueCardBackground: View {
    let showOrbs: Bool
    let height: CGFloat

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            LinearGradient.primary
            if showOrbs {
                TimelineView(.animation(minimumInterval: reduceMotion ? 60 : nil)) { timeline in
                    let time = timeline.date.timeIntervalSinceReferenceDate
                    let first = drift(time, duration: 19,
                        frames: [(0, 0, 0), (0.25, 80, 40), (0.5, 100, 10), (0.75, 40, 60), (1, 0, 0)])
                    let second = drift(time, duration: 23,
                        frames: [(0, 0, 0), (0.3, -80, -30), (0.6, -50, -80), (0.85, -90, -20), (1, 0, 0)])
                    let third = drift(time, duration: 29,
                        frames: [(0, 0, 0), (0.2, -50, 30), (0.45, 50, 50), (0.7, -30, -40), (1, 0, 0)])
                    ZStack {
                        ProjectContinueOrb(width: 280, height: 240, opacity: 0.35)
                            .position(x: 70 + first.width, y: 60 + first.height)
                        ProjectContinueOrb(width: 260, height: 220, opacity: 0.35)
                            .position(x: 250 + second.width, y: 170 + second.height)
                        ProjectContinueOrb(width: 200, height: 180, opacity: 0.38)
                            .position(x: 175 + third.width, y: 80 + third.height)
                    }
                    .frame(width: 300, height: 200)
                }
            }
        }
        .frame(width: 300, height: height)
        .clipped()
    }

    private func drift(_ time: TimeInterval, duration: Double,
                       frames: [(Double, CGFloat, CGFloat)]) -> CGSize {
        guard !reduceMotion else { return .zero }
        let fraction = time.truncatingRemainder(dividingBy: duration) / duration
        for index in 0..<(frames.count - 1) where fraction <= frames[index + 1].0 {
            let from = frames[index]
            let to = frames[index + 1]
            let progress = (fraction - from.0) / (to.0 - from.0)
            let eased = CGFloat(progress * progress * (3 - 2 * progress))
            return CGSize(width: from.1 + (to.1 - from.1) * eased,
                          height: from.2 + (to.2 - from.2) * eased)
        }
        return .zero
    }
}

// ProjectsPage.svelte .file-selection-actions button and global buttons.css.
// Keep this compact border treatment local; generic secondary actions use a
// different background and padding in the rest of the application.
private struct ProjectFileSelectionButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP.weight(.medium))
            .foregroundStyle(Color.fontPrimary)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing2)
            .frame(minWidth: 112, minHeight: 41)
            .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius5))
            .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey30, lineWidth: 1))
            .contentShape(Rectangle())
            .shadow(color: .black.opacity(0.25), radius: 4, y: 4)
            .opacity(isEnabled ? 1 : 0.5)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }
}

private struct ProjectContinueOrb: View {
    let width: CGFloat
    let height: CGFloat
    let opacity: Double

    var body: some View {
        Ellipse()
            .fill(RadialGradient(stops: [
                .init(color: Color(hex: 0x5A85EB), location: 0),
                .init(color: Color(hex: 0x5A85EB), location: 0.4),
                .init(color: .clear, location: 0.85),
            ], center: .center, startRadius: 0, endRadius: max(width, height) / 2))
            .frame(width: width, height: height)
            .blur(radius: 22)
            .opacity(opacity)
            .accessibilityHidden(true)
    }
}
