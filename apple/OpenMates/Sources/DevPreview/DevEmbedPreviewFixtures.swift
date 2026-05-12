// Debug fixtures for native embed preview galleries.
// Mirrors the deployed Svelte /dev/preview/embeds app showcase sections so
// Xcode simulator screenshots can be compared against app.dev.openmates.org.
// This file is compiled in Debug builds only.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/dev/preview/embeds/[app]/+page.svelte
//          frontend/packages/ui/src/components/embeds/web/*.preview.ts
//          frontend/packages/ui/src/components/embeds/images/*.preview.ts
//          frontend/packages/ui/src/components/embeds/travel/*.preview.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import Foundation

enum DevEmbedPreviewApp: String, CaseIterable, Identifiable {
    case code
    case web
    case images
    case travel

    var id: String { rawValue }

    var title: String {
        switch self {
        case .code: return "Code"
        case .web: return "Web"
        case .images: return "Images"
        case .travel: return "Travel"
        }
    }
}

struct DevEmbedPreviewSkill: Identifiable {
    let id: String
    let label: String
    let primaryEmbed: EmbedRecord
    let childEmbeds: [EmbedRecord]
    let allRecords: [String: EmbedRecord]
}

enum DevEmbedPreviewFixtures {
    static func skills(for app: DevEmbedPreviewApp) -> [DevEmbedPreviewSkill] {
        switch app {
        case .code:
            return [codeEmbed, codeGetDocs]
        case .web:
            return [webSearch, webRead, website]
        case .images:
            return [imageGenerate, imagesSearch, imageResult, imageUpload, imageView]
        case .travel:
            return [travelSearch, travelConnection, travelPriceCalendar, travelStay, travelStays]
        }
    }

    // MARK: - Code

    private static var codeEmbed: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-code-1",
            type: EmbedType.codeCode.rawValue,
            appId: "code",
            skillId: "code",
            data: [
                "type": "code",
                "app_id": "code",
                "skill_id": "code",
                "language": "svelte",
                "filename": "MyComponent.svelte",
                "line_count": 28,
                "code": """
                <script lang="ts">
                  let count = $state(0);
                  let doubled = $derived(count * 2);

                  function increment() {
                    count += 1;
                  }
                </script>

                <section class="counter">
                  <h1>Svelte 5 Counter</h1>
                  <button onclick={increment}>
                    Count: {count}
                  </button>
                  <p>Doubled: {doubled}</p>
                </section>

                <style>
                  .counter {
                    display: grid;
                    gap: 1rem;
                    place-items: center;
                    padding: 2rem;
                  }
                </style>
                """
            ]
        )
        return skill(id: "code-code", label: "Code", primary: embed)
    }

    private static var codeGetDocs: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-code-get-docs-1",
            type: EmbedType.codeGetDocs.rawValue,
            appId: "code",
            skillId: "get_docs",
            data: [
                "library": "svelte",
                "question": "How does the $state rune work in Svelte 5?",
                "results": [[
                    "library_id": "/sveltejs/svelte",
                    "library_title": "Svelte",
                    "content": "The $state rune declares reactive state. Mutating that state updates every dependent expression and template binding.",
                    "word_count": 1180
                ]],
                "word_count": 1180
            ]
        )
        return skill(id: "code-get-docs", label: "Get Docs", primary: embed)
    }

    // MARK: - Web

    private static var webSearch: DevEmbedPreviewSkill {
        let children = [
            record(
                id: "preview-web-search-result-1",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.visitberlin.de/en/restaurants",
                    "title": "Top 10 Restaurants in Berlin - Local Guide",
                    "description": "Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors. Updated for 2026."
                ],
                parentEmbedId: "preview-web-search-1"
            ),
            record(
                id: "preview-web-search-result-2",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.timeout.com/berlin/restaurants",
                    "title": "Berlin Food Scene: A Complete Guide",
                    "description": "From street food to Michelin-starred restaurants, explore what makes Berlin one of Europe's top food destinations."
                ],
                parentEmbedId: "preview-web-search-1"
            ),
            record(
                id: "preview-web-search-result-3",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.lonelyplanet.com/germany/berlin/restaurants",
                    "title": "Where to Eat in Berlin - Travel Blog",
                    "description": "A curated list of must-visit restaurants, cafes, and food markets in Berlin. Includes budget-friendly options."
                ],
                parentEmbedId: "preview-web-search-1"
            )
        ]
        let parent = appSkill(
            id: "preview-web-search-1",
            type: EmbedType.webSearch.rawValue,
            appId: "web",
            skillId: "search",
            data: ["query": "best restaurants in Berlin", "provider": "Brave Search"],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "web-search", label: "Search", primary: parent, children: children)
    }

    private static var webRead: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-web-read-1",
            type: EmbedType.webRead.rawValue,
            appId: "web",
            skillId: "read",
            data: [
                "url": "https://svelte.dev/blog/svelte-5-migration-guide",
                "title": "Complete Guide to Migrating from Svelte 4 to Svelte 5",
                "content": "Svelte 5 introduces runes, a powerful new reactivity system that replaces the $: reactive statements. This guide walks you through every step of the migration process, from updating your dependencies to converting your components.",
                "word_count": 1280
            ]
        )
        return skill(id: "web-read", label: "Read", primary: embed)
    }

    private static var website: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-website-1",
            type: EmbedType.webWebsite.rawValue,
            appId: "web",
            data: [
                "url": "https://svelte.dev",
                "title": "Svelte - Cybernetically enhanced web apps",
                "description": "Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.",
                "favicon_url": "https://svelte.dev/favicon.png"
            ]
        )
        return skill(id: "web-website", label: "Website", primary: embed)
    }

    // MARK: - Images

    private static var imageGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-image-gen-1",
            type: EmbedType.imagesGenerate.rawValue,
            appId: "images",
            skillId: "generate",
            data: [
                "prompt": "A serene mountain landscape at sunset with vibrant orange and purple skies",
                "model": "flux-schnell"
            ]
        )
        return skill(id: "images-generate", label: "Generate", primary: embed)
    }

    private static var imagesSearch: DevEmbedPreviewSkill {
        let results = imageSearchResults(parentId: "preview-images-search-1")
        let parent = appSkill(
            id: "preview-images-search-1",
            type: EmbedType.imagesSearch.rawValue,
            appId: "images",
            skillId: "search",
            data: ["query": "Golden Gate Bridge", "provider": "Brave"],
            embedIds: results.map(\.id).joined(separator: "|")
        )
        return skill(id: "images-search", label: "Search", primary: parent, children: results)
    }

    private static var imageResult: DevEmbedPreviewSkill {
        let embed = imageResultRecord(
            id: "preview-image-result-1",
            title: "Golden Gate Bridge at dusk",
            thumbnail: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
            image: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
            parentId: nil
        )
        return skill(id: "images-result", label: "Image Result", primary: embed)
    }

    private static var imageUpload: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-image-embed-1",
            type: EmbedType.image.rawValue,
            appId: "images",
            data: ["filename": "golden-gate-sunset.jpg"]
        )
        return skill(id: "images-upload", label: "Upload", primary: embed)
    }

    private static var imageView: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-image-view-1",
            type: "app:images:view",
            appId: "images",
            skillId: "view",
            data: ["filename": "golden-gate-sunset.jpg"]
        )
        return skill(id: "images-view", label: "View", primary: embed)
    }

    // MARK: - Travel

    private static var travelSearch: DevEmbedPreviewSkill {
        let children = [
            travelConnectionRecord(
                id: "preview-travel-search-result-1",
                price: "189.00",
                destination: "London Heathrow (LHR)",
                departure: "2026-03-15T08:30:00",
                arrival: "2026-03-15T10:00:00",
                duration: "2h 30m",
                stops: 0,
                carrierCodes: ["LH"],
                parentId: "preview-travel-search-1"
            ),
            travelConnectionRecord(
                id: "preview-travel-search-result-2",
                price: "245.50",
                destination: "London Gatwick (LGW)",
                departure: "2026-03-15T14:15:00",
                arrival: "2026-03-15T17:45:00",
                duration: "4h 30m",
                stops: 1,
                carrierCodes: ["BA", "EW"],
                parentId: "preview-travel-search-1"
            )
        ]
        let parent = appSkill(
            id: "preview-travel-search-1",
            type: EmbedType.travelConnections.rawValue,
            appId: "travel",
            skillId: "search_connections",
            data: ["query": "Munich -> London, 2026-03-15", "provider": "Google"],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "travel-search", label: "Search", primary: parent, children: children)
    }

    private static var travelConnection: DevEmbedPreviewSkill {
        let embed = travelConnectionRecord(
            id: "preview-travel-connection-1",
            price: "189.00",
            destination: "London Heathrow (LHR)",
            departure: "2026-03-15T08:30:00",
            arrival: "2026-03-15T10:00:00",
            duration: "2h 30m",
            stops: 0,
            carrierCodes: ["LH"],
            parentId: nil
        )
        return skill(id: "travel-connection", label: "Connection", primary: embed)
    }

    private static var travelPriceCalendar: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-travel-price-calendar-1",
            type: EmbedType.travelPriceCalendar.rawValue,
            appId: "travel",
            skillId: "price_calendar",
            data: [
                "query": "Munich -> Barcelona, March 2026",
                "origin": "Munich",
                "destination": "Barcelona"
            ]
        )
        return skill(id: "travel-price-calendar", label: "Price Calendar", primary: embed)
    }

    private static var travelStay: DevEmbedPreviewSkill {
        let embed = travelStayRecord(
            id: "preview-travel-stay-1",
            name: "Hotel Maximilian",
            hotelClass: 4,
            rating: 4.3,
            reviews: 1248,
            ratePerNight: "129",
            totalRate: "387",
            parentId: nil
        )
        return skill(id: "travel-stay", label: "Stay", primary: embed)
    }

    private static var travelStays: DevEmbedPreviewSkill {
        let children = [
            travelStayRecord(id: "preview-travel-stays-result-1", name: "Hotel Arts Barcelona", hotelClass: 5, rating: 4.7, reviews: 4521, ratePerNight: "320", totalRate: "960", parentId: "preview-travel-stays-1"),
            travelStayRecord(id: "preview-travel-stays-result-2", name: "Casa Camper Barcelona", hotelClass: 4, rating: 4.4, reviews: 1832, ratePerNight: "185", totalRate: "555", parentId: "preview-travel-stays-1"),
            travelStayRecord(id: "preview-travel-stays-result-3", name: "Generator Barcelona", hotelClass: 2, rating: 4.0, reviews: 3200, ratePerNight: "55", totalRate: "165", parentId: "preview-travel-stays-1")
        ]
        let parent = appSkill(
            id: "preview-travel-stays-1",
            type: EmbedType.travelStays.rawValue,
            appId: "travel",
            skillId: "search_stays",
            data: ["query": "Hotels in Barcelona, Mar 15-18", "provider": "Google"],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "travel-stays", label: "Stays Search", primary: parent, children: children)
    }

    // MARK: - Builders

    private static func skill(
        id: String,
        label: String,
        primary: EmbedRecord,
        children: [EmbedRecord] = []
    ) -> DevEmbedPreviewSkill {
        DevEmbedPreviewSkill(
            id: id,
            label: label,
            primaryEmbed: primary,
            childEmbeds: children,
            allRecords: ([primary] + children).reduce(into: [:]) { records, embed in
                records[embed.id] = embed
            }
        )
    }

    private static func appSkill(
        id: String,
        type: String,
        appId: String,
        skillId: String,
        data: [String: Any],
        status: EmbedStatus = .finished,
        embedIds: String? = nil
    ) -> EmbedRecord {
        var raw = data
        raw["type"] = "app_skill_use"
        raw["app_id"] = appId
        raw["skill_id"] = skillId
        return record(id: id, type: type, status: status, appId: appId, skillId: skillId, data: raw, embedIds: embedIds)
    }

    private static func record(
        id: String,
        type: String,
        status: EmbedStatus = .finished,
        appId: String?,
        skillId: String? = nil,
        data: [String: Any],
        parentEmbedId: String? = nil,
        embedIds: String? = nil
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: status,
            data: .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            createdAt: "2026-03-15T08:30:00Z"
        )
    }

    private static func imageSearchResults(parentId: String) -> [EmbedRecord] {
        [
            imageResultRecord(id: "preview-images-search-result-1", title: "Golden Gate Bridge at dusk", thumbnail: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200", image: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29", parentId: parentId),
            imageResultRecord(id: "preview-images-search-result-2", title: "Aerial view of Golden Gate", thumbnail: "https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?w=200", image: "https://images.unsplash.com/photo-1506146332389-18140dc7b2fb", parentId: parentId),
            imageResultRecord(id: "preview-images-search-result-3", title: "Golden Gate Bridge towers in fog", thumbnail: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=200", image: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64", parentId: parentId)
        ]
    }

    private static func imageResultRecord(id: String, title: String, thumbnail: String, image: String, parentId: String?) -> EmbedRecord {
        record(
            id: id,
            type: EmbedType.imagesImageResult.rawValue,
            appId: "images",
            data: [
                "title": title,
                "source": "unsplash.com",
                "source_domain": "unsplash.com",
                "thumbnail_url": thumbnail,
                "image_url": image,
                "source_page_url": "https://unsplash.com/photos/Cs99I6PYLlk"
            ],
            parentEmbedId: parentId
        )
    }

    private static func travelConnectionRecord(
        id: String,
        price: String,
        destination: String,
        departure: String,
        arrival: String,
        duration: String,
        stops: Int,
        carrierCodes: [String],
        parentId: String?
    ) -> EmbedRecord {
        record(
            id: id,
            type: EmbedType.travelConnection.rawValue,
            appId: "travel",
            data: [
                "price": price,
                "total_price": price,
                "currency": "EUR",
                "transport_method": "airplane",
                "trip_type": "one_way",
                "origin": "Munich (MUC)",
                "destination": destination,
                "departure": departure,
                "arrival": arrival,
                "duration": duration,
                "stops": stops,
                "carrier_codes": carrierCodes,
                "carriers": carrierCodes
            ],
            parentEmbedId: parentId
        )
    }

    private static func travelStayRecord(
        id: String,
        name: String,
        hotelClass: Int,
        rating: Double,
        reviews: Int,
        ratePerNight: String,
        totalRate: String,
        parentId: String?
    ) -> EmbedRecord {
        record(
            id: id,
            type: EmbedType.travelStay.rawValue,
            appId: "travel",
            data: [
                "name": name,
                "hotel_class": hotelClass,
                "overall_rating": rating,
                "rating": rating,
                "reviews": reviews,
                "currency": "EUR",
                "rate_per_night": ratePerNight,
                "price_per_night": Double(ratePerNight) ?? 0,
                "total_rate": totalRate,
                "amenities": ["Free Wi-Fi", "Breakfast included", "Spa", "Fitness center"],
                "free_cancellation": true,
                "eco_certified": true
            ],
            parentEmbedId: parentId
        )
    }
}
#endif
