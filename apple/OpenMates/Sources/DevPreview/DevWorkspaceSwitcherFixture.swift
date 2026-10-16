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
    @State private var syncActive = false
    @State private var forcedWidth: CGFloat?
    @StateObject private var connectionManager = WebSocketManager()

    init(viewport: CGSize, reducedMotion: Bool, shortViewport: Bool = false, startsWide: Bool = false) {
        self.viewport = viewport
        self.reducedMotion = reducedMotion
        self.shortViewport = shortViewport
        _narrow = State(initialValue: !startsWide)
    }
    private var width: CGFloat { min(forcedWidth ?? (narrow ? 320 : viewport.width), viewport.width) }

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
                onOpenReferral: { action = "referral" }, onOpenAuth: {}, isSyncing: syncActive,
                connectionManager: ProcessInfo.processInfo.arguments.contains("--ui-test-connection-status") ? connectionManager : nil,
                connectionAuthenticated: true, onReconnect: { action = "reconnect" })
                .zIndex(2)
            HStack {
                Button { syncActive.toggle() } label: {
                    Icon("lucide-repeat", size: 18).frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Toggle sync activity")
                .accessibilityIdentifier("workspace-picker-fixture-toggle-sync")
                Text(action).font(.omSmall).accessibilityIdentifier("workspace-picker-fixture-action")
                Spacer()
            }
            .padding(.horizontal, .spacing8)
            Spacer()
            HStack {
                ForEach([320, 350, 390], id: \.self) { value in
                    Button("\(value)") { forcedWidth = CGFloat(value) }
                        .accessibilityIdentifier("workspace-picker-fixture-width-\(value)")
                }
            }
            .buttonStyle(.plain)
            HStack {
                Button("Resize workspace") { forcedWidth = nil; narrow.toggle() }.accessibilityIdentifier("workspace-picker-fixture-resize")
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
