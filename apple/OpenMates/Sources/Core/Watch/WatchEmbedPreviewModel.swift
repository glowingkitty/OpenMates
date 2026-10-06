// Watch embed preview contract.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.compact-layout, apple-watch.embeds.read-only-fullscreen
// Maps regular OpenMates embed records into a small, watchOS-safe card model
// without importing the large iOS/macOS renderer stack. The model keeps private
// content out of continuation links and exposes only compact display fields for
// Watch UI and deterministic unit tests.

import Foundation
import CryptoKit
import CoreFoundation

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
    case event
    case document
    case spreadsheet
    case mindmap
    case audio
    case application
    case unsupported
}

enum WatchEmbedPreviewState: String, Sendable {
    case ready
    case processing
    case error
    case unavailable
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

struct WatchEmbedOpenRequest: Equatable, Sendable {
    let chatId: String
    let embedId: String

    init?(chatId: String?, embedId: String) {
        guard let chatId, !chatId.isEmpty, !embedId.isEmpty else { return nil }
        self.chatId = chatId
        self.embedId = embedId
    }
}

enum WatchEmbedOpenConnectivityPayload {
    static let kindKey = "kind"
    static let chatIdKey = "chat_id"
    static let embedIdKey = "embed_id"
    static let watchEmbedOpenRequestKind = "openmates.watch.embed_open.request"

    static func requestMessage(_ request: WatchEmbedOpenRequest) -> [String: Any] {
        [
            kindKey: watchEmbedOpenRequestKind,
            chatIdKey: request.chatId,
            embedIdKey: request.embedId,
        ]
    }

    static func parseRequest(_ message: [String: Any]) -> WatchEmbedOpenRequest? {
        guard message[kindKey] as? String == watchEmbedOpenRequestKind,
              let chatId = message[chatIdKey] as? String,
              let embedId = message[embedIdKey] as? String else { return nil }
        return WatchEmbedOpenRequest(chatId: chatId, embedId: embedId)
    }
}

enum WatchEmbedPreviewVisual: Equatable, Sendable {
    case symbol
    case text([String])
    case code([String])
    case table(headers: [String], rows: [[String]], cellCount: Int?)
}

struct WatchEmbedPreviewModel: Equatable, Identifiable, Sendable {
    static let cardWidth: Double = 156
    static let cardHeight: Double = 196

    let id: String
    let family: WatchEmbedPreviewFamily
    let state: WatchEmbedPreviewState
    let appId: String
    let typeLabel: String
    let title: String
    let subtitle: String?
    let detail: String?
    let continuation: WatchEmbedContinuation
    let visual: WatchEmbedPreviewVisual
    var detailContent: WatchEmbedDetailContent = .empty
    var previewSymbolAssetName: String? = nil

    var hasPreviewVisual: Bool {
        if state == .processing || detailContent.imageData != nil || detailContent.imageURL != nil { return true }
        switch visual {
        // The reported code placeholder must not repeat its app-bar icon.
        // Preserve other families' existing symbol preview composition.
        case .symbol: return family != .code && previewSymbolIconName != nil
        case .text(let lines), .code(let lines): return !lines.isEmpty
        case .table(let headers, _, _): return !headers.isEmpty
        }
    }

    /// Transcription/processing does not own the local recording's playback.
    /// Other processing embed families keep their existing opening guard.
    var hasPlayableAudio: Bool {
        (family == .audioRecording || family == .audio)
            && (detailContent.audioData != nil || detailContent.audioSource != nil)
    }
    var canOpenReadOnlyPreview: Bool { state != .processing || hasPlayableAudio }

    var isSupported: Bool { family != .unsupported }
    // The Watch app bar represents the app; a search-result symbol represents
    // its skill. Preserve Mail's explicit mail glyph from the web preview.
    var previewSymbolIconName: String? {
        if state == .error { return "warning" }
        if let previewSymbolAssetName { return previewSymbolAssetName.isEmpty ? nil : previewSymbolAssetName }
        return iconName
    }

    var iconName: String {
        switch appId {
        case "mindmaps": return "workflow"
        case "tasks": return "task"
        case "workflows": return "workflow"
        case "electronics": return "pcbdesign"
        case "hosting": return "server"
        case "models3d": return "3dmodels"
        case "file": return "files"
        case "photos": return "image"
        default: return appId
        }
    }
}

/// Read-only projection reuses the same hydrated record as the preview. No
/// detail plaintext or fetched binary is persisted by this view model.
struct WatchEmbedDetailContent: Equatable, Sendable {
    var text: String?
    var isCode = false
    var imageURL: URL?
    var imageData: Data?
    var audioData: Data?
    var audioSource: WatchAudioSource?
    var tableHeaders: [String] = []
    var tableRows: [[String]] = []
    var latitude: Double?
    var longitude: Double?
    var children: [WatchEmbedPreviewModel] = []
    static let empty = Self()

    static func make(for embed: EmbedRecord, family: WatchEmbedPreviewFamily,
                     allRecords: [String: EmbedRecord], chatId: String? = nil) -> Self {
        let raw = embed.rawData ?? [:]
        func string(_ keys: [String]) -> String? {
            keys.lazy.compactMap { raw[$0]?.value as? String }
                .first { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        }
        var result = Self()
        let keys: [String]
        switch family {
        case .code: keys = ["code", "content", "text"]; result.isCode = true
        case .spreadsheet: keys = ["table", "markdown", "code", "content"]
        case .document, .mindmap: keys = ["markdown", "content", "text", "description"]
        case .audio, .audioRecording: keys = ["transcript", "transcription", "text"]
        case .mapPlace: keys = ["formattedAddress", "formatted_address", "address", "description"]
        default: keys = ["description", "summary", "text", "content"]
        }
        result.text = string(keys)
        if family == .audio || family == .audioRecording {
            result.audioSource = WatchAudioSource(raw: raw)
            if raw["use_corrected"]?.value as? Bool == true {
                result.text = string(["transcript_corrected"]) ?? result.text
            } else {
                result.text = string(["transcript_original"]) ?? result.text
            }
        }
        if family == .spreadsheet, let text = result.text {
            let lines = text.components(separatedBy: .newlines).filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty && $0.contains("|") }
            func cells(_ line: String) -> [String] {
                var value = line.trimmingCharacters(in: .whitespaces)
                if value.hasPrefix("|") { value.removeFirst() }
                if value.hasSuffix("|") { value.removeLast() }
                return value.split(separator: "|", omittingEmptySubsequences: false).map { $0.trimmingCharacters(in: .whitespaces) }
            }
            if lines.count > 1, lines[1].contains("---") {
                result.tableHeaders = cells(lines[0]); result.tableRows = lines.dropFirst(2).map(cells)
            }
        }
        if let encoded = string(["thumbnail_base64", "thumbnail_data"]), encoded.utf8.count <= 700_000,
           let data = Data(base64Encoded: encoded), data.count <= 512_000 { result.imageData = data }
        // Same public thumbnail fields accepted by the iPhone image/map views.
        if let value = string(["thumbnail_url", "thumbnail_original", "map_image_url", "mapImageUrl",
                               "imageUrl", "image_url", "photo_url", "preview_url"] + (family == .image ? ["url", "src"] : [])),
           let url = URL(string: value), ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
           url.host?.isEmpty == false, url.user == nil, url.password == nil {
            result.imageURL = url
        }
        if family == .mapPlace {
            let nested = (raw["location"]?.value as? [String: Any])?.mapValues(AnyCodable.init) ?? [:]
            func number(_ data: [String: AnyCodable], _ keys: [String], _ bounds: ClosedRange<Double>) -> Double? {
                for key in keys {
                    guard let raw = data[key]?.value else { continue }
                    if let value = raw as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() { continue }
                    let value = (raw as? NSNumber)?.doubleValue ?? (raw as? String).flatMap(Double.init)
                    if let value, value.isFinite, bounds.contains(value) { return value }
                }
                return nil
            }
            result.latitude = number(nested, ["latitude", "lat"], -90...90)
                ?? number(raw, ["location_latitude", "location_lat", "latitude", "lat"], -90...90)
            result.longitude = number(nested, ["longitude", "lon", "lng"], -180...180)
                ?? number(raw, ["location_longitude", "location_lon", "location_lng", "longitude", "lon", "lng"], -180...180)
        }
        // A group opens its ordered child records; unresolved children remain
        // explicit unavailable cards. Children do not recursively expand here.
        result.children = embed.childEmbedIds.filter { $0 != embed.id }.map { id in
            let record = allRecords[id] ?? EmbedRecord(id: id, type: "web-website", status: .finished,
                data: nil, parentEmbedId: embed.id, appId: "web", skillId: nil, embedIds: nil, createdAt: nil)
            return WatchEmbedPreviewMapper.makeModel(for: record, chatId: chatId)
        }
        return result
    }
}

/// Preserve large-preview positions; inline citations remain readable links.
/// Consecutive preview markers use the iPhone carousel ordering and group keys.
struct WatchMessageRenderSegment: Equatable, Identifiable, Sendable {
    enum Content: Equatable, Sendable { case markdown(String), embeds([WatchEmbedPreviewModel]) }
    let id: Int
    let content: Content
}

enum WatchMessageRenderProjection {
    static func segments(message: WatchChatMessage, hydratedChildren: [EmbedRecord] = [], localAudio: [String: Data] = [:]) -> [WatchMessageRenderSegment] {
        let refs = WatchMessageContentSanitizer.mergedEmbedRefs(content: message.content, provided: message.embedRefs)
        let records = refs.map(WatchEmbedPreviewMapper.embedRecord(from:))
        let lookup = EmbedRecord.dictionaryById(records + hydratedChildren, context: "watchMessageProjection") { _ in }
        var aliases: [String: String] = [:]
        for record in records {
            aliases[record.id] = record.id
            if let ref = record.rawData?["embed_ref"]?.value as? String { aliases[ref] = record.id }
        }
        var output: [WatchMessageRenderSegment.Content] = []
        var seen = Set<String>()
        var group: [WatchEmbedPreviewModel] = []
        var groupKey: String?
        func flushGroup() { if !group.isEmpty { output.append(.embeds(group)); group = []; groupKey = nil } }
        func appendText(_ text: String) {
            guard let display = WatchMessageContentSanitizer.displayText(content: text, embedRefs: refs),
                  !display.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            flushGroup(); output.append(.markdown(display))
        }
        func appendEmbed(_ refID: String) {
            let id = aliases[refID] ?? refID
            guard seen.insert(id).inserted else { return }
            let record = lookup[id] ?? WatchEmbedPreviewMapper.embedRecord(from:
                WatchEmbedRef(id: id, type: "web-website", status: "finished", data: nil))
            let key = record.isAppSkillUse ? "app-skill-use" : record.type
            if groupKey != nil && groupKey != key { flushGroup() }
            groupKey = key
            var model = WatchEmbedPreviewMapper.makeModel(for: record, chatId: message.chatId, allEmbedRecords: lookup)
            model.detailContent.audioData = localAudio[id]
            group.append(model)
        }
        let source = message.content ?? ""
        // Match embed JSON only; ordinary fenced code stays intact and its
        // apparent embed markers must not become interactive previews.
        let pattern = #"```(?:json_embed|json)\s*[\s\S]*?```|```[\s\S]*?```|~~~[\s\S]*?~~~|\[\[embed(?:ref)?:([^\]]+)\]\]|\[!\]\(embed:([^\)]+)\)"#
        let regex = try? NSRegularExpression(pattern: pattern)
        var cursor = source.startIndex
        for match in regex?.matches(in: source, range: NSRange(source.startIndex..., in: source)) ?? [] {
            guard let range = Range(match.range, in: source) else { continue }
            let token = String(source[range])
            let parsed = WatchMessageContentSanitizer.inlineEmbedRefs(content: token)
            if let ref = parsed.first {
                appendText(String(source[cursor..<range.lowerBound])); appendEmbed(ref.id)
                cursor = range.upperBound
            }
        }
        appendText(String(source[cursor...])); flushGroup()
        let inlineIDs = WatchMessageContentSanitizer.inlineEmbedReferenceIds(content: message.content)
        let childIDs = Set(records.flatMap(\.childEmbedIds))
        for record in records where !seen.contains(record.id) && !childIDs.contains(record.id) {
            let alias = record.rawData?["embed_ref"]?.value as? String
            guard !inlineIDs.contains(record.id), alias.map(inlineIDs.contains) != true else { continue }
            appendEmbed(record.id)
        }
        flushGroup()
        return output.enumerated().map { WatchMessageRenderSegment(id: $0.offset, content: $0.element) }
    }
}

enum WatchEmbedPreviewMapper {
    static func makeModel(
        for embedRef: WatchEmbedRef,
        chatId: String?,
        allEmbedRecords: [String: EmbedRecord] = [:]
    ) -> WatchEmbedPreviewModel {
        makeModel(
            for: embedRecord(from: embedRef),
            chatId: chatId,
            allEmbedRecords: allEmbedRecords
        )
    }

    static func embedRecord(from embedRef: WatchEmbedRef) -> EmbedRecord {
        var raw = embedRef.data ?? [:]
        if let encoded = raw["content"]?.value as? String {
            let decoded = EmbedRecord.parseContent(encoded).mapValues(AnyCodable.init)
            // A serialized embed envelope differs from a JSON code/document body.
            // Preserve ordinary JSON source as readable content on Watch.
            let envelopeKeys = ["app_id", "embed_id", "code", "table", "markdown", "filename", "embed_ids"]
            if envelopeKeys.contains(where: { decoded[$0] != nil })
                || (encoded.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("{")
                    && EmbedType.normalized(rawValue: embedRef.type) != .codeCode) {
                raw.removeValue(forKey: "content")
            }
            raw = decoded.merging(raw, uniquingKeysWith: { _, supplied in supplied })
        }
        let embedType = EmbedType.normalized(rawValue: embedRef.type)
        let appId = string(raw, keys: ["app_id", "appId"]) ?? embedType?.appId
        let skillId = string(raw, keys: ["skill_id", "skillId"])
        // Live and stored WebSocket envelopes carry an array; encoded embed
        // content can carry the same IDs as a pipe-separated string.
        let embedIds: String?
        if let ids = (raw["embed_ids"] ?? raw["embedIds"])?.value as? [String] {
            embedIds = ids.joined(separator: "|")
        } else {
            embedIds = string(raw, keys: ["embed_ids", "embedIds"])
        }
        return EmbedRecord(
            id: embedRef.id,
            type: embedType?.rawValue ?? embedRef.type,
            status: embedRef.status.flatMap(EmbedStatus.init(rawValue:)) ?? .finished,
            data: raw.isEmpty ? nil : .raw(raw),
            parentEmbedId: string(raw, keys: ["parent_embed_id", "parentEmbedId"]),
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            createdAt: nil
        )
    }

    static func makeModel(
        for embed: EmbedRecord,
        chatId: String?,
        allEmbedRecords: [String: EmbedRecord] = [:]
    ) -> WatchEmbedPreviewModel {
        let inferredSkill: EmbedType?
        if embed.isAppSkillUse,
           let appId = embed.appId ?? string(embed.rawData ?? [:], keys: ["app_id", "appId"]),
           let skillId = embed.skillId ?? string(embed.rawData ?? [:], keys: ["skill_id", "skillId"]) {
            inferredSkill = EmbedType(rawValue: "app:\(appId):\(skillId)")
        } else { inferredSkill = nil }
        let embedType = inferredSkill ?? EmbedType.normalized(rawValue: embed.type)
        let family = family(for: embed, embedType: embedType)
        let raw = embed.rawData ?? [:]
        let appId = embed.appId ?? string(raw, keys: ["app_id", "appId"]) ?? embedType?.appId ?? appId(for: family)
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
            continuation: WatchEmbedContinuation(chatId: chatId, embedId: embed.id),
            visual: visual(for: family, raw: raw, allEmbedRecords: allEmbedRecords, embed: embed),
            detailContent: family == .unsupported || state == .error ? .empty : WatchEmbedDetailContent.make(for: embed, family: family, allRecords: allEmbedRecords, chatId: chatId),
            previewSymbolAssetName: GeneratedWebEmbedPreviewIconPolicy.name(for: embed)
        )
    }

    /// Refresh an already opened projection when its authorized hydration arrives.
    /// No fetch or durable plaintext storage is introduced by this display helper.
    static func refreshedModel(_ model: WatchEmbedPreviewModel,
                               hydratedRefs: [String: WatchEmbedRef]) -> WatchEmbedPreviewModel {
        guard let ref = hydratedRefs[model.id], ref.id == model.id else { return model }
        let records = hydratedRefs.mapValues { embedRecord(from: $0) }
        var updated = makeModel(for: ref, chatId: model.continuation.chatId, allEmbedRecords: records)
        updated.detailContent.audioData = model.detailContent.audioData
        return updated
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
        let identification = Set(["type", "embed_id", "embedId", "embed_ref", "app_id", "appId", "skill_id", "skillId", "embed_ids", "embedIds", "parent_embed_id"])
        let meaningful = (embed.rawData ?? [:]).contains { key, field in
            guard !identification.contains(key), !(field.value is NSNull) else { return false }
            if let text = field.value as? String { return !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            return true
        }
        if !meaningful { return .unavailable }
        return .ready
    }

    private static func family(for embed: EmbedRecord, embedType: EmbedType?) -> WatchEmbedPreviewFamily {
        if embed.isAppSkillUse,
           let appId = embed.appId ?? string(embed.rawData ?? [:], keys: ["app_id"]),
           let skillId = embed.skillId ?? string(embed.rawData ?? [:], keys: ["skill_id"]),
           let inferred = EmbedType(rawValue: "app:\(appId):\(skillId)") {
            return family(for: inferred) ?? .unsupported
        }
        if embed.isAppSkillUse, let appID = embed.appId {
            switch appID {
            case "sheets": return .spreadsheet
            case "docs": return .document
            case "mindmaps": return .mindmap
            default:
                if EmbedType.allCases.contains(where: { $0.appId == appID }) { return .application }
            }
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
        case .codeCode, .codeGetDocs, .codeRepo, .codeNotebook, .codeApplication:
            return .code
        case .pdf:
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
        case .eventsEvent: return .event
        case .docsDoc: return .document
        case .sheetsSheet: return .spreadsheet
        case .mindmapsMindmap: return .mindmap
        case .audioGenerate, .audioSpeak: return .audio
        default:
            if embedType.childType != nil { return .searchResults }
            if embedType.appId != nil { return .application }
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
            if let number = raw["duration"]?.value as? NSNumber,
               CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite,
               (0...86_400).contains(number.doubleValue) {
                let seconds = Int(number.doubleValue)
                subtitle = String(format: "%d:%02d", seconds / 60, seconds % 60)
            } else { subtitle = string(raw, keys: ["duration", "duration_text", "mime_type"]) }
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
        case .event:
            title = string(raw, keys: ["name", "title"]) ?? fallback
            subtitle = string(raw, keys: ["date_start", "start_time", "date", "venue_name", "location"])
            detail = string(raw, keys: ["price", "provider"])
        case .document, .spreadsheet, .mindmap, .audio, .application:
            title = string(raw, keys: ["title", "name", "filename", "query", "prompt"]) ?? fallback
            subtitle = string(raw, keys: ["description", "summary", "skill_id", "format"]).flatMap(cleanText)
            detail = string(raw, keys: ["duration", "row_count", "node_count", "page_count"])
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

    /// Compact content only. Private asset URLs/keys are never promoted into
    /// an unauthenticated image fetch or a rich native engine on the Watch.
    private static func visual(for family: WatchEmbedPreviewFamily, raw: [String: AnyCodable],
                               allEmbedRecords: [String: EmbedRecord], embed: EmbedRecord) -> WatchEmbedPreviewVisual {
        if family == .spreadsheet,
           let markdown = string(raw, keys: ["table", "code", "content", "markdown"]) {
            let limited = String(markdown.prefix(65_536))
            let lines = limited.components(separatedBy: .newlines)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty && $0.contains("|") }
            func cells(_ line: String) -> [String] {
                var line = line.trimmingCharacters(in: .whitespacesAndNewlines)
                if line.hasPrefix("|") { line.removeFirst() }
                if line.hasSuffix("|") { line.removeLast() }
                return line.split(separator: "|", omittingEmptySubsequences: false).prefix(2).map {
                    cleanText(String($0).trimmingCharacters(in: .whitespacesAndNewlines)) ?? ""
                }
            }
            if lines.count >= 2, lines[1].contains("---") {
                let headers = cells(lines[0])
                let rows = lines.dropFirst(2).prefix(3).map(cells)
                let declaredRows = string(raw, keys: ["row_count", "rowCount", "rows"]).flatMap(Int.init)
                let declaredColumns = string(raw, keys: ["col_count", "colCount", "cols"]).flatMap(Int.init)
                let declaredCells = string(raw, keys: ["cell_count", "cellCount"]).flatMap(Int.init)
                let count: Int?
                if let declaredCells, declaredCells >= 0 { count = declaredCells }
                else if let declaredRows, let declaredColumns, declaredRows >= 0, declaredColumns > 0,
                        !declaredRows.multipliedReportingOverflow(by: declaredColumns).overflow {
                    count = declaredRows * declaredColumns
                } else if markdown.count <= 65_536 {
                    var header = lines[0]
                    if header.hasPrefix("|") { header.removeFirst() }
                    if header.hasSuffix("|") { header.removeLast() }
                    count = max(0, lines.count - 2) * header.split(separator: "|", omittingEmptySubsequences: false).count
                } else { count = nil }
                return .table(headers: headers, rows: rows, cellCount: count)
            }
        }
        if family == .code, let code = string(raw, keys: ["code", "content"]) {
            return .code(String(code.prefix(2048)).components(separatedBy: .newlines).prefix(4).map { String($0.prefix(96)) })
        }
        if family == .searchResults {
            let embedded = (raw["preview_results"] ?? raw["results"])?.value as? [[String: Any]] ?? []
            let titles = embedded.prefix(3).compactMap { item in
                string(item.mapValues(AnyCodable.init), keys: ["title", "name", "description"])
            }
            let children = embed.childEmbedIds.prefix(3).compactMap { allEmbedRecords[$0] }
                .compactMap { string($0.rawData ?? [:], keys: ["title", "name", "description"]) }
            if !(titles + children).isEmpty { return .text(Array((titles + children).prefix(3))) }
        }
        if let text = string(raw, keys: ["description", "summary", "transcript", "transcription", "content", "text"]) {
            return .text(String(text.prefix(512)).components(separatedBy: .newlines).prefix(3).map { String($0.prefix(160)) })
        }
        return .symbol
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
        case .event: return "events"
        case .document: return "docs"
        case .spreadsheet: return "sheets"
        case .mindmap: return "mindmaps"
        case .audio: return "audio"
        case .application: return "ai"
        case .unsupported: return "web"
        }
    }
}

enum WatchMessageContentSanitizer {
    static func inlineEmbedReferenceIds(content: String?) -> Set<String> {
        guard let content else { return [] }
        let pattern = #"\[([^\]\n]*)\]\(embed:([^\)\n]+)\)"#
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return [] }
        let matches = expression.matches(
            in: content,
            range: NSRange(content.startIndex..<content.endIndex, in: content)
        )
        return Set(matches.compactMap { match in
            guard let labelRange = Range(match.range(at: 1), in: content),
                  content[labelRange] != "!",
                  let refRange = Range(match.range(at: 2), in: content) else { return nil }
            return String(content[refRange])
        })
    }

    static func inlineEmbedRefs(content: String?) -> [WatchEmbedRef] {
        guard let content else { return [] }
        let pattern = #"```(?:json_embed|json)\s*([\s\S]*?)\s*```"#
        let nsRange = NSRange(content.startIndex..<content.endIndex, in: content)
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        var refsById: [String: (location: Int, ref: WatchEmbedRef)] = [:]
        var seenIds = Set<String>()
        func appendRef(_ ref: WatchEmbedRef, location: Int) {
            guard seenIds.insert(ref.id).inserted else { return }
            refsById[ref.id] = (location, ref)
        }
        func appendFallbackRef(id: String, location: Int) {
            appendRef(WatchEmbedRef(id: id, type: EmbedType.webWebsite.rawValue, status: "finished", data: nil), location: location)
        }

        for match in regex.matches(in: content, range: nsRange) {
            guard let jsonRange = Range(match.range(at: 1), in: content),
                  let data = String(content[jsonRange]).data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            guard let embedId = (object["embed_id"] as? String) ?? (object["embedId"] as? String),
                  !seenIds.contains(embedId) else { continue }
            let type = object["type"] as? String ?? "web-website"
            let status = object["status"] as? String ?? "finished"
            appendRef(WatchEmbedRef(
                id: embedId,
                type: type,
                status: status,
                data: previewSafeInlineData(from: object)
            ), location: match.range.location)
        }

        let codeRanges = (try? NSRegularExpression(pattern: #"```[\s\S]*?```|~~~[\s\S]*?~~~"#))?
            .matches(in: content, range: nsRange).map(\.range) ?? []
        for markerPattern in [#"\[\[embed(?:ref)?:([^\]]+)\]\]"#, #"\[!\]\(embed:([^\)]+)\)"#] {
            guard let markerRegex = try? NSRegularExpression(pattern: markerPattern) else { continue }
            for match in markerRegex.matches(in: content, range: nsRange) {
                guard !codeRanges.contains(where: { NSIntersectionRange($0, match.range).length > 0 }) else { continue }
                guard let idRange = Range(match.range(at: 1), in: content) else { continue }
                appendFallbackRef(id: String(content[idRange]), location: match.range.location)
            }
        }

        return refsById.values.sorted { lhs, rhs in lhs.location < rhs.location }.map { $0.ref }
    }

    static func mergedEmbedRefs(content: String?, provided: [WatchEmbedRef]?) -> [WatchEmbedRef] {
        var result = provided ?? []
        var indices: [String: Int] = [:]
        for (index, ref) in result.enumerated() { if indices[ref.id] == nil { indices[ref.id] = index } }
        for parsed in inlineEmbedRefs(content: content) {
            if let index = indices[parsed.id] {
                let existing = result[index]
                var fields = parsed.data ?? [:]
                fields.merge(existing.data ?? [:], uniquingKeysWith: { _, supplied in supplied })
                result[index] = WatchEmbedRef(id: existing.id, type: existing.type,
                    status: existing.status ?? parsed.status, data: fields.isEmpty ? nil : fields)
            } else { indices[parsed.id] = result.count; result.append(parsed) }
        }
        return result
    }

    private static func previewSafeInlineData(from object: [String: Any]) -> [String: AnyCodable] {
        let allowedKeys = Set([
            "app_id", "appId", "skill_id", "skillId", "embed_ids", "embedIds", "embed_ref", "embed_id", "embedId", "type", "status", "title", "name",
            "filename", "duration", "duration_seconds",
            "page_count", "line_count", "language", "query", "result_count", "provider",
        ])
        return object.reduce(into: [:]) { result, item in
            guard allowedKeys.contains(item.key) else { return }
            result[item.key] = AnyCodable(item.value)
        }
    }

    static func displayText(content: String?, embedRefs: [WatchEmbedRef]?) -> String? {
        guard let content else { return nil }
        let embedIds = Set((embedRefs ?? []).map(\.id))
        var output: [String] = []
        var fencedBlock: [String] = []
        var isInFence = false

        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.hasPrefix("```") {
                fencedBlock.append(line)
                if isInFence {
                    if !isEmbedOnlyBlock(fencedBlock.joined(separator: "\n"), embedIds: embedIds) {
                        output.append(contentsOf: fencedBlock)
                    }
                    fencedBlock = []
                }
                isInFence.toggle()
                continue
            }

            if isInFence {
                fencedBlock.append(line)
                continue
            }

            guard !isEmbedOnlyLine(line, embedIds: embedIds) else { continue }
            output.append(replacingInlineEmbedLinks(in: line))
        }

        if !fencedBlock.isEmpty, !isEmbedOnlyBlock(fencedBlock.joined(separator: "\n"), embedIds: embedIds) {
            output.append(contentsOf: fencedBlock)
        }

        let trimmed = output.joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func isEmbedOnlyBlock(_ block: String, embedIds: Set<String>) -> Bool {
        let lowercased = block.lowercased()
        if lowercased.contains("embed_id") || lowercased.contains("embed-id") { return true }
        return embedIds.contains { block.contains("embed:\($0)") || block.contains($0) }
    }

    private static func isEmbedOnlyLine(_ line: String, embedIds: Set<String>) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        if trimmed.contains("\"embed_id\"") || trimmed.contains("embed_id:") { return true }
        if trimmed.hasPrefix("[[embed:") || trimmed.hasPrefix("[[embedref:") || trimmed.hasPrefix("[!](embed:") { return true }
        return embedIds.contains { trimmed == "embed:\($0)" || trimmed == $0 }
    }

    private static func replacingInlineEmbedLinks(in line: String) -> String {
        let pattern = #"\[([^\]\n]*)\]\(embed:([^\)\n]+)\)"#
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return line }
        let matches = expression.matches(
            in: line,
            range: NSRange(line.startIndex..<line.endIndex, in: line)
        )
        var output = line
        for match in matches.reversed() {
            guard let fullRange = Range(match.range(at: 0), in: output),
                  let labelRange = Range(match.range(at: 1), in: line),
                  let refRange = Range(match.range(at: 2), in: line) else { continue }
            let label = String(line[labelRange]).trimmingCharacters(in: .whitespacesAndNewlines)
            let ref = String(line[refRange]).trimmingCharacters(in: .whitespacesAndNewlines)
            output.replaceSubrange(fullRange, with: displayText(label: label, ref: ref))
        }
        return output
    }

    private static func displayText(label: String, ref: String) -> String {
        let refBase = stripEmbedRefSuffix(ref)
        let suffix = ref.replacingOccurrences(of: refBase, with: "")
            .replacingOccurrences(of: "-", with: "", options: .anchored)
        let isTechnicalLabel = label.isEmpty
            || label == ref
            || label == refBase
            || (!suffix.isEmpty && label == suffix)
        if !isTechnicalLabel, label.count > 3 { return label }
        if let domainRange = ref.range(
            of: #"^[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?"#,
            options: .regularExpression
        ) {
            return String(ref[domainRange])
        }

        let base = refBase.replacingOccurrences(of: #"\s*\(\d+\)$"#, with: "", options: .regularExpression)
        if let expression = try? NSRegularExpression(pattern: #"^([a-zA-Z][a-zA-Z0-9_-]*)-(\d{4})$"#),
           let match = expression.firstMatch(in: base, range: NSRange(base.startIndex..., in: base)),
           let carrierRange = Range(match.range(at: 1), in: base),
           let timeRange = Range(match.range(at: 2), in: base) {
            let carrier = formatCarrierLabel(String(base[carrierRange]))
            let rawTime = String(base[timeRange])
            let splitIndex = rawTime.index(rawTime.startIndex, offsetBy: 2)
            return "\(carrier) \(rawTime[..<splitIndex]):\(rawTime[splitIndex...])"
        }

        let words = base.split(whereSeparator: { $0 == "-" || $0 == "_" })
        guard !words.isEmpty else { return ref }
        return words.prefix(4).map { formatCarrierLabel(String($0)) }.joined(separator: " ")
    }

    private static func stripEmbedRefSuffix(_ ref: String) -> String {
        ref.replacingOccurrences(
            of: #"-[a-zA-Z0-9]{2,4}(?:\s*\(\d+\))?$"#,
            with: "",
            options: .regularExpression
        )
    }

    private static func formatCarrierLabel(_ raw: String) -> String {
        switch raw.lowercased() {
        case "db": return "DB"
        case "ice": return "ICE"
        case "ic": return "IC"
        case "ec": return "EC"
        case "flixtrain", "flixzug": return "FlixTrain"
        default:
            return raw.count <= 4 ? raw.uppercased() : raw.capitalized
        }
    }
}

extension WatchChatMessage {
    var watchEmbedRecords: [EmbedRecord] {
        let inlineReferenceIds = WatchMessageContentSanitizer.inlineEmbedReferenceIds(content: content)
        return WatchMessageContentSanitizer.mergedEmbedRefs(content: content, provided: embedRefs)
            .filter { ref in
                guard !inlineReferenceIds.contains(ref.id) else { return false }
                guard let embedRef = ref.data?["embed_ref"]?.value as? String else { return true }
                return !inlineReferenceIds.contains(embedRef)
            }
            .map(WatchEmbedPreviewMapper.embedRecord(from:))
    }

    var watchDisplayContent: String? {
        WatchMessageContentSanitizer.displayText(content: content, embedRefs: embedRefs)
    }
}

// Compact semantic blocks preserve Markdown structure on the small Watch screen.
struct WatchMarkdownBlock: Equatable, Identifiable, Sendable {
    enum Kind: Equatable, Sendable { case paragraph, heading(Int), list(String), quote, code(String?), divider }
    let id: Int
    let kind: Kind
    let text: String
}

enum WatchMarkdownParser {
    static func blocks(_ markdown: String) -> [WatchMarkdownBlock] {
        var result: [WatchMarkdownBlock] = []
        var paragraph: [String] = []
        var code: [String]? = nil
        var language: String?
        var fenceMarker: String?
        func append(_ kind: WatchMarkdownBlock.Kind, _ text: String) {
            result.append(WatchMarkdownBlock(id: result.count, kind: kind, text: text))
        }
        func flush() {
            if !paragraph.isEmpty { append(.paragraph, paragraph.joined(separator: "\n")); paragraph = [] }
        }
        for line in markdown.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if let marker = fenceMarker {
                if trimmed.hasPrefix(marker) {
                    append(.code(language), (code ?? []).joined(separator: "\n"))
                    code = nil; fenceMarker = nil; language = nil
                } else { code?.append(line) }
                continue
            }
            if trimmed.hasPrefix("```") || trimmed.hasPrefix("~~~") {
                flush(); fenceMarker = String(trimmed.prefix(3)); code = []
                let label = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                language = label.isEmpty ? nil : label
            } else if trimmed.isEmpty { flush() }
            else if trimmed == "---" || trimmed == "***" || trimmed == "___" { flush(); append(.divider, "") }
            else if trimmed.hasPrefix("> ") { flush(); append(.quote, String(trimmed.dropFirst(2))) }
            else if let match = trimmed.range(of: #"^#{1,6} "#, options: .regularExpression) {
                flush(); let count = trimmed.distance(from: trimmed.startIndex, to: match.upperBound) - 1
                append(.heading(count), String(trimmed[match.upperBound...]))
            } else if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") || trimmed.hasPrefix("+ ") {
                flush(); append(.list("•"), String(trimmed.dropFirst(2)))
            } else if let match = trimmed.range(of: #"^[0-9]+[.)] "#, options: .regularExpression) {
                flush(); append(.list(String(trimmed[..<match.upperBound]).trimmingCharacters(in: .whitespaces)), String(trimmed[match.upperBound...]))
            } else { paragraph.append(line) }
        }
        flush()
        if let code { append(.code(language), code.joined(separator: "\n")) }
        return result
    }
}

// Opens only the exact referenced embed using a wrapper bound to this chat/account.
// Hydrated preview fields remain in memory; they are not added to the disk snapshot.
enum WatchEmbedHydration {
    static func open(payload: [String: Any], embedID: String, chatID: String,
                     accountID: String, masterKey: SymmetricKey, chatKey: SymmetricKey?) throws -> WatchEmbedRef {
        guard payload["embed_id"] as? String == embedID,
              payload["user_id"] as? String == accountID,
              let content = payload["content"] as? String else { throw WatchChatRuntimeError.missingChatKey }
        let rawType = payload["type"] as? String ?? "app_skill_use"
        let plaintext: String
        let type: String
        if payload["already_encrypted"] as? Bool == true || payload["encryption_mode"] as? String == "client" {
            let wrappers = payload["embed_keys"] as? [[String: Any]] ?? []
            let hashedEmbedID = hash(embedID)
            let hashedChatID = hash(chatID)
            let hashedAccountID = hash(accountID)
            var openedKey: SymmetricKey?
            for row in wrappers {
                guard row["hashed_embed_id"] as? String == hashedEmbedID,
                      let encryptedKey = row["encrypted_embed_key"] as? String else { continue }
                let wrappingKey: SymmetricKey?
                switch row["key_type"] as? String {
                case "master":
                    guard row["hashed_user_id"] as? String == hashedAccountID else { continue }
                    wrappingKey = masterKey
                case "chat":
                    guard row["hashed_chat_id"] as? String == hashedChatID else { continue }
                    wrappingKey = chatKey
                default: continue
                }
                guard let wrappingKey,
                      let key = try? ComposerEmbedCrypto.unwrapKey(encryptedKey, using: wrappingKey),
                      key.withUnsafeBytes({ $0.count }) == 32 else { continue }
                openedKey = key; break
            }
            guard let key = openedKey else { throw WatchChatRuntimeError.missingChatKey }
            plaintext = try ComposerEmbedCrypto.decryptContent(content, using: key)
            if let decryptedType = try? ComposerEmbedCrypto.decryptContent(rawType, using: key) { type = decryptedType }
            else if rawType == "app_skill_use" || rawType == "app-skill-use" || EmbedType.normalized(rawValue: rawType) != nil { type = rawType }
            else { throw WatchChatRuntimeError.missingChatKey }
        } else {
            // The existing live skill transport delivers transient plaintext only.
            guard let ownerChatID = payload["chat_id"] as? String,
                  ownerChatID == chatID || ownerChatID == hash(chatID) else { throw WatchChatRuntimeError.missingChatKey }
            plaintext = content; type = rawType
        }
        var fields = EmbedRecord.parseContent(plaintext)
        guard !fields.isEmpty else { throw WatchChatRuntimeError.historyUnavailable }
        fields["type"] = type
        fields["embed_id"] = embedID
        if let embedIDs = payload["embed_ids"], !(embedIDs is NSNull) { fields["embed_ids"] = embedIDs }
        if let parentID = payload["parent_embed_id"], !(parentID is NSNull) { fields["parent_embed_id"] = parentID }
        return WatchEmbedRef(id: embedID, type: type, status: payload["status"] as? String ?? "finished",
                             data: fields.mapValues(AnyCodable.init))
    }

    static func prepareStorage(payload: [String: Any], embedID: String, chatID: String, messageID: String,
                               accountID: String, masterKey: SymmetricKey, chatKey: SymmetricKey,
                               now: Int = Int(Date().timeIntervalSince1970)) throws -> (keys: [String: Any], embed: [String: Any]) {
        guard payload["already_encrypted"] as? Bool != true, payload["encryption_mode"] as? String != "client" else {
            throw WatchChatRuntimeError.invalidPendingTurn
        }
        let ref = try open(payload: payload, embedID: embedID, chatID: chatID, accountID: accountID,
                           masterKey: masterKey, chatKey: chatKey)
        guard let plaintext = payload["content"] as? String else { throw WatchChatRuntimeError.historyUnavailable }
        let embedKey = ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: embedID)
        let wrappers: [[String: Any]] = [
            ["hashed_embed_id": hash(embedID), "key_type": "master", "hashed_chat_id": NSNull(),
             "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: masterKey),
             "hashed_user_id": hash(accountID), "created_at": now],
            ["hashed_embed_id": hash(embedID), "key_type": "chat", "hashed_chat_id": hash(chatID),
             "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: chatKey),
             "hashed_user_id": hash(accountID), "created_at": now]
        ]
        var embed: [String: Any] = ["request_id": UUID().uuidString.lowercased(), "embed_id": embedID,
            "encrypted_type": try ComposerEmbedCrypto.encryptContent(ref.type, using: embedKey),
            "encrypted_content": try ComposerEmbedCrypto.encryptContent(plaintext, using: embedKey),
            "status": ref.status ?? "finished", "hashed_chat_id": hash(chatID), "hashed_message_id": hash(messageID),
            "hashed_user_id": hash(accountID), "created_at": now, "updated_at": now,
            "is_private": payload["is_private"] as? Bool ?? false, "is_shared": payload["is_shared"] as? Bool ?? false,
            "embed_ids": WatchEmbedPreviewMapper.embedRecord(from: ref).childEmbedIds]
        if let preview = payload["text_preview"] as? String {
            embed["encrypted_text_preview"] = try ComposerEmbedCrypto.encryptContent(preview, using: embedKey)
        }
        for field in ["parent_embed_id", "hashed_task_id", "version_number", "file_path", "content_hash", "text_length_chars"] {
            if let value = payload[field], !(value is NSNull) { embed[field] = value }
        }
        return (["request_id": UUID().uuidString.lowercased(), "keys": wrappers], embed)
    }

    private static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// Persists only a bounded preference, never message text or account content.
enum WatchTranscriptZoom {
    static let minimum = -2
    static let maximum = 5
    static func adjust(_ level: Int, increase: Bool) -> Int {
        min(maximum, max(minimum, level + (increase ? 1 : -1)))
    }
    static func scale(for level: Int) -> Double { pow(1.15, Double(min(maximum, max(minimum, level)))) }
}


/// Recording file metadata is decrypted with the embed; it never enters a
/// continuation link or the offline preview allowlist. Only original media is
/// accepted, and unknown encryption versions fail closed.
struct WatchAudioSource: Equatable, Sendable {
    static let maximumBytes = 16 * 1024 * 1024
    let s3Key: String
    let aesKey: String
    let aesNonce: String?
    let encryption: String?

    init?(raw: [String: AnyCodable]) {
        // Watch currently supports personal chats only. A Team-owned media
        // descriptor must not escape into a personal presign request.
        if let team = raw["team_id"]?.value, !(team is NSNull) { return nil }
        guard let files = raw["files"]?.value as? [String: Any],
              let original = files["original"] as? [String: Any],
              let key = original["s3_key"] as? String, !key.isEmpty, key.utf8.count <= 2_048,
              let aesKey = raw["aes_key"]?.value as? String,
              Self.material(aesKey, count: 32) != nil else { return nil }
        let nonce = (original["aes_nonce"] as? String) ?? (raw["aes_nonce"]?.value as? String)
        let encryption = (original["encryption"] as? String) ?? (raw["encryption"]?.value as? String)
        guard encryption == nil || encryption == "" || encryption == "aes-gcm-nonce-prefixed-v1" else { return nil }
        // Web accepts an explicit empty legacy nonce as nonce-prefixed;
        // genuinely missing nonce metadata is not a playable legacy recording.
        guard encryption == "aes-gcm-nonce-prefixed-v1" || nonce != nil else { return nil }
        if encryption == nil, let nonce, !nonce.isEmpty,
           Self.material(nonce, count: 12) == nil { return nil }
        if let size = original["size_bytes"] as? NSNumber,
           size.int64Value <= 0 || size.int64Value > Int64(Self.maximumBytes) { return nil }
        self.s3Key = key; self.aesKey = aesKey; self.aesNonce = nonce; self.encryption = encryption
    }

    private static func material(_ encoded: String, count: Int) -> Data? {
        if encoded.utf8.count == count * 2 {
            var data = Data(); var index = encoded.startIndex
            while index < encoded.endIndex {
                let end = encoded.index(index, offsetBy: 2)
                guard let byte = UInt8(encoded[index..<end], radix: 16) else { return nil }
                data.append(byte); index = end
            }
            return data
        }
        guard let data = Data(base64Encoded: encoded), data.count == count else { return nil }
        return data
    }

    func decrypt(_ data: Data) throws -> Data {
        guard data.count <= Self.maximumBytes, let key = Self.material(aesKey, count: 32) else {
            throw WatchChatRuntimeError.invalidRecording
        }
        let nonce: Data
        let body: Data
        if encryption == "aes-gcm-nonce-prefixed-v1" || aesNonce?.isEmpty != false {
            guard data.count > 28 else { throw WatchChatRuntimeError.invalidRecording }
            nonce = Data(data.prefix(12)); body = Data(data.dropFirst(12))
        } else {
            guard let bytes = Self.material(aesNonce!, count: 12), data.count > 16 else {
                throw WatchChatRuntimeError.invalidRecording
            }
            nonce = bytes; body = data
        }
        let sealed = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: nonce),
            ciphertext: body.dropLast(16), tag: body.suffix(16))
        return try AES.GCM.open(sealed, using: SymmetricKey(data: key))
    }
}

// BEGIN GENERATED WEB EMBED PREVIEW ICON POLICY
// Generated by scripts/audit_apple_embed_icons.py --write-watch-policy.
// Source: canonical enabled registry + actual Svelte preview props/CSS.
// Empty asset means the web preview intentionally omits its secondary icon.
enum GeneratedWebEmbedPreviewIconPolicy {
    static let assets: [String: String] = [
        "app:audio:generate": "audio",
        "app:audio:speak": "audio",
        "app:business:company_financials": "business",
        "app:calendar:create-event": "search",
        "app:calendar:delete-event": "search",
        "app:calendar:get-events": "search",
        "app:calendar:list-calendars": "search",
        "app:calendar:update-event": "search",
        "app:code:get_docs": "docs",
        "app:code:search_repos": "search",
        "app:design:search_icons": "search",
        "app:electronics:search_components": "search",
        "app:events:search": "search",
        "app:finance:check_accounts": "finance",
        "app:fitness:search_classes": "search",
        "app:fitness:search_locations": "search",
        "app:health:search_appointments": "search",
        "app:home:search": "search",
        "app:hosting:search_domains": "search",
        "app:images:generate": "ai",
        "app:images:generate_draft": "ai",
        "app:images:search": "search",
        "app:mail:search": "mail",
        "app:maps:search": "search",
        "app:math:calculate": "math",
        "app:models3d:generate": "3dmodels",
        "app:models3d:search": "search",
        "app:music:generate": "ai",
        "app:news:search": "search",
        "app:nutrition:search_recipes": "search",
        "app:reminder:cancel-reminder": "reminder",
        "app:reminder:list-reminders": "reminder",
        "app:reminder:set-reminder": "reminder",
        "app:shopping:search_products": "search",
        "app:social_media:get-posts": "search",
        "app:social_media:search": "search",
        "app:tasks:create": "task",
        "app:tasks:search": "search",
        "app:travel:get_flight": "travel",
        "app:travel:price_calendar": "calendar",
        "app:travel:search_connections": "search",
        "app:travel:search_stays": "search",
        "app:videos:create": "videos",
        "app:videos:generate": "videos",
        "app:videos:get_transcript": "transcript",
        "app:videos:search": "search",
        "app:weather:forecast": "",
        "app:weather:rain_radar": "",
        "app:web:read": "text",
        "app:web:search": "search",
        "app:workflows:create-or-modify": "workflow",
        "app:workflows:search": "search",
        "business-company-financial-result": "business",
        "code-application": "coding",
        "code-code": "coding",
        "code-notebook": "coding",
        "code-repo": "github",
        "design-icon-result": "search",
        "docs-doc": "docs",
        "electronics-component": "search",
        "electronics-pcb-schematic": "pcbdesign",
        "events-event": "event",
        "file-file": "files",
        "fitness-class": "fitness",
        "fitness-location": "fitness",
        "focus-mode-activation": "insight",
        "health-appointment": "heart",
        "home-listing": "search",
        "hosting-domain": "search",
        "image": "image",
        "images-image-result": "image",
        "mail-email": "mail",
        "maps": "pin",
        "maps-place": "pin",
        "math-plot": "math",
        "mindmaps-mindmap": "workflow",
        "models3d-model-result": "3dmodels",
        "nutrition-recipe": "search",
        "pdf": "pdf",
        "recording": "recordaudio",
        "sheets-sheet": "sheets",
        "shopping-product": "search",
        "social-media-post": "socialmedia",
        "tasks-task": "task",
        "travel-connection": "search",
        "travel-stay": "search",
        "videos-video": "videos",
        "weather-day": "weather",
        "web-website": "web",
        "workflows-workflow": "workflow",
    ]

    static func name(for embed: EmbedRecord) -> String? {
        let appID = embed.appId ?? embed.rawData?["app_id"]?.value as? String ?? embed.rawData?["appId"]?.value as? String
        let skillID = embed.skillId ?? embed.rawData?["skill_id"]?.value as? String ?? embed.rawData?["skillId"]?.value as? String
        let key: String
        if embed.isAppSkillUse, let appID, let skillID {
            key = "app:\(appID):\(skillID)"
        } else {
            key = EmbedType.normalized(rawValue: embed.type)?.rawValue ?? embed.type
        }
        return assets[key]
    }
}
// END GENERATED WEB EMBED PREVIEW ICON POLICY
