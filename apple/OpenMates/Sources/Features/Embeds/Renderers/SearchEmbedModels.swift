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

import Foundation

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
        appId = embed.appId ?? EmbedFieldReader.string(raw, keys: ["app_id"]) ?? inferredAppId ?? "web"
        skillId = embed.skillId ?? EmbedFieldReader.string(raw, keys: ["skill_id"]) ?? inferredSkillId ?? "search"
        query = EmbedFieldReader.string(raw, keys: ["query", "title"]) ?? EmbedType(rawValue: embed.type)?.displayName ?? skillId
        let fallbackProvider = appId == "images" ? "Brave" : "Brave Search"
        provider = EmbedFieldReader.string(raw, keys: ["provider"]).map(Self.displayProvider) ?? fallbackProvider
        status = embed.status
        childEmbeds = Self.resolveChildren(for: embed, appId: appId, allEmbedRecords: allEmbedRecords)
        previewResultCount = EmbedFieldReader.int(raw, keys: ["result_count"])
            ?? (childEmbeds.isEmpty ? Self.previewRecords(from: embed).count : childEmbeds.count)
    }

    private static func previewRecords(from embed: EmbedRecord) -> [EmbedRecord] {
        let raw = embed.rawData ?? [:]
        let previewResults = EmbedFieldReader.dictionaryArray(raw, key: "preview_results")
        guard !previewResults.isEmpty else { return [] }

        return previewResults.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable(embed.appId ?? "web")
            return EmbedRecord(
                id: "\(embed.id)-preview-\(index)",
                type: Self.previewChildType(for: embed),
                status: .finished,
                data: .raw(recordData),
                parentEmbedId: embed.id,
                appId: embed.appId,
                skillId: nil,
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
    }

    private static func previewChildType(for embed: EmbedRecord) -> String {
        switch embed.appId {
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
        allEmbedRecords: [String: EmbedRecord]
    ) -> [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return deduplicated(explicit) }

        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        if !parented.isEmpty { return deduplicated(parented) }

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
    let previewImageURL: String?
    let snippet: String?
    let pageAge: String?

    init?(embed: EmbedRecord) {
        let raw = embed.rawData ?? [:]
        let resolvedURL = EmbedFieldReader.string(raw, keys: ["url"])
        guard let resolvedURL, !resolvedURL.isEmpty else { return nil }
        id = embed.id
        self.embed = embed
        url = resolvedURL
        sourceDomain = EmbedFieldReader.host(from: resolvedURL) ?? resolvedURL
        title = EmbedFieldReader.string(raw, keys: ["title", "site_name", "profile_name"]) ?? sourceDomain
        faviconURL = EmbedFieldReader.proxiedImageURL(
            EmbedFieldReader.string(raw, keys: ["meta_url_favicon", "favicon_url", "favicon", "meta_url.favicon"]),
            maxWidth: 64
        ) ?? EmbedFieldReader.proxiedFaviconURL(pageURL: resolvedURL)
        previewImageURL = EmbedFieldReader.proxiedImageURL(
            EmbedFieldReader.string(raw, keys: [
                "thumbnail_original", "thumbnail_src", "thumbnail_url",
                "thumbnail.original", "thumbnail.src", "preview_image_url",
                "image", "image_url", "meta_image", "og_image"
            ]),
            maxWidth: 1024
        )
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
        ) ?? EmbedFieldReader.proxiedFaviconURL(pageURL: sourcePageURL)
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

    static func proxiedImageURL(_ rawURL: String?, maxWidth: Int) -> String? {
        guard let rawURL, !rawURL.isEmpty else { return nil }
        if shouldLoadDirectly(rawURL) {
            return rawURL
        }
        if rawURL.hasPrefix("https://preview.openmates.org/api/v1/image")
            || rawURL.hasPrefix("data:")
            || rawURL.hasPrefix("/") {
            return rawURL
        }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/image")
        components?.queryItems = [
            URLQueryItem(name: "url", value: rawURL),
            URLQueryItem(name: "max_width", value: "\(maxWidth)")
        ]
        return components?.url?.absoluteString ?? rawURL
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
