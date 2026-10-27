// Unit coverage for native settings and billing parity guardrails.
// These tests use static product metadata only and never touch StoreKit purchases,
// payment methods, invoices, customer IDs, private accounts, or network state.

import XCTest
import CryptoKit
import SwiftData
@testable import OpenMates

@MainActor
final class SettingsBillingParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=billing.documents.visible-downloadable,billing.bank-transfer.pending-visible
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

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete,billing.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete
    func testOverviewPreservesEveryContextOnceAndReconcilesDayCredits() async throws {
        let model = BillingUsageModel()
        await model.load(tab: .overview, accountID: nil, fixture: true)
        let day = try XCTUnwrap(model.groups.first)
        XCTAssertEqual(day.rows.count, 9)
        XCTAssertEqual(Set(day.rows.map(\.id)).count, 9)
        XCTAssertEqual(day.rows.reduce(0) { $0 + $1.credits }, day.credits)
        XCTAssertEqual(day.rows.filter { $0.identifier == "usage-overview-chat-row" }.count, 2)
        XCTAssertEqual(day.rows.filter { $0.identifier == "usage-overview-workflow-row" }.count, 2)
        XCTAssertEqual(day.rows.filter { $0.identifier == "usage-overview-api-device-row" }.count, 2)
        XCTAssertTrue(day.rows.first { $0.identifier == "usage-overview-app-row" }?.subtitle.contains(AppStrings.usageInterruptedRecording) == true)
        XCTAssertNil(day.rows.first { $0.identifier == "usage-overview-other-row" }?.chatID)
        XCTAssertTrue(model.hasMore)
        await model.load(tab: .overview, accountID: nil, more: true, fixture: true)
        XCTAssertEqual(model.groups.count, 2)
        XCTAssertEqual(model.loadedDays, 14)
        XCTAssertFalse(model.hasMore)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.receipt-token-breakdown,billing.surface.semantic-parity
    func testUsageEntryReceiptPreservesDecimalsAndReconcilesInputComposition() throws {
        let entries = try BillingUsageModel.decode(UsageDetailsResponse.self, Data(BillingUsageModel.fixtureEntries.utf8)).entries
        let entry = try XCTUnwrap(entries.first)
        XCTAssertEqual(entry.appSkillTokens, 400)
        XCTAssertEqual((entry.systemPromptTokens ?? 0) + (entry.userInputTokens ?? 0) + (entry.appSkillTokens ?? 0), entry.inputTokens)
        XCTAssertEqual(entry.llmUsageBreakdown?.rawCredits.text, "11.6000")
        XCTAssertEqual(entry.llmUsageBreakdown?.roundingAdjustment.text, "0.4000")
        XCTAssertEqual(entry.llmUsageBreakdown?.creditsCharged, 12)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete,billing.surface.semantic-parity
    func testMonthlySpeechGroupsOnlySameMessageAndRetainsKnownCharges() throws {
        let response: UsageDetailsResponse = try decode("""
        {"entries":[
          {"id":"speech-1","type":"skill","app_id":"assistant_response_speech","chat_id":"chat","message_id":"one","credits":2,"created_at":1792386000},
          {"id":"speech-2","type":"skill","app_id":"assistant_response_speech","chat_id":"chat","message_id":"one","credits":3,"created_at":1792386001},
          {"id":"speech-3","type":"skill","app_id":"assistant_response_speech","chat_id":"chat","message_id":"two","credits":4,"created_at":1792386002},
          {"id":"ordinary","type":"skill","app_id":"audio","chat_id":"chat","message_id":"one","credits":5,"created_at":1792386003}
        ]}
        """)
        let rows = BillingUsageModel.groupSpeech(response.entries)
        XCTAssertEqual(rows.map(\.id), ["speech-1", "speech-3", "ordinary"])
        XCTAssertEqual(rows.map { $0.credits ?? 0 }, [5, 4, 5])
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.surface.semantic-parity
    func testInvalidatedOwnerCannotPublishSuspendedUsageResponse() async throws {
        let gate = UsageResponseGate()
        let model = BillingUsageModel(transport: { path, _ in
            if path.hasPrefix("/v1/apps/") { return Data("{\"apps\":{}}".utf8) }
            return await gate.waitForResponse()
        }, validate: { _ in })
        let load = Task { await model.load(tab: .overview, accountID: "synthetic-owner") }
        await gate.waitUntilRequested()
        model.invalidate()
        gate.complete(Data(BillingUsageModel.fixtureOverview.utf8))
        await load.value
        XCTAssertTrue(model.groups.isEmpty)
        XCTAssertFalse(model.loading)
        XCTAssertFalse(model.error)
        XCTAssertNil(model.selectedTitle)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity
    func testOverviewDrilldownIsLocalFixtureAndBackRetainsLandingGroups() async throws {
        let model = BillingUsageModel()
        await model.load(tab: .overview, accountID: nil, fixture: true)
        let row = try XCTUnwrap(model.groups.first?.rows.first)
        await model.open(row, tab: .overview, accountID: nil, fixture: true)
        let entry = try XCTUnwrap(model.entryRows.first?.entry)
        await model.selectEntry(entry, fixture: true)
        XCTAssertEqual(model.selectedEntry?.id, entry.id)
        XCTAssertNil(model.selectedTarget, "Fixture must not fabricate a message or result target")
        model.closeEntry()
        XCTAssertNil(model.selectedEntry)
        XCTAssertFalse(model.entryRows.isEmpty)
        model.back()
        XCTAssertNil(model.selectedTitle)
        XCTAssertEqual(model.groups.first?.rows.count, 9)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.usage.landing-complete
    func testHiddenTitlesAndMessageActionsRequireCurrentUnlockAndExistingMessage() async throws {
        var hidden: Chat = try decode("""
        {"id":"00000000-0000-0000-0000-000000000369","title":"Synthetic hidden title","is_hidden":true}
        """)
        hidden.teamId = TeamWorkspaceContext.shared.teamID
        let message: Message = try decode("""
        {"id":"fixture-usage-message","chat_id":"00000000-0000-0000-0000-000000000369","role":"assistant","created_at":"2026-10-19T09:00:00Z"}
        """)
        let model = BillingUsageModel(transport: { path, _ in
            Data((path.hasPrefix("/v1/apps/") ? "{\"apps\":{}}" : BillingUsageModel.fixtureOverview).utf8)
        }, validate: { _ in })
        let entry = try XCTUnwrap(BillingUsageModel.decode(UsageDetailsResponse.self, Data(BillingUsageModel.fixtureEntries.utf8)).entries.first)
        var opened: BillingUsageOpenTarget?
        var context = BillingUsageContext(hiddenChatsUnlocked: false, chat: { _ in hidden },
            messages: { _ in [message] }, embeds: { _ in [] }, openTarget: { opened = $0 })
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.title, AppStrings.chat)
        await model.selectEntry(entry)
        XCTAssertNil(model.selectedTarget)
        context.hiddenChatsUnlocked = true
        context.messages = { _ in [] }
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.title, "Synthetic hidden title")
        await model.selectEntry(entry)
        XCTAssertNil(model.selectedTarget, "A chat alone cannot establish that its message exists")
        context.messages = { _ in [message] }
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        await model.selectEntry(entry)
        XCTAssertEqual(model.selectedTarget, .message(chatID: hidden.id, messageID: message.id))
        await model.openSelectedTarget()
        XCTAssertEqual(opened, model.selectedTarget)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity,billing.usage.landing-complete
    func testSparseMonthlyAPIRowsDoNotHideOlderHistoryWhenCountEqualsWindow() async throws {
        let transport = MonthlyUsageTransport(responses: [3: """
        {"summaries":[{"app_id":"ai","year_month":"2026-10","total_credits":3},{"app_id":"ai","year_month":"2026-09","total_credits":2},{"app_id":"ai","year_month":"2026-08","total_credits":1}],"count":3,"has_more_months":true,"next_older_month":"2025-02"}
        """])
        let model = BillingUsageModel(transport: transport.call, validate: { _ in }, now: { MonthlyUsageTransport.now })
        await model.load(tab: .apps, accountID: "synthetic-owner")
        XCTAssertFalse(model.error)
        XCTAssertEqual(model.groups.map(\.id), ["2026-10", "2026-09", "2026-08"])
        XCTAssertTrue(model.hasMore)
        XCTAssertFalse(model.historyAvailabilityMissing)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity
    func testManyEntitiesInOneMonthDoNotInventOlderMonthlyHistory() async throws {
        let transport = MonthlyUsageTransport(responses: [3: """
        {"summaries":[{"app_id":"ai","year_month":"2026-10","total_credits":1},{"app_id":"web","year_month":"2026-10","total_credits":2},{"app_id":"audio","year_month":"2026-10","total_credits":3},{"app_id":"code","year_month":"2026-10","total_credits":4}],"count":4,"has_more_months":false,"next_older_month":null}
        """])
        let model = BillingUsageModel(transport: transport.call, validate: { _ in }, now: { MonthlyUsageTransport.now })
        await model.load(tab: .apps, accountID: "synthetic-owner")
        XCTAssertEqual(model.groups.count, 1)
        XCTAssertEqual(model.groups.first?.rows.count, 4)
        XCTAssertFalse(model.hasMore)
        XCTAssertFalse(model.historyAvailabilityMissing)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity,billing.usage.landing-complete
    func testMonthlyPaginationJumpsAcrossEmptyGapUsingValidatedServerMonth() async throws {
        let needed = try XCTUnwrap(BillingUsageMonth.windowIncluding("2025-02", now: MonthlyUsageTransport.now))
        let transport = MonthlyUsageTransport(responses: [3: """
        {"summaries":[{"app_id":"ai","year_month":"2026-10","total_credits":3}],"count":1,"has_more_months":true,"next_older_month":"2025-02"}
        """, needed: """
        {"summaries":[{"app_id":"ai","year_month":"2026-10","total_credits":3},{"app_id":"audio","year_month":"2025-02","total_credits":7}],"count":2,"has_more_months":false,"next_older_month":null}
        """])
        let model = BillingUsageModel(transport: transport.call, validate: { _ in }, now: { MonthlyUsageTransport.now })
        await model.load(tab: .apps, accountID: "synthetic-owner")
        XCTAssertTrue(model.hasMore)
        await model.load(tab: .apps, accountID: "synthetic-owner", more: true)
        XCTAssertEqual(model.groups.map(\.id), ["2026-10", "2025-02"])
        XCTAssertEqual(model.loadedMonths, needed)
        XCTAssertFalse(model.hasMore)
        XCTAssertEqual(transport.windows, [3, needed])
    }

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity
    func testOldServerAvailabilityIsExplicitlyUnknownAndManualWindowStillWorks() async throws {
        let payload = """
        {"summaries":[{"app_id":"ai","year_month":"2026-10","total_credits":3}],"count":1}
        """
        let transport = MonthlyUsageTransport(responses: [3: payload, 6: payload])
        let model = BillingUsageModel(transport: transport.call, validate: { _ in }, now: { MonthlyUsageTransport.now })
        await model.load(tab: .apps, accountID: "synthetic-owner")
        XCTAssertFalse(model.hasMore, "Absent metadata must not fabricate an availability claim")
        XCTAssertTrue(model.historyAvailabilityMissing)
        await model.load(tab: .apps, accountID: "synthetic-owner", more: true)
        XCTAssertEqual(transport.windows, [3, 6])
        XCTAssertEqual(model.groups.count, 1)
        XCTAssertFalse(model.error)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete,billing.access.authenticated-first-party,billing.surface.semantic-parity
    func testUsageProjectsProvidedCategoryIconsAndMonthlyFallbacksFromCurrentChat() async throws {
        var chat: Chat = try decode("""
        {"id":"00000000-0000-0000-0000-000000000398","title":"Synthetic chat","category":"software_development","icon":"rocket"}
        """)
        chat.teamId = TeamWorkspaceContext.shared.teamID
        let model = categoryModel(chatID: chat.id)
        let context = BillingUsageContext(chat: { _ in chat })
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance,
            BillingUsageChatAppearance(kind: .standard, category: "software_development", lucideIcon: "rocket"))
        await model.load(tab: .chats, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance,
            BillingUsageChatAppearance(kind: .standard, category: "software_development", lucideIcon: "rocket"))
        chat.category = "science"; chat.icon = nil
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance,
            BillingUsageChatAppearance(kind: .standard, category: "science", lucideIcon: "microscope"))
        chat.category = "unknown-synthetic-category"
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance, BillingUsageChatAppearance.fallback)
        chat.icon = "rocket"
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance,
            BillingUsageChatAppearance(kind: .standard, lucideIcon: "rocket"), "Unknown categories must not acquire a primary gradient")
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.usage.landing-complete
    func testUsageCategoryIconPrivacyRequiresCurrentHiddenUnlockAndMatchingTeamAndChat() async throws {
        var chat: Chat = try decode("""
        {"id":"00000000-0000-0000-0000-000000000398","title":"Synthetic hidden chat","category":"finance","icon":"dollar-sign","is_hidden_candidate":true}
        """)
        chat.teamId = TeamWorkspaceContext.shared.teamID
        let expectedID = chat.id
        let model = categoryModel(chatID: expectedID)
        var context = BillingUsageContext(hiddenChatsUnlocked: false, chat: { _ in chat })
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.title, AppStrings.chat)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance, BillingUsageChatAppearance.fallback)
        context.hiddenChatsUnlocked = true
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance?.category, "finance")
        chat.teamId = "other-synthetic-team"
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.title, AppStrings.chat)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance, BillingUsageChatAppearance.fallback)
        chat = try decode("""
        {"id":"wrong-synthetic-chat","title":"Unrelated","category":"medical_health","icon":"heart"}
        """)
        chat.teamId = TeamWorkspaceContext.shared.teamID
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance, BillingUsageChatAppearance.fallback)
        XCTAssertEqual(model.groups.first?.rows.first?.title, AppStrings.chat)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.surface.semantic-parity
    func testUsageDecryptsOnlyItsExistingCategoryAndIconWithoutInstallingOrPersistingMetadata() async throws {
        let id = UUID().uuidString, key = SymmetricKey(size: .bits256)
        let category = try await CryptoManager.shared.encryptContent("finance", key: key)
        let icon = try await CryptoManager.shared.encryptContent("rocket", key: key)
        let body = try JSONSerialization.data(withJSONObject: ["id": id, "title": "Synthetic chat", "encrypted_category": category, "encrypted_icon": icon])
        var chat = try BillingUsageModel.decode(Chat.self, body)
        chat.teamId = TeamWorkspaceContext.shared.teamID
        ChatKeyManager.shared.setKey(key, for: id)
        defer { ChatKeyManager.shared.removeKey(for: id) }
        let generation = ChatKeyManager.shared.cacheGeneration
        let model = categoryModel(chatID: id)
        await model.load(tab: .overview, accountID: "synthetic-owner", context: .init(chat: { _ in chat }))
        XCTAssertFalse(model.error)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance,
            BillingUsageChatAppearance(kind: .standard, category: "finance", lucideIcon: "rocket"))
        XCTAssertEqual(ChatKeyManager.shared.cacheGeneration, generation)
        XCTAssertNil(ChatKeyManager.shared.encryptedKey(for: id))
        XCTAssertNil(chat.category); XCTAssertNil(chat.icon, "Projection must not mutate its scoped source chat")
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.usage.landing-complete
    func testIncognitoAndDeletedUsageNeverExposeAvailableLocalCategoryMetadata() async throws {
        let suite = "org.openmates.tests.usage-special-category-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let registry = BillingUsageDraftAudioRegistry(defaults: defaults, validate: { _ in })
        var chat: Chat = try decode("""
        {"id":"00000000-0000-0000-0000-000000000398","title":"Synthetic local title","category":"finance","icon":"dollar-sign"}
        """)
        chat.teamId = TeamWorkspaceContext.shared.teamID
        for (id, deleted, expected) in [(chat.id, true, BillingUsageChatAppearance.Kind.deleted), ("incognito", false, .incognito)] {
            let model = categoryModel(chatID: id, deleted: deleted, draftAudioRegistry: registry)
            await model.load(tab: .overview, accountID: "synthetic-owner", context: .init(hiddenChatsUnlocked: true, chat: { _ in chat }))
            let appearance = try XCTUnwrap(model.groups.first?.rows.first?.chatAppearance)
            XCTAssertEqual(appearance.kind, expected)
            XCTAssertNil(appearance.category); XCTAssertNil(appearance.lucideIcon)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity
    func testUsageLucideRendererResolvesArbitrarySupportedIconsAndWebInvalidFallback() {
        XCTAssertEqual(BillingUsageLucideResolver.resolve("rocket"), "rocket")
        XCTAssertEqual(BillingUsageLucideResolver.resolve("microscope"), "microscope")
        XCTAssertEqual(BillingUsageLucideResolver.resolve("not-a-real-usage-icon"), "help-circle")
        XCTAssertEqual(BillingUsageLucideResolver.resolve(""), "help-circle")
        XCTAssertEqual(BillingUsageLucideResolver.resolve(String(repeating: "x", count: 101)), "help-circle")
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.surface.semantic-parity
    func testUsageMessageNavigationAcceptsOnlyExactNonemptyServerAliasInSameChat() async throws {
        var chat: Chat = try decode("""
        {"id":"00000000-0000-0000-0000-000000000369","title":"Synthetic chat"}
        """)
        chat.teamId = TeamWorkspaceContext.shared.teamID
        var message: Message = try decode("""
        {"id":"local-database-id","serverMessageId":"fixture-usage-message","chat_id":"00000000-0000-0000-0000-000000000369","role":"assistant","created_at":"2026-10-19T09:00:00Z"}
        """)
        let model = BillingUsageModel(transport: { path, _ in
            Data((path.hasPrefix("/v1/apps/") ? "{\"apps\":{}}" : BillingUsageModel.fixtureOverview).utf8)
        }, validate: { _ in })
        var opened: BillingUsageOpenTarget?
        let context = BillingUsageContext(chat: { _ in chat }, messages: { _ in [message] }, openTarget: { opened = $0 })
        let entry = try XCTUnwrap(BillingUsageModel.decode(UsageDetailsResponse.self, Data(BillingUsageModel.fixtureEntries.utf8)).entries.first)
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        await model.selectEntry(entry)
        XCTAssertEqual(model.selectedTarget, .message(chatID: chat.id, messageID: "fixture-usage-message"))
        await model.openSelectedTarget()
        XCTAssertEqual(opened, model.selectedTarget)
        for (alias, messageChat) in [("fixture-usage-message-extra", chat.id), ("", chat.id), ("fixture-usage-message", "other-chat")] {
            let data = try JSONSerialization.data(withJSONObject: ["id": "local-database-id", "serverMessageId": alias,
                "chat_id": messageChat, "role": "assistant", "created_at": "2026-10-19T09:00:00Z"])
            message = try BillingUsageModel.decode(Message.self, data)
            await model.selectEntry(entry)
            XCTAssertNil(model.selectedTarget)
        }
    }

    // Lower-level allocation/model coverage only: this companion is in a
    // separate isolated repository, not injected into the former shared-store
    // fallback. This case does not detect that old fallback by itself.
    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.usage.landing-complete
    func testConfirmedAllocationControlsDeletedLabelWithIsolatedRecordingFixture() async throws {
        let establishedID = UUID().uuidString, allocatedID = UUID().uuidString
        let owner = UserTasksAccountFence(accountID: "synthetic-owner")
        let suite = "org.openmates.tests.usage-allocation-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let registry = BillingUsageDraftAudioRegistry(defaults: defaults, validate: { _ in })
        let schema = Schema([PersistedComposerDraft.self])
        let container = try ModelContainer(for: schema,
            configurations: [ModelConfiguration("UsageEstablishedRecording", schema: schema, isStoredInMemoryOnly: true)])
        let repository = OfflineStore(modelContainer: container)
        let payload = "{\"attachments\":[{\"type\":\"audio-recording\"}]}"
        let encrypted = try await CryptoManager.shared.encryptContent(payload, key: SymmetricKey(size: .bits256))
        try await repository.upsert(.init(chatId: establishedID, encryptedMarkdown: "synthetic-ciphertext",
            encryptedPreview: "synthetic-ciphertext", encryptedRecordingPayload: encrypted, revision: 1, draftVersion: 1))
        let stored = try await repository.record(chatId: establishedID)
        XCTAssertEqual(stored?.encryptedRecordingPayload, encrypted)
        var established: Chat = try decode("{\"id\":\"\(establishedID)\",\"title\":\"Established\",\"messages_v\":2}")
        established.teamId = owner.teamID
        let accepted: Message = try decode("{\"id\":\"accepted-user-message\",\"chat_id\":\"\(establishedID)\",\"role\":\"user\",\"created_at\":\"2026-10-19T09:00:00Z\"}")
        let model = categoryModel(chatID: establishedID, deleted: true, draftAudioRegistry: registry)
        await model.load(tab: .overview, accountID: owner.accountID,
            context: .init(chat: { _ in established }, messages: { _ in [accepted] }))
        XCTAssertEqual(model.groups.first?.rows.first?.title, AppStrings.usageDeletedChat)
        XCTAssertEqual(model.groups.first?.rows.first?.chatAppearance?.kind, .deleted)
        let allocation = try XCTUnwrap(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(
            draftChatID: allocatedID, recordingChatID: allocatedID, isNewChatComposer: true,
            hasAcceptedUserMessage: false, teamID: owner.teamID))
        _ = try await registry.mark(allocation, fence: owner)
        let allocated = categoryModel(chatID: allocatedID, deleted: true, draftAudioRegistry: registry)
        await allocated.load(tab: .overview, accountID: owner.accountID)
        XCTAssertEqual(allocated.groups.first?.rows.first?.title, AppStrings.usageUnsentDraft)
        XCTAssertEqual(allocated.groups.first?.rows.first?.chatAppearance?.kind, .unsentDraft)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.surface.semantic-parity
    func testUsageTargetsRemainAvailableWithNonemptyLiveAndOlderCachedMessagesAndEmbeds() async throws {
        var chat: Chat = try decode("""
        {"id":"00000000-0000-0000-0000-000000000369","title":"Synthetic chat"}
        """)
        chat.teamId = TeamWorkspaceContext.shared.teamID
        let live: Message = try decode("""
        {"id":"new-live-message","chat_id":"00000000-0000-0000-0000-000000000369","role":"assistant","created_at":"2026-10-19T09:00:00Z"}
        """)
        let cached: Message = try decode("""
        {"id":"fixture-usage-message","chat_id":"00000000-0000-0000-0000-000000000369","role":"assistant","created_at":"2026-10-18T09:00:00Z"}
        """)
        let hash = SHA256.hash(data: Data(cached.id.utf8)).map { String(format: "%02x", $0) }.joined()
        let liveEmbed: EmbedRecord = try decode("""
        {"id":"live-embed","type":"app-skill-use","app_id":"web","skill_id":"search","hashed_message_id":"unrelated-new-live-hash"}
        """)
        let cachedEmbed: EmbedRecord = try decode("{\"id\":\"cached-embed\",\"type\":\"app-skill-use\",\"app_id\":\"web\",\"skill_id\":\"search\",\"hashed_message_id\":\"\(hash)\"}")
        let context = BillingUsageContext(chat: { _ in chat }, messages: { _ in [live, cached] },
            embeds: { _ in [liveEmbed, cachedEmbed] }, openTarget: { _ in })
        let model = categoryModel(chatID: chat.id)
        await model.load(tab: .overview, accountID: "synthetic-owner", context: context)
        let llm = try XCTUnwrap(BillingUsageModel.decode(UsageDetailsResponse.self, Data(BillingUsageModel.fixtureEntries.utf8)).entries.first)
        await model.selectEntry(llm)
        XCTAssertEqual(model.selectedTarget, .message(chatID: chat.id, messageID: cached.id))
        let web: UsageEntry = try decode("{\"id\":\"older-web-usage\",\"type\":\"skill_execution\",\"app_id\":\"web\",\"skill_id\":\"search\",\"chat_id\":\"\(chat.id)\",\"message_id\":\"\(cached.id)\"}")
        await model.selectEntry(web)
        XCTAssertEqual(model.selectedTarget, .embed(chatID: chat.id, embedID: cachedEmbed.id))
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete,billing.surface.semantic-parity
    func testMonthlySpecialChatKindsPreserveTheirSemanticRowAndDetailGlyph() async throws {
        let owner = UserTasksAccountFence(accountID: "synthetic-owner")
        let deletedID = UUID().uuidString, allocatedID = UUID().uuidString
        let suite = "org.openmates.tests.usage-monthly-glyph-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let registry = BillingUsageDraftAudioRegistry(defaults: defaults, validate: { _ in })
        let allocation = try XCTUnwrap(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(
            draftChatID: allocatedID, recordingChatID: allocatedID, isNewChatComposer: true,
            hasAcceptedUserMessage: false, teamID: owner.teamID))
        _ = try await registry.mark(allocation, fence: owner)
        let cases: [(String, Bool, BillingUsageChatAppearance.Kind, String)] = [
            ("incognito", false, .incognito, "anonym"),
            (deletedID, true, .deleted, "delete"),
            (allocatedID, true, .unsentDraft, "recordaudio")
        ]
        for (id, deleted, kind, glyph) in cases {
            let model = categoryModel(chatID: id, deleted: deleted, draftAudioRegistry: registry)
            // The existing overview response supplies authoritative deletion
            // metadata retained when the monthly tab opens; absence is not deletion.
            await model.load(tab: .overview, accountID: owner.accountID)
            await model.load(tab: .chats, accountID: owner.accountID)
            let row = try XCTUnwrap(model.groups.first?.rows.first)
            XCTAssertEqual(row.chatAppearance?.kind, kind)
            XCTAssertNil(row.chatAppearance?.lucideIcon)
            XCTAssertEqual(row.icon, glyph, "The detail header captures this same row icon")
        }
        XCTAssertNil(BillingUsageChatAppearance(kind: .standard, category: "science", lucideIcon: "rocket").semanticIcon,
            "Standard chat icons retain their separate supplied/category Lucide renderer")
    }

    private func categoryModel(chatID: String, deleted: Bool = false,
                               draftAudioRegistry: BillingUsageDraftAudioRegistry = .shared) -> BillingUsageModel {
        BillingUsageModel(transport: { path, _ in
            if path.hasPrefix("/v1/apps/") { return Data("{\"apps\":{}}".utf8) }
            if path.contains("daily-overview") {
                return Data("{\"days\":[{\"date\":\"2026-10-19\",\"total_credits\":3,\"items\":[{\"type\":\"chat\",\"chat_id\":\"\(chatID)\",\"is_deleted\":\(deleted),\"total_credits\":3,\"entry_count\":1}]}],\"has_more_days\":false}".utf8)
            }
            return Data("{\"summaries\":[{\"chat_id\":\"\(chatID)\",\"year_month\":\"2026-10\",\"total_credits\":3}],\"has_more_months\":false}".utf8)
        }, validate: { _ in }, draftAudioRegistry: draftAudioRegistry)
    }

    private func decode<T: Decodable>(_ json: String) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: Data(json.utf8))
    }
}

@MainActor
private final class UsageResponseGate {
    private var response: CheckedContinuation<Data, Never>?
    private var requested: CheckedContinuation<Void, Never>?
    func waitForResponse() async -> Data {
        await withCheckedContinuation { continuation in
            response = continuation
            requested?.resume(); requested = nil
        }
    }
    func waitUntilRequested() async {
        if response != nil { return }
        await withCheckedContinuation { requested = $0 }
    }
    func complete(_ data: Data) { response?.resume(returning: data); response = nil }
}

@MainActor
private final class MonthlyUsageTransport {
    static let now = Date(timeIntervalSince1970: 1_792_386_000)
    let responses: [Int: String]
    private(set) var windows: [Int] = []
    init(responses: [Int: String]) { self.responses = responses }
    func call(_ path: String, _ fence: UserTasksAccountFence) async throws -> Data {
        if path.hasPrefix("/v1/apps/") { return Data("{\"apps\":{}}".utf8) }
        let query = URLComponents(string: "https://fixture.invalid" + path)?.queryItems
        let months = query?.first(where: { $0.name == "months" })?.value.flatMap(Int.init) ?? 0
        windows.append(months)
        guard let response = responses[months] else { throw APIError.invalidResponse }
        return Data(response.utf8)
    }
}
