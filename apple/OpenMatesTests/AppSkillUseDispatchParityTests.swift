// Focused routing coverage for completed app-skill parent embeds that have no
// child records. Synthetic payloads contain no account or provider data.

import SwiftUI
import XCTest
@testable import OpenMates

final class AppSkillUseDispatchParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testCompletedParentSkillsChooseStructuredRenderersWithoutChildren() {
        let cases: [(String, String, AppSkillUseRenderer.SpecializedKind)] = [
            ("weather", "forecast", .weatherForecast),
            ("finance", "check_accounts", .financeCheckAccounts),
            ("music", "generate", .musicGenerate),
            ("videos", "generate", .videoGenerate),
            ("math", "calculate", .mathCalculate),
            ("travel", "get_flight", .travelFlight),
            ("reminder", "set-reminder", .reminder),
            ("reminder", "list-reminders", .reminder),
            ("reminder", "cancel-reminder", .reminder)
        ]

        for (appId, skillId, expected) in cases {
            let parent = EmbedRecord(
                id: "test-\(appId)-\(skillId)",
                type: "app:\(appId):\(skillId)",
                status: .finished,
                data: .raw([
                    "app_id": AnyCodable(appId),
                    "skill_id": AnyCodable(skillId),
                    "status": AnyCodable("finished")
                ]),
                parentEmbedId: nil,
                appId: appId,
                skillId: skillId,
                embedIds: nil,
                createdAt: nil
            )
            XCTAssertTrue(parent.childEmbedIds.isEmpty)
            XCTAssertEqual(
                AppSkillUseRenderer.specializedKind(appId: appId, skillId: skillId),
                expected,
                "\(appId)/\(skillId) must render its parent data without waiting for child hydration"
            )
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testUnrelatedSearchSkillsKeepTheirSearchRenderer() {
        XCTAssertNil(AppSkillUseRenderer.specializedKind(appId: "web", skillId: "search"))
        XCTAssertNil(AppSkillUseRenderer.specializedKind(appId: "images", skillId: "search"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testFlightParentUsesActualTrackingFields() {
        let data: [String: AnyCodable] = [
            "flight_number": AnyCodable("LH2472"),
            "actual_takeoff": AnyCodable("2026-06-03T09:15:00Z"),
            "actual_landing": AnyCodable("2026-06-03T11:05:00Z"),
            "tracks": AnyCodable([["lat": 48.1], ["lat": 50.1]]),
            "diverted": AnyCodable(true)
        ]
        let card = TravelFlightSkillCard(data: data, mode: .preview)
        XCTAssertEqual(card.flightNumber, "LH2472")
        XCTAssertEqual(card.trackCount, 2)
        XCTAssertTrue(card.diverted)
        XCTAssertEqual(card.takeoff, "2026-06-03T09:15:00Z")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testWeatherOnlyUsesLinkedChildRecords() {
        let parent = parent(appId: "weather", skillId: "forecast", payload: [:])
        let unrelated = EmbedRecord(
            id: "other-weather-day", type: "weather-day", status: .finished,
            data: .raw(["date": AnyCodable("2026-06-03")]),
            parentEmbedId: "different-forecast", appId: "weather", skillId: nil,
            embedIds: nil, createdAt: nil
        )
        XCTAssertTrue(AppSkillUseRenderer.linkedChildren(
            parent: parent,
            allRecords: [unrelated.id: unrelated]
        ).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testForecastIconSelectionMatchesWebMeteoconRules() {
        let cases: [(String?, String?, String)] = [
            ("wmo-95", nil, "thunderstorms-day-rain"),
            ("wmo-71", nil, "snow"),
            ("wmo-61", nil, "rain"),
            ("wmo-45", nil, "fog-day"),
            ("wmo-3", nil, "overcast"),
            ("wmo-2", nil, "partly-cloudy-day"),
            ("partly_cloudy_night", nil, "partly-cloudy-night"),
            (nil, "windy", "wind"),
            (nil, "clear night", "clear-night"),
            (nil, "clear", "clear-day")
        ]
        for (icon, condition, expected) in cases {
            XCTAssertEqual(WeatherForecastSkillCard.meteoconSlug(icon: icon, condition: condition), expected)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testEncrypted3DPosterAndProviderURLValidation() {
        let payload: [String: AnyCodable] = [
            "s3_base_url": AnyCodable("https://assets.example.org"),
            "aes_key": AnyCodable("test-key"),
            "files": AnyCodable(["poster": ["s3_key": "posters/example.enc", "aes_nonce": "test-nonce"]])
        ]
        let poster = Models3DGenerateEmbedRenderer.encryptedPoster(from: payload)
        XCTAssertEqual(poster?.s3Key, "posters/example.enc")
        XCTAssertEqual(poster?.nonce, "test-nonce")
        XCTAssertEqual(Models3DResultEmbedRenderer.providerURL("https://provider.example.org/model")?.host, "provider.example.org")
        XCTAssertNil(Models3DResultEmbedRenderer.providerURL("javascript:alert(1)"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testFinanceCounterpartyStaysRedactedUntilSharedRevealIsOn() {
        let transaction: [String: Any] = [
            "counterparty_placeholder": "[MERCHANT_SOFTWARE_001]",
            "counterparty": "Never read this provider field"
        ]
        let mapping = PIIMapping(
            placeholder: "[MERCHANT_SOFTWARE_001]",
            original: "Synthetic Vendor",
            type: "MERCHANT_SOFTWARE"
        )
        XCTAssertEqual(
            FinanceCheckAccountsSkillCard.counterpartyLabel(
                in: transaction, mappings: [mapping], revealed: false
            ),
            "[MERCHANT_SOFTWARE_001]"
        )
        XCTAssertEqual(
            FinanceCheckAccountsSkillCard.counterpartyLabel(
                in: transaction, mappings: [mapping], revealed: true
            ),
            "Synthetic Vendor"
        )
        XCTAssertEqual(
            FinanceCheckAccountsSkillCard.counterpartyLabel(
                in: transaction, mappings: [], revealed: true
            ),
            "[MERCHANT_SOFTWARE_001]"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testRepresentativeCompletedParentsRenderInBothModes() {
        let examples: [(String, String, [String: AnyCodable])] = [
            ("math", "calculate", ["results": AnyCodable([["expression": "2+2", "result": "4"]])]),
            ("reminder", "set-reminder", ["prompt": AnyCodable("Review changes"), "trigger_at_formatted": AnyCodable("Tomorrow")]),
            ("travel", "get_flight", ["flight_number": AnyCodable("LH2472"), "actual_takeoff": AnyCodable("2026-06-03T09:15:00Z")]),
            ("finance", "check_accounts", ["overview": AnyCodable(["accounts": [["account_ref": "A1", "currency": "EUR", "balance": 100.0]], "transactions": [["counterparty_placeholder": "MERCHANT_001", "amount": 20.0, "direction": "expense", "posted_at": "2026-06-03"]]])])
        ]
        for (appId, skillId, payload) in examples {
            let record = parent(appId: appId, skillId: skillId, payload: payload)
            for mode in [EmbedDisplayMode.preview, .fullscreen] {
                let view = AppSkillUseRenderer(embed: record, allEmbedRecords: [record.id: record], mode: mode)
                    .frame(width: 420, height: mode == .preview ? 200 : 600)
                XCTAssertNotNil(ImageRenderer(content: view).uiImage, "\(appId)/\(skillId) \(mode) failed to render")
            }
        }
    }

    private func parent(appId: String, skillId: String, payload: [String: AnyCodable]) -> EmbedRecord {
        var data = payload
        data["app_id"] = AnyCodable(appId)
        data["skill_id"] = AnyCodable(skillId)
        return EmbedRecord(
            id: "test-\(appId)-\(skillId)", type: "app:\(appId):\(skillId)", status: .finished,
            data: .raw(data), parentEmbedId: nil, appId: appId, skillId: skillId,
            embedIds: nil, createdAt: nil
        )
    }
}
