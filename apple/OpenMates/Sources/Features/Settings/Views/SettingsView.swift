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
    @State private var showIncognitoInfo = false
    @State private var destination: SettingsDestination?

    private var isAuthenticated: Bool { authManager.currentUser != nil }
    private var isAdmin: Bool { authManager.currentUser?.isAdmin == true }

    var body: some View {
        ZStack {
            if let destination {
                settingsDestinationView(destination)
            } else {
                settingsHome
            }

            if showIncognitoInfo {
                incognitoOverlay
            }
        }
    }

    // MARK: - Main settings menu
    // Web: .settings-menu has grey-20 bg, 17px radius, shadow.
    // Items sit directly on the background — NO container/section wrapper.
    // Header is a thin strip with breadcrumb, NOT a big bold title.

    private var settingsHome: some View {
        VStack(spacing: 0) {
            // Header strip — web: .settings-header, sticky, min-height 30px,
            // border-bottom 1px solid grey-30, box-shadow 0 2px 4px rgba(0,0,0,0.05)
            HStack {
                Text(AppStrings.settings)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                Spacer()
                OMIconButton(icon: "close", label: AppStrings.done) {
                    dismiss()
                }
            }
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing3)
            .background(Color.grey20)
            .overlay(alignment: .bottom) {
                // 1px bottom border (web: border-bottom: 1px solid var(--color-grey-30))
                Color.grey30.frame(height: 1)
            }
            .shadow(color: .black.opacity(0.05), radius: 2, x: 0, y: 2)

            // Scrollable content — web: .settings-content-wrapper, overflow-y auto
            // Background: grey-20 (same as outer panel), NO additional styling
            ScrollView {
                VStack(spacing: 0) {
                    // Profile section — web: .profile-container-docked + .user-info-container
                    if isAuthenticated {
                        profileSection
                    }

                    // Menu items — web: flat list, NO container/section wrapper
                    // Each item sits directly on grey-20 background
                    // Items use padding 5px 10px, min-height 40px, radius-3

                    if !isAuthenticated {
                        row(.pricing, AppStrings.settingsPricing, icon: "coins", gradient: .appFinance)
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

                    row(.ai, AppStrings.settingsAI, icon: "ai", gradient: .appAi)
                    row(.apps, AppStrings.settingsApps, icon: "app", gradient: .primary)

                    if isAuthenticated {
                        row(.memories, AppStrings.settingsMemories, icon: "insight", gradient: .appMessages)
                        row(.privacy, AppStrings.settingsPrivacy, icon: "lock", gradient: .appSecrets)
                    }

                    row(.mates, AppStrings.settingsMates, icon: "mate", gradient: .appMessages)

                    if isAuthenticated {
                        row(.billing, AppStrings.settingsBilling, icon: "coins", gradient: .appFinance)
                        row(.notifications, AppStrings.settingsNotifications, icon: "chat", gradient: .appMessages)
                        row(.shared, AppStrings.settingsShared, icon: "share", gradient: .appSocialmedia)
                    }

                    row(.interface, AppStrings.settingsInterface, icon: "darkmode", gradient: .appDesign)

                    if isAuthenticated {
                        row(.account, AppStrings.settingsAccount, icon: "user", gradient: .primary)
                        row(.developers, AppStrings.settingsDevelopers, icon: "coding", gradient: .appCode)
                    }

                    row(.newsletter, AppStrings.settingsNewsletter, icon: "mail", gradient: .appPublishing)
                    row(.support, AppStrings.settingsSupport, icon: "heart", gradient: .appHealth)
                    row(.reportIssue, AppStrings.settingsReportIssue, icon: "bug", gradient: .appNews)

                    if isAdmin {
                        row(.server, AppStrings.serverAdmin, icon: "server", gradient: .appHosting)
                        row(.logs, AppStrings.logs, icon: "log", gradient: .appCode)
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
                .padding(.horizontal, .spacing5) // web: .menu-item padding is 5px 10px
            }
            .scrollContentBackground(.hidden)
        }
        .background(Color.grey20) // web: .settings-menu background-color: var(--color-grey-20)
    }

    // MARK: - Profile Section
    // Web: .profile-container-docked (50x50 circle) + .user-info-container
    // No container wrapper — sits directly on grey-20 background

    private var profileSection: some View {
        Group {
            if let user = authManager.currentUser {
                HStack(spacing: 0) {
                    // Web: .profile-container-docked, 50x50 circle
                    Circle()
                        .fill(LinearGradient.primary)
                        .frame(width: 50, height: 50)
                        .overlay {
                            Text(String(user.username.prefix(1)).uppercased())
                                .font(.omH4)
                                .fontWeight(.bold)
                                .foregroundStyle(.white)
                        }
                        .padding(.trailing, .spacing6)

                    // Web: .user-info-container, margin-inline-start 85px (but we use HStack)
                    VStack(alignment: .leading, spacing: .spacing2) {
                        // Web: .username, font-size-xl (20px), weight 500
                        Text(user.username)
                            .font(.omH3) // web: font-size-xl = 20px = omH3
                            .foregroundStyle(Color.fontPrimary)
                        if let credits = user.credits {
                            // Web: .credits-container with coins icon + amount
                            HStack(spacing: .spacing4) {
                                Icon("coins", size: 19)
                                    .foregroundStyle(LinearGradient.primary)
                                Text(AppStrings.creditsAmount(String(format: "%.2f", credits)))
                                    .font(.omP)
                                    .foregroundStyle(Color.fontPrimary)
                            }
                        }
                    }

                    Spacer()
                }
                .padding(.vertical, .spacing5)
            }
        }
    }

    // MARK: - Footer
    // Web: SettingsFooter.svelte — margin-top 100px, sections with h3 headings + links
    // Sections: For everyone (social), For developers, Contact, Legal, Version

    private var settingsFooter: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            // "For everyone" — social links
            footerSection(LocalizationManager.shared.text("footer.sections.for_everyone")) {
                footerLink(LocalizationManager.shared.text("settings.instagram"), url: "https://instagram.com/openmates")
                footerLink(LocalizationManager.shared.text("common.discord"), url: "https://discord.gg/openmates")
            }

            // "For developers"
            footerSection(LocalizationManager.shared.text("footer.sections.for_developers")) {
                footerLink(LocalizationManager.shared.text("common.github"), url: "https://github.com/OpenMates/OpenMates")
            }

            // Legal
            footerSection(LocalizationManager.shared.text("common.legal")) {
                footerNavLink(AppStrings.imprint) { destination = .imprint }
                footerNavLink(AppStrings.privacyPolicy) { destination = .privacyPolicy }
                footerNavLink(AppStrings.termsOfService) { destination = .terms }
            }

            // Version
            footerSection("App version") {
                Text("v\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")")
                    .font(.omSmall)
                    .foregroundStyle(Color.grey50)
                    .padding(.vertical, .spacing3)
            }
        }
        // web: margin-top: 100px
        // web: margin-top: 100px — no single token, combine spacing32 (64) + spacing20 (40) ≈ 104pt
        .padding(.top, .spacing32 + .spacing20)
        .padding(.horizontal, .spacing6)
        .padding(.bottom, .spacing8)
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

    // MARK: - Sub-page Shell

    private func settingsShell<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: .spacing4) {
                OMIconButton(icon: "back", label: AppStrings.back, size: 36) {
                    destination = nil
                }
                Text(title)
                    .font(.omH3)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                Spacer()
                OMIconButton(icon: "close", label: AppStrings.done, size: 36) {
                    dismiss()
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing6)
            .background(Color.grey0)

            content()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color.grey0)
    }

    @ViewBuilder
    private func settingsDestinationView(_ destination: SettingsDestination) -> some View {
        settingsShell(title: destination.title) {
            destination.view
        }
    }

    // MARK: - Destination Enum (matches web settingsRoutes.ts top-level keys)

    @MainActor
    private enum SettingsDestination: Hashable {
        // Top-level menu items (matching web settingsRoutes.ts order)
        case pricing, ai, memories, apps, privacy, mates
        case billing, notifications, shared, interface
        case account, developers, newsletter, support, reportIssue
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
            case .server: return AppStrings.serverAdmin
            case .logs: return AppStrings.logs
            case .privacyPolicy: return AppStrings.privacyPolicy
            case .terms: return AppStrings.termsOfService
            case .imprint: return AppStrings.imprint
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
            case .server: SettingsServerView()
            case .logs: SettingsLogsView()
            case .privacyPolicy: LegalChatView(documentType: .privacy)
            case .terms: LegalChatView(documentType: .terms)
            case .imprint: LegalChatView(documentType: .imprint)
            }
        }
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
