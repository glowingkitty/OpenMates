// Unit coverage for skill, application, code, and file/media parity fixtures.
// These tests use debug-only synthetic fixtures and never touch provider APIs,
// user files, private hosts, code-run logs, secrets, or network state.

import XCTest
@testable import OpenMates

@MainActor
final class SkillApplicationParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testCodeFixturesClassifyApplicationCodeAndDocsStates() throws {
        let codeSkills = DevEmbedPreviewFixtures.skills(for: .code)
        let skillsById = Dictionary(uniqueKeysWithValues: codeSkills.map { ($0.id, $0) })

        let code = try XCTUnwrap(skillsById["code-code"]?.primaryEmbed)
        XCTAssertEqual(code.type, EmbedType.codeCode.rawValue)
        XCTAssertEqual(code.appId, "code")
        let normalizedCode = AppleCodeEmbedContent(data: code.rawData)
        XCTAssertEqual(normalizedCode.language, "html")
        XCTAssertEqual(normalizedCode.filename, "index.html")
        XCTAssertTrue(normalizedCode.code.contains("Rendered index.html"))
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCompositeSkillFixturesPreserveChildEmbedRelationships() throws {
        let webSearch = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .web).first { $0.id == "web-search" }
        )

        XCTAssertTrue(webSearch.primaryEmbed.isAppSkillUse)
        XCTAssertEqual(webSearch.primaryEmbed.type, EmbedType.webSearch.rawValue)
        XCTAssertEqual(webSearch.primaryEmbed.childEmbedIds, webSearch.childEmbeds.map(\.id))
        XCTAssertEqual(webSearch.childEmbeds.count, 4)

        for child in webSearch.childEmbeds {
            XCTAssertEqual(child.type, EmbedType.webWebsite.rawValue)
            XCTAssertEqual(child.parentEmbedId, webSearch.primaryEmbed.id)
            XCTAssertNotNil(webSearch.allRecords[child.id])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
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

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testPersistedWebSearchUsesInlineResultsToonWhenChildRecordsAreMissing() throws {
        let parent = EmbedRecord(
            id: "inline-results-web-search",
            type: EmbedType.webSearch.rawValue,
            status: .finished,
            data: .raw([
                "type": AnyCodable("app_skill_use"),
                "app_id": AnyCodable("web"),
                "skill_id": AnyCodable("search"),
                "query": AnyCodable("OpenMates Apple app"),
                "provider": AnyCodable("Brave Search"),
                "result_count": AnyCodable(1),
                "results_toon": AnyCodable("""
                    results[1]{embed_id,title,url,snippet}:
                      cited-result,OpenMates,https://openmates.org,Private AI assistants
                    """),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: nil,
            createdAt: "2026-09-23T00:00:00Z"
        )

        let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.websiteResults.map(\.id), ["cited-result"])
        XCTAssertEqual(model.websiteResults.map(\.title), ["OpenMates"])
        XCTAssertEqual(model.previewResultCount, 1)
        XCTAssertTrue(EmbedRecord.unresolvedCompositeParentIds(
            referencedIds: [parent.id],
            from: [parent],
            context: "test.inlineResultsToon"
        ).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity,chats.rendering.inline-entity-interaction
    func testPersistedWebSearchDecodesListToonAndPairsRowsWithDeclaredChildIds() throws {
        let parent = EmbedRecord(
            id: "list-results-web-search",
            type: EmbedType.webSearch.rawValue,
            status: .finished,
            data: .raw([
                "type": AnyCodable("app_skill_use"),
                "app_id": AnyCodable("web"),
                "skill_id": AnyCodable("search"),
                "query": AnyCodable("OpenAI Anthropic headlines"),
                "provider": AnyCodable("Brave Search"),
                "result_count": AnyCodable(2),
                "results_toon": AnyCodable("""
                    results[2]:
                      - type: search_result
                        title: "First headline"
                        url: "https://example.com/first"
                        description: "First summary"
                      - type: search_result
                        title: "Second headline"
                        url: "https://example.com/second"
                        meta_url_favicon: "https://example.com/favicon.ico"
                    count: 2
                    """),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: "result-first|result-second",
            createdAt: "2026-09-24T00:00:00Z"
        )

        let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.websiteResults.map(\.id), ["result-first", "result-second"])
        XCTAssertEqual(model.websiteResults.map(\.title), ["First headline", "Second headline"])
        XCTAssertEqual(model.websiteResults.map(\.url), ["https://example.com/first", "https://example.com/second"])
        XCTAssertTrue(model.websiteResults.last?.faviconURL?.contains("example.com/favicon.ico") == true)
        XCTAssertEqual(model.previewResultCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testPersistedWebSearchUsesInlineResultsArrayWhenChildRecordsAreMissing() throws {
        let parent = EmbedRecord(
            id: "inline-results-array-web-search",
            type: EmbedType.webSearch.rawValue,
            status: .finished,
            data: .raw([
                "query": AnyCodable("native results"),
                "provider": AnyCodable("Brave Search"),
                "results": AnyCodable([[
                    "title": "Native result",
                    "url": "https://example.com/native",
                ]]),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: nil,
            createdAt: "2026-09-23T00:00:00Z"
        )

        let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.websiteResults.map(\.title), ["Native result"])
        XCTAssertEqual(model.previewResultCount, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testPersistedWebSearchFlattensGroupedInlineResults() throws {
        let parent = EmbedRecord(
            id: "grouped-results-web-search",
            type: EmbedType.webSearch.rawValue,
            status: .finished,
            data: .raw([
                "query": AnyCodable("grouped native results"),
                "results": AnyCodable([[
                    "id": "request-1",
                    "results": [[
                        "title": "Grouped result",
                        "url": "https://example.com/grouped",
                    ]],
                ]]),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: nil,
            createdAt: "2026-09-23T00:00:00Z"
        )

        let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.websiteResults.map(\.title), ["Grouped result"])
        XCTAssertEqual(model.websiteResults.map(\.url), ["https://example.com/grouped"])
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testPersistedWebSearchMergesPartiallyHydratedChildrenOverInlineResults() throws {
        let parent = EmbedRecord(
            id: "partially-hydrated-web-search",
            type: EmbedType.webSearch.rawValue,
            status: .finished,
            data: .raw([
                "query": AnyCodable("native child graph"),
                "result_count": AnyCodable(2),
                "results_toon": AnyCodable("""
                    results[2]{embed_id,title,url}:
                      web-b,Inline B,https://example.com/b
                      web-a,Inline A,https://example.com/a
                    count: 2
                    """),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: "web-b|web-a",
            createdAt: "2026-09-23T00:00:00Z"
        )
        let hydrated = EmbedRecord(
            id: "web-a",
            type: EmbedType.webWebsite.rawValue,
            status: .finished,
            data: .raw([
                "title": AnyCodable("Hydrated A"),
                "url": AnyCodable("https://example.com/a"),
            ]),
            parentEmbedId: parent.id,
            appId: "web",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-09-23T00:00:01Z"
        )

        let model = SearchSkillPreviewModel(
            embed: parent,
            allEmbedRecords: [parent.id: parent, hydrated.id: hydrated]
        )

        XCTAssertEqual(model.websiteResults.map(\.id), ["web-b", "web-a"])
        XCTAssertEqual(model.websiteResults.map(\.title), ["Inline B", "Hydrated A"])
        XCTAssertEqual(model.previewResultCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRepositorySearchResolvesPersistedChildEmbedsInParentOrder() throws {
        let parent = EmbedRecord(
            id: "persisted-repository-search",
            type: EmbedType.codeRepoSearch.rawValue,
            status: .finished,
            data: .raw([
                "query": AnyCodable("swift encrypted chat"),
                "provider": AnyCodable("GitHub"),
                "result_count": AnyCodable(2),
            ]),
            parentEmbedId: nil,
            appId: "code",
            skillId: "search_repos",
            embedIds: "repository-b|repository-a",
            createdAt: "2026-09-23T00:00:00Z"
        )
        let first = EmbedRecord(
            id: "repository-a",
            type: EmbedType.codeRepo.rawValue,
            status: .finished,
            data: .raw(["full_name": AnyCodable("openmates/apple-a"), "url": AnyCodable("https://github.com/openmates/apple-a")]),
            parentEmbedId: parent.id,
            appId: "code",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-09-23T00:00:01Z"
        )
        let second = EmbedRecord(
            id: "repository-b",
            type: EmbedType.codeRepo.rawValue,
            status: .finished,
            data: .raw(["full_name": AnyCodable("openmates/apple-b"), "url": AnyCodable("https://github.com/openmates/apple-b")]),
            parentEmbedId: parent.id,
            appId: "code",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-09-23T00:00:02Z"
        )

        let model = CodeRepoSearchModel(
            embed: parent,
            allEmbedRecords: [parent.id: parent, first.id: first, second.id: second]
        )

        XCTAssertEqual(model.repositoryEmbeds.map(\.id), [second.id, first.id])
        XCTAssertEqual(model.resultCount, 2)
        XCTAssertEqual(model.resultCountLabel, "2 repositories")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRepositorySearchUsesParentResultsToonUntilChildrenHydrate() throws {
        let parent = EmbedRecord(
            id: "inline-repository-search",
            type: EmbedType.codeRepoSearch.rawValue,
            status: .finished,
            data: .raw([
                "query": AnyCodable("svelte markdown editor"),
                "provider": AnyCodable("GitHub"),
                "result_count": AnyCodable(2),
                "results_toon": AnyCodable("""
                    results[2]{embed_id,full_name,url,stars}:
                      repo-1,openmates/repo-one,https://github.com/openmates/repo-one,128
                      repo-2,openmates/repo-two,https://github.com/openmates/repo-two,64
                    count: 2
                    """),
            ]),
            parentEmbedId: nil,
            appId: "code",
            skillId: "search_repos",
            embedIds: "repo-1|repo-2",
            createdAt: "2026-09-23T00:00:00Z"
        )

        let model = CodeRepoSearchModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.repositoryEmbeds.map(\.id), ["repo-1", "repo-2"])
        XCTAssertEqual(model.repositoryEmbeds.map(\.type), [EmbedType.codeRepo.rawValue, EmbedType.codeRepo.rawValue])
        XCTAssertEqual(model.repositoryEmbeds.first?.rawData?["full_name"]?.value as? String, "openmates/repo-one")
        XCTAssertEqual(model.resultCount, 2)
        XCTAssertEqual(model.resultCountLabel, "2 repositories")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRepositorySearchMergesPartiallyHydratedChildrenOverInlineResults() throws {
        let parent = EmbedRecord(
            id: "partially-hydrated-repository-search",
            type: EmbedType.codeRepoSearch.rawValue,
            status: .finished,
            data: .raw([
                "query": AnyCodable("swift repositories"),
                "result_count": AnyCodable(2),
                "results_toon": AnyCodable("""
                    results[2]{embed_id,full_name,url,stars}:
                      repo-2,openmates/repo-two,https://github.com/openmates/repo-two,64
                      repo-1,openmates/repo-one-inline,https://github.com/openmates/repo-one,128
                    count: 2
                    """),
            ]),
            parentEmbedId: nil,
            appId: "code",
            skillId: "search_repos",
            embedIds: "repo-2|repo-1",
            createdAt: "2026-09-23T00:00:00Z"
        )
        let hydrated = EmbedRecord(
            id: "repo-1",
            type: EmbedType.codeRepo.rawValue,
            status: .finished,
            data: .raw([
                "full_name": AnyCodable("openmates/repo-one-hydrated"),
                "url": AnyCodable("https://github.com/openmates/repo-one"),
            ]),
            parentEmbedId: parent.id,
            appId: "code",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-09-23T00:00:01Z"
        )

        let model = CodeRepoSearchModel(
            embed: parent,
            allEmbedRecords: [parent.id: parent, hydrated.id: hydrated]
        )

        XCTAssertEqual(model.repositoryEmbeds.map(\.id), ["repo-2", "repo-1"])
        XCTAssertEqual(
            model.repositoryEmbeds.map { $0.rawData?["full_name"]?.value as? String },
            ["openmates/repo-two", "openmates/repo-one-hydrated"]
        )
        XCTAssertEqual(model.resultCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
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
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testImageViewSkillResolvesOriginalUploadMediaForPreviewAndFullscreen() throws {
        let upload = EmbedRecord(
            id: "uploaded-image-1",
            type: EmbedType.image.rawValue,
            status: .finished,
            data: .raw([
                "filename": AnyCodable("receipt.png"),
                "s3_base_url": AnyCodable("https://media.example.invalid"),
                "s3_url": AnyCodable("https://direct.example.invalid/original.enc"),
                "files": AnyCodable([
                    "preview": ["s3_key": "preview.enc"],
                    "original": ["s3_key": "original.enc"],
                ]),
                "aes_key": AnyCodable("synthetic-key"),
                "aes_nonce": AnyCodable("synthetic-nonce"),
            ]),
            parentEmbedId: nil,
            appId: "images",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-09-24T00:00:00Z"
        )
        let view = EmbedRecord(
            id: "image-view-1",
            type: "app:images:view",
            status: .finished,
            data: .raw([
                "type": AnyCodable("app_skill_use"),
                "app_id": AnyCodable("images"),
                "skill_id": AnyCodable("view"),
                "embed_id": AnyCodable(upload.id),
            ]),
            parentEmbedId: nil,
            appId: "images",
            skillId: "view",
            embedIds: nil,
            createdAt: "2026-09-24T00:00:01Z"
        )

        let model = ImageViewSkillModel(
            embed: view,
            allEmbedRecords: [view.id: view, upload.id: upload]
        )

        XCTAssertEqual(model.originalEmbedId, upload.id)
        XCTAssertEqual(model.resolvedData?["filename"]?.value as? String, "receipt.png")
        XCTAssertEqual(EmbedMediaPayload.previewS3Key(from: model.resolvedData), "preview.enc")
        XCTAssertEqual(EmbedMediaPayload.s3Key(from: model.resolvedData), "original.enc")
        XCTAssertEqual(
            EmbedMediaPayload.previewS3URL(from: model.resolvedData),
            "https://media.example.invalid/preview.enc"
        )
        XCTAssertEqual(
            EmbedMediaPayload.s3URL(from: model.resolvedData),
            "https://direct.example.invalid/original.enc"
        )
        let noncePrefixedUpload: [String: AnyCodable] = [
            "aes_key": AnyCodable("synthetic-key"),
            "aes_nonce": AnyCodable(""),
            "files": AnyCodable([
                "original": ["s3_key": "original.enc"],
            ]),
        ]
        let missingMetadata: [String: AnyCodable] = [
            "aes_key": AnyCodable("synthetic-key"),
            "files": AnyCodable([
                "original": ["s3_key": "original.enc"],
            ]),
        ]

        XCTAssertEqual(
            EmbedMediaPayload.encryption(from: noncePrefixedUpload),
            S3MediaClient.noncePrefixedEncryption
        )
        XCTAssertNil(EmbedMediaPayload.encryption(from: missingMetadata))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=events-search.surface-parity
    func testBackendEventChildTypeNormalizesToEventsRenderer() throws {
        let record = try JSONDecoder().decode(EmbedRecord.self, from: Data(#"""
        {
          "embed_id": "event-child-1",
          "type": "event",
          "status": "finished",
          "data": {
            "title": "Swift meetup",
            "date_start": "2026-09-24T18:00:00Z",
            "event_type": "PHYSICAL",
            "venue_city": "Berlin",
            "venue_country": "Germany"
          }
        }
        """#.utf8))

        XCTAssertEqual(record.type, EmbedType.eventsEvent.rawValue)
        XCTAssertEqual(EmbedType.normalized(rawValue: "event"), .eventsEvent)
        let summary = EventResultSummary(embedId: record.id, data: try XCTUnwrap(record.rawData))
        XCTAssertEqual(summary.title, "Swift meetup")
        XCTAssertEqual(summary.shortLocation, "Berlin, Germany")
    }

    // contract-test: supporting surface=gui.apple assertions=events-search.surface-parity
    func testEventSearchOnlyUsesExplicitOrParentLinkedChildren() throws {
        let parent = try decodeRecord(#"""
        {
          "embed_id": "event-search-1",
          "type": "app:events:search",
          "status": "finished",
          "embed_ids": ["event-child-1"],
          "data": {"query": "Events in Berlin"}
        }
        """#)
        let linked = try decodeRecord(#"""
        {
          "embed_id": "event-child-1", "type": "event", "status": "finished",
          "parent_embed_id": "event-search-1", "data": {"title": "Linked event"}
        }
        """#)
        let unrelated = try decodeRecord(#"""
        {
          "embed_id": "event-child-2", "type": "event", "status": "finished",
          "parent_embed_id": "another-search", "data": {"title": "Unrelated event"}
        }
        """#)

        let children = EventsSearchEmbedModel.childEmbeds(
            for: parent,
            in: [linked.id: linked, unrelated.id: unrelated]
        )

        XCTAssertEqual(children.map(\.id), [linked.id])
        let summaries = children.map {
            EventResultSummary(embedId: $0.id, data: $0.rawData ?? [:])
        }
        XCTAssertEqual(EventsSearchEmbedModel.query(from: parent.rawData, events: summaries), "Events in Berlin")
        XCTAssertEqual(summaries.map(\.title), ["Linked event"])
    }

    // contract-test: supporting surface=gui.apple assertions=events-search.surface-parity
    func testLegacyResultsToonAndMarkdownDescriptionRenderAsEventContent() throws {
        let data: [String: AnyCodable] = [
            "results_toon": AnyCodable("""
            results[1]{title,date_start,event_type,venue_city,venue_country}:
              Community workshop,2026-09-24T18:00:00Z,PHYSICAL,Berlin,Germany
            """)
        ]

        let event = try XCTUnwrap(EventResultSummary.list(from: data).first)
        XCTAssertEqual(event.title, "Community workshop")
        XCTAssertEqual(event.shortLocation, "Berlin, Germany")
        XCTAssertEqual(String(EventValue.markdown("Meet **local builders**").characters), "Meet local builders")
    }

    private func decodeRecord(_ json: String) throws -> EmbedRecord {
        try JSONDecoder().decode(EmbedRecord.self, from: Data(json.utf8))
    }
}
