// Unit coverage for native settings and billing parity guardrails.
// These tests use static product metadata only and never touch StoreKit purchases,
// payment methods, invoices, customer IDs, private accounts, or network state.

import XCTest
@testable import OpenMates

@MainActor
final class SettingsBillingParityTests: XCTestCase {
    func testAppleCreditProductsMatchKnownCreditTiers() {
        XCTAssertEqual(
            StoreManager.productIDs,
            [
                "org.openmates.credits.1000",
                "org.openmates.credits.10000",
                "org.openmates.credits.21000",
                "org.openmates.credits.54000",
            ]
        )
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.1000"], 1_000)
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.10000"], 10_000)
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.21000"], 21_000)
        XCTAssertEqual(StoreManager.creditsByProductID["org.openmates.credits.54000"], 54_000)
    }

    func testBillingOverviewDecodesCurrentBackendSchema() throws {
        let response: BillingOverviewResponse = try decode(
            """
            {
              "payment_tier": 2,
              "auto_topup_enabled": true,
              "auto_topup_threshold": 100,
              "auto_topup_amount": 10000,
              "auto_topup_currency": "eur",
              "invoices": []
            }
            """
        )

        XCTAssertEqual(response.paymentTier, 2)
        XCTAssertTrue(response.autoTopupEnabled)
        XCTAssertEqual(response.autoTopupThreshold, 100)
        XCTAssertEqual(response.autoTopupAmount, 10_000)
    }

    func testInvoiceListDecodesReadyAndPendingDocuments() throws {
        let response: InvoicesListResponse = try decode(
            """
            {
              "invoices": [
                {
                  "id": "invoice-1", "date": "2026-07-01", "amount": "599",
                  "credits_purchased": 1000, "filename": "Invoice.pdf",
                  "is_gift_card": false, "currency": "eur", "provider": "apple",
                  "document_status": "ready"
                },
                {
                  "id": "bt-1", "order_id": "bt-1", "date": "2026-07-02",
                  "amount": "599", "credits_purchased": 1000, "filename": "",
                  "is_gift_card": false, "currency": "eur", "provider": "bank_transfer",
                  "bank_transfer_reference": "OM-TEST", "transaction_status": "pending",
                  "document_status": "pending_bank_transfer"
                }
              ]
            }
            """
        )

        XCTAssertEqual(response.invoices.count, 2)
        XCTAssertEqual(response.invoices[0].documentStatus, "ready")
        XCTAssertEqual(response.invoices[1].bankTransferReference, "OM-TEST")
    }

    func testUsageResponsesDecodeCurrentEnvelopesAndOptionalPrivateFields() throws {
        let summaries: UsageSummaryResponse = try decode(
            """
            {"summaries":[{"app_id":"ai","month":"2026-07","total_credits":12.5}]}
            """
        )
        let details: UsageDetailsResponse = try decode(
            """
            {"entries":[{"id":"usage-1","type":"skill_execution","app_id":"ai","credits":null,"created_at":null}]}
            """
        )
        let daily: DailyUsageResponse = try decode(
            """
            {"days":[{"date":"2026-07-01","total_credits":12.5,"items":[]}]}
            """
        )

        XCTAssertEqual(summaries.summaries.first?.identifier, "ai")
        XCTAssertNil(details.entries.first?.credits)
        XCTAssertEqual(daily.days.first?.totalCredits, 12.5)
    }

    private func decode<T: Decodable>(_ json: String) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: Data(json.utf8))
    }
}
