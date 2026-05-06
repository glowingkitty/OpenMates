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
import UIKit

#if os(iOS)
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
        switch shortcutItem.type {
        case "org.openmates.newchat":
            NotificationCenter.default.post(name: .newChat, object: nil)
            return true
        default:
            return false
        }
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

    var shouldShowPhoneController: Bool {
        hasExternalDisplay && UIDevice.current.userInterfaceIdiom == .phone
    }

    private init() {}

    func attachExternalDisplayScene(_ windowScene: UIWindowScene) {
        hasExternalDisplay = true

        let window = UIWindow(windowScene: windowScene)
        window.rootViewController = UIHostingController(
            rootView: ExternalDisplayStageView()
                .environmentObject(self)
        )
        window.isHidden = false
        externalWindows[windowScene.session.persistentIdentifier] = window
    }

    func detachExternalDisplayScene(_ windowScene: UIWindowScene) {
        externalWindows[windowScene.session.persistentIdentifier]?.isHidden = true
        externalWindows[windowScene.session.persistentIdentifier] = nil
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

}

private struct ExternalDisplayStageView: View {
    @EnvironmentObject private var coordinator: ExternalDisplayCoordinator

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.grey0
                    .ignoresSafeArea()

                VStack(spacing: .spacing12) {
                    externalHeader
                    conversationPreview
                    composerPreview
                }
                .padding(.horizontal, .spacing24)
                .padding(.vertical, .spacing16)
                .frame(maxWidth: .infinity, maxHeight: .infinity)

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
            }
        }
    }

    private var externalHeader: some View {
        HStack(spacing: .spacing8) {
            Image("openmates-brand")
                .renderingMode(.original)
                .resizable()
                .frame(width: 46, height: 46)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(AppStrings.openMatesName)
                    .font(.omH2)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                Text(AppStrings.newChat)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }

            Spacer(minLength: .spacing8)
        }
    }

    private var conversationPreview: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                ExternalDisplayBubble(text: AppStrings.whatDoYouNeedHelpWith, isUser: false)
                if !coordinator.composedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    ExternalDisplayBubble(text: coordinator.composedText, isUser: true)
                }
            }
            .frame(maxWidth: 1000)
            .frame(maxWidth: .infinity)
            .padding(.vertical, .spacing8)
        }
    }

    private var composerPreview: some View {
        HStack(spacing: .spacing6) {
            Text(coordinator.composedText.isEmpty ? AppStrings.typeMessage : coordinator.composedText)
                .font(.omP)
                .foregroundStyle(coordinator.composedText.isEmpty ? Color.fontTertiary : Color.fontPrimary)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing6)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                .overlay(
                    RoundedRectangle(cornerRadius: .radiusFull)
                        .stroke(Color.buttonPrimary, lineWidth: 2)
                )

            Text(AppStrings.sendAction)
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontButton)
                .padding(.horizontal, .spacing12)
                .padding(.vertical, .spacing8)
                .background(coordinator.composedText.isEmpty ? Color.grey20 : Color.buttonPrimary)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
        }
        .frame(maxWidth: 1000)
    }
}

private struct ExternalDisplayBubble: View {
    let text: String
    let isUser: Bool

    var body: some View {
        HStack {
            if isUser {
                Spacer(minLength: 100)
            }

            Text(text)
                .font(.omP)
                .foregroundStyle(isUser ? Color.grey100 : Color.fontPrimary)
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing6)
                .background(isUser ? Color.greyBlue : Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: 13))
                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)

            if !isUser {
                Spacer(minLength: 100)
            }
        }
    }
}

struct ExternalDisplayControllerView: View {
    @EnvironmentObject private var coordinator: ExternalDisplayCoordinator
    @FocusState private var isTextInputFocused: Bool

    var body: some View {
        ZStack {
            Color.grey0
                .ignoresSafeArea()

            VStack(spacing: .spacing10) {
                HStack(spacing: .spacing6) {
                    Image("openmates-brand")
                        .renderingMode(.original)
                        .resizable()
                        .frame(width: 38, height: 38)
                        .clipShape(Circle())

                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(AppStrings.openMatesName)
                            .font(.omH3)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                        Text(AppStrings.newChat)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontSecondary)
                    }

                    Spacer(minLength: .spacing6)
                }

                controllerTouchpad

                HStack(spacing: .spacing5) {
                    TextField(AppStrings.typeMessage, text: $coordinator.composedText, axis: .vertical)
                        .textFieldStyle(.plain)
                        .font(.omP)
                        .lineLimit(1...4)
                        .tint(Color.buttonPrimary)
                        .focused($isTextInputFocused)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing6)
                        .background(Color.grey0)
                        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                        .overlay(
                            RoundedRectangle(cornerRadius: .radiusFull)
                                .stroke(isTextInputFocused ? Color.buttonPrimary : Color.grey30, lineWidth: 2)
                        )
                        .shadow(
                            color: isTextInputFocused ? Color.buttonPrimary.opacity(0.22) : .clear,
                            radius: 3,
                            x: 0,
                            y: 0
                        )

                    Button {
                        coordinator.registerClick()
                        coordinator.composedText = ""
                    } label: {
                        Text(AppStrings.sendAction)
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(coordinator.composedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing10)
        }
        .onAppear {
            isTextInputFocused = true
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
                        coordinator.registerClick()
                    }
            )
        }
        .frame(maxWidth: .infinity)
        .frame(height: 320)
    }
}
#endif
