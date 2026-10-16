// Debug-only geometry host for the production continuation region, carousel,
// browse links, sidebar and search. All records are synthetic; account/draft/send
// lifecycles are detached. The shared workspace field supplies measured keyboard
// geometry without constructing the production chat submission pipeline.
#if DEBUG
import SwiftUI

struct DevChatContinuationLayoutFixture: View {
    let onAction: (String) -> Void
    @StateObject private var store: ChatStore
    @State private var sidebarOpen = false
    @State private var searchOpen = false
    @State private var browsingChatGrid = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var input = ""
    @State private var bannerBottom: CGFloat?
    @State private var composerTop: CGFloat?
    @State private var keyboardMinY: CGFloat?
    init(onAction: @escaping (String) -> Void) {
        self.onAction = onAction
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChats([
                DevHistoryWelcomeData.chat("fixture-resume", title: "Continue the research"),
                DevHistoryWelcomeData.chat("fixture-second", title: "Telescope research")
            ])
        }
        _store = StateObject(wrappedValue: store)
    }
    var body: some View {
        GeometryReader { geometry in
            WorkspaceSidebarLayout(width: geometry.size.width, isOpen: sidebarOpen) {
                ChatSidebarContent(userSections: [.init(id: "fixture", title: AppStrings.chats, chats: store.chats)],
                    publicSections: [], selectedChatID: nil, draftPreviews: [:], showSearch: searchOpen,
                    emptyMessage: nil, loadMore: nil,
                    actions: .init(select: { selected($0.id) }, showActions: nil,
                        search: { searchOpen = true }, close: { sidebarOpen = false; searchOpen = false },
                        showHidden: {}, loadMore: {}), refresh: {}) {
                        ChatSearchView(chats: store.chats, activeChatId: nil, chatStore: store,
                            onSelectResult: { selected($0.chatId) }, onClose: { searchOpen = false },
                            prepareSearchMetadata: {}, allowsOfflineContent: false)
                    }
            } content: {
                let globalBottom = geometry.frame(in: .global).maxY
                let keyboardOverlap = max(0, globalBottom - (keyboardMinY ?? globalBottom))
                let placement = WorkspaceContinuationLayoutPolicy.resolve(width: geometry.size.width, height: geometry.size.height,
                    bannerBottom: browsingChatGrid ? 0 : bannerBottom ?? 190,
                    composerTop: composerTop ?? max(0, geometry.size.height - 69 - keyboardOverlap))
                ZStack(alignment: .bottom) {
                    VStack {
                        if !browsingChatGrid {
                        InspirationCard(inspiration: DailyInspirationData(text: "Explore a useful research question.", title: "Research tip", category: "technology"),
                            containerSize: geometry.size, heightOverride: 190) { }
                            .accessibilityIdentifier("continuation-inspiration")
                            .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named("continuation-fixture-layout")).maxY } action: {
                                bannerBottom = $0
                            }
                            .transition(reduceMotion ? .opacity : .move(edge: .top).combined(with: .opacity))
                        }
                        Spacer(minLength: 0)
                    }
                    if browsingChatGrid {
                        WelcomeChatGrid(cards: store.chats.map { WelcomeScreenState.cardData(for: $0) },
                            width: geometry.size.width, height: placement.availableHeight,
                            onBack: { setBrowsing(false) }, onOpenChat: selected,
                            onShowChatActions: { onAction("actions:\($0)") })
                            .position(x: geometry.size.width / 2, y: placement.centerY)
                            .transition(.opacity)
                    } else {
                    WelcomeContinuationLayout(placement: placement, width: geometry.size.width) {
                        VStack(spacing: .spacing4) {
                            VStack(spacing: .spacing3) {
                                Text(AppStrings.welcomeHeyUser("Researcher")).font(.custom("Lexend Deca", size: 30).weight(.semibold))
                                Text(AppStrings.resumeLastChatTitle).font(.omP.weight(.semibold))
                            }
                            WelcomeContinuationCarousel(cards: store.chats.map { WelcomeScreenState.cardData(for: $0) },
                                containerSize: CGSize(width: geometry.size.width, height: placement.availableHeight),
                                onOpenChat: selected, onShowChatActions: { onAction("actions:\($0)") })
                            HStack(spacing: .spacing5) {
                                WorkspaceContinuationLink(title: AppStrings.welcomeShowAllChats, icon: "message-square", identifier: "welcome-show-all-chats") {
                                    setBrowsing(true)
                                }
                                WorkspaceContinuationLink(title: AppStrings.search, icon: "search", identifier: "welcome-search-chats") {
                                    sidebarOpen = true; searchOpen = true
                                }
                            }
                        }
                        .fixedSize(horizontal: false, vertical: true)
                    }
                    }
                    WorkspacePromptComposerView(text: $input, placeholder: AppStrings.whatDoYouNeedHelpWith,
                        submitLabel: AppStrings.send, submittingLabel: AppStrings.send, disabled: false, submitting: false,
                        identifier: "continuation-composer", inputIdentifier: "continuation-input",
                        submitIdentifier: "continuation-submit", micIdentifier: "continuation-mic",
                        onSubmit: { _ in }, onMic: {})
                        .padding(.bottom, 5 + keyboardOverlap)
                        .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named("continuation-fixture-layout")).minY } action: {
                            composerTop = $0
                        }
                }
                .coordinateSpace(name: "continuation-fixture-layout")
                .background(Color.grey20)
            }
        }
        .modifier(WorkspaceContinuationKeyboardTracking(minY: $keyboardMinY))
    }
    private func selected(_ id: String) {
        onAction("open:\(id)")
        sidebarOpen = false
        searchOpen = false
    }
    private func setBrowsing(_ value: Bool) {
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) { browsingChatGrid = value }
    }
}
#endif
