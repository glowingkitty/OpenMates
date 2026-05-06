// Full settings screen — mirrors the web app's settings panel from settingsRoutes.ts.
// Product UI must use OpenMates primitives instead of default platform List/Form chrome.
// ALL navigation targets are native SwiftUI views — no web redirects.
// ALL strings go through AppStrings (i18n) — no hardcoded English.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/CurrentSettingsPage.svelte
//          frontend/packages/ui/src/components/settings/SettingsMainHeader.svelte
//          frontend/packages/ui/src/components/settings/settingsRoutes.ts
//          frontend/packages/ui/src/components/settings/SettingsFooter.svelte
// CSS:     frontend/packages/ui/src/components/SettingsItem.svelte (icon styles)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var themeManager: ThemeManager
    @Environment(\.dismiss) var dismiss
    @Environment(\.openURL) private var openURL
    var onClose: (() -> Void)?
    @State private var showIncognitoInfo = false
    @State private var destination: SettingsDestination?
    @State private var navigationDirection: SettingsNavigationDirection = .forward
    @State private var homeScrollTop: CGFloat = 0
    @State private var destinationScrollTop: CGFloat = 0

    init(onClose: (() -> Void)? = nil) {
        self.onClose = onClose
    }

    private var isAuthenticated: Bool { authManager.currentUser != nil }
    private var isAdmin: Bool { authManager.currentUser?.isAdmin == true }

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                settingsBannerShell

                ZStack {
                    if let destination {
                        settingsDestinationContent(destination)
                            .transition(.move(edge: navigationDirection == .forward ? .trailing : .leading))
                    } else {
                        settingsHomeContent
                            .transition(.move(edge: navigationDirection == .forward ? .leading : .trailing))
                    }
                }
                .clipped()
                .animation(.easeOut(duration: 0.2), value: destination)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(Color.grey20)

            if showIncognitoInfo {
                incognitoOverlay
            }
        }
    }

    // MARK: - Main settings menu
    // Web: .settings-menu has grey-20 bg, 17px radius, shadow.
    // Items sit directly on the background — NO container/section wrapper.
    // Root settings collapses .settings-header.app-top-level and starts with settings-banner-shell.

    private var settingsHomeContent: some View {
        // Scrollable content — web: .settings-content-wrapper, overflow-y auto
        // Background: grey-20 (same as outer panel), NO additional styling
        GeometryReader { scrollFrame in
            ScrollView {
                VStack(spacing: 0) {
                    GeometryReader { contentFrame in
                        Color.clear.preference(
                            key: SettingsHomeScrollOffsetPreferenceKey.self,
                            value: max(
                                0,
                                scrollFrame.frame(in: .global).minY - contentFrame.frame(in: .global).minY
                            )
                        )
                    }
                    .frame(height: 0)

                    // Menu items — web: flat list, NO container/section wrapper
                    // Each item sits directly on grey-20 background
                    // Items use padding 5px 10px, min-height 40px, radius-3

                    if !isAuthenticated {
                        row(.pricing, AppStrings.settingsPricing, icon: "pricing")
                    }

                    // Incognito toggle — web: SettingsItem type="quickaction" (flat icon, no bg)
                    if isAuthenticated {
                        OMSettingsRow(
                            title: AppStrings.settingsIncognito,
                            icon: "eye-off",
                            showsChevron: false
                        ) {
                            showIncognitoInfo = true
                        }
                    }

                    row(.ai, AppStrings.settingsAI, icon: "ai")
                    row(.apps, AppStrings.settingsApps, icon: "app_store")

                    if isAuthenticated {
                        row(.memories, AppStrings.settingsMemories, icon: "settings_memories")
                        row(.privacy, AppStrings.settingsPrivacy, icon: "privacy")
                    }

                    row(.mates, AppStrings.settingsMates, icon: "mates")

                    if isAuthenticated {
                        row(.billing, AppStrings.settingsBilling, icon: "billing")
                        row(.notifications, AppStrings.settingsNotifications, icon: "notifications")
                        row(.shared, AppStrings.settingsShared, icon: "shared")
                    }

                    row(.interface, AppStrings.settingsInterface, icon: "interface")
                    row(.serverConnection, "Server", icon: "server")

                    if isAuthenticated {
                        row(.account, AppStrings.settingsAccount, icon: "account")
                        row(.developers, AppStrings.settingsDevelopers, icon: "developers")
                    }

                    row(.newsletter, AppStrings.settingsNewsletter, icon: "newsletter")
                    row(.support, AppStrings.settingsSupport, icon: "support")
                    row(.reportIssue, AppStrings.settingsReportIssue, icon: "report_issue")

                    if isAdmin {
                        row(.server, AppStrings.serverAdmin, icon: "server")
                        row(.logs, AppStrings.logs, icon: "log")
                    }

                    if isAuthenticated {
                        OMSettingsRow(
                            title: AppStrings.logOut,
                            icon: "logout",
                            isDestructive: true,
                            showsChevron: false
                        ) {
                            Task { await authManager.logout() }
                        }
                    }

                    // Footer — web: SettingsFooter.svelte, margin-top 100px
                    settingsFooter
                }
            }
        }
        .onPreferenceChange(SettingsHomeScrollOffsetPreferenceKey.self) { offset in
            homeScrollTop = offset
        }
        .scrollContentBackground(.hidden)
        .background(Color.grey20) // web: .settings-menu background-color: var(--color-grey-20)
    }

    // MARK: - Settings Banner Shell
    // Web: .settings-banner-shell wrapping SettingsMainHeader.svelte.

    private var settingsBannerShell: some View {
        Group {
            if let destination {
                SettingsStandardBanner(destination: destination, scrollTop: destinationScrollTop) {
                    navigationDirection = .back
                    withAnimation(.easeOut(duration: 0.2)) {
                        self.destination = nil
                    }
                }
            } else {
                SettingsMainBanner(
                    username: authManager.currentUser?.username ?? AppStrings.guest,
                    profileImageUrl: authManager.currentUser?.profileImageUrl,
                    isAuthenticated: isAuthenticated,
                    credits: authManager.currentUser?.credits,
                    scrollTop: homeScrollTop
                )
            }
        }
    }

    // MARK: - Footer
    // Web: SettingsFooter.svelte — margin-top 100px, sections with h3 headings + links
    // Sections: For everyone (social), For developers, Contact, Legal, Version

    private var settingsFooter: some View {
        OMSettingsFooter()
    }

    private func footerSection<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            // web: h3 — color grey-60, font-size-small (12px), weight 600, margin 6px 0
            Text(title)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontSecondary)
                .padding(.vertical, .spacing3)
            content()
        }
    }

    private func footerLink(_ title: String, url: String) -> some View {
        Button {
            if let u = URL(string: url) { openURL(u) }
        } label: {
            // web: .submenu-link — color grey-50, font-size-small (12px), padding 6px 0
            Text(title)
                .font(.omSmall)
                .foregroundStyle(Color.grey50)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, .spacing3)
        }
        .buttonStyle(.plain)
    }

    private func footerNavLink(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.omSmall)
                .foregroundStyle(Color.grey50)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, .spacing3)
        }
        .buttonStyle(.plain)
    }

    // MARK: - Row Helper

    private func row(
        _ destination: SettingsDestination,
        _ title: String,
        icon: String,
        gradient: LinearGradient? = nil,
        isDestructive: Bool = false
    ) -> some View {
        OMSettingsRow(title: title, icon: icon, iconGradient: gradient, isDestructive: isDestructive) {
            navigateTo(destination)
        }
    }

    private func navigateTo(_ destination: SettingsDestination) {
        navigationDirection = .forward
        destinationScrollTop = 0
        withAnimation(.easeOut(duration: 0.2)) {
            self.destination = destination
        }
    }

    // MARK: - Incognito Overlay

    private var incognitoOverlay: some View {
        ZStack {
            Color.black.opacity(0.35)
                .ignoresSafeArea()
                .onTapGesture {
                    showIncognitoInfo = false
                }

            VStack(spacing: 0) {
                HStack {
                    Text(AppStrings.settingsIncognito)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                OMIconButton(icon: "close", label: AppStrings.cancel, size: 32) {
                    showIncognitoInfo = false
                }
                }
                .padding(.spacing6)

                SettingsIncognitoInfoView(
                    onActivate: {
                        showIncognitoInfo = false
                        NotificationCenter.default.post(name: .incognitoActivated, object: nil)
                    },
                    onCancel: { showIncognitoInfo = false }
                )
            }
            .frame(maxWidth: 620, maxHeight: 720)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .padding(.spacing8)
        }
    }

    private func closeSettings() {
        if let onClose {
            onClose()
        } else {
            dismiss()
        }
    }

    @ViewBuilder
    private func settingsDestinationContent(_ destination: SettingsDestination) -> some View {
        destinationContent(for: destination)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .environment(\.omSettingsScrollOffsetHandler, OMSettingsScrollOffsetHandler { offset in
                destinationScrollTop = offset
            })
    }

    @ViewBuilder
    private func destinationContent(for destination: SettingsDestination) -> some View {
        switch destination {
        case .pricing:
            SettingsPricingView(
                onOpenApps: { navigateTo(.apps) },
                onOpenAI: { navigateTo(.ai) }
            )
        default:
            destination.view
        }
    }

    private struct SettingsStandardBanner: View {
        let destination: SettingsDestination
        let scrollTop: CGFloat
        let onBack: () -> Void

        private var progress: CGFloat {
            let raw = min(1, max(0, scrollTop / 80))
            return raw < 0.5 ? 4 * raw * raw * raw : 1 - pow(-2 * raw + 2, 3) / 2
        }

        private var isCollapsed: Bool { progress > 0.5 }
        private var height: CGFloat { 190 - (190 - 88) * progress }
        private var iconSize: CGFloat { 50 - 14 * progress }
        private var titleSize: CGFloat { 20 - 3 * progress }
        private var detailsOpacity: CGFloat { max(0, 1 - progress * 2) }
        private var identityHeight: CGFloat { isCollapsed ? 44 : 76 }

        var body: some View {
            VStack(spacing: 0) {
                LinearGradient.primary
                    .overlay(alignment: .top) {
                        VStack(spacing: 0) {
                            Button(action: onBack) {
                                HStack(spacing: .spacing3) {
                                    Icon("back", size: 22)
                                        .foregroundStyle(Color.white.opacity(0.85))
                                    Text(AppStrings.settings)
                                        .font(.omSmall.weight(.semibold))
                                        .foregroundStyle(Color.white.opacity(0.72))
                                        .lineLimit(1)
                                }
                                .padding(.horizontal, .spacing5)
                                .frame(maxWidth: .infinity, minHeight: 44, maxHeight: 44, alignment: .leading)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)

                            identityBlock
                                .frame(height: identityHeight)

                            detailsBlock
                        }
                    }
            }
            .frame(height: height)
            .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: 14, bottomTrailingRadius: 14))
            .shadow(color: .black.opacity(0.2), radius: 16, x: 0, y: 4)
            .animation(.easeInOut(duration: 0.15), value: scrollTop)
        }

        @ViewBuilder
        private var identityBlock: some View {
            if isCollapsed {
                HStack(spacing: .spacing5) {
                    bannerIcon
                    bannerTitle(alignment: .leading, lineLimit: 1)
                }
                .padding(.horizontal, .spacing8)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            } else {
                VStack(spacing: .spacing5) {
                    bannerIcon
                    bannerTitle(alignment: .center, lineLimit: 2)
                }
                .padding(.horizontal, .spacing8)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            }
        }

        @ViewBuilder
        private var detailsBlock: some View {
            if !destination.description.isEmpty {
                Text(destination.description)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontButton)
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
                    .opacity(detailsOpacity)
                    .padding(.horizontal, .spacing8)
                    .padding(.top, .spacing5)
            }
        }

        private var bannerIcon: some View {
            Icon(destination.icon, size: iconSize)
                .foregroundStyle(Color.white.opacity(0.95))
        }

        private func bannerTitle(alignment: TextAlignment, lineLimit: Int) -> some View {
            Text(destination.title)
                .font(Font.custom("Lexend Deca", size: titleSize).weight(.bold))
                .foregroundStyle(Color.fontButton)
                .multilineTextAlignment(alignment)
                .lineLimit(lineLimit)
        }
    }

    // MARK: - Destination Enum (matches web settingsRoutes.ts top-level keys)

    @MainActor
    private enum SettingsDestination: Hashable {
        // Top-level menu items (matching web settingsRoutes.ts order)
        case pricing, ai, memories, apps, privacy, mates
        case billing, notifications, shared, interface
        case account, developers, newsletter, support, reportIssue
        case serverConnection
        case server, logs
        // Footer legal items
        case privacyPolicy, terms, imprint

        var title: String {
            switch self {
            case .pricing: return AppStrings.settingsPricing
            case .ai: return AppStrings.settingsAI
            case .memories: return AppStrings.settingsMemories
            case .apps: return AppStrings.settingsApps
            case .privacy: return AppStrings.settingsPrivacy
            case .mates: return AppStrings.settingsMates
            case .billing: return AppStrings.settingsBilling
            case .notifications: return AppStrings.settingsNotifications
            case .shared: return AppStrings.settingsShared
            case .interface: return AppStrings.settingsInterface
            case .account: return AppStrings.settingsAccount
            case .developers: return AppStrings.settingsDevelopers
            case .newsletter: return AppStrings.settingsNewsletter
            case .support: return AppStrings.settingsSupport
            case .reportIssue: return AppStrings.settingsReportIssue
            case .serverConnection: return "Server"
            case .server: return AppStrings.serverAdmin
            case .logs: return AppStrings.logs
            case .privacyPolicy: return AppStrings.privacyPolicy
            case .terms: return AppStrings.termsOfService
            case .imprint: return AppStrings.imprint
            }
        }

        var icon: String {
            switch self {
            case .pricing: return "pricing"
            case .ai: return "ai"
            case .memories: return "settings_memories"
            case .apps: return "app_store"
            case .privacy: return "privacy"
            case .mates: return "mates"
            case .billing: return "billing"
            case .notifications: return "notifications"
            case .shared: return "shared"
            case .interface: return "interface"
            case .account: return "account"
            case .developers: return "developers"
            case .newsletter: return "newsletter"
            case .support: return "support"
            case .reportIssue: return "report_issue"
            case .serverConnection: return "server"
            case .server: return "server"
            case .logs: return "log"
            case .privacyPolicy, .terms, .imprint: return "document"
            }
        }

        var description: String {
            switch self {
            case .pricing: return LocalizationManager.shared.text("settings.pricing.description")
            case .ai: return LocalizationManager.shared.text("settings.ai.description")
            case .memories: return LocalizationManager.shared.text("settings.settings_memories.description")
            case .apps: return LocalizationManager.shared.text("settings.app_store.description")
            case .privacy: return LocalizationManager.shared.text("settings.privacy.description")
            case .mates: return LocalizationManager.shared.text("settings.mates.description")
            case .billing: return LocalizationManager.shared.text("settings.billing.description")
            case .notifications: return LocalizationManager.shared.text("settings.notifications.description")
            case .shared: return LocalizationManager.shared.text("settings.shared.description")
            case .interface: return LocalizationManager.shared.text("settings.interface.description")
            case .account: return LocalizationManager.shared.text("settings.account.description")
            case .developers: return LocalizationManager.shared.text("settings.developers_description")
            case .newsletter: return LocalizationManager.shared.text("settings.newsletter.description")
            case .support: return LocalizationManager.shared.text("settings.support.description")
            case .serverConnection: return "Choose the OpenMates server domain"
            case .server: return LocalizationManager.shared.text("settings.server.description")
            default: return ""
            }
        }

        @ViewBuilder
        var view: some View {
            switch self {
            case .pricing: SettingsPricingView()
            case .ai: SettingsAIFullView()
            case .memories: SettingsMemoriesFullView()
            case .apps: SettingsAppsFullView()
            case .privacy: SettingsPrivacySubPage()
            case .mates: SettingsMatesView()
            case .billing: SettingsBillingView()
            case .notifications: SettingsNotificationsView()
            case .shared: SettingsSharedView()
            case .interface: SettingsInterfaceSubPage()
            case .account: SettingsAccountSubPage()
            case .developers: SettingsDeveloperView()
            case .newsletter: NewsletterSettingsView()
            case .support: SettingsSupportView()
            case .reportIssue: ReportIssueView()
            case .serverConnection: SettingsServerConnectionView()
            case .server: SettingsServerView()
            case .logs: SettingsLogsView()
            case .privacyPolicy: LegalChatView(documentType: .privacy)
            case .terms: LegalChatView(documentType: .terms)
            case .imprint: LegalChatView(documentType: .imprint)
            }
        }
    }
}

private enum SettingsNavigationDirection {
    case forward, back
}

private struct SettingsHomeScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat { 0 }

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct SettingsMainBanner: View {
    let username: String
    let profileImageUrl: String?
    let isAuthenticated: Bool
    let credits: Double?
    let scrollTop: CGFloat

    private var progress: CGFloat {
        let raw = min(1, max(0, scrollTop / 60))
        return raw < 0.5 ? 4 * raw * raw * raw : 1 - pow(-2 * raw + 2, 3) / 2
    }

    private var isCollapsed: Bool { progress > 0.5 }
    private var height: CGFloat { 190 - (190 - 72) * progress }
    private var avatarSize: CGFloat { 56 - 24 * progress }
    private var nameSize: CGFloat { 20 - 3 * progress }

    var body: some View {
        ZStack {
            LinearGradient.appOpenmates

            Circle()
                .fill(Color.white.opacity(0.18))
                .frame(width: 220, height: 220)
                .blur(radius: 24)
                .offset(x: -70, y: -70)

            Circle()
                .fill(Color.white.opacity(0.14))
                .frame(width: 190, height: 190)
                .blur(radius: 24)
                .offset(x: 90, y: 78)

            Group {
                if isCollapsed {
                    HStack(spacing: .spacing6) {
                        avatar

                        VStack(alignment: .leading, spacing: .spacing2) {
                            usernameText
                            creditsView
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    VStack(spacing: .spacing4) {
                        avatar
                        usernameText
                        creditsView
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                }
            }
            .padding(.horizontal, .spacing8)
        }
        .frame(height: height)
        .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: 14, bottomTrailingRadius: 14))
        .shadow(color: .black.opacity(0.2), radius: 16, x: 0, y: 4)
    }

    private var usernameText: some View {
        Text(username)
            .font(Font.custom("Lexend Deca", size: nameSize).weight(.bold))
            .foregroundStyle(.white)
            .lineLimit(1)
    }

    @ViewBuilder
    private var creditsView: some View {
        if isAuthenticated, let credits {
            HStack(spacing: .spacing3) {
                Icon("coins", size: 19)
                    .foregroundStyle(.white)
                Text(AppStrings.creditsAmount(Self.formatCredits(credits)))
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(.white)
                    .lineLimit(1)
            }
        }
    }

    @ViewBuilder
    private var avatar: some View {
        if isAuthenticated, let profileImageUrl, let url = URL(string: profileImageUrl) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFill()
                default:
                    defaultAvatar
                }
            }
            .frame(width: avatarSize, height: avatarSize)
            .clipShape(Circle())
            .shadow(color: .black.opacity(0.18), radius: 8, x: 0, y: 3)
        } else {
            defaultAvatar
        }
    }

    private var defaultAvatar: some View {
        Circle()
            .fill(Color.white.opacity(isAuthenticated ? 0.22 : 0.28))
            .frame(width: avatarSize, height: avatarSize)
            .overlay {
                Icon("user", size: avatarSize * 0.61)
                    .foregroundStyle(.white)
            }
            .shadow(color: .black.opacity(0.18), radius: 8, x: 0, y: 3)
    }

    private static func formatCredits(_ credits: Double) -> String {
        let digits = String(Int(credits.rounded()))
        var result = ""
        for (index, character) in digits.reversed().enumerated() {
            if index > 0, index % 3 == 0 {
                result.append(".")
            }
            result.append(character)
        }
        return String(result.reversed())
    }
}

// MARK: - Privacy Sub-Page
// Web source: SettingsPrivacy.svelte — shows hide personal data, auto deletion, debug logging

struct SettingsPrivacySubPage: View {
    @State private var destination: PrivacyDestination?

    var body: some View {
        if let dest = destination {
            VStack(spacing: 0) {
                HStack(spacing: .spacing4) {
                    OMIconButton(icon: "back", label: AppStrings.back, size: 36) {
                        destination = nil
                    }
                    Text(dest.title)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing6)
                .background(Color.grey0)

                dest.view
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(Color.grey0)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing8) {
                    OMSettingsSection {
                        OMSettingsRow(
                            title: AppStrings.hidePersonalData,
                            icon: "anonym",
                            iconGradient: .appSecrets
                        ) { destination = .hidePersonalData }

                        OMSettingsRow(
                            title: AppStrings.autoDeleteChats,
                            icon: "delete",
                            iconGradient: .appNews
                        ) { destination = .autoDelete }

                        OMSettingsRow(
                            title: AppStrings.shareDebugLogs,
                            icon: "bug",
                            iconGradient: .appCode
                        ) { destination = .debugLogs }
                    }
                }
                .padding(.horizontal, .spacing8)
                .padding(.bottom, .spacing16)
            }
            .scrollContentBackground(.hidden)
            .background(Color.grey0)
        }
    }

    @MainActor
    enum PrivacyDestination: Hashable {
        case hidePersonalData, autoDelete, debugLogs

        var title: String {
            switch self {
            case .hidePersonalData: return AppStrings.hidePersonalData
            case .autoDelete: return AppStrings.autoDeleteChats
            case .debugLogs: return AppStrings.shareDebugLogs
            }
        }

        @ViewBuilder
        var view: some View {
            switch self {
            case .hidePersonalData: SettingsHidePersonalDataView()
            case .autoDelete: SettingsAutoDeleteView()
            case .debugLogs: SettingsShareDebugLogsView()
            }
        }
    }
}

// MARK: - Interface Sub-Page
// Web source: SettingsInterface.svelte — shows theme toggle and language

struct SettingsInterfaceSubPage: View {
    @EnvironmentObject var themeManager: ThemeManager
    @State private var destination: InterfaceDestination?

    var body: some View {
        if let dest = destination {
            VStack(spacing: 0) {
                HStack(spacing: .spacing4) {
                    OMIconButton(icon: "back", label: AppStrings.back, size: 36) {
                        destination = nil
                    }
                    Text(dest.title)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing6)
                .background(Color.grey0)

                dest.view
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(Color.grey0)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing8) {
                    // Theme selector (inline, like the web's SettingsInterface.svelte)
                    OMSettingsSection(AppStrings.theme) {
                        VStack(alignment: .leading, spacing: .spacing4) {
                            OMSegmentedControl(
                                items: [
                                    .init(id: ThemeManager.ThemeMode.auto, title: AppStrings.systemTheme),
                                    .init(id: ThemeManager.ThemeMode.light, title: AppStrings.lightTheme),
                                    .init(id: ThemeManager.ThemeMode.dark, title: AppStrings.darkTheme)
                                ],
                                selection: Binding(
                                    get: { themeManager.themeMode },
                                    set: { themeManager.setTheme($0) }
                                )
                            )
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                    }

                    // Language row
                    OMSettingsSection {
                        OMSettingsRow(
                            title: AppStrings.language,
                            icon: "language",
                            iconGradient: .appLanguage
                        ) { destination = .language }
                    }
                }
                .padding(.horizontal, .spacing8)
                .padding(.bottom, .spacing16)
            }
            .scrollContentBackground(.hidden)
            .background(Color.grey0)
        }
    }

    @MainActor
    enum InterfaceDestination: Hashable {
        case language

        var title: String {
            switch self {
            case .language: return AppStrings.language
            }
        }

        @ViewBuilder
        var view: some View {
            switch self {
            case .language: SettingsLanguageView()
            }
        }
    }
}

// MARK: - Account Sub-Page
// Web source: SettingsAccount.svelte — shows username, email, profile pic, usage, storage, etc.

struct SettingsAccountSubPage: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var destination: AccountDestination?

    var body: some View {
        if let dest = destination {
            VStack(spacing: 0) {
                HStack(spacing: .spacing4) {
                    OMIconButton(icon: "back", label: AppStrings.back, size: 36) {
                        destination = nil
                    }
                    Text(dest.title)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing6)
                .background(Color.grey0)

                dest.view
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(Color.grey0)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing8) {
                    OMSettingsSection {
                        OMSettingsRow(title: AppStrings.username, icon: "user", iconGradient: .primary) {
                            destination = .username
                        }
                        OMSettingsRow(title: AppStrings.email, icon: "mail", iconGradient: .appMail) {
                            destination = .email
                        }
                        OMSettingsRow(title: AppStrings.profilePicture, icon: "image", iconGradient: .appPhotos) {
                            destination = .profilePicture
                        }
                        OMSettingsRow(title: AppStrings.usage, icon: "usage", iconGradient: .appFinance) {
                            destination = .usage
                        }
                        OMSettingsRow(title: AppStrings.storage, icon: "cloud", iconGradient: .appFiles) {
                            destination = .storage
                        }
                        OMSettingsRow(title: AppStrings.chats, icon: "chat", iconGradient: .appMessages) {
                            destination = .chats
                        }
                        OMSettingsRow(title: AppStrings.importChats, icon: "download", iconGradient: .appDocs) {
                            destination = .importChats
                        }
                        OMSettingsRow(title: AppStrings.exportData, icon: "upload", iconGradient: .appDocs) {
                            destination = .exportData
                        }
                    }

                    OMSettingsSection(AppStrings.settingsSecurity) {
                        OMSettingsRow(title: AppStrings.passkeys, icon: "passkey", iconGradient: .appSecrets) {
                            destination = .passkeys
                        }
                        OMSettingsRow(title: AppStrings.password, icon: "lock", iconGradient: .appSecrets) {
                            destination = .password
                        }
                        OMSettingsRow(title: AppStrings.twoFactorAuth, icon: "tfas", iconGradient: .appSecrets) {
                            destination = .twoFactor
                        }
                        OMSettingsRow(title: AppStrings.recoveryKey, icon: "secret", iconGradient: .appSecrets) {
                            destination = .recoveryKey
                        }
                        OMSettingsRow(title: AppStrings.activeSessions, icon: "desktop", iconGradient: .appCode) {
                            destination = .sessions
                        }
                        OMSettingsRow(title: AppStrings.pairNewDevice, icon: "dummyqr", iconGradient: .primary) {
                            destination = .pairDevice
                        }
                    }

                    OMSettingsSection {
                        OMSettingsRow(
                            title: AppStrings.deleteAccount,
                            icon: "delete",
                            isDestructive: true
                        ) { destination = .deleteAccount }
                    }
                }
                .padding(.horizontal, .spacing8)
                .padding(.bottom, .spacing16)
            }
            .scrollContentBackground(.hidden)
            .background(Color.grey0)
        }
    }

    @MainActor
    enum AccountDestination: Hashable {
        case username, email, profilePicture, usage, storage, chats
        case importChats, exportData, deleteAccount
        case passkeys, password, twoFactor, recoveryKey, sessions, pairDevice

        var title: String {
            switch self {
            case .username: return AppStrings.username
            case .email: return AppStrings.email
            case .profilePicture: return AppStrings.profilePicture
            case .usage: return AppStrings.usage
            case .storage: return AppStrings.storage
            case .chats: return AppStrings.chats
            case .importChats: return AppStrings.importChats
            case .exportData: return AppStrings.exportData
            case .deleteAccount: return AppStrings.deleteAccount
            case .passkeys: return AppStrings.passkeys
            case .password: return AppStrings.password
            case .twoFactor: return AppStrings.twoFactorAuth
            case .recoveryKey: return AppStrings.recoveryKey
            case .sessions: return AppStrings.activeSessions
            case .pairDevice: return AppStrings.pairNewDevice
            }
        }

        @ViewBuilder
        var view: some View {
            switch self {
            case .username: SettingsAccountDetailView()
            case .email: SettingsEmailView()
            case .profilePicture: SettingsProfilePictureView()
            case .usage: SettingsUsageView()
            case .storage: SettingsStorageFullView()
            case .chats: SettingsAccountChatsView()
            case .importChats: ChatImportView()
            case .exportData: SettingsExportAccountView()
            case .deleteAccount: SettingsDeleteAccountView()
            case .passkeys: SettingsPasskeysView()
            case .password: SettingsPasswordView()
            case .twoFactor: Settings2FAView()
            case .recoveryKey: SettingsRecoveryKeyView()
            case .sessions: SettingsSessionsView()
            case .pairDevice: SettingsPairInitiateView()
            }
        }
    }
}

// MARK: - Delete Account

struct SettingsDeleteAccountView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var password = ""
    @State private var confirmText = ""
    @State private var isDeleting = false
    @State private var error: String?

    private var canDelete: Bool {
        !password.isEmpty && confirmText.lowercased() == "delete my account"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                Text(AppStrings.deleteAccountWarning)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.spacing6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.error.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: .radius7))

                OMSettingsSection(AppStrings.confirm) {
                    VStack(alignment: .leading, spacing: .spacing5) {
                        SecureField(AppStrings.enterPassword, text: $password)
                            .textContentType(.password)
                            .textFieldStyle(OMTextFieldStyle())
                            .accessibleInput(AppStrings.enterPassword, hint: LocalizationManager.shared.text("auth.enter_account_password"))

                        TextField(AppStrings.deleteAccountConfirmText, text: $confirmText)
                            .textFieldStyle(OMTextFieldStyle())
                            .autocorrectionDisabled()
                            #if os(iOS)
                            .textInputAutocapitalization(.never)
                            #endif
                            .accessibleInput(AppStrings.deleteAccountConfirmText, hint: LocalizationManager.shared.text("settings.type_delete_confirm_hint"))
                    }
                    .padding(.spacing6)
                }

                Button(role: .destructive) {
                    deleteAccount()
                } label: {
                    HStack {
                        Spacer()
                        if isDeleting {
                            Text(AppStrings.loading)
                                .font(.omP)
                                .fontWeight(.medium)
                        } else {
                            Text(AppStrings.permanentlyDeleteAccount)
                                .font(.omP)
                                .fontWeight(.medium)
                        }
                        Spacer()
                    }
                    .foregroundStyle(Color.fontButton)
                    .padding(.vertical, .spacing5)
                    .background(canDelete && !isDeleting ? Color.error : Color.buttonSecondary)
                    .clipShape(RoundedRectangle(cornerRadius: .radius7))
                }
                .buttonStyle(.plain)
                .disabled(!canDelete || isDeleting)
                .accessibleButton(AppStrings.permanentlyDeleteAccount, hint: LocalizationManager.shared.text("settings.delete_account_hint"))

                if let error {
                    Text(error)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                        .padding(.spacing6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.error.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: .radius7))
                }
            }
            .padding(.spacing8)
        }
        .background(Color.grey0)
    }

    private func deleteAccount() {
        isDeleting = true
        error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/account/delete",
                    body: ["password": password]
                )
                await authManager.logout()
            } catch {
                self.error = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isDeleting = false
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let incognitoActivated = Notification.Name("openmates.incognitoActivated")
}
