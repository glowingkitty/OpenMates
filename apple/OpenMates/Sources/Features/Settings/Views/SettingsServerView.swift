// Admin-only server settings for updates, statistics, budgets, gift cards, and tests.
// Routes and payloads mirror the current web settings and backend contracts.
// Managed-cloud-only controls remain separate from self-host software operations.
// Risky mutations expose explicit saving, confirmation, success, and error states.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsServer.svelte
//          frontend/packages/ui/src/components/settings/server/*.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsServerView: View {
    @State private var destination: Destination?

    var body: some View {
        if let destination {
            VStack(spacing: 0) {
                OMSettingsRow(
                    title: AppStrings.back,
                    icon: "back",
                    showsChevron: false,
                    accessibilityIdentifier: "settings-server-back"
                ) { self.destination = nil }
                destination.view
            }
            .background(Color.grey0)
        } else {
            OMSettingsPage(title: AppStrings.serverAdmin, showsHeader: false) {
                OMSettingsSection {
                    serverRow(.softwareUpdate, title: L("settings.software_updates"), icon: "download")
                    serverRow(.stats, title: L("settings.server.stats"), icon: "usage")
                    serverRow(.giftCards, title: L("common.gift_cards"), icon: "gift_cards")
                    serverRow(.freeTestingCredits, title: L("settings.server.free_testing_budget.title"), icon: "gift_cards")
                    serverRow(.anonymousFreeUsage, title: L("settings.server.anonymous_free_usage_budget.title"), icon: "ai")
                    serverRow(.tests, title: L("settings.server.tests"), icon: "check")
                }
            }
            .accessibilityIdentifier("settings-server-page")
        }
    }

    private func serverRow(_ value: Destination, title: String, icon: String) -> some View {
        OMSettingsRow(title: title, icon: icon, accessibilityIdentifier: value.identifier) {
            destination = value
        }
    }

    private enum Destination {
        case softwareUpdate, stats, giftCards, freeTestingCredits, anonymousFreeUsage, tests

        var identifier: String {
            switch self {
            case .softwareUpdate: return "software-update-settings-item"
            case .stats: return "server-stats-settings-item"
            case .giftCards: return "gift-cards-settings-item"
            case .freeTestingCredits: return "free-testing-budget-settings-item"
            case .anonymousFreeUsage: return "anonymous-free-usage-settings-item"
            case .tests: return "server-tests-settings-item"
            }
        }

        @MainActor @ViewBuilder var view: some View {
            switch self {
            case .softwareUpdate: ServerSoftwareUpdateView()
            case .stats: ServerStatsView()
            case .giftCards: ServerGiftCardGeneratorView()
            case .freeTestingCredits: ServerFreeTestingCreditsView()
            case .anonymousFreeUsage: ServerAnonymousFreeUsageView()
            case .tests: ServerTestResultsView()
            }
        }
    }
}

struct ServerSoftwareUpdateView: View {
    @State private var versions: [String: AnyCodable] = [:]
    @State private var autoCheckEnabled = true
    @State private var autoInstallEnabled = false
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var pendingInstall = false
    @State private var statusMessage: String?
    @State private var errorMessage: String?

    var body: some View {
        OMSettingsPage(title: L("settings.software_updates"), showsHeader: false) {
            if isLoading { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }
            else {
                OMSettingsSection(L("admin.current_version")) {
                    OMSettingsStaticRow(
                        title: L("admin.commit"),
                        value: stringValue("current_version") ?? L("admin.not_available")
                    )
                    OMSettingsStaticRow(
                        title: L("admin.latest"),
                        value: stringValue("latest_version") ?? L("admin.not_available")
                    )
                }
                OMSettingsSection(L("admin.update_settings")) {
                    OMSettingsToggleRow(title: L("admin.auto_check_updates"), isOn: $autoCheckEnabled, disabled: isSaving)
                        .onChange(of: autoCheckEnabled) { _, _ in saveConfig() }
                    OMSettingsToggleRow(title: L("admin.auto_install_updates"), isOn: $autoInstallEnabled, disabled: isSaving)
                        .onChange(of: autoInstallEnabled) { _, _ in saveConfig() }
                }
                OMSettingsSection {
                    Button(L("admin.check_for_updates")) { checkForUpdates() }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(isSaving)
                    Button(L("admin.install_update")) { pendingInstall = true }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(isSaving)
                }
            }
            settingsStatus(statusMessage, error: false)
            settingsStatus(errorMessage, error: true)
        }
        .task { await load() }
        .overlay {
            if pendingInstall {
                OMConfirmDialog(
                    title: L("admin.install_update"),
                    message: L("admin.install_update_hint"),
                    confirmTitle: AppStrings.confirm,
                    isDestructive: false,
                    onConfirm: { pendingInstall = false; installUpdate() },
                    onCancel: { pendingInstall = false }
                )
            }
        }
    }

    private func stringValue(_ key: String) -> String? {
        versions[key]?.value as? String
    }

    private func load() async {
        do {
            async let versionRequest: [String: AnyCodable] = APIClient.shared.request(
                .get, path: "/v1/settings/software_update/versions"
            )
            async let configRequest: [String: AnyCodable] = APIClient.shared.request(
                .get, path: "/v1/settings/software_update/config"
            )
            let (versionResponse, configResponse) = try await (versionRequest, configRequest)
            versions = versionResponse
            autoCheckEnabled = configResponse["auto_check"]?.value as? Bool ?? true
            autoInstallEnabled = configResponse["auto_install"]?.value as? Bool ?? false
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Software update settings load failed", category: "settings.admin")
        }
        isLoading = false
    }

    private func checkForUpdates() {
        isSaving = true
        Task {
            do {
                versions = try await APIClient.shared.request(
                    .get, path: "/v1/settings/software_update/check"
                )
                statusMessage = AppStrings.success
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Software update check failed", category: "settings.admin")
            }
            isSaving = false
        }
    }

    private func saveConfig() {
        mutate(
            method: .put,
            path: "/v1/settings/software_update/config",
            body: SoftwareUpdateConfig(autoCheck: autoCheckEnabled, autoInstall: autoInstallEnabled),
            checksInstallStatus: false
        )
    }

    private func installUpdate() {
        mutate(
            method: .post,
            path: "/v1/settings/software_update/install",
            body: SoftwareUpdateInstallRequest(clearCache: true),
            checksInstallStatus: true
        )
    }

    private func mutate<Body: Encodable>(
        method: HTTPMethod,
        path: String,
        body: Body,
        checksInstallStatus: Bool
    ) {
        isSaving = true
        errorMessage = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(method, path: path, body: body)
                statusMessage = AppStrings.success
                if checksInstallStatus {
                    let _: [String: AnyCodable] = try await APIClient.shared.request(
                        .get, path: "/v1/settings/software_update/install_status"
                    )
                }
                await load()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Software update mutation failed", category: "settings.admin")
            }
            isSaving = false
        }
    }
}

private struct SoftwareUpdateConfig: Encodable {
    let autoCheck: Bool
    let autoInstall: Bool
}

private struct SoftwareUpdateInstallRequest: Encodable {
    let clearCache: Bool
}

struct ServerStatsView: View {
    @State private var response: ServerStatsResponse?
    @State private var isLoading = true
    @State private var errorMessage: String?

    struct ServerStatsResponse: Decodable {
        let current: [String: AnyCodable]
        let dailyHistory: [[String: AnyCodable]]
        let newsletterSubscribersCount: Int
        let timestamp: String
    }

    var body: some View {
        OMSettingsPage(title: L("settings.server.stats"), showsHeader: false) {
            if isLoading { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }
            else if let response {
                OMSettingsSection(L("settings.server.stats")) {
                    statRow("total_regular_users", response.current["total_regular_users"])
                    statRow("messages_sent", response.current["messages_sent"])
                    statRow("chats_created", response.current["chats_created"])
                    statRow("credits_used", response.current["credits_used"])
                    OMSettingsStaticRow(
                        title: L("settings.server.stats.newsletter_subscribers"),
                        value: "\(response.newsletterSubscribersCount)"
                    )
                }
                OMSettingsSection(L("settings.server.stats.daily_history")) {
                    ForEach(Array(response.dailyHistory.prefix(30).enumerated()), id: \.offset) { _, day in
                        OMSettingsStaticRow(
                            title: (day["date"]?.value as? String) ?? L("common.unknown"),
                            value: numberString(day["messages_sent"])
                        )
                    }
                }
            }
            settingsStatus(errorMessage, error: true)
        }
        .task { await load() }
    }

    private func statRow(_ key: String, _ value: AnyCodable?) -> some View {
        OMSettingsStaticRow(title: L("settings.server.stats.\(key)"), value: numberString(value))
    }

    private func load() async {
        do {
            response = try await APIClient.shared.request(.get, path: "/v1/admin/server-stats")
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Server statistics load failed", category: "settings.admin")
        }
        isLoading = false
    }
}

struct ServerGiftCardGeneratorView: View {
    @State private var cards: [GiftCard] = []
    @State private var creditsValue = 1_000
    @State private var count = 1
    @State private var prefix = ""
    @State private var notes = ""
    @State private var isSaving = false
    @State private var errorMessage: String?

    struct GiftCard: Identifiable, Decodable {
        let id: String?
        let code: String
        let creditsValue: Int
        let createdAt: String?
        var stableID: String { id ?? code }
    }
    private struct ListResponse: Decodable { let giftCards: [GiftCard] }
    private struct GenerateResponse: Decodable { let giftCards: [GiftCard] }

    var body: some View {
        OMSettingsPage(title: L("common.gift_cards"), showsHeader: false) {
            OMSettingsSection(L("admin.generate_gift_cards")) {
                VStack(alignment: .leading, spacing: .spacing5) {
                    TextField(L("admin.credits"), value: $creditsValue, format: .number)
                        .textFieldStyle(OMTextFieldStyle())
                    TextField(L("admin.quantity"), value: $count, format: .number)
                        .textFieldStyle(OMTextFieldStyle())
                    TextField(L("admin.custom_prefix_optional"), text: $prefix)
                        .textFieldStyle(OMTextFieldStyle())
                    TextField(L("admin.notes_optional"), text: $notes)
                        .textFieldStyle(OMTextFieldStyle())
                    Button(L("admin.generate")) { generate() }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(isSaving || creditsValue < 1 || count < 1)
                }
                .padding(.spacing6)
            }
            OMSettingsSection(L("admin.active_gift_cards")) {
                ForEach(cards, id: \.stableID) { card in
                    OMSettingsStaticRow(title: card.code, value: "\(card.creditsValue)")
                }
            }
            settingsStatus(errorMessage, error: true)
        }
        .task { await loadCards() }
    }

    private func loadCards() async {
        do {
            let response: ListResponse = try await APIClient.shared.request(.get, path: "/v1/admin/gift-cards")
            cards = response.giftCards
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Gift card list failed", category: "settings.admin")
        }
    }

    private func generate() {
        isSaving = true
        Task {
            do {
                let response: GenerateResponse = try await APIClient.shared.request(
                    .post,
                    path: "/v1/admin/generate-gift-cards",
                    body: GiftCardRequest(
                        creditsValue: creditsValue,
                        count: count,
                        prefix: prefix.isEmpty ? nil : prefix,
                        notes: notes.isEmpty ? nil : notes
                    )
                )
                cards = response.giftCards + cards
                prefix = ""
                notes = ""
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Gift card generation failed", category: "settings.admin")
            }
            isSaving = false
        }
    }
}

private struct GiftCardRequest: Encodable {
    let creditsValue: Int
    let count: Int
    let prefix: String?
    let notes: String?
}

struct ServerFreeTestingCreditsView: View {
    @State private var budget: FreeTestingBudget?
    @State private var isSaving = false
    @State private var errorMessage: String?

    struct FreeTestingBudget: Codable {
        var enabled: Bool
        var totalBudgetCredits: Int
        let usedBudgetCredits: Int
        let remainingBudgetCredits: Int
        var perUserGrantCredits: Int
    }

    var body: some View {
        budgetPage(
            title: L("settings.server.free_testing_budget.title"),
            enabled: Binding(get: { budget?.enabled ?? false }, set: { budget?.enabled = $0 }),
            total: Binding(get: { budget?.totalBudgetCredits ?? 0 }, set: { budget?.totalBudgetCredits = $0 }),
            perIdentity: Binding(get: { budget?.perUserGrantCredits ?? 0 }, set: { budget?.perUserGrantCredits = $0 }),
            used: budget?.usedBudgetCredits ?? 0,
            remaining: budget?.remainingBudgetCredits ?? 0,
            isSaving: isSaving,
            errorMessage: errorMessage,
            onSave: save
        )
        .task { await load() }
    }

    private func load() async {
        do { budget = try await APIClient.shared.request(.get, path: "/v1/admin/free-testing-credits-budget") }
        catch { errorMessage = error.localizedDescription; NativeDiagnostics.error("Free testing budget load failed", category: "settings.admin") }
    }

    private func save() {
        guard let budget else { return }
        isSaving = true
        Task {
            do {
                self.budget = try await APIClient.shared.request(
                    .put,
                    path: "/v1/admin/free-testing-credits-budget",
                    body: FreeTestingBudgetRequest(
                        enabled: budget.enabled,
                        totalBudgetCredits: budget.totalBudgetCredits,
                        perUserGrantCredits: budget.perUserGrantCredits
                    )
                )
            } catch { errorMessage = error.localizedDescription; NativeDiagnostics.error("Free testing budget save failed", category: "settings.admin") }
            isSaving = false
        }
    }
}

private struct FreeTestingBudgetRequest: Encodable {
    let enabled: Bool
    let totalBudgetCredits: Int
    let perUserGrantCredits: Int
}

struct ServerAnonymousFreeUsageView: View {
    @State private var budget: AnonymousBudget?
    @State private var isSaving = false
    @State private var errorMessage: String?

    struct AnonymousBudget: Codable {
        var enabled: Bool
        var monthlyBudgetCredits: Int
        var dailyHardCapPercent: Int
        var weeklyCapPercent: Int
        var perIdentityDailyCapCredits: Int
        let monthlyUsedCredits: Int
        let monthlyRemainingCredits: Int
    }

    var body: some View {
        budgetPage(
            title: L("settings.server.anonymous_free_usage_budget.title"),
            enabled: Binding(get: { budget?.enabled ?? false }, set: { budget?.enabled = $0 }),
            total: Binding(get: { budget?.monthlyBudgetCredits ?? 0 }, set: { budget?.monthlyBudgetCredits = $0 }),
            perIdentity: Binding(get: { budget?.perIdentityDailyCapCredits ?? 0 }, set: { budget?.perIdentityDailyCapCredits = $0 }),
            used: budget?.monthlyUsedCredits ?? 0,
            remaining: budget?.monthlyRemainingCredits ?? 0,
            isSaving: isSaving,
            errorMessage: errorMessage,
            onSave: save
        )
        .task { await load() }
    }

    private func load() async {
        do { budget = try await APIClient.shared.request(.get, path: "/v1/admin/anonymous-free-usage-budget") }
        catch { errorMessage = error.localizedDescription; NativeDiagnostics.error("Anonymous budget load failed", category: "settings.admin") }
    }

    private func save() {
        guard let budget else { return }
        isSaving = true
        Task {
            do {
                self.budget = try await APIClient.shared.request(
                    .put,
                    path: "/v1/admin/anonymous-free-usage-budget",
                    body: AnonymousBudgetRequest(
                        enabled: budget.enabled,
                        monthlyBudgetCredits: budget.monthlyBudgetCredits,
                        dailyHardCapPercent: budget.dailyHardCapPercent,
                        weeklyCapPercent: budget.weeklyCapPercent,
                        perIdentityDailyCapCredits: budget.perIdentityDailyCapCredits
                    )
                )
            } catch { errorMessage = error.localizedDescription; NativeDiagnostics.error("Anonymous budget save failed", category: "settings.admin") }
            isSaving = false
        }
    }
}

private struct AnonymousBudgetRequest: Encodable {
    let enabled: Bool
    let monthlyBudgetCredits: Int
    let dailyHardCapPercent: Int
    let weeklyCapPercent: Int
    let perIdentityDailyCapCredits: Int
}

@MainActor
private func budgetPage(
    title: String,
    enabled: Binding<Bool>,
    total: Binding<Int>,
    perIdentity: Binding<Int>,
    used: Int,
    remaining: Int,
    isSaving: Bool,
    errorMessage: String?,
    onSave: @escaping () -> Void
) -> some View {
    OMSettingsPage(title: title, showsHeader: false) {
        OMSettingsSection {
            OMSettingsToggleRow(title: AppStrings.enabled, isOn: enabled, disabled: isSaving)
            TextField(L("settings.server.budget.total"), value: total, format: .number)
                .textFieldStyle(OMTextFieldStyle()).padding(.horizontal, .spacing6)
            TextField(L("settings.server.budget.per_identity"), value: perIdentity, format: .number)
                .textFieldStyle(OMTextFieldStyle()).padding(.horizontal, .spacing6)
            OMSettingsStaticRow(title: L("settings.server.budget.used"), value: "\(used)")
            OMSettingsStaticRow(title: L("settings.server.budget.remaining"), value: "\(remaining)")
            Button(AppStrings.save, action: onSave)
                .buttonStyle(OMPrimaryButtonStyle()).disabled(isSaving).padding(.spacing6)
        }
        settingsStatus(errorMessage, error: true)
    }
}

struct ServerTestResultsView: View {
    @State private var response: TestResultsResponse?
    @State private var isLoading = true
    @State private var errorMessage: String?

    struct TestResultsResponse: Decodable {
        let hasResults: Bool
        let lastRunTimestamp: String?
        let nextScheduledRunUtc: String
        let hoursUntilNextRun: Double
    }

    var body: some View {
        OMSettingsPage(title: L("settings.server.tests"), showsHeader: false) {
            if isLoading { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }
            else if let response {
                OMSettingsSection {
                    OMSettingsStaticRow(
                        title: L("settings.server.tests.last_run"),
                        value: response.lastRunTimestamp ?? L("admin.no_test_results")
                    )
                    OMSettingsStaticRow(
                        title: L("settings.server.tests.next_run"),
                        value: response.nextScheduledRunUtc
                    )
                    OMSettingsStaticRow(
                        title: L("settings.server.tests.hours_until"),
                        value: "\(response.hoursUntilNextRun)"
                    )
                }
            }
            settingsStatus(errorMessage, error: true)
        }
        .task { await load() }
    }

    private func load() async {
        do { response = try await APIClient.shared.request(.get, path: "/v1/admin/test-results") }
        catch { errorMessage = error.localizedDescription; NativeDiagnostics.error("Test results load failed", category: "settings.admin") }
        isLoading = false
    }
}

private struct EmptyAdminRequest: Encodable {}

private func numberString(_ value: AnyCodable?) -> String {
    if let int = value?.value as? Int { return "\(int)" }
    if let double = value?.value as? Double { return "\(double)" }
    return "0"
}

@ViewBuilder
private func settingsStatus(_ message: String?, error: Bool) -> some View {
    if let message {
        Text(message)
            .font(.omSmall)
            .foregroundStyle(error ? Color.error : Color.buttonPrimary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.spacing6)
    }
}

@MainActor
private func L(_ key: String) -> String { LocalizationManager.shared.text(key) }
