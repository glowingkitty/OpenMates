// Hosting domain normalization mirrors hostingDomainData.ts at dev 3053414ea2c50d4dfa0990e1211931fe09cf2b26.
import Foundation
import CoreFoundation

enum HostingDomainAvailability: String { case available, unavailable, unknown }
enum HostingDomainView: String, CaseIterable { case selected, available, all, inUse = "in-use", unknown }

enum HostingEmbedKind {
    static func isSearch(_ embed: EmbedRecord) -> Bool {
        if embed.type == "app:hosting:search_domains" { return true }
        return (embed.appId ?? embed.rawData?["app_id"]?.value as? String) == "hosting"
            && (embed.skillId ?? embed.rawData?["skill_id"]?.value as? String) == "search_domains"
            && embed.isAppSkillUse
    }
    static func isDomain(_ embed: EmbedRecord) -> Bool {
        ["hosting-domain", "hosting_domain"].contains(embed.type)
    }
}

struct HostingDomainTier {
    enum TaxBasis: Equatable { case including, excluding }
    struct Quote { let amount: Double; let basis: TaxBasis }
    let raw: [String: Any]
    var unit: String { raw["unit"] as? String ?? "" }
    var isYearly: Bool { ["y", "year", "years"].contains(unit) }
    var minimumYears: Double? {
        isYearly ? HostingFields.number((raw["duration_range"] as? [String: Any])?["minimum"]) : nil
    }
    var maximumYears: Double? { HostingFields.number((raw["duration_range"] as? [String: Any])?["maximum"]) }
    var quote: Quote? {
        if let value = HostingFields.number(raw["price_including_tax"]), value >= 0 {
            return Quote(amount: value, basis: .including)
        }
        if let value = HostingFields.number(raw["price_excluding_tax"]), value >= 0 {
            return Quote(amount: value, basis: .excluding)
        }
        return nil
    }
    var normalPrice: Double? {
        HostingFields.number(raw[quote?.basis == .including ? "normal_price" : "normal_price_before_taxes"])
    }
    var isFirstYearOffer: Bool {
        guard minimumYears == 1, raw["discount"] as? Bool == true,
              let quote, let normalPrice else { return false }
        return normalPrice > quote.amount
    }
    var taxRate: Double? {
        HostingFields.number(raw["tax_rate"])
            ?? HostingFields.number((raw["product_taxes"] as? [[String: Any]])?.first?["rate"])
    }
    static func headline(_ tiers: [Self]) -> Self? {
        tiers.first { $0.minimumYears == 1 && $0.quote != nil } ?? tiers.first { $0.quote != nil }
    }
}

struct HostingDomainModel {
    let embed: EmbedRecord
    let ascii: String
    let name: String
    let availability: HostingDomainAvailability
    let provider: String
    let currency: String
    let country: String
    let premium: Bool
    let restrictions: [String]
    let registrationTiers: [HostingDomainTier]
    let renewalTiers: [HostingDomainTier]
    let checkedAt: Date?
    let providerURL: URL?
    var registration: HostingDomainTier? { HostingDomainTier.headline(registrationTiers) }
    var renewal: HostingDomainTier? { HostingDomainTier.headline(renewalTiers) }
    var showsBodyName: Bool { name.count > 24 || name != ascii }

    init(_ embed: EmbedRecord) {
        self.embed = embed
        let raw = embed.rawData ?? [:]
        ascii = HostingFields.text(raw, "domain_ascii")
        let unicode = HostingFields.text(raw, "domain_unicode")
        name = unicode.isEmpty ? ascii : unicode
        availability = HostingDomainAvailability(rawValue: HostingFields.text(raw, "availability")) ?? .unknown
        provider = HostingFields.text(raw, "provider", fallback: "Gandi")
        currency = HostingFields.text(raw, "currency", fallback: "EUR")
        country = HostingFields.text(raw, "country")
        premium = raw["premium"]?.value as? Bool == true
        restrictions = HostingFields.strings(raw["restrictions"]?.value)
        registrationTiers = EmbedFieldReader.dictionaryArray(raw, key: "registration_tiers").map { HostingDomainTier(raw: $0) }
        renewalTiers = EmbedFieldReader.dictionaryArray(raw, key: "renewal_tiers").map { HostingDomainTier(raw: $0) }
        checkedAt = ISO8601DateFormatter().date(from: HostingFields.text(raw, "checked_at"))
            ?? { let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return formatter.date(from: HostingFields.text(raw, "checked_at")) }()
        providerURL = Self.safeGandiURL(HostingFields.text(raw, "provider_url"))
    }

    static func safeGandiURL(_ value: String) -> URL? {
        guard let url = URL(string: value), url.scheme?.lowercased() == "https",
              url.host?.lowercased() == "shop.gandi.net" else { return nil }
        return url
    }
}

struct HostingSearchModel {
    let embed: EmbedRecord
    let query: String
    let provider: String
    let currency: String
    let country: String
    let checkedCount: Int
    let availableCount: Int
    let unavailableCount: Int
    let unknownCount: Int
    let resultCount: Int
    let partial: Bool
    let error: String
    let limit: Int
    let selectedIDs: [String]
    let checkedIDs: [String]
    let children: [EmbedRecord]
    let startingQuote: HostingDomainTier.Quote?
    let startingCurrency: String

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        self.embed = embed
        let raw = embed.rawData ?? [:]
        query = HostingFields.text(raw, "query")
        provider = HostingFields.text(raw, "provider", fallback: "Gandi")
        currency = HostingFields.text(raw, "currency", fallback: "EUR")
        country = HostingFields.text(raw, "country")
        checkedCount = EmbedFieldReader.int(raw, keys: ["checked_count"]) ?? 0
        availableCount = EmbedFieldReader.int(raw, keys: ["available_count"]) ?? 0
        unavailableCount = EmbedFieldReader.int(raw, keys: ["unavailable_count"]) ?? 0
        unknownCount = EmbedFieldReader.int(raw, keys: ["unknown_count"]) ?? 0
        selectedIDs = HostingFields.ids(raw["selected_embed_ids"]?.value)
        checkedIDs = raw["embed_ids"] == nil ? embed.childEmbedIds : HostingFields.ids(raw["embed_ids"]?.value)
        resultCount = EmbedFieldReader.int(raw, keys: ["result_count"]) ?? selectedIDs.count
        partial = raw["partial"]?.value as? Bool == true
        error = HostingFields.text(raw, "error")
        limit = max(1, min(20, EmbedFieldReader.int(raw, keys: ["max_results"]) ?? 10))
        // Hydrate only declared checked children and preserve their order. A
        // late/unrelated linked child cannot alter the bounded checked pool.
        children = checkedIDs.compactMap { allEmbedRecords[$0] }.filter(HostingEmbedKind.isDomain)
        let starting = raw["preview_starting_registration"]?.value as? [String: Any] ?? [:]
        startingCurrency = starting["currency"] as? String ?? currency
        if embed.status == .finished, starting["unit"] as? String == "year",
           HostingFields.number(starting["duration"]) == 1,
           let amount = HostingFields.number(starting["amount"]), amount >= 0 {
            startingQuote = .init(amount: amount, basis: starting["tax_basis"] as? String == "excluding" ? .excluding : .including)
        } else { startingQuote = nil }
    }
    var isHydrating: Bool { children.count < checkedIDs.count }
    func visibleChildren(_ view: HostingDomainView) -> [EmbedRecord] {
        let byID = Dictionary(uniqueKeysWithValues: children.map { ($0.id, $0) })
        if view == .selected {
            let selected = selectedIDs.compactMap { byID[$0] }
            if !selected.isEmpty || error.isEmpty { return Array(selected.prefix(limit)) }
            return visibleChildren(.unknown)
        }
        return Array(children.filter {
            let status = HostingDomainModel($0).availability
            switch view {
            case .selected: return false
            case .available: return status == .available
            case .all: return status != .unknown
            case .inUse: return status == .unavailable
            case .unknown: return status == .unknown
            }
        }.prefix(limit))
    }
}

private enum HostingFields {
    static func text(_ raw: [String: AnyCodable], _ key: String, fallback: String = "") -> String {
        guard let value = raw[key]?.value as? String, !value.isEmpty else { return fallback }; return value
    }
    static func number(_ value: Any?) -> Double? {
        // Swift Bool bridges to NSNumber; it is not a provider price.
        guard let value, CFGetTypeID(value as CFTypeRef) != CFBooleanGetTypeID() else { return nil }
        let result = (value as? NSNumber)?.doubleValue ?? (value as? String).flatMap(Double.init)
        return result.flatMap { $0.isFinite ? $0 : nil }
    }
    static func strings(_ value: Any?) -> [String] {
        (value as? [Any] ?? []).compactMap { $0 as? String }.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
    static func ids(_ value: Any?) -> [String] {
        let items = (value as? String).map { $0.components(separatedBy: "|") } ?? strings(value)
        var seen = Set<String>()
        return items.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty && seen.insert($0).inserted }
    }
}
