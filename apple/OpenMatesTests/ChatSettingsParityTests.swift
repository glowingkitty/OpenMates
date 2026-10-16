// Focused chat settings guards/export evidence; live API and visible parent flow
// require the native UI tests and root-owned account verification.
import CryptoKit
import XCTest
import SwiftUI
import ZIPFoundation
@testable import OpenMates

@MainActor
final class ChatSettingsParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testSummaryRejectsEmbedPayloadsAndPreservesReadableSummary() {
        XCTAssertEqual(ChatSettingsProjection.summary("  Coordinate the launch.  "), "Coordinate the launch.")
        for value in ["", "```json\n{}\n```", "[!](embed:synthetic)", "{\"embed_id\":\"synthetic\"}", "{\"type\":\"code\",\"content\":\"value\"}"] {
            XCTAssertEqual(ChatSettingsProjection.summary(value), "No summary available yet.")
        }
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testHeaderUsesWebCategoryFallbackAndPreservesPrimaryPreviewFixture() throws {
        func stops(_ gradient: LinearGradient) throws -> [Gradient.Stop] {
            try XCTUnwrap(Mirror(reflecting: gradient).descendant("gradient") as? Gradient).stops
        }
        let general = try stops(CategoryMapping.gradient(for: "general_knowledge"))
        for category in [nil, "", "unknown-category"] as [String?] {
            XCTAssertEqual(try stops(ChatSettingsView.headerGradient(category: category, preview: false)), general)
        }
        XCTAssertEqual(try stops(ChatSettingsView.headerGradient(category: "software_development", preview: false)),
                       try stops(CategoryMapping.gradient(for: "software_development")))
        XCTAssertEqual(try stops(ChatSettingsView.headerGradient(category: "design", preview: true)),
                       try stops(LinearGradient.primary))
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testExampleTabsHideOwnerPlanningAndUnknownUsage() {
        XCTAssertEqual(ChatSettingsProjection.visibleTabs(example: true, hasFiles: false, hasUsage: false), [.share])
        XCTAssertEqual(ChatSettingsProjection.visibleTabs(example: true, hasFiles: true, hasUsage: true), [.files, .usage, .share])
        XCTAssertEqual(ChatSettingsProjection.visibleTabs(example: false, hasFiles: false, hasUsage: false), ChatSettingsTab.allCases)
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testFilesExcludeSearchCardsAndDeduplicateConcreteFiles() throws {
        func embed(_ id: String, _ type: String) throws -> EmbedRecord {
            let json = try JSONSerialization.data(withJSONObject: ["id": id, "type": type, "status": "finished", "data": ["title": "Synthetic file"]])
            return try JSONDecoder().decode(EmbedRecord.self, from: json)
        }
        let files = try [embed("image", "images-image"), embed("search", "web-search"), embed("code", "code-code"), embed("image", "images-image")]
        XCTAssertEqual(ChatSettingsProjection.files(files).map(\.id), ["code", "image"])
    }
    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted
    func testSharedViewerCannotCreateOrCompleteTask() async {
        let model = ChatSettingsModel()
        let created = await model.create(title: "Synthetic task", description: "", chatID: "synthetic", accountID: "synthetic-owner", shared: true)
        XCTAssertFalse(created)
        await model.toggle(.init(id: "synthetic", title: "Task", detail: "", status: "todo"), accountID: "synthetic-owner", shared: true)
        XCTAssertTrue(model.tasks.isEmpty)
        XCTAssertFalse(model.saving)
        XCTAssertNil(model.error)
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testTaskProgressAndShareExpirationMatchWeb() {
        let rows: [ChatSettingsPlanningRow] = [.init(id: "a", title: "A", detail: "", status: "done"), .init(id: "b", title: "B", detail: "", status: "todo"), .init(id: "c", title: "C", detail: "", status: "blocked")]
        XCTAssertEqual(ChatSettingsProjection.progress(rows), 33)
        XCTAssertEqual(ChatSettingsProjection.progress([]), 0)
        XCTAssertEqual(ShareDuration.tenMinutes.rawValue, 600)
    }
    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted
    func testShareRequiresKeyAndOwnerAndDoesNotFabricateLink() async {
        let share = ChatSettingsShareModel()
        await share.generate(chat: fixtureChat(), accountID: nil)
        XCTAssertNil(share.url)
        XCTAssertNotNil(share.error)
        XCTAssertFalse(share.generating)
    }
    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted
    func testFallbackFileExportOmitsMediaSecretsAndSanitizesNames() async throws {
        let data = try JSONSerialization.data(withJSONObject: ["id": "synthetic-file", "type": "document", "status": "finished", "data": ["title": "../report", "aes_key": "private-synthetic-key"]])
        let embed = try JSONDecoder().decode(EmbedRecord.self, from: data)
        let file = try await ChatSettingsExport.file(embed, scope: nil)
        XCTAssertEqual(file.filename, "report.json")
        XCTAssertFalse(String(decoding: file.data, as: UTF8.self).contains("private-synthetic-key"))
        XCTAssertEqual(ChatSettingsExport.safeFilename("../folder/review.txt", fallback: "file"), "review.txt")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testFileSnapshotDetectsSameIDHydrationAndPayloadChanges() throws {
        func embed(_ type: String, _ status: String, _ title: String) throws -> EmbedRecord {
            let bytes = try JSONSerialization.data(withJSONObject: ["id": "same-file", "type": type, "status": status, "data": ["title": title]])
            return try JSONDecoder().decode(EmbedRecord.self, from: bytes)
        }
        let pending = try embed("web-search", "processing", "Pending")
        let ready = try embed("images-image", "finished", "Image")
        let renamed = try embed("images-image", "finished", "Updated image")
        XCTAssertNotEqual(ChatSettingsFileSnapshot(records: [pending]), ChatSettingsFileSnapshot(records: [ready]))
        XCTAssertNotEqual(ChatSettingsFileSnapshot(records: [ready]), ChatSettingsFileSnapshot(records: [renamed]))
        XCTAssertEqual(ChatSettingsFileSnapshot(records: [renamed]), ChatSettingsFileSnapshot(records: [renamed]))
        XCTAssertEqual(ChatSettingsProjection.files([renamed]).first?.rawData?["title"]?.value as? String, "Updated image")
    }
    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted
    func testSharedAndAnonymousUsageClearPreviousOwnerTotalAndRows() async {
        let model = ChatSettingsUsageModel()
        model.total = 777
        model.rows = [.init(id: "private-owner-row", label: "Owner usage", provider: "Provider", credits: 777, timestamp: "")]
        await model.load(chatID: "shared-chat", accountID: "synthetic-owner", shared: true, messages: [])
        XCTAssertNil(model.total)
        XCTAssertTrue(model.rows.isEmpty)
        model.total = 888
        await model.load(chatID: "anonymous-chat", accountID: nil, shared: false, messages: [])
        XCTAssertNil(model.total)
        XCTAssertTrue(model.rows.isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testBundledPublicUsagePopulatesKnownCreditsWithoutOwnerLoading() {
        let rows = PublicChatUsageCatalog.rows(chatID: "example-audio-speak-openmates-welcome-message")
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows.map(\.label), ["ai | ask", "audio | speak"])
        let model = ChatSettingsUsageModel()
        model.total = 999
        model.loadStatic(rows: rows)
        XCTAssertNil(model.total)
        XCTAssertEqual(model.knownCredits, 37)
        XCTAssertTrue(model.hasKnownCredits)
        XCTAssertTrue(ChatSettingsProjection.visibleTabs(example: true, hasFiles: false, hasUsage: model.hasKnownCredits).contains(.usage))
        XCTAssertFalse(rows[0].timestampLabel.isEmpty)
        XCTAssertEqual(rows[0].provider, "Google AI Studio / US")
        XCTAssertTrue(PublicChatUsageCatalog.rows(chatID: "example-gigantic-airplanes").isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testPublicUsageRejectsWrongIdentityAndUntrustedExecutableValues() {
        let source = """
        export const example = { chat_id: "example-synthetic", usage_entries: [{id: "row", app_id: "ai", skill_id: "ask", credits: 2, created_at: 1786382249}] };
        """
        XCTAssertEqual(PublicChatUsageCatalog.parse(source, chatID: "example-synthetic").first?.credits, 2)
        XCTAssertTrue(PublicChatUsageCatalog.parse(source, chatID: "example-other").isEmpty)
        XCTAssertTrue(PublicChatUsageCatalog.parse(source.replacingOccurrences(of: "credits: 2", with: "credits: fetch('private')"), chatID: "example-synthetic").isEmpty)
        let unknown = ChatSettingsUsageModel()
        unknown.loadStatic(rows: [.init(id: "unknown", label: "AI | Ask", provider: "Unknown provider", credits: nil, timestamp: "")])
        XCTAssertFalse(unknown.hasKnownCredits)
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testBundledPublicAudioFileUsesConfiguredOriginAndSanitizedReference() throws {
        let chatID = "example-audio-speak-openmates-welcome-message"
        let files = PublicChatFileCatalog.rows(chatID: chatID)
        XCTAssertEqual(files.count, 1)
        let file = try XCTUnwrap(files.first)
        XCTAssertEqual(file.type, "audio")
        XCTAssertEqual(ChatSettingsExport.title(file), "audio-speak-openmates-welcome-message.mp3")
        let url = try XCTUnwrap(ChatSettingsExport.publicFileURL(file))
        XCTAssertEqual(url, PublicAssistantSpeechSegment.url("/store-examples/audio-speak-openmates-welcome-message.mp3"))
        XCTAssertEqual(url.host, ServerProfile.current().webBaseURL.host)
        XCTAssertEqual(url.pathExtension, "mp3")
        XCTAssertEqual(Set(file.rawData?.keys.map { $0 } ?? []), ["filename", "type", "mime_type", "public_file_url", "public_file_reference", "file_icon", "file_metadata"])
        XCTAssertEqual(ChatSettingsProjection.visibleTabs(example: true, hasFiles: !files.isEmpty, hasUsage: true), [.files, .usage, .share])
        let source = try XCTUnwrap(PublicChatUsageCatalog.source(chatID: chatID))
        let alternate = URL(string: "https://public-fixture.example.invalid")!
        let alternateFile = try XCTUnwrap(PublicChatFileCatalog.parse(source, chatID: chatID, origin: alternate).first)
        XCTAssertEqual(ChatSettingsExport.publicFileURL(alternateFile)?.host, alternate.host)
        XCTAssertTrue(PublicChatFileCatalog.parse(source, chatID: "example-other").isEmpty)
        let rejected = source.replacingOccurrences(of: "/store-examples/audio-speak-openmates-welcome-message.mp3", with: "https://user:secret@example.invalid/file.mp3")
        let rejectedFile = try XCTUnwrap(PublicChatFileCatalog.parse(rejected, chatID: chatID).first)
        XCTAssertNil(ChatSettingsExport.publicFileURL(rejectedFile))
        XCTAssertNil(rejectedFile.rawData?["prompt"])
        XCTAssertNil(rejectedFile.rawData?["aes_key"])
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testFileDownloadCountLabelsResolveSingularPluralAndEmpty() {
        XCTAssertFalse(AppStrings.chatSettingsDownloadableCount(0).contains("{count}"))
        XCTAssertTrue(AppStrings.chatSettingsDownloadableCount(1).contains("1"))
        XCTAssertTrue(AppStrings.chatSettingsDownloadableCount(2).contains("2"))
        XCTAssertNotEqual(AppStrings.chatSettingsDownloadableCount(1), AppStrings.chatSettingsDownloadableCount(2))
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testPublicTemplateFilesDecodeWithoutExecutingInterpolation() throws {
        let files = PublicChatFileCatalog.rows(chatID: "example-beautiful-single-page-html")
        let html = try XCTUnwrap(files.first)
        XCTAssertEqual(ChatSettingsExport.title(html), "index.html")
        XCTAssertEqual(html.rawData?["file_icon"]?.value as? String, "coding")
        XCTAssertEqual(html.rawData?["file_metadata"]?.value as? String, "Code file | 165 lines")
        XCTAssertNil(html.rawData?["code"])
        let source = try XCTUnwrap(PublicChatUsageCatalog.source(chatID: "example-beautiful-single-page-html"))
        let executable = source.replacingOccurrences(of: "content: `type:", with: "content: `${fetch('private')}type:")
        XCTAssertTrue(PublicChatFileCatalog.parse(executable, chatID: "example-beautiful-single-page-html").isEmpty)
        XCTAssertNil(PublicAssistantSpeechManifest.json5WithStaticTemplates("{ content: `unterminated"))
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testPublicCodeWithoutURLExportsSanitizedReferenceInsteadOfEmptyCode() async throws {
        for (chatID, expected) in [("example-python-squares-code-run", "square_parity.py"), ("example-svelte-runes-docs", "PriceCalculator.svelte")] {
            let file = try XCTUnwrap(PublicChatFileCatalog.rows(chatID: chatID).first { ChatSettingsExport.title($0) == expected })
            XCTAssertEqual(file.rawData?["public_file_reference"]?.value as? Bool, true)
            let exported = try await ChatSettingsExport.file(file, scope: nil)
            XCTAssertEqual(exported.filename, expected + ".json")
            XCTAssertEqual(exported.contentType, .json)
            let reference = try XCTUnwrap(JSONSerialization.jsonObject(with: exported.data) as? [String: String])
            XCTAssertEqual(Set(reference.keys), ["embedId", "contentRef", "title", "type"])
            XCTAssertEqual(reference["title"], expected)
            XCTAssertEqual(reference["contentRef"], "embed:" + file.id)
            XCTAssertFalse(exported.data.isEmpty)
        }
        let audio = try XCTUnwrap(PublicChatFileCatalog.rows(chatID: "example-audio-speak-openmates-welcome-message").first)
        XCTAssertEqual(audio.rawData?["file_icon"]?.value as? String, "audio")
        XCTAssertEqual(audio.rawData?["file_metadata"]?.value as? String, "Audio | 4.6s | 73 KB")
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testUsageEntryAppIconsMatchWebMappingAndFallback() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        for app in ["web", "ai", "news", "videos", "maps", "code", "audio", "unknown-app"] {
            let data = try JSONSerialization.data(withJSONObject: ["id": "row", "app_id": app, "credits": 1])
            let row = try decoder.decode(ChatSettingsUsageRow.self, from: data)
            XCTAssertEqual(row.appID, app)
            XCTAssertEqual(row.iconName, app == "unknown-app" ? "chat" : app)
        }
        let local = ChatSettingsUsageRow(id: "local", label: "AI | Ask", provider: "Model", credits: nil, timestamp: "")
        XCTAssertNil(local.appID)
        XCTAssertEqual(local.iconName, "chat")
        XCTAssertEqual(PublicChatUsageCatalog.rows(chatID: "example-audio-speak-openmates-welcome-message").map(\.iconName), ["ai", "audio"])
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testUsageDatesNormalizeSecondsMillisecondsAndISOTime() {
        let locale = Locale(identifier: "en_US"), zone = TimeZone(secondsFromGMT: 0)!
        let values = ["1790856000", "1790856000000", "2026-10-01T12:00:00Z"]
        let formatted = values.map { ChatSettingsUsageRow.formatTimestamp($0, locale: locale, timeZone: zone) }
        XCTAssertEqual(Set(formatted).count, 1)
        XCTAssertTrue(formatted[0].contains("2026"))
        XCTAssertEqual(ChatSettingsUsageRow.formatTimestamp("invalid"), "")
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.receipt-token-breakdown
    func testUsageReceiptKeepsCacheCategoriesAndDecimalCharges() throws {
        let json = #"{"id":"usage-1","created_at":"2026-10-06T12:00:00Z","input_tokens":100,"output_tokens":20,"system_prompt_tokens":40,"user_input_tokens":10,"llm_usage_breakdown":{"schema_version":1,"input_tokens":100,"uncached_input_tokens":50,"cache_read_input_tokens":30,"cache_creation_input_tokens":20,"output_tokens":20,"usage_source":"provider","entries":[{"model_id":"model","inference_host":"bedrock","pricing_version":"v1","write_billing":"separate","input_tokens":100,"uncached_input_tokens":50,"cache_read_input_tokens":30,"cache_creation_input_tokens":20,"cache_creation_5m_input_tokens":20,"cache_creation_1h_input_tokens":null,"output_tokens":20,"rates":{"input":"0.01","cache_read":"0.001","cache_write":"0.02","output":"0.05"},"category_credits":{"input":"0.5","cache_read":"0.03","cache_write":"0.4","cache_write_1h":"0","output":"1"},"raw_credits":"1.93"}],"raw_credits":"1.93","rounding_adjustment":"0.07","credits_charged":2}}"#
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let withBand = json
            .replacingOccurrences(of: "\"pricing_version\":\"v1\"", with: "\"pricing_version\":\"v1\",\"context_band\":\"over_272k\"")
            .replacingOccurrences(of: "\"input\":\"0.01\"", with: "\"input\":\"82.5\"")
        let row = try decoder.decode(ChatSettingsUsageRow.self, from: Data(withBand.utf8))
        let receipt = try XCTUnwrap(row.llmUsageBreakdown)
        XCTAssertEqual(receipt.uncachedInputTokens + (receipt.cacheReadInputTokens ?? 0) + (receipt.cacheCreationInputTokens ?? 0), receipt.inputTokens)
        XCTAssertEqual(receipt.entries[0].categoryCredits.cacheRead.text, "0.03")
        XCTAssertEqual(receipt.entries[0].rates.cacheWrite?.text, "0.02")
        XCTAssertEqual(receipt.entries[0].writeBilling, "separate")
        XCTAssertEqual(receipt.entries[0].contextBand, "over_272k")
        XCTAssertNil(receipt.entries[0].purpose)
        XCTAssertEqual(receipt.entries[0].rates.input?.text, "82.5")
        XCTAssertEqual(receipt.entries[0].pricedInputTokens, 50)
        XCTAssertEqual(receipt.entries[0].cacheCreation5mInputTokens, 20)
        XCTAssertEqual(receipt.entries[0].categoryCredits.cacheWrite1h.text, "0")
        XCTAssertEqual(row.systemPromptTokens, 40)
        XCTAssertNil(receipt.entries[0].rates.cacheWrite1h)
        XCTAssertEqual(receipt.roundingAdjustment.text, "0.07")
        XCTAssertEqual(receipt.creditsCharged, 2)
        XCTAssertNil(try decoder.decode(ChatSettingsUsageRow.self, from: Data(#"{"id":"legacy"}"#.utf8)).llmUsageBreakdown)
        let summary = json
            .replacingOccurrences(of: "\"model_id\":\"model\"", with: "\"model_id\":\"gemini-3.5-flash-lite\",\"purpose\":\"summary\"")
            .replacingOccurrences(of: "\"input\":\"0.01\"", with: "\"input\":\"1100\"")
            .replacingOccurrences(of: "\"output\":\"0.05\"", with: "\"output\":\"130\"")
        let summaryRow = try decoder.decode(ChatSettingsUsageRow.self, from: Data(summary.utf8))
        XCTAssertEqual(summaryRow.llmUsageBreakdown?.entries[0].purpose, "summary")
        XCTAssertEqual(summaryRow.llmUsageBreakdown?.entries[0].rates.input?.text, "1100")
        XCTAssertEqual(summaryRow.llmUsageBreakdown?.entries[0].rates.output?.text, "130")
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.receipt-token-breakdown
    func testReceiptDecodesOneHourCacheRateWithSnakeCaseStrategy() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let rates = try decoder.decode(LLMUsageBreakdown.Rates.self, from: Data(#"{"cache_write_1h":"350"}"#.utf8))
        XCTAssertEqual(rates.cacheWrite1h?.text, "350")
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.receipt-token-breakdown
    func testOrdinaryInputFallbackPricesKnownInputWithoutChangingPhysicalCategories() throws {
        let json = #"{"model_id":"model","inference_host":null,"pricing_version":"v1","billing_mode":"ordinary_input","billed_input_tokens":150,"input_tokens":150,"uncached_input_tokens":100,"cache_read_input_tokens":50,"cache_creation_input_tokens":0,"output_tokens":20,"rates":{"input":"1000","output":"200"},"category_credits":{"input":"0.15","cache_read":"0","cache_write":"0","cache_write_1h":"0","output":"0.1"},"raw_credits":"0.25"}"#
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let entry = try decoder.decode(LLMUsageBreakdown.Entry.self, from: Data(json.utf8))
        XCTAssertTrue(entry.usesOrdinaryInputFallback)
        XCTAssertEqual(entry.pricedInputTokens, 150)
        XCTAssertEqual(entry.uncachedInputTokens, 100)
        XCTAssertEqual(entry.cacheReadInputTokens, 50)
        XCTAssertNil(entry.inferenceHost)
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testAllActivePlansSurviveProjectionAndOnlyClosedPlansAreHidden() {
        let active = (1...8).map { ChatSettingsPlanningRow(id: "plan-\($0)", title: "Plan \($0)", detail: "", status: "active") }
        let rows = active + [.init(id: "closed", title: "Closed", detail: "", status: "completed"), .init(id: "archived", title: "Archived", detail: "", status: "archived")]
        XCTAssertEqual(ChatSettingsProjection.activePlans(rows).map(\.id), active.map(\.id))
    }
    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testTabActivationRefreshesOwnerPlanningAndExcludesInitialPublicAndRecipientLoads() {
        func action(_ tab: ChatSettingsTab, initialized: Bool = true, preview: Bool = false, example: Bool = false, shared: Bool = false) -> ChatSettingsRefreshAction {
            ChatSettingsRefreshPolicy.action(tab: tab, initialized: initialized, preview: preview, example: example, shared: shared)
        }
        XCTAssertEqual([ChatSettingsTab.plan, .tasks, .share, .plan].map { action($0) }, [.planning, .planning, .none, .planning])
        XCTAssertEqual(action(.usage), .usage)
        for tab in ChatSettingsTab.allCases {
            XCTAssertEqual(action(tab, initialized: false), .none)
            XCTAssertEqual(action(tab, preview: true), .none)
            XCTAssertEqual(action(tab, example: true), .none)
            XCTAssertEqual(action(tab, shared: true), .none)
        }
    }
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testShortenerFailurePreservesFullEncryptedLinkPasswordExpiryAndPublication() async throws {
        let id = "fallback-fixture", bytes = Data(repeating: 7, count: 32)
        let blob = try await ShareLinkCrypto.encryptedShareBlob(identifier: id, key: SymmetricKey(data: bytes),
            duration: .tenMinutes, password: "fixturePwd", keyField: "chat_encryption_key")
        let full = try ShareLinkCrypto.urlWithFragment(ServerProfile.development.webBaseURL.appendingPathComponent("share/chat/\(id)"), fragment: "key=\(blob)")
        let failures: [Error] = [APIError.httpError(status: 503, message: "Synthetic failure"), URLError(.timedOut), URLError(.notConnectedToInternet)]
        for failure in failures {
            var published: URL?
            let result = try await ShareLinkPublication.create(longURL: full, check: {}, shorten: { throw failure }, publish: { url, fallback in
                XCTAssertTrue(fallback); published = url
            })
            XCTAssertEqual(result.url, full); XCTAssertEqual(published, full); XCTAssertTrue(result.usedLongFallback)
        }
        let decoded = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: Int(Date().timeIntervalSince1970), password: "fixturePwd")
        XCTAssertEqual(decoded.withUnsafeBytes { Data($0) }, bytes)
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: Int(Date().timeIntervalSince1970), password: nil)
            XCTFail("Fallback must retain the password requirement")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .passwordRequired) }
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: Int(Date().timeIntervalSince1970) + 601, password: "fixturePwd")
            XCTFail("Fallback must retain the ten-minute expiry")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .expired) }
    }
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testSuccessfulShortenerReturnsPrimaryURLOnlyAfterPublication() async throws {
        let full = try XCTUnwrap(URL(string: "https://example.invalid/share/chat/fixture#key=synthetic"))
        let short = try XCTUnwrap(URL(string: "https://example.invalid/s/fixture#synthetic"))
        var published = false
        let result = try await ShareLinkPublication.create(longURL: full, check: {}, shorten: { short }, publish: { url, fallback in
            XCTAssertEqual(url, short); XCTAssertFalse(fallback); published = true
        })
        XCTAssertTrue(published); XCTAssertEqual(result.url, short); XCTAssertFalse(result.usedLongFallback)
    }
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testPublicationFailureNeverReturnsASuccessfulShortOrFullLink() async throws {
        let full = try XCTUnwrap(URL(string: "https://example.invalid/share/chat/fixture#key=synthetic"))
        for shortenerFails in [false, true] {
            do {
                _ = try await ShareLinkPublication.create(longURL: full, check: {}, shorten: {
                    if shortenerFails { throw URLError(.timedOut) }; return full
                }, publish: { _, _ in throw APIError.httpError(status: 403, message: "Synthetic owner denial") })
                XCTFail("Owner publication failure cannot expose a usable link")
            } catch { guard case APIError.httpError(status: 403, message: _) = error else { return XCTFail("Publication denial must propagate") } }
        }
    }
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testAccountFenceAndCancellationAbortFallbackBeforePublication() async throws {
        let full = try XCTUnwrap(URL(string: "https://example.invalid/share/chat/fixture#key=synthetic"))
        var checks = 0, publications = 0
        do {
            _ = try await ShareLinkPublication.create(longURL: full, check: {
                checks += 1; if checks > 1 { throw UserTasksError.accountChanged }
            }, shorten: { throw URLError(.timedOut) }, publish: { _, _ in publications += 1 })
            XCTFail("An account change must abort fallback")
        } catch { guard case UserTasksError.accountChanged = error else { return XCTFail("Account fence must abort sharing") } }
        do {
            _ = try await ShareLinkPublication.create(longURL: full, check: {}, shorten: { throw CancellationError() }, publish: { _, _ in publications += 1 })
            XCTFail("Cancelled shortening must abort sharing")
        } catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertEqual(publications, 0)
    }
    private func fixtureChat() -> Chat {
        Chat(id: "synthetic-chat", title: "Synthetic chat", lastMessageAt: nil, createdAt: "2026-10-01", updatedAt: nil, isArchived: false, isPinned: false, appId: nil, encryptedTitle: nil, encryptedChatKey: nil)
    }
}
