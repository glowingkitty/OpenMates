import SwiftUI

// Web chrome: frontend/packages/ui/src/components/chats/Chats.svelte .chats-topbar.
// Web reference: ProjectsPage.svelte's `variant === 'sidebar'` surface.
struct ProjectsSidebarView: View {
    @ObservedObject var store: ProjectsWorkspaceStore
    var onClose: () -> Void
    var onOpenProject: (String) -> Void

    @State private var searchQuery = ""
    @State private var showsSearch = false

    private var visibleProjects: [ProjectWorkspaceProject] {
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        return query.isEmpty ? store.projects : store.projects.filter {
            $0.name.localizedCaseInsensitiveContains(query) || $0.description.localizedCaseInsensitiveContains(query)
        }
    }

    @State private var newName = ""
    @State private var policyName = ""
    @State private var writeMode: ProjectWorkspaceWriteMode?
    @State private var showsPolicy = false

    var body: some View {
        VStack(spacing: 0) {
            WorkspaceSidebarHeader(onSearch: { showsSearch.toggle(); if !showsSearch { searchQuery = "" } },
                onClose: onClose, searchIdentifier: "projects-sidebar-search",
                closeIdentifier: "projects-sidebar-close", topBarIdentifier: "projects-sidebar-topbar")
            if showsSearch {
                WorkspaceSidebarSearchField(query: $searchQuery, identifier: "projects-sidebar-search-input")
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(AppStrings.projects)
                        .font(.omSmall).fontWeight(.bold)
                        .foregroundStyle(Color.fontSecondary)
                    HStack(spacing: 8) {
                        TextField(AppStrings.projectSidebarName, text: $newName)
                            #if os(iOS)
                            .textInputAutocapitalization(.words)
                            #endif
                            .accessibilityIdentifier("project-name-input")
                        Button(AppStrings.projectSidebarCreate) { requestCreation() }
                            .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isSaving)
                            .buttonStyle(.borderedProminent)
                            .accessibilityIdentifier("project-create-button")
                    }
                    if store.isLoading {
                        ProgressView(AppStrings.projectLoading)
                            .frame(maxWidth: .infinity, minHeight: 72)
                    } else if store.projects.isEmpty {
                        Text(store.errorMessage == nil ? AppStrings.projectSidebarEmpty : AppStrings.projectSidebarFailed)
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        if store.errorMessage != nil {
                            Button(AppStrings.retry) {
                                if let accountID = store.loadedAccountID {
                                    Task { await store.load(accountId: accountID) }
                                }
                            }
                        }
                    } else if visibleProjects.isEmpty {
                        Text(AppStrings.searchNoResults).font(.omSmall).foregroundStyle(Color.fontSecondary)
                            .accessibilityIdentifier("projects-sidebar-no-matches")
                    } else {
                        LazyVStack(spacing: 8) {
                            ForEach(visibleProjects) { project in
                                Button {
                                    Task {
                                        await store.selectProject(project.id)
                                        onOpenProject(project.id)
                                    }
                                } label: {
                                    HStack(spacing: 12) {
                                        Icon("files", size: 18)
                                            .foregroundStyle(Color.fontButton)
                                            .frame(width: 36, height: 36)
                                            .background(LinearGradient.appWeather, in: Circle())
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(project.name).font(.omSmall).fontWeight(.semibold)
                                                .lineLimit(1)
                                            Text(AppStrings.projectCount(project.itemCount, key: "workspace_items_count"))
                                                .font(.omXs).foregroundStyle(Color.fontSecondary)
                                        }
                                        Spacer(minLength: 0)
                                        Text("›").font(.omH3)
                                            .foregroundStyle(Color.fontSecondary)
                                            .frame(width: 44, height: 44)
                                    }
                                    .padding(.leading, 9)
                                    .foregroundStyle(Color.fontPrimary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(store.selectedProjectID == project.id
                                        ? Color.grey60.opacity(0.3) : Color.clear,
                                        in: RoundedRectangle(cornerRadius: 10))
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(AppStrings.projectSidebarOpen(project.name))
                                .accessibilityIdentifier("project-sidebar-card-\(project.id)")
                            }
                        }
                    }
                }
                .padding(16)
            }
        }
        .background(Color.grey20.ignoresSafeArea())
        .sheet(isPresented: $showsPolicy) {
            NavigationStack {
                Form {
                    Text(policyName).font(.omP).fontWeight(.semibold)
                    Section(AppStrings.projectWritePermission) {
                        Text(AppStrings.localized("settings.projects.write_policy_prompt"))
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        ForEach(ProjectWorkspaceWriteMode.allCases) { mode in
                            Button {
                                writeMode = mode
                            } label: {
                                HStack {
                                    Text(mode.title)
                                    Spacer()
                                    if writeMode == mode { Icon("check", size: 18) }
                                }
                            }
                        }
                    }
                }
                .navigationTitle(AppStrings.projectNew)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(AppStrings.cancel) { showsPolicy = false }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button(AppStrings.projectCreateAction) {
                            guard let writeMode else { return }
                            let name = policyName
                            showsPolicy = false
                            self.writeMode = nil
                            Task {
                                await store.createProject(name: name, writeMode: writeMode)
                                if let id = store.selectedProjectID { onOpenProject(id) }
                            }
                        }
                        .disabled(writeMode == nil)
                    }
                }
            }
            .accessibilityIdentifier("project-sidebar-write-policy")
        }
        .accessibilityIdentifier("projects-sidebar")
    }

    private func requestCreation() {
        let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        policyName = name
        newName = ""
        writeMode = nil
        showsPolicy = true
    }
}

extension AppStrings {
    static var projectSidebarName: String { localized("projects.workspace_sidebar_new_name") }
    static var projectSidebarCreate: String { localized("projects.workspace_sidebar_create") }
    static var projectCreating: String { localized("projects.workspace_creating") }
    static var projectSidebarEmpty: String { localized("projects.workspace_sidebar_empty") }
    static var projectSidebarFailed: String { localized("projects.workspace_sidebar_failed") }
    static var projectSidebarClose: String { localized("projects.workspace_sidebar_close") }
    static func projectSidebarOpen(_ name: String) -> String {
        LocalizationManager.shared.text("projects.workspace_sidebar_open", replacements: ["project": name])
    }
}
