// Synthetic Hosting fixtures from web hostingPreviewFixtures.ts at dev 3053414ea2c50d4dfa0990e1211931fe09cf2b26.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/hosting/HostingSearchEmbedPreview.preview.ts
//         frontend/packages/ui/src/components/embeds/hosting/HostingSearchEmbedFullscreen.preview.ts
//         frontend/packages/ui/src/components/embeds/hosting/HostingDomainEmbedPreview.preview.ts
//         frontend/packages/ui/src/components/embeds/hosting/HostingDomainEmbedFullscreen.preview.ts
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
#if DEBUG
import Foundation

enum DevHostingEmbedFixtures {
    static func record(id: String, type: String, status: EmbedStatus = .finished, raw: [String: Any], parent: String? = nil) -> EmbedRecord {
        EmbedRecord(id: id, type: type, status: status, data: .raw(raw.mapValues(AnyCodable.init)),
                    parentEmbedId: parent, appId: "hosting", skillId: type.hasPrefix("app:") ? "search_domains" : nil,
                    embedIds: (raw["embed_ids"] as? [String])?.joined(separator: "|"), createdAt: nil)
    }
    private static func tier(_ amount: Double, minimum: Int = 1, discount: Bool = false) -> [String: Any] {
        ["unit": "y", "duration_range": ["minimum": minimum, "maximum": minimum == 1 ? 10 : 9],
         "minimum_term": "\(minimum) y", "price_including_tax": amount,
         "price_excluding_tax": (amount / 1.19 * 100).rounded() / 100, "discount": discount,
         "normal_price": discount ? amount + 7.45 : NSNull(), "product_taxes": [["name": "VAT", "rate": 19]]]
    }
    static func domain(_ variant: String = "default", fullscreen: Bool = false) -> EmbedRecord {
        var name = fullscreen ? "cedarcomet.com" : "cedarcomet.net"
        var raw: [String: Any] = ["availability": "available", "provider": "Gandi", "currency": "EUR", "country": "DE",
            "checked_at": "2026-10-01T13:09:00Z", "restrictions": [],
            "registration_tiers": fullscreen ? [tier(13.09), tier(30.91, minimum: 2, discount: true)] : [tier(14.27, discount: true)],
            "renewal_tiers": fullscreen ? [tier(38.06), tier(34.25, minimum: 2, discount: true)] : [tier(47.60)]]
        switch variant {
        case "unavailable": name = "cedarcomet.org"; raw["availability"] = "unavailable"; raw["registration_tiers"] = []; raw["renewal_tiers"] = []
        case "unknown": name = "cedarcomet.et"; raw["availability"] = "unknown"; raw["registration_tiers"] = []; raw["renewal_tiers"] = []
        case "premium": name = "rarecedar.com"; raw["premium"] = true; raw["restrictions"] = ["Registration requires identity verification"]; raw["registration_tiers"] = [tier(900)]; raw["renewal_tiers"] = [tier(1100)]
        case "minTwoYears": name = "cedarcomet.dev"; raw["registration_tiers"] = [tier(29.40, minimum: 2)]; raw["renewal_tiers"] = [tier(38.20, minimum: 2)]
        case "missingPrice": name = "cedarcomet.info"; raw["registration_tiers"] = []; raw["renewal_tiers"] = []
        case "longIdn": name = "xn--berlange-domainkennung-6zb.cedarcomet-example.test"; raw["domain_unicode"] = "überlange-domainkennung-mit-vielen-zeichen.cedarcomet-example.test"; raw["registration_tiers"] = [tier(21.90)]; raw["renewal_tiers"] = [tier(29.90)]
        default: break
        }
        raw["domain_ascii"] = name; raw["domain_unicode"] = raw["domain_unicode"] ?? name
        raw["provider_url"] = "https://shop.gandi.net/en/domain/suggest?search=\(name)"
        return record(id: "preview-hosting-domain-\(variant)", type: "hosting-domain", raw: raw, parent: "preview-hosting-search")
    }
    static func search(_ variant: String = "default") -> DevEmbedPreviewSkill {
        let parentID = "preview-hosting-search"
        var children = [domain(fullscreen: true), domain(), domain("unavailable"), domain("unknown")]
        children = children.enumerated().map { index, child in
            record(id: "preview-hosting-\(index)", type: "hosting-domain", raw: child.rawData?.mapValues(\.value) ?? [:], parent: parentID)
        }
        // Include the remaining checked candidates from the exact web fixture.
        var idn = domain().rawData?.mapValues(\.value) ?? [:]
        idn["domain_ascii"] = "xn--bcher-beispiel-wob.de"; idn["domain_unicode"] = "bücher-beispiel.de"
        idn["provider_url"] = "https://shop.gandi.net/en/domain/suggest?search=xn--bcher-beispiel-wob.de"
        idn["registration_tiers"] = [tier(18.40)]; idn["renewal_tiers"] = [tier(24.80)]
        var co = domain("unavailable").rawData?.mapValues(\.value) ?? [:]
        co["provider_url"] = "https://shop.gandi.net/en/domain/suggest?search=cedarcomet.co"
        co["domain_ascii"] = "cedarcomet.co"; co["domain_unicode"] = "cedarcomet.co"
        children.insert(record(id: "preview-hosting-idn", type: "hosting-domain", raw: idn, parent: parentID), at: 2)
        children.insert(record(id: "preview-hosting-co", type: "hosting-domain", raw: co, parent: parentID), at: 4)
        var raw: [String: Any] = ["query": "cedarcomet", "provider": "Gandi", "country": "DE", "currency": "EUR",
            "max_results": 2, "checked_count": 6, "result_count": 2, "available_count": 3, "unavailable_count": 2, "unknown_count": 1,
            "embed_ids": children.map(\.id), "selected_embed_ids": Array(children.prefix(2)).map(\.id), "partial": false,
            "preview_starting_registration": ["amount": 13.09, "currency": "EUR", "tax_basis": "including", "unit": "year", "duration": 1]]
        var status = EmbedStatus.finished
        switch variant {
        case "processing": status = .processing; children = []; raw["embed_ids"] = []; raw["selected_embed_ids"] = []
        case "cancelled": status = .cancelled; children = []; raw["embed_ids"] = []; raw["selected_embed_ids"] = []
        case "empty": children = []; raw["embed_ids"] = []; raw["selected_embed_ids"] = []; raw["result_count"] = 0; raw["checked_count"] = 0; raw["preview_starting_registration"] = NSNull()
        case "error": status = .error; children = children.filter { HostingDomainModel($0).availability == .unknown }; raw["embed_ids"] = children.map(\.id); raw["selected_embed_ids"] = []; raw["result_count"] = 0; raw["error"] = "Synthetic provider unavailable"; raw["partial"] = true
        case "partial": raw["partial"] = true
        case "availableOnly": raw["availability"] = "available_only"
        default: break
        }
        let parent = record(id: parentID, type: "app:hosting:search_domains", status: status, raw: raw)
        return skill(parent, children: children, label: "Search domains")
    }
    static func skill(_ embed: EmbedRecord, children: [EmbedRecord] = [], label: String = "Domain") -> DevEmbedPreviewSkill {
        var records = Dictionary(uniqueKeysWithValues: children.map { ($0.id, $0) }); records[embed.id] = embed
        return DevEmbedPreviewSkill(id: embed.type, label: label, primaryEmbed: embed, childEmbeds: children, allRecords: records)
    }
    static var skills: [DevEmbedPreviewSkill] { [search(), skill(domain())] }
    static func variants(_ base: DevEmbedPreviewSkill, fullscreen: Bool) -> [DevEmbedPreviewVariant] {
        let search = HostingEmbedKind.isSearch(base.primaryEmbed)
        let names = search ? ["default", "processing", "cancelled", "empty", "error", "partial", "availableOnly"]
            : ["default", "unavailable", "unknown", "premium", "minTwoYears", "missingPrice", "longIdn"]
        return names.map { name in
            DevEmbedPreviewVariant(name: name, skill: search ? self.search(name) : skill(domain(name, fullscreen: fullscreen)))
        }
    }
}
#endif
