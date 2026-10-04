// Local-only production header fixture; no stores, credentials or requests.
// Web source: frontend/packages/ui/src/components/Header.svelte.
#if DEBUG
import SwiftUI

struct DevWorkspaceSwitcherFixture: View {
    let viewport: CGSize
    let reducedMotion: Bool
    var shortViewport = false
    @State private var selected: WorkspaceDestination = .chat
    @State private var narrow = true
    @State private var action = "ready"

    init(viewport: CGSize, reducedMotion: Bool, shortViewport: Bool = false, startsWide: Bool = false) {
        self.viewport = viewport
        self.reducedMotion = reducedMotion
        self.shortViewport = shortViewport
        _narrow = State(initialValue: !startsWide)
    }
    private var width: CGFloat { narrow ? min(320, viewport.width) : viewport.width }

    private var height: CGFloat { shortViewport ? min(320, viewport.height) : viewport.height }

    var body: some View {
        VStack(spacing: 0) {
            OpenMatesWebHeader(viewportWidth: width, viewportHeight: height,
                isAuthenticated: true, isChatsPanelOpen: false, isSettingsOpen: false,
                profileUserId: nil, profileImageUrl: nil, onToggleChats: { action = "sidebar" },
                selectedWorkspace: selected, onSelectWorkspace: {
                    selected = $0; action = "select:\($0.rawValue)"
                },
                onNewChat: { action = "new-chat" }, showWorkspaceSwitcher: true,
                onShareChat: {}, canShareChat: false, onOpenSettings: { action = "settings" },
                onOpenReferral: { action = "referral" }, onOpenAuth: {})
                .zIndex(2)
            Spacer()
            Text(action).font(.omSmall).accessibilityIdentifier("workspace-picker-fixture-action")
            HStack {
                Button("Resize workspace") { narrow.toggle() }.accessibilityIdentifier("workspace-picker-fixture-resize")
                Button("Open Tasks externally") { selected = .tasks; action = "external-tasks" }
                    .accessibilityIdentifier("workspace-picker-fixture-external")
            }
            .buttonStyle(.plain)
            .padding(.spacing8)
        }
        .frame(width: width, height: height)
        .background(Color.grey0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workspace-picker-fixture-canvas")
        .environment(\.workspacePickerReducedMotionOverride, reducedMotion)
    }
}
#endif
