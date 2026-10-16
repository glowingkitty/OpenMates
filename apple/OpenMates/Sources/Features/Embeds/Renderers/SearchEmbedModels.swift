// Pure normalization models for search-style embeds.
// Converts raw EmbedRecord graphs into Swift presentation data matching the
// Svelte web/images search preview and fullscreen components.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
//          frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialsEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

// Specification: specifications/features/app-skills/web-search/specification.yml
//                specifications/features/chats/specification.yml
// Assertions: web-search.surface-parity, chats.surface.semantic-parity

import Foundation
import CoreFoundation

struct SearchSkillPreviewModel {
    let embed: EmbedRecord
    let appId: String
    let skillId: String
    let query: String
    let provider: String
    let status: EmbedStatus
    let childEmbeds: [EmbedRecord]
    let previewResultCount: Int

    var websiteResults: [WebsiteResultModel] {
        let childResults = childEmbeds.compactMap(WebsiteResultModel.init(embed:))
        return childResults.isEmpty ? previewRecords.compactMap(WebsiteResultModel.init(embed:)) : childResults
    }

    var imageResults: [ImageSearchResultModel] {
        let childResults = childEmbeds.compactMap(ImageSearchResultModel.init(embed:))
        return childResults.isEmpty ? previewRecords.compactMap(ImageSearchResultModel.init(embed:)) : childResults
    }

    private var previewRecords: [EmbedRecord] {
        Self.previewRecords(from: embed)
    }

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        let raw = embed.rawData ?? [:]
        let typeParts = embed.type.split(separator: ":")
        let inferredAppId = typeParts.count >= 2 && typeParts[0] == "app" ? String(typeParts[1]) : nil
        let inferredSkillId = typeParts.count >= 3 && typeParts[0] == "app" ? String(typeParts[2]) : nil
        self.embed = embed
        let resolvedAppId = embed.appId ?? EmbedFieldReader.string(raw, keys: ["app_id"]) ?? inferredAppId ?? "web"
        appId = resolvedAppId
        skillId = embed.skillId ?? EmbedFieldReader.string(raw, keys: ["skill_id"]) ?? inferredSkillId ?? "search"
        query = AppSkillInputPreviewModel(embed: embed).text
            ?? EmbedFieldReader.string(raw, keys: ["title"])
            ?? EmbedType(rawValue: embed.type)?.displayName ?? skillId
        let fallbackProvider = resolvedAppId == "images" ? "Brave" : "Brave Search"
        provider = EmbedFieldReader.string(raw, keys: ["provider"]).map {
            resolvedAppId == "images" ? $0 : Self.displayProvider($0)
        } ?? fallbackProvider
        status = embed.status
        childEmbeds = Self.resolveChildren(
            for: embed,
            appId: appId,
            inlineRecords: Self.previewRecords(from: embed),
            allEmbedRecords: allEmbedRecords
        )
        previewResultCount = EmbedFieldReader.int(raw, keys: ["result_count"])
            ?? (childEmbeds.isEmpty ? Self.previewRecords(from: embed).count : childEmbeds.count)
    }

    private static func previewRecords(from embed: EmbedRecord) -> [EmbedRecord] {
        let raw = embed.rawData ?? [:]
        let previewResults = ["results", "preview_results", "preview_thumbnails"]
            .lazy.map { EmbedFieldReader.dictionaryArray(raw, key: $0) }
            .first { !$0.isEmpty } ?? []
        let encoded = raw["results_toon"]?.value as? String ?? raw["preview_results_json"]?.value as? String
        let resolvedResults = previewResults.isEmpty
            ? resultsFromEncodedPayload(encoded) : flattenedResults(previewResults)
        let parts = embed.type.split(separator: ":")
        let app = embed.appId ?? EmbedFieldReader.string(raw, keys: ["app_id"])
            ?? (parts.count >= 3 && parts[0] == "app" ? String(parts[1]) : "web")
        guard !resolvedResults.isEmpty else { return [] }

        return resolvedResults.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable(app)
            return EmbedRecord(
                id: EmbedFieldReader.string(recordData, keys: ["embed_id", "id"])
                    ?? (embed.childEmbedIds.indices.contains(index) ? embed.childEmbedIds[index] : nil)
                    ?? "\(embed.id)-preview-\(index)",
                type: Self.previewChildType(appId: app),
                status: .finished,
                data: .raw(recordData),
                parentEmbedId: embed.id,
                appId: app,
                skillId: nil,
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
    }

    fileprivate static func resultsFromEncodedPayload(_ payload: String?) -> [[String: Any]] {
        guard let payload, !payload.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return [] }
        let decoded = EmbedRecord.parseContent(payload)
        if let results = decoded["results"] as? [[String: Any]] { return flattenedResults(results) }
        if let results = decoded["results"] as? [Any] {
            return flattenedResults(results.compactMap { $0 as? [String: Any] })
        }
        // The backend TOON encoder selects a YAML-like list for web search
        // payloads whose rows do not share an identical field set:
        //
        // results[2]:
        //   - type: search_result
        //     title: First result
        //     url: https://example.com
        //
        // EmbedRecord.parseContent handles compact tabular TOON, but older and
        // current persisted chats can contain this list form. Parse each flat
        // result mapping here so the encrypted parent remains a complete
        // rendering fallback while child records hydrate asynchronously.
        let listResults = listResultsFromEncodedPayload(payload)
        if !listResults.isEmpty { return flattenedResults(listResults) }
        return decoded["url"] == nil ? [] : [decoded]
    }

    private static func listResultsFromEncodedPayload(_ payload: String) -> [[String: Any]] {
        let lines = payload.components(separatedBy: .newlines)
        guard let headerIndex = lines.firstIndex(where: { line in
            let value = line.trimmingCharacters(in: .whitespacesAndNewlines)
            return value.hasPrefix("results[") && value.hasSuffix("]:")
        }) else { return [] }

        let headerIndent = indentation(of: lines[headerIndex])
        var rows: [[String: Any]] = []
        var rowLines: [String] = []

        func appendRow() {
            guard !rowLines.isEmpty else { return }
            let decoded = EmbedRecord.parseContent(rowLines.joined(separator: "\n"))
            if !decoded.isEmpty { rows.append(decoded) }
            rowLines.removeAll(keepingCapacity: true)
        }

        for rawLine in lines.dropFirst(headerIndex + 1) {
            let trimmed = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty { continue }
            let indent = indentation(of: rawLine)
            if indent <= headerIndent { break }
            if trimmed.hasPrefix("- ") {
                appendRow()
                rowLines.append(String(trimmed.dropFirst(2)))
            } else if !rowLines.isEmpty {
                rowLines.append(trimmed)
            }
        }
        appendRow()
        return rows
    }

    private static func indentation(of line: String) -> Int {
        line.prefix { $0 == " " || $0 == "\t" }.count
    }

    fileprivate static func flattenedResults(_ rows: [[String: Any]]) -> [[String: Any]] {
        rows.flatMap { row in
            guard let nested = row["results"] as? [Any] else { return [row] }
            let nestedRows = nested.compactMap { $0 as? [String: Any] }
            return nestedRows.isEmpty ? [row] : flattenedResults(nestedRows)
        }
    }

    private static func previewChildType(appId: String) -> String {
        switch appId {
        case "images", "photos": return EmbedType.imagesImageResult.rawValue
        case "videos": return EmbedType.videosVideo.rawValue
        default: return EmbedType.webWebsite.rawValue
        }
    }

    private static func displayProvider(_ provider: String) -> String {
        provider == "Brave" ? "Brave Search" : provider
    }

    private static func resolveChildren(
        for embed: EmbedRecord,
        appId: String,
        inlineRecords: [EmbedRecord],
        allEmbedRecords: [String: EmbedRecord]
    ) -> [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        let hydrated = deduplicated(explicit + parented)
        if !inlineRecords.isEmpty || !hydrated.isEmpty {
            return mergedRecords(
                parentOrder: embed.childEmbedIds,
                inlineRecords: inlineRecords,
                hydratedRecords: hydrated
            )
        }

        let fallback = allEmbedRecords.values
            .filter { child in
                guard child.id != embed.id else { return false }
                let type = EmbedType(rawValue: child.type)
                switch appId {
                case "web", "news":
                    return type == .webWebsite
                case "images", "photos":
                    return type == .imagesImageResult || type == .image
                default:
                    return child.appId == appId
                }
            }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        return deduplicated(fallback)
    }

    /// Preserve the parent's declared result order and full inline fallback,
    /// replacing synthetic rows only when the corresponding decrypted child is
    /// available. A partially hydrated graph must never collapse the grid.
    static func mergedRecords(
        parentOrder: [String],
        inlineRecords: [EmbedRecord],
        hydratedRecords: [EmbedRecord]
    ) -> [EmbedRecord] {
        let inlineById = Dictionary(inlineRecords.map { ($0.id, $0) }, uniquingKeysWith: { _, latest in latest })
        let hydratedById = Dictionary(hydratedRecords.map { ($0.id, $0) }, uniquingKeysWith: { _, latest in latest })
        var seen = Set<String>()
        var resolved: [EmbedRecord] = []

        for id in parentOrder where seen.insert(id).inserted {
            if let record = hydratedById[id] ?? inlineById[id] {
                resolved.append(record)
            }
        }
        for inline in inlineRecords where seen.insert(inline.id).inserted {
            resolved.append(hydratedById[inline.id] ?? inline)
        }
        for hydrated in hydratedRecords where seen.insert(hydrated.id).inserted {
            resolved.append(hydrated)
        }
        return resolved
    }

    private static func deduplicated(_ embeds: [EmbedRecord]) -> [EmbedRecord] {
        var seen = Set<String>()
        return embeds.filter { seen.insert($0.id).inserted }
    }
}

/// Normalized parent/child graph for Code's GitHub repository search. Finished
/// live results can arrive as child embeds, while persisted Apple chat payloads
/// can contain only the parent's encrypted `results_toon` fallback.
@MainActor
struct CodeRepoSearchModel {
    let embed: EmbedRecord
    let query: String
    let provider: String?
    let status: EmbedStatus
    let repositoryEmbeds: [EmbedRecord]
    let resultCount: Int

    var resultCountLabel: String {
        // Match CodeRepoSearchEmbedPreview.svelte's explicit irregular plural.
        let noun = resultCount == 1 ? "repository" : "repositories"
        return "\(resultCount) \(noun)"
    }

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        let raw = embed.rawData ?? [:]
        self.embed = embed
        query = EmbedFieldReader.string(raw, keys: ["query", "title"])
            ?? AppStrings.codeSearchRepos
        provider = EmbedFieldReader.string(raw, keys: ["provider"])
        status = embed.status

        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        let hydrated = Self.deduplicated(explicit + parented)
        repositoryEmbeds = SearchSkillPreviewModel.mergedRecords(
            parentOrder: embed.childEmbedIds,
            inlineRecords: Self.inlineRepositoryEmbeds(parent: embed, raw: raw),
            hydratedRecords: hydrated
        )
        resultCount = EmbedFieldReader.int(raw, keys: ["result_count"])
            ?? (embed.childEmbedIds.isEmpty ? repositoryEmbeds.count : embed.childEmbedIds.count)
    }

    private static func inlineRepositoryEmbeds(
        parent: EmbedRecord,
        raw: [String: AnyCodable]
    ) -> [EmbedRecord] {
        let direct = EmbedFieldReader.dictionaryArray(raw, key: "results")
        let previews = direct.isEmpty
            ? EmbedFieldReader.dictionaryArray(raw, key: "preview_results")
            : direct
        let rows = previews.isEmpty
            ? SearchSkillPreviewModel.resultsFromEncodedPayload(raw["results_toon"]?.value as? String)
            : SearchSkillPreviewModel.flattenedResults(previews)

        return rows.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable("code")
            return EmbedRecord(
                id: EmbedFieldReader.string(recordData, keys: ["embed_id", "id"])
                    ?? "\(parent.id)-repository-\(index)",
                type: EmbedType.codeRepo.rawValue,
                status: .finished,
                data: .raw(recordData),
                parentEmbedId: parent.id,
                appId: "code",
                skillId: nil,
                embedIds: nil,
                createdAt: parent.createdAt
            )
        }
    }

    private static func deduplicated(_ embeds: [EmbedRecord]) -> [EmbedRecord] {
        var seen = Set<String>()
        return embeds.filter { seen.insert($0.id).inserted }
    }
}

struct WebsiteResultModel: Identifiable {
    let id: String
    let embed: EmbedRecord
    let title: String
    let url: String
    let sourceDomain: String
    let faviconURL: String?
    let previewFaviconURL: String?
    let sourceImageURL: String?
    let previewImageURL: String?
    let thumbnailStripURL: String?
    let snippet: String?
    let pageAge: String?

    // WebSearchEmbedFullscreen passes the original search image to its website
    // card, which proxies external hosts but loads local example paths directly.
    // Persisted children often call this preview_image_url; normalize that key
    // without losing the original local/external distinction.
    var cardEmbed: EmbedRecord {
        guard let sourceImageURL else { return embed }
        var raw = embed.rawData ?? [:]
        raw["thumbnail_original"] = AnyCodable(sourceImageURL)
        return EmbedRecord(
            id: embed.id, type: embed.type, status: embed.status,
            data: .raw(raw), encryptedContent: embed.encryptedContent,
            encryptedType: embed.encryptedType, encryptedTextPreview: embed.encryptedTextPreview,
            parentEmbedId: embed.parentEmbedId, appId: embed.appId, skillId: embed.skillId,
            embedIds: embed.embedIds, hashedChatId: embed.hashedChatId,
            hashedMessageId: embed.hashedMessageId, hashedUserId: embed.hashedUserId,
            versionNumber: embed.versionNumber, contentHash: embed.contentHash,
            versionHistory: embed.versionHistory, versionHistoryReadonly: embed.versionHistoryReadonly,
            createdAt: embed.createdAt
        )
    }

    // WebSearchEmbedFullscreen.svelte presents canonical YouTube results with
    // the video card and drill-down, even when persisted as website children.
    var videoEmbed: EmbedRecord? {
        guard let videoID = YouTubeVideoURL.videoID(from: url) else { return nil }
        var raw = embed.rawData ?? [:]
        raw["video_id"] = AnyCodable(videoID)
        let thumbnail = EmbedFieldReader.string(raw, keys: [
            "thumbnail_url", "preview_image_url", "image_url", "thumbnail_original", "thumbnail.original"
        ]) ?? "https://img.youtube.com/vi/\(videoID)/hqdefault.jpg"
        raw["thumbnail_url"] = raw["thumbnail_url"] ?? AnyCodable(thumbnail)
        raw["channel"] = raw["channel"] ?? raw["channel_name"]
        raw["duration"] = raw["duration"] ?? raw["duration_formatted"]
        return EmbedRecord(
            id: embed.id, type: EmbedType.videosVideo.rawValue, status: embed.status,
            data: .raw(raw), encryptedContent: embed.encryptedContent,
            encryptedType: embed.encryptedType, encryptedTextPreview: embed.encryptedTextPreview,
            parentEmbedId: embed.parentEmbedId, appId: "videos", skillId: embed.skillId,
            embedIds: embed.embedIds, hashedChatId: embed.hashedChatId,
            hashedMessageId: embed.hashedMessageId, hashedUserId: embed.hashedUserId,
            versionNumber: embed.versionNumber, contentHash: embed.contentHash,
            versionHistory: embed.versionHistory, versionHistoryReadonly: embed.versionHistoryReadonly,
            createdAt: embed.createdAt
        )
    }

    init?(embed: EmbedRecord) {
        let raw = embed.rawData ?? [:]
        let resolvedURL = EmbedFieldReader.string(raw, keys: ["url"])
        guard let resolvedURL, !resolvedURL.isEmpty else { return nil }
        id = embed.id
        self.embed = embed
        url = resolvedURL
        sourceDomain = EmbedFieldReader.host(from: resolvedURL) ?? resolvedURL
        title = EmbedFieldReader.string(raw, keys: ["title", "site_name", "profile_name"]) ?? sourceDomain
        let rawFavicon = EmbedFieldReader.string(raw, keys: ["favicon", "favicon_url", "meta_url_favicon", "meta_url.favicon"])
        previewFaviconURL = EmbedFieldReader.proxiedImageURL(rawFavicon, maxWidth: 38)
        faviconURL = EmbedFieldReader.proxiedFaviconImageURL(
            directURL: rawFavicon,
            pageURL: resolvedURL
        )
        let rawPreviewImage = EmbedFieldReader.string(raw, keys: [
            "thumbnail_url", "preview_image_url", "image_url",
            "thumbnail_original", "thumbnail.original", "thumbnail_src",
            "thumbnail.src", "image", "meta_image", "og_image"
        ])
        sourceImageURL = rawPreviewImage
        previewImageURL = EmbedFieldReader.proxiedImageURL(rawPreviewImage, maxWidth: 1024)
        thumbnailStripURL = EmbedFieldReader.proxiedImageURL(rawPreviewImage, maxWidth: 520)
        snippet = EmbedFieldReader.strippedHTML(
            EmbedFieldReader.string(raw, keys: ["snippet", "description", "meta_description", "summary"])
        )
        pageAge = EmbedFieldReader.string(raw, keys: ["page_age", "age", "data_date", "date", "published_date"])
    }
}

struct ImageSearchResultModel: Identifiable {
    let id: String
    let embed: EmbedRecord
    let title: String?
    let sourceDomain: String
    let imageURL: String?
    let thumbnailURL: String?
    let faviconURL: String?
    let sourcePageURL: String?

    init?(embed: EmbedRecord) {
        let raw = embed.rawData ?? [:]
        let image = EmbedFieldReader.string(raw, keys: ["image_url", "image", "url"])
        let thumbnail = EmbedFieldReader.string(raw, keys: ["thumbnail_url", "thumbnail_original", "thumbnail"])
        guard image != nil || thumbnail != nil else { return nil }
        id = embed.id
        self.embed = embed
        title = EmbedFieldReader.string(raw, keys: ["title", "name"])
        sourcePageURL = EmbedFieldReader.string(raw, keys: ["source_page_url", "url"])
        sourceDomain = EmbedFieldReader.string(raw, keys: ["source", "source_domain"])
            ?? EmbedFieldReader.host(from: sourcePageURL)
            ?? "Image"
        imageURL = EmbedFieldReader.proxiedImageURL(image, maxWidth: 1024)
        thumbnailURL = EmbedFieldReader.proxiedImageURL(thumbnail ?? image, maxWidth: 520)
        faviconURL = EmbedFieldReader.proxiedImageURL(
            EmbedFieldReader.string(raw, keys: ["favicon_url", "favicon", "meta_url_favicon", "meta_url.favicon"]),
            maxWidth: 64
        )
    }
}

@MainActor
struct BusinessCompanyFinancialsModel {
    let embed: EmbedRecord
    let query: String
    let provider: String
    let periodLabel: String
    let metricGroupLabel: String
    let status: EmbedStatus
    let resultCount: Int
    let childEmbeds: [EmbedRecord]

    var resultSummary: String {
        if resultCount <= 0, status == .finished {
            return AppStrings.businessFinancialsNoResults
        }
        if childEmbeds.isEmpty, resultCount > 0 {
            return AppStrings.businessFinancialsOpenToView
        }
        return "\(AppStrings.businessFinancialsResultsCount(resultCount)) · \(AppStrings.via) \(provider)"
    }

    var financialResults: [BusinessCompanyFinancialResultModel] {
        childEmbeds.enumerated().map { index, embed in
            BusinessCompanyFinancialResultModel(embed: embed, fallbackIndex: index)
        }
    }

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        let raw = embed.rawData ?? [:]
        self.embed = embed
        query = EmbedFieldReader.string(raw, keys: ["query", "title"]) ?? AppStrings.businessCompanyFinancials
        provider = EmbedFieldReader.string(raw, keys: ["provider"]) ?? "SEC EDGAR"
        periodLabel = Self.displayLabel(
            EmbedFieldReader.string(raw, keys: ["period"]) ?? "latest_annual"
        )
        metricGroupLabel = Self.displayLabel(
            EmbedFieldReader.string(raw, keys: ["metric_group"]) ?? "summary"
        )
        status = embed.status
        childEmbeds = Self.resolveChildren(for: embed, allEmbedRecords: allEmbedRecords)
        resultCount = EmbedFieldReader.int(raw, keys: ["result_count"]) ?? childEmbeds.count
    }

    private static func resolveChildren(for embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) -> [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return deduplicated(explicit) }

        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        if !parented.isEmpty { return deduplicated(parented) }

        let raw = embed.rawData ?? [:]
        let inlineResults = EmbedFieldReader.dictionaryArray(raw, key: "results")
        let previewResults = inlineResults.isEmpty ? EmbedFieldReader.dictionaryArray(raw, key: "preview_results") : inlineResults
        return previewResults.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable("business")
            recordData["skill_id"] = recordData["skill_id"] ?? AnyCodable("company_financials")
            return EmbedRecord(
                id: EmbedFieldReader.string(recordData, keys: ["embed_id", "id"]) ?? "\(embed.id)-financial-\(index)",
                type: EmbedType.businessCompanyFinancialResult.rawValue,
                status: .finished,
                data: .raw(recordData),
                parentEmbedId: embed.id,
                appId: "business",
                skillId: "company_financials",
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
    }

    private static func deduplicated(_ embeds: [EmbedRecord]) -> [EmbedRecord] {
        var seen = Set<String>()
        return embeds.filter { seen.insert($0.id).inserted }
    }

    private static func displayLabel(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ")
    }
}

@MainActor
struct BusinessCompanyFinancialResultModel: Identifiable {
    let id: String
    let embed: EmbedRecord
    let company: String
    let ticker: String?
    let form: String?
    let filed: String?
    let sourceURL: String?
    let sourceMetadata: String?
    let periodLabel: String
    let periodRange: String?
    let subtitle: String?
    let revenue: String
    let netIncome: String
    let metricRows: [(label: String, value: String)]
    let notes: [String]

    init(embed: EmbedRecord, fallbackIndex: Int = 0) {
        let raw = embed.rawData ?? [:]
        self.embed = embed
        id = embed.id
        company = EmbedFieldReader.string(raw, keys: ["company", "name"])
            ?? EmbedFieldReader.string(raw, keys: ["ticker"])
            ?? AppStrings.businessFinancialResultTitle
        ticker = EmbedFieldReader.string(raw, keys: ["ticker"])
        form = EmbedFieldReader.string(raw, keys: ["form"])
        filed = EmbedFieldReader.string(raw, keys: ["filed"])
        sourceURL = EmbedFieldReader.string(raw, keys: ["source_url"])
        periodLabel = Self.periodLabel(raw)
        let periodStart = EmbedFieldReader.string(raw, keys: ["period_start"])
        let periodEnd = EmbedFieldReader.string(raw, keys: ["period_end"])
        periodRange = Self.nonEmpty([periodStart, periodEnd].compactMap { $0 }.joined(separator: " - "))
        subtitle = Self.nonEmpty([ticker, periodLabel, form].compactMap { $0 }.joined(separator: " · "))
        sourceMetadata = Self.nonEmpty(
            [form, EmbedFieldReader.string(raw, keys: ["accession_number"]), filed]
                .compactMap { $0 }
                .joined(separator: " · ")
        )
        let currency = EmbedFieldReader.string(raw, keys: ["currency"]) ?? "USD"
        revenue = Self.formatMoney(EmbedFieldReader.double(raw, keys: ["revenue"]), currency: currency)
        netIncome = Self.formatMoney(EmbedFieldReader.double(raw, keys: ["net_income"]), currency: currency)
        metricRows = Self.metricRows(from: raw, currency: currency)
        notes = EmbedFieldReader.stringArray(raw, keys: ["notes"])
    }

    private static func metricRows(from raw: [String: AnyCodable], currency: String) -> [(label: String, value: String)] {
        [
            ("revenue", AppStrings.businessFinancialRevenue),
            ("gross_profit", AppStrings.businessFinancialGrossProfit),
            ("operating_income", AppStrings.businessFinancialOperatingIncome),
            ("net_income", AppStrings.businessFinancialNetIncome),
            ("operating_cash_flow", AppStrings.businessFinancialOperatingCashFlow),
            ("assets", AppStrings.businessFinancialAssets),
            ("liabilities", AppStrings.businessFinancialLiabilities),
            ("equity", AppStrings.businessFinancialEquity)
        ].compactMap { row in
            let (key, label) = row
            guard let value = EmbedFieldReader.double(raw, keys: [key]) else { return nil }
            return (label: label, value: formatMoney(value, currency: currency))
        }
    }

    private static func nonEmpty(_ value: String) -> String? {
        value.isEmpty ? nil : value
    }

    private static func periodLabel(_ raw: [String: AnyCodable]) -> String {
        let periodType = EmbedFieldReader.string(raw, keys: ["period_type"])
        let fiscalYear = EmbedFieldReader.int(raw, keys: ["fiscal_year"])
        let fiscalQuarter = EmbedFieldReader.string(raw, keys: ["fiscal_quarter"])
        if periodType == "quarter", let fiscalQuarter, let fiscalYear {
            return "\(fiscalQuarter) \(fiscalYear)"
        }
        if let fiscalYear {
            return "FY \(fiscalYear)"
        }
        return EmbedFieldReader.string(raw, keys: ["period_end"]) ?? AppStrings.businessFinancialPeriod
    }

    private static func formatMoney(_ amount: Double?, currency: String) -> String {
        guard let amount else { return AppStrings.businessFinancialNotAvailable }
        let absAmount = abs(amount)
        let divisor: Double
        let suffix: String
        if absAmount >= 1_000_000_000 {
            divisor = 1_000_000_000
            suffix = "B"
        } else if absAmount >= 1_000_000 {
            divisor = 1_000_000
            suffix = "M"
        } else {
            divisor = 1
            suffix = ""
        }

        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = divisor == 1 ? 0 : 1
        let formatted = formatter.string(from: NSNumber(value: amount / divisor)) ?? "\(amount / divisor)"
        return "\(currency) \(formatted)\(suffix)"
    }
}

enum EmbedFieldReader {
    static func string(_ raw: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if key.contains("."),
               let value = nestedString(raw, path: key) {
                return value
            }
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value
            }
            if let value = raw[key]?.value as? Int {
                return String(value)
            }
            if key == "meta_url_favicon",
               let favicon = nestedString(raw, path: "meta_url.favicon") {
                return favicon
            }
        }
        return nil
    }

    static func int(_ raw: [String: AnyCodable], keys: [String]) -> Int? {
        for key in keys {
            if let value = raw[key]?.value as? Int {
                return value
            }
            if let value = raw[key]?.value as? String, let intValue = Int(value) {
                return intValue
            }
        }
        return nil
    }

    static func double(_ raw: [String: AnyCodable], keys: [String]) -> Double? {
        for key in keys {
            if let value = raw[key]?.value as? Double {
                return value
            }
            if let value = raw[key]?.value as? Int {
                return Double(value)
            }
            if let value = raw[key]?.value as? String, let doubleValue = Double(value) {
                return doubleValue
            }
        }
        return nil
    }

    static func stringArray(_ raw: [String: AnyCodable], keys: [String]) -> [String] {
        for key in keys {
            if let values = raw[key]?.value as? [String] {
                return values.filter { !$0.isEmpty }
            }
            if let values = raw[key]?.value as? [Any] {
                return values.compactMap { $0 as? String }.filter { !$0.isEmpty }
            }
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value.split(separator: "|").map(String.init).filter { !$0.isEmpty }
            }
        }
        return []
    }

    static func dictionaryArray(_ raw: [String: AnyCodable], key: String) -> [[String: Any]] {
        guard let value = raw[key]?.value else { return [] }
        if let dictionaries = value as? [[String: Any]] {
            return dictionaries
        }
        if let array = value as? [Any] {
            return array.compactMap { item in
                if let dictionary = item as? [String: Any] {
                    return dictionary
                }
                if let dictionary = item as? [String: String] {
                    return dictionary.mapValues { $0 as Any }
                }
                return nil
            }
        }
        return []
    }

    static func host(from value: String?) -> String? {
        guard let value, let url = URL(string: value), let host = url.host else { return nil }
        return host.replacingOccurrences(of: "www.", with: "")
    }

    static func strippedHTML(_ text: String?) -> String? {
        guard let text, !text.isEmpty else { return nil }
        let withoutTags = text.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        let decoded = withoutTags
            .replacingOccurrences(of: "\\\"", with: "\"")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return decoded.isEmpty ? nil : decoded
    }

    static func proxiedImageURL(
        _ rawURL: String?, maxWidth: Int,
        webBaseURL: URL = ServerProfile.current().webBaseURL
    ) -> String? {
        guard let rawURL = rawURL?.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawURL.isEmpty else { return nil }
        if shouldLoadDirectly(rawURL) || rawURL.hasPrefix("data:") {
            return rawURL
        }
        // Native URLSession needs an absolute URL for the web's same-origin
        // /store-examples assets. A //host URL is external and stays proxied.
        if rawURL.hasPrefix("/"), !rawURL.hasPrefix("//") {
            return URL(string: rawURL, relativeTo: webBaseURL)?.absoluteURL.absoluteString
        }
        if let existing = URLComponents(string: rawURL),
           existing.scheme == "https", existing.host == "preview.openmates.org",
           (existing.path == "/api/v1/image" || existing.path == "/api/v1/favicon") {
            return rawURL
        }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/image")
        components?.queryItems = [
            URLQueryItem(name: "url", value: rawURL.hasPrefix("//") ? "https:" + rawURL : rawURL),
            URLQueryItem(name: "max_width", value: "\(maxWidth)")
        ]
        return components?.url?.absoluteString ?? rawURL
    }

    static func proxiedFaviconImageURL(directURL: String?, pageURL: String?) -> String? {
        let direct = directURL?.trimmingCharacters(in: .whitespacesAndNewlines)
        // WebsiteEmbedPreview.svelte proxies supplied favicon bitmaps through
        // /image, but uses /favicon directly when extracting from the page URL.
        // Wrapping /favicon in /image breaks sites that the browser renders.
        if let direct, !direct.isEmpty {
            return proxiedImageURL(direct, maxWidth: 38)
        }
        return proxiedFaviconURL(pageURL: pageURL)
    }

    static func proxiedFaviconURL(pageURL: String?) -> String? {
        guard let pageURL, !pageURL.isEmpty else { return nil }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/favicon")
        components?.queryItems = [URLQueryItem(name: "url", value: pageURL)]
        return components?.url?.absoluteString
    }

    private static func shouldLoadDirectly(_ rawURL: String) -> Bool {
        guard let host = URL(string: rawURL)?.host?.lowercased() else { return false }
        return host == "imgs.search.brave.com"
    }

    private static func nestedString(_ raw: [String: AnyCodable], path: String) -> String? {
        let parts = path.split(separator: ".").map(String.init)
        guard let first = parts.first else { return nil }
        var current: Any? = raw[first]?.value
        for part in parts.dropFirst() {
            if let dict = current as? [String: Any] {
                current = dict[part]
            } else if let dict = current as? [String: AnyCodable] {
                current = dict[part]?.value
            } else {
                return nil
            }
        }
        if let value = current as? String, !value.isEmpty {
            return value
        }
        return nil
    }
}

/// User-facing input identity for a called skill. The allowlist follows each
/// registered skill's request fields; never stringify arbitrary payload fields.
/// Request metadata survives result hydration, so these inputs do not become a
/// generated result title while the skill is running.
struct AppSkillInputPreviewModel {
    let text: String?
    let provider: String?

    static let fieldsBySkill: [String: [String]] = [
        "audio.transcribe": ["filename", "language"],
        "audio.generate": ["prompt"], "audio.speak": ["text", "text_preview"],
        "business.company_financials": ["query", "period"],
        "calendar.list-calendars": ["query"],
        "calendar.get-events": ["query", "calendar_id", "time_min", "time_max"],
        "calendar.create-event": ["summary", "title", "start", "end"],
        "calendar.update-event": ["summary", "title", "event_id", "start", "end"],
        "calendar.delete-event": ["event_id", "calendar_id"],
        "code.search_repos": ["query"], "code.get_docs": ["library", "question"],
        "code.run": ["entry_path", "argv", "target_embed_id", "target"],
        "design.search_icons": ["query"],
        "electronics.search_components": ["query", "category", "input_voltage_min", "input_voltage_max", "output_voltage", "output_current_max"],
        "events.search": ["query", "location", "start_date", "end_date"],
        "finance.check_accounts": ["period", "time_range"],
        "fitness.search_locations": ["query", "city", "address"],
        "fitness.search_classes": ["query", "city", "start_date", "end_date"],
        "health.search_appointments": ["query", "speciality", "city"],
        "home.search": ["query"], "hosting.search_domains": ["query", "tlds"],
        "images.generate": ["prompt"], "images.generate_draft": ["prompt"],
        "images.search": ["query", "file_path"], "images.view": ["file_path"],
        "images.vectorize": ["source_image"], "mail.search": ["query", "mailbox"],
        "maps.search": ["query", "area"], "math.calculate": ["expression", "query"],
        "models3d.search": ["query"], "models3d.generate": ["prompt", "image_embed_refs"],
        "music.generate": ["prompt"], "news.search": ["query"],
        "nutrition.search_recipes": ["query"],
        "openmates.share-usecase": ["summary"], "openmates.get-docs": ["url"],
        "pdf.read": ["file_path", "pages"], "pdf.search": ["query", "file_path"],
        "pdf.view": ["file_path", "pages", "query"],
        "projects.search": ["query"], "projects.read": ["query", "path", "file_path"],
        "reminder.set-reminder": ["prompt", "trigger_datetime"],
        "reminder.list-reminders": ["query"], "reminder.cancel-reminder": ["reminder_id"],
        "shopping.search_products": ["query"],
        "social_media.get-posts": ["query", "page", "platform"], "social_media.search": ["query"],
        "tasks.create": ["title", "description"], "tasks.search": ["query"],
        "travel.search_connections": ["query", "origin", "destination", "date"],
        "travel.search_stays": ["query", "check_in_date", "check_out_date"],
        "travel.price_calendar": ["query", "origin", "destination", "month", "start_date", "end_date"],
        "travel.get_flight": ["flight_number", "departure_date"],
        "videos.search": ["query"], "videos.get_transcript": ["url", "languages"],
        "videos.generate": ["prompt"], "videos.create": ["filename"],
        "weather.forecast": ["location", "location_name", "latitude", "longitude", "start_date", "end_date"],
        "weather.rain_radar": ["location", "location_name", "latitude", "longitude"], "web.search": ["query"], "web.read": ["url"],
        "workflows.create-or-modify": ["instruction", "title", "name"], "workflows.search": ["query"]
    ]

    static func isRegisteredSkill(_ embed: EmbedRecord) -> Bool {
        let type = EmbedType.normalized(rawValue: embed.type)?.rawValue ?? embed.type
        let parts = type.split(separator: ":").map(String.init)
        guard parts.count == 3, parts[0] == "app" else { return embed.isAppSkillUse }
        return fieldsBySkill["\(parts[1]).\(parts[2])"] != nil
    }

    init(embed: EmbedRecord) {
        let data = embed.rawData ?? [:]
        let parts = (EmbedType.normalized(rawValue: embed.type)?.rawValue ?? embed.type)
            .split(separator: ":").map(String.init)
        let app = embed.appId ?? EmbedFieldReader.string(data, keys: ["app_id"])
            ?? (parts.count >= 3 && parts[0] == "app" ? parts[1] : "")
        let rawSkill = embed.skillId ?? EmbedFieldReader.string(data, keys: ["skill_id"])
            ?? (parts.count >= 3 && parts[0] == "app" ? parts[2] : "")
        let skill = EmbedType.normalized(rawValue: "app:\(app):\(rawSkill)")?.rawValue
            .split(separator: ":").last.map(String.init) ?? rawSkill
        let keys = Self.fieldsBySkill["\(app).\(skill)"] ?? ["query", "prompt", "url", "title"]
        // Most placeholders flatten the first request. Retain compatibility
        // with the requests[] envelope without borrowing output result fields.
        let envelope = ["requests", "tasks", "workflows"].compactMap { data[$0]?.value as? [[String: Any]] }.first
        let request = envelope?.first ?? [:]
        var inputs = data.mapValues(\.value)
        for (key, value) in request where inputs[key] == nil { inputs[key] = value }
        if app == "travel", skill == "search_connections", inputs["query"] == nil,
           let legs = inputs["legs"] as? [[String: Any]], let first = legs.first {
            for key in ["origin", "destination", "date"] where inputs[key] == nil { inputs[key] = first[key] }
        }
        var seen = Set<String>()
        let values = keys.compactMap { key -> String? in
            let nestedLocation = (inputs[key] as? [String: Any]).flatMap { location in
                ["location", "area"].contains(key) ? location["name"] ?? location["text"] : nil
            }
            guard let value = Self.displayValue(nestedLocation ?? inputs[key]), seen.insert(value).inserted else { return nil }
            return value
        }
        text = values.isEmpty ? nil : values.joined(separator: " · ")
        provider = Self.displayValue(inputs["provider"])
    }

    init(data: [String: AnyCodable], appId: String, skillId: String) {
        self.init(embed: EmbedRecord(id: "skill-input-preview", type: "app:\(appId):\(skillId)",
                                    status: .processing, data: .raw(data), parentEmbedId: nil,
                                    appId: appId, skillId: skillId, embedIds: nil, createdAt: nil))
    }

    private static func displayValue(_ value: Any?) -> String? {
        if let string = value as? String {
            let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        if let strings = value as? [String] {
            let values = strings.compactMap { displayValue($0) }
            return values.isEmpty ? nil : values.joined(separator: ", ")
        }
        if let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() { return number.stringValue }
        return nil
    }
}
