// Watch embed preview contract.
// Maps regular OpenMates embed records into a small, watchOS-safe card model
// without importing the large iOS/macOS renderer stack. The model keeps private
// content out of continuation links and exposes only compact display fields for
// Watch UI and deterministic unit tests.

import Foundation

enum WatchEmbedPreviewFamily: String, CaseIterable, Sendable {
    case website
    case webVideo
    case image
    case audioRecording
    case code
    case pdf
    case mapPlace
    case searchResults
    case travelStay
    case travelConnection
    case shoppingProduct
    case weather
    case reminder
    case unsupported
}

enum WatchEmbedPreviewState: String, Sendable {
    case ready
    case processing
    case error
}

struct WatchEmbedContinuation: Equatable, Sendable {
    static let handoffActivityType = "org.openmates.app.viewChat"

    let chatId: String?
    let embedId: String
    let handoffActivityType: String
    let universalLink: String?
    let qrPayload: String?

    init(chatId: String?, embedId: String) {
        self.chatId = chatId
        self.embedId = embedId
        self.handoffActivityType = Self.handoffActivityType
        guard let chatId, !chatId.isEmpty else {
            universalLink = nil
            qrPayload = nil
            return
        }
        let link = "https://openmates.org/#chat-id=\(Self.urlFragment(chatId))&embed-id=\(Self.urlFragment(embedId))"
        universalLink = link
        qrPayload = link
    }

    private static func urlFragment(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed) ?? value
    }
}

struct WatchEmbedPreviewModel: Equatable, Identifiable, Sendable {
    static let cardWidth: Double = 156
    static let cardHeight: Double = 112

    let id: String
    let family: WatchEmbedPreviewFamily
    let state: WatchEmbedPreviewState
    let appId: String
    let typeLabel: String
    let title: String
    let subtitle: String?
    let detail: String?
    let continuation: WatchEmbedContinuation

    var isSupported: Bool { family != .unsupported }
}

enum WatchEmbedPreviewMapper {
    static func makeModel(
        for embed: EmbedRecord,
        chatId: String?,
        allEmbedRecords: [String: EmbedRecord] = [:]
    ) -> WatchEmbedPreviewModel {
        let embedType = EmbedType(rawValue: embed.type)
        let family = family(for: embed, embedType: embedType)
        let raw = embed.rawData ?? [:]
        let appId = embed.appId ?? embedType?.appId ?? appId(for: family)
        let state = state(for: embed, family: family)
        let content = content(for: embed, embedType: embedType, family: family, raw: raw, allEmbedRecords: allEmbedRecords)
        return WatchEmbedPreviewModel(
            id: embed.id,
            family: family,
            state: state,
            appId: appId,
            typeLabel: embedType?.displayName ?? sanitizedTypeLabel(embed.type),
            title: state == .error ? content.errorTitle : content.title,
            subtitle: state == .error ? content.errorSubtitle : content.subtitle,
            detail: content.detail,
            continuation: WatchEmbedContinuation(chatId: chatId, embedId: embed.id)
        )
    }

    static func supports(_ embedType: EmbedType) -> Bool {
        family(for: embedType) != nil
    }

    private struct Content {
        let title: String
        let subtitle: String?
        let detail: String?
        let errorTitle: String
        let errorSubtitle: String?
    }

    private static func state(for embed: EmbedRecord, family: WatchEmbedPreviewFamily) -> WatchEmbedPreviewState {
        if embed.status == .processing { return .processing }
        if embed.status == .error || embed.status == .cancelled || family == .unsupported { return .error }
        return .ready
    }

    private static func family(for embed: EmbedRecord, embedType: EmbedType?) -> WatchEmbedPreviewFamily {
        if embed.isAppSkillUse,
           let appId = embed.appId ?? string(embed.rawData ?? [:], keys: ["app_id"]),
           let skillId = embed.skillId ?? string(embed.rawData ?? [:], keys: ["skill_id"]),
           let inferred = EmbedType(rawValue: "app:\(appId):\(skillId)") {
            return family(for: inferred) ?? .unsupported
        }
        guard let embedType else { return .unsupported }
        return family(for: embedType) ?? .unsupported
    }

    private static func family(for embedType: EmbedType) -> WatchEmbedPreviewFamily? {
        switch embedType {
        case .webWebsite, .webRead, .wiki:
            return .website
        case .videosVideo, .videosTranscript:
            return .webVideo
        case .image, .imagesImageResult, .imagesGenerate, .imagesGenerateDraft:
            return .image
        case .recording:
            return .audioRecording
        case .codeCode, .codeGetDocs:
            return .code
        case .pdf, .docsDoc:
            return .pdf
        case .maps, .mapsPlace:
            return .mapPlace
        case .webSearch, .newsSearch, .imagesSearch, .mapsSearch, .travelConnections, .travelStays, .shoppingSearch, .videosSearch:
            return .searchResults
        case .travelStay:
            return .travelStay
        case .travelConnection, .travelFlight:
            return .travelConnection
        case .shoppingProduct:
            return .shoppingProduct
        case .weatherForecast, .weatherDay:
            return .weather
        case .reminderSet, .reminderList, .reminderCancel:
            return .reminder
        default:
            return nil
        }
    }

    private static func content(
        for embed: EmbedRecord,
        embedType: EmbedType?,
        family: WatchEmbedPreviewFamily,
        raw: [String: AnyCodable],
        allEmbedRecords: [String: EmbedRecord]
    ) -> Content {
        let typeLabel = embedType?.displayName ?? sanitizedTypeLabel(embed.type)
        let fallback = typeLabel.isEmpty ? "Preview" : typeLabel
        let title: String
        let subtitle: String?
        let detail: String?

        switch family {
        case .website:
            title = string(raw, keys: ["title", "site_name", "name"]) ?? host(from: string(raw, keys: ["url", "source_page_url"])) ?? fallback
            subtitle = string(raw, keys: ["description", "summary", "url"]).flatMap(cleanText)
            detail = host(from: string(raw, keys: ["url", "source_page_url"]))
        case .webVideo:
            title = string(raw, keys: ["title", "name"]) ?? fallback
            subtitle = string(raw, keys: ["channel", "provider", "source", "url"])
            detail = string(raw, keys: ["duration", "published_at", "publishedAt"])
        case .image:
            title = string(raw, keys: ["title", "alt", "prompt", "source_domain"]) ?? fallback
            subtitle = host(from: string(raw, keys: ["source_page_url", "url"])) ?? string(raw, keys: ["provider", "status"])
            detail = string(raw, keys: ["width", "height"]).map { "\($0)" }
        case .audioRecording:
            title = string(raw, keys: ["title", "filename", "transcript"]).flatMap(cleanText) ?? fallback
            subtitle = string(raw, keys: ["duration", "duration_text", "mime_type"])
            detail = string(raw, keys: ["transcript"]).flatMap(cleanText)
        case .code:
            title = filename(from: string(raw, keys: ["filename", "path"])) ?? string(raw, keys: ["title", "language"]) ?? fallback
            subtitle = string(raw, keys: ["language", "runtime"])
            detail = lineCountText(raw)
        case .pdf:
            title = filename(from: string(raw, keys: ["filename", "title", "name"])) ?? fallback
            subtitle = string(raw, keys: ["page_count", "pages", "status"])
            detail = string(raw, keys: ["summary", "description"]).flatMap(cleanText)
        case .mapPlace:
            title = string(raw, keys: ["name", "title", "address"]) ?? fallback
            subtitle = string(raw, keys: ["address", "formatted_address", "vicinity"])
            detail = string(raw, keys: ["rating", "category", "type"])
        case .searchResults:
            title = string(raw, keys: ["query", "title"]) ?? fallback
            subtitle = resultCountText(embed: embed, raw: raw, allEmbedRecords: allEmbedRecords)
            detail = embedType?.childType?.displayName
        case .travelStay:
            title = string(raw, keys: ["name", "title", "hotel_name"]) ?? fallback
            subtitle = string(raw, keys: ["city", "address", "location"])
            detail = string(raw, keys: ["price", "rating", "nights"])
        case .travelConnection:
            title = routeTitle(raw) ?? string(raw, keys: ["title", "route"]) ?? fallback
            subtitle = string(raw, keys: ["carrier", "airline", "operator", "duration"])
            detail = string(raw, keys: ["price", "departure_time", "arrival_time"])
        case .shoppingProduct:
            title = string(raw, keys: ["name", "title", "product_name"]) ?? fallback
            subtitle = string(raw, keys: ["price", "merchant", "store"])
            detail = string(raw, keys: ["rating", "availability", "brand"])
        case .weather:
            title = string(raw, keys: ["location", "city", "title", "date"]) ?? fallback
            subtitle = string(raw, keys: ["summary", "condition", "temperature", "temp"])
            detail = string(raw, keys: ["high", "low", "precipitation"])
        case .reminder:
            title = string(raw, keys: ["title", "text", "name"]) ?? fallback
            subtitle = string(raw, keys: ["due_at", "due", "date", "time"])
            detail = string(raw, keys: ["status", "list", "recurrence"])
        case .unsupported:
            title = "Unsupported preview"
            subtitle = nil
            detail = nil
        }

        return Content(
            title: cleanText(title) ?? fallback,
            subtitle: subtitle.flatMap(cleanText),
            detail: detail.flatMap(cleanText),
            errorTitle: family == .unsupported ? "Unsupported preview" : "Preview unavailable",
            errorSubtitle: embed.status == .processing ? nil : typeLabel
        )
    }

    private static func string(_ raw: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            guard let value = raw[key]?.value else { continue }
            if let string = value as? String, !string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return string
            }
            if let int = value as? Int { return String(int) }
            if let double = value as? Double { return String(double) }
        }
        return nil
    }

    private static func resultCountText(
        embed: EmbedRecord,
        raw: [String: AnyCodable],
        allEmbedRecords: [String: EmbedRecord]
    ) -> String? {
        if let count = string(raw, keys: ["result_count", "resultCount", "count", "total"]) {
            return "\(count) results"
        }
        if let results = raw["results"]?.value as? [Any] {
            return "\(results.count) results"
        }
        let childCount = embed.childEmbedIds.filter { allEmbedRecords[$0] != nil || !allEmbedRecords.isEmpty }.count
        return childCount > 0 ? "\(childCount) results" : nil
    }

    private static func routeTitle(_ raw: [String: AnyCodable]) -> String? {
        let origin = string(raw, keys: ["origin_code", "departure_airport_code", "from_code", "origin", "from"])
        let destination = string(raw, keys: ["destination_code", "arrival_airport_code", "to_code", "destination", "to"])
        guard let origin, let destination else { return nil }
        return "\(origin) -> \(destination)"
    }

    private static func lineCountText(_ raw: [String: AnyCodable]) -> String? {
        if let count = string(raw, keys: ["line_count", "lineCount"]) {
            return "\(count) lines"
        }
        guard let code = string(raw, keys: ["code"]), !code.isEmpty else { return nil }
        return "\(code.components(separatedBy: .newlines).count) lines"
    }

    private static func filename(from value: String?) -> String? {
        guard let value, !value.isEmpty else { return nil }
        return value.split(separator: "/").last.map(String.init) ?? value
    }

    private static func host(from value: String?) -> String? {
        guard let value, let url = URL(string: value), let host = url.host else { return nil }
        return host.replacingOccurrences(of: "www.", with: "")
    }

    private static func cleanText(_ value: String) -> String? {
        let cleaned = value
            .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return nil }
        if cleaned.first == "{" || cleaned.first == "[" { return nil }
        return cleaned
    }

    private static func sanitizedTypeLabel(_ rawType: String) -> String {
        rawType
            .replacingOccurrences(of: "app:", with: "")
            .replacingOccurrences(of: ":", with: " ")
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .capitalized
    }

    private static func appId(for family: WatchEmbedPreviewFamily) -> String {
        switch family {
        case .website, .searchResults: return "web"
        case .webVideo: return "videos"
        case .image: return "images"
        case .audioRecording: return "audio"
        case .code: return "code"
        case .pdf: return "pdf"
        case .mapPlace: return "maps"
        case .travelStay, .travelConnection: return "travel"
        case .shoppingProduct: return "shopping"
        case .weather: return "weather"
        case .reminder: return "reminder"
        case .unsupported: return "web"
        }
    }
}
