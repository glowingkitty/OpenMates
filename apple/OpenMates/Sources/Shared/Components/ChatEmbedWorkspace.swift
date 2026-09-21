import SwiftUI

/// ActiveChat.svelte side-by-side contract. The same transcript subtree stays
/// mounted across overlay/split and hide/restore, preserving scroll and editor state.
struct ChatEmbedWorkspace<Transcript: View, Embed: View>: View {
    let embedOpen: Bool
    @Binding var chatHidden: Bool
    var onLayout: (CGFloat, CGFloat) -> Void = { _, _ in }
    @ViewBuilder let transcript: () -> Transcript
    @ViewBuilder let embed: () -> Embed
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @Environment(\.workspacePaneIsVisible) private var parentVisible
    var body: some View {
        GeometryReader { geometry in
            let split = embedOpen && geometry.size.width >= 1024
            let chatWidth: CGFloat = split ? 400 : geometry.size.width
            let leading: CGFloat = split && !chatHidden ? 410 : 0
            ZStack(alignment: .leading) {
                transcript()
                    .environment(\.workspacePaneIsVisible, parentVisible && (!embedOpen || (split && !chatHidden)))
                    .frame(width: chatWidth, height: geometry.size.height)
                    .onChange(of: CGSize(width: geometry.size.width, height: chatWidth), initial: true) { _, size in onLayout(size.width, size.height) }
                    .clipShape(RoundedRectangle(cornerRadius: split ? 17 : 0))
                    .shadow(color: .black.opacity(split ? 0.25 : 0), radius: 12)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("workspace-transcript")
                    .offset(x: split && chatHidden ? -410 : 0)
                    .opacity(split && chatHidden ? 0 : 1)
                    .allowsHitTesting(!embedOpen || (split && !chatHidden))
                    .accessibilityHidden(embedOpen && (!split || chatHidden))
                if embedOpen {
                    embed()
                        .environment(\.workspacePaneIsVisible, parentVisible)
                        .frame(width: max(0, geometry.size.width - leading), height: geometry.size.height)
                        .clipShape(RoundedRectangle(cornerRadius: 17))
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("workspace-embed")
                        .offset(x: leading)
                        .transition(reduceMotion ? .identity : .modifier(active: WorkspaceEmbedReveal(progress: 0), identity: WorkspaceEmbedReveal(progress: 1)))
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height, alignment: .leading)
            .clipped()
            .animation(reduceMotion ? nil : .timingCurve(0.4, 0, 0.2, 1, duration: 0.4), value: chatHidden)
            .animation(reduceMotion ? nil : .timingCurve(0.4, 0, 0.2, 1, duration: 0.4), value: split)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("chat-embed-workspace")
        }
    }
}


/// +page.svelte sidebar: one stable content subtree across the600pt breakpoint.
struct WorkspaceSidebarLayout<Sidebar: View, Content: View>: View {
    let width: CGFloat
    let isOpen: Bool
    var dragOffset: CGFloat = 0
    @ViewBuilder let sidebar: () -> Sidebar
    @ViewBuilder let content: () -> Content
    @Environment(\.workspacePaneIsVisible) private var parentVisible
    var body: some View {
        let mobile = width <= 600
        let panelWidth: CGFloat = mobile ? width : 325
        let inset: CGFloat = mobile ? 0 : isOpen ? 335 : 10
        ZStack(alignment: .leading) {
            sidebar()
                .environment(\.workspacePaneIsVisible, parentVisible && isOpen)
                .frame(width: panelWidth)
                .offset(x: isOpen ? min(0, dragOffset) : -panelWidth + max(0, dragOffset))
                .allowsHitTesting(parentVisible && (isOpen || dragOffset > 0))
                .accessibilityHidden(!parentVisible || !isOpen)
            content()
                .environment(\.workspacePaneIsVisible, parentVisible && !(mobile && isOpen))
                .frame(width: max(0, width - inset))
                .offset(x: mobile ? (isOpen ? max(0, width + dragOffset) : max(0, dragOffset)) : inset)
                // Keep the subtree mounted for state restoration, but exclude
                // the offscreen mobile workspace from hit testing and VoiceOver.
                .allowsHitTesting(parentVisible && !(mobile && isOpen))
                .accessibilityHidden(!parentVisible || (mobile && isOpen))
        }
        .frame(width: width, alignment: .leading)
        .clipped()
    }
}


/// Settings keeps its navigation subtree, and the workspace, mounted on resize.
struct WorkspaceSettingsLayout<Content: View, Settings: View>: View {
    let windowWidth: CGFloat
    var windowFrame: CGRect = .zero
    @Binding var isOpen: Bool
    var dragOffset: CGFloat = 0
    @ViewBuilder let content: () -> Content
    @ViewBuilder let settings: () -> Settings
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.workspacePaneIsVisible) private var parentVisible
    var body: some View {
        GeometryReader { geometry in
            let overlay = windowWidth <= 1100
            let reveal = isOpen ? max(0, min(323, 323 - max(0, dragOffset))) : max(0, min(323, -dragOffset))
            let reservation: CGFloat = !overlay && reveal > 0 ? reveal + 20 * reveal / 323 : 0
            let visible = isOpen || reveal > 0
            let panelWidth = min(323, max(0, windowWidth - 20))
            let frame = geometry.frame(in: .global)
            let rightInset: CGFloat = windowWidth <= 730 ? 10 : 20
            let bottomInset: CGFloat = windowWidth <= 730 ? 10 : 18
            let hasWindowFrame = !windowFrame.isEmpty
            let x = overlay && hasWindowFrame ? windowFrame.maxX - rightInset - panelWidth - frame.minX : geometry.size.width - panelWidth
            let y = overlay && hasWindowFrame ? windowFrame.minY + 65 - frame.minY : 0
            let height = overlay && hasWindowFrame ? max(0, windowFrame.height - 65 - bottomInset) : geometry.size.height
            ZStack(alignment: .leading) {
                content().environment(\.workspacePaneIsVisible, parentVisible && (!overlay || !isOpen)).frame(width: max(0, geometry.size.width - reservation))
                    .background(Color.grey20)
                    .clipShape(RoundedRectangle(cornerRadius: 17))
                    .shadow(color: .black.opacity(0.25), radius: 12)
                    .allowsHitTesting(parentVisible && (!overlay || !isOpen))
                    .accessibilityHidden(!parentVisible || (overlay && isOpen))
                if parentVisible && overlay && isOpen {
                    Color.black.opacity(0.2).contentShape(Rectangle())
                        .onTapGesture { isOpen = false }.accessibilityHidden(true)
                }
                settings().environment(\.workspacePaneIsVisible, parentVisible && visible).frame(width: panelWidth, height: height)
                    // A retained native ScrollView can expose its own AX node
                    // through an implicit SwiftUI group. Give the pane a real
                    // ancestor whose accessibility and actions close together.
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("workspace-settings")
                    .disabled(!parentVisible || !isOpen)
                    .offset(x: overlay ? (visible ? x + (323 - reveal) : x + panelWidth + rightInset * 2) : geometry.size.width - reveal, y: y)
                    .opacity(visible ? 1 : 0)
                    .allowsHitTesting(parentVisible && isOpen)
                    .accessibilityHidden(!parentVisible || !visible)
            }.frame(width: geometry.size.width, height: geometry.size.height, alignment: .leading)
                .animation(reduceMotion ? nil : .easeOut(duration: overlay ? 0.12 : 0.3), value: isOpen)
        }
    }
}


/// CSS panelReveal/panelHide: inset(0 0 0 100%) -> inset(0), plus opacity.
private struct WorkspaceEmbedReveal: AnimatableModifier {
    nonisolated var progress: CGFloat
    nonisolated var animatableData: CGFloat { get { progress } set { progress = newValue } }
    func body(content: Content) -> some View {
        content.mask(WorkspaceEmbedRevealMask(progress: progress)).opacity(progress)
    }
}
struct WorkspaceEmbedRevealMask: Shape {
    var progress: CGFloat
    var animatableData: CGFloat { get { progress } set { progress = newValue } }
    func path(in rect: CGRect) -> Path {
        let width = rect.width * min(1, max(0, progress))
        return Path(CGRect(x: rect.maxX - width, y: rect.minY, width: width, height: rect.height))
    }
}


private struct WorkspacePaneVisibilityKey: EnvironmentKey { static let defaultValue = true }
extension EnvironmentValues {
    var workspacePaneIsVisible: Bool {
        get { self[WorkspacePaneVisibilityKey.self] }
        set { self[WorkspacePaneVisibilityKey.self] = newValue }
    }
}
enum WorkspaceMotionPolicy {
    static func shouldAnimate(paneVisible: Bool, scrollVisible: Bool, sceneActive: Bool, reduced: Bool) -> Bool {
        paneVisible && scrollVisible && sceneActive && !reduced
    }
}
