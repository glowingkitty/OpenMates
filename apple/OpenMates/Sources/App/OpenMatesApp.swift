// OpenMates native Apple app entry point.
// Universal app targeting iOS, iPadOS, and macOS via SwiftUI multiplatform.
// Wires up auth, push notifications, font registration, and WebSocket lifecycle.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//          frontend/packages/ui/src/components/chats/Chat.svelte
// CSS:     frontend/packages/ui/src/styles/fields.css
//          frontend/packages/ui/src/styles/chat.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import SwiftData
#if os(iOS)
import UIKit
#elseif os(macOS)
import UniformTypeIdentifiers
#endif

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

enum AppQuickAction: String {
    case ask
    case askAboutPhoto
    case search
    case incognitoAsk
}

#if os(iOS)
extension AppQuickAction {
    static let askType = "org.openmates.ask"
    static let legacyNewChatType = "org.openmates.newchat"
    static let askAboutPhotoType = "org.openmates.ask-about-photo"
    static let searchType = "org.openmates.search"
    static let incognitoAskType = "org.openmates.incognito-ask"

    var shortcutType: String {
        switch self {
        case .ask:
            return Self.askType
        case .askAboutPhoto:
            return Self.askAboutPhotoType
        case .search:
            return Self.searchType
        case .incognitoAsk:
            return Self.incognitoAskType
        }
    }

    @MainActor
    static var shortcutItems: [UIApplicationShortcutItem] {
        [
            UIApplicationShortcutItem(
                type: AppQuickAction.ask.shortcutType,
                localizedTitle: AppStrings.quickActionAsk,
                localizedSubtitle: nil,
                icon: UIApplicationShortcutIcon(systemImageName: "square.and.pencil"),
                userInfo: nil
            ),
            UIApplicationShortcutItem(
                type: AppQuickAction.askAboutPhoto.shortcutType,
                localizedTitle: AppStrings.quickActionAskAboutPhoto,
                localizedSubtitle: nil,
                icon: UIApplicationShortcutIcon(systemImageName: "camera"),
                userInfo: nil
            ),
            UIApplicationShortcutItem(
                type: AppQuickAction.search.shortcutType,
                localizedTitle: AppStrings.search,
                localizedSubtitle: nil,
                icon: UIApplicationShortcutIcon(systemImageName: "magnifyingglass"),
                userInfo: nil
            ),
            UIApplicationShortcutItem(
                type: AppQuickAction.incognitoAsk.shortcutType,
                localizedTitle: AppStrings.quickActionIncognitoAsk,
                localizedSubtitle: nil,
                icon: UIApplicationShortcutIcon(systemImageName: "eye.slash"),
                userInfo: nil
            )
        ]
    }
}
#endif

@MainActor
final class AppQuickActionCenter {
    static let shared = AppQuickActionCenter()

    private var pendingAction: AppQuickAction?

    private init() {}

    func perform(_ action: AppQuickAction) {
        pendingAction = action
        NotificationCenter.default.post(
            name: .quickActionReceived,
            object: nil,
            userInfo: ["action": action.rawValue]
        )
    }

    func consumePendingAction() -> AppQuickAction? {
        let action = pendingAction
        pendingAction = nil
        return action
    }

    func clearPendingAction(_ action: AppQuickAction) {
        if pendingAction == action {
            pendingAction = nil
        }
    }
}

@MainActor
final class AppSessionCoordinator: ObservableObject {
    static let shared = AppSessionCoordinator()

    let chatStore = ChatStore()
    let webSocketManager = WebSocketManager()

    private var offlineBridgeStorage: OfflineSyncBridge?
    private var didLoadFromDisk = false
    private var didStartNetworkMonitoring = false

    private init() {}

    func prepareAuthenticatedRuntime(lastOpenedChatId: String?) -> OfflineSyncBridge {
        let bridge = offlineBridge()
        chatStore.setBridge(bridge)

        if !didLoadFromDisk {
            bridge.loadFromDisk(lastOpenedChatId: lastOpenedChatId)
            didLoadFromDisk = true
        }

        if !didStartNetworkMonitoring {
            bridge.startNetworkMonitoring()
            didStartNetworkMonitoring = true
        }

        return bridge
    }

    func resetTransientRuntime() {
        webSocketManager.disconnect()
        chatStore.clearInMemory()
        didLoadFromDisk = false
    }

    private func offlineBridge() -> OfflineSyncBridge {
        if let offlineBridgeStorage {
            return offlineBridgeStorage
        }
        let bridge = OfflineSyncBridge(chatStore: chatStore, wsManager: webSocketManager)
        offlineBridgeStorage = bridge
        return bridge
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
        NativeMetricKitReporter.shared.start()
    }

    @SceneBuilder
    var body: some Scene {
        mainWindowScene

        #if os(macOS)
        quickCaptureMenuBarScene
        #endif
    }

    @SceneBuilder
    private var mainWindowScene: some Scene {
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
                    NativeDiagnostics.info("Apple app runtime starting", category: "app_lifecycle")
                    NativePerformanceMonitor.shared.startSampling()
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--openmates-keychain-self-test") {
                        KeychainHelper.debugSelfTest()
                    }
                    #endif
                    await locManager.restoreSavedLanguage()
                    await authManager.checkSession()
                }
                .onChange(of: authManager.state) { _, newState in
                    if case .authenticated = newState {
                        NativeLogForwarder.shared.startDefaultTelemetry()
                        Task {
                            await NativeLogForwarder.shared.syncActiveDebugSession()
                        }
                        Task {
                            let _ = await pushManager.requestPermission()
                        }
                        // Sync language from user profile
                        if let lang = authManager.currentUser?.language,
                           let supported = SupportedLanguage.from(code: lang),
                           supported != locManager.currentLanguage {
                            Task { await locManager.setLanguage(supported) }
                        }
                    } else {
                        NativeLogForwarder.shared.stopDefaultTelemetry()
                        NativeLogForwarder.shared.stopDebugSession()
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

    #if os(macOS)
    private var quickCaptureMenuBarScene: some Scene {
        MenuBarExtra {
            MacMenuBarQuickCaptureView()
                .environmentObject(authManager)
                .environmentObject(locManager)
                .frame(width: 430)
        } label: {
            Image("openmates")
                .renderingMode(.original)
                .resizable()
                .scaledToFit()
                .frame(width: 18, height: 18)
        }
        .menuBarExtraStyle(.window)
    }
    #endif
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

@MainActor
private final class MacMenuBarQuickCaptureViewModel: ObservableObject {
    enum Tab: String, CaseIterable, Identifiable {
        case chats
        case projects
        case plans
        case tasks
        case workflows

        var id: String { rawValue }

        @MainActor var title: String {
            switch self {
            case .chats: return AppStrings.chats
            case .projects: return AppStrings.projects
            case .plans: return AppStrings.plans
            case .tasks: return AppStrings.tasks
            case .workflows: return AppStrings.workflows
            }
        }
    }

    struct CaptureJob: Identifiable, Equatable {
        enum Status: Equatable {
            case uploading
            case transcribing
            case sending
            case sent
            case failed(String)

            var blocksSend: Bool {
                switch self {
                case .uploading, .transcribing:
                    return true
                case .sending, .sent, .failed:
                    return false
                }
            }

            @MainActor var label: String {
                switch self {
                case .uploading:
                    return AppStrings.uploadProgressUploading(percent: "")
                case .transcribing:
                    return AppStrings.uploadProgressTranscribing
                case .sending:
                    return AppStrings.loading
                case .sent:
                    return AppStrings.success
                case .failed:
                    return AppStrings.error
                }
            }
        }

        let id: UUID
        let title: String
        var status: Status
    }

    @Published var selectedTab: Tab = .chats
    @Published var message = ""
    @Published var recentChats: [BackgroundChatSender.DestinationChat] = []
    @Published var selectedChat: BackgroundChatSender.DestinationChat?
    @Published var draftDestination: BackgroundChatSender.DestinationChat?
    @Published var pendingEmbeds: [BackgroundPreparedEmbed] = []
    @Published var jobs: [CaptureJob] = []
    @Published var isLoadingRecentChats = false
    @Published var isSending = false
    @Published var error: String?

    private let sender = BackgroundChatSender()

    var hasActiveAttachmentWork: Bool {
        jobs.contains { $0.status.blocksSend }
    }

    var isDestinationLocked: Bool {
        hasActiveAttachmentWork || !pendingEmbeds.isEmpty
    }

    var canSend: Bool {
        !isSending && !hasActiveAttachmentWork
    }

    func loadRecentChats() {
        guard !isLoadingRecentChats else { return }
        isLoadingRecentChats = true
        Task {
            do {
                recentChats = try await sender.loadRecentChats(limit: 10)
            } catch {
                NativeDiagnostics.warning("Quick capture recent chat load failed: \(type(of: error))", category: "quick_capture")
            }
            isLoadingRecentChats = false
        }
    }

    func selectNewChat() {
        guard !isDestinationLocked else { return }
        selectedChat = nil
        draftDestination = nil
    }

    func selectChat(_ chat: BackgroundChatSender.DestinationChat) {
        guard !isDestinationLocked else { return }
        selectedChat = chat
        draftDestination = nil
    }

    func sendCurrentMessage(closePopover: Bool = false) {
        guard canSend else { return }
        let text = message
        let embeds = pendingEmbeds
        do {
            _ = try BackgroundChatSendContract.contentForSend(text: text, embeds: embeds)
        } catch {
            self.error = error.localizedDescription
            return
        }
        isSending = true
        let jobId = UUID()
        jobs.insert(CaptureJob(id: jobId, title: text.isEmpty ? AppStrings.attachFiles : text, status: .sending), at: 0)
        message = ""
        pendingEmbeds = []
        let destination = selectedChat ?? draftDestination
        draftDestination = nil
        if closePopover {
            NSApp.keyWindow?.orderOut(nil)
        }

        Task {
            do {
                _ = try await sender.send(.init(content: text, destination: destination, embeds: embeds))
                updateJob(jobId, status: .sent)
            } catch {
                message = text
                pendingEmbeds = embeds
                if selectedChat == nil {
                    draftDestination = destination
                }
                updateJob(jobId, status: .failed(error.localizedDescription))
                self.error = error.localizedDescription
            }
            isSending = false
        }
    }

    func handleDroppedURLs(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        let destination = ensureAttachmentDestination()
        for url in urls {
            let jobId = UUID()
            jobs.insert(CaptureJob(id: jobId, title: url.lastPathComponent, status: .uploading), at: 0)
            Task {
                do {
                    try validateAttachmentSize(url)
                    let data = try Data(contentsOf: url)
                    let type = contentType(for: url)
                    if BackgroundAttachmentClassifier.classification(filename: url.lastPathComponent, contentType: type) == nil {
                        throw BackgroundChatSendError.unsupportedAttachment
                    }
                    updateJob(jobId, status: type.hasPrefix("audio/") ? .transcribing : .uploading)
                    let embed = try await sender.prepareAttachment(
                        data: data,
                        filename: url.lastPathComponent,
                        contentType: type,
                        chatId: destination.id
                    )
                    pendingEmbeds.append(embed)
                    updateJob(jobId, status: .sent)
                } catch {
                    updateJob(jobId, status: .failed(error.localizedDescription))
                    self.error = error.localizedDescription
                }
            }
        }
    }

    func handleAttachmentData(data: Data, filename: String, contentType: String) {
        let destination = ensureAttachmentDestination()
        let jobId = UUID()
        jobs.insert(CaptureJob(id: jobId, title: filename, status: .uploading), at: 0)
        Task {
            do {
                guard data.count <= BackgroundAttachmentClassifier.maxFileSizeBytes else {
                    throw BackgroundChatSendError.unsupportedAttachment
                }
                if BackgroundAttachmentClassifier.classification(filename: filename, contentType: contentType) == nil {
                    throw BackgroundChatSendError.unsupportedAttachment
                }
                updateJob(jobId, status: contentType.hasPrefix("audio/") ? .transcribing : .uploading)
                let embed = try await sender.prepareAttachment(
                    data: data,
                    filename: filename,
                    contentType: contentType,
                    chatId: destination.id
                )
                pendingEmbeds.append(embed)
                updateJob(jobId, status: .sent)
            } catch {
                updateJob(jobId, status: .failed(error.localizedDescription))
                self.error = error.localizedDescription
            }
        }
    }

    func handleRecording(url: URL, duration: TimeInterval, closePopover: Bool) {
        let destination = ensureAttachmentDestination()
        let text = message
        message = ""
        let jobId = UUID()
        jobs.insert(CaptureJob(id: jobId, title: AppStrings.recordAudio, status: .uploading), at: 0)
        if closePopover {
            NSApp.keyWindow?.orderOut(nil)
        }
        Task {
            do {
                let data = try Data(contentsOf: url)
                guard data.count <= BackgroundAttachmentClassifier.maxFileSizeBytes else {
                    throw BackgroundChatSendError.unsupportedAttachment
                }
                updateJob(jobId, status: .transcribing)
                let embed = try await sender.prepareAttachment(
                    data: data,
                    filename: url.lastPathComponent,
                    contentType: "audio/mp4",
                    chatId: destination.id,
                    durationSeconds: duration
                )
                updateJob(jobId, status: .sending)
                _ = try await sender.send(.init(content: text, destination: destination, embeds: [embed]))
                updateJob(jobId, status: .sent)
            } catch {
                message = text
                updateJob(jobId, status: .failed(error.localizedDescription))
                self.error = error.localizedDescription
            }
        }
    }

    func deleteJob(_ id: UUID) {
        jobs.removeAll { $0.id == id }
    }

    private func ensureAttachmentDestination() -> BackgroundChatSender.DestinationChat {
        if let selectedChat { return selectedChat }
        if let draftDestination { return draftDestination }
        let destination = BackgroundChatSender.DestinationChat(
            id: UUID().uuidString,
            title: AppStrings.newChat,
            lastMessageAt: nil,
            createdAt: ISO8601DateFormatter().string(from: Date()),
            updatedAt: nil,
            appId: nil,
            encryptedTitle: nil,
            encryptedCategory: nil,
            encryptedIcon: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0
        )
        draftDestination = destination
        return destination
    }

    private func updateJob(_ id: UUID, status: CaptureJob.Status) {
        if let index = jobs.firstIndex(where: { $0.id == id }) {
            jobs[index].status = status
        }
    }

    private func contentType(for url: URL) -> String {
        if let type = UTType(filenameExtension: url.pathExtension), let mime = type.preferredMIMEType {
            return mime
        }
        let ext = url.pathExtension.lowercased()
        switch ext {
        case "m4a", "mp4": return "audio/mp4"
        case "mp3": return "audio/mpeg"
        case "wav": return "audio/wav"
        case "webm": return "audio/webm"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "pdf": return "application/pdf"
        default: return "application/octet-stream"
        }
    }

    private func validateAttachmentSize(_ url: URL) throws {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        if let size = values.fileSize, size > BackgroundAttachmentClassifier.maxFileSizeBytes {
            throw BackgroundChatSendError.unsupportedAttachment
        }
    }

    #if DEBUG
    func seedUITestStateIfRequested() {
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("--ui-test-seed-quick-capture-recent-chat"), recentChats.isEmpty {
            recentChats = [
                BackgroundChatSender.DestinationChat(
                    id: "quick-capture-ui-test-chat",
                    title: "UI Test Chat",
                    lastMessageAt: nil,
                    createdAt: ISO8601DateFormatter().string(from: Date()),
                    updatedAt: nil,
                    appId: nil,
                    encryptedTitle: nil,
                    encryptedCategory: nil,
                    encryptedIcon: nil,
                    encryptedChatKey: nil,
                    messagesV: 1,
                    titleV: 0
                )
            ]
        }

        if arguments.contains("--ui-test-seed-quick-capture-attachment"), pendingEmbeds.isEmpty {
            pendingEmbeds = [
                BackgroundPreparedEmbed(
                    id: "quick-capture-ui-test-embed",
                    type: "application/pdf",
                    referenceType: "application",
                    status: "processing",
                    content: [
                        "app_id": "pdf",
                        "type": "application",
                        "status": "processing",
                        "filename": "Shared fixture.pdf"
                    ],
                    textPreview: "Shared fixture.pdf"
                )
            ]
            jobs.insert(CaptureJob(id: UUID(), title: "Shared fixture.pdf", status: .sent), at: 0)
        }
    }
    #endif
}

struct MacMenuBarQuickCaptureView: View {
    @StateObject private var viewModel = MacMenuBarQuickCaptureViewModel()
    @StateObject private var recorder = VoiceRecorder()
    @FocusState private var inputFocused: Bool
    @State private var isRecordingGestureActive = false

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            headerTabs
            Divider().opacity(0.35)
            if viewModel.selectedTab == .chats {
                chatsContent
            } else {
                placeholderContent(for: viewModel.selectedTab)
            }
        }
        .padding(.spacing8)
        .background(Color.grey0)
        .onAppear {
            inputFocused = true
            #if DEBUG
            viewModel.seedUITestStateIfRequested()
            #endif
            viewModel.loadRecentChats()
        }
    }

    private var headerTabs: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing4) {
                ForEach(MacMenuBarQuickCaptureViewModel.Tab.allCases) { tab in
                    Button {
                        viewModel.selectedTab = tab
                    } label: {
                        Text(tab.title)
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(viewModel.selectedTab == tab ? Color.fontButton : Color.fontPrimary)
                            .padding(.horizontal, .spacing6)
                            .padding(.vertical, .spacing3)
                            .background(viewModel.selectedTab == tab ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.grey10))
                            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("quick-capture-tab-\(tab.rawValue)")
                }
            }
        }
    }

    private var chatsContent: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            destinationStrip
            composer
            if !viewModel.pendingEmbeds.isEmpty {
                pendingAttachments
            }
            statusList
            if let error = viewModel.error {
                Text(error)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("quick-capture-error")
            }
        }
    }

    private var destinationStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing4) {
                destinationButton(title: AppStrings.newChat, selected: viewModel.selectedChat == nil) {
                    viewModel.selectNewChat()
                }
                ForEach(viewModel.recentChats) { chat in
                    destinationButton(title: chat.displayTitle, selected: viewModel.selectedChat?.id == chat.id) {
                        viewModel.selectChat(chat)
                    }
                }
            }
        }
        .accessibilityIdentifier("quick-capture-recent-chats")
    }

    private func destinationButton(title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.omXs.weight(.semibold))
                .foregroundStyle(selected ? Color.fontButton : Color.fontPrimary)
                .lineLimit(1)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing3)
                .background(selected ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.grey10))
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        }
        .buttonStyle(.plain)
        .disabled(viewModel.isDestinationLocked)
        .opacity(viewModel.isDestinationLocked ? 0.55 : 1)
    }

    private var composer: some View {
        VStack(spacing: .spacing4) {
            TextField("", text: $viewModel.message, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.omP)
                .lineLimit(2...5)
                .focused($inputFocused)
                .tint(Color.buttonPrimary)
                .padding(.spacing6)
                .background(Color.greyBlue)
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .overlay(alignment: .topLeading) {
                    if viewModel.message.isEmpty && !inputFocused {
                        Text(AppStrings.whatDoYouNeedHelpWith)
                            .font(.omP)
                            .foregroundStyle(Color.fontTertiary)
                            .padding(.spacing6)
                            .allowsHitTesting(false)
                    }
                }
                .accessibilityIdentifier("quick-capture-message-editor")
                .onDrop(of: [UTType.fileURL.identifier], isTargeted: nil) { providers in
                    loadDroppedURLs(from: providers)
                }
                .onPasteCommand(of: [UTType.fileURL, UTType.image, UTType.png, UTType.jpeg]) { providers in
                    loadPastedItems(from: providers)
                }

            HStack(spacing: .spacing4) {
                recordButton
                Spacer()
                Button {
                    viewModel.sendCurrentMessage()
                } label: {
                    Text(AppStrings.sendAction)
                        .font(.omSmall.weight(.bold))
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing4)
                        .background(LinearGradient.primary)
                        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                }
                .buttonStyle(.plain)
                .disabled(!viewModel.canSend)
                .opacity(viewModel.canSend ? 1 : 0.55)
                .accessibilityIdentifier("quick-capture-send-button")
            }
        }
        .padding(.spacing5)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .accessibilityIdentifier("quick-capture-composer")
    }

    private var recordButton: some View {
        Button {} label: {
            Icon("recordaudio", size: 22)
                .foregroundStyle(Color.fontButton)
                .frame(width: 42, height: 42)
                .background(recorder.isRecording ? Color.error : Color.buttonPrimary)
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .simultaneousGesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard !isRecordingGestureActive else { return }
                    isRecordingGestureActive = true
                    recorder.startRecording()
                }
                .onEnded { _ in
                    isRecordingGestureActive = false
                    if let url = recorder.stopRecording() {
                        viewModel.handleRecording(url: url, duration: recorder.duration, closePopover: true)
                    }
                }
        )
        .accessibilityIdentifier("quick-capture-record-audio-button")
    }

    private var pendingAttachments: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            ForEach(viewModel.pendingEmbeds) { embed in
                HStack(spacing: .spacing3) {
                    Icon("files", size: 14)
                    Text(embed.textPreview ?? embed.id)
                        .font(.omXs)
                        .lineLimit(1)
                }
                .foregroundStyle(Color.fontSecondary)
            }
        }
        .accessibilityIdentifier("quick-capture-pending-attachments")
    }

    private var statusList: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            ForEach(viewModel.jobs.prefix(5)) { job in
                HStack(spacing: .spacing3) {
                    Text(job.title)
                        .font(.omXs)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                    Spacer()
                    Text(job.status.label)
                        .font(.omMicro.weight(.semibold))
                        .foregroundStyle(statusColor(job.status))
                    Button {
                        viewModel.deleteJob(job.id)
                    } label: {
                        Icon("close", size: 12)
                            .foregroundStyle(Color.fontTertiary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.delete)
                }
            }
        }
        .accessibilityIdentifier("quick-capture-status-list")
    }

    private func placeholderContent(for tab: MacMenuBarQuickCaptureViewModel.Tab) -> some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            Text(AppStrings.workspacePreviewTitle(tab.title))
                .font(.omH3)
                .foregroundStyle(Color.fontPrimary)
            Text(AppStrings.workspacePreviewBody(tab.title))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .accessibilityIdentifier("quick-capture-placeholder-\(tab.rawValue)")
    }

    private func statusColor(_ status: MacMenuBarQuickCaptureViewModel.CaptureJob.Status) -> Color {
        switch status {
        case .sent:
            return Color.buttonPrimary
        case .failed:
            return Color.error
        default:
            return Color.fontSecondary
        }
    }

    private func loadDroppedURLs(from providers: [NSItemProvider]) -> Bool {
        var handled = false
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            handled = true
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                let url: URL?
                if let data = item as? Data {
                    url = URL(dataRepresentation: data, relativeTo: nil)
                } else {
                    url = item as? URL
                }
                guard let url else { return }
                Task { @MainActor in
                    viewModel.handleDroppedURLs([url])
                }
            }
        }
        return handled
    }

    private func loadPastedItems(from providers: [NSItemProvider]) {
        if loadDroppedURLs(from: providers) { return }
        for provider in providers {
            let typeIdentifier = provider.registeredTypeIdentifiers.first { identifier in
                UTType(identifier)?.conforms(to: .image) == true
            }
            guard let typeIdentifier else { continue }
            let filename = pastedFilename(from: provider, typeIdentifier: typeIdentifier)
            let contentType = UTType(typeIdentifier)?.preferredMIMEType ?? "image/png"
            provider.loadDataRepresentation(forTypeIdentifier: typeIdentifier) { data, _ in
                guard let data else { return }
                Task { @MainActor in
                    viewModel.handleAttachmentData(data: data, filename: filename, contentType: contentType)
                }
            }
        }
    }

    private func pastedFilename(from provider: NSItemProvider, typeIdentifier: String) -> String {
        if let suggestedName = provider.suggestedName, !suggestedName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            if URL(fileURLWithPath: suggestedName).pathExtension.isEmpty,
               let ext = UTType(typeIdentifier)?.preferredFilenameExtension {
                return "\(suggestedName).\(ext)"
            }
            return suggestedName
        }
        return "Pasted Image.\(UTType(typeIdentifier)?.preferredFilenameExtension ?? "png")"
    }
}
#endif

// MARK: - App delegate for push notification token delivery

#if os(iOS)
@MainActor
class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        application.shortcutItems = AppQuickAction.shortcutItems
        return true
    }

    func applicationDidBecomeActive(_ application: UIApplication) {
        application.shortcutItems = AppQuickAction.shortcutItems
    }

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
    static let quickActionReceived = Notification.Name("openmates.quickActionReceived")
    static let toggleIncognito = Notification.Name("openmates.toggleIncognito")
    static let embedRefreshNeeded = Notification.Name("openmates.embedRefreshNeeded")
    static let openAuth = Notification.Name("openmates.openAuth")
}
