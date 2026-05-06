// Embed data models for all 33 embed types.
// Each type has a content struct matching the backend schema.
// Status machine: processing → finished | error | cancelled.

import Foundation

// MARK: - Embed status

enum EmbedStatus: String, Codable, Sendable {
    case processing
    case finished
    case error
    case cancelled
}

// MARK: - Embed record

struct EmbedRecord: Identifiable, Decodable, @unchecked Sendable {
    let id: String
    let type: String
    let status: EmbedStatus
    let data: EmbedData?
    let parentEmbedId: String?
    let appId: String?
    let skillId: String?
    let embedIds: String?
    let createdAt: String?

    var childEmbedIds: [String] {
        guard let embedIds else { return [] }
        return embedIds
            .split { $0 == "|" || $0 == "," }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    var rawData: [String: AnyCodable]? {
        guard let data, case .raw(let dict) = data else { return nil }
        return dict
    }

    var isAppSkillUse: Bool {
        rawData?["type"]?.value as? String == "app_skill_use"
    }
}

// MARK: - Embed type enum (33 types)

enum EmbedType: String, CaseIterable {
    // Direct embeds
    case recording
    case codeCode = "code-code"
    case docsDoc = "docs-doc"
    case image
    case mailEmail = "mail-email"
    case maps
    case mathPlot = "math-plot"
    case pdf
    case sheetsSheet = "sheets-sheet"
    case focusModeActivation = "focus-mode-activation"

    // Composite search embeds
    case eventsSearch = "app:events:search"
    case eventsEvent = "events-event"
    case healthSearch = "app:health:search_appointments"
    case healthAppointment = "health-appointment"
    case homeSearch = "app:home:search"
    case homeListing = "home-listing"
    case imagesSearch = "app:images:search"
    case imagesImageResult = "images-image-result"
    case mailSearch = "app:mail:search"
    case mapsSearch = "app:maps:search"
    case mapsPlace = "maps-place"
    case newsSearch = "app:news:search"
    case nutritionSearch = "app:nutrition:search_recipes"
    case nutritionRecipe = "nutrition-recipe"
    case shoppingSearch = "app:shopping:search_products"
    case shoppingProduct = "shopping-product"
    case travelConnections = "app:travel:search_connections"
    case travelConnection = "travel-connection"
    case travelStays = "app:travel:search_stays"
    case travelStay = "travel-stay"
    case travelPriceCalendar = "app:travel:price_calendar"
    case travelFlight = "app:travel:get_flight"
    case videosSearch = "app:videos:search"
    case videosVideo = "videos-video"
    case videosTranscript = "app:videos:get_transcript"
    case webSearch = "app:web:search"
    case webWebsite = "web-website"
    case webRead = "app:web:read"
    case wiki

    // App skill use embeds
    case codeGetDocs = "app:code:get_docs"
    case imagesGenerate = "app:images:generate"
    case imagesGenerateDraft = "app:images:generate_draft"
    case mathCalculate = "app:math:calculate"
    case reminderSet = "app:reminder:set-reminder"

    var isComposite: Bool {
        switch self {
        case .eventsSearch, .healthSearch, .homeSearch, .imagesSearch,
             .mailSearch, .mapsSearch, .newsSearch, .nutritionSearch,
             .shoppingSearch, .travelConnections, .travelStays,
             .videosSearch, .webSearch:
            return true
        default:
            return false
        }
    }

    var childType: EmbedType? {
        switch self {
        case .eventsSearch: return .eventsEvent
        case .healthSearch: return .healthAppointment
        case .homeSearch: return .homeListing
        case .imagesSearch: return .imagesImageResult
        case .mapsSearch: return .mapsPlace
        case .newsSearch: return .webWebsite
        case .nutritionSearch: return .nutritionRecipe
        case .shoppingSearch: return .shoppingProduct
        case .travelConnections: return .travelConnection
        case .travelStays: return .travelStay
        case .videosSearch: return .videosVideo
        case .webSearch: return .webWebsite
        default: return nil
        }
    }

    var appId: String? {
        let raw = rawValue
        guard raw.hasPrefix("app:") else {
            switch self {
            case .codeCode: return "code"
            case .docsDoc: return "docs"
            case .recording: return "audio"
            case .image, .imagesImageResult: return "photos"
            case .maps, .mapsPlace: return "maps"
            case .mailEmail: return "mail"
            case .mathPlot: return "math"
            case .pdf: return "pdf"
            case .sheetsSheet: return "sheets"
            case .webWebsite: return "web"
            case .wiki: return "study"
            case .videosVideo: return "videos"
            case .eventsEvent: return "events"
            case .healthAppointment: return "health"
            case .homeListing: return "home"
            case .nutritionRecipe: return "nutrition"
            case .shoppingProduct: return "shopping"
            case .travelConnection, .travelStay: return "travel"
            default: return nil
            }
        }
        let parts = raw.split(separator: ":")
        return parts.count >= 2 ? String(parts[1]) : nil
    }

    var displayName: String {
        switch self {
        case .webSearch, .newsSearch: return "Search"
        case .webRead: return "Read"
        case .webWebsite: return "Website"
        case .wiki: return "Wikipedia"
        case .codeCode: return "Code"
        case .codeGetDocs: return "Docs"
        case .docsDoc: return "Document"
        case .image: return "Image"
        case .imagesSearch: return "Image Search"
        case .imagesGenerate, .imagesGenerateDraft: return "Generated Image"
        case .imagesImageResult: return "Image"
        case .maps, .mapsSearch: return "Map"
        case .mapsPlace: return "Place"
        case .mailEmail, .mailSearch: return "Email"
        case .mathPlot: return "Plot"
        case .mathCalculate: return "Calculate"
        case .pdf: return "PDF"
        case .sheetsSheet: return "Sheet"
        case .recording: return "Recording"
        case .videosSearch: return "Video Search"
        case .videosVideo: return "Video"
        case .videosTranscript: return "Transcript"
        case .eventsSearch: return "Events"
        case .eventsEvent: return "Event"
        case .healthSearch: return "Appointments"
        case .healthAppointment: return "Appointment"
        case .homeSearch: return "Listings"
        case .homeListing: return "Listing"
        case .nutritionSearch: return "Recipes"
        case .nutritionRecipe: return "Recipe"
        case .shoppingSearch: return "Products"
        case .shoppingProduct: return "Product"
        case .travelConnections: return "Connections"
        case .travelConnection: return "Connection"
        case .travelStays: return "Stays"
        case .travelStay: return "Stay"
        case .travelPriceCalendar: return "Price Calendar"
        case .travelFlight: return "Flight"
        case .focusModeActivation: return "Focus Mode"
        case .reminderSet: return "Reminder"
        }
    }
}

// MARK: - Decoded embed content types

enum EmbedData: Decodable, @unchecked Sendable {
    case webSearch(WebSearchContent)
    case website(WebsiteContent)
    case webRead(WebReadContent)
    case code(CodeContent)
    case docs(DocsContent)
    case video(VideoContent)
    case videoSearch(VideoSearchContent)
    case transcript(TranscriptContent)
    case imageResult(ImageResultContent)
    case imageGenerate(ImageGenerateContent)
    case mapsPlace(MapsPlaceContent)
    case mapsSearch(MapsSearchContent)
    case travelConnection(TravelConnectionContent)
    case travelStay(TravelStayContent)
    case travelPriceCalendar(TravelPriceCalendarContent)
    case travelFlight(TravelFlightContent)
    case event(EventContent)
    case appointment(AppointmentContent)
    case listing(HomeListingContent)
    case recipe(RecipeContent)
    case product(ShoppingProductContent)
    case mailEmail(MailEmailContent)
    case sheet(SheetContent)
    case mathPlot(MathPlotContent)
    case mathCalculate(MathCalculateContent)
    case recording(RecordingContent)
    case pdf(PDFContent)
    case image(ImageContent)
    case reminder(ReminderContent)
    case focusMode(FocusModeContent)
    case codeGetDocs(CodeGetDocsContent)
    case raw([String: AnyCodable])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        self = .raw(try container.decode([String: AnyCodable].self))
    }
}

// MARK: - Content structs for each embed type

struct WebSearchContent: Codable {
    let query: String
    let provider: String?
    let resultCount: Int?
    let embedIds: String?
}

struct WebsiteContent: Codable {
    let url: String
    let title: String?
    let description: String?
    let pageAge: String?
    let metaUrlFavicon: String?
    let thumbnailOriginal: String?
    let extraSnippets: String?
}

struct WebReadContent: Codable {
    let url: String
    let title: String?
    let content: String?
    let wordCount: Int?
}

struct CodeContent: Codable {
    let language: String?
    let code: String
    let filename: String?
    let lineCount: Int?
}

struct DocsContent: Codable {
    let html: String?
    let title: String?
    let wordCount: Int?
}

struct VideoContent: Codable {
    let title: String?
    let url: String?
    let thumbnailUrl: String?
    let duration: String?
    let channel: String?
}

struct VideoSearchContent: Codable {
    let query: String?
    let resultCount: Int?
    let embedIds: String?
}

struct TranscriptContent: Codable {
    let videoUrl: String?
    let title: String?
    let transcript: String?
    let language: String?
}

struct ImageResultContent: Codable {
    let url: String?
    let title: String?
    let sourceUrl: String?
    let thumbnailUrl: String?
    let width: Int?
    let height: Int?
}

struct ImageGenerateContent: Codable {
    let prompt: String?
    let model: String?
    let s3BaseUrl: String?
    let aesKey: String?
    let aesNonce: String?
}

struct MapsPlaceContent: Codable {
    let name: String?
    let address: String?
    let latitude: Double?
    let longitude: Double?
    let rating: Double?
    let phoneNumber: String?
    let website: String?
    let openingHours: String?
    let category: String?
}

struct MapsSearchContent: Codable {
    let query: String?
    let resultCount: Int?
    let embedIds: String?
}

struct TravelConnectionContent: Codable {
    let departure: String?
    let arrival: String?
    let departureTime: String?
    let arrivalTime: String?
    let price: Double?
    let currency: String?
    let duration: String?
    let transfers: Int?
    let carrier: String?
    let transportType: String?
}

struct TravelStayContent: Codable {
    let name: String?
    let location: String?
    let pricePerNight: Double?
    let currency: String?
    let rating: Double?
    let imageUrl: String?
    let checkIn: String?
    let checkOut: String?
    let amenities: String?
    let bookingUrl: String?
}

struct TravelPriceCalendarContent: Codable {
    let origin: String?
    let destination: String?
    let prices: [String: Double]?
}

struct TravelFlightContent: Codable {
    let airline: String?
    let flightNumber: String?
    let departure: String?
    let arrival: String?
    let departureTime: String?
    let arrivalTime: String?
    let duration: String?
    let price: Double?
    let currency: String?
    let cabin: String?
}

struct EventContent: Codable {
    let title: String?
    let date: String?
    let time: String?
    let location: String?
    let description: String?
    let url: String?
    let price: String?
    let imageUrl: String?
}

struct AppointmentContent: Codable {
    let doctorName: String?
    let specialty: String?
    let date: String?
    let time: String?
    let location: String?
    let bookingUrl: String?
}

struct HomeListingContent: Codable {
    let title: String?
    let price: Double?
    let currency: String?
    let address: String?
    let rooms: Int?
    let area: Double?
    let imageUrl: String?
    let url: String?
}

struct RecipeContent: Codable {
    let title: String?
    let description: String?
    let imageUrl: String?
    let prepTime: String?
    let cookTime: String?
    let servings: Int?
    let calories: Int?
    let url: String?
    let ingredients: String?
}

struct ShoppingProductContent: Codable {
    let title: String?
    let price: Double?
    let currency: String?
    let imageUrl: String?
    let url: String?
    let rating: Double?
    let reviewCount: Int?
    let seller: String?
    let description: String?
}

struct MailEmailContent: Codable {
    let subject: String?
    let to: String?
    let body: String?
}

struct SheetContent: Codable {
    let markdown: String?
    let title: String?
}

struct MathPlotContent: Codable {
    let svgData: String?
    let title: String?
}

struct MathCalculateContent: Codable {
    let expression: String?
    let result: String?
    let steps: String?
}

struct RecordingContent: Codable {
    let duration: Double?
    let s3Url: String?
    let aesKey: String?
    let aesNonce: String?
    let transcription: String?
}

struct PDFContent: Codable {
    let filename: String?
    let pageCount: Int?
    let s3Url: String?
    let aesKey: String?
    let aesNonce: String?
}

struct ImageContent: Codable {
    let filename: String?
    let width: Int?
    let height: Int?
    let s3Url: String?
    let aesKey: String?
    let aesNonce: String?
    let mimeType: String?
}

struct ReminderContent: Codable {
    let title: String?
    let datetime: String?
    let recurring: String?
}

struct FocusModeContent: Codable {
    let focusId: String?
    let appId: String?
}

struct CodeGetDocsContent: Codable {
    let query: String?
    let library: String?
    let content: String?
}
