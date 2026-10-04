// Compact Watch adaptation of the iPhone/web chat banner and share settings.
// Web: frontend/packages/ui/src/components/ChatHeader.svelte
//      frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Tokens: generated gradients, colors, spacing and typography.
import SwiftUI

/// Cached visual identity used by both workspace rows and the opened chat.
/// Category labels use existing web interest translations rather than mate names.
@MainActor
enum WatchChatIdentityPresentation {
    static func gradient(for category: String?) -> LinearGradient {
        guard let category else { return .primary }
        return CategoryMapping.gradient(for: category)
    }

    static func categoryLabel(for category: String?) -> String? {
        guard let category, CategoryMapping.isKnownCategory(category) else { return nil }
        switch category {
        case "openmates_official": return "OpenMates"
        case "onboarding_support": return WatchLocalization.text("settings.support")
        default: return WatchLocalization.text("chat.interests.\(category)")
        }
    }

    static func icon(for chat: WatchChatSummary) -> String {
        // Watch reuses generated Lucide assets that are actually bundled.
        let override = chat.icon?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if bundledLucideIcons.contains(override) { return "lucide-" + override }
        guard let category = chat.category, CategoryMapping.isKnownCategory(category) else {
            return "lucide-help-circle"
        }
        return "lucide-" + CategoryMapping.lucideIconName(for: category)
    }

    private static let bundledLucideIcons: Set<String> = [
        "clock", "palette", "wrench", "briefcase", "newspaper", "dollar-sign", "heart",
        "list-checks", "users", "workflow", "zap", "globe", "cloud-rain", "archive",
        "folder-kanban", "compass", "microscope", "megaphone", "folder", "map-pin",
        "chevron-down", "hash", "shield-check", "download", "trending-up", "heading",
        "help-circle", "utensils", "link", "tv", "repeat", "gavel", "calendar-days",
        "code", "pencil", "house"
    ]
}

struct WatchChatHeaderView: View {
    let chat: WatchChatSummary
    private var gradient: LinearGradient { WatchChatIdentityPresentation.gradient(for: chat.category ?? "general_knowledge") }
    private var icon: String { WatchChatIdentityPresentation.icon(for: chat) }
    var body: some View {
        HStack(spacing: .spacing3) {
            Icon(icon, size: 24).accessibilityIdentifier("watch-chat-header-icon")
            Text(chat.title?.isEmpty == false ? chat.title! : WatchStrings.untitledChat)
                .modifier(WatchTranscriptType(weight: .semibold))
                .lineLimit(3).fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("watch-chat-header-title")
        }
        .foregroundStyle(Color.white)
        .padding(.spacing3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(gradient, in: RoundedRectangle(cornerRadius: .radius4))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-chat-header")
    }
}

struct WatchChatShareView: View {
    let chat: WatchChatSummary
    let context: WatchChatRequestContext?
    let dependencies: WatchChatShareDependencies
    let onClose: () -> Void
    @State private var duration: ShareDuration = .noExpiration
    @State private var passwordEnabled = false
    @State private var password = ""
    @State private var generatedURL: URL?
    @State private var isGenerating = false
    @State private var failed = false
    @State private var generation: Task<Void, Never>?

    private var canCreate: Bool {
        context != nil && WatchChatShareService.canShare(chat) && !isGenerating
            && (!passwordEnabled || (!password.isEmpty && password.count <= 10))
    }

    var body: some View {
        VStack(spacing: .spacing2) {
            Button(action: onClose) {
                HStack(spacing: .spacing2) {
                    Icon("back", size: 16)
                    Text(WatchLocalization.text("common.share")).font(.omSmall.weight(.semibold))
                    Spacer(minLength: 0)
                }.frame(minHeight: 32).contentShape(Rectangle())
            }
            .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
            .accessibilityIdentifier("watch-chat-share-close")
            // The native Watch scroll host extends above its visible content.
            // Keep the fixed close target ahead of it for hit testing.
            .zIndex(1)
            ScrollView {
                VStack(alignment: .leading, spacing: .spacing3) {
                    WatchChatHeaderView(chat: chat)
                    if let generatedURL {
                        Text(generatedURL.absoluteString)
                            .modifier(WatchTranscriptType(monospaced: true))
                            .foregroundStyle(Color.grey0)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("watch-chat-share-short-url")
                        // watchOS has no public general-purpose clipboard API.
                        Button { self.generatedURL = nil; failed = false } label: {
                            Text(WatchLocalization.text("settings.share.change_settings"))
                                .font(.omSmall).frame(maxWidth: .infinity, minHeight: 38)
                        }
                        .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                        .accessibilityIdentifier("watch-chat-share-change-settings")
                    } else {
                        Text(WatchLocalization.text("settings.share.share_description"))
                            .font(.omSmall).foregroundStyle(Color.grey20)
                        Button {
                            passwordEnabled.toggle()
                            if !passwordEnabled { password = "" }
                        } label: {
                            HStack {
                                Text(WatchLocalization.text("settings.share.password_protection")).font(.omSmall)
                                Spacer(minLength: 0)
                                Icon(passwordEnabled ? "check" : "lock", size: 16)
                            }.frame(minHeight: 38).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain).foregroundStyle(Color.grey0)
                        .disabled(isGenerating)
                        .accessibilityValue(passwordEnabled ? "1" : "0")
                        .accessibilityIdentifier("watch-chat-share-password-toggle")
                        if passwordEnabled {
                            SecureField(WatchLocalization.text("settings.share.password_placeholder"), text: $password)
                                .font(.omSmall).foregroundStyle(Color.grey0).tint(Color.buttonPrimary)
                                .disabled(isGenerating)
                                .onChange(of: password) { _, value in
                                    if value.count > 10 { password = String(value.prefix(10)) }
                                }
                                .accessibilityIdentifier("watch-chat-share-password")
                        }
                        Text(WatchLocalization.text("settings.share.time_limit")).font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color.grey0)
                        ForEach(ShareDuration.allCases) { option in
                            Button { duration = option } label: {
                                HStack {
                                    Text(durationLabel(option)).font(.omSmall)
                                    Spacer(minLength: 0)
                                    if duration == option { Icon("check", size: 14) }
                                }.padding(.horizontal, .spacing2).frame(minHeight: 32)
                                    .background(duration == option ? Color.buttonPrimary : Color.grey90,
                                                in: RoundedRectangle(cornerRadius: .radius3))
                            }
                            .buttonStyle(.plain).foregroundStyle(Color.grey0).disabled(isGenerating)
                            .accessibilityAddTraits(duration == option ? .isSelected : [])
                            .accessibilityIdentifier("watch-chat-share-duration-\(option.rawValue)")
                        }
                        Button(action: createLink) {
                            Text(WatchLocalization.text(isGenerating ? "settings.share.sharing_chat_status" : "settings.share.share_chat"))
                                .font(.omSmall.weight(.semibold)).frame(maxWidth: .infinity, minHeight: 38)
                                .background(Color.buttonPrimary, in: RoundedRectangle(cornerRadius: .radius4))
                        }
                        .buttonStyle(.plain).foregroundStyle(Color.fontButton).disabled(!canCreate)
                        .accessibilityIdentifier("watch-chat-share-create")
                        if failed || context == nil || !WatchChatShareService.canShare(chat) {
                            Text(WatchLocalization.text("common.error")).font(.omSmall).foregroundStyle(Color.error)
                                .accessibilityIdentifier("watch-chat-share-error")
                        }
                    }
                }.padding(.bottom, .spacing4)
            }
            .clipped()
            .accessibilityIdentifier("watch-chat-share-scroll")
        }
        .padding(.horizontal, .spacing4).padding(.top, .spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey100)
        .accessibilityIdentifier("watch-chat-share-screen")
        .onDisappear { generation?.cancel() }
    }

    private func createLink() {
        guard canCreate, let context else { return }
        isGenerating = true; failed = false
        generation = Task { @MainActor in
            defer { isGenerating = false }
            do {
                let url = try await WatchChatShareService.create(chat: chat, context: context,
                    duration: duration, password: passwordEnabled ? password : nil, dependencies: dependencies)
                try Task.checkCancellation()
                generatedURL = url
            } catch is CancellationError { } catch { failed = true }
        }
    }

    private func durationLabel(_ option: ShareDuration) -> String {
        let key: String
        switch option {
        case .noExpiration: key = "settings.share.no_expiration"
        case .oneMinute: key = "settings.share.one_minute"
        case .tenMinutes: key = "chat_settings.ten_minutes"
        case .oneHour: key = "settings.share.one_hour"
        case .twentyFourHours: key = "settings.share.twenty_four_hours"
        case .sevenDays: key = "settings.share.seven_days"
        case .fourteenDays: key = "settings.share.fourteen_days"
        case .thirtyDays: key = "settings.share.thirty_days"
        case .ninetyDays: key = "settings.share.ninety_days"
        }
        return WatchLocalization.text(key)
    }
}

#if DEBUG
/// An explicit no-account launch fixture exercises production Watch views and
/// the real encrypted-share construction with a synthetic in-memory publisher.
@MainActor
struct WatchChatShareUITestView: View {
    private var snapshot: WatchChatSnapshot {
        var chat = WatchChatSummary(id: "watch-share-fixture", title: "Watch sharing example",
            lastMessageAt: nil, preview: "Synthetic public example", isPinned: false,
            encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil)
        chat.category = "science"; chat.icon = "microscope"
        return WatchChatSnapshot(chats: [chat], messagesByChatId: [chat.id: [
            WatchChatMessage(id: "watch-share-message", chatId: chat.id, role: .assistant,
                content: "A synthetic sharing example.", encryptedContent: nil, embedRefs: nil,
                createdAt: "2026-10-03T00:00:00Z", isPending: false)
        ]], savedAt: .distantPast)
    }
    var body: some View {
        WatchChatShellView(uiTestSnapshot: snapshot, selectedChatId: "watch-share-fixture")
    }
}
#endif

#if DEBUG
@MainActor
struct WatchChatListMetadataUITestView: View {
    private var snapshot: WatchChatSnapshot {
        func chat(_ id: String, title: String) -> WatchChatSummary {
            WatchChatSummary(id: id, title: title, lastMessageAt: nil, preview: nil, isPinned: false,
                encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil)
        }
        var explicit = chat("watch-list-explicit", title: "Synthetic category icon")
        explicit.category = "science"; explicit.icon = "code"
        var fallback = chat("watch-list-fallback", title: "Synthetic category fallback")
        fallback.category = "science"; fallback.icon = "unavailable-custom-icon"
        let legacy = chat("watch-list-legacy", title: "Legacy cached chat")
        return WatchChatSnapshot(chats: [explicit, fallback, legacy], messagesByChatId: [:], savedAt: .distantPast)
    }
    var body: some View { WatchChatShellView(uiTestSnapshot: snapshot, selectedChatId: nil) }
}
#endif
