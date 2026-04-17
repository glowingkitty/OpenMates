// StoreKit 2 purchase manager — handles in-app credit purchases via Apple's payment system.
// Products are consumable (credits are added to the user's balance on purchase).
// Transaction verification uses StoreKit 2's built-in JWS verification, then the
// signed transaction is forwarded to the backend for credit fulfillment.

import StoreKit
import SwiftUI

@MainActor
final class StoreManager: ObservableObject {
    static let shared = StoreManager()

    @Published private(set) var products: [Product] = []
    @Published private(set) var purchaseState: PurchaseState = .idle
    @Published private(set) var lastError: String?

    enum PurchaseState: Equatable {
        case idle
        case loading
        case purchasing
        case verifying
        case success(credits: Int)
        case failed(String)
    }

    private var transactionListener: Task<Void, Never>?

    private init() {
        transactionListener = listenForTransactions()
    }

    deinit {
        transactionListener?.cancel()
    }

    // MARK: - Product IDs mapped to credit tiers from pricing.yml

    static let productIDs: [String] = [
        "org.openmates.credits.1000",
        "org.openmates.credits.10000",
        "org.openmates.credits.21000",
        "org.openmates.credits.54000",
    ]

    static let creditsByProductID: [String: Int] = [
        "org.openmates.credits.1000": 1_000,
        "org.openmates.credits.10000": 10_000,
        "org.openmates.credits.21000": 21_000,
        "org.openmates.credits.54000": 54_000,
    ]

    // MARK: - Load products from App Store

    func loadProducts() async {
        purchaseState = .loading
        lastError = nil

        do {
            let storeProducts = try await Product.products(for: Self.productIDs)
            products = storeProducts.sorted { $0.price < $1.price }
            purchaseState = .idle
        } catch {
            lastError = "Failed to load products: \(error.localizedDescription)"
            purchaseState = .failed(lastError!)
        }
    }

    // MARK: - Purchase

    func purchase(_ product: Product) async {
        purchaseState = .purchasing
        lastError = nil

        do {
            let result = try await product.purchase()

            switch result {
            case .success(let verification):
                let transaction = try checkVerified(verification)
                purchaseState = .verifying

                // Send the signed transaction to our backend for credit fulfillment
                let credits = Self.creditsByProductID[product.id] ?? 0
                await fulfillOnBackend(transaction: transaction, productID: product.id, credits: credits)

                await transaction.finish()
                purchaseState = .success(credits: credits)

            case .userCancelled:
                purchaseState = .idle

            case .pending:
                purchaseState = .idle
                lastError = "Purchase is pending approval (e.g. Ask to Buy)."

            @unknown default:
                purchaseState = .idle
            }
        } catch {
            lastError = error.localizedDescription
            purchaseState = .failed(lastError!)
        }
    }

    // MARK: - Restore purchases (for unfinished transactions)

    func restorePurchases() async {
        purchaseState = .loading
        var restoredCount = 0

        for await result in Transaction.unfinished {
            do {
                let transaction = try checkVerified(result)
                let credits = Self.creditsByProductID[transaction.productID] ?? 0
                await fulfillOnBackend(
                    transaction: transaction,
                    productID: transaction.productID,
                    credits: credits
                )
                await transaction.finish()
                restoredCount += 1
            } catch {
                print("[StoreKit] Failed to restore transaction: \(error)")
            }
        }

        if restoredCount > 0 {
            purchaseState = .success(credits: 0)
        } else {
            purchaseState = .idle
        }
    }

    // MARK: - Transaction listener (handles interrupted purchases, renewals)

    private func listenForTransactions() -> Task<Void, Never> {
        Task.detached { [weak self] in
            for await result in Transaction.updates {
                do {
                    let transaction = try self?.checkVerified(result)
                    if let transaction {
                        let credits = Self.creditsByProductID[transaction.productID] ?? 0
                        await self?.fulfillOnBackend(
                            transaction: transaction,
                            productID: transaction.productID,
                            credits: credits
                        )
                        await transaction.finish()
                    }
                } catch {
                    print("[StoreKit] Transaction listener error: \(error)")
                }
            }
        }
    }

    // MARK: - Verification

    private func checkVerified<T>(_ result: VerificationResult<T>) throws -> T {
        switch result {
        case .unverified(_, let error):
            throw StoreError.verificationFailed(error.localizedDescription)
        case .verified(let safe):
            return safe
        }
    }

    // MARK: - Backend fulfillment

    private func fulfillOnBackend(transaction: Transaction, productID: String, credits: Int) async {
        do {
            let body: [String: Any] = [
                "transaction_id": String(transaction.id),
                "original_transaction_id": String(transaction.originalID),
                "product_id": productID,
                "credits": credits,
                "environment": transaction.environment.rawValue,
                "signed_date": ISO8601DateFormatter().string(from: transaction.signedDate),
                "storefront": transaction.storefrontCountryCode,
            ]

            let _: Data = try await APIClient.shared.request(
                .post, path: "/v1/payments/apple/verify-transaction",
                body: body
            )
        } catch {
            print("[StoreKit] Backend fulfillment error: \(error)")
            lastError = "Credits purchased but fulfillment delayed. They will sync shortly."
        }
    }

    // MARK: - Helpers

    func resetState() {
        purchaseState = .idle
        lastError = nil
    }
}

// MARK: - Errors

enum StoreError: LocalizedError {
    case verificationFailed(String)
    case productNotFound

    var errorDescription: String? {
        switch self {
        case .verificationFailed(let reason):
            return "Transaction verification failed: \(reason)"
        case .productNotFound:
            return "Product not found in the App Store."
        }
    }
}

// MARK: - Product extension for display

extension Product {
    var creditsAmount: Int {
        StoreManager.creditsByProductID[id] ?? 0
    }

    var formattedCredits: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.groupingSeparator = "."
        return formatter.string(from: NSNumber(value: creditsAmount)) ?? "\(creditsAmount)"
    }

    var isRecommended: Bool {
        id == "org.openmates.credits.21000"
    }
}
