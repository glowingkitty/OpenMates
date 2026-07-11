// Native billing, StoreKit purchases, invoices, usage, gift cards, referrals, and support.
// Uses the current backend response envelopes and keeps product-owned flows inside OpenMates.
// Downloaded CSV/PDF documents are handed to OS-owned file/share surfaces only.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsBilling.svelte
//          frontend/packages/ui/src/components/settings/SettingsUsage.svelte
//          frontend/packages/ui/src/components/settings/billing/SettingsInvoices.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import StoreKit
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

enum BillingUITestFixture {
    static var enabled: Bool { ProcessInfo.processInfo.arguments.contains("--ui-test-billing-fixture") }
}

private enum BillingRoute {
    case buyCredits, autoTopUp, invoices, usage, referralCode, giftCards, support
}

struct SettingsBillingView: View {
    let referralCodeRequest: Int

    @EnvironmentObject private var authManager: AuthManager
    @State private var route: BillingRoute?
    @State private var handledReferralCodeRequest = 0

    init(referralCodeRequest: Int = 0) {
        self.referralCodeRequest = referralCodeRequest
        _route = State(initialValue: referralCodeRequest > 0 ? .referralCode : nil)
        _handledReferralCodeRequest = State(initialValue: referralCodeRequest)
    }

    var body: some View {
        Group {
            if let route { subview(route) } else { hub }
        }
        .onChange(of: referralCodeRequest) { _, request in
            guard request != handledReferralCodeRequest else { return }
            handledReferralCodeRequest = request
            route = .referralCode
        }
        .onReceive(NotificationCenter.default.publisher(for: .paymentCompleted)) { _ in
            Task { await authManager.validateSessionAfterOfflineBootstrap() }
        }
    }

    private var hub: some View {
        OMSettingsPage(title: AppStrings.settingsBilling, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-hub")

            HStack(spacing: .spacing5) {
                Icon("coins", size: 28).foregroundStyle(Color.grey90)
                Text(Int(authManager.currentUser?.credits ?? 0).formatted())
                    .font(.omH2.weight(.semibold)).foregroundStyle(Color.grey100).monospacedDigit()
                Text(AppStrings.credits).font(.omSmall).foregroundStyle(Color.grey60)
            }
            .frame(maxWidth: .infinity)
            .padding(.spacing10)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing4)

            OMSettingsSection {
                billingRow(AppStrings.buyCredits, icon: "coins", id: "settings-billing-buy-credits-row", route: .buyCredits)
                billingRow(AppStrings.autoTopUp, icon: "reload", id: "settings-billing-auto-topup-row", route: .autoTopUp)
                billingRow(AppStrings.invoices, icon: "document", id: "settings-billing-invoices-row", route: .invoices)
                billingRow(AppStrings.giftCards, icon: "gift", id: "settings-billing-gift-cards-row", route: .giftCards)
                billingRow(AppStrings.referralCode, icon: "gift", id: "settings-billing-referral-code-row", route: .referralCode)
                billingRow(AppStrings.billingSupport, icon: "support", id: "settings-billing-support-row", route: .support)
            }

            Rectangle().fill(Color.grey25).frame(height: 1).padding(.horizontal, .spacing5).padding(.vertical, .spacing6)

            OMSettingsSection(AppStrings.usage, icon: "usage") {
                billingRow(AppStrings.billingUsageDetails, icon: "usage", id: "settings-billing-usage-row", route: .usage)
            }
        }
    }

    private func billingRow(_ title: String, icon: String, id: String, route: BillingRoute) -> some View {
        OMSettingsRow(title: title, icon: icon) { self.route = route }
            .accessibilityIdentifier(id)
    }

    @ViewBuilder
    private func subview(_ route: BillingRoute) -> some View {
        VStack(spacing: 0) {
            Button { self.route = nil } label: {
                HStack(spacing: .spacing3) {
                    Icon("back", size: 20).foregroundStyle(Color.fontSecondary)
                    Text(AppStrings.settingsBilling).font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontSecondary)
                    Spacer()
                }
                .padding(.horizontal, .spacing8).padding(.vertical, .spacing5).background(Color.grey20)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("settings-billing-subview-back")

            switch route {
            case .buyCredits: BuyCreditsView()
            case .autoTopUp: AutoTopUpView()
            case .invoices: InvoicesView()
            case .usage: BillingUsageView()
            case .referralCode: SettingsReferralCodeView()
            case .giftCards: BillingGiftCardsView()
            case .support: BillingSupportView()
            }
        }
    }
}

// MARK: - StoreKit credits

struct BuyCreditsView: View {
    @StateObject private var store = StoreManager.shared

    private let fixtureProducts = [(1_000, "€5.99"), (10_000, "€49.99"), (21_000, "€99.99"), (54_000, "€249.99")]

    var body: some View {
        OMSettingsPage(title: AppStrings.buyCredits, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-buy-credits-page")

            OMSettingsSection(AppStrings.billingCreditPackages, icon: "coins") {
                if BillingUITestFixture.enabled {
                    ForEach(fixtureProducts, id: \.0) { credits, price in
                        creditRow(credits: credits, price: price, action: nil)
                            .accessibilityIdentifier("settings-billing-product-\(credits)")
                    }
                } else if store.products.isEmpty {
                    loadingRow(AppStrings.billingLoadingProducts)
                } else {
                    ForEach(store.products, id: \.id) { product in
                        creditRow(credits: product.creditsAmount, price: product.displayPrice) {
                            Task { await store.purchase(product) }
                        }
                    }
                }
            }

            if store.purchaseState == .purchasing { loadingSection(AppStrings.billingProcessingPurchase) }
            if store.purchaseState == .verifying { loadingSection(AppStrings.billingVerifyingPurchase) }
            if case .success(let credits) = store.purchaseState {
                OMSettingsSection {
                    VStack(spacing: .spacing4) {
                        Icon("check", size: 40).foregroundStyle(Color.buttonPrimary)
                        Text(AppStrings.billingPurchaseComplete).font(.omH4.weight(.semibold))
                        Text(AppStrings.billingCreditsAdded(credits)).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        Button(AppStrings.done) { store.resetState() }.buttonStyle(OMPrimaryButtonStyle())
                    }
                    .frame(maxWidth: .infinity).padding(.spacing6)
                }
            }
            if let error = store.lastError {
                OMSettingsSection { Text(error).font(.omSmall).foregroundStyle(Color.error).padding(.spacing5) }
            }

            OMSettingsSection {
                Button(AppStrings.billingRestorePurchases) { Task { await store.restorePurchases() } }
                    .buttonStyle(.plain).font(.omSmall).padding(.spacing5)
                    .accessibilityIdentifier("settings-billing-restore-purchases-row")
            }
        }
        .task { if !BillingUITestFixture.enabled { await store.loadProducts() } }
    }

    private func creditRow(credits: Int, price: String, action: (() -> Void)?) -> some View {
        HStack {
            Text(AppStrings.billingCreditsAdded(credits)).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
            Spacer()
            Button(price) { action?() }
                .buttonStyle(OMPrimaryButtonStyle()).disabled(action == nil && !BillingUITestFixture.enabled)
        }
        .padding(.horizontal, .spacing5).padding(.vertical, .spacing3)
    }

    private func loadingRow(_ text: String) -> some View {
        HStack(spacing: .spacing3) { ProgressView(); Text(text).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            .padding(.spacing5)
    }

    private func loadingSection(_ text: String) -> some View {
        OMSettingsSection { loadingRow(text) }
    }
}

// MARK: - Auto top-up

struct AutoTopUpView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var overview = BillingOverviewResponse.empty
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var error: String?

    private let amounts = [1_000, 10_000, 21_000, 54_000]

    var body: some View {
        OMSettingsPage(title: AppStrings.autoTopUp, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-auto-topup-page")
            if isLoading { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }

            OMSettingsSection(AppStrings.billingLowBalanceAutoTopUp, icon: "reload") {
                OMSettingsToggleRow(
                    title: AppStrings.enabled,
                    subtitle: AppStrings.billingLowBalanceDescription,
                    isOn: $overview.autoTopupEnabled
                )
                .disabled(isSaving)
                .accessibilityIdentifier("settings-billing-low-balance-toggle")
                .onChange(of: overview.autoTopupEnabled) { previousValue, enabled in
                    guard previousValue != enabled, !isLoading else { return }
                    var previous = overview
                    previous.autoTopupEnabled = previousValue
                    save(previous: previous)
                }

                if overview.autoTopupEnabled {
                    OMSettingsStaticRow(title: AppStrings.billingWhenBelow, value: AppStrings.billingCreditsAdded(overview.autoTopupThreshold))
                    OMSettingsPickerRow(
                        title: AppStrings.billingTopUpPackage,
                        options: amounts.map { OMDropdownOption("\($0)", label: AppStrings.billingCreditsAdded($0)) },
                        selection: Binding(
                            get: { "\(overview.autoTopupAmount)" },
                            set: { if let amount = Int($0) { updateAmount(amount) } }
                        )
                    )
                    .disabled(isSaving)
                    .accessibilityIdentifier("settings-billing-low-balance-package")
                }
            }
            if let error { OMSettingsSection { Text(error).font(.omSmall).foregroundStyle(Color.error).padding(.spacing5) } }
        }
        .task { await load() }
    }

    private func load() async {
        if BillingUITestFixture.enabled {
            overview = .fixture
            isLoading = false
            return
        }
        do { overview = try await BillingService.shared.billingOverview() }
        catch {
            self.error = error.localizedDescription
            NativeDiagnostics.warning("Billing overview load failed: \(type(of: error))", category: "billing")
        }
        isLoading = false
    }

    private func updateAmount(_ amount: Int) {
        let previous = overview
        overview.autoTopupAmount = amount
        save(previous: previous)
    }

    private func save(previous: BillingOverviewResponse) {
        guard !BillingUITestFixture.enabled else { return }
        isSaving = true
        error = nil
        Task {
            do {
                try await BillingService.shared.updateAutoTopUp(
                    enabled: overview.autoTopupEnabled,
                    amount: overview.autoTopupAmount,
                    currency: overview.autoTopupCurrency,
                    email: authManager.currentUser?.email
                )
            } catch {
                overview = previous
                self.error = error.localizedDescription
                NativeDiagnostics.warning("Auto top-up update failed: \(type(of: error))", category: "billing")
            }
            isSaving = false
        }
    }
}

// MARK: - Invoices

struct InvoicesView: View {
    @State private var invoices: [BillingInvoice] = []
    @State private var isLoading = true
    @State private var error: String?
    @State private var downloadedURL: URL?

    var body: some View {
        OMSettingsPage(title: AppStrings.invoices, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-invoices-page")
            if isLoading { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }
            else if invoices.isEmpty {
                OMSettingsSection { Text(AppStrings.billingNoInvoices).font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.spacing5) }
                    .accessibilityIdentifier("settings-billing-no-invoices")
            } else {
                OMSettingsSection {
                    ForEach(invoices) { invoice in
                        VStack(alignment: .leading, spacing: .spacing3) {
                            HStack {
                                VStack(alignment: .leading, spacing: .spacing1) {
                                    Text(invoice.formattedAmount).font(.omSmall.weight(.semibold))
                                    Text(invoice.date).font(.omXs).foregroundStyle(Color.fontTertiary)
                                    Text(AppStrings.billingCreditsAdded(invoice.creditsPurchased)).font(.omXs).foregroundStyle(Color.fontSecondary)
                                }
                                Spacer()
                                Text(invoice.displayStatus).font(.omTiny).foregroundStyle(Color.fontSecondary)
                            }
                            if invoice.documentStatus == "ready" {
                                Button(AppStrings.billingDownloadInvoice) { download(invoice: invoice, creditNote: false) }
                                    .buttonStyle(OMPrimaryButtonStyle())
                                if invoice.refundStatus == "completed" {
                                    Button(AppStrings.billingDownloadCreditNote) { download(invoice: invoice, creditNote: true) }
                                        .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                                }
                            } else if let reference = invoice.bankTransferReference {
                                Text(AppStrings.billingBankTransferReference(reference)).font(.omXs).textSelection(.enabled)
                            }
                        }
                        .padding(.spacing5)
                        .accessibilityIdentifier("settings-billing-invoice-row")
                    }
                }
            }
            if let error { OMSettingsSection { Text(error).font(.omSmall).foregroundStyle(Color.error).padding(.spacing5) } }
        }
        .task { await load() }
        .onChange(of: downloadedURL) { _, url in if let url { presentFile(url) } }
    }

    private func load() async {
        if BillingUITestFixture.enabled {
            invoices = [.fixture]
            isLoading = false
            return
        }
        do { invoices = try await BillingService.shared.invoices().invoices }
        catch {
            self.error = error.localizedDescription
            NativeDiagnostics.warning("Invoice list load failed: \(type(of: error))", category: "billing")
        }
        isLoading = false
    }

    private func download(invoice: BillingInvoice, creditNote: Bool) {
        Task {
            do { downloadedURL = try await BillingService.shared.downloadInvoice(invoice, creditNote: creditNote) }
            catch { self.error = error.localizedDescription }
        }
    }
}

// MARK: - Usage

private enum UsageTab: String, CaseIterable { case overview, chats, apps, api }

struct BillingUsageView: View {
    @State private var tab: UsageTab = .overview
    @State private var daily: [UsageDay] = []
    @State private var summaries: [UsageSummary] = []
    @State private var details: [UsageEntry] = []
    @State private var selected: UsageSummary?
    @State private var isLoading = false
    @State private var error: String?
    @State private var exportedURL: URL?

    var body: some View {
        OMSettingsPage(title: AppStrings.usage, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-usage-page")
            OMSegmentedControl(
                items: UsageTab.allCases.map { .init(id: $0, title: title($0)) },
                selection: $tab
            )
            .padding(.horizontal, .spacing5)
            .accessibilityIdentifier("settings-billing-usage-tabs")

            OMSettingsSection {
                Button(AppStrings.billingExportUsage) { exportUsage() }
                    .buttonStyle(OMPrimaryButtonStyle()).padding(.spacing5)
                    .accessibilityIdentifier("settings-billing-usage-export")
            }

            if isLoading { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }
            else if selected != nil {
                OMSettingsSection(AppStrings.billingUsageDetails) {
                    Button(AppStrings.back) { self.selected = nil; details = [] }.buttonStyle(.plain).padding(.spacing5)
                    ForEach(details) { entry in usageEntry(entry) }
                }
                .accessibilityIdentifier("settings-billing-usage-drilldown")
            } else if tab == .overview {
                OMSettingsSection {
                    ForEach(daily) { day in
                        OMSettingsStaticRow(title: day.date, value: day.totalCredits.formatted())
                    }
                }
            } else {
                OMSettingsSection {
                    ForEach(summaries) { summary in
                        Button { open(summary) } label: {
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(summary.identifier(fallback: AppStrings.billingUnknownUsage))
                                        .font(.omSmall).foregroundStyle(Color.fontPrimary).lineLimit(1)
                                    Text(summary.month).font(.omXs).foregroundStyle(Color.fontTertiary)
                                }
                                Spacer()
                                Text(summary.totalCredits.formatted()).font(.omSmall).foregroundStyle(Color.fontSecondary)
                                Icon("forward", size: 16).foregroundStyle(Color.fontTertiary)
                            }
                            .padding(.spacing5)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            if let error { OMSettingsSection { Text(error).font(.omSmall).foregroundStyle(Color.error).padding(.spacing5) } }
        }
        .task { await load() }
        .onChange(of: tab) { _, _ in Task { await load() } }
        .onChange(of: exportedURL) { _, url in if let url { presentFile(url) } }
    }

    private func title(_ tab: UsageTab) -> String {
        switch tab {
        case .overview: AppStrings.billingUsageOverview
        case .chats: AppStrings.billingUsageChats
        case .apps: AppStrings.billingUsageApps
        case .api: AppStrings.billingUsageAPI
        }
    }

    private func load() async {
        isLoading = true
        error = nil
        selected = nil
        if BillingUITestFixture.enabled {
            daily = [.fixture]
            summaries = [.fixture(for: tab)]
            isLoading = false
            return
        }
        do {
            if tab == .overview { daily = try await BillingService.shared.dailyUsage().days }
            else { summaries = try await BillingService.shared.usageSummaries(type: tab.backendType).summaries }
        } catch {
            self.error = error.localizedDescription
            NativeDiagnostics.warning("Usage load failed: \(type(of: error))", category: "billing_usage")
        }
        isLoading = false
    }

    private func open(_ summary: UsageSummary) {
        selected = summary
        isLoading = true
        let unknownUsage = AppStrings.billingUnknownUsage
        Task {
            do {
                details = try await BillingService.shared.usageDetails(
                    type: tab.detailType,
                    summary: summary,
                    unknownUsage: unknownUsage
                ).entries
            }
            catch { self.error = error.localizedDescription }
            isLoading = false
        }
    }

    private func usageEntry(_ entry: UsageEntry) -> some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(entry.displayName).font(.omSmall).foregroundStyle(Color.fontPrimary)
            Text(Date(timeIntervalSince1970: TimeInterval(entry.createdAt)).formatted())
                .font(.omXs).foregroundStyle(Color.fontTertiary)
            Text(entry.credits.formatted()).font(.omXs).foregroundStyle(Color.fontSecondary)
        }
        .padding(.spacing5)
    }

    private func exportUsage() {
        Task {
            do { exportedURL = try await BillingService.shared.exportUsage() }
            catch { self.error = error.localizedDescription }
        }
    }
}

private extension UsageTab {
    var backendType: String { self == .api ? "api_keys" : rawValue }
    var detailType: String { self == .api ? "api_key" : String(rawValue.dropLast()) }
}

// MARK: - Gift cards and support

struct BillingGiftCardsView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var code = ""
    @State private var redeemed: [GiftCardRecord] = []
    @State private var purchased: [GiftCardRecord] = []
    @State private var purchaseAmount = "10000"
    @State private var transfer: BankTransferOrder?
    @State private var message: String?
    @State private var isWorking = false

    var body: some View {
        OMSettingsPage(title: AppStrings.giftCards, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-gift-cards-page")
            OMSettingsSection(AppStrings.billingRedeemGiftCard) {
                TextField(AppStrings.billingGiftCardCode, text: $code)
                    .textFieldStyle(OMTextFieldStyle()).autocorrectionDisabled().padding(.spacing5)
                Button(AppStrings.billingRedeemGiftCard) { redeem() }
                    .buttonStyle(OMPrimaryButtonStyle()).disabled(code.isEmpty || isWorking).padding(.spacing5)
            }
            OMSettingsSection(AppStrings.billingPurchaseGiftCard) {
                OMSettingsPickerRow(
                    title: AppStrings.billingTopUpPackage,
                    options: [1_000, 10_000, 21_000, 54_000].map {
                        OMDropdownOption("\($0)", label: AppStrings.billingCreditsAdded($0))
                    },
                    selection: $purchaseAmount
                )
                Button(AppStrings.billingCreateBankTransfer) { createGiftCardTransfer() }
                    .buttonStyle(OMPrimaryButtonStyle()).disabled(isWorking).padding(.spacing5)
                    .accessibilityIdentifier("settings-billing-gift-card-purchase")
            }
            if let transfer {
                OMSettingsSection(AppStrings.billingBankTransferDetails) {
                    OMSettingsStaticRow(title: AppStrings.billingTransferAmount, value: transfer.amountEur)
                    OMSettingsStaticRow(title: AppStrings.billingTransferReference, value: transfer.reference)
                    OMSettingsStaticRow(title: AppStrings.billingTransferIBAN, value: transfer.iban)
                    OMSettingsStaticRow(title: AppStrings.billingTransferBIC, value: transfer.bic)
                }
            }
            giftCardSection(AppStrings.billingRedeemedGiftCards, cards: redeemed)
            giftCardSection(AppStrings.billingPurchasedGiftCards, cards: purchased)
            if let message { OMSettingsSection { Text(message).font(.omSmall).padding(.spacing5) } }
        }
        .task { await load() }
    }

    private func giftCardSection(_ title: String, cards: [GiftCardRecord]) -> some View {
        OMSettingsSection(title) {
            if cards.isEmpty { Text(AppStrings.billingNoGiftCards).font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.spacing5) }
            ForEach(cards) { card in
                OMSettingsStaticRow(title: card.code, value: AppStrings.billingCreditsAdded(card.creditsValue))
            }
        }
    }

    private func load() async {
        if BillingUITestFixture.enabled { return }
        do {
            redeemed = try await BillingService.shared.redeemedGiftCards().redeemedCards
            purchased = try await BillingService.shared.purchasedGiftCards().purchasedCards
        } catch { message = error.localizedDescription }
    }

    private func redeem() {
        isWorking = true
        Task {
            do {
                let response = try await BillingService.shared.redeemGiftCard(code: code)
                message = response.message
                code = ""
                await load()
            } catch { message = error.localizedDescription }
            isWorking = false
        }
    }

    private func createGiftCardTransfer() {
        guard let credits = Int(purchaseAmount),
              let user = authManager.currentUser,
              let email = user.email,
              let saltValue = user.userEmailSalt,
              let salt = Data(base64Encoded: saltValue) else {
            message = AppStrings.billingGiftCardPurchaseUnavailable
            return
        }
        isWorking = true
        Task {
            do {
                let key = await CryptoManager.shared.deriveEmailEncryptionKey(email: email, salt: salt)
                transfer = try await BillingService.shared.createGiftCardTransfer(
                    credits: credits,
                    emailEncryptionKey: key.base64EncodedString()
                )
            } catch { message = error.localizedDescription }
            isWorking = false
        }
    }
}

struct BillingSupportView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var amount = ""
    @State private var transfer: BankTransferOrder?
    @State private var error: String?

    var body: some View {
        OMSettingsPage(title: AppStrings.billingSupport, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-support-page")
            OMSettingsSection(AppStrings.billingSupportContribution) {
                TextField(AppStrings.billingSupportAmount, text: $amount)
                    .textFieldStyle(OMTextFieldStyle()).padding(.spacing5)
                    #if os(iOS)
                    .keyboardType(.decimalPad)
                    #endif
                Button(AppStrings.billingCreateBankTransfer) { createTransfer() }
                    .buttonStyle(OMPrimaryButtonStyle()).padding(.spacing5)
            }
            if let transfer {
                OMSettingsSection(AppStrings.billingBankTransferDetails) {
                    OMSettingsStaticRow(title: AppStrings.billingTransferAmount, value: transfer.amountEur)
                    OMSettingsStaticRow(title: AppStrings.billingTransferReference, value: transfer.reference)
                    OMSettingsStaticRow(title: AppStrings.billingTransferIBAN, value: transfer.iban)
                    OMSettingsStaticRow(title: AppStrings.billingTransferBIC, value: transfer.bic)
                }
            }
            if let error { OMSettingsSection { Text(error).font(.omSmall).foregroundStyle(Color.error).padding(.spacing5) } }
        }
    }

    private func createTransfer() {
        guard let email = authManager.currentUser?.email,
              let decimal = Decimal(string: amount), decimal > 0 else {
            error = AppStrings.billingInvalidSupportAmount
            return
        }
        let cents = NSDecimalNumber(decimal: decimal * 100).intValue
        Task {
            do { transfer = try await BillingService.shared.createSupportTransfer(amount: cents, email: email) }
            catch { self.error = error.localizedDescription }
        }
    }
}

// MARK: - Referral

struct SettingsReferralCodeView: View {
    @State private var status: ReferralStatusResponse?
    @State private var error: String?
    @State private var copied = false

    var body: some View {
        OMSettingsPage(title: AppStrings.referralCode, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-referral-code-page")
            OMSettingsSection(AppStrings.getFreeCredits, icon: "gift") {
                if let status, status.available, let code = status.referralCode {
                    Text(code).font(.omP).textSelection(.enabled).padding(.spacing5)
                    Text(AppStrings.referralProgress(count: "\(status.successfulReferralsCount)", max: "\(status.maxSuccessfulReferrals)"))
                        .font(.omXs).foregroundStyle(Color.fontSecondary).padding(.horizontal, .spacing5)
                    Button(copied ? AppStrings.copied : AppStrings.copy) { copy(code) }
                        .buttonStyle(OMPrimaryButtonStyle()).padding(.spacing5)
                } else if let error { Text(error).font(.omSmall).foregroundStyle(Color.error).padding(.spacing5) }
                else { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }
            }
        }
        .task { await load() }
    }

    private func load() async {
        if BillingUITestFixture.enabled {
            status = .fixture
            return
        }
        do { status = try await BillingService.shared.referralStatus() }
        catch { self.error = error.localizedDescription }
    }

    private func copy(_ code: String) {
        #if os(iOS)
        UIPasteboard.general.string = code
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(code, forType: .string)
        #endif
        copied = true
    }
}

// MARK: - Typed backend contracts

private struct BillingOverviewResponse: Decodable {
    let paymentTier: Int
    var autoTopupEnabled: Bool
    let autoTopupThreshold: Int
    var autoTopupAmount: Int
    let autoTopupCurrency: String
    let invoices: [BillingInvoice]

    static let empty = Self(paymentTier: 1, autoTopupEnabled: false, autoTopupThreshold: 100, autoTopupAmount: 10_000, autoTopupCurrency: "eur", invoices: [])
    static let fixture = Self(paymentTier: 1, autoTopupEnabled: true, autoTopupThreshold: 100, autoTopupAmount: 10_000, autoTopupCurrency: "eur", invoices: [])
}

private struct BillingInvoice: Decodable, Identifiable {
    let id: String
    let orderId: String?
    let date: String
    let amount: String
    let creditsPurchased: Int
    let filename: String
    let isGiftCard: Bool
    let refundedAt: String?
    let refundStatus: String?
    let currency: String?
    let provider: String?
    let bankTransferReference: String?
    let transactionStatus: String?
    let documentStatus: String?

    var formattedAmount: String {
        let value = (Decimal(string: amount) ?? 0) / 100
        return "\(value) \((currency ?? "eur").uppercased())"
    }
    var displayStatus: String { documentStatus ?? transactionStatus ?? refundStatus ?? "" }
    static let fixture = Self(id: "fixture", orderId: nil, date: "2026-01-01", amount: "599", creditsPurchased: 1_000, filename: "Invoice.pdf", isGiftCard: false, refundedAt: nil, refundStatus: "none", currency: "eur", provider: "apple", bankTransferReference: nil, transactionStatus: nil, documentStatus: "ready")
}

private struct InvoicesListResponse: Decodable { let invoices: [BillingInvoice] }

private struct UsageSummaryResponse: Decodable { let summaries: [UsageSummary] }
private struct UsageDetailsResponse: Decodable { let entries: [UsageEntry] }
private struct DailyUsageResponse: Decodable { let days: [UsageDay] }

private struct UsageSummary: Decodable, Identifiable {
    let chatId: String?
    let appId: String?
    let apiKeyHash: String?
    let month: String
    let totalCredits: Double
    func identifier(fallback: String) -> String { chatId ?? appId ?? apiKeyHash ?? fallback }
    var id: String { "\(chatId ?? ""):\(appId ?? ""):\(apiKeyHash ?? ""):\(month)" }
    static func fixture(for tab: UsageTab) -> Self { Self(chatId: tab == .chats ? "fixture-chat" : nil, appId: tab == .apps ? "ai" : nil, apiKeyHash: tab == .api ? "fixture-key" : nil, month: "2026-01", totalCredits: 42) }
}

private struct UsageEntry: Decodable, Identifiable {
    let id: String
    let type: String
    let appId: String?
    let skillId: String?
    let credits: Double
    let createdAt: Int
    var displayName: String { [appId, skillId].compactMap { $0 }.joined(separator: " / ").nonEmpty ?? type }
}

private struct UsageDay: Decodable, Identifiable {
    let date: String
    let totalCredits: Double
    var id: String { date }
    static let fixture = Self(date: "2026-01-01", totalCredits: 42)
}

private struct GiftCardRecord: Decodable, Identifiable {
    let giftCardCode: String
    let creditsValue: Int
    var id: String { giftCardCode }
    var code: String { giftCardCode }
}
private struct RedeemedGiftCardsResponse: Decodable { let redeemedCards: [GiftCardRecord] }
private struct PurchasedGiftCardsResponse: Decodable { let purchasedCards: [GiftCardRecord] }
private struct RedeemGiftCardResponse: Decodable { let success: Bool; let creditsAdded: Int; let currentCredits: Int; let message: String }

private struct ReferralStatusResponse: Decodable {
    let available: Bool
    let referralCode: String?
    let successfulReferralsCount: Int
    let maxSuccessfulReferrals: Int
    let creditsPerReferrer: Int
    let creditsPerReferredUser: Int
    let minPurchaseAmountCents: Int
    let attributionExpiresDays: Int
    static let fixture = Self(available: true, referralCode: "OPENMATES", successfulReferralsCount: 1, maxSuccessfulReferrals: 5, creditsPerReferrer: 1_000, creditsPerReferredUser: 1_000, minPurchaseAmountCents: 100, attributionExpiresDays: 30)
}

private struct BankTransferOrder: Decodable {
    let orderId: String
    let reference: String
    let iban: String
    let bic: String
    let bankName: String
    let amountEur: String
    let expiresAt: String
}

private extension String { var nonEmpty: String? { isEmpty ? nil : self } }

private actor BillingService {
    static let shared = BillingService()

    func billingOverview() async throws -> BillingOverviewResponse {
        try await APIClient.shared.request(.get, path: "/v1/settings/billing")
    }

    func updateAutoTopUp(enabled: Bool, amount: Int, currency: String, email: String?) async throws {
        let _: Data = try await APIClient.shared.request(
            .post,
            path: "/v1/settings/auto-topup/low-balance",
            body: ["enabled": enabled, "threshold": 100, "amount": amount, "currency": currency, "email": email as Any]
        )
    }

    func invoices() async throws -> InvoicesListResponse {
        try await APIClient.shared.request(.get, path: "/v1/payments/invoices")
    }

    func dailyUsage() async throws -> DailyUsageResponse {
        try await APIClient.shared.request(.get, path: "/v1/settings/usage/daily-overview?days=30")
    }

    func usageSummaries(type: String) async throws -> UsageSummaryResponse {
        try await APIClient.shared.request(.get, path: "/v1/settings/usage/summaries?type=\(type)&months=3")
    }

    func usageDetails(type: String, summary: UsageSummary, unknownUsage: String) async throws -> UsageDetailsResponse {
        let rawIdentifier = summary.identifier(fallback: unknownUsage)
        let identifier = rawIdentifier.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? rawIdentifier
        return try await APIClient.shared.request(.get, path: "/v1/settings/usage/details?type=\(type)&identifier=\(identifier)&year_month=\(summary.month)")
    }

    func exportUsage() async throws -> URL {
        let data: Data = try await APIClient.shared.request(.get, path: "/v1/settings/usage/export?months=3")
        return try write(data, filename: "usage-export.csv")
    }

    func downloadInvoice(_ invoice: BillingInvoice, creditNote: Bool) async throws -> URL {
        let suffix = creditNote ? "/credit-note/download" : "/download"
        let data: Data = try await APIClient.shared.request(.get, path: "/v1/payments/invoices/\(invoice.id)\(suffix)")
        let filename = creditNote ? "CreditNote_\(invoice.id).pdf" : (invoice.filename.nonEmpty ?? "Invoice_\(invoice.id).pdf")
        return try write(data, filename: filename)
    }

    func redeemedGiftCards() async throws -> RedeemedGiftCardsResponse {
        try await APIClient.shared.request(.get, path: "/v1/payments/redeemed-gift-cards")
    }

    func purchasedGiftCards() async throws -> PurchasedGiftCardsResponse {
        try await APIClient.shared.request(.get, path: "/v1/payments/purchased-gift-cards")
    }

    func redeemGiftCard(code: String) async throws -> RedeemGiftCardResponse {
        try await APIClient.shared.request(.post, path: "/v1/payments/redeem-gift-card", body: ["code": code])
    }

    func createGiftCardTransfer(credits: Int, emailEncryptionKey: String) async throws -> BankTransferOrder {
        try await APIClient.shared.request(
            .post,
            path: "/v1/payments/create-gift-card-bank-transfer-order",
            body: [
                "credits_amount": credits,
                "currency": "eur",
                "email_encryption_key": emailEncryptionKey,
                "is_signup": false,
                "is_gift_card": true,
            ] as [String: Any]
        )
    }

    func referralStatus() async throws -> ReferralStatusResponse {
        try await APIClient.shared.request(.get, path: "/v1/referrals/status")
    }

    func createSupportTransfer(amount: Int, email: String) async throws -> BankTransferOrder {
        try await APIClient.shared.request(
            .post,
            path: "/v1/payments/create-support-bank-transfer-order",
            body: ["amount": amount, "currency": "eur", "support_email": email]
        )
    }

    private func write(_ data: Data, filename: String) throws -> URL {
        let safe = filename.replacingOccurrences(of: "/", with: "-")
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(safe)
        try data.write(to: url, options: .atomic)
        return url
    }
}

@MainActor
private func presentFile(_ url: URL) {
    #if os(iOS)
    let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
    guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
          let root = scene.windows.first?.rootViewController else { return }
    controller.popoverPresentationController?.sourceView = root.view
    root.present(controller, animated: true)
    #elseif os(macOS)
    let panel = NSSavePanel()
    panel.nameFieldStringValue = url.lastPathComponent
    guard panel.runModal() == .OK, let destination = panel.url else { return }
    try? FileManager.default.copyItem(at: url, to: destination)
    #endif
}
