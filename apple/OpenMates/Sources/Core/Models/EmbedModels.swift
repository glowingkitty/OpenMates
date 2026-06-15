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

struct EmbedVersionMetadata: Identifiable, Codable, Equatable, Sendable {
    let versionNumber: Int
    let createdAt: Int
    let hasSnapshot: Bool
    let hasPatch: Bool
    let contentHash: String?

    var id: Int { versionNumber }

    private enum CodingKeys: String, CodingKey {
        case versionNumber = "version_number"
        case createdAt = "created_at"
        case hasSnapshot = "has_snapshot"
        case hasPatch = "has_patch"
        case contentHash = "content_hash"
    }
}

struct EmbedVersionRestoreRequest: Codable, Equatable, Sendable {
    let embedId: String
    let versionNumber: Int

    private enum CodingKeys: String, CodingKey {
        case embedId = "embed_id"
        case versionNumber = "version_number"
    }
}

struct EmbedRecord: Identifiable, Decodable, @unchecked Sendable {
    let id: String
    let type: String
    let status: EmbedStatus
    let data: EmbedData?
    let encryptedContent: String?
    let encryptedType: String?
    let encryptedTextPreview: String?
    let parentEmbedId: String?
    let appId: String?
    let skillId: String?
    let embedIds: String?
    let hashedChatId: String?
    let hashedUserId: String?
    let versionNumber: Int?
    let contentHash: String?
    let versionHistory: [EmbedVersionMetadata]
    let versionHistoryReadonly: Bool
    let createdAt: String?

    var childEmbedIds: [String] {
        Self.normalizeEmbedIds(embedIds)
    }

    var rawData: [String: AnyCodable]? {
        guard let data, case .raw(let dict) = data else { return nil }
        return dict
    }

    var isAppSkillUse: Bool {
        let rawType = rawData?["type"]?.value as? String
        return rawType == "app_skill_use" || rawType == "app-skill-use" || type == "app-skill-use"
    }

    static func dictionaryById(
        _ embeds: [EmbedRecord],
        context: String,
        duplicateReporter: (([String: Int]) -> Void)? = nil
    ) -> [String: EmbedRecord] {
        var records: [String: EmbedRecord] = [:]
        var duplicateIds: [String: Int] = [:]
        for embed in embeds {
            if records[embed.id] != nil {
                duplicateIds[embed.id, default: 1] += 1
            }
            records[embed.id] = embed
        }
        if let duplicateReporter {
            duplicateReporter(duplicateIds)
        } else {
            logDuplicateIds(duplicateIds, context: context)
        }
        return records
    }

    static func deduplicatedById(
        _ embeds: [EmbedRecord],
        context: String,
        duplicateReporter: (([String: Int]) -> Void)? = nil
    ) -> [EmbedRecord] {
        var orderedIds: [String] = []
        var records: [String: EmbedRecord] = [:]
        var duplicateIds: [String: Int] = [:]
        for embed in embeds {
            if records[embed.id] == nil {
                orderedIds.append(embed.id)
            } else {
                duplicateIds[embed.id, default: 1] += 1
            }
            records[embed.id] = embed
        }
        if let duplicateReporter {
            duplicateReporter(duplicateIds)
        } else {
            logDuplicateIds(duplicateIds, context: context)
        }
        return orderedIds.compactMap { records[$0] }
    }

    static func relatedRecords(
        referencedIds: Set<String>,
        from embeds: [EmbedRecord],
        context: String
    ) -> [EmbedRecord] {
        guard !referencedIds.isEmpty, !embeds.isEmpty else { return [] }
        _ = dictionaryById(embeds, context: context)
        var includedIds = referencedIds
        var changed = true
        while changed {
            changed = false
            for embed in embeds {
                let referencesIncludedParent = embed.parentEmbedId.map { includedIds.contains($0) } ?? false
                let referencesIncludedChild = !Set(embed.childEmbedIds).isDisjoint(with: includedIds)
                if (referencesIncludedParent || referencesIncludedChild), includedIds.insert(embed.id).inserted {
                    changed = true
                }
            }
        }
        return embeds.filter { embed in
            includedIds.contains(embed.id) ||
            (embed.parentEmbedId.map { includedIds.contains($0) } ?? false) ||
            !Set(embed.childEmbedIds).isDisjoint(with: includedIds)
        }
    }

    init(
        id: String,
        type: String,
        status: EmbedStatus,
        data: EmbedData?,
        encryptedContent: String? = nil,
        encryptedType: String? = nil,
        encryptedTextPreview: String? = nil,
        parentEmbedId: String?,
        appId: String?,
        skillId: String?,
        embedIds: String?,
        hashedChatId: String? = nil,
        hashedUserId: String? = nil,
        versionNumber: Int? = nil,
        contentHash: String? = nil,
        versionHistory: [EmbedVersionMetadata] = [],
        versionHistoryReadonly: Bool = false,
        createdAt: String?
    ) {
        self.id = id
        self.type = type
        self.status = status
        self.data = data
        self.encryptedContent = encryptedContent
        self.encryptedType = encryptedType
        self.encryptedTextPreview = encryptedTextPreview
        self.parentEmbedId = parentEmbedId
        self.appId = appId
        self.skillId = skillId
        self.embedIds = embedIds
        self.hashedChatId = hashedChatId
        self.hashedUserId = hashedUserId
        self.versionNumber = versionNumber
        self.contentHash = contentHash
        self.versionHistory = versionHistory
        self.versionHistoryReadonly = versionHistoryReadonly
        self.createdAt = createdAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let legacyContainer = try decoder.container(keyedBy: LegacyCodingKeys.self)
        let decodedId = try container.decodeIfPresent(String.self, forKey: .id)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .embedId))
            ?? (try container.decode(String.self, forKey: .embedId))
        let decodedParentEmbedId = try container.decodeIfPresent(String.self, forKey: .parentEmbedId)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .parentEmbedId))
        let decodedAppId = try container.decodeIfPresent(String.self, forKey: .appId)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .appId))
        let decodedSkillId = try container.decodeIfPresent(String.self, forKey: .skillId)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .skillId))
        let decodedStatus = (try? container.decodeIfPresent(EmbedStatus.self, forKey: .status)) ?? .finished
        let decodedType = try container.decodeIfPresent(String.self, forKey: .type)
            ?? (try container.decodeIfPresent(String.self, forKey: .embedType))
        encryptedContent = try container.decodeIfPresent(String.self, forKey: .encryptedContent)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .encryptedContent))
        encryptedType = try container.decodeIfPresent(String.self, forKey: .encryptedType)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .encryptedType))
        encryptedTextPreview = try container.decodeIfPresent(String.self, forKey: .encryptedTextPreview)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .encryptedTextPreview))
        hashedChatId = try container.decodeIfPresent(String.self, forKey: .hashedChatId)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .hashedChatId))
        hashedUserId = try container.decodeIfPresent(String.self, forKey: .hashedUserId)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .hashedUserId))
        versionNumber = try container.decodeIfPresent(Int.self, forKey: .versionNumber)
            ?? (try legacyContainer.decodeIfPresent(Int.self, forKey: .versionNumber))
        contentHash = try container.decodeIfPresent(String.self, forKey: .contentHash)
            ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .contentHash))
        let decodedVersionHistory = try container.decodeIfPresent([EmbedVersionMetadata].self, forKey: .versionHistory)
        versionHistory = try decodedVersionHistory
            ?? legacyContainer.decodeIfPresent([EmbedVersionMetadata].self, forKey: .versionHistory)
            ?? []
        let decodedVersionHistoryReadonly = try container.decodeIfPresent(Bool.self, forKey: .versionHistoryReadonly)
        versionHistoryReadonly = try decodedVersionHistoryReadonly
            ?? legacyContainer.decodeIfPresent(Bool.self, forKey: .versionHistoryReadonly)
            ?? false
        var decodedEmbedIds: String?
        if let ids = try container.decodeIfPresent([String].self, forKey: .embedIds) {
            decodedEmbedIds = ids.joined(separator: "|")
        } else if let ids = try legacyContainer.decodeIfPresent([String].self, forKey: .embedIds) {
            decodedEmbedIds = ids.joined(separator: "|")
        } else {
            decodedEmbedIds = try container.decodeIfPresent(String.self, forKey: .embedIds)
                ?? (try legacyContainer.decodeIfPresent(String.self, forKey: .embedIds))
        }
        createdAt = Self.decodeStringOrNumber(container, forKey: .createdAt)
            ?? Self.decodeStringOrNumber(legacyContainer, forKey: .createdAt)
        id = decodedId
        status = decodedStatus
        parentEmbedId = decodedParentEmbedId
        appId = decodedAppId
        skillId = decodedSkillId

        if let decodedData = try container.decodeIfPresent(EmbedData.self, forKey: .data) {
            data = decodedData
            type = decodedType ?? decodedData.rawType ?? Self.inferredType(appId: decodedAppId, skillId: decodedSkillId)
            if decodedEmbedIds == nil, case .raw(let raw) = decodedData {
                decodedEmbedIds = Self.embedIdsString(from: raw["embed_ids"]?.value)
                    ?? Self.embedIdsString(from: raw["embedIds"]?.value)
            }
        } else if let content = try container.decodeIfPresent(String.self, forKey: .content) {
            var raw = Self.parseToonContent(content)
            let contentType = raw["type"] as? String
            type = decodedType ?? contentType ?? Self.inferredType(appId: decodedAppId, skillId: decodedSkillId)
            decodedEmbedIds = decodedEmbedIds
                ?? Self.embedIdsString(from: raw["embed_ids"])
                ?? Self.embedIdsString(from: raw["embedIds"])
            raw["embed_id"] = raw["embed_id"] ?? id
            raw["type"] = raw["type"] ?? type
            raw["app_id"] = raw["app_id"] ?? appId
            raw["skill_id"] = raw["skill_id"] ?? skillId
            raw["parent_embed_id"] = raw["parent_embed_id"] ?? parentEmbedId
            raw["embed_ids"] = raw["embed_ids"] ?? Self.normalizeEmbedIds(decodedEmbedIds)
            data = .raw(raw.mapValues { AnyCodable($0) })
        } else {
            type = decodedType ?? Self.inferredType(appId: decodedAppId, skillId: decodedSkillId)
            data = nil
        }
        embedIds = decodedEmbedIds
    }

    func decryptedCopy(content: String?, type decryptedType: String?) -> EmbedRecord {
        var raw: [String: Any]?
        if let content {
            raw = Self.parseContent(content)
        }

        let resolvedType = Self.normalizedType(
            decryptedType
            ?? raw?["type"] as? String
            ?? type,
            appId: appId ?? raw?["app_id"] as? String,
            skillId: skillId ?? raw?["skill_id"] as? String
        )
        let resolvedEmbedIds = embedIds
            ?? Self.embedIdsString(from: raw?["embed_ids"])
            ?? Self.embedIdsString(from: raw?["embedIds"])
        var resolvedRaw = raw ?? [:]
        if !resolvedRaw.isEmpty {
            resolvedRaw["embed_id"] = resolvedRaw["embed_id"] ?? id
            resolvedRaw["type"] = resolvedRaw["type"] ?? resolvedType
            resolvedRaw["app_id"] = resolvedRaw["app_id"] ?? appId
            resolvedRaw["skill_id"] = resolvedRaw["skill_id"] ?? skillId
            resolvedRaw["parent_embed_id"] = resolvedRaw["parent_embed_id"] ?? parentEmbedId
            resolvedRaw["embed_ids"] = resolvedRaw["embed_ids"] ?? Self.normalizeEmbedIds(resolvedEmbedIds)
        }

        return EmbedRecord(
            id: id,
            type: resolvedType,
            status: status,
            data: resolvedRaw.isEmpty ? data : .raw(resolvedRaw.mapValues { AnyCodable($0) }),
            encryptedContent: encryptedContent,
            encryptedType: encryptedType,
            encryptedTextPreview: encryptedTextPreview,
            parentEmbedId: parentEmbedId,
            appId: appId ?? resolvedRaw["app_id"] as? String,
            skillId: skillId ?? resolvedRaw["skill_id"] as? String,
            embedIds: resolvedEmbedIds,
            hashedChatId: hashedChatId,
            hashedUserId: hashedUserId,
            versionNumber: versionNumber,
            contentHash: contentHash,
            versionHistory: versionHistory,
            versionHistoryReadonly: versionHistoryReadonly,
            createdAt: createdAt
        )
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case embedId = "embed_id"
        case type
        case embedType = "embed_type"
        case status
        case data
        case content
        case encryptedContent = "encrypted_content"
        case encryptedType = "encrypted_type"
        case encryptedTextPreview = "encrypted_text_preview"
        case parentEmbedId = "parent_embed_id"
        case appId = "app_id"
        case skillId = "skill_id"
        case embedIds = "embed_ids"
        case hashedChatId = "hashed_chat_id"
        case hashedUserId = "hashed_user_id"
        case versionNumber = "version_number"
        case contentHash = "content_hash"
        case versionHistory = "version_history"
        case versionHistoryReadonly = "version_history_readonly"
        case createdAt = "created_at"
    }

    private enum LegacyCodingKeys: String, CodingKey {
        case embedId
        case encryptedContent
        case encryptedType
        case encryptedTextPreview
        case parentEmbedId
        case appId
        case skillId
        case embedIds
        case hashedChatId
        case hashedUserId
        case versionNumber
        case contentHash
        case versionHistory
        case versionHistoryReadonly
        case createdAt
    }

    private static func parseContent(_ content: String) -> [String: Any] {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if let data = trimmed.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: data),
           let object = json as? [String: Any] {
            return object
        }
        return parseToonContent(content)
    }

    private static func normalizedType(_ rawType: String, appId: String?, skillId: String?) -> String {
        switch rawType {
        case "image_result":
            return EmbedType.imagesImageResult.rawValue
        case "website", "web_result", "search_result":
            return EmbedType.webWebsite.rawValue
        default:
            break
        }

        if appId == "images", skillId == "image_result" {
            return EmbedType.imagesImageResult.rawValue
        }
        if (appId == "web" || appId == "news"), skillId == "website" || skillId == "web_result" {
            return EmbedType.webWebsite.rawValue
        }
        return rawType
    }

    private static func decodeStringOrNumber<Key: CodingKey>(
        _ container: KeyedDecodingContainer<Key>,
        forKey key: Key
    ) -> String? {
        if let string = try? container.decodeIfPresent(String.self, forKey: key) {
            return string
        }
        if let int = try? container.decodeIfPresent(Int.self, forKey: key) {
            return String(int)
        }
        if let double = try? container.decodeIfPresent(Double.self, forKey: key) {
            return String(double)
        }
        return nil
    }

    private static func parseToonContent(_ content: String) -> [String: Any] {
        var result: [String: Any] = [:]
        let lines = content.components(separatedBy: .newlines)
        var index = 0

        while index < lines.count {
            let rawLine = lines[index]
            let indentation = rawLine.prefix { $0 == " " || $0 == "\t" }.count
            let trimmed = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty, let separator = trimmed.firstIndex(of: ":") else {
                index += 1
                continue
            }
            let key = String(trimmed[..<separator]).trimmingCharacters(in: .whitespacesAndNewlines)
            let value = String(trimmed[trimmed.index(after: separator)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            if !key.isEmpty {
                if value.isEmpty, index + 1 < lines.count {
                    let nested = parseNestedObject(lines: lines, start: index + 1, parentIndentation: indentation)
                    if !nested.values.isEmpty {
                        result[key] = nested.values
                        index = nested.nextIndex
                        continue
                    }
                }
                result[key] = parseScalarOrArray(value)
            }
            index += 1
        }
        return result
    }

    private static func logDuplicateIds(_ duplicateIds: [String: Int], context: String) {
        guard !duplicateIds.isEmpty else { return }
        let sample = duplicateIds.keys.sorted().prefix(6).joined(separator: ",")
        let duplicateEntries = duplicateIds.values.reduce(0) { $0 + $1 - 1 }
        NativeSyncPerfLog.warning(
            "phase=embedDedup context=\(context) duplicateIds=\(duplicateIds.count) duplicateEntries=\(duplicateEntries) sample=\(sample)"
        )
    }

    private static func parseNestedObject(
        lines: [String],
        start: Int,
        parentIndentation: Int
    ) -> (values: [String: Any], nextIndex: Int) {
        var values: [String: Any] = [:]
        var index = start

        while index < lines.count {
            let rawLine = lines[index]
            let indentation = rawLine.prefix { $0 == " " || $0 == "\t" }.count
            let trimmed = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else {
                index += 1
                continue
            }
            guard indentation > parentIndentation else { break }
            if trimmed.hasPrefix("- ") {
                let value = String(trimmed.dropFirst(2)).trimmingCharacters(in: .whitespacesAndNewlines)
                let key = String(values.count)
                values[key] = parseScalarOrArray(value)
                index += 1
                continue
            }
            guard let separator = trimmed.firstIndex(of: ":") else { break }
            let key = String(trimmed[..<separator]).trimmingCharacters(in: .whitespacesAndNewlines)
            let value = String(trimmed[trimmed.index(after: separator)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            values[key] = parseScalarOrArray(value)
            index += 1
        }

        return (values, index)
    }

    private static func parseScalarOrArray(_ rawValue: String) -> Any {
        var value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.hasPrefix("\""), value.hasSuffix("\""), value.count >= 2 {
            value.removeFirst()
            value.removeLast()
            return value
        }
        if value.hasPrefix("["), value.hasSuffix("]") {
            let inner = value.dropFirst().dropLast()
            return inner
                .split(separator: ",")
                .map { cleanScalar(String($0)) }
                .filter { !$0.isEmpty }
        }
        if value.contains("|"), value.range(of: #"\s"#, options: .regularExpression) == nil {
            return value
                .split(separator: "|")
                .map { cleanScalar(String($0)) }
                .filter { !$0.isEmpty }
        }
        return cleanScalar(value)
    }

    private static func cleanScalar(_ value: String) -> String {
        var cleaned = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.hasPrefix("\""), cleaned.hasSuffix("\""), cleaned.count >= 2 {
            cleaned.removeFirst()
            cleaned.removeLast()
        }
        return cleaned
    }

    private static func embedIdsString(from value: Any?) -> String? {
        let normalized = normalizeEmbedIds(value)
        return normalized.isEmpty ? nil : normalized.joined(separator: "|")
    }

    private static func normalizeEmbedIds(_ value: Any?) -> [String] {
        switch value {
        case let ids as [String]:
            return ids.map(cleanScalar).filter { !$0.isEmpty }
        case let ids as [Any]:
            return ids.compactMap { $0 as? String }.map(cleanScalar).filter { !$0.isEmpty }
        case let ids as String:
            return ids
                .split { $0 == "|" || $0 == "," }
                .map { cleanScalar(String($0)) }
                .filter { !$0.isEmpty }
        default:
            return []
        }
    }

    private static func inferredType(appId: String?, skillId: String?) -> String {
        guard let appId, !appId.isEmpty else { return "unknown" }
        guard let skillId, !skillId.isEmpty else { return appId }
        return "app:\(appId):\(skillId)"
    }
}

struct EmbedKeyRecord: Decodable, Sendable {
    let hashedEmbedId: String
    let keyType: String
    let hashedChatId: String?
    let encryptedEmbedKey: String

    private enum CodingKeys: String, CodingKey {
        case hashedEmbedId
        case keyType
        case hashedChatId
        case encryptedEmbedKey
    }
}

private extension EmbedData {
    var rawType: String? {
        guard case .raw(let dict) = self else { return nil }
        return dict["type"]?.value as? String
    }
}

// MARK: - Embed type enum (33 types)

enum EmbedType: String, CaseIterable {
    // Direct embeds
    case recording
    case codeRepo = "code-repo"
    case codeCode = "code-code"
    case codeApplication = "code-application"
    case docsDoc = "docs-doc"
    case electronicsComponent = "electronics-component"
    case image
    case mailEmail = "mail-email"
    case maps
    case mathPlot = "math-plot"
    case pdf
    case sheetsSheet = "sheets-sheet"
    case focusModeActivation = "focus-mode-activation"
    case socialMediaPost = "social-media-post"
    case weatherDay = "weather-day"

    // Composite search embeds
    case codeRepoSearch = "app:code:search_repos"
    case electronicsSearch = "app:electronics:search_components"
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
    case musicGenerate = "app:music:generate"
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
    case videosGenerate = "app:videos:generate"
    case videosCreate = "app:videos:create"
    case webSearch = "app:web:search"
    case webWebsite = "web-website"
    case webRead = "app:web:read"
    case wiki
    case weatherForecast = "app:weather:forecast"

    // App skill use embeds
    case codeGetDocs = "app:code:get_docs"
    case imagesGenerate = "app:images:generate"
    case imagesGenerateDraft = "app:images:generate_draft"
    case mathCalculate = "app:math:calculate"
    case reminderSet = "app:reminder:set-reminder"
    case reminderList = "app:reminder:list-reminders"
    case reminderCancel = "app:reminder:cancel-reminder"
    case socialMediaGetPosts = "app:social_media:get-posts"
    case socialMediaSearch = "app:social_media:search"

    var isComposite: Bool {
        switch self {
        case .codeRepoSearch, .electronicsSearch,
             .eventsSearch, .healthSearch, .homeSearch, .imagesSearch,
             .mailSearch, .mapsSearch, .newsSearch, .nutritionSearch,
             .shoppingSearch, .socialMediaGetPosts, .socialMediaSearch,
             .travelConnections, .travelStays, .videosSearch, .weatherForecast,
             .webSearch:
            return true
        default:
            return false
        }
    }

    var childType: EmbedType? {
        switch self {
        case .codeRepoSearch: return .codeRepo
        case .electronicsSearch: return .electronicsComponent
        case .eventsSearch: return .eventsEvent
        case .healthSearch: return .healthAppointment
        case .homeSearch: return .homeListing
        case .imagesSearch: return .imagesImageResult
        case .mapsSearch: return .mapsPlace
        case .newsSearch: return .webWebsite
        case .nutritionSearch: return .nutritionRecipe
        case .shoppingSearch: return .shoppingProduct
        case .socialMediaGetPosts, .socialMediaSearch: return .socialMediaPost
        case .travelConnections: return .travelConnection
        case .travelStays: return .travelStay
        case .videosSearch: return .videosVideo
        case .weatherForecast: return .weatherDay
        case .webSearch: return .webWebsite
        default: return nil
        }
    }

    var appId: String? {
        let raw = rawValue
        guard raw.hasPrefix("app:") else {
            switch self {
            case .codeRepo, .codeCode, .codeApplication: return "code"
            case .docsDoc: return "docs"
            case .electronicsComponent: return "electronics"
            case .recording: return "audio"
            case .image, .imagesImageResult: return "images"
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
            case .socialMediaPost: return "social_media"
            case .travelConnection, .travelStay: return "travel"
            case .weatherDay: return "weather"
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
        case .codeRepoSearch: return "Repository Search"
        case .codeRepo: return "Repository"
        case .codeCode: return "Code"
        case .codeApplication: return "Application"
        case .codeGetDocs: return "Docs"
        case .docsDoc: return "Document"
        case .electronicsSearch: return "Component Search"
        case .electronicsComponent: return "Component"
        case .image: return "Image"
        case .imagesSearch: return "Image Search"
        case .imagesGenerate, .imagesGenerateDraft: return "Generated Image"
        case .imagesImageResult: return "Image"
        case .maps, .mapsSearch: return "Map"
        case .mapsPlace: return "Place"
        case .mailEmail, .mailSearch: return "Email"
        case .mathPlot: return "Plot"
        case .mathCalculate: return "Calculate"
        case .musicGenerate: return "Music"
        case .pdf: return "PDF"
        case .sheetsSheet: return "Sheet"
        case .recording: return "Recording"
        case .videosSearch: return "Video Search"
        case .videosVideo: return "Video"
        case .videosTranscript: return "Transcript"
        case .videosGenerate: return "Generated Video"
        case .videosCreate: return "Created Video"
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
        case .socialMediaGetPosts: return "Posts"
        case .socialMediaSearch: return "Social Search"
        case .socialMediaPost: return "Post"
        case .travelConnections: return "Connections"
        case .travelConnection: return "Connection"
        case .travelStays: return "Stays"
        case .travelStay: return "Stay"
        case .travelPriceCalendar: return "Price Calendar"
        case .travelFlight: return "Flight"
        case .focusModeActivation: return "Focus Mode"
        case .reminderSet, .reminderList, .reminderCancel: return "Reminder"
        case .weatherForecast: return "Forecast"
        case .weatherDay: return "Weather"
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
