// Full billing hub — buy credits via Apple In-App Purchase, invoices, auto top-up.
// Uses StoreKit 2 for native Apple payment. Credits are consumable products fulfilled
// by the backend after Apple transaction verification.

import SwiftUI
import StoreKit

struct SettingsBillingView: View {
    @State private var balance: Double = 0
    @State private var isLoading = true

    var body: some View {
        List {
            Section("Balance") {
                HStack {
                    Text("Credits")
                        .font(.omP)
                    Spacer()
                    Text(String(format: "%.4f", balance))
                        .font(.system(.body, design: .monospaced))
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.buttonPrimary)
                }
            }

            Section("Top Up") {
                NavigationLink {
                    BuyCreditsView()
                } label: {
                    Label("Buy Credits", systemImage: "creditcard")
                }

                NavigationLink {
                    AutoTopUpView()
                } label: {
                    Label("Auto Top-Up", systemImage: "arrow.triangle.2.circlepath")
                }
            }

            Section("History") {
                NavigationLink {
                    PurchaseHistoryView()
                } label: {
                    Label("Purchase History", systemImage: "clock.arrow.circlepath")
                }

                NavigationLink {
                    InvoicesView()
                } label: {
                    Label("Invoices", systemImage: "doc.text")
                }

                NavigationLink {
                    SettingsGiftCardsView()
                } label: {
                    Label("Gift Cards", systemImage: "gift")
                }
            }
        }
        .navigationTitle("Billing")
        .task { await loadBalance() }
        .onReceive(NotificationCenter.default.publisher(for: .paymentCompleted)) { _ in
            Task { await loadBalance() }
        }
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
        isLoading = false
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
                        Text("Purchase Complete!")
                            .font(.omH4).fontWeight(.semibold)
                        if credits > 0 {
                            Text("\(credits.formatted()) credits added to your balance")
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                        Button("Done") {
                            storeManager.resetState()
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(Color.buttonPrimary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, .spacing6)
                }

            default:
                Section {
                    Text("Credits are used for AI requests. Choose a package below.")
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                }

                Section("Credit Packages") {
                    if storeManager.products.isEmpty {
                        HStack {
                            ProgressView()
                            Text("Loading products...")
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
                            Text("Processing purchase...")
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }

                if storeManager.purchaseState == .verifying {
                    Section {
                        HStack {
                            ProgressView()
                            Text("Verifying with server...")
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
                    Button("Restore Purchases") {
                        Task { await storeManager.restorePurchases() }
                    }
                    .font(.omSmall)
                }
            }
        }
        .navigationTitle("Buy Credits")
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
                        Text("Best Value")
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
                    Text("No purchase history")
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
        .navigationTitle("Purchase History")
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
            Section("Low Balance Auto Top-Up") {
                Toggle("Enable", isOn: $isLowBalanceEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: isLowBalanceEnabled) { _, _ in save() }

                if isLowBalanceEnabled {
                    HStack {
                        Text("When below")
                        Spacer()
                        Text(String(format: "%.1f credits", lowBalanceThreshold))
                            .foregroundStyle(Color.fontSecondary)
                    }

                    Picker("Top-up package", selection: $lowBalanceProductID) {
                        ForEach(StoreManager.productIDs, id: \.self) { productID in
                            let credits = StoreManager.creditsByProductID[productID] ?? 0
                            Text("\(credits.formatted()) credits").tag(productID)
                        }
                    }
                    .onChange(of: lowBalanceProductID) { _, _ in save() }

                    Text("When your balance drops below the threshold, the selected credit package will be purchased automatically.")
                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                }
            }

            Section("Monthly Auto Top-Up") {
                Toggle("Enable", isOn: $isMonthlyEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: isMonthlyEnabled) { _, _ in save() }

                if isMonthlyEnabled {
                    Picker("Monthly package", selection: $monthlyProductID) {
                        ForEach(StoreManager.productIDs, id: \.self) { productID in
                            let credits = StoreManager.creditsByProductID[productID] ?? 0
                            Text("\(credits.formatted()) credits").tag(productID)
                        }
                    }
                    .onChange(of: monthlyProductID) { _, _ in save() }

                    Text("A credit package will be purchased on the first of each month.")
                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                }
            }
        }
        .navigationTitle("Auto Top-Up")
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
                    Text("No invoices yet")
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
                }
            }
        }
        .navigationTitle("Invoices")
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
