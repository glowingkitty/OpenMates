// OpenMates native Apple app entry point.
// Universal app targeting iOS, iPadOS, and macOS via SwiftUI multiplatform.
// Wires up auth, push notifications, font registration, and WebSocket lifecycle.

import SwiftUI
import SwiftData

@main
struct OpenMatesApp: App {
    @StateObject private var authManager = AuthManager()
    @StateObject private var themeManager = ThemeManager()
    @StateObject private var pushManager = PushNotificationManager.shared

    #if os(iOS)
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    #elseif os(macOS)
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    #endif

    init() {
        FontRegistration.registerFonts()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(authManager)
                .environmentObject(themeManager)
                .environmentObject(pushManager)
                .preferredColorScheme(themeManager.resolvedScheme)
                .task {
                    await authManager.checkSession()
                }
                .onChange(of: authManager.state) { _, newState in
                    if case .authenticated = newState {
                        Task {
                            let _ = await pushManager.requestPermission()
                        }
                    }
                }
        }
        #if os(macOS)
        .defaultSize(width: 1200, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Chat") {
                    NotificationCenter.default.post(name: .newChat, object: nil)
                }
                .keyboardShortcut("n", modifiers: .command)
            }
        }
        #endif
    }
}

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
}
#elseif os(macOS)
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
}
#endif

extension Notification.Name {
    static let newChat = Notification.Name("openmates.newChat")
}
