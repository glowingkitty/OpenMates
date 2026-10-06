// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Production sidebar content, independently renderable with in-memory inputs.
// Web: chats/Chats.svelte .activity-history-wrapper/.group-title, chats/Chat.svelte.
// Account loading/filtering, hidden-chat authentication and shell width stay with
// the parent. This renderer never opens an account store or starts a request.
import SwiftUI
#if os(iOS)
import UIKit
#endif

// Observe draft changes within the sidebar subtree, never the entire app shell.
// Isolated fixtures use ChatSidebarContent directly and never construct this.
struct ChatSidebarDraftContext<Content: View>: View {
    @ObservedObject private var drafts = DraftService.shared
    @ViewBuilder let content: ([String: String]) -> Content
    var body: some View { content(drafts.draftPreviews) }
}

struct ChatSidebarSection: Identifiable {
    let id: String
    let title: String
    let chats: [Chat]
}
struct ChatSidebarLoadMore {
    let totalCount: Int
    let loadedCount: Int
    let isLoading: Bool
}
struct ChatSidebarActions {
    let select: (Chat) -> Void
    let showActions: ((Chat) -> Void)?
    let search: () -> Void
    let close: () -> Void
    let showHidden: () -> Void
    let loadMore: () -> Void
    var dragPayload: ((Chat) -> ChatProjectDragPayload?)? = nil
    var dropChat: ((ChatProjectDragPayload, Chat) -> Void)? = nil
}

struct ChatSidebarContent<SearchContent: View>: View {
    var projectNavigation: ChatProjectNavigationContext? = nil
    var recentActiveChats: [Chat] = []
    var revealRunningRequest = 0
    var showsHiddenChatsButton = true
    var processingChatIDs: Set<String> = []
    let userSections: [ChatSidebarSection]
    let publicSections: [ChatSidebarSection]
    let selectedChatID: String?
    let draftPreviews: [String: String]
    let showSearch: Bool
    let emptyMessage: String?
    let loadMore: ChatSidebarLoadMore?
    let actions: ChatSidebarActions
    let refresh: () async -> Void
    @ViewBuilder let searchContent: () -> SearchContent

    var body: some View {
        VStack(spacing: 0) {
            if showSearch {
                searchContent()
            } else {
                WorkspaceSidebarHeader(onSearch: actions.search, onClose: actions.close)
                ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        Color.clear.frame(height: 0).id("chat-sidebar-top")
                        if showsHiddenChatsButton { hiddenButton }
                        if let eligibleProjectNavigation { ChatProjectNavigator(context: eligibleProjectNavigation) }
                        sections(userSections)
                        if let emptyMessage {
                            Text(emptyMessage).font(.omSmall).foregroundStyle(Color.fontTertiary)
                                .frame(maxWidth: .infinity).padding(.vertical, 20)
                        }
                        if let loadMore {
                            ShowMoreChatsButton(totalCount: loadMore.totalCount, loadedCount: loadMore.loadedCount,
                                isLoading: loadMore.isLoading, onLoadMore: actions.loadMore)
                                .padding(.horizontal, 15)
                        }
                        sections(publicSections)
                    }
                }
                .accessibilityIdentifier("chat-sidebar-scroll")
                .refreshable { await refresh() }
                .onChange(of: revealRunningRequest) { _, _ in proxy.scrollTo("chat-sidebar-top", anchor: .top) }
                .onAppear { if revealRunningRequest > 0 { proxy.scrollTo("chat-sidebar-top", anchor: .top) } }
                }
            }
        }
        .background(Color.grey20)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-history-panel")
        .onChange(of: eligibleProjectNavigation?.location, initial: true) { _, location in
            if let projectNavigation, projectNavigation.location != location {
                projectNavigation.navigate(location)
            }
        }
    }
    private var eligibleProjectNavigation: ChatProjectNavigationContext? {
        guard let context = projectNavigation else { return nil }
        let projects = ChatSidebarDisplayPolicy.eligibleProjects(context.projects, recentActiveChats: recentActiveChats)
        let location = context.location.flatMap { location in
            projects.first(where: { $0.id == location.projectID }).flatMap { project in
                location.folderID == nil || project.contents.folders.contains(where: { $0.id == location.folderID }) ? location : nil
            }
        }
        return .init(projects: projects, location: location, runningIDs: context.runningIDs,
            activeSubChatCounts: context.activeSubChatCounts, isOrganizing: context.isOrganizing,
            errorMessage: context.errorMessage, navigate: context.navigate, drop: context.drop,
            createFolder: context.createFolder, openProject: context.openProject)
    }
    private var hiddenButton: some View {
        Button(action: actions.showHidden) {
            HStack(spacing: 8) {
                Icon("hidden", size: 20).foregroundStyle(Color.grey60).accessibilityHidden(true)
                Text(AppStrings.showHiddenChats.uppercased())
                    .font(.custom("Lexend Deca", size: 13.6).weight(.medium))
                    .tracking(0.5).foregroundStyle(Color.grey60)
                Spacer(minLength: 0)
            }.frame(height: 20).contentShape(Rectangle())
        }.buttonStyle(.plain).padding(.horizontal, 15).padding(.vertical, 10)
            .accessibilityIdentifier("chat-sidebar-show-hidden")
    }
    // Keep headers and rows as direct children of the outer LazyVStack. An
    // eager VStack around an entire section would mount every loaded row.
    @ViewBuilder private func sections(_ sections: [ChatSidebarSection]) -> some View {
        ForEach(sections) { section in
            if !section.chats.isEmpty {
                Text(section.title.uppercased())
                    .font(.custom("Lexend Deca", size: 13.6).weight(.medium))
                    .tracking(0.5).foregroundStyle(Color.grey60)
                    .padding(.horizontal, 15).padding(.top, 15).padding(.bottom, 10)
                    .accessibilityIdentifier("chat-sidebar-section-\(section.id)")
                ForEach(section.chats) { chat in
                    ChatSidebarRowButton(chat: chat, selected: selectedChatID == chat.id,
                        processing: processingChatIDs.contains(chat.id) || projectNavigation?.runningIDs.contains(chat.id) == true,
                        activeSubChatCount: projectNavigation?.activeSubChatCounts[chat.id] ?? 0,
                        draftPreview: draftPreviews[chat.id], onSelect: { actions.select(chat) },
                        onShowActions: actions.showActions.map { action in { action(chat) } })
                        .modifier(ChatProjectDragModifier(payload: actions.dragPayload?(chat),
                            onDrop: actions.dropChat.map { drop in { drop($0, chat) } }))
                        .padding(.bottom, 4)
                }
                Color.clear.frame(height: 16).accessibilityHidden(true)
            }
        }
    }
}

// Gesture bookkeeping is consumed by the Button action, not rendering.
// Mutating this retained gate must not rebuild a SwiftUI native drag source
// while UIKit is lifting it. The row's State retains its identity across copies.
private final class SidebarRowSelectionGate {
    var suppressSelection = false
}

private struct ChatSidebarRowButton: View {
    let chat: Chat
    let selected: Bool
    let processing: Bool
    let activeSubChatCount: Int
    let draftPreview: String?
    let onSelect: () -> Void
    let onShowActions: (() -> Void)?
    @State private var hovering = false
    @GestureState private var holdingForActions = false
    @State private var suppressSelection = false
    #if os(iOS)
    @State private var selectionGate = SidebarRowSelectionGate()
    #endif
    @State private var holdMoved = false
    var body: some View {
        Button {
            #if os(iOS)
            if !selectionGate.suppressSelection { onSelect() }
            #else
            if !suppressSelection { onSelect() }
            #endif
        } label: {
            ChatListRow(chat: chat, suppliedDraftPreview: draftPreview, processing: processing, activeSubChatCount: activeSubChatCount)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(selected ? Color.grey0 : hovering ? Color.grey10 : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .contentShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain)
            .onHover { value in
                if hovering != value { NativeDragDiagnostics.record("sidebar.hover.changed=\(value)") }
                hovering = value
            }
            #if os(iOS)
            // A passive observer never recognizes/prevents a drag or scroll.
            .background(SidebarStationaryHoldObserver(onSuppressSelection: {
                let gate = selectionGate
                gate.suppressSelection = true
                NativeDragDiagnostics.record("sidebar.suppression.retainedGate")
            }, onRelease: { opensActions in
                if opensActions { onShowActions?() }
                resetHoldAfterRelease()
            }))
            #else
            // A draggable row must not present the custom menu during the lift.
            // Complete a stationary hold on release; travel belongs to drag/drop.
            .simultaneousGesture(
                LongPressGesture(minimumDuration: 0.5, maximumDistance: 10)
                    .sequenced(before: DragGesture(minimumDistance: 0))
                    .updating($holdingForActions) { value, holding, _ in
                        switch value {
                        case .first(let recognized): holding = recognized
                        case .second(let recognized, _): holding = recognized
                        }
                    }
                    .onChanged { value in
                        switch value {
                        case .first(true): NativeDragDiagnostics.record("sidebar.hold.first"); suppressSelection = true
                        case .second(true, let drag):
                            NativeDragDiagnostics.record("sidebar.hold.second")
                            suppressSelection = true
                            if let drag, hypot(drag.translation.width, drag.translation.height) > 10 { holdMoved = true }
                        default: break
                        }
                    }
                    .onEnded { value in
                        NativeDragDiagnostics.record("sidebar.hold.ended")
                        if case .second(true, let drag) = value,
                           !holdMoved, drag.map({ hypot($0.translation.width, $0.translation.height) <= 10 }) ?? true {
                            onShowActions?()
                        }
                        resetHoldAfterRelease()
                    }
            )
            .onChange(of: holdingForActions) { _, holding in
                if !holding { NativeDragDiagnostics.record("sidebar.hold.released"); resetHoldAfterRelease() }
            }
            #endif
            .accessibilityAddTraits(selected ? .isSelected : [])
    }
    private func resetHoldAfterRelease() {
        // Keep the release's Button action suppressed, then permit the next tap.
        // GestureState also resets here when the native drag interaction cancels.
        #if os(iOS)
        let gate = selectionGate
        DispatchQueue.main.async { gate.suppressSelection = false }
        #else
        DispatchQueue.main.async { suppressSelection = false; holdMoved = false }
        #endif
    }
}

// Retain peak movement: returning a dragged row to its origin cannot open actions.
struct SidebarStationaryHoldTracking {
    private var origin = CGPoint.zero
    private var beganAt: TimeInterval = 0
    private(set) var moved = false
    mutating func begin(at point: CGPoint, time: TimeInterval) {
        origin = point; beganAt = time; moved = false
    }
    mutating func record(_ point: CGPoint) {
        moved = moved || hypot(point.x - origin.x, point.y - origin.y) > 10
    }
    func elapsed(at time: TimeInterval) -> TimeInterval { time - beganAt }
    func opensActions(at time: TimeInterval) -> Bool { !moved && elapsed(at: time) >= 0.5 }
}

#if os(iOS)
private struct SidebarStationaryHoldObserver: UIViewRepresentable {
    let onSuppressSelection: () -> Void
    let onRelease: (Bool) -> Void
    func makeUIView(context: Context) -> Reader { Reader() }
    func updateUIView(_ view: Reader, context: Context) {
        view.onSuppressSelection = onSuppressSelection; view.onRelease = onRelease
    }
    static func dismantleUIView(_ view: Reader, coordinator: ()) { view.detach() }
    final class Reader: UIView, UIGestureRecognizerDelegate {
        var onSuppressSelection: () -> Void = {}
        var onRelease: (Bool) -> Void = { _ in }
        private weak var observedWindow: UIWindow?
        private var observer: PassiveTouchObserver?
        override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? { nil }
        override func didMoveToWindow() {
            super.didMoveToWindow(); detach()
            guard let window else { return }
            observedWindow = window
            let observer = PassiveTouchObserver()
            observer.reader = self; observer.delegate = self
            observer.cancelsTouchesInView = false
            observer.delaysTouchesBegan = false; observer.delaysTouchesEnded = false
            window.addGestureRecognizer(observer); self.observer = observer
        }
        func detach() {
            observer?.invalidate(releasing: true)
            if let observer { observedWindow?.removeGestureRecognizer(observer) }
            observer = nil; observedWindow = nil
        }
        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
            let point = touch.location(in: self)
            guard touch.window === observedWindow, bounds.contains(point) else { return false }
            var ancestor = superview
            while let view = ancestor {
                if view.clipsToBounds, !view.bounds.contains(convert(point, to: view)) { return false }
                ancestor = view.superview
            }
            return true
        }
    }
    // Remain possible until the touch finishes, then fail. This observer cannot
    // win recognition against SwiftUI's native drag source or either ScrollView.
    final class PassiveTouchObserver: UIGestureRecognizer {
        weak var reader: Reader?
        private weak var touch: UITouch?
        private var tracking = SidebarStationaryHoldTracking()
        private var generation = UUID()
        private var hasActiveSequence = false
        #if DEBUG
        private var arbitrationReceipts = 0
        private func recordArbitration(_ relation: String, recognizer: UIGestureRecognizer) {
            guard NativeDragDiagnostics.enabled, arbitrationReceipts < 8 else { return }
            arbitrationReceipts += 1
            NativeDragDiagnostics.record("sidebar.passive.arbitration;relation=\(relation);other=\(String(describing: type(of: recognizer)));state=\(recognizer.state.rawValue)")
        }
        // Observe existing interactions and recognizers without adding a drag
        // delegate, failure dependency, gesture, or view-state mutation.
        private func recordNativeState(_ phase: String, touch: UITouch) {
            guard NativeDragDiagnostics.enabled else { return }
            var ancestor = touch.view
            var views: [String] = []
            var depth = 0
            while let view = ancestor, depth < 6 {
                let drags = view.interactions.compactMap { $0 as? UIDragInteraction }.map {
                    "enabled=\($0.isEnabled),delegate=\($0.delegate.map { String(describing: type(of: $0)) } ?? "nil")"
                }
                let gestures = (view.gestureRecognizers ?? []).prefix(8).map {
                    "\(String(describing: type(of: $0))):\($0.state.rawValue):\($0.isEnabled)"
                }
                views.append("\(String(describing: type(of: view)))[drag=\(drags.joined(separator: "/"));gestures=\(gestures.joined(separator: "/"))]")
                ancestor = view.superview; depth += 1
            }
            NativeDragDiagnostics.record("sidebar.native.\(phase);chain=\(views.joined(separator: ">"))")
        }
        #endif
        override func canPrevent(_ preventedGestureRecognizer: UIGestureRecognizer) -> Bool {
            #if DEBUG
            recordArbitration("canPrevent=false", recognizer: preventedGestureRecognizer)
            #endif
            return false
        }
        override func canBePrevented(by preventingGestureRecognizer: UIGestureRecognizer) -> Bool {
            #if DEBUG
            recordArbitration("canBePrevented=false", recognizer: preventingGestureRecognizer)
            #endif
            return false
        }
        override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent) {
            guard touch == nil, let touch = touches.first, let reader else { state = .failed; return }
            self.touch = touch; generation = UUID(); hasActiveSequence = true
            tracking.begin(at: touch.location(in: reader), time: touch.timestamp)
            #if DEBUG
            arbitrationReceipts = 0
            recordNativeState("began", touch: touch)
            #endif
            NativeDragDiagnostics.record("sidebar.passive.began;xy=\(Int(touch.location(in: reader).x)),\(Int(touch.location(in: reader).y));timestampMS=\(Int(touch.timestamp * 1000))")
            let captured = generation
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                guard let self, self.generation == captured, let touch = self.touch,
                      touch.phase != .ended, touch.phase != .cancelled else { return }
                #if DEBUG
                self.recordNativeState("held", touch: touch)
                #endif
                self.reader?.onSuppressSelection()
                NativeDragDiagnostics.record("sidebar.passive.held")
            }
        }
        override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent) {
            guard let touch, touches.contains(touch), let reader else { return }
            let previouslyMoved = tracking.moved
            tracking.record(touch.location(in: reader))
            #if DEBUG
            if tracking.moved && !previouslyMoved { recordNativeState("firstMove", touch: touch) }
            #endif
            if tracking.moved { NativeDragDiagnostics.record("sidebar.passive.moved"); reader.onSuppressSelection() }
        }
        override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent) {
            guard let touch, touches.contains(touch), let reader else { state = .failed; return }
            tracking.record(touch.location(in: reader))
            #if DEBUG
            recordNativeState("ended", touch: touch)
            #endif
            let opens = tracking.opensActions(at: touch.timestamp)
            NativeDragDiagnostics.record("sidebar.passive.ended;opens=\(opens);moved=\(tracking.moved);elapsedMS=\(Int(tracking.elapsed(at: touch.timestamp) * 1000));xy=\(Int(touch.location(in: reader).x)),\(Int(touch.location(in: reader).y))")
            if opens { reader.onSuppressSelection() }
            invalidate(); reader.onRelease(opens); state = .failed
        }
        override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent) {
            NativeDragDiagnostics.record("sidebar.passive.cancelled")
            invalidate(releasing: true); state = .failed
        }
        func invalidate(releasing: Bool = false) {
            let hadActiveSequence = hasActiveSequence
            if hadActiveSequence { NativeDragDiagnostics.record("sidebar.passive.invalidate;release=\(releasing)") }
            touch = nil; generation = UUID(); hasActiveSequence = false
            if releasing && hadActiveSequence { reader?.onRelease(false) }
        }
        override func reset() { super.reset(); invalidate(releasing: true) }
    }
}
#endif

// Shared workspace navigator chrome. Web: chats/Chats.svelte .chats-topbar.
// Workspace lists supply their own search action and always close the shell rail.
struct WorkspaceSidebarHeader: View {
    let onSearch: () -> Void
    let onClose: () -> Void
    var searchIdentifier = "search-button"
    var closeIdentifier = "chat-sidebar-close"
    var topBarIdentifier = "chat-sidebar-topbar"
    var body: some View {
        HStack(spacing: 12) {
            Button(action: onSearch) {
                Icon("search", size: 25).foregroundStyle(LinearGradient.primary).frame(width: 25, height: 25)
            }.buttonStyle(.plain).accessibilityIdentifier(searchIdentifier)
                .help(Text(AppStrings.search)).accessibilityLabel(AppStrings.search)
            Spacer()
            Button(action: onClose) {
                Icon("close", size: 25).foregroundStyle(LinearGradient.primary).frame(width: 25, height: 25)
            }.buttonStyle(.plain).accessibilityIdentifier(closeIdentifier)
                .help(Text(AppStrings.close)).accessibilityLabel(AppStrings.close)
        }
        .frame(height: 32).padding(.horizontal, 20).padding(.vertical, 16)
        .background(Color.grey20)
        .padding(.bottom, 1)
        .overlay(alignment: .bottom) { Rectangle().fill(Color.grey30).frame(height: 1) }
        .accessibilityElement(children: .contain).accessibilityIdentifier(topBarIdentifier)
    }
}

// Searches loaded workspace metadata only; no query leaves the device.
struct WorkspaceSidebarSearchField: View {
    @Binding var query: String
    let identifier: String
    @FocusState private var focused: Bool

    var body: some View {
        TextField(AppStrings.search, text: $query)
            .textFieldStyle(OMTextFieldStyle())
            .autocorrectionDisabled()
            #if os(iOS)
            .textInputAutocapitalization(.never)
            #endif
            .focused($focused)
            .accessibilityIdentifier(identifier)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .onAppear { focused = true }
    }
}
