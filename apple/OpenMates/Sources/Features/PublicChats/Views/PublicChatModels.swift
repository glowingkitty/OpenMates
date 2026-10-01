// Public chat data models — intro, example, legal, announcement, and tips chats.
// These are hardcoded or fetched from the backend and shown to all users.
// Mirrors the web app's DemoChat/DemoChatMessage types.

// Web source: frontend/packages/ui/src/demo_chats/types.ts,
// frontend/packages/ui/src/demo_chats/exampleChatStore.ts
// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity

import Foundation
import Yams

struct DemoChat: Identifiable, Decodable {
    let chatId: String
    let slug: String
    let title: String
    let description: String?
    let messages: [DemoMessage]
    let metadata: DemoChatMetadata?
    var publicSpeech: [String: [PublicAssistantSpeechSegment]]? = nil

    var id: String { chatId }
}

struct DemoMessage: Identifiable, Decodable {
    let messageId: String
    let role: String
    let content: String
    let embedRefs: [EmbedRef]?

    var id: String { messageId }
}

struct DemoChatMetadata: Decodable {
    let category: String?
    let featured: Bool?
    let order: Int?
    let iconNames: [String]?
    let videoKey: String?
}

enum PublicChatCategory: String, CaseIterable {
    case intro = "openmates_official"
    case example = "example"
    case legal = "legal"
    case announcement = "announcements"
    case tips = "tips_and_tricks"

    var displayName: String {
        switch self {
        case .intro: return "Introduction"
        case .example: return "Example Chats"
        case .legal: return "Legal"
        case .announcement: return "Announcements"
        case .tips: return "Tips & Tricks"
        }
    }

    var icon: String {
        switch self {
        case .intro: return "introduction"
        case .example: return "chat"
        case .legal: return "legal"
        case .announcement: return "announcement"
        case .tips: return "insight"
        }
    }
}

// Chat Settings reads sanitized public usage from the same bundled TypeScript
// examples as the web. The lexer reads values; it never executes TypeScript.
@MainActor
enum PublicChatUsageCatalog {
    private static var cache: [String: [ChatSettingsUsageRow]] = [:]
    static func rows(chatID: String) -> [ChatSettingsUsageRow] {
        if let cached = cache[chatID] { return cached }
        guard let source = source(chatID: chatID) else { cache[chatID] = []; return [] }
        let result = parse(source, chatID: chatID)
        cache[chatID] = result
        return result
    }
    static func source(chatID: String) -> String? {
        let aliases = ["example-eu-chat-control-law": "eu-chat-control-law-criticisms", "example-flights-berlin-bangkok": "flights-berlin-to-bangkok"]
        let name = aliases[chatID] ?? String(chatID.dropFirst("example-".count))
        guard chatID.hasPrefix("example-"), !name.contains("/"),
              let url = Bundle.main.url(forResource: name, withExtension: "ts", subdirectory: "example_chats")
                ?? Bundle.main.url(forResource: name, withExtension: "ts"),
              let source = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        return source
    }
    static func parse(_ source: String, chatID: String) -> [ChatSettingsUsageRow] {
        guard source.utf8.count <= 10_485_760,
              let identity = PublicAssistantSpeechManifest.value("chat_id", source),
              let value = PublicAssistantSpeechManifest.value("usage_entries", source),
              let data = value.data(using: .utf8), let identityData = identity.data(using: .utf8) else { return [] }
        let decoder = JSONDecoder(); decoder.allowsJSON5 = true; decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard (try? decoder.decode(String.self, from: identityData)) == chatID,
              let rows = try? decoder.decode([ChatSettingsUsageRow].self, from: data),
              rows.allSatisfy({ !$0.id.isEmpty && ($0.credits == nil || ($0.credits!.isFinite && $0.credits! >= 0)) }) else { return [] }
        return rows
    }
}

// Public file records contain only downloadable reference fields, never the
// source app payload, prompts, encryption keys or private media metadata.
@MainActor
enum PublicChatFileCatalog {
    private struct StaticEmbed: Decodable {
        let embedId: String
        let type: String
        let content: AnyCodable?
        let embedIds: [String]?
    }
    static func rows(chatID: String) -> [EmbedRecord] {
        guard let source = PublicChatUsageCatalog.source(chatID: chatID) else { return [] }
        return parse(source, chatID: chatID)
    }
    static func parse(_ source: String, chatID: String, origin: URL = ServerProfile.current().webBaseURL) -> [EmbedRecord] {
        guard source.utf8.count <= 10_485_760,
              let identity = PublicAssistantSpeechManifest.value("chat_id", source)?.data(using: .utf8),
              let embedSource = PublicAssistantSpeechManifest.value("embeds", source),
              let normalized = PublicAssistantSpeechManifest.json5WithStaticTemplates(embedSource),
              let embeds = normalized.data(using: .utf8) else { return [] }
        let decoder = JSONDecoder(); decoder.allowsJSON5 = true; decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard (try? decoder.decode(String.self, from: identity)) == chatID,
              let entries = try? decoder.decode([StaticEmbed].self, from: embeds), entries.count <= 4096 else { return [] }
        // Web uses all static embeds when messages contain no explicit refs.
        let messages = PublicAssistantSpeechManifest.value("messages", source) ?? ""
        let pattern = #"embed:([a-zA-Z0-9_.:-]+)"#
        let regex = try? NSRegularExpression(pattern: pattern)
        let range = NSRange(messages.startIndex..., in: messages)
        var referenced = Set((regex?.matches(in: messages, range: range) ?? []).compactMap { match -> String? in
            Range(match.range(at: 1), in: messages).map { String(messages[$0]) }
        })
        if !referenced.isEmpty {
            for _ in 0..<entries.count {
                let expanded = referenced.union(entries.filter { referenced.contains($0.embedId) }.flatMap { $0.embedIds ?? [] })
                if expanded == referenced { break }; referenced = expanded
            }
        }
        let records = entries.filter { referenced.isEmpty || referenced.contains($0.embedId) }.compactMap { entry -> EmbedRecord? in
            guard !entry.embedId.isEmpty else { return nil }
            let payload: [String: Any]
            if let content = entry.content?.value as? String {
                guard content.utf8.count <= 1_048_576, let decoded = try? Yams.load(yaml: content) as? [String: Any] else { return nil }
                payload = decoded
            } else { payload = entry.content?.value as? [String: Any] ?? [:] }
            let type = (payload["type"] as? String ?? entry.type).lowercased()
            let common = ["downloadUrl", "download_url", "file_url"]
            let media: [String]
            if type.contains("audio") || type == "music" || type == "recording" { media = ["previewAudioUrl", "preview_audio_url", "src", "url", "audio_url"] }
            else if type.contains("video") { media = ["previewVideoUrl", "preview_video_url", "video_url", "src", "url", "previewImageUrl", "preview_image_url"] }
            else if type.contains("image") || type == "svg" { media = ["previewImageUrl", "preview_image_url", "src", "url"] }
            else { media = ["previewAudioUrl", "preview_audio_url", "previewImageUrl", "preview_image_url", "previewVideoUrl", "preview_video_url", "src", "url", "video_url"] }
            let rawURL = (common + media).compactMap { payload[$0] as? String }.first { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            let url = rawURL.flatMap { PublicAssistantSpeechSegment.url($0, origin: origin) }
            let filename = inferredFilename(id: entry.embedId, type: type, payload: payload, url: url)
            let node = nodeType(type: type, filename: filename)
            var clean: [String: Any] = ["filename": filename, "type": type, "public_file_reference": true, "file_icon": icon(node), "file_metadata": metadata(node: node, type: type, payload: payload)]
            if let url { clean["public_file_url"] = url.absoluteString }
            if let mime = payload["mime_type"] as? String { clean["mime_type"] = mime }
            let value: [String: Any] = ["id": entry.embedId, "type": type, "status": "finished", "data": clean]
            guard let data = try? JSONSerialization.data(withJSONObject: value) else { return nil }
            return try? JSONDecoder().decode(EmbedRecord.self, from: data)
        }
        return ChatSettingsProjection.files(records)
    }
    private static func inferredFilename(id: String, type: String, payload: [String: Any], url: URL?) -> String {
        let basename = url?.lastPathComponent ?? ""
        if (type.contains("video") || type == "music" || type == "audio"), !basename.isEmpty { return ChatSettingsExport.safeFilename(basename, fallback: "file") }
        if let filename = payload["filename"] as? String, !filename.isEmpty { return filename.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "\\", with: "_") }
        if !basename.isEmpty { return ChatSettingsExport.safeFilename(basename, fallback: "file") }
        let language = (payload["language"] as? String ?? "").lowercased()
        let languages = ["bash": "sh", "javascript": "js", "typescript": "ts", "python": "py", "markdown": "md", "yaml": "yml", "text": "txt", "html": "html", "svelte": "svelte", "css": "css", "json": "json", "rust": "rs"]
        let mime = payload["mime_type"] as? String ?? ""
        let mimeExtensions = ["audio/mpeg": "mp3", "audio/wav": "wav", "image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf", "video/mp4": "mp4"]
        let fallback = type.contains("audio") || type == "music" || type == "recording" ? "mp3" : type.contains("video") ? "mp4" : type.contains("image") ? "png" : type.contains("pdf") ? "pdf" : type.contains("doc") ? "docx" : type.contains("sheet") ? "xlsx" : type == "model3d" ? "glb" : languages[language] ?? "txt"
        let ext = mimeExtensions[mime] ?? fallback
        let title = payload["title"] as? String
        return ChatSettingsExport.safeFilename((title.map { $0 + "." + ext }) ?? "\(type)-\(id.prefix(8)).\(ext)", fallback: "file.\(ext)")
    }
    private static func nodeType(type: String, filename: String) -> String {
        let ext = URL(fileURLWithPath: filename).pathExtension.lowercased()
        if type.contains("pdf") || ext == "pdf" { return "pdf" }
        if type.contains("image") || ["png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "heic", "heif"].contains(ext) { return "image" }
        if type.contains("video") || ["mp4", "mov", "webm", "m4v"].contains(ext) { return "video" }
        if type.contains("audio") || type == "music" || type == "recording" || ["mp3", "wav", "m4a", "ogg"].contains(ext) { return "recording" }
        if type.contains("sheet") || type == "spreadsheet" || ["csv", "xls", "xlsx", "ods"].contains(ext) { return "sheets-sheet" }
        if type.contains("doc") || ["doc", "docx", "odt", "rtf"].contains(ext) { return "docs-doc" }
        if type == "model3d" { return "model3d" }
        if type.contains("code") || type == "notebook" { return "code-code" }
        return "file"
    }
    private static func icon(_ node: String) -> String {
        ["pdf": "pdf", "image": "image", "video": "video", "recording": "audio", "sheets-sheet": "sheets", "docs-doc": "document", "code-code": "coding", "model3d": "3dmodels"][node] ?? "files"
    }
    private static func metadata(node: String, type: String, payload: [String: Any]) -> String {
        let label = ["pdf": "PDF", "image": "Image", "video": "Video", "recording": type == "music" ? "Music" : "Audio", "sheets-sheet": "Sheet", "docs-doc": "Document", "code-code": type == "notebook" ? "Notebook" : "Code file", "model3d": "3D model"][node] ?? "File"
        func number(_ keys: [String]) -> Double? {
            for key in keys {
                let value = (payload[key] as? NSNumber)?.doubleValue ?? (payload[key] as? String).flatMap(Double.init)
                if let value, value.isFinite, value > 0, value < Double(Int.max) { return value }
            }
            return nil
        }
        var parts = [label]
        for (keys, singular) in [(["line_count", "lineCount"], "line"), (["page_count", "pageCount"], "page"), (["word_count", "wordCount"], "word")] {
            if let count = number(keys) { parts.append("\(Int(count)) \(singular)" + (count == 1 ? "" : "s")) }
        }
        if let duration = number(["duration_seconds", "durationSeconds"]) { parts.append(String(format: duration < 10 ? "%.1fs" : "%.0fs", locale: Locale(identifier: "en_US_POSIX"), duration)) }
        if let size = number(["byte_length", "size_bytes", "sizeBytes"]) {
            if size < 1024 { parts.append("\(Int(size)) B") }
            else {
                let megabytes = size >= 1024 * 1024
                let amount = size / (megabytes ? 1024 * 1024 : 1024)
                parts.append(String(format: amount < 10 ? "%.1f" : "%.0f", locale: Locale(identifier: "en_US_POSIX"), amount) + (megabytes ? " MB" : " KB"))
            }
        }
        return parts.joined(separator: " | ")
    }

}
