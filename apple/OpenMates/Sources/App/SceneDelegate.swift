// Scene delegate — enables iPad multitasking (Split View, Slide Over, Stage Manager),
// Handoff continuation from other Apple devices, home screen shortcut items, and
// external display scenes for the iPhone/iPad controller experience.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/+page.svelte
//          frontend/packages/ui/src/components/ChatHistory.svelte
//          frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css
//          frontend/packages/ui/src/styles/fields.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#endif

#if os(iOS)
extension AppQuickAction {
    init?(shortcutItem: UIApplicationShortcutItem) {
        switch shortcutItem.type {
        case "org.openmates.newchat":
            self = .newChat
        case "org.openmates.search":
            self = .search
        default:
            return nil
        }
    }
}

class SceneDelegate: NSObject, UIWindowSceneDelegate {
    func scene(
        _ scene: UIScene,
        willConnectTo session: UISceneSession,
        options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard let windowScene = scene as? UIWindowScene else { return }

        if session.role == .windowExternalDisplayNonInteractive {
            ExternalDisplayCoordinator.shared.attachExternalDisplayScene(windowScene)
            return
        }

        // Enable all iPad multitasking sizes — Split View, Slide Over, Stage Manager
        if windowScene.responds(to: #selector(getter: UIWindowScene.sizeRestrictions)) {
            windowScene.sizeRestrictions?.minimumSize = CGSize(width: 320, height: 480)
            windowScene.sizeRestrictions?.maximumSize = CGSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        }

        // Handle Handoff activities that arrived at launch
        for activity in connectionOptions.userActivities {
            handleUserActivity(activity)
        }

        if let shortcutItem = connectionOptions.shortcutItem,
           let action = AppQuickAction(shortcutItem: shortcutItem) {
            AppQuickActionCenter.shared.perform(action)
        }
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        for context in URLContexts {
            NotificationCenter.default.post(
                name: .deepLinkReceived,
                object: nil,
                userInfo: ["url": context.url]
            )
        }
    }

    /// Handoff continuation — called when the user picks up an activity from another device
    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        handleUserActivity(userActivity)
    }

    func windowScene(
        _ windowScene: UIWindowScene,
        performActionFor shortcutItem: UIApplicationShortcutItem
    ) async -> Bool {
        guard let action = AppQuickAction(shortcutItem: shortcutItem) else {
            return false
        }
        AppQuickActionCenter.shared.perform(action)
        return true
    }

    // MARK: - Handoff handler

    private func handleUserActivity(_ activity: NSUserActivity) {
        switch activity.activityType {
        case HandoffManager.viewChatActivityType:
            if let chatId = activity.userInfo?["chatId"] as? String {
                NotificationCenter.default.post(
                    name: .handoffChatReceived,
                    object: nil,
                    userInfo: ["chatId": chatId]
                )
            }
        case HandoffManager.browseChatsActivityType:
            // App is already at the chat list — no navigation needed
            break
        default:
            break
        }
    }

    func sceneDidDisconnect(_ scene: UIScene) {
        guard let windowScene = scene as? UIWindowScene,
              windowScene.session.role == .windowExternalDisplayNonInteractive else {
            return
        }
        ExternalDisplayCoordinator.shared.detachExternalDisplayScene(windowScene)
    }

    func windowScene(
        _ windowScene: UIWindowScene,
        didUpdate previousCoordinateSpace: UICoordinateSpace,
        interfaceOrientation previousInterfaceOrientation: UIInterfaceOrientation,
        traitCollection previousTraitCollection: UITraitCollection
    ) {
        guard windowScene.session.role == .windowExternalDisplayNonInteractive else { return }
        ExternalDisplayCoordinator.shared.updateExternalDisplayScene(windowScene)
    }
}

#endif

extension Notification.Name {
    static let deepLinkReceived = Notification.Name("openmates.deepLinkReceived")
    static let handoffChatReceived = Notification.Name("openmates.handoffChatReceived")
}

#if os(iOS)
@MainActor
final class ExternalDisplayCoordinator: ObservableObject {
    static let shared = ExternalDisplayCoordinator()

    @Published private(set) var hasExternalDisplay = false
    @Published var pointerLocation = CGPoint(x: 0.5, y: 0.5)
    @Published var composedText = ""
    @Published var clickCount = 0

    private var externalWindows: [String: UIWindow] = [:]
    private weak var activeExternalWindow: UIWindow?

    var shouldShowPhoneController: Bool {
        hasExternalDisplay && UIDevice.current.userInterfaceIdiom == .phone
    }

    private init() {}

    func attachExternalDisplayScene(_ windowScene: UIWindowScene) {
        hasExternalDisplay = true

        let window = UIWindow(windowScene: windowScene)
        window.frame = windowScene.coordinateSpace.bounds
        window.rootViewController = UIHostingController(
            rootView: ExternalDisplayAppSceneView()
                .environmentObject(self)
        )
        window.rootViewController?.view.frame = window.bounds
        window.rootViewController?.view.backgroundColor = UIColor(named: "grey-0")
        window.makeKeyAndVisible()
        externalWindows[windowScene.session.persistentIdentifier] = window
        activeExternalWindow = window
    }

    func updateExternalDisplayScene(_ windowScene: UIWindowScene) {
        guard let window = externalWindows[windowScene.session.persistentIdentifier] else { return }
        window.frame = windowScene.coordinateSpace.bounds
        window.rootViewController?.view.frame = window.bounds
    }

    func detachExternalDisplayScene(_ windowScene: UIWindowScene) {
        externalWindows[windowScene.session.persistentIdentifier]?.isHidden = true
        externalWindows[windowScene.session.persistentIdentifier] = nil
        activeExternalWindow = externalWindows.values.first
        refreshConnectedDisplays()
    }

    func refreshConnectedDisplays() {
        hasExternalDisplay = UIApplication.shared.connectedScenes.contains { scene in
            guard let windowScene = scene as? UIWindowScene else { return false }
            return windowScene.session.role == .windowExternalDisplayNonInteractive
        }
    }

    func updatePointer(from location: CGPoint, in size: CGSize) {
        guard size.width > 0, size.height > 0 else { return }
        pointerLocation = CGPoint(
            x: min(max(location.x / size.width, 0), 1),
            y: min(max(location.y / size.height, 0), 1)
        )
    }

    func registerClick() {
        clickCount += 1
    }

    func performTap() {
        registerClick()

        guard let activeExternalWindow else { return }
        let point = CGPoint(
            x: pointerLocation.x * activeExternalWindow.bounds.width,
            y: pointerLocation.y * activeExternalWindow.bounds.height
        )

        guard let targetView = activeExternalWindow.hitTest(point, with: nil) else { return }

        if let control = targetView as? UIControl {
            control.sendActions(for: [.primaryActionTriggered, .touchUpInside])
            return
        }

        _ = targetView.accessibilityActivate()
    }

    func scrollExternalDisplay(direction: ExternalDisplayScrollDirection) {
        guard let activeExternalWindow else { return }
        let point = CGPoint(
            x: pointerLocation.x * activeExternalWindow.bounds.width,
            y: pointerLocation.y * activeExternalWindow.bounds.height
        )

        guard let scrollView = scrollView(at: point, in: activeExternalWindow)
            ?? firstScrollView(in: activeExternalWindow) else {
            return
        }

        let delta = activeExternalWindow.bounds.height * 0.34
        let yOffset = direction == .down ? delta : -delta
        let minY = -scrollView.adjustedContentInset.top
        let maxY = max(
            minY,
            scrollView.contentSize.height - scrollView.bounds.height + scrollView.adjustedContentInset.bottom
        )
        let nextY = min(max(scrollView.contentOffset.y + yOffset, minY), maxY)
        scrollView.setContentOffset(CGPoint(x: scrollView.contentOffset.x, y: nextY), animated: true)
    }

    private func scrollView(at point: CGPoint, in rootView: UIView) -> UIScrollView? {
        let pointInView = rootView.convert(point, from: activeExternalWindow)
        guard rootView.bounds.contains(pointInView), !rootView.isHidden, rootView.alpha > 0 else {
            return nil
        }

        for subview in rootView.subviews.reversed() {
            if let match = scrollView(at: point, in: subview) {
                return match
            }
        }

        return rootView as? UIScrollView
    }

    private func firstScrollView(in rootView: UIView) -> UIScrollView? {
        if let scrollView = rootView as? UIScrollView {
            return scrollView
        }

        for subview in rootView.subviews {
            if let match = firstScrollView(in: subview) {
                return match
            }
        }

        return nil
    }

}

enum ExternalDisplayScrollDirection {
    case up
    case down
}

private struct ExternalDisplayAppSceneView: View {
    @StateObject private var authManager = AuthManager()
    @StateObject private var themeManager = ThemeManager()
    @StateObject private var pushManager = PushNotificationManager.shared
    @StateObject private var locManager = LocalizationManager.shared
    @StateObject private var offlineStore = OfflineStore.shared
    @EnvironmentObject private var coordinator: ExternalDisplayCoordinator

    var body: some View {
        GeometryReader { geo in
            RootView()
                .environmentObject(authManager)
                .environmentObject(themeManager)
                .environmentObject(pushManager)
                .environmentObject(locManager)
                .environmentObject(offlineStore)
                .environment(\.isExternalDisplayScene, true)
                .preferredColorScheme(themeManager.resolvedScheme)
                .environment(\.layoutDirection, locManager.currentLanguage.layoutDirection)
                .overlay {
                    Circle()
                        .fill(Color.buttonPrimary.opacity(0.92))
                        .frame(width: 22, height: 22)
                        .overlay(
                            Circle()
                                .stroke(Color.grey0, lineWidth: 3)
                        )
                        .shadow(color: .black.opacity(0.22), radius: 8, x: 0, y: 4)
                        .position(
                            x: coordinator.pointerLocation.x * geo.size.width,
                            y: coordinator.pointerLocation.y * geo.size.height
                        )
                        .scaleEffect(coordinator.clickCount.isMultiple(of: 2) ? 1 : 1.45)
                        .animation(.spring(response: 0.22, dampingFraction: 0.62), value: coordinator.clickCount)
                        .allowsHitTesting(false)
                }
                .task {
                    await locManager.restoreSavedLanguage()
                    await authManager.checkSession()
                }
                .onChange(of: authManager.state) { _, newState in
                    if case .authenticated = newState,
                       let lang = authManager.currentUser?.language,
                       let supported = SupportedLanguage.from(code: lang),
                       supported != locManager.currentLanguage {
                        Task { await locManager.setLanguage(supported) }
                    }
                }
            }
        }
    }

struct ExternalDisplayControllerView: View {
    @EnvironmentObject private var coordinator: ExternalDisplayCoordinator
    @FocusState private var isTextInputFocused: Bool
    @State private var keyboardText = ""

    var body: some View {
        ZStack {
            Color.grey0
                .ignoresSafeArea()

            VStack(spacing: .spacing8) {
                HStack(spacing: .spacing6) {
                    Image("openmates-brand")
                        .renderingMode(.original)
                        .resizable()
                        .frame(width: 38, height: 38)
                        .clipShape(Circle())

                    Text(AppStrings.openMatesName)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)

                    Spacer(minLength: .spacing6)
                }

                controllerTouchpad

                HStack(spacing: .spacing5) {
                    controllerButton(icon: nil, isPrimary: true) {
                        coordinator.performTap()
                    }
                    .overlay {
                        Circle()
                            .fill(Color.fontButton)
                            .frame(width: 10, height: 10)
                    }

                    controllerButton(icon: "up") {
                        coordinator.scrollExternalDisplay(direction: .up)
                    }

                    controllerButton(icon: "down") {
                        coordinator.scrollExternalDisplay(direction: .down)
                    }

                    controllerButton(icon: "keyboard") {
                        isTextInputFocused = true
                    }

                    TextField("", text: $keyboardText)
                        .textFieldStyle(.plain)
                        .focused($isTextInputFocused)
                        .frame(width: 1, height: 1)
                        .opacity(0.01)
                        .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing10)
        }
    }

    private var controllerTouchpad: some View {
        GeometryReader { geo in
            ZStack {
                RoundedRectangle(cornerRadius: .radius8)
                    .fill(Color.grey10)
                    .overlay(
                        RoundedRectangle(cornerRadius: .radius8)
                            .stroke(Color.grey30, lineWidth: 1)
                    )

                Circle()
                    .fill(Color.buttonPrimary)
                    .frame(width: 18, height: 18)
                    .position(
                        x: coordinator.pointerLocation.x * geo.size.width,
                        y: coordinator.pointerLocation.y * geo.size.height
                    )

                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        Icon("keyboard", size: 26)
                            .foregroundStyle(Color.fontSecondary)
                            .padding(.spacing8)
                    }
                }
            }
            .contentShape(RoundedRectangle(cornerRadius: .radius8))
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        coordinator.updatePointer(from: value.location, in: geo.size)
                    }
                    .onEnded { value in
                        coordinator.updatePointer(from: value.location, in: geo.size)
                    }
            )
            .simultaneousGesture(
                TapGesture()
                    .onEnded {
                        coordinator.performTap()
                    }
            )
        }
        .frame(maxWidth: .infinity)
        .frame(height: 360)
    }

    private func controllerButton(
        icon: String?,
        isPrimary: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Group {
                if let icon {
                    Icon(icon, size: 26)
                } else {
                    Color.clear
                }
            }
            .foregroundStyle(isPrimary ? Color.fontButton : Color.fontPrimary)
            .frame(maxWidth: .infinity)
            .frame(height: 56)
        }
        .buttonStyle(.plain)
        .background(isPrimary ? Color.buttonPrimary : Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay(
            RoundedRectangle(cornerRadius: .radius8)
                .stroke(isPrimary ? Color.buttonPrimary : Color.grey30, lineWidth: 1)
        )
    }
}
#endif
