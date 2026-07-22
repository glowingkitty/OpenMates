// Unit coverage for skill, application, code, and file/media parity fixtures.
// These tests use debug-only synthetic fixtures and never touch provider APIs,
// user files, private hosts, code-run logs, secrets, or network state.

import XCTest
@testable import OpenMates

final class SkillApplicationParityTests: XCTestCase {
    func testShortcutSkillFormatterUnwrapsRestSdkEnvelope() throws {
        let response: [String: Any] = [
            "success": true,
            "data": [
                "results": [
                    [
                        "id": 1,
                        "results": [
                            [
                                "title": "Open Air Concert",
                                "date_start": "2026-07-10T19:00:00Z",
                                "venue": [
                                    "name": "Park Stage",
                                    "city": "Berlin",
                                ],
                            ],
                        ],
                        "total_available": 1,
                    ],
                ],
            ],
            "credits_charged": 1,
        ]

        let formatted = SkillFormatter.formatResults(response, type: "events")

        XCTAssertFalse(formatted.contains("No details available"))
        XCTAssertTrue(formatted.contains("Open Air Concert"))
        XCTAssertTrue(formatted.contains("Starts: 2026-07-10T19:00:00Z"))
        XCTAssertTrue(formatted.contains("Venue: Park Stage, Berlin"))
    }

    func testShortcutSkillFormatterPreservesUnknownPayloadAsJson() throws {
        let response: [String: Any] = [
            "success": true,
            "data": [
                "answer": "42",
                "confidence": "high",
            ],
        ]

        let formatted = SkillFormatter.formatResults(response, type: "unknown")

        XCTAssertFalse(formatted.contains("No details available"))
        XCTAssertTrue(formatted.contains("\"answer"))
        XCTAssertTrue(formatted.contains("42"))
    }

    func testCodeFixturesClassifyApplicationCodeAndDocsStates() throws {
        let codeSkills = DevEmbedPreviewFixtures.skills(for: .code)
        let skillsById = Dictionary(uniqueKeysWithValues: codeSkills.map { ($0.id, $0) })

        let code = try XCTUnwrap(skillsById["code-code"]?.primaryEmbed)
        XCTAssertEqual(code.type, EmbedType.codeCode.rawValue)
        XCTAssertEqual(code.appId, "code")
        XCTAssertEqual(code.rawData?["language"]?.value as? String, "svelte")
        XCTAssertEqual(code.rawData?["filename"]?.value as? String, "MyComponent.svelte")
        XCTAssertFalse(code.isAppSkillUse)

        let application = try XCTUnwrap(skillsById["code-application"]?.primaryEmbed)
        XCTAssertEqual(application.type, EmbedType.codeApplication.rawValue)
        XCTAssertEqual(application.appId, "code")
        XCTAssertEqual(application.status, .finished)
        XCTAssertEqual(application.rawData?["title"]?.value as? String, "Habit Garden")
        XCTAssertEqual(application.rawData?["framework"]?.value as? String, "vite")
        XCTAssertFalse(application.isAppSkillUse)

        let docs = try XCTUnwrap(skillsById["code-get-docs"]?.primaryEmbed)
        XCTAssertTrue(docs.isAppSkillUse)
        XCTAssertEqual(docs.type, EmbedType.codeGetDocs.rawValue)
        XCTAssertEqual(docs.appId, "code")
        XCTAssertEqual(docs.skillId, "get_docs")
        XCTAssertEqual(docs.rawData?["library"]?.value as? String, "svelte")
    }

    func testCompositeSkillFixturesPreserveChildEmbedRelationships() throws {
        let webSearch = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .web).first { $0.id == "web-search" }
        )

        XCTAssertTrue(webSearch.primaryEmbed.isAppSkillUse)
        XCTAssertEqual(webSearch.primaryEmbed.type, EmbedType.webSearch.rawValue)
        XCTAssertEqual(webSearch.primaryEmbed.childEmbedIds, webSearch.childEmbeds.map(\.id))
        XCTAssertEqual(webSearch.childEmbeds.count, 3)

        for child in webSearch.childEmbeds {
            XCTAssertEqual(child.type, EmbedType.webWebsite.rawValue)
            XCTAssertEqual(child.parentEmbedId, webSearch.primaryEmbed.id)
            XCTAssertNotNil(webSearch.allRecords[child.id])
        }
    }

    func testRelatedEmbedGraphIncludesChildrenForReferencedCompositeParent() throws {
        let webSearch = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .web).first { $0.id == "web-search" }
        )
        let shuffled = Array(webSearch.childEmbeds.reversed()) + [webSearch.primaryEmbed]

        let related = EmbedRecord.relatedRecords(
            referencedIds: [webSearch.primaryEmbed.id],
            from: shuffled,
            context: "test.relatedGraph"
        )

        XCTAssertEqual(Set(related.map(\.id)), Set(webSearch.allRecords.keys))
    }

    func testSearchPreviewModelUsesParentPreviewMetadataWithoutChildHydration() throws {
        let parent = EmbedRecord(
            id: "metadata-only-news-parent",
            type: EmbedType.newsSearch.rawValue,
            status: .finished,
            data: .raw([
                "app_id": AnyCodable("news"),
                "skill_id": AnyCodable("search"),
                "query": AnyCodable("privacy ai"),
                "provider": AnyCodable("Brave Search"),
                "result_count": AnyCodable(2),
                "embed_ids": AnyCodable(["child-1", "child-2"]),
                "preview_results": AnyCodable([
                    [
                        "title": "OpenMates privacy launch",
                        "url": "https://news.example/openmates",
                        "favicon": "https://news.example/favicon.ico",
                    ]
                ]),
            ]),
            parentEmbedId: nil,
            appId: "news",
            skillId: "search",
            embedIds: "child-1|child-2",
            createdAt: "2026-06-21T12:00:00Z"
        )

        let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.previewResultCount, 2)
        XCTAssertEqual(model.websiteResults.map(\.title), ["OpenMates privacy launch"])
        XCTAssertTrue(model.websiteResults.first?.faviconURL?.contains("news.example") == true)
    }

    func testPersistedWebSearchResolvesReferencedChildrenAndFaviconMetadata() throws {
        let parent = EmbedRecord(
            id: "persisted-web-search",
            type: EmbedType.webSearch.rawValue,
            status: .finished,
            data: .raw([
                "query": AnyCodable("native embed parity"),
                "result_count": AnyCodable(2),
                "embed_ids": AnyCodable(["persisted-web-child-1", "persisted-web-child-2"]),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: "persisted-web-child-1|persisted-web-child-2",
            createdAt: "2026-07-12T00:00:00Z"
        )
        let firstChild = EmbedRecord(
            id: "persisted-web-child-1",
            type: EmbedType.webWebsite.rawValue,
            status: .finished,
            data: .raw([
                "url": AnyCodable("https://example.com/one"),
                "favicon": AnyCodable("https://example.com/favicon.ico"),
            ]),
            parentEmbedId: parent.id,
            appId: "web",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-07-12T00:00:01Z"
        )
        let secondChild = EmbedRecord(
            id: "persisted-web-child-2",
            type: EmbedType.webWebsite.rawValue,
            status: .finished,
            data: .raw(["url": AnyCodable("https://example.org/two")]),
            parentEmbedId: parent.id,
            appId: "web",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-07-12T00:00:02Z"
        )

        let model = SearchSkillPreviewModel(
            embed: parent,
            allEmbedRecords: [parent.id: parent, firstChild.id: firstChild, secondChild.id: secondChild]
        )

        XCTAssertEqual(model.websiteResults.map { $0.embed.id }, [firstChild.id, secondChild.id])
        XCTAssertEqual(model.previewResultCount, 2)
        XCTAssertTrue(model.websiteResults.first?.faviconURL?.contains("example.com") == true)
    }

    @MainActor
    func testBusinessCompanyFinancialsModelPreservesSecFilingMetadata() throws {
        let parent = EmbedRecord(
            id: "business-financials-parent",
            type: EmbedType.businessCompanyFinancials.rawValue,
            status: .finished,
            data: .raw([
                "type": AnyCodable("app_skill_use"),
                "app_id": AnyCodable("business"),
                "skill_id": AnyCodable("company_financials"),
                "query": AnyCodable("VITL"),
                "provider": AnyCodable("SEC EDGAR"),
                "period": AnyCodable("latest_annual"),
                "metric_group": AnyCodable("summary"),
                "result_count": AnyCodable(1),
                "embed_ids": AnyCodable(["business-financials-child"]),
            ]),
            parentEmbedId: nil,
            appId: "business",
            skillId: "company_financials",
            embedIds: "business-financials-child",
            createdAt: "2026-07-20T00:00:00Z"
        )
        let child = EmbedRecord(
            id: "business-financials-child",
            type: EmbedType.businessCompanyFinancialResult.rawValue,
            status: .finished,
            data: .raw(Self.businessFinancialResultData),
            parentEmbedId: parent.id,
            appId: "business",
            skillId: "company_financials",
            embedIds: nil,
            createdAt: "2026-07-20T00:00:01Z"
        )

        let model = BusinessCompanyFinancialsModel(
            embed: parent,
            allEmbedRecords: [parent.id: parent, child.id: child]
        )
        let result = try XCTUnwrap(model.financialResults.first)

        XCTAssertEqual(EmbedType.businessCompanyFinancials.childType, .businessCompanyFinancialResult)
        XCTAssertTrue(EmbedType.businessCompanyFinancials.isComposite)
        XCTAssertEqual(EmbedType.businessCompanyFinancialResult.appId, "business")
        XCTAssertEqual(model.query, "VITL")
        XCTAssertEqual(model.provider, "SEC EDGAR")
        XCTAssertEqual(model.resultCount, 1)
        XCTAssertTrue(model.resultSummary.contains("SEC EDGAR"))
        XCTAssertEqual(result.company, "Vital Farms, Inc.")
        XCTAssertEqual(result.periodLabel, "FY 2025")
        XCTAssertEqual(result.revenue, "USD 759.4M")
        XCTAssertEqual(result.netIncome, "USD 66.3M")
        XCTAssertEqual(result.sourceMetadata, "10-K · 0001193125-26-073423 · 2026-02-26")
        XCTAssertEqual(result.sourceURL, "https://www.sec.gov/Archives/edgar/data/000119312526073423/")
        XCTAssertFalse(model.resultSummary.localizedCaseInsensitiveContains("buy"))
        XCTAssertFalse(model.resultSummary.localizedCaseInsensitiveContains("sell"))
        XCTAssertFalse(result.metricRows.map(\.label).joined(separator: " ").localizedCaseInsensitiveContains("advice"))
    }

    @MainActor
    func testBusinessCompanyFinancialsModelUsesInlineLegacyResults() throws {
        let parent = EmbedRecord(
            id: "business-financials-inline-parent",
            type: EmbedType.businessCompanyFinancials.rawValue,
            status: .finished,
            data: .raw([
                "type": AnyCodable("app_skill_use"),
                "app_id": AnyCodable("business"),
                "skill_id": AnyCodable("company_financials"),
                "query": AnyCodable("VITL"),
                "provider": AnyCodable("SEC EDGAR"),
                "results": AnyCodable([Self.businessFinancialResultData.mapValues(\.value)]),
            ]),
            parentEmbedId: nil,
            appId: "business",
            skillId: "company_financials",
            embedIds: nil,
            createdAt: "2026-07-20T00:00:00Z"
        )

        let model = BusinessCompanyFinancialsModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.financialResults.count, 1)
        XCTAssertEqual(model.financialResults.first?.ticker, "VITL")
        XCTAssertEqual(model.financialResults.first?.form, "10-K")
    }

    func testFileMediaFixturesUseSyntheticPublicPayloads() throws {
        let imageUpload = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .images).first { $0.id == "images-upload" }?.primaryEmbed
        )
        XCTAssertEqual(imageUpload.type, EmbedType.image.rawValue)
        XCTAssertEqual(imageUpload.rawData?["filename"]?.value as? String, "golden-gate-sunset.jpg")
        XCTAssertNil(imageUpload.rawData?["private_url"])
        XCTAssertNil(imageUpload.rawData?["secret"])

        let pdf = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .pdf).first { $0.id == "pdf" }?.primaryEmbed
        )
        XCTAssertEqual(pdf.type, EmbedType.pdf.rawValue)
        XCTAssertEqual(pdf.rawData?["filename"]?.value as? String, "Q4 2025 Report.pdf")
        XCTAssertEqual(pdf.rawData?["page_count"]?.value as? Int, 18)

        let generatedVideo = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .videos).first { $0.id == "videos-generate" }?.primaryEmbed
        )
        XCTAssertTrue(generatedVideo.isAppSkillUse)
        XCTAssertEqual(generatedVideo.type, EmbedType.videosGenerate.rawValue)
        XCTAssertEqual(generatedVideo.rawData?["title"]?.value as? String, "Product launch promo")
    }

    func testFinanceCheckAccountsFixtureUsesRegisteredAppSkillType() throws {
        let embed = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .finance).first { $0.id == "finance-check-accounts" }?.primaryEmbed
        )

        XCTAssertTrue(embed.isAppSkillUse)
        XCTAssertEqual(embed.type, EmbedType.financeCheckAccounts.rawValue)
        XCTAssertEqual(EmbedType.financeCheckAccounts.displayName, "Check accounts")
        XCTAssertEqual(embed.appId, "finance")
        XCTAssertEqual(embed.skillId, "check_accounts")
        XCTAssertEqual(embed.rawData?["account_count"]?.value as? Int, 2)
        XCTAssertNil(embed.rawData?["secret"])
    }

    func testDiagramsMermaidFixtureDecodesSourcePayload() throws {
        let diagramsSkills = DevEmbedPreviewFixtures.skills(for: .diagrams)
        let mermaid = try XCTUnwrap(diagramsSkills.first { $0.id == "diagrams-mermaid" }?.primaryEmbed)

        XCTAssertEqual(mermaid.type, EmbedType.diagramsMermaid.rawValue)
        XCTAssertEqual(EmbedType.diagramsMermaid.appId, "diagrams")
        XCTAssertEqual(EmbedType.diagramsMermaid.displayName, "Diagram")
        XCTAssertEqual(mermaid.appId, "diagrams")
        XCTAssertEqual(mermaid.skillId, "mermaid")
        XCTAssertEqual(mermaid.rawData?["title"]?.value as? String, "Signup Flow")
        XCTAssertEqual(mermaid.rawData?["diagram_kind"]?.value as? String, "sequenceDiagram")
        XCTAssertTrue((mermaid.rawData?["diagram_code"]?.value as? String ?? "").contains("User->>App"))
    }

    private static var businessFinancialResultData: [String: AnyCodable] {
        [
            "type": AnyCodable("company_financial_result"),
            "app_id": AnyCodable("business"),
            "skill_id": AnyCodable("company_financials"),
            "company": AnyCodable("Vital Farms, Inc."),
            "ticker": AnyCodable("VITL"),
            "period_type": AnyCodable("annual"),
            "fiscal_year": AnyCodable(2025),
            "fiscal_quarter": AnyCodable("FY"),
            "period_start": AnyCodable("2024-12-30"),
            "period_end": AnyCodable("2025-12-28"),
            "filed": AnyCodable("2026-02-26"),
            "form": AnyCodable("10-K"),
            "currency": AnyCodable("USD"),
            "revenue": AnyCodable(759_444_000),
            "gross_profit": AnyCodable(285_682_000),
            "operating_income": AnyCodable(88_373_000),
            "net_income": AnyCodable(66_282_000),
            "operating_cash_flow": AnyCodable(33_715_000),
            "source_url": AnyCodable("https://www.sec.gov/Archives/edgar/data/000119312526073423/"),
            "accession_number": AnyCodable("0001193125-26-073423"),
            "notes": AnyCodable(["assets was not available in standardized SEC facts"]),
        ]
    }
}
