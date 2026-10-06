// Web source: frontend/packages/ui/src/components/Header.svelte.
// Compact native design: user-approved WatchHubView.selector gradient overlay.
import SwiftUI

#if DEBUG
private struct WorkspacePickerReducedMotionOverrideKey: EnvironmentKey {
    static let defaultValue: Bool? = nil
}

extension EnvironmentValues {
    var workspacePickerReducedMotionOverride: Bool? {
        get { self[WorkspacePickerReducedMotionOverrideKey.self] }
        set { self[WorkspacePickerReducedMotionOverrideKey.self] = newValue }
    }
}
#endif

/// Wide icon tabs retain their fixed segment layout and show bounded native
/// press feedback without changing the selection or hover pill appearance.
private struct WorkspaceTabButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
#if DEBUG
    @Environment(\.workspacePickerReducedMotionOverride) private var fixtureReduceMotion
#endif
    private static let pressedScale: CGFloat = 0.98
    private static let animationDuration: Double = 0.15

    private var reduceMotion: Bool {
#if DEBUG
        fixtureReduceMotion ?? systemReduceMotion
#else
        systemReduceMotion
#endif
    }

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? Self.pressedScale : 1)
            .animation(reduceMotion ? nil : .easeInOut(duration: Self.animationDuration),
                value: configuration.isPressed)
    }
}

enum WorkspaceDestination: String, CaseIterable, Identifiable {
    case chat
    case apps
    case projects
    case workflows
    case tasks

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .apps:
            return "apps"
        case .chat:
            return "chat"
        case .projects:
            return "project"
        case .tasks:
            return "projectmanagement"
        case .workflows:
            return "workflow"
        }
    }

    @MainActor var label: String {
        switch self {
        case .apps:
            return AppStrings.apps
        case .chat:
            return AppStrings.chat
        case .projects:
            return AppStrings.projects
        case .tasks:
            return AppStrings.tasks
        case .workflows:
            return AppStrings.workflows
        }
    }

    var testId: String {
        switch self {
        case .apps:
            return "apps-nav-link"
        case .chat:
            return "chats-nav-link"
        case .projects:
            return "projects-nav-link"
        case .tasks:
            return "tasks-nav-link"
        case .workflows:
            return "workflows-nav-link"
        }
    }

    var placeholderIcon: String { icon }
}

struct WorkspaceSwitcherTabs: View {
    let isCompact: Bool
    let selectedWorkspace: WorkspaceDestination
    let onSelectWorkspace: (WorkspaceDestination) -> Void
    let onNewChat: () -> Void

    @State private var hoveredTabId: WorkspaceDestination.ID?
    let viewportSize: CGSize
    let availableCenterWidth: CGFloat

    private static let tabWidth: CGFloat = 72
    private static let tabHeight: CGFloat = 44.8
    private static let tabRadius: CGFloat = 52
    private static let compactWidth: CGFloat = 120
    private static let compactHeight: CGFloat = 44

    private var tabs: [WorkspaceDestination] {
        WorkspaceDestination.allCases
    }

    private var activeTab: WorkspaceDestination {
        selectedWorkspace
    }

    private var activeIndex: Int {
        tabs.firstIndex(of: selectedWorkspace) ?? 0
    }

    private var hoveredIndex: Int? {
        guard let hoveredTabId else { return nil }
        return tabs.firstIndex { $0.id == hoveredTabId }
    }

    var body: some View {
        if isCompact {
            compactSwitcher
        } else {
            desktopSwitcher
        }
    }

    private var desktopSwitcher: some View {
        ZStack(alignment: .leading) {
            if let hoveredIndex, hoveredIndex != activeIndex {
                RoundedRectangle(cornerRadius: Self.tabRadius)
                    .fill(LinearGradient.primary)
                    .opacity(0.5)
                    .frame(width: Self.tabWidth, height: Self.tabHeight)
                    .offset(x: CGFloat(hoveredIndex) * Self.tabWidth)
                    .animation(.easeInOut(duration: 0.25), value: hoveredIndex)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }

            RoundedRectangle(cornerRadius: Self.tabRadius)
                .fill(LinearGradient.primary)
                .frame(width: Self.tabWidth, height: Self.tabHeight)
                .offset(x: CGFloat(activeIndex) * Self.tabWidth)
                .animation(.easeInOut(duration: 0.3), value: activeIndex)
                .allowsHitTesting(false)
                .accessibilityHidden(true)

            HStack(spacing: 0) {
                ForEach(tabs) { tab in
                    workspaceTab(tab)
                }
            }
        }
        .frame(width: Self.tabWidth * CGFloat(tabs.count), height: Self.tabHeight)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: Self.tabRadius))
        .shadow(color: Color.black.opacity(0.14), radius: 4, x: 0, y: 4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workspace-switcher")
    }

    private var compactSwitcher: some View {
        CompactWorkspacePicker(selectedWorkspace: selectedWorkspace,
            viewportSize: viewportSize, availableCenterWidth: availableCenterWidth,
            onSelectWorkspace: onSelectWorkspace,
            onNewChat: onNewChat)
    }

    @ViewBuilder
    private func workspaceTab(_ item: WorkspaceDestination) -> some View {
        let isActive = item == selectedWorkspace
        let tab = Button {
            if item == .chat, isActive {
                onNewChat()
            } else {
                onSelectWorkspace(item)
            }
        } label: {
            // Keep the icon inside its real button so the visible center and
            // the whole segment share the same action and accessibility node.
            Icon(item.icon, size: 20)
                .foregroundStyle(isActive || hoveredTabId == item.id
                    ? AnyShapeStyle(Color.white) : AnyShapeStyle(Color.grey70))
                .frame(width: Self.tabWidth, height: Self.tabHeight)
                .contentShape(.interaction, Rectangle())
        }
        .buttonStyle(WorkspaceTabButtonStyle())
        .onHover { isHovering in
            hoveredTabId = isHovering ? item.id : nil
        }
        .accessibilityIdentifier(item.testId)
        .help(Text(item.label))
        .accessibilityLabel(item.label)

        if isActive {
            tab.accessibilityAddTraits(.isSelected)
        } else {
            tab
        }
    }
}


/// Fits the existing centered 5 × 72 point strip between the measured controls.
/// A size class cannot distinguish a wide landscape phone from a narrow Mac.
enum WorkspaceSwitcherLayoutPolicy {
    static let tabsWidth: CGFloat = 360
    static let expandedHeight: CGFloat = 376
    static let triggerHeight: CGFloat = 44
    static func compactTriggerWidth(availableCenterWidth: CGFloat) -> CGFloat {
        guard availableCenterWidth.isFinite else { return 0 }
        return min(120, max(0, availableCenterWidth))
    }
    static func panelHeight(viewportHeight: CGFloat) -> CGFloat {
        guard viewportHeight.isFinite else { return triggerHeight }
        // Header top padding and a bottom gap keep the overlay inside its canvas.
        return max(triggerHeight, min(expandedHeight, viewportHeight - .spacing5 - .spacing4))
    }
    static func availableWidth(headerWidth: CGFloat, leadingWidth: CGFloat, trailingWidth: CGFloat) -> CGFloat {
        guard headerWidth.isFinite, leadingWidth.isFinite, trailingWidth.isFinite else { return 0 }
        return max(0, headerWidth - 2 * (max(leadingWidth, trailingWidth) + CGFloat.spacing10 + CGFloat.spacing4))
    }
    static func isCompact(headerWidth: CGFloat, leadingWidth: CGFloat, trailingWidth: CGFloat) -> Bool {
        availableWidth(headerWidth: headerWidth, leadingWidth: leadingWidth, trailingWidth: trailingWidth) < tabsWidth
    }
}

/// Same rounded blue overlay and generous white rows as the Watch selector.
/// The panel remains mounted; only its clipped size changes during expansion.
struct CompactWorkspacePicker: View {
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
#if DEBUG
    @Environment(\.workspacePickerReducedMotionOverride) private var fixtureReduceMotion
#endif
    private var reduceMotion: Bool {
#if DEBUG
        fixtureReduceMotion ?? systemReduceMotion
#else
        systemReduceMotion
#endif
    }
    @State private var expanded = false
    @FocusState private var focusedWorkspace: WorkspaceDestination?
    let selectedWorkspace: WorkspaceDestination
    let viewportSize: CGSize
    let availableCenterWidth: CGFloat
    let onSelectWorkspace: (WorkspaceDestination) -> Void
    let onNewChat: () -> Void

    private var openAnimation: Animation? { reduceMotion ? nil : .easeInOut(duration: 0.18) }
    private var closeAnimation: Animation? { reduceMotion ? nil : .easeInOut(duration: 0.14) }
    private var triggerWidth: CGFloat { WorkspaceSwitcherLayoutPolicy.compactTriggerWidth(availableCenterWidth: availableCenterWidth) }
    private var panelHeight: CGFloat { WorkspaceSwitcherLayoutPolicy.panelHeight(viewportHeight: viewportSize.height) }
    private var panelWidth: CGFloat { min(280, max(120, viewportSize.width - 2 * CGFloat.spacing10)) }

    var body: some View {
        Color.clear
            .frame(width: triggerWidth, height: 44)
            .overlay(alignment: .top) {
                ZStack(alignment: .top) {
                    if expanded {
                        Color.black.opacity(0.72)
                            .frame(width: viewportSize.width, height: max(44, viewportSize.height))
                            .offset(y: 0)
                            .contentShape(Rectangle())
                            .onTapGesture { close() }
                            .accessibilityHidden(true)
                            .transition(.opacity)
                    }
                    ZStack(alignment: .top) {
                        RoundedRectangle(cornerRadius: expanded ? 30 : 52)
                            .fill(LinearGradient.primary)
                            .frame(width: expanded ? panelWidth : triggerWidth, height: expanded ? panelHeight : 44)
                            .shadow(color: Color.black.opacity(0.14), radius: 4, y: 4)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                        Button(action: togglePicker) {
                            HStack(spacing: .spacing3) {
                                Icon(selectedWorkspace.icon, size: 22)
                                if expanded { Text(selectedWorkspace.label).font(.omP.weight(.bold)).lineLimit(1) }
                                Icon("dropdown", size: 18).rotationEffect(.degrees(expanded ? 180 : 0))
                            }
                            .foregroundStyle(Color.white)
                            .frame(width: expanded ? panelWidth : triggerWidth, height: 44)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        // The trigger is a fixed-height sibling of the options,
                        // independent of the expanding panel's decorative shape.
                        .frame(width: expanded ? panelWidth : triggerWidth, height: 44)
                        .clipped()
                        .contentShape(Rectangle())
                        .accessibilityElement(children: .ignore)
                        .accessibilityAddTraits(.isButton)
                        .accessibilityAction { togglePicker() }
                        .focused($focusedWorkspace, equals: selectedWorkspace)
                        .accessibilityIdentifier("workspace-switcher")
                        .accessibilityLabel(selectedWorkspace.label)
                        .accessibilityValue(expanded ? "expanded" : "collapsed")
                        .onKeyPress(.escape) { guard expanded else { return .ignored }; close(); return .handled }
                        .zIndex(1)
                        if expanded {
                            ScrollView(.vertical, showsIndicators: panelHeight < WorkspaceSwitcherLayoutPolicy.expandedHeight) {
                            VStack(spacing: 0) {
                                ForEach(WorkspaceDestination.allCases) { workspace in
                                    Button {
                                        close()
                                        if workspace == .chat, workspace == selectedWorkspace { onNewChat() }
                                        else { onSelectWorkspace(workspace) }
                                    } label: {
                                        HStack(spacing: .spacing10) {
                                            Icon(workspace.icon, size: 24).accessibilityHidden(true)
                                            Text(workspace.label).font(.omP.weight(.bold)).lineLimit(1)
                                                .minimumScaleFactor(0.75)
                                            Spacer(minLength: 0)
                                            if workspace == selectedWorkspace { Icon("check", size: 18).accessibilityHidden(true) }
                                        }
                                        .foregroundStyle(Color.white)
                                        .padding(.horizontal, .spacing12)
                                        .frame(maxWidth: .infinity)
                                        .frame(height: 60)
                                        .contentShape(Rectangle())
                                    }
                                    .buttonStyle(.plain)
                                    .accessibilityIdentifier(workspace.testId)
                                    .accessibilityLabel(workspace.label)
                                    .accessibilityAddTraits(workspace == selectedWorkspace ? .isSelected : [])
                                }
                            }
                            .padding(.vertical, .spacing8)
                            }
                            .frame(width: panelWidth, height: panelHeight - WorkspaceSwitcherLayoutPolicy.triggerHeight)
                            .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: 30, bottomTrailingRadius: 30))
                            .offset(y: WorkspaceSwitcherLayoutPolicy.triggerHeight)
                            .scrollDisabled(panelHeight >= WorkspaceSwitcherLayoutPolicy.expandedHeight)
                            .accessibilityIdentifier("workspace-picker-options")
                            .allowsHitTesting(expanded)
                            .accessibilityHidden(!expanded)
                            .transition(.opacity)
                        }
                    }
                    .frame(width: expanded ? panelWidth : triggerWidth, height: expanded ? panelHeight : 44, alignment: .top)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("workspace-picker-panel")
                    .accessibilityValue(reduceMotion ? "reduced-motion" : "animated")
                }
            }
            .onChange(of: selectedWorkspace) { _, _ in close() }
            .onChange(of: viewportSize) { _, _ in close() }
            .onDisappear { expanded = false }
    }

    private func togglePicker() {
        withAnimation(expanded ? closeAnimation : openAnimation) { expanded.toggle() }
        focusedWorkspace = selectedWorkspace
    }

    private func close() {
        withAnimation(closeAnimation) { expanded = false }
        focusedWorkspace = selectedWorkspace
    }
}
