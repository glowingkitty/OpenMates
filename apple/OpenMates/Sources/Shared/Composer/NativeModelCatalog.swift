// Specification: specifications/features/ai-model-routing/specification.yml
// Assertions: ai-model-routing.catalog.public-read-only
import Foundation

struct NativeModelCatalog: Decodable {
    let schemaVersion: Int
    let sourceDigest: String
    let providers: [ProviderDisplay]
    let models: [Model]
    struct AutomaticSummaryRate {
        let modelName: String
        let inputTokensPerCredit: Double
        let outputTokensPerCredit: Double
    }
    struct AutomaticSummaryPricing {
        let primary: AutomaticSummaryRate
        let fallback: AutomaticSummaryRate
    }
    func automaticSummaryPricing(for model: Model, today: String = CachePricing.todayUTC()) -> AutomaticSummaryPricing? {
        guard model.cachePricesActive(today: today) else { return nil }
        func rate(_ id: String) -> AutomaticSummaryRate? {
            guard let summaryModel = models.first(where: { $0.id == id }),
                  let input = summaryModel.pricing?.input_tokens_per_credit, input.isFinite, input > 0,
                  let output = summaryModel.pricing?.output_tokens_per_credit, output.isFinite, output > 0 else { return nil }
            return AutomaticSummaryRate(modelName: summaryModel.name, inputTokensPerCredit: input, outputTokensPerCredit: output)
        }
        guard let primary = rate("gemini-3.5-flash-lite"), let fallback = rate("gpt-oss-120b") else { return nil }
        return AutomaticSummaryPricing(primary: primary, fallback: fallback)
    }
    struct ProviderDisplay: Decodable {
        let id: String
        let brandName: String
        let companyName: String
        let order: Int
        let logoSvg: String
    }
    struct Model: Decodable {
        let id: String
        let name: String
        let description: String?
        let country_origin: String?
        let input_types: [String]?
        let output_types: [String]?
        let pricing: Pricing?
        let cache_pricing: CachePricing?
        let default_server: String?
        let provider_id: String
        let provider_name: String
        let logo_svg: String
        let for_app_skill: String?
        let release_date: String?
        let capability_level: String?
        // Public catalog tier is displayed on exact default-model option rows.
        var tier: String? = nil
        let show_in_mentions: Bool?
        let servers: [Server]
        func cachePricesActive(today: String = CachePricing.todayUTC()) -> Bool {
            guard let pricing else { return false }
            return cache_pricing?.isDisplayActive(defaultHost: default_server, pricing: pricing, today: today) == true
        }
        func longContextPricesActive(today: String = CachePricing.todayUTC()) -> Bool {
            guard cachePricesActive(today: today), default_server == "openai",
                  let standardInput = pricing?.input_tokens_per_credit, standardInput.isFinite, standardInput > 0,
                  let standardOutput = pricing?.output_tokens_per_credit, standardOutput.isFinite, standardOutput > 0,
                  let band = pricing?.context_bands?.over_272k,
                  band.min_input_tokens == 272_001,
                  band.eligible_hosts == ["openai"],
                  let input = band.input_tokens_per_credit, input.isFinite, input > 0,
                  let read = band.cache_read_tokens_per_credit, read.isFinite, read > 0,
                  let output = band.output_tokens_per_credit, output.isFinite, output > 0 else { return false }
            if cache_pricing?.write_billing == "separate" {
                guard let write = band.cache_write_tokens_per_credit, write.isFinite, write > 0 else { return false }
            }
            return true
        }
        var supportsOneHourCacheWrites: Bool {
            guard let default_server, !default_server.isEmpty else { return false }
            return cache_pricing?.cache_write_1h_hosts?.contains(default_server) == true
        }
    }
    struct Server: Decodable {
        let id: String
        let name: String?
        let region: String?
    }
    struct Pricing: Decodable {
        let input_tokens_per_credit: Double?
        let output_tokens_per_credit: Double?
        let cache_read_tokens_per_credit: Double?
        let cache_write_tokens_per_credit: Double?
        let cache_write_1h_tokens_per_credit: Double?
        let context_bands: ContextBands?
        struct ContextBands: Decodable {
            let over_272k: LongContextBand?
        }
        struct LongContextBand: Decodable {
            let min_input_tokens: Int?
            let eligible_hosts: [String]?
            let input_tokens_per_credit: Double?
            let cache_read_tokens_per_credit: Double?
            let cache_write_tokens_per_credit: Double?
            let output_tokens_per_credit: Double?
        }
    }
    struct CachePricing: Decodable {
        let enabled: Bool
        let write_billing: String?
        let write_ttl: String?
        let pricing_version: String?
        let source_url: String?
        let reviewed_on: String?
        let effective_from: String?
        let expires_on: String?
        let status: String?
        let eligible_hosts: [String]?
        let cache_write_1h_hosts: [String]?
        let requires_cache_write_metric: Bool?
        let requires_cache_retention_metric: Bool?

        func isDisplayActive(defaultHost: String?, pricing: Pricing, today: String) -> Bool {
            guard enabled, status == "verified_for_activation",
                  write_billing == "included_in_input" || write_billing == "separate",
                  let source_url, !source_url.isEmpty,
                  let reviewed_on, Self.validUTCDate(reviewed_on),
                  let expires_on, Self.validUTCDate(expires_on),
                  let eligible_hosts, !eligible_hosts.isEmpty,
                  let defaultHost, !defaultHost.isEmpty, eligible_hosts.contains(defaultHost),
                  Self.validUTCDate(today),
                  reviewed_on <= today, today <= expires_on else { return false }
            guard let readRate = pricing.cache_read_tokens_per_credit, readRate > 0 else { return false }
            if write_billing == "separate" {
                guard let writeRate = pricing.cache_write_tokens_per_credit, writeRate > 0 else { return false }
            }
            if requires_cache_retention_metric == true {
                guard let oneHourRate = pricing.cache_write_1h_tokens_per_credit, oneHourRate > 0 else { return false }
            }
            if let effective_from, !effective_from.isEmpty {
                guard Self.validUTCDate(effective_from), effective_from <= today else { return false }
            }
            return true
        }
        static func todayUTC() -> String {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = TimeZone(secondsFromGMT: 0)!
            let parts = calendar.dateComponents([.year, .month, .day], from: Date())
            return String(format: "%04d-%02d-%02d", parts.year!, parts.month!, parts.day!)
        }
        private static func validUTCDate(_ value: String) -> Bool {
            let parts = value.split(separator: "-", omittingEmptySubsequences: false)
            guard value.count == 10, parts.count == 3,
                  parts[0].count == 4, parts[1].count == 2, parts[2].count == 2,
                  parts.allSatisfy({ $0.allSatisfy(\.isNumber) }),
                  let year = Int(parts[0]), year >= 1,
                  let month = Int(parts[1]), (1...12).contains(month),
                  let day = Int(parts[2]), (1...31).contains(day) else { return false }
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = TimeZone(secondsFromGMT: 0)!
            let components = DateComponents(year: year, month: month, day: day)
            guard let date = calendar.date(from: components) else { return false }
            let checked = calendar.dateComponents([.year, .month, .day], from: date)
            return checked.year == year && checked.month == month && checked.day == day
        }
    }
    enum Failure: Error { case unsupportedSchema, missingDisplayMetadata, invalidCatalog }
    static func load(data: Data) throws -> Self {
        let result = try JSONDecoder().decode(Self.self, from: data)
        guard result.schemaVersion == 2 else { throw Failure.unsupportedSchema }
        let providerIDs = Set(result.providers.map(\.id))
        guard result.sourceDigest.count == 64, result.sourceDigest.allSatisfy({ $0.isHexDigit }),
              providerIDs.count == result.providers.count,
              result.models.allSatisfy({ providerIDs.contains($0.provider_id) }) else { throw Failure.invalidCatalog }
        return result
    }
    static func load(bundle: Bundle) throws -> Self {
        guard let url = bundle.url(forResource: "modelsMetadata", withExtension: "json") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try load(data: Data(contentsOf: url))
    }
    // Web compareAiModels: newest date, strongest capability for equal dates,
    // then ID; missing metadata throws instead of inventing ranks/dates.
    static func modelsForDisplay(_ models: [Model]) throws -> [Model] {
        let ranks = ["low": 0, "medium": 1, "high": 2, "max": 3]
        return try models.sorted { a, b in
            guard let ad = a.release_date, !ad.isEmpty, let bd = b.release_date, !bd.isEmpty else { throw Failure.missingDisplayMetadata }
            if ad != bd { return ad.compare(bd, locale: Locale(identifier: "en_US")) == .orderedDescending }
            guard let ac = a.capability_level, let bc = b.capability_level, let ar = ranks[ac], let br = ranks[bc] else { throw Failure.missingDisplayMetadata }
            if ar != br { return ar > br }
            return a.id.compare(b.id, locale: Locale(identifier: "en_US")) == .orderedAscending
        }
    }
    func routing(disabledModels: Set<String> = [], disabledServers: [String: Set<String>] = [:], health: ProviderHealthSnapshot?) -> ModelRoutingCatalog {
        ModelRoutingCatalog(entries: models.map { .init(provider: $0.provider_id, modelID: $0.id, skill: $0.for_app_skill ?? "", servers: $0.servers.map(\.id)) },
            disabledModels: disabledModels, disabledServers: disabledServers,
            unhealthyServers: Set(health?.providers.filter { $0.value.status != "healthy" }.keys.map { $0 } ?? []))
    }
    // The generator and web helper share aiProviderDisplay.json. Native never
    // guesses provider product names or substitutes alphabetical brand order.
    var pickerProviders: [ProviderDisplay] {
        let selectableProviders = Set(models.filter { $0.for_app_skill == "ai.ask" }.map(\.provider_id))
        return providers.filter { selectableProviders.contains($0.id) }
    }
    var mentionModels: [Model] { models.filter { $0.for_app_skill == "ai.ask" && $0.show_in_mentions != false } }
}

// Exact public GET /v1/health response subset. Missing/failed response and
// absent provider remain usable, matching appHealthStore.isProviderHealthy.
struct ProviderHealthSnapshot: Decodable {
    struct Provider: Decodable { let status: String }
    let providers: [String: Provider]
}
