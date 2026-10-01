// Web source: frontend/packages/ui/src/services/chatExportService.ts,
// frontend/packages/ui/src/services/zipExportService.ts, chats/chatSettingsFiles.ts.
// Exports decrypted content only after an explicit action. Encryption keys are
// never included in fallback file metadata or ZIP manifests.
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.readonly-viewer-controls
import Foundation
import SwiftUI
import UniformTypeIdentifiers
import Yams
import ZIPFoundation

struct ChatSettingsExportDocument: FileDocument {
    static let readableContentTypes: [UTType] = [.data]
    let data: Data
    init(data: Data) { self.data = data }
    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else { throw CocoaError(.fileReadCorruptFile) }
        self.data = data
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}

struct ChatSettingsExportFile {
    let filename: String
    let data: Data
    let contentType: UTType
}

enum ChatSettingsExport {
    static func yaml(chat: Chat, messages: [Message]) throws -> Data {
        let value: [String: Any] = [
            "chat_id": chat.id, "title": chat.title ?? "Untitled chat",
            "summary": chat.chatSummary ?? "", "created_at": chat.createdAt,
            "messages": messages.map { ["message_id": $0.id, "role": $0.role.rawValue,
                                          "content": $0.content ?? "", "created_at": $0.createdAt] }
        ]
        return Data(try Yams.dump(object: value).utf8)
    }
    static func safeFilename(_ proposed: String, fallback: String) -> String {
        let last = proposed.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? fallback
        let safe = String(last.unicodeScalars.filter { !CharacterSet.controlCharacters.contains($0) && !"<>:\"|?*".unicodeScalars.contains($0) })
        return safe.isEmpty || safe == "." || safe == ".." ? fallback : String(safe.prefix(180))
    }
    static func title(_ embed: EmbedRecord) -> String {
        EmbedMediaPayload.string(embed.rawData, keys: ["filename", "title", "name"]) ?? embed.type
    }
    static func publicFileURL(_ embed: EmbedRecord) -> URL? {
        guard let value = EmbedMediaPayload.string(embed.rawData, keys: ["public_file_url"]) else { return nil }
        return PublicAssistantSpeechSegment.url(value)
    }
    @MainActor
    static func file(_ embed: EmbedRecord, scope: String?, recipientContext: RecipientMediaContext? = nil) async throws -> ChatSettingsExportFile {
        try recipientContext?.checkCurrent()
        let exported = try await exportFile(embed, scope: scope, recipientContext: recipientContext)
        try recipientContext?.checkCurrent()
        return exported
    }
    @MainActor
    private static func exportFile(_ embed: EmbedRecord, scope: String?, recipientContext: RecipientMediaContext?) async throws -> ChatSettingsExportFile {
        let raw = embed.rawData
        if let url = publicFileURL(embed) {
            let data: Data
            if let recipientContext { data = try await recipientContext.download(url) }
            else {
                let (bytes, response) = try await URLSession.shared.data(from: url)
                guard let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode) else { throw URLError(.badServerResponse) }
                data = bytes
            }
            let name = safeFilename(title(embed), fallback: url.lastPathComponent)
            return .init(filename: name, data: data, contentType: UTType(filenameExtension: URL(fileURLWithPath: name).pathExtension) ?? .data)
        }
        if raw?["public_file_reference"]?.value as? Bool == true {
            return try referenceFile(embed)
        }
        if let image = ImageOriginalDownloadPayload(data: raw) {
            guard let scope = recipientContext?.namespace ?? scope else { throw UserTasksError.accountChanged }
            return .init(filename: image.filename, data: try await image.load(using: recipientContext?.client ?? .shared, scope: scope), contentType: UTType(filenameExtension: URL(fileURLWithPath: image.filename).pathExtension) ?? .data)
        }
        if embed.type == "code-code" || embed.type == "code" {
            let code = AppleCodeEmbedContent(data: raw)
            let name = safeFilename(code.filename ?? "code.txt", fallback: "code.txt")
            return .init(filename: name, data: Data(code.code.utf8), contentType: .plainText)
        }
        if ["sheet", "sheets", "sheets-sheet", "spreadsheet"].contains(embed.type) {
            let table = ParsedSheetTable(data: raw)
            if !table.headers.isEmpty {
                return .init(filename: safeFilename(title(embed), fallback: "table") + ".xlsx", data: try SheetXLSXExporter.makeData(table: table), contentType: UTType(filenameExtension: "xlsx") ?? .data)
            }
        }
        if let key = EmbedMediaPayload.string(raw, keys: ["aes_key", "aesKey"]),
           let s3Key = EmbedMediaPayload.s3Key(from: raw) {
            guard let scope = recipientContext?.namespace ?? scope else { throw UserTasksError.accountChanged }
            let data = try await RecipientMediaContext.fetchAndDecrypt(context: recipientContext, s3Url: EmbedMediaPayload.s3URL(from: raw) ?? "", aesKeyHex: key,
                aesNonceHex: EmbedMediaPayload.string(raw, keys: ["aes_nonce", "aesNonce"]),
                encryption: EmbedMediaPayload.encryption(from: raw), s3Key: s3Key,
                cacheNamespace: scope, cachePolicy: .memoryOnly)
            let name = safeFilename(title(embed), fallback: "download.bin")
            return .init(filename: name, data: data, contentType: UTType(filenameExtension: URL(fileURLWithPath: name).pathExtension) ?? .data)
        }
        if let value = EmbedMediaPayload.string(raw, keys: ["url", "download_url", "audio_url", "video_url"]),
           let url = URL(string: value), url.scheme == "https" || url.scheme == "http" {
            let data: Data
            if let recipientContext { data = try await recipientContext.download(url) }
            else {
                let (bytes, response) = try await URLSession.shared.data(from: url)
                guard let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode) else { throw URLError(.badServerResponse) }
                data = bytes
            }
            let name = safeFilename(title(embed), fallback: "download.bin")
            return .init(filename: name, data: data, contentType: UTType(filenameExtension: URL(fileURLWithPath: name).pathExtension) ?? .data)
        }
        // Same fallback as chatSettingsFiles: export a file reference, never raw
        // decrypted payload metadata (which can contain a media AES key).
        return try referenceFile(embed)
    }
    private static func referenceFile(_ embed: EmbedRecord) throws -> ChatSettingsExportFile {
        let reference: [String: String] = ["embedId": embed.id, "contentRef": "embed:\(embed.id)", "title": title(embed), "type": embed.type]
        return .init(filename: safeFilename(title(embed), fallback: "file") + ".json", data: try JSONSerialization.data(withJSONObject: reference, options: [.prettyPrinted, .sortedKeys]), contentType: .json)
    }

    @MainActor
    static func zip(chat: Chat, messages: [Message], embeds: [EmbedRecord], scope: String?, recipientContext: RecipientMediaContext? = nil, check: () async throws -> Void) async throws -> Data {
        let archive = try Archive(data: Data(), accessMode: .create)
        var names: Set<String> = []
        func add(_ filename: String, _ data: Data) throws {
            let original = safeFilename(filename, fallback: "file.bin")
            var name = original; var suffix = 2
            while names.contains(name.lowercased()) {
                let url = URL(fileURLWithPath: original)
                name = "\(url.deletingPathExtension().lastPathComponent)_\(suffix)" + (url.pathExtension.isEmpty ? "" : ".\(url.pathExtension)")
                suffix += 1
            }
            names.insert(name.lowercased())
            try archive.addEntry(with: name, type: .file, uncompressedSize: Int64(data.count)) { offset, size in
                data.subdata(in: Int(offset)..<min(Int(offset) + size, data.count))
            }
        }
        try recipientContext?.checkCurrent()
        try await check()
        try add("chat.yaml", yaml(chat: chat, messages: messages))
        let markdown = messages.map { "## \($0.role.rawValue.capitalized)\n\n\($0.content ?? "")" }.joined(separator: "\n\n")
        try add("chat.md", Data(markdown.utf8))
        for embed in ChatSettingsProjection.files(embeds) {
            try recipientContext?.checkCurrent()
            try await check()
            let exported = try await file(embed, scope: scope, recipientContext: recipientContext)
            try recipientContext?.checkCurrent()
            try await check()
            try add(exported.filename, exported.data)
        }
        try recipientContext?.checkCurrent()
        try await check()
        guard let bytes = archive.data else { throw CocoaError(.fileWriteUnknown) }
        return bytes
    }
}
