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
}
