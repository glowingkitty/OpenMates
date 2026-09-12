import Foundation

struct NativeModelCatalog: Decodable {
    let schemaVersion: Int
    let sourceDigest: String
    let providers: [ProviderDisplay]
    let models: [Model]
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
        let provider_id: String
        let provider_name: String
        let logo_svg: String
        let for_app_skill: String?
        let release_date: String?
        let capability_level: String?
        let show_in_mentions: Bool?
        let servers: [Server]
    }
    struct Server: Decodable {
        let id: String
        let name: String?
        let region: String?
    }
    struct Pricing: Decodable {
        let input_tokens_per_credit: Double?
        let output_tokens_per_credit: Double?
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
