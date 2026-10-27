// Bundled public examples shared by the main app and standalone Watch.
// Foundation data and static parsing only; never reads account or chat storage.
// Web source: frontend/packages/ui/src/demo_chats/data/example_chats/
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.guest.compact-workspace, apple-watch.guest.account-isolation

import Foundation

enum BundledPublicExampleCatalog {
    struct MessageSpec: Sendable {
        let id: String
        let role: String
        let key: String
        static func user(_ id: String, _ key: String) -> Self { Self(id: id, role: "user", key: key) }
        static func assistant(_ id: String, _ key: String) -> Self { Self(id: id, role: "assistant", key: key) }
    }
    struct Example: Sendable {
        let titleKey: String
        let appId: String
        let messages: [MessageSpec]
        let followUps: ClosedRange<Int>
        init(_ titleKey: String, _ appId: String, _ messages: [MessageSpec], _ followUps: ClosedRange<Int>) {
            self.titleKey = titleKey; self.appId = appId; self.messages = messages; self.followUps = followUps
        }
        var key: String { String(titleKey.dropFirst("example_chats.".count).dropLast(".title".count)) }
        var fileName: String {
            switch key {
            case "eu_chat_control_law": return "eu-chat-control-law-criticisms.ts"
            case "flights_berlin_bangkok": return "flights-berlin-to-bangkok.ts"
            default: return key.replacingOccurrences(of: "_", with: "-") + ".ts"
            }
        }
    }
    struct Reference {
        let id: String
        let type: String
        let status: String?
        let data: [String: AnyCodable]?
    }
    static let examples: [String: Example] = [
            "example-gigantic-airplanes": Example(
                "example_chats.gigantic_airplanes.title",
                "general_knowledge",
                [
                    .user("example-gigantic-airplanes-user-1", "example_chats.gigantic_airplanes.user_message_1"),
                    .assistant("example-gigantic-airplanes-assistant-1", "example_chats.gigantic_airplanes.assistant_message_1"),
                    .user("example-gigantic-airplanes-user-2", "example_chats.gigantic_airplanes.user_message_2"),
                    .assistant("example-gigantic-airplanes-assistant-2", "example_chats.gigantic_airplanes.assistant_message_2")
                ],
                1...6
            ),
            "example-artemis-ii-mission": Example(
                "example_chats.artemis_ii_mission.title",
                "science",
                [
                    .user("example-artemis-ii-mission-user-1", "example_chats.artemis_ii_mission.user_message_1"),
                    .assistant("example-artemis-ii-mission-assistant-2", "example_chats.artemis_ii_mission.assistant_message_2")
                ],
                1...4
            ),
            "example-beautiful-single-page-html": Example(
                "example_chats.beautiful_single_page_html.title",
                "software_development",
                [
                    .user("example-beautiful-single-page-html-user-1", "example_chats.beautiful_single_page_html.user_message_1"),
                    .assistant("example-beautiful-single-page-html-assistant-2", "example_chats.beautiful_single_page_html.assistant_message_2")
                ],
                1...6
            ),
            "example-eu-chat-control-law": Example(
                "example_chats.eu_chat_control_law.title",
                "legal_law",
                [
                    .user("example-eu-chat-control-law-user-1", "example_chats.eu_chat_control_law.user_message_1"),
                    .assistant("example-eu-chat-control-law-assistant-1", "example_chats.eu_chat_control_law.assistant_message_1")
                ],
                1...6
            ),
            "example-flights-berlin-bangkok": Example(
                "example_chats.flights_berlin_bangkok.title",
                "general_knowledge",
                [
                    .user("example-flights-berlin-bangkok-user-1", "example_chats.flights_berlin_bangkok.user_message_1"),
                    .assistant("example-flights-berlin-bangkok-assistant-1", "example_chats.flights_berlin_bangkok.assistant_message_1")
                ],
                1...6
            ),
            "example-creativity-drawing-meetups-berlin": Example(
                "example_chats.creativity_drawing_meetups_berlin.title",
                "general_knowledge",
                [
                    .user("example-creativity-drawing-meetups-berlin-user-1", "example_chats.creativity_drawing_meetups_berlin.user_message_1"),
                    .assistant("example-creativity-drawing-meetups-berlin-assistant-1", "example_chats.creativity_drawing_meetups_berlin.assistant_message_1")
                ],
                1...6
            )
        ]

    static var orderedIDs: [String] { examples.keys.sorted() }
    static var allowedIDs: Set<String> { Set(examples.keys) }
    static func extractEmbeds(from content: String, fallbackAppId: String?) -> (content: String, refs: [Reference], records: [EmbedRecord]) {
        var cleaned = content
        var records: [EmbedRecord] = []
        var refsById: [String: (location: Int, ref: Reference)] = [:]

        func recordRef(_ ref: Reference, location: Int) {
            guard refsById[ref.id] == nil else { return }
            refsById[ref.id] = (location, ref)
        }

        let jsonPattern = #"```(json_embed|json)\s*([\s\S]*?)\s*```"#
        for match in regexMatches(jsonPattern, in: content).reversed() {
            guard let fenceRange = Range(match.range(at: 1), in: content),
                  let jsonRange = Range(match.range(at: 2), in: content),
                  let fullRange = Range(match.range(at: 0), in: cleaned) else { continue }

            let fence = String(content[fenceRange])
            let json = String(content[jsonRange])
            guard let data = json.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let type = object["type"] as? String else { continue }

            let record: EmbedRecord
            if fence == "json_embed", type == "website", let url = object["url"] as? String {
                record = embedRecord(
                    id: stableEmbedId(prefix: "web", value: url),
                    type: "web-website",
                    appId: "web",
                    skillId: nil,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: nil
                )
            } else if type == "app_skill_use", let embedId = object["embed_id"] as? String {
                let appId = object["app_id"] as? String ?? fallbackAppId ?? "web"
                let skillId = object["skill_id"] as? String ?? "search"
                let embedType = "app:\(appId):\(skillId)"
                record = embedRecord(
                    id: embedId,
                    type: embedType,
                    appId: appId,
                    skillId: skillId,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: embedIds(from: object["embed_ids"] ?? object["child_embed_ids"])
                )
            } else if type == "code", let embedId = object["embed_id"] as? String {
                record = embedRecord(
                    id: embedId,
                    type: "code-code",
                    appId: "code",
                    skillId: nil,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: nil
                )
            } else if type == "sheet", let embedId = object["embed_id"] as? String {
                record = embedRecord(
                    id: embedId,
                    type: "sheets-sheet",
                    appId: "sheets",
                    skillId: object["skill_id"] as? String ?? "sheet",
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: nil
                )
            } else if let embedId = object["embed_id"] as? String {
                record = embedRecord(
                    id: embedId,
                    type: normalizedEmbedType(from: type, appId: object["app_id"] as? String ?? fallbackAppId, skillId: object["skill_id"] as? String),
                    appId: object["app_id"] as? String ?? fallbackAppId,
                    skillId: object["skill_id"] as? String,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: embedIds(from: object["embed_ids"] ?? object["child_embed_ids"])
                )
            } else {
                continue
            }

            records.insert(record, at: 0)
            recordRef(embedRef(for: record), location: match.range.location)
            cleaned.replaceSubrange(fullRange, with: "\n[[embed:\(record.id)]]\n")
        }

        let markdownEmbedPattern = #"\[!\]\(embed:([^)]+)\)"#
        for match in regexMatches(markdownEmbedPattern, in: cleaned).reversed() {
            guard let refRange = Range(match.range(at: 1), in: cleaned),
                  let fullRange = Range(match.range(at: 0), in: cleaned) else { continue }

            let ref = String(cleaned[refRange])
            recordRef(Reference(id: ref, type: "web-website", status: "finished", data: nil), location: match.range.location)
            cleaned.replaceSubrange(fullRange, with: "\n[[embedref:\(ref)]]\n")
        }

        let inlineEmbedPattern = #"\[\[embed(?:ref)?:([^\]]+)\]\]"#
        for match in regexMatches(inlineEmbedPattern, in: cleaned).reversed() {
            guard let idRange = Range(match.range(at: 1), in: cleaned) else { continue }
            recordRef(Reference(id: String(cleaned[idRange]), type: "web-website", status: "finished", data: nil), location: match.range.location)
        }

        let orderedRefs = refsById.values.sorted { lhs, rhs in lhs.location < rhs.location }.map { $0.ref }
        return (sanitize(cleaned), orderedRefs, records)
    }

    private static func embedRef(for record: EmbedRecord) -> Reference {
        Reference(id: record.id, type: record.type, status: record.status.rawValue, data: nil)
    }

    private static func embedRecord(
        id: String,
        type: String,
        appId: String?,
        skillId: String?,
        data: [String: Any],
        parentEmbedId: String?,
        embedIds: String?
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: .finished,
            data: .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            createdAt: "2026-04-20T12:00:00Z"
        )
    }

    static func demoEmbedRecords(for chatId: String) -> [String: EmbedRecord] {
        guard let fileName = demoEmbedFileName(for: chatId),
              let sourceURL = demoEmbedURL(fileName: fileName),
              let source = try? String(contentsOf: sourceURL, encoding: .utf8) else {
            return [:]
        }

        var records: [String: EmbedRecord] = [:]
        let objectPattern = #"\{\s*embed_id:\s*"([^"]+)"([\s\S]*?)\n\s*\},"#
        for match in regexMatches(objectPattern, in: source) {
            guard let idRange = Range(match.range(at: 1), in: source),
                  let blockRange = Range(match.range(at: 2), in: source) else { continue }

            let embedId = String(source[idRange])
            let block = String(source[blockRange])
            guard let rawType = firstRegexCapture(#"type:\s*"([^"]+)""#, in: block),
                  let rawContent = firstRegexCapture(#"content:\s*`([\s\S]*?)`"#, in: block) else { continue }
            let content = unescapedDemoEmbedContent(rawContent)
            var data = parseToonObject(content)
            data["embed_id"] = embedId
            data["type"] = data["type"] ?? rawType

            let parentEmbedId = firstRegexCapture(#"parent_embed_id:\s*"([^"]+)""#, in: block)
            let embedIds = firstRegexCapture(#"embed_ids:\s*\[([^\]]*)\]"#, in: block)
                .map(parseEmbedIdArray)
                ?? firstRegexCapture(#"embed_ids:\s*"([^"]*)""#, in: block)
                ?? data["embed_ids"] as? String
            let appId = data["app_id"] as? String
            let skillId = data["skill_id"] as? String
            let normalizedType = normalizedEmbedType(from: rawType, appId: appId, skillId: skillId)

            let record = embedRecord(
                id: embedId,
                type: normalizedType,
                appId: appId ?? EmbedType(rawValue: normalizedType)?.appId,
                skillId: skillId,
                data: data,
                parentEmbedId: parentEmbedId,
                embedIds: embedIds
            )
            records[embedId] = record
            if let embedRef = data["embed_ref"] as? String, !embedRef.isEmpty {
                records[embedRef] = record
            }
        }
        return records
    }

    private static func unescapedDemoEmbedContent(_ content: String) -> String {
        content
            .replacingOccurrences(of: #"\n"#, with: "\n")
            .replacingOccurrences(of: #"\""#, with: "\"")
            .replacingOccurrences(of: #"\u20ac"#, with: "€")
    }

    private static func firstRegexCapture(_ pattern: String, in text: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: []),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let range = Range(match.range(at: 1), in: text) else {
            return nil
        }
        return String(text[range])
    }

    private static func parseEmbedIdArray(_ value: String) -> String {
        value
            .split(separator: ",")
            .map {
                $0.trimmingCharacters(in: CharacterSet(charactersIn: " \n\t\""))
            }
            .filter { !$0.isEmpty }
            .joined(separator: "|")
    }

    private static func demoEmbedFileName(for chatId: String) -> String? {
        examples[chatId]?.fileName
    }

    private static func demoEmbedURL(fileName: String) -> URL? {
        let resourceName = (fileName as NSString).deletingPathExtension
        let resourceExtension = (fileName as NSString).pathExtension
        let bundleCandidates = [
            Bundle.main.url(forResource: resourceName, withExtension: resourceExtension, subdirectory: "example_chats"),
            Bundle.main.url(forResource: resourceName, withExtension: resourceExtension, subdirectory: "demo_chats/example_chats"),
            Bundle.main.url(forResource: resourceName, withExtension: resourceExtension),
            Bundle.main.url(forResource: fileName, withExtension: nil, subdirectory: "example_chats"),
            Bundle.main.url(forResource: fileName, withExtension: nil, subdirectory: "demo_chats/example_chats"),
            Bundle.main.url(forResource: fileName, withExtension: nil)
        ]
        if let bundled = bundleCandidates.compactMap({ $0 }).first {
            return bundled
        }

        let sourceFile = URL(fileURLWithPath: #filePath)
        let repoRoot = sourceFile
            .deletingLastPathComponent() // PublicChats/
            .deletingLastPathComponent() // Core/
            .deletingLastPathComponent() // Sources/
            .deletingLastPathComponent() // OpenMates/
            .deletingLastPathComponent() // apple/
        return repoRoot.appendingPathComponent("frontend/packages/ui/src/demo_chats/data/example_chats/\(fileName)")
    }

    private static func parseToonObject(_ content: String) -> [String: Any] {
        var result: [String: Any] = [:]
        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let separator = trimmed.firstIndex(of: ":") else { continue }
            let key = String(trimmed[..<separator]).trimmingCharacters(in: .whitespacesAndNewlines)
            var value = String(trimmed[trimmed.index(after: separator)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            if value.hasPrefix("\""), value.hasSuffix("\""), value.count >= 2 {
                value.removeFirst()
                value.removeLast()
            }
            value = value
                .replacingOccurrences(of: #"\""#, with: #"""#)
                .replacingOccurrences(of: #"\\n"#, with: "\n")
            if !key.isEmpty {
                result[key] = value
            }
        }
        return result
    }

    private static func embedIds(from value: Any?) -> String? {
        if let ids = value as? [String] {
            return ids.joined(separator: "|")
        }
        if let ids = value as? [Any] {
            let strings = ids.compactMap { $0 as? String }
            return strings.isEmpty ? nil : strings.joined(separator: "|")
        }
        return value as? String
    }

    private static func normalizedEmbedType(from type: String, appId: String?, skillId: String?) -> String {
        if type == "code" {
            return "code-code"
        }
        if type == "website" || type == "web_result" || type == "search_result" {
            return "web-website"
        }
        if type == "image_result" {
            return "images-image-result"
        }
        if type == "connection" {
            return "travel-connection"
        }
        if type == "event_result" || type == "event" {
            return "events-event"
        }
        if type == "video_result" {
            return "videos-video"
        }
        if let appId, let skillId, type == "app_skill_use" {
            return "app:\(appId):\(skillId)"
        }
        return type
    }

    private static func stableEmbedId(prefix: String, value: String) -> String {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash &*= 1_099_511_628_211
        }
        return "\(prefix)-\(String(hash, radix: 16))"
    }

    private static func regexMatches(_ pattern: String, in text: String) -> [NSTextCheckingResult] {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: []) else { return [] }
        return regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
    }

    static func sanitize(_ content: String) -> String {
        let placeholders = [
            "[[example_chats_group]]",
            "[[dev_example_chats_group]]",
            "[[app_store_group]]",
            "[[dev_app_store_group]]",
            "[[skills_group]]",
            "[[dev_skills_group]]",
            "[[focus_modes_group]]",
            "[[dev_focus_modes_group]]",
            "[[settings_memories_group]]",
            "[[dev_settings_memories_group]]",
            "[[ai_models_group]]"
        ]
        var cleaned = content
        let embedPlaceholderPattern = #"\[\[embed(?:ref)?:[^\]]+\]\]"#
        let embedPlaceholderMatches = regexMatches(embedPlaceholderPattern, in: cleaned)
            .compactMap { match -> String? in
                guard let range = Range(match.range(at: 0), in: cleaned) else { return nil }
                return String(cleaned[range])
            }
        for (index, placeholder) in embedPlaceholderMatches.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: placeholder, with: "__OM_EMBED_PLACEHOLDER_\(index)__")
        }
        for (index, placeholder) in placeholders.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: placeholder, with: "__OM_DEMO_PLACEHOLDER_\(index)__")
        }
        cleaned = cleaned
            .replacingOccurrences(of: #"\[\[[^\]]+\]\]"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: "\n\n\n", with: "\n\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        for (index, placeholder) in placeholders.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: "__OM_DEMO_PLACEHOLDER_\(index)__", with: placeholder)
        }
        for (index, placeholder) in embedPlaceholderMatches.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: "__OM_EMBED_PLACEHOLDER_\(index)__", with: placeholder)
        }
        return cleaned
    }
}
