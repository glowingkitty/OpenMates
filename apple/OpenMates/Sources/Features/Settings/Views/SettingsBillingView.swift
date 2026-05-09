// Full billing hub — buy credits via Apple In-App Purchase, invoices, auto top-up.
// Uses StoreKit 2 for native Apple payment. Credits are consumable products fulfilled
// by the backend after Apple transaction verification.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsBilling.svelte
//          frontend/packages/ui/src/components/settings/billing/SettingsBuyCredits.svelte
//          frontend/packages/ui/src/components/settings/billing/SettingsInvoices.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import StoreKit

struct SettingsBillingView: View {
    private enum BillingRoute: String {
        case buyCredits
        case autoTopUp
        case invoices
        case giftCards
    }

    @State private var balance: Double = 0
    @State private var usageCredits: Double = 0
    @State private var usageMessages: Int = 0
    @State private var route: BillingRoute?

    var body: some View {
        Group {
            if let route {
                billingSubview(route)
            } else {
                billingHub
            }
        }
        .task { await loadBillingHub() }
        .onReceive(NotificationCenter.default.publisher(for: .paymentCompleted)) { _ in
            Task { await loadBillingHub() }
        }
    }

    private var billingHub: some View {
        OMSettingsPage(title: AppStrings.settingsBilling, showsHeader: false) {
            billingBalanceDisplay

            OMSettingsSection {
                OMSettingsRow(title: AppStrings.buyCredits, icon: "coins") {
                    route = .buyCredits
                }
                OMSettingsRow(title: AppStrings.autoTopUp, icon: "reload") {
                    route = .autoTopUp
                }
                OMSettingsRow(title: AppStrings.invoices, icon: "document") {
                    route = .invoices
                }
                OMSettingsRow(title: AppStrings.giftCards, icon: "gift") {
                    route = .giftCards
                }
            }

            billingDivider

            OMSettingsSection(AppStrings.usage, icon: "usage") {
                OMSettingsStaticRow(
                    title: LocalizationManager.shared.text("settings.usage.total_credits_label"),
                    value: formattedDecimal(usageCredits)
                )
                OMSettingsStaticRow(
                    title: LocalizationManager.shared.text("settings.server_stats.messages"),
                    value: "\(usageMessages)"
                )
            }
        }
    }

    @ViewBuilder
    private func billingSubview(_ route: BillingRoute) -> some View {
        VStack(spacing: 0) {
            Button {
                self.route = nil
            } label: {
                HStack(spacing: .spacing3) {
                    Icon("back", size: 20)
                        .foregroundStyle(Color.fontSecondary)
                    Text(AppStrings.settingsBilling)
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)
                    Spacer()
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing5)
                .background(Color.grey20)
            }
            .buttonStyle(.plain)

            switch route {
            case .buyCredits:
                BuyCreditsView()
            case .autoTopUp:
                AutoTopUpView()
            case .invoices:
                InvoicesView()
            case .giftCards:
                SettingsGiftCardsView()
            }
        }
    }

    private var billingBalanceDisplay: some View {
        VStack(alignment: .center, spacing: 0) {
            HStack(spacing: .spacing5) {
                Icon("coins", size: 28)
                    .foregroundStyle(Color.grey90)

                Text(formatCredits(Int(balance)))
                    .font(.omH2.weight(.semibold))
                    .foregroundStyle(Color.grey100)
                    .monospacedDigit()

                Text(AppStrings.credits)
                    .font(.omSmall)
                    .foregroundStyle(Color.grey60)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, .spacing10)
            .padding(.horizontal, .spacing6)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .shadow(color: .black.opacity(0.10), radius: 2, x: 0, y: 1)
        }
        .padding(.horizontal, .spacing5)
        .padding(.top, .spacing5)
        .padding(.bottom, .spacing4)
        .accessibilityElement(children: .combine)
        .accessibleSetting(AppStrings.credits, value: formatCredits(Int(balance)))
    }

    private var billingDivider: some View {
        Rectangle()
            .fill(Color.grey25)
            .frame(height: 1)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing6)
    }

    private func loadBillingHub() async {
        await loadBalance()
        await loadUsage()
    }

    private func loadBalance() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/billing"
            )
            balance = response["credits"]?.value as? Double ?? 0
        } catch {
            print("[Settings] Billing load error: \(error)")
        }
    }

    private func loadUsage() async {
        do {
            let data: [String: AnyCodable] = try await APIClient.shared.request(.get, path: "/v1/settings/usage")
            usageCredits = data["total_credits_used"]?.value as? Double ?? 0
            usageMessages = data["message_count"]?.value as? Int ?? 0
        } catch {
            print("[Settings] Billing usage load error: \(error)")
        }
    }

    private func formatCredits(_ credits: Int) -> String {
        credits.formatted(.number.grouping(.automatic))
    }

    private func formattedDecimal(_ value: Double) -> String {
        String(format: "%.4f", value)
    }
}

// MARK: - Buy Credits (StoreKit 2 native purchase)

struct BuyCreditsView: View {
    @StateObject private var storeManager = StoreManager.shared

    var body: some View {
        List {
            switch storeManager.purchaseState {
            case .success(let credits):
                Section {
                    VStack(spacing: .spacing4) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 40))
                            .foregroundStyle(.green)
                        Text(LocalizationManager.shared.text("settings.billing.purchase_complete"))
                            .font(.omH4).fontWeight(.semibold)
                        if credits > 0 {
                            Text("\(credits.formatted()) \(LocalizationManager.shared.text("settings.billing.credits_added"))")
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                        Button(AppStrings.done) {
                            storeManager.resetState()
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(Color.buttonPrimary)
                        .accessibleButton(AppStrings.done, hint: LocalizationManager.shared.text("settings.billing.done_hint"))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, .spacing6)
                }

            default:
                Section {
                    Text(LocalizationManager.shared.text("settings.billing.credits_description"))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                }

                Section(LocalizationManager.shared.text("settings.billing.credit_packages")) {
                    if storeManager.products.isEmpty {
                        HStack {
                            ProgressView()
                            Text(LocalizationManager.shared.text("settings.billing.loading_products"))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    } else {
                        ForEach(storeManager.products, id: \.id) { product in
                            CreditProductRow(
                                product: product,
                                isPurchasing: storeManager.purchaseState == .purchasing ||
                                              storeManager.purchaseState == .verifying
                            ) {
                                Task { await storeManager.purchase(product) }
                            }
                        }
                    }
                }

                if storeManager.purchaseState == .purchasing {
                    Section {
                        HStack {
                            ProgressView()
                            Text(LocalizationManager.shared.text("settings.billing.processing_purchase"))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }

                if storeManager.purchaseState == .verifying {
                    Section {
                        HStack {
                            ProgressView()
                            Text(LocalizationManager.shared.text("settings.billing.verifying_with_server"))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }

                if let error = storeManager.lastError {
                    Section {
                        Text(error)
                            .font(.omSmall).foregroundStyle(Color.error)
                    }
                }

                Section {
                    Button(LocalizationManager.shared.text("settings.billing.restore_purchases")) {
                        Task { await storeManager.restorePurchases() }
                    }
                    .font(.omSmall)
                    .accessibleButton(
                        LocalizationManager.shared.text("settings.billing.restore_purchases"),
                        hint: LocalizationManager.shared.text("settings.billing.restore_hint")
                    )
                }
            }
        }
        .navigationTitle(AppStrings.buyCredits)
        .task { await storeManager.loadProducts() }
    }
}

// MARK: - Credit product row

struct CreditProductRow: View {
    let product: Product
    let isPurchasing: Bool
    let onPurchase: () -> Void

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack(spacing: .spacing3) {
                    Text("\(product.formattedCredits) credits")
                        .font(.omP).fontWeight(.semibold)

                    if product.isRecommended {
                        Text(LocalizationManager.shared.text("settings.billing.best_value"))
                            .font(.omTiny).fontWeight(.bold)
                            .foregroundStyle(.white)
                            .padding(.horizontal, .spacing2)
                            .padding(.vertical, 2)
                            .background(Color.buttonPrimary)
                            .clipShape(RoundedRectangle(cornerRadius: .radius1))
                    }
                }

                if product.creditsAmount >= 10_000 {
                    let bonusCredits: Int = switch product.creditsAmount {
                    case 10_000: 500
                    case 21_000: 1_000
                    case 54_000: 3_000
                    default: 0
                    }
                    if bonusCredits > 0 {
                        Text("+\(bonusCredits) bonus with monthly auto top-up")
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                }
            }

            Spacer()

            Button {
                onPurchase()
            } label: {
                Text(product.displayPrice)
                    .font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(.white)
                    .padding(.horizontal, .spacing4)
                    .padding(.vertical, .spacing2)
                    .background(Color.buttonPrimary)
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
            .disabled(isPurchasing)
            .buttonStyle(.plain)
            .accessibleButton(
                "\(product.displayPrice) — \(product.formattedCredits) credits",
                hint: LocalizationManager.shared.text("settings.billing.buy_hint")
            )
        }
        .padding(.vertical, .spacing2)
    }
}

// MARK: - Purchase History

struct PurchaseHistoryView: View {
    @State private var transactions: [TransactionRecord] = []
    @State private var isLoading = true

    struct TransactionRecord: Identifiable {
        let id: UInt64
        let productID: String
        let credits: Int
        let purchaseDate: Date
        let price: String
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if transactions.isEmpty {
                Section {
                    Text(LocalizationManager.shared.text("settings.billing.no_purchase_history"))
                        .foregroundStyle(Color.fontSecondary)
                }
            } else {
                ForEach(transactions) { tx in
                    HStack {
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text("\(tx.credits.formatted()) credits")
                                .font(.omSmall).fontWeight(.medium)
                            Text(tx.purchaseDate.formatted(date: .abbreviated, time: .shortened))
                                .font(.omXs).foregroundStyle(Color.fontTertiary)
                        }
                        Spacer()
                        Text(tx.price)
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                }
            }
        }
        .navigationTitle(AppStrings.purchaseHistory)
        .task { await loadHistory() }
    }

    private func loadHistory() async {
        var records: [TransactionRecord] = []

        for await result in Transaction.all {
            if case .verified(let transaction) = result {
                let credits = StoreManager.creditsByProductID[transaction.productID] ?? 0
                records.append(TransactionRecord(
                    id: transaction.id,
                    productID: transaction.productID,
                    credits: credits,
                    purchaseDate: transaction.purchaseDate,
                    price: transaction.productID
                ))
            }
        }

        transactions = records.sorted { $0.purchaseDate > $1.purchaseDate }
        isLoading = false
    }
}

// MARK: - Auto Top-Up

struct AutoTopUpView: View {
    @State private var isLowBalanceEnabled = false
    @State private var lowBalanceThreshold: Double = 1.0
    @State private var lowBalanceProductID = "org.openmates.credits.10000"
    @State private var isMonthlyEnabled = false
    @State private var monthlyProductID = "org.openmates.credits.10000"
    @State private var isLoading = true

    var body: some View {
        List {
            Section(LocalizationManager.shared.text("settings.billing.low_balance_auto_topup")) {
                Toggle(AppStrings.enabled, isOn: $isLowBalanceEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: isLowBalanceEnabled) { _, _ in save() }
                    .accessibleToggle(LocalizationManager.shared.text("settings.billing.low_balance_auto_topup"), isOn: isLowBalanceEnabled)

                if isLowBalanceEnabled {
                    HStack {
                        Text(LocalizationManager.shared.text("settings.billing.when_below"))
                        Spacer()
                        Text(String(format: "%.1f credits", lowBalanceThreshold))
                            .foregroundStyle(Color.fontSecondary)
                    }

                    Picker(LocalizationManager.shared.text("settings.billing.topup_package"), selection: $lowBalanceProductID) {
                        ForEach(StoreManager.productIDs, id: \.self) { productID in
                            let credits = StoreManager.creditsByProductID[productID] ?? 0
                            Text("\(credits.formatted()) credits").tag(productID)
                        }
                    }
                    .onChange(of: lowBalanceProductID) { _, _ in save() }

                    Text(LocalizationManager.shared.text("settings.billing.low_balance_description"))
                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                }
            }

            Section(LocalizationManager.shared.text("settings.billing.monthly_auto_topup")) {
                Toggle(AppStrings.enabled, isOn: $isMonthlyEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: isMonthlyEnabled) { _, _ in save() }
                    .accessibleToggle(LocalizationManager.shared.text("settings.billing.monthly_auto_topup"), isOn: isMonthlyEnabled)

                if isMonthlyEnabled {
                    Picker(LocalizationManager.shared.text("settings.billing.monthly_package"), selection: $monthlyProductID) {
                        ForEach(StoreManager.productIDs, id: \.self) { productID in
                            let credits = StoreManager.creditsByProductID[productID] ?? 0
                            Text("\(credits.formatted()) credits").tag(productID)
                        }
                    }
                    .onChange(of: monthlyProductID) { _, _ in save() }

                    Text(LocalizationManager.shared.text("settings.billing.monthly_description"))
                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                }
            }
        }
        .navigationTitle(AppStrings.autoTopUp)
        .task { await loadSettings() }
    }

    private func loadSettings() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/billing/auto-topup"
            )
            isLowBalanceEnabled = response["low_balance_enabled"]?.value as? Bool ?? false
            lowBalanceThreshold = response["low_balance_threshold"]?.value as? Double ?? 1.0
            lowBalanceProductID = response["low_balance_product_id"]?.value as? String ?? "org.openmates.credits.10000"
            isMonthlyEnabled = response["monthly_enabled"]?.value as? Bool ?? false
            monthlyProductID = response["monthly_product_id"]?.value as? String ?? "org.openmates.credits.10000"
        } catch {
            print("[Settings] Auto top-up load error: \(error)")
        }
        isLoading = false
    }

    private func save() {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/billing/auto-topup",
                body: [
                    "low_balance_enabled": isLowBalanceEnabled,
                    "low_balance_threshold": lowBalanceThreshold,
                    "low_balance_product_id": lowBalanceProductID,
                    "monthly_enabled": isMonthlyEnabled,
                    "monthly_product_id": monthlyProductID,
                ] as [String: Any]
            ) as Data
        }
    }
}

// MARK: - Invoices

struct InvoicesView: View {
    @State private var invoices: [Invoice] = []
    @State private var isLoading = true

    struct Invoice: Identifiable, Decodable {
        let id: String
        let amount: Double?
        let currency: String?
        let status: String?
        let createdAt: String?
        let pdfUrl: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if invoices.isEmpty {
                Section {
                    Text(LocalizationManager.shared.text("settings.billing.no_invoices"))
                        .foregroundStyle(Color.fontSecondary)
                }
            } else {
                ForEach(invoices) { invoice in
                    HStack {
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(String(format: "%@ %.2f", invoice.currency?.uppercased() ?? "USD", invoice.amount ?? 0))
                                .font(.omSmall).fontWeight(.medium)
                            if let date = invoice.createdAt {
                                Text(date)
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        Spacer()
                        if let status = invoice.status {
                            Text(status.capitalized)
                                .font(.omTiny).fontWeight(.medium)
                                .foregroundStyle(status == "paid" ? .green : Color.fontSecondary)
                                .padding(.horizontal, .spacing2)
                                .padding(.vertical, 2)
                                .background(status == "paid" ? Color.green.opacity(0.1) : Color.grey10)
                                .clipShape(RoundedRectangle(cornerRadius: .radius1))
                        }
                        if invoice.pdfUrl != nil {
                            Image(systemName: "arrow.down.doc")
                                .foregroundStyle(Color.buttonPrimary)
                                .accessibilityHidden(true)
                        }
                    }
                    .contentShape(Rectangle())
                    .onTapGesture {
                        if let url = invoice.pdfUrl, let downloadURL = URL(string: url) {
                            #if os(iOS)
                            UIApplication.shared.open(downloadURL)
                            #elseif os(macOS)
                            NSWorkspace.shared.open(downloadURL)
                            #endif
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel({
                        let amount = String(format: "%@ %.2f", invoice.currency?.uppercased() ?? "USD", invoice.amount ?? 0)
                        let status = invoice.status?.capitalized ?? ""
                        let date = invoice.createdAt ?? ""
                        return "\(amount), \(status), \(date)"
                    }())
                    .accessibilityHint(invoice.pdfUrl != nil ? LocalizationManager.shared.text("settings.billing.tap_to_download") : "")
                    .accessibilityAddTraits(invoice.pdfUrl != nil ? .isButton : [])
                }
            }
        }
        .navigationTitle(AppStrings.invoices)
        .task { await loadInvoices() }
    }

    private func loadInvoices() async {
        do {
            invoices = try await APIClient.shared.request(
                .get, path: "/v1/settings/billing/invoices"
            )
        } catch {
            print("[Settings] Invoices load error: \(error)")
        }
        isLoading = false
    }
}
