// Real fullscreen export sources; absent artifacts never become dummy downloads.
// Web: embeds/{code,audio,docs,images,pdf,videos,diagrams}/ *EmbedFullscreen.svelte
//      services/zipExportService.ts
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.persistence.client-encrypted
import Foundation
import UniformTypeIdentifiers
import ZIPFoundation

@MainActor
enum NativeEmbedDownload {
    enum Source {
        case inline(NativeEmbedExportFile)
        case encrypted(filename: String, mime: String, key: String, nonce: String?, marker: String?, s3: String)
        case remote(filename: String, mime: String, url: URL)

        @MainActor
        func load(scope: String?, recipient: RecipientMediaContext?,
                  fetch: ((URL) async throws -> Data)? = nil,
                  decrypt: ((String, String, String?, String?) async throws -> Data)? = nil) async throws -> NativeEmbedExportFile {
            try Task.checkCancellation(); try recipient?.checkCurrent()
            let file: NativeEmbedExportFile
            switch self {
            case .inline(let value): file = value
            case .encrypted(let filename, let mime, let key, let nonce, let marker, let s3):
                guard recipient != nil || scope != nil else { throw UserTasksError.accountChanged }
                let bytes: Data
                if let decrypt { bytes = try await decrypt(s3, key, nonce, marker) }
                else { bytes = try await RecipientMediaContext.fetchAndDecrypt(context: recipient, s3Url: "", aesKeyHex: key,
                    aesNonceHex: nonce, encryption: marker, s3Key: s3, cacheNamespace: scope, cachePolicy: .memoryOnly) }
                file = .init(filename: filename, bytes: bytes, mimeType: mime)
            case .remote(let filename, let mime, let url):
                let bytes: Data
                if let fetch { bytes = try await fetch(url) }
                else if let recipient { bytes = try await recipient.download(url) }
                else {
                    let configuration = URLSessionConfiguration.ephemeral
                    configuration.httpCookieStorage = nil; configuration.urlCredentialStorage = nil; configuration.urlCache = nil
                    let session = URLSession(configuration: configuration); defer { session.invalidateAndCancel() }
                    let (data, response) = try await session.data(from: url)
                    guard let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode) else { throw URLError(.badServerResponse) }
                    bytes = data
                }
                guard !bytes.isEmpty else { throw URLError(.zeroByteResource) }
                file = .init(filename: filename, bytes: bytes, mimeType: mime)
            }
            try Task.checkCancellation(); try recipient?.checkCurrent()
            guard !file.bytes.isEmpty else { throw URLError(.zeroByteResource) }
            return file
        }
    }

    static func hasSource(_ embed: EmbedRecord) -> Bool {
        guard let type = EmbedType.normalized(rawValue: embed.type) else { return false }
        var raw = embed.rawData ?? [:]
        if let first = (raw["results"]?.value as? [[String: Any]])?.first {
            raw.merge(first.mapValues { AnyCodable($0) }, uniquingKeysWith: { _, new in new })
        }
        switch type {
        case .codeNotebook: return raw["notebook"] != nil || raw["cells"] != nil || raw["content"] != nil
        case .codeApplication: return (raw["file_refs"]?.value as? [[String: Any]])?.isEmpty == false
        case .diagramsMermaid, .electronicsPcbSchematic, .videosTranscript, .codeGetDocs: return hasCopySource(embed)
        case .fileFile: return FileEmbedPayload(raw).availableDownloadURL.flatMap { NativeEmbedActionURL.external($0.absoluteString) }?.scheme == "https"
        case .docsDoc: return (raw["docx_s3_key"] != nil && raw["aes_key"] != nil) || !DocumentCanvasSource(data: raw).html.isEmpty
        case .image, .imagesGenerate, .imagesGenerateDraft, .pdf, .audioGenerate, .audioSpeak, .recording, .musicGenerate, .videosGenerate, .videosCreate, .designIconResult:
            let original = (raw["files"]?.value as? [String: Any])?["original"] as? [String: Any]
            let key = (raw["aes_key"]?.value as? String) ?? (raw["aesKey"]?.value as? String)
            if let key, !key.isEmpty {
                let s3 = (original?["s3_key"] as? String) ?? (raw["files_original_s3_key"]?.value as? String) ?? (raw["s3_key"]?.value as? String)
                let nonce = (original?["aes_nonce"] as? String) ?? (raw["aes_nonce"]?.value as? String) ?? (raw["aesNonce"]?.value as? String)
                let marker = (original?["encryption"] as? String) ?? (raw["encryption"]?.value as? String) ?? (raw["files_original_encryption"]?.value as? String)
                return s3?.isEmpty == false && (nonce?.isEmpty == false || marker == S3MediaClient.noncePrefixedEncryption)
            }
            if (raw["audio_base64"]?.value as? String)?.isEmpty == false { return true }
            return ["audio_url", "video_url", "download_url", "png_url"].contains { field in
                guard let value = raw[field]?.value as? String, let url = NativeEmbedActionURL.external(value) else { return false }
                return url.scheme == "https"
            }
        default: return false
        }
    }

    static func source(_ embed: EmbedRecord, records: [String: EmbedRecord] = [:],
                       renderText: (String) -> String = { $0 }) -> Source? {
        guard let type = EmbedType.normalized(rawValue: embed.type) else { return nil }
        var raw = embed.rawData?.mapValues(\.value) ?? [:]
        if let results = raw["results"] as? [[String: Any]], let first = results.first {
            raw.merge(first, uniquingKeysWith: { _, new in new })
        }
        func string(_ keys: [String]) -> String? { keys.compactMap { raw[$0] as? String }.first(where: { !$0.isEmpty }) }
        func inline(_ text: String, _ name: String, _ mime: String) -> Source {
            .inline(.init(filename: name, bytes: Data(renderText(text).utf8), mimeType: mime))
        }
        let filename = string(["filename", "name", "title"]) ?? "download"
        let fields = raw.mapValues { AnyCodable($0) }
        switch type {
        case .fileFile:
            let file = FileEmbedPayload(fields)
            guard let url = file.availableDownloadURL, let safe = NativeEmbedActionURL.external(url.absoluteString), safe.scheme == "https" else { return nil }
            return .remote(filename: file.filename, mime: file.mimeType, url: safe)
        case .codeNotebook:
            let notebook: [String: Any]?
            if let value = raw["notebook"] as? [String: Any] { notebook = value }
            else if let value = raw["content"] as? [String: Any] { notebook = value }
            else if let value = raw["content"] as? String { notebook = try? JSONSerialization.jsonObject(with: Data(value.utf8)) as? [String: Any] }
            else { notebook = raw["cells"] != nil ? raw : nil }
            guard let notebook, notebook["cells"] is [Any],
                  let bytes = try? JSONSerialization.data(withJSONObject: notebook, options: [.prettyPrinted, .sortedKeys]) else { return nil }
            return .inline(.init(filename: filename.lowercased().hasSuffix(".ipynb") ? filename : "\(filename).ipynb",
                bytes: bytes, mimeType: "application/x-ipynb+json"))
        case .codeApplication:
            guard let refs = raw["file_refs"] as? [[String: Any]], !refs.isEmpty,
                  let bytes = try? applicationZIP(refs: refs, records: records, renderText: renderText) else { return nil }
            return .inline(.init(filename: slug(string(["app_name", "title", "name"]) ?? "application") + ".zip", bytes: bytes, mimeType: "application/zip"))
        case .diagramsMermaid:
            guard let code = string(["diagram_code", "diagramCode", "code", "source", "content"]) else { return nil }
            return inline(code, slug(string(["title"]) ?? "diagram") + ".mmd", "text/plain")
        case .electronicsPcbSchematic:
            let code = AppleCodeEmbedContent(data: fields)
            guard !code.code.isEmpty else { return nil }
            return inline(code.code, code.filename ?? "board.ato", "text/plain")
        case .videosTranscript:
            let results = VideoTranscriptPayload.flattenedResults(in: embed.rawData ?? [:])
            let payloads = results.map { VideoTranscriptPayload(data: $0.mapValues { AnyCodable($0) }) }.filter { !$0.transcript.isEmpty }
            guard !payloads.isEmpty else { return nil }
            let text = payloads.map { payload in
                var text = payload.title.map { "# \($0)\n\n" } ?? ""
                if let url = payload.sourceURL { text += "Source: \(url)\n\n" }
                if payload.wordCount > 0 { text += "Word count: \(payload.wordCount.formatted())\n\n" }
                return text + payload.transcript
            }.joined(separator: "\n\n---\n\n")
            return inline(text, slug(payloads.first?.title ?? "video") + "_transcript.md", "text/markdown")
        case .codeGetDocs:
            guard let text = string(["documentation", "content", "text"]) else { return nil }
            let library = string(["library_id", "libraryId"]) ?? "library"
            var content = "# \(library)\n\n"
            if let question = string(["question", "query"]) { content += "Query: \(question)\n" }
            content += "Source: Context7 (https://context7.com\(library))\n\n---\n\n" + text
            return inline(content, slug(library) + "_docs.md", "text/markdown")
        case .docsDoc:
            // Generated DOCX artifacts below remain the preferred original.
            if string(["docx_s3_key"]) == nil {
                let html = DocumentCanvasSource(data: fields).html
                guard !html.isEmpty, let bytes = try? NativeDocumentDOCX.build(html: renderText(html)) else { return nil }
                return .inline(.init(filename: filename.lowercased().hasSuffix(".docx") ? filename : filename + ".docx",
                    bytes: bytes, mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
            }
        default: break
        }
        if let key = string(["aes_key", "aesKey"]) {
            let files = raw["files"] as? [String: Any]
            let original = files?["original"] as? [String: Any]
            let s3 = (type == .docsDoc ? string(["docx_s3_key"]) : nil)
                ?? (original?["s3_key"] as? String) ?? string(["files_original_s3_key", "s3_key"])
            let nonce = (original?["aes_nonce"] as? String) ?? string(["aes_nonce", "aesNonce"])
            let marker = (original?["encryption"] as? String) ?? string(["encryption", "files_original_encryption"])
                // docsArtifactCrypto.ts explicitly defines nonce-prefixed artifacts.
                ?? (type == .docsDoc && string(["docx_s3_key"]) != nil ? S3MediaClient.noncePrefixedEncryption : nil)
            if let s3, nonce?.isEmpty == false || marker == S3MediaClient.noncePrefixedEncryption {
                let defaultExtension = type == .docsDoc ? "docx" : [.image, .imagesGenerate, .imagesGenerateDraft].contains(type) ? "png" : type == .pdf ? "pdf" : [EmbedType.recording, .audioGenerate, .audioSpeak, .musicGenerate].contains(type) ? "mp3" : [EmbedType.videosGenerate, .videosCreate].contains(type) ? "mp4" : "bin"
                let ext = original?["format"] as? String ?? defaultExtension
                let name: String
                if [.imagesGenerate, .imagesGenerateDraft].contains(type) { name = imageFilename(prompt: renderText(string(["prompt"]) ?? ""), extension: ext) }
                else { name = URL(fileURLWithPath: filename).pathExtension.isEmpty ? "\(filename).\(ext)" : filename }
                let mime = string(["mime_type", "content_type"]) ?? UTType(filenameExtension: ext)?.preferredMIMEType ?? "application/octet-stream"
                return .encrypted(filename: name, mime: mime, key: key, nonce: nonce, marker: marker, s3: s3)
            }
            // A private artifact with incomplete encryption metadata cannot fall
            // through to an unencrypted URL or a fabricated reference download.
            return nil
        }
        if [.audioGenerate, .audioSpeak, .recording, .musicGenerate].contains(type),
           let encoded = string(["audio_base64"]), let bytes = Data(base64Encoded: encoded), !bytes.isEmpty {
            let mime = string(["mime_type"]) ?? "audio/mpeg"
            let ext = UTType(mimeType: mime)?.preferredFilenameExtension ?? "mp3"
            return .inline(.init(filename: URL(fileURLWithPath: filename).pathExtension.isEmpty ? filename + "." + ext : filename,
                bytes: bytes, mimeType: mime))
        }
        if [.audioGenerate, .audioSpeak, .recording, .musicGenerate, .videosGenerate, .videosCreate, .designIconResult].contains(type) {
            let value = string(type == .designIconResult ? ["png_url", "download_url"] : ["audio_url", "video_url", "download_url"])
            if let value, let url = NativeEmbedActionURL.external(value), url.scheme == "https" {
                let ext = type == .designIconResult ? "png" : [.videosGenerate, .videosCreate].contains(type) ? "mp4" : "mp3"
                let name = URL(fileURLWithPath: filename).pathExtension.isEmpty ? "\(filename).\(ext)" : filename
                return .remote(filename: name, mime: UTType(filenameExtension: ext)?.preferredMIMEType ?? "application/octet-stream", url: url)
            }
        }
        return nil
    }

    static func hasCopySource(_ embed: EmbedRecord) -> Bool {
        guard let type = EmbedType.normalized(rawValue: embed.type) else { return false }
        let raw = embed.rawData ?? [:]
        switch type {
        case .docsDoc: return !DocumentCanvasSource(data: raw).html.isEmpty
        case .codeNotebook: return raw["notebook"] != nil || raw["cells"] != nil || raw["content"] != nil
        case .videosTranscript: return !VideoTranscriptPayload.flattenedResults(in: raw).isEmpty
        case .diagramsMermaid: return ["diagram_code", "diagramCode", "code", "source", "content"].contains { (raw[$0]?.value as? String)?.isEmpty == false }
        case .electronicsPcbSchematic: return !AppleCodeEmbedContent(data: raw).code.isEmpty
        case .codeGetDocs:
            let results = raw["results"]?.value as? [[String: Any]]
            return ["documentation", "content", "text"].contains { key in
                (raw[key]?.value as? String)?.isEmpty == false || (results?.first?[key] as? String)?.isEmpty == false
            }
        default: return false
        }
    }

    static func copyText(_ embed: EmbedRecord, renderText: (String) -> String = { $0 }) -> String? {
        guard let type = EmbedType.normalized(rawValue: embed.type) else { return nil }
        if [.diagramsMermaid, .electronicsPcbSchematic, .videosTranscript, .codeGetDocs, .codeNotebook].contains(type),
           let export = source(embed, renderText: renderText), case .inline(let file) = export {
            return String(data: file.bytes, encoding: .utf8)
        }
        if type == .docsDoc {
            let html = DocumentCanvasSource(data: embed.rawData).html
            guard !html.isEmpty else { return nil }
            return renderText(DocumentCanvasSource.sanitizeHTML(html)
                .replacingOccurrences(of: "<[^>]*>", with: " ", options: .regularExpression)
                .replacingOccurrences(of: "&nbsp;", with: " ").replacingOccurrences(of: "&lt;", with: "<")
                .replacingOccurrences(of: "&gt;", with: ">").replacingOccurrences(of: "&amp;", with: "&"))
        }
        return nil
    }

    static func applicationZIP(refs: [[String: Any]], records: [String: EmbedRecord], renderText: (String) -> String) throws -> Data {
        let zip = try Archive(data: Data(), accessMode: .create)
        var paths = Set<String>()
        for ref in refs {
            guard let id = ref["embed_id"] as? String, let path = ref["path"] as? String,
                  let record = records[id], EmbedType(rawValue: record.type) == .codeCode,
                  let data = record.rawData else { throw URLError(.fileDoesNotExist) }
            let code = AppleCodeEmbedContent(data: data)
            guard !code.code.isEmpty else { throw URLError(.fileDoesNotExist) }
            let safe = path.replacingOccurrences(of: "\\", with: "/").split(separator: "/")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty && $0 != "." && $0 != ".." }.joined(separator: "/")
            guard !safe.isEmpty, paths.insert(safe).inserted else { throw URLError(.badURL) }
            let bytes = Data(renderText(code.code).utf8)
            try zip.addEntry(with: safe, type: .file, uncompressedSize: Int64(bytes.count), compressionMethod: .deflate) { position, count in
                bytes.subdata(in: Int(position)..<min(bytes.count, Int(position) + count))
            }
        }
        return zip.data ?? Data()
    }
    private static func imageFilename(prompt: String, extension ext: String) -> String {
        var slug = prompt.lowercased().replacingOccurrences(of: "[^a-z0-9\\s]", with: " ", options: .regularExpression)
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression).trimmingCharacters(in: .whitespaces)
        if slug.count > 60 {
            slug = String(slug.prefix(60))
            if let space = slug.lastIndex(of: " "), slug.distance(from: slug.startIndex, to: space) > 20 { slug = String(slug[..<space]) }
        }
        slug = slug.replacingOccurrences(of: " ", with: "_").trimmingCharacters(in: CharacterSet(charactersIn: "_"))
        return "openmates_" + (slug.isEmpty ? "generated_image" : slug) + "." + ext
    }
    private static func slug(_ value: String) -> String {
        let value = value.lowercased().replacingOccurrences(of: "[^a-z0-9._-]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return value.isEmpty ? "download" : value
    }
}
