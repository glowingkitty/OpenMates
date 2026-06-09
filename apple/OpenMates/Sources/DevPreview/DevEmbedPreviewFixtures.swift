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
//          frontend/packages/ui/src/components/embeds/events/*.preview.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import Foundation

enum DevEmbedPreviewApp: String, CaseIterable, Identifiable {
    case audio
    case code
    case docs
    case electronics
    case health
    case home
    case web
    case images
    case mail
    case maps
    case math
    case music
    case news
    case nutrition
    case pdf
    case reminder
    case sheets
    case shopping
    case socialMedia = "social_media"
    case travel
    case videos
    case weather
    case events

    var id: String { rawValue }

    var title: String {
        switch self {
        case .audio: return "Audio"
        case .code: return "Code"
        case .docs: return "Docs"
        case .electronics: return "Electronics"
        case .health: return "Health"
        case .home: return "Home"
        case .web: return "Web"
        case .images: return "Images"
        case .mail: return "Mail"
        case .maps: return "Maps"
        case .math: return "Math"
        case .music: return "Music"
        case .news: return "News"
        case .nutrition: return "Nutrition"
        case .pdf: return "PDF"
        case .reminder: return "Reminder"
        case .sheets: return "Sheets"
        case .shopping: return "Shopping"
        case .socialMedia: return "Social"
        case .travel: return "Travel"
        case .videos: return "Videos"
        case .weather: return "Weather"
        case .events: return "Events"
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
        case .audio:
            return [recording]
        case .code:
            return [codeRepoSearch, codeRepo, codeEmbed, codeApplication, codeGetDocs]
        case .docs:
            return [docsDocument]
        case .electronics:
            return [electronicsSearch, electronicsComponent]
        case .health:
            return [healthAppointment, healthSearch]
        case .home:
            return [homeSearch, homeListing]
        case .web:
            return [webSearch, webRead, website]
        case .images:
            return [imageGenerate, imagesSearch, imageResult, imageUpload, imageView]
        case .mail:
            return [mail, mailSearch]
        case .maps:
            return [mapsSearch, mapsLocation]
        case .math:
            return [mathCalculate, mathPlot]
        case .music:
            return [musicGenerate]
        case .news:
            return [newsSearch]
        case .nutrition:
            return [nutritionSearch, nutritionRecipe]
        case .pdf:
            return [pdf]
        case .reminder:
            return [reminderSet, reminderList, reminderCancel]
        case .sheets:
            return [sheet]
        case .shopping:
            return [shoppingSearch, shoppingProduct]
        case .socialMedia:
            return [socialMediaGetPosts, socialMediaSearch, socialMediaPost]
        case .travel:
            return [travelSearch, travelConnection, travelPriceCalendar, travelStay, travelStays]
        case .videos:
            return [videosSearch, video, videoTranscript, videoGenerate]
        case .weather:
            return [weatherForecast, weatherDay]
        case .events:
            return [eventsSearch, event]
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

    // MARK: - Events

    private static var eventsSearch: DevEmbedPreviewSkill {
        let children = eventResults(parentId: "preview-events-search-1")
        let parent = appSkill(
            id: "preview-events-search-1",
            type: EmbedType.eventsSearch.rawValue,
            appId: "events",
            skillId: "search",
            data: [
                "query": "AI meetups in Berlin",
                "provider": "Meetup",
                "providers": ["meetup"]
            ],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "events-search", label: "Search", primary: parent, children: children)
    }

    private static var event: DevEmbedPreviewSkill {
        let embed = eventRecord(
            id: "preview-event-1",
            title: "AI & Machine Learning Berlin Meetup - Spring Edition",
            dateStart: "2026-03-15T19:00:00+01:00",
            dateEnd: "2026-03-15T22:00:00+01:00",
            eventType: "PHYSICAL",
            city: "Berlin",
            country: "Germany",
            rsvpCount: 142,
            isPaid: false,
            feeAmount: nil,
            imageURL: "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?w=1200",
            venueName: "Factory Berlin",
            venueAddress: "Lohmühlenstraße 65",
            venueLatitude: 52.5008,
            venueLongitude: 13.4498,
            parentId: nil
        )
        return skill(id: "events-event", label: "Event", primary: embed)
    }

    // MARK: - Additional registry coverage

    private static var recording: DevEmbedPreviewSkill {
        let embed = record(id: "preview-recording-1", type: EmbedType.recording.rawValue, appId: "audio", data: ["filename": "voice-note.m4a", "duration_seconds": 42, "transcript": "Synthetic voice note transcript for embed parity."])
        return skill(id: "recording", label: "Recording", primary: embed)
    }

    private static var codeRepoSearch: DevEmbedPreviewSkill {
        let child = record(id: "preview-code-repo-1", type: EmbedType.codeRepo.rawValue, appId: "code", data: ["name": "openmates/example", "description": "Synthetic repository fixture", "stars": 128], parentEmbedId: "preview-code-repo-search-1")
        let parent = appSkill(id: "preview-code-repo-search-1", type: EmbedType.codeRepoSearch.rawValue, appId: "code", skillId: "search_repos", data: ["query": "svelte chat UI", "provider": "GitHub"], embedIds: child.id)
        return skill(id: "code-search-repos", label: "Search Repos", primary: parent, children: [child])
    }

    private static var codeRepo: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-repo-direct-1", type: EmbedType.codeRepo.rawValue, appId: "code", data: ["name": "openmates/example", "description": "Synthetic repository fixture", "stars": 128])
        return skill(id: "code-repo", label: "Repository", primary: embed)
    }

    private static var codeApplication: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-application-1", type: EmbedType.codeApplication.rawValue, appId: "code", data: ["title": "Habit Garden", "framework": "vite", "status": "finished"])
        return skill(id: "code-application", label: "Application", primary: embed)
    }

    private static var docsDocument: DevEmbedPreviewSkill {
        let embed = record(id: "preview-docs-doc-1", type: EmbedType.docsDoc.rawValue, appId: "docs", data: ["filename": "architecture.docx", "title": "Architecture Notes", "summary": "PostgreSQL serves as the primary data store."])
        return skill(id: "docs-doc", label: "Document", primary: embed)
    }

    private static var electronicsSearch: DevEmbedPreviewSkill {
        let child = record(id: "preview-electronics-component-1", type: EmbedType.electronicsComponent.rawValue, appId: "electronics", data: ["mpn": "TPS564257DRLR", "description": "Buck converter", "efficiency": "92.4%"], parentEmbedId: "preview-electronics-search-1")
        let parent = appSkill(id: "preview-electronics-search-1", type: EmbedType.electronicsSearch.rawValue, appId: "electronics", skillId: "search_components", data: ["query": "12V to 3.3V buck converter", "provider": "TI WEBENCH"], embedIds: child.id)
        return skill(id: "electronics-search-components", label: "Search Components", primary: parent, children: [child])
    }

    private static var electronicsComponent: DevEmbedPreviewSkill {
        let embed = record(id: "preview-electronics-component-direct-1", type: EmbedType.electronicsComponent.rawValue, appId: "electronics", data: ["mpn": "TPS564257DRLR", "description": "Buck converter", "efficiency": "92.4%"])
        return skill(id: "electronics-component", label: "Component", primary: embed)
    }

    private static var healthAppointment: DevEmbedPreviewSkill {
        let embed = record(id: "preview-health-appointment-1", type: EmbedType.healthAppointment.rawValue, appId: "health", data: ["doctor_name": "Dr. Mueller", "specialty": "Cardiology", "date": "2026-04-03T10:30:00+02:00"])
        return skill(id: "health-appointment", label: "Appointment", primary: embed)
    }

    private static var healthSearch: DevEmbedPreviewSkill {
        let child = healthAppointment.primaryEmbed
        let parent = appSkill(id: "preview-health-search-1", type: EmbedType.healthSearch.rawValue, appId: "health", skillId: "search_appointments", data: ["query": "Cardiologists near Munich", "provider": "Doctolib"], embedIds: child.id)
        return skill(id: "health-search-appointments", label: "Search", primary: parent, children: [child])
    }

    private static var homeListing: DevEmbedPreviewSkill {
        let embed = record(id: "preview-home-listing-1", type: EmbedType.homeListing.rawValue, appId: "home", data: ["title": "2-room apartment in Kreuzberg", "price": "850", "size": "55 m²", "rooms": 2])
        return skill(id: "home-listing", label: "Listing", primary: embed)
    }

    private static var homeSearch: DevEmbedPreviewSkill {
        let child = homeListing.primaryEmbed
        let parent = appSkill(id: "preview-home-search-1", type: EmbedType.homeSearch.rawValue, appId: "home", skillId: "search", data: ["query": "Apartments in Berlin", "provider": "Immobilienscout"], embedIds: child.id)
        return skill(id: "home-search", label: "Search", primary: parent, children: [child])
    }

    private static var mail: DevEmbedPreviewSkill {
        let embed = record(id: "preview-mail-email-1", type: EmbedType.mailEmail.rawValue, appId: "mail", data: ["subject": "Project update", "from": "anna@example.com", "snippet": "The latest sprint review went well."])
        return skill(id: "mail-email", label: "Mail", primary: embed)
    }

    private static var mailSearch: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-mail-search-1", type: EmbedType.mailSearch.rawValue, appId: "mail", skillId: "search", data: ["query": "project update", "provider": "mail"], embedIds: mail.primaryEmbed.id)
        return skill(id: "mail-search", label: "Search", primary: parent, children: [mail.primaryEmbed])
    }

    private static var mapsLocation: DevEmbedPreviewSkill {
        let embed = record(id: "preview-maps-location-1", type: EmbedType.maps.rawValue, appId: "maps", data: ["title": "Berlin Hauptbahnhof", "address": "Europaplatz 1, Berlin", "latitude": 52.5251, "longitude": 13.3694])
        return skill(id: "maps", label: "Location", primary: embed)
    }

    private static var mapsSearch: DevEmbedPreviewSkill {
        let child = record(id: "preview-maps-place-1", type: EmbedType.mapsPlace.rawValue, appId: "maps", data: ["title": "Man vs. Machine Coffee", "address": "Munich", "rating": 4.7], parentEmbedId: "preview-maps-search-1")
        let parent = appSkill(id: "preview-maps-search-1", type: EmbedType.mapsSearch.rawValue, appId: "maps", skillId: "search", data: ["query": "Coffee near Marienplatz", "provider": "Maps"], embedIds: child.id)
        return skill(id: "maps-search", label: "Search", primary: parent, children: [child])
    }

    private static var mathCalculate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-math-calculate-1", type: EmbedType.mathCalculate.rawValue, appId: "math", skillId: "calculate", data: ["expression": "sin(pi/4) + cos(pi/3)", "result": "1.207"])
        return skill(id: "math-calculate", label: "Calculate", primary: embed)
    }

    private static var mathPlot: DevEmbedPreviewSkill {
        let embed = record(id: "preview-math-plot-1", type: EmbedType.mathPlot.rawValue, appId: "math", data: ["title": "sin(x) and cos(x)", "expression": "sin(x), cos(x)"])
        return skill(id: "math-plot", label: "Plot", primary: embed)
    }

    private static var musicGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-music-generate-1", type: EmbedType.musicGenerate.rawValue, appId: "music", skillId: "generate", data: ["prompt": "Ambient synth background loop", "duration_seconds": 30])
        return skill(id: "music-generate", label: "Generate", primary: embed)
    }

    private static var newsSearch: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-news-search-1", type: EmbedType.newsSearch.rawValue, appId: "news", skillId: "search", data: ["query": "Latest technology news", "provider": "Brave News"], embedIds: website.primaryEmbed.id)
        return skill(id: "news-search", label: "Search", primary: parent, children: [website.primaryEmbed])
    }

    private static var nutritionRecipe: DevEmbedPreviewSkill {
        let embed = record(id: "preview-nutrition-recipe-1", type: EmbedType.nutritionRecipe.rawValue, appId: "nutrition", data: ["title": "Spaghetti Aglio e Olio", "duration": "25 min", "servings": 4])
        return skill(id: "nutrition-recipe", label: "Recipe", primary: embed)
    }

    private static var nutritionSearch: DevEmbedPreviewSkill {
        let child = nutritionRecipe.primaryEmbed
        let parent = appSkill(id: "preview-nutrition-search-1", type: EmbedType.nutritionSearch.rawValue, appId: "nutrition", skillId: "search_recipes", data: ["query": "Vegetarian pasta recipes", "provider": "Recipe Search"], embedIds: child.id)
        return skill(id: "nutrition-search-recipes", label: "Search", primary: parent, children: [child])
    }

    private static var pdf: DevEmbedPreviewSkill {
        let embed = record(id: "preview-pdf-1", type: EmbedType.pdf.rawValue, appId: "pdf", data: ["filename": "Q4 2025 Report.pdf", "title": "Q4 2025 Report", "page_count": 18])
        return skill(id: "pdf", label: "PDF", primary: embed)
    }

    private static var reminderSet: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-set-1", type: EmbedType.reminderSet.rawValue, appId: "reminder", skillId: "set-reminder", data: ["title": "Follow up tomorrow", "due_at": "2026-03-16T09:00:00Z"])
        return skill(id: "reminder-set-reminder", label: "Set", primary: embed)
    }

    private static var reminderList: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-list-1", type: EmbedType.reminderList.rawValue, appId: "reminder", skillId: "list-reminders", data: ["count": 2, "title": "Upcoming reminders"])
        return skill(id: "reminder-list-reminders", label: "List", primary: embed)
    }

    private static var reminderCancel: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-cancel-1", type: EmbedType.reminderCancel.rawValue, appId: "reminder", skillId: "cancel-reminder", data: ["title": "Cancelled reminder", "status": "cancelled"])
        return skill(id: "reminder-cancel-reminder", label: "Cancel", primary: embed)
    }

    private static var sheet: DevEmbedPreviewSkill {
        let embed = record(id: "preview-sheets-sheet-1", type: EmbedType.sheetsSheet.rawValue, appId: "sheets", data: ["title": "Budget spreadsheet", "rows": 12, "columns": 8])
        return skill(id: "sheets-sheet", label: "Sheet", primary: embed)
    }

    private static var shoppingProduct: DevEmbedPreviewSkill {
        let embed = record(id: "preview-shopping-product-1", type: EmbedType.shoppingProduct.rawValue, appId: "shopping", data: ["title": "Bio Vollmilch-Joghurt", "price": "1.39", "currency": "EUR"])
        return skill(id: "shopping-product", label: "Product", primary: embed)
    }

    private static var shoppingSearch: DevEmbedPreviewSkill {
        let child = shoppingProduct.primaryEmbed
        let parent = appSkill(id: "preview-shopping-search-1", type: EmbedType.shoppingSearch.rawValue, appId: "shopping", skillId: "search_products", data: ["query": "Wireless headphones under 100 EUR", "provider": "Shopping"], embedIds: child.id)
        return skill(id: "shopping-search-products", label: "Search", primary: parent, children: [child])
    }

    private static var socialMediaPost: DevEmbedPreviewSkill {
        let embed = record(id: "preview-social-media-post-1", type: EmbedType.socialMediaPost.rawValue, appId: "social_media", data: ["platform": "bluesky", "title": "Small cafe bar layout notes", "body": "A compact espresso bar can still feel calm.", "author_display_name": "Sample Cafe Journal"])
        return skill(id: "social-media-post", label: "Post", primary: embed)
    }

    private static var socialMediaGetPosts: DevEmbedPreviewSkill {
        let child = socialMediaPost.primaryEmbed
        let parent = appSkill(id: "preview-social-media-get-posts-1", type: EmbedType.socialMediaGetPosts.rawValue, appId: "social_media", skillId: "get-posts", data: ["query": "@samplegarden.example", "provider": "bluesky_public", "result_count": 1], embedIds: child.id)
        return skill(id: "social-media-get-posts", label: "Get Posts", primary: parent, children: [child])
    }

    private static var socialMediaSearch: DevEmbedPreviewSkill {
        let child = socialMediaPost.primaryEmbed
        let parent = appSkill(id: "preview-social-media-search-1", type: EmbedType.socialMediaSearch.rawValue, appId: "social_media", skillId: "search", data: ["query": "Indie coffee setup inspiration", "provider": "bluesky_public", "result_count": 1], embedIds: child.id)
        return skill(id: "social-media-search", label: "Search", primary: parent, children: [child])
    }

    private static var video: DevEmbedPreviewSkill {
        let embed = record(id: "preview-videos-video-1", type: EmbedType.videosVideo.rawValue, appId: "videos", data: ["title": "Understanding Svelte 5 Runes", "channel": "Sample Channel", "duration_seconds": 620])
        return skill(id: "videos-video", label: "Video", primary: embed)
    }

    private static var videosSearch: DevEmbedPreviewSkill {
        let child = video.primaryEmbed
        let parent = appSkill(id: "preview-videos-search-1", type: EmbedType.videosSearch.rawValue, appId: "videos", skillId: "search", data: ["query": "Svelte 5 tutorial", "provider": "YouTube"], embedIds: child.id)
        return skill(id: "videos-search", label: "Search", primary: parent, children: [child])
    }

    private static var videoTranscript: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-video-transcript-1", type: EmbedType.videosTranscript.rawValue, appId: "videos", skillId: "get_transcript", data: ["title": "Svelte 5 transcript", "transcript": "Today we are going to learn about Svelte 5 runes."])
        return skill(id: "videos-get-transcript", label: "Transcript", primary: embed)
    }

    private static var videoGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-video-generate-1", type: EmbedType.videosGenerate.rawValue, appId: "videos", skillId: "generate", data: ["title": "Product launch promo", "duration_seconds": 15])
        return skill(id: "videos-generate", label: "Generate", primary: embed)
    }

    private static var weatherDay: DevEmbedPreviewSkill {
        let embed = record(id: "preview-weather-day-1", type: EmbedType.weatherDay.rawValue, appId: "weather", data: ["date": "2026-06-03", "location_name": "Berlin", "condition": "rain", "temperature_min_c": 14, "temperature_max_c": 19])
        return skill(id: "weather-day", label: "Day", primary: embed)
    }

    private static var weatherForecast: DevEmbedPreviewSkill {
        let child = weatherDay.primaryEmbed
        let parent = appSkill(id: "preview-weather-forecast-1", type: EmbedType.weatherForecast.rawValue, appId: "weather", skillId: "forecast", data: ["query": "Berlin weather forecast", "provider": "Deutscher Wetterdienst", "location": ["name": "Berlin"]], embedIds: child.id)
        return skill(id: "weather-forecast", label: "Forecast", primary: parent, children: [child])
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
        return record(
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
        let destinationCode = destination.contains("Gatwick") ? "LGW" : "LHR"
        let destinationLatitude = destination.contains("Gatwick") ? 51.1537 : 51.4700
        let destinationLongitude = destination.contains("Gatwick") ? -0.1821 : -0.4543
        return record(
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
                "origin_country_code": "DE",
                "destination_country_code": "GB",
                "departure": departure,
                "arrival": arrival,
                "duration": duration,
                "stops": stops,
                "carrier_codes": carrierCodes,
                "carriers": carrierCodes,
                "booking_url": "https://www.google.com/travel/flights",
                "booking_provider": "Google Flights",
                "legs": [[
                    "leg_index": 0,
                    "origin": "Munich (MUC)",
                    "destination": destination,
                    "departure": departure,
                    "arrival": arrival,
                    "duration": duration,
                    "stops": stops,
                    "segments": [[
                        "carrier": carrierCodes.first ?? "LH",
                        "carrier_code": carrierCodes.first ?? "LH",
                        "number": "\(carrierCodes.first ?? "LH") 123",
                        "departure_station": "MUC",
                        "departure_time": departure,
                        "departure_country_code": "DE",
                        "departure_is_daytime": false,
                        "departure_latitude": 48.3538,
                        "departure_longitude": 11.7861,
                        "arrival_station": destinationCode,
                        "arrival_time": arrival,
                        "arrival_country_code": "GB",
                        "arrival_is_daytime": false,
                        "arrival_latitude": destinationLatitude,
                        "arrival_longitude": destinationLongitude,
                        "duration": duration,
                        "travel_class": "Economy"
                    ]]
                ]]
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
                "link": "https://www.google.com/travel/hotels",
                "thumbnail": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=1200",
                "gps_coordinates": [
                    "latitude": 41.3874,
                    "longitude": 2.1686
                ],
                "amenities": ["Free Wi-Fi", "Breakfast included", "Spa", "Fitness center"],
                "free_cancellation": true,
                "eco_certified": true
            ],
            parentEmbedId: parentId
        )
    }

    private static func eventResults(parentId: String) -> [EmbedRecord] {
        [
            eventRecord(
                id: "preview-events-result-1",
                title: "AI & Machine Learning Berlin Meetup - Spring Edition",
                dateStart: "2026-03-15T19:00:00+01:00",
                dateEnd: "2026-03-15T22:00:00+01:00",
                eventType: "PHYSICAL",
                city: "Berlin",
                country: "Germany",
                rsvpCount: 142,
                isPaid: false,
                feeAmount: nil,
                imageURL: "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?w=1200",
                venueName: "Factory Berlin",
                venueAddress: "Lohmühlenstraße 65",
                venueLatitude: 52.5008,
                venueLongitude: 13.4498,
                parentId: parentId
            ),
            eventRecord(
                id: "preview-events-result-2",
                title: "TypeScript Deep Dive: Advanced Patterns for Scalable Apps",
                dateStart: "2026-03-20T18:00:00Z",
                dateEnd: "2026-03-20T20:00:00Z",
                eventType: "ONLINE",
                city: nil,
                country: nil,
                rsvpCount: 87,
                isPaid: false,
                feeAmount: nil,
                imageURL: "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=1200",
                venueName: nil,
                venueAddress: nil,
                venueLatitude: nil,
                venueLongitude: nil,
                parentId: parentId
            ),
            eventRecord(
                id: "preview-events-result-3",
                title: "Product Management Summit - London 2026",
                dateStart: "2026-04-05T09:00:00+01:00",
                dateEnd: "2026-04-06T17:00:00+01:00",
                eventType: "PHYSICAL",
                city: "London",
                country: "United Kingdom",
                rsvpCount: 320,
                isPaid: true,
                feeAmount: 25,
                imageURL: "https://images.unsplash.com/photo-1505373877841-8d25f7d46678?w=1200",
                venueName: "Business Design Centre",
                venueAddress: "52 Upper Street",
                venueLatitude: 51.5356,
                venueLongitude: -0.1066,
                parentId: parentId
            )
        ]
    }

    private static func eventRecord(
        id: String,
        title: String,
        dateStart: String,
        dateEnd: String,
        eventType: String,
        city: String?,
        country: String?,
        rsvpCount: Int,
        isPaid: Bool,
        feeAmount: Double?,
        imageURL: String?,
        venueName: String?,
        venueAddress: String?,
        venueLatitude: Double?,
        venueLongitude: Double?,
        parentId: String?
    ) -> EmbedRecord {
        var data: [String: Any] = [
            "type": "event_result",
            "provider": "meetup",
            "title": title,
            "description": "Join us for an evening of talks, creative exchange, and community networking.",
            "url": "https://www.meetup.com/example-ai-berlin/events/preview",
            "date_start": dateStart,
            "date_end": dateEnd,
            "timezone": "Europe/Berlin",
            "event_type": eventType,
            "organizer_name": "AI Berlin Community",
            "rsvp_count": rsvpCount,
            "is_paid": isPaid,
            "app_id": "events",
            "skill_id": "search"
        ]
        if let imageURL { data["image_url"] = imageURL }
        if let venueName { data["venue_name"] = venueName }
        if let venueAddress { data["venue_address"] = venueAddress }
        if let venueLatitude { data["venue_lat"] = venueLatitude }
        if let venueLongitude { data["venue_lon"] = venueLongitude }
        if let city { data["venue_city"] = city }
        if let country { data["venue_country"] = country }
        if let feeAmount {
            data["fee_amount"] = feeAmount
            data["fee_currency"] = "GBP"
        }
        return record(
            id: id,
            type: EmbedType.eventsEvent.rawValue,
            appId: "events",
            data: data,
            parentEmbedId: parentId
        )
    }
}
#endif
