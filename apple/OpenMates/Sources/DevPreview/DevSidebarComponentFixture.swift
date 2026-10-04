#if DEBUG
import SwiftUI

// Actual production sidebar, rows and search engine with a detached in-memory
// store. Public fixtures reuse bundled production chats. Account rows are plainly
// synthetic; they never inspect saved accounts, messages, drafts or credentials.
struct DevSidebarComponentFixture: View {
    let variant: String
    @StateObject private var projectStore: ProjectsWorkspaceStore
    @State private var projectLocation: ChatProjectLocation?
    @State private var dragScope = UUID()
    @StateObject private var store: ChatStore
    @State private var selected: Chat?
    @State private var showSearch = false
    @State private var isOpen = true
    @State private var hiddenBoundary = false
    @State private var actionChat: Chat?
    @State private var actionCallbackCount = 0
    @State private var limit: Int
    @State private var lastActiveID: String?
    private let userChats: [Chat]
    private let publicSections: [ChatSidebarSection]
    private let drafts = ["sidebar-draft": "A local draft kept in memory"]

    init(variant: String) {
        self.variant = variant
        _projectStore = StateObject(wrappedValue: ProjectsWorkspaceStore(service: SidebarProjectFixtureService(), validateFence: { _ in }))
        let users = variant == "dated" ? Self.datedChats : ["account", "organization"].contains(variant) ? Self.accountChats : []
        _limit = State(initialValue: variant == "dated" ? ChatSidebarDisplayPolicy.initialLimit : 2)
        let sections = variant == "empty" ? [] : Self.bundledPublicSections
        userChats = users; publicSections = sections
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChats(users + sections.flatMap(\.chats))
            for chat in users {
                store.setMessages(for: chat.id, messages: [Message(id: "\(chat.id)-message", chatId: chat.id, role: .user,
                    content: "A deterministic local transcript about telescope lenses.", encryptedContent: nil,
                    createdAt: "2026-09-12T12:00:00Z", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)])
            }
        }
        _store = StateObject(wrappedValue: store)
    }
    var body: some View {
        GeometryReader { geometry in
            fixtureContent(size: geometry.size)
        }
        .overlay { actionSheet }
        .task {
            if variant == "organization" { await projectStore.refreshChatNavigation(accountID: "synthetic-owner", teamID: nil) }
        }
    }

    private func fixtureContent(size: CGSize) -> some View {
        VStack(spacing: 0) {
            hiddenBoundaryContent
            ZStack(alignment: .leading) {
                selectedContent(height: size.height)
                if isOpen {
                    sidebarContent.frame(width: size.width <= 600 ? size.width : 325)
                }
            }
            reopenControls
            if variant == "organization" {
                Text(String(actionCallbackCount)).font(.omXs).accessibilityIdentifier("sidebar-fixture-action-count")
            }
            Text("Local fixture; account/network/persistence disabled.")
                .font(.omXs).accessibilityIdentifier("sidebar-fixture-boundary")
        }
    }

    @ViewBuilder private var hiddenBoundaryContent: some View {
        if hiddenBoundary {
            Text("Hidden-chat authentication is not connected in this isolated component.")
                .font(.omSmall).accessibilityIdentifier("sidebar-fixture-hidden-boundary")
            Button(AppStrings.back) { hiddenBoundary = false }
                .accessibilityIdentifier("sidebar-fixture-hidden-return")
        }
    }

    @ViewBuilder private func selectedContent(height: CGFloat) -> some View {
        if let selected {
            VStack(spacing: 12) {
                ChatBannerView(state: .loaded(title: selected.displayTitle, appId: selected.category ?? "ai", summary: selected.chatSummary),
                    viewportHeight: height)
                Text(store.messages(for: selected.id).first?.content ?? selected.displayTitle)
                    .accessibilityIdentifier("sidebar-fixture-selected-content")
                Text(selected.id).accessibilityIdentifier("sidebar-fixture-selected-id")
            }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        } else {
            Color.grey20
        }
    }

    private var sidebarContent: some View {
        ChatSidebarContent(projectNavigation: variant == "organization" ? projectNavigation : nil,
            userSections: userSections, publicSections: publicSections,
            selectedChatID: selected?.id, draftPreviews: drafts, showSearch: showSearch,
            emptyMessage: variant == "empty" ? AppStrings.noChats : nil,
            loadMore: sidebarLoadMore, actions: sidebarActions, refresh: {}) {
                sidebarSearch
            }
    }

    private var sidebarLoadMore: ChatSidebarLoadMore? {
        limit < userChats.count ? .init(totalCount: userChats.count, loadedCount: limit, isLoading: false) : nil
    }

    private var sidebarActions: ChatSidebarActions {
        let showActions: ((Chat) -> Void)? = variant == "organization" ? { chat in actionCallbackCount += 1; actionChat = chat } : nil
        let dragPayload: ((Chat) -> ChatProjectDragPayload?)? = variant == "organization" ? { chat in self.payload(chat) } : nil
        let dropChat: ((ChatProjectDragPayload, Chat) -> Void)? = variant == "organization" ? { payload, target in self.group(payload, target) } : nil
        return .init(select: select, showActions: showActions, search: { showSearch = true },
            close: { isOpen = false }, showHidden: { hiddenBoundary = true },
            loadMore: { limit = ChatSidebarDisplayPolicy.nextLimit(after: limit) },
            dragPayload: dragPayload, dropChat: dropChat)
    }

    private var sidebarSearch: some View {
        ChatSearchView(chats: store.chats, activeChatId: selected?.id, chatStore: store,
            onSelectResult: { result in
                if let chat = store.chat(for: result.chatId) { select(chat) }
            }, onClose: { showSearch = false }, prepareSearchMetadata: {},
            draftPreviews: drafts, allowsOfflineContent: false)
    }

    @ViewBuilder private var reopenControls: some View {
        if !isOpen {
            HStack {
                Button(AppStrings.chats) { isOpen = true }
                    .accessibilityIdentifier("sidebar-fixture-reopen")
                if variant == "dated" {
                    Button(AppStrings.newChat) { selected = nil; isOpen = true }
                        .accessibilityIdentifier("sidebar-fixture-new-chat")
                }
            }
        }
    }

    private var actionSheet: some View {
        OMSheet(isPresented: Binding(get: { actionChat != nil }, set: { if !$0 { actionChat = nil } }), title: actionChat?.displayTitle) {
            Text(actionChat?.id ?? "").accessibilityIdentifier("sidebar-fixture-action-chat")
            Button(AppStrings.close) { actionChat = nil }.accessibilityIdentifier("sidebar-fixture-action-close")
        }.accessibilityIdentifier("sidebar-fixture-actions-overlay")
    }
    private var projectNavigation: ChatProjectNavigationContext {
        .init(projects: projectStore.chatNavigationProjects, location: projectLocation,
            navigate: { projectLocation = $0 }, drop: { payload, at in
                guard accepts(payload), let chat = store.chat(for: payload.chatID) else { return }
                Task { await projectStore.moveChats([chat], to: at) }
            }, createFolder: { at, name in Task { await projectStore.createChatFolder(at: at, name: name) } }, openProject: { _ in })
    }
    private func payload(_ chat: Chat) -> ChatProjectDragPayload? {
        .init(chatID: chat.id, accountID: "synthetic-owner", scope: dragScope, serverOrigin: "fixture.invalid", teamID: nil)
    }
    private func accepts(_ payload: ChatProjectDragPayload) -> Bool {
        payload.accountID == "synthetic-owner" && payload.scope == dragScope && payload.serverOrigin == "fixture.invalid" && payload.teamID == nil
    }
    private func group(_ payload: ChatProjectDragPayload, _ target: Chat) {
        guard accepts(payload), payload.chatID != target.id, let source = store.chat(for: payload.chatID) else { return }
        Task { _ = await projectStore.createChatOrganization(chats: [source, target]) }
    }
    private var userSections: [ChatSidebarSection] {
        let linked = Set(projectStore.chatNavigationProjects.flatMap { $0.contents.items.filter { $0.kind == "chat" }.map(\.targetID) })
        let eligible = variant == "organization" ? userChats.filter { chat in
            if let location = projectLocation {
                return projectStore.chatNavigationProjects.first(where: { $0.id == location.projectID })?.chatIDs(in: location.folderID).contains(chat.id) == true
            }
            return !linked.contains(chat.id)
        } : userChats
        let visible = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: eligible, limit: projectLocation == nil ? limit : Int.max,
            selectedChatID: selected?.id, lastActiveChatID: lastActiveID)
        return ChatSidebarDisplayPolicy.groups(visible, now: Self.fixtureNow, calendar: Self.fixtureCalendar).map { group in
            ChatSidebarSection(id: group.key,
                title: ChatSidebarDisplayPolicy.title(for: group.key, locale: Locale(identifier: "en_US")), chats: group.chats)
        }
    }
    private func select(_ chat: Chat) {
        selected = chat
        lastActiveID = chat.id
        showSearch = false
        isOpen = false
    }
    private static var accountChats: [Chat] {
        [DevHistoryWelcomeData.chat("sidebar-pinned", title: "Telescope research", pinned: true),
         DevHistoryWelcomeData.chat("sidebar-draft", title: "A weekend in Berlin", draft: 1),
         DevHistoryWelcomeData.chat("sidebar-long", title: "Understanding the performance of a long conversation and its many source previews"),
         DevHistoryWelcomeData.chat("sidebar-final", title: "Latest local conversation")]
    }
    private static let fixtureNow = Date(timeIntervalSince1970: 1_789_214_400) // 2026-09-12 12:00 UTC
    private static var fixtureCalendar: Calendar {
        var value = Calendar(identifier: .gregorian); value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }
    private static var datedChats: [Chat] {
        (0..<35).map { index in
            let age = index == 34 ? 70 : index < 5 ? 0 : index < 10 ? 1 : index < 15 ? 4 : index < 25 ? 20 : 40
            let date = fixtureNow.addingTimeInterval(-Double(age) * 86_400 - Double(index) * 60)
            let stamp = ISO8601DateFormatter().string(from: date)
            return Chat(id: "sidebar-dated-\(index)",
                title: index == 34 ? "Historic telescope archive" : "Dated conversation \(index)",
                lastMessageAt: stamp, createdAt: stamp, updatedAt: stamp, isArchived: false,
                isPinned: index < 15, appId: nil, encryptedTitle: nil, encryptedChatKey: nil, messagesV: 1)
        }
    }
    private static var bundledPublicSections: [ChatSidebarSection] {
        let definitions: [(String, String, [String])] = [
            ("intro", AppStrings.introSection, ["demo-who-develops-openmates"]),
            ("examples", AppStrings.exampleChatsSection, ["example-gigantic-airplanes", "example-artemis-ii-mission", "example-beautiful-single-page-html", "example-eu-chat-control-law", "example-flights-berlin-bangkok", "example-creativity-drawing-meetups-berlin"]),
            ("announcements", AppStrings.announcementsSection, ["announcements-introducing-openmates-v09"]),
            ("legal", AppStrings.legalSection, ["legal-privacy", "legal-terms", "legal-imprint"])
        ]
        return definitions.map { id, title, ids in
            ChatSidebarSection(id: id, title: title, chats: ids.compactMap { PublicChatContent.chat(for: $0)?.chat })
        }
    }
}
#endif
#if DEBUG
// Detached transport for actual production Project creation/move controls.
// No account, inference request, persistence bridge, or external service is touched.
@MainActor
private final class SidebarProjectFixtureService: ProjectsWorkspaceServing {
    private var projects: [ProjectWorkspaceProject] = []
    private var links: [String: [ProjectWorkspaceItem]] = [:]
    private var folders: [String: [ProjectWorkspaceFolder]] = [:]
    func listProjects(accountID: String, teamID: String?) async throws -> [ProjectWorkspaceProject] { projects }
    func contents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents {
        .init(folders: folders[project.id] ?? [], items: links[project.id] ?? [], sources: [])
    }
    func createChatOrganization(chats: [Chat], fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject {
        var project = ProjectsWorkspacePreviewFixture.state(for: "default").project
        project.name = "Website launch"
        projects = [project]; links[project.id] = []
        return project
    }
    func copyItem(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject, folderID: String?, fence: ProjectsWorkspaceFence) async throws {
        links[project.id, default: []].append(.init(id: item.id, kind: item.kind, targetID: item.targetID,
            name: item.name, metadata: item.metadata, folderHash: folderID.map(ChatSidebarProject.hash), position: item.position, createdAt: item.createdAt))
    }
    func moveItem(_ itemID: String, project: ProjectWorkspaceProject, folderID: String?, fence: ProjectsWorkspaceFence) async throws {
        guard let item = links[project.id]?.first(where: { $0.id == itemID }) else { return }
        links[project.id]?.removeAll { $0.id == itemID }
        try await copyItem(item, project: project, folderID: folderID, fence: fence)
    }
    func createFolder(_ name: String, project: ProjectWorkspaceProject, parentID: String?, fence: ProjectsWorkspaceFence) async throws {
        folders[project.id, default: []].append(.init(id: UUID().uuidString, name: name,
            parentHash: parentID.map(ChatSidebarProject.hash), position: 0, createdAt: 0))
    }
    func removeChatLink(chatID: String, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws { links[project.id]?.removeAll { $0.targetID == chatID } }
    func listSources(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [ProjectWorkspaceSource] { [] }
    func settings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings {
        .init(writeMode: .applyAndShow, selectionRequired: true, focusID: nil, focusInstruction: nil)
    }
    func createProject(name: String, writeMode: ProjectWorkspaceWriteMode, fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject { throw ProjectsWorkspaceError.invalidContext }
    func updateProject(_ project: ProjectWorkspaceProject, name: String?, description: String?, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceProject { throw ProjectsWorkspaceError.invalidContext }
    func updateWriteMode(_ mode: ProjectWorkspaceWriteMode, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings { throw ProjectsWorkspaceError.invalidContext }
    func activateFocus(project: ProjectWorkspaceProject, chatID: String, focusID: String, instruction: String, fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func deleteProject(_ project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func readStoredFile(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [String: Any] { throw ProjectsWorkspaceError.invalidContext }
    func openLinkedEmbed(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> EmbedRecord { throw ProjectsWorkspaceError.invalidContext }
}
#endif
