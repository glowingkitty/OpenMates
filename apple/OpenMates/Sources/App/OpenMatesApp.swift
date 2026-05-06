// OpenMates native Apple app entry point.
// Universal app targeting iOS, iPadOS, and macOS via SwiftUI multiplatform.
// Wires up auth, push notifications, font registration, and WebSocket lifecycle.

import SwiftUI
import SwiftData

struct AppWindowLaunchCommand: Codable, Hashable {
    enum Action: String, Codable, Hashable {
        case newWindow
        case newChat
    }

    let id: String
    let action: Action

    init(action: Action, id: String = UUID().uuidString) {
        self.id = id
        self.action = action
    }

    static func newWindow() -> AppWindowLaunchCommand {
        AppWindowLaunchCommand(action: .newWindow)
    }

    static func newChat() -> AppWindowLaunchCommand {
        AppWindowLaunchCommand(action: .newChat)
    }
}

@main
struct OpenMatesApp: App {
    private static let mainWindowID = "openmates-main-window"

    @StateObject private var authManager = AuthManager()
    @StateObject private var themeManager = ThemeManager()
    @StateObject private var pushManager = PushNotificationManager.shared
    @StateObject private var locManager = LocalizationManager.shared
    @StateObject private var offlineStore = OfflineStore.shared

    #if os(iOS)
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    #elseif os(macOS)
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @Environment(\.openWindow) private var openWindow
    @FocusedValue(\.newChatCommand) private var focusedNewChatCommand
    #endif

    init() {
        FontRegistration.registerFonts()
    }

    var body: some Scene {
        WindowGroup(id: Self.mainWindowID, for: AppWindowLaunchCommand.self) { launchCommand in
            RootView(launchCommand: launchCommand.wrappedValue)
                .environmentObject(authManager)
                .environmentObject(themeManager)
                .environmentObject(pushManager)
                .environmentObject(locManager)
                .environmentObject(offlineStore)
                .preferredColorScheme(themeManager.resolvedScheme)
                .environment(\.layoutDirection, locManager.currentLanguage.layoutDirection)
                .task {
                    await locManager.restoreSavedLanguage()
                    await authManager.checkSession()
                }
                .onChange(of: authManager.state) { _, newState in
                    if case .authenticated = newState {
                        Task {
                            let _ = await pushManager.requestPermission()
                        }
                        // Sync language from user profile
                        if let lang = authManager.currentUser?.language,
                           let supported = SupportedLanguage.from(code: lang),
                           supported != locManager.currentLanguage {
                            Task { await locManager.setLanguage(supported) }
                        }
                    }
                }
                #if os(macOS)
                .modifier(AppWindowCommandInstaller {
                    openWindow(id: Self.mainWindowID, value: $0)
                })
                #endif
        }
        #if os(macOS)
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1200, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button(AppStrings.newWindow) {
                    AppWindowCommandCenter.shared.openNewWindow()
                }
                .keyboardShortcut("n", modifiers: .command)

                Button(AppStrings.newChat) {
                    if let focusedNewChatCommand {
                        focusedNewChatCommand()
                    } else {
                        AppWindowCommandCenter.shared.openNewChatWindow()
                    }
                }
                .keyboardShortcut("n", modifiers: [.command, .shift])
            }
            CommandGroup(after: .appVisibility) {
                Button(AppStrings.settingsIncognito) {
                    NotificationCenter.default.post(name: .toggleIncognito, object: nil)
                }
                .keyboardShortcut("i", modifiers: [.command, .shift])
            }
        }
        #endif
    }
}

#if os(macOS)
@MainActor
private final class AppWindowCommandCenter {
    static let shared = AppWindowCommandCenter()

    var openMainWindow: ((AppWindowLaunchCommand) -> Void)?

    func openNewWindow() {
        if let openMainWindow {
            openMainWindow(.newWindow())
        } else {
            NSApp.sendAction(#selector(NSResponder.newWindowForTab(_:)), to: nil, from: nil)
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    func openNewChatWindow() {
        if let openMainWindow {
            openMainWindow(.newChat())
        } else {
            NotificationCenter.default.post(name: .newChat, object: nil)
        }
        NSApp.activate(ignoringOtherApps: true)
    }
}

private struct AppWindowCommandInstaller: ViewModifier {
    let openMainWindow: (AppWindowLaunchCommand) -> Void

    func body(content: Content) -> some View {
        content.onAppear {
            AppWindowCommandCenter.shared.openMainWindow = openMainWindow
        }
    }
}

private struct NewChatCommandKey: FocusedValueKey {
    typealias Value = @MainActor () -> Void
}

extension FocusedValues {
    var newChatCommand: (@MainActor () -> Void)? {
        get { self[NewChatCommandKey.self] }
        set { self[NewChatCommandKey.self] = newValue }
    }
}
#endif

// MARK: - App delegate for push notification token delivery

#if os(iOS)
class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task { @MainActor in
            PushNotificationManager.shared.handleDeviceToken(deviceToken)
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        Task { @MainActor in
            PushNotificationManager.shared.handleRegistrationError(error)
        }
    }

    // iPad multitasking: register SceneDelegate for Split View / Slide Over / Stage Manager
    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        let config = UISceneConfiguration(name: nil, sessionRole: connectingSceneSession.role)
        config.delegateClass = SceneDelegate.self
        return config
    }
}
#elseif os(macOS)
@MainActor
class AppDelegate: NSObject, NSApplicationDelegate {
    func application(
        _ application: NSApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task { @MainActor in
            PushNotificationManager.shared.handleDeviceToken(deviceToken)
        }
    }

    func application(
        _ application: NSApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        Task { @MainActor in
            PushNotificationManager.shared.handleRegistrationError(error)
        }
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()

        let newWindowItem = NSMenuItem(
            title: AppStrings.newWindow,
            action: #selector(openNewWindowFromDockMenu),
            keyEquivalent: ""
        )
        newWindowItem.target = self
        menu.addItem(newWindowItem)

        let newChatItem = NSMenuItem(
            title: AppStrings.newChat,
            action: #selector(openNewChatFromDockMenu),
            keyEquivalent: ""
        )
        newChatItem.target = self
        menu.addItem(newChatItem)

        return menu
    }

    @objc private func openNewWindowFromDockMenu() {
        AppWindowCommandCenter.shared.openNewWindow()
    }

    @objc private func openNewChatFromDockMenu() {
        AppWindowCommandCenter.shared.openNewChatWindow()
    }
}
#endif

extension Notification.Name {
    static let newChat = Notification.Name("openmates.newChat")
    static let toggleIncognito = Notification.Name("openmates.toggleIncognito")
    static let embedRefreshNeeded = Notification.Name("openmates.embedRefreshNeeded")
    static let openAuth = Notification.Name("openmates.openAuth")
}
