// Background encrypted chat sender for OpenMates Apple surfaces.
// Used by extension-style flows that must start an assistant task without
// foreground navigation, such as the iOS share menu and notification replies.
// It mirrors ChatSendPipeline's WebSocket payloads and crypto handling while
// avoiding UI/store dependencies that are unavailable inside extensions.

import CryptoKit
import Foundation

struct BackgroundChatStoragePayload {
    let chatId: String
    let messageId: String
    let encryptedContent: String
    let createdAtUnix: Int
    let encryptedChatKey: String
    let messagesV: Int
    let titleV: Int
    let taskId: String
    let encryptedSenderName: String
    let encryptedPIIMappings: String?
    let encryptedTitle: String?
    let encryptedIcon: String?
    let encryptedChatCategory: String?
    let encryptedUserCategory: String?

    init(
        chatId: String,
        messageId: String,
        encryptedContent: String,
        createdAtUnix: Int,
        encryptedChatKey: String,
        messagesV: Int,
        titleV: Int,
        taskId: String,
        encryptedSenderName: String,
        encryptedPIIMappings: String? = nil,
        encryptedTitle: String? = nil,
        encryptedIcon: String? = nil,
        encryptedChatCategory: String? = nil,
        encryptedUserCategory: String? = nil
    ) {
        self.chatId = chatId
        self.messageId = messageId
        self.encryptedContent = encryptedContent
        self.createdAtUnix = createdAtUnix
        self.encryptedChatKey = encryptedChatKey
        self.messagesV = messagesV
        self.titleV = titleV
        self.taskId = taskId
        self.encryptedSenderName = encryptedSenderName
        self.encryptedPIIMappings = encryptedPIIMappings
        self.encryptedTitle = encryptedTitle
        self.encryptedIcon = encryptedIcon
        self.encryptedChatCategory = encryptedChatCategory
        self.encryptedUserCategory = encryptedUserCategory
    }

    var dictionary: [String: Any] {
        var payload: [String: Any] = [
            "chat_id": chatId,
            "message_id": messageId,
            "encrypted_content": encryptedContent,
            "created_at": createdAtUnix,
            "encrypted_chat_key": encryptedChatKey,
            "versions": [
                "messages_v": messagesV,
                "title_v": titleV,
                "last_edited_overall_timestamp": createdAtUnix
            ],
            "task_id": taskId,
            "encrypted_sender_name": encryptedSenderName
        ]
        if let encryptedPIIMappings { payload["encrypted_pii_mappings"] = encryptedPIIMappings }
        if let encryptedTitle { payload["encrypted_title"] = encryptedTitle }
        if let encryptedIcon { payload["encrypted_icon"] = encryptedIcon }
        if let encryptedChatCategory { payload["encrypted_chat_category"] = encryptedChatCategory }
        if let encryptedUserCategory { payload["encrypted_category"] = encryptedUserCategory }
        return payload
    }
}

struct BackgroundPIIMapping: Codable, Equatable, Sendable {
    let placeholder: String
    let original: String
    let type: String
}

struct BackgroundPIIRedactionResult: Equatable, Sendable {
    let content: String
    let piiMappings: [BackgroundPIIMapping]
}

enum BackgroundChatStorageContract {
    private static func hasText(_ value: String?) -> Bool {
        guard let value else { return false }
        return !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    static func shouldSendEncryptedStoragePackage(afterInboundEventType _: String) -> Bool {
        true
    }

    static func hasCompleteNewChatMetadata(title: String?, category: String?) -> Bool {
        hasText(title) && hasText(category)
    }

    static func storageTaskId(taskId: String?, aiTaskId: String?, activeTaskId: String?) -> String? {
        taskId ?? aiTaskId ?? activeTaskId
    }
}

enum BackgroundChatID {
    static func makeAuthenticatedChatId() -> String {
        UUID().uuidString.lowercased()
    }

    static func makeMessageId(chatId: String) -> String {
        "\(chatId.suffix(10))-\(UUID().uuidString.lowercased())"
    }
}

enum BackgroundChatHTTPContract {
    static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}

struct BackgroundAttachmentClassification: Equatable, Sendable {
    let embedType: String
    let referenceType: String
    let status: String
    let appId: String
    let skillId: String?
    let shouldSendContent: Bool
}

enum BackgroundAttachmentClassifier {
    static let maxFileSizeBytes = 100 * 1024 * 1024

    private static let imageExtensions: Set<String> = ["jpg", "jpeg", "png", "gif", "heic", "webp"]
    private static let audioExtensions: Set<String> = ["m4a", "mp3", "wav", "webm", "mp4", "flac", "ogg", "aac"]
    private static let documentExtensions: Set<String> = [
        "txt", "md", "markdown", "csv", "tsv", "json", "jsonl", "xml", "html", "htm", "log",
        "yaml", "yml", "toml", "ini", "conf", "config", "properties",
        "js", "jsx", "ts", "tsx", "svelte", "css", "scss", "sass", "less",
        "py", "rb", "php", "java", "kt", "kts", "swift", "go", "rs", "c", "h", "cpp", "hpp",
        "cs", "m", "mm", "sh", "bash", "zsh", "fish", "ps1", "sql", "r", "lua", "dart",
        "doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "ppt", "pptx", "odp"
    ]

    static func classification(filename: String, contentType: String?) -> BackgroundAttachmentClassification? {
        let mime = contentType?.lowercased() ?? ""
        let ext = (filename as NSString).pathExtension.lowercased()
        if mime.hasPrefix("audio/") || audioExtensions.contains(ext) {
            return BackgroundAttachmentClassification(
                embedType: "audio-recording",
                referenceType: "audio-recording",
                status: "finished",
                appId: "audio",
                skillId: "transcribe",
                shouldSendContent: true
            )
        }
        if mime.hasPrefix("image/") || imageExtensions.contains(ext) {
            return BackgroundAttachmentClassification(
                embedType: "images-image",
                referenceType: "image",
                status: "finished",
                appId: "images",
                skillId: "upload",
                shouldSendContent: true
            )
        }
        if mime == "application/pdf" || ext == "pdf" {
            return BackgroundAttachmentClassification(
                embedType: "pdf",
                referenceType: "pdf",
                status: "finished",
                appId: "pdf",
                skillId: nil,
                shouldSendContent: true
            )
        }
        if mime.hasPrefix("text/") || documentExtensions.contains(ext) {
            return BackgroundAttachmentClassification(
                embedType: "docs-doc",
                referenceType: "file",
                status: "finished",
                appId: "docs",
                skillId: nil,
                shouldSendContent: true
            )
        }
        return nil
    }
}

struct BackgroundUploadedFileVariant: Decodable, Sendable {
    let s3Key: String
    let sizeBytes: Int?
    let width: Int?
    let height: Int?
    let format: String?
}

struct BackgroundUploadFileResponse: Decodable, Sendable {
    let embedId: String
    let filename: String
    let contentType: String
    let contentHash: String?
    let files: [String: BackgroundUploadedFileVariant]
    let s3BaseUrl: String
    let aesKey: String
    let aesNonce: String
    let vaultWrappedAesKey: String
    let pageCount: Int?
    let deduplicated: Bool?
}

struct BackgroundAudioTranscriptionMetadata: Equatable, Sendable {
    let transcript: String?
    let transcriptOriginal: String?
    let transcriptCorrected: String?
    let useCorrected: Bool?
    let correctionModel: String?
    let model: String?
}

struct BackgroundPreparedEmbed: Identifiable, @unchecked Sendable {
    let id: String
    let type: String
    let referenceType: String
    let status: String
    let content: [String: Any]
    let textPreview: String?

    var markdownReference: String {
        "```json\n{\"type\": \"\(referenceType)\", \"embed_id\": \"\(id)\"}\n```"
    }

    var serverPayload: [String: Any]? {
        guard let contentString = Self.jsonString(content) else { return nil }
        var payload: [String: Any] = [
            "embed_id": id,
            "type": type,
            "status": status,
            "content": contentString,
            "createdAt": Int(Date().timeIntervalSince1970),
            "updatedAt": Int(Date().timeIntervalSince1970)
        ]
        if let textPreview { payload["text_preview"] = textPreview }
        return payload
    }

    static func from(
        upload: BackgroundUploadFileResponse,
        audioMetadata: BackgroundAudioTranscriptionMetadata? = nil,
        durationSeconds: TimeInterval? = nil
    ) throws -> BackgroundPreparedEmbed {
        guard let classification = BackgroundAttachmentClassifier.classification(
            filename: upload.filename,
            contentType: upload.contentType
        ) else {
            throw BackgroundChatSendError.unsupportedAttachment
        }

        let isPDF = upload.contentType.lowercased() == "application/pdf"
            || (upload.filename as NSString).pathExtension.lowercased() == "pdf"
        let status = isPDF && upload.deduplicated != true ? "processing" : classification.status

        var object: [String: Any] = [
            "app_id": classification.appId,
            "type": classification.referenceType,
            "status": status,
            "filename": upload.filename,
            "s3_base_url": upload.s3BaseUrl,
            "files": upload.files.mapValues { variant in
                var file: [String: Any] = ["s3_key": variant.s3Key]
                if let size = variant.sizeBytes { file["size_bytes"] = size }
                if let width = variant.width { file["width"] = width }
                if let height = variant.height { file["height"] = height }
                if let format = variant.format { file["format"] = format }
                return file
            },
            "aes_key": upload.aesKey,
            "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey
        ]
        if let skillId = classification.skillId { object["skill_id"] = skillId }
        if let contentHash = upload.contentHash { object["content_hash"] = contentHash }
        if let pageCount = upload.pageCount { object["page_count"] = pageCount }
        if let durationSeconds { object["duration"] = durationSeconds }
        if let audioMetadata {
            if let transcript = audioMetadata.transcript { object["transcript"] = transcript }
            if let transcriptOriginal = audioMetadata.transcriptOriginal { object["transcript_original"] = transcriptOriginal }
            if let transcriptCorrected = audioMetadata.transcriptCorrected { object["transcript_corrected"] = transcriptCorrected }
            if let useCorrected = audioMetadata.useCorrected { object["use_corrected"] = useCorrected }
            if let correctionModel = audioMetadata.correctionModel { object["correction_model"] = correctionModel }
            if let model = audioMetadata.model { object["model"] = model }
        }

        return BackgroundPreparedEmbed(
            id: upload.embedId,
            type: classification.embedType,
            referenceType: classification.referenceType,
            status: status,
            content: object,
            textPreview: audioMetadata?.transcript ?? upload.filename
        )
    }

    static func jsonString(_ object: [String: Any]) -> String? {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }
}

enum BackgroundChatSendContract {
    static func chatKeyIntent(
        isExistingChat: Bool,
        encryptedChatKey: String?
    ) throws -> BackgroundChatKeyIntent {
        if isExistingChat {
            guard let encryptedChatKey, !encryptedChatKey.isEmpty else {
                throw BackgroundChatSendError.missingChatKey
            }
            return .loadExisting(encryptedChatKey)
        }
        return .createNew
    }

    private struct Pattern: Sendable {
        let type: String
        let expression: NSRegularExpression
        let placeholderPrefix: String
        let validator: (@Sendable (String) -> Bool)?

        init(_ type: String, _ pattern: String, placeholderPrefix: String, options: NSRegularExpression.Options = [], validator: (@Sendable (String) -> Bool)? = nil) throws {
            self.type = type
            self.expression = try NSRegularExpression(pattern: pattern, options: options)
            self.placeholderPrefix = placeholderPrefix
            self.validator = validator
        }
    }

    private static let patterns: [Pattern] = {
        do {
            return [
                try Pattern("AWS_ACCESS_KEY", #"\bAKIA[0-9A-Z]{16}\b"#, placeholderPrefix: "AWS_KEY"),
                try Pattern("OPENAI_KEY", #"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,200}\b"#, placeholderPrefix: "OPENAI_KEY"),
                try Pattern("ANTHROPIC_KEY", #"\bsk-ant-api03-[A-Za-z0-9_-]{90,110}\b"#, placeholderPrefix: "ANTHROPIC_KEY"),
                try Pattern("GITHUB_PAT", #"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}|gho_[A-Za-z0-9]{36})\b"#, placeholderPrefix: "GITHUB_TOKEN"),
                try Pattern("STRIPE_KEY", #"\b[sr]k_(?:live|test)_[0-9a-zA-Z]{24,99}\b"#, placeholderPrefix: "STRIPE_KEY"),
                try Pattern("GOOGLE_API_KEY", #"\bAIza[0-9A-Za-z\-_]{35}\b"#, placeholderPrefix: "GOOGLE_KEY"),
                try Pattern("SLACK_TOKEN", #"\bxox[bpras]-[0-9a-zA-Z-]{10,250}\b"#, placeholderPrefix: "SLACK_TOKEN"),
                try Pattern("AWS_SECRET_KEY", #"(?:aws_secret|secret_key|secretkey|secret_access_key)['\":\s=]+([0-9a-zA-Z/+=]{40})\b"#, placeholderPrefix: "AWS_SECRET", options: [.caseInsensitive]),
                try Pattern("TWILIO_KEY", #"\b(?:AC[a-f0-9]{32}|SK[a-f0-9]{32})\b"#, placeholderPrefix: "TWILIO_KEY"),
                try Pattern("SENDGRID_KEY", #"\bSG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}\b"#, placeholderPrefix: "SENDGRID_KEY"),
                try Pattern("AZURE_KEY", #"(?:azure|subscription|ocp-apim)[_-]?(?:key|secret|token)['\":\s=]+([0-9a-f]{32})\b"#, placeholderPrefix: "AZURE_KEY", options: [.caseInsensitive]),
                try Pattern("HUGGINGFACE_KEY", #"\bhf_[a-zA-Z0-9]{34,}\b"#, placeholderPrefix: "HF_TOKEN"),
                try Pattern("DATABRICKS_TOKEN", #"\bdapi[a-f0-9]{32,40}\b"#, placeholderPrefix: "DATABRICKS_TOKEN"),
                try Pattern("FIREBASE_KEY", #"\bAAAA[A-Za-z0-9_-]{100,200}\b"#, placeholderPrefix: "FIREBASE_KEY"),
                try Pattern("GENERIC_SECRET", #"(?:api[_-]?key|api[_-]?secret|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|private[_-]?key|password|passwd|credential|client[_-]?secret|app[_-]?secret|signing[_-]?key|encryption[_-]?key)['\":\s=]+['\"]?([A-Za-z0-9_\-/.+=]{8,200})['\"]?"#, placeholderPrefix: "SECRET", options: [.caseInsensitive]),
                try Pattern("PRIVATE_KEY", #"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"#, placeholderPrefix: "PRIVATE_KEY"),
                try Pattern("JWT", #"\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+"#, placeholderPrefix: "JWT_TOKEN"),
                try Pattern("EMAIL", #"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"#, placeholderPrefix: "EMAIL", options: [.caseInsensitive]),
                try Pattern("CREDIT_CARD", #"\b(?:4[0-9]{3}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|5[1-5][0-9]{2}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|3[47][0-9]{2}[-\s]?[0-9]{6}[-\s]?[0-9]{5}|6(?:011|5[0-9]{2})[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4})\b"#, placeholderPrefix: "CARD", validator: luhnCheck),
                try Pattern("SSN", #"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"#, placeholderPrefix: "SSN", validator: ssnCheck),
                try Pattern("PHONE", #"(?:(?:\+|00)[1-9]\d{0,2}[-.\s/]?(?:\(?\d{1,5}\)?[-.\s/]?){1,4}\d{2,4})|(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}|(?:0\d[-.\s/]?(?:\(?\d{1,5}\)?[-.\s/]?){1,4}\d{2,4})"#, placeholderPrefix: "PHONE", validator: phoneCheck),
                try Pattern("IPV4", #"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"#, placeholderPrefix: "IP", validator: publicIPv4Check),
                try Pattern("IPV6", #"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"#, placeholderPrefix: "IPV6"),
                try Pattern("IBAN", #"\b[A-Z]{2}\d{2}[\s]?[\dA-Z]{4}[\s]?(?:[\dA-Z]{4}[\s]?){1,7}[\dA-Z]{1,4}\b"#, placeholderPrefix: "IBAN", validator: ibanCheck),
                try Pattern("HOME_FOLDER", #"(?:/home/|/Users/|[A-Z]:\\Users\\)[a-zA-Z0-9_.-]{1,64}(?=[/\\]|\b)|PS [A-Z]:\\Users\\[a-zA-Z0-9_.-]{1,64}(?=[\\>]|\b)|PS /(?:home|Users)/[a-zA-Z0-9_.-]{1,64}(?=[/>]|\b)"#, placeholderPrefix: "HOME_PATH", validator: homeFolderCheck),
                try Pattern("USER_AT_HOSTNAME", #"\b[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,31}@[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}(?=[\s:~])"#, placeholderPrefix: "USER_HOST", validator: userAtHostnameCheck),
                try Pattern("MAC_ADDRESS", #"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"#, placeholderPrefix: "MAC", validator: macAddressCheck),
                try Pattern("PASSPORT", #"(?:passport|reisepass|passeport|pass(?:port)?[\s._-]?(?:no|nr|num(?:ber)?|#))[:\s#=]*([A-Z0-9]{6,9})\b"#, placeholderPrefix: "PASSPORT", options: [.caseInsensitive]),
                try Pattern("TAX_ID", #"\b(?:AT ?U\d{8}|BE ?0?\d{9,10}|BG ?\d{9,10}|HR ?\d{11}|CY ?\d{8}[A-Z]|CZ ?\d{8,10}|DK ?\d{8}|EE ?\d{9}|FI ?\d{8}|FR ?[0-9A-Z]{2}\d{9}|DE ?\d{9}|EL ?\d{9}|HU ?\d{8}|IE ?\d{7}[A-Z]{1,2}|IT ?\d{11}|LV ?\d{11}|LT ?\d{9,12}|LU ?\d{8}|MT ?\d{8}|NL ?\d{9}B\d{2}|PL ?\d{10}|PT ?\d{9}|RO ?\d{2,10}|SK ?\d{10}|SI ?\d{8}|ES ?[A-Z0-9]\d{7}[A-Z0-9]|SE ?\d{12}|GB ?\d{9}(?:\d{3})?)\b|(?:tax[\s_-]?(?:id|number|no|nr)|steuer(?:nummer|identifikationsnummer|nr|ident(?:nummer)?)|tin[\s_-]?(?:number|no|nr)|vat[\s_-]?(?:id|number|no|nr)|tax[\s_-]?identification(?:[\s_-]?number)?)[:\s#=]+([A-Z0-9\s/-]{5,20})"#, placeholderPrefix: "TAX_ID", options: [.caseInsensitive]),
                try Pattern("VEHICLE_PLATE", #"(?:license[\s_-]?plate|plate[\s_-]?(?:number|no|nr)|kennzeichen|nummernschild|kfz[\s_-]?kennzeichen|immatriculation|registration[\s_-]?(?:number|no|nr|plate)|vrm|numberplate)[:\s#=]*([A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,6})\b"#, placeholderPrefix: "PLATE", options: [.caseInsensitive]),
                try Pattern("CRYPTO_WALLET", #"\b(?:bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|0x[0-9a-fA-F]{40})\b"#, placeholderPrefix: "WALLET")
            ]
        } catch {
            fatalError("Invalid background PII detector regex: \(error)")
        }
    }()

    static func contentForSend(text: String, embeds: [BackgroundPreparedEmbed]) throws -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || !embeds.isEmpty else { throw BackgroundChatSendError.emptyMessage }
        let references = embeds.map(\.markdownReference).joined(separator: "\n")
        if trimmed.isEmpty { return references }
        if references.isEmpty { return trimmed }
        return "\(trimmed)\n\n\(references)"
    }

    static func redactedContentForSend(text: String, embeds: [BackgroundPreparedEmbed]) throws -> BackgroundPIIRedactionResult {
        let content = try contentForSend(text: text, embeds: embeds)
        return redactPII(in: content)
    }

    private static func redactPII(in text: String) -> BackgroundPIIRedactionResult {
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        var occupied: [NSRange] = []
        var counters: [String: Int] = [:]
        var replacements: [(range: NSRange, mapping: BackgroundPIIMapping)] = []

        for pattern in patterns {
            pattern.expression.enumerateMatches(in: text, options: [], range: fullRange) { result, _, _ in
                guard let result else { return }
                let range = result.range(at: result.numberOfRanges > 1 && result.range(at: 1).location != NSNotFound ? 1 : 0)
                guard range.location != NSNotFound, range.length > 0 else { return }
                guard !occupied.contains(where: { NSIntersectionRange($0, range).length > 0 }) else { return }
                let value = nsText.substring(with: range)
                if let validator = pattern.validator, !validator(value) { return }
                let count = (counters[pattern.type] ?? 0) + 1
                counters[pattern.type] = count
                let placeholder = "[\(pattern.placeholderPrefix)_\(count)_\(suffix(value))]"
                occupied.append(range)
                replacements.append((
                    range,
                    BackgroundPIIMapping(placeholder: placeholder, original: value, type: pattern.type)
                ))
            }
        }

        let mutable = NSMutableString(string: text)
        for replacement in replacements.sorted(by: { $0.range.location > $1.range.location }) {
            mutable.replaceCharacters(in: replacement.range, with: replacement.mapping.placeholder)
        }
        return BackgroundPIIRedactionResult(
            content: mutable as String,
            piiMappings: replacements.sorted { $0.range.location < $1.range.location }.map(\.mapping)
        )
    }

    private static func suffix(_ value: String) -> String {
        let cleaned = value.trimmingCharacters(in: CharacterSet(charactersIn: "'\"; \n\t"))
        return String(cleaned.suffix(3))
    }

    private static func luhnCheck(_ value: String) -> Bool {
        let digits = value.compactMap(\.wholeNumberValue)
        guard (13...19).contains(digits.count) else { return false }
        var sum = 0
        var doubleDigit = false
        for digit in digits.reversed() {
            var value = digit
            if doubleDigit {
                value *= 2
                if value > 9 { value -= 9 }
            }
            sum += value
            doubleDigit.toggle()
        }
        return sum % 10 == 0
    }

    private static func ssnCheck(_ value: String) -> Bool {
        let digits = value.compactMap(\.wholeNumberValue)
        guard digits.count == 9 else { return false }
        let area = digits[0] * 100 + digits[1] * 10 + digits[2]
        let group = digits[3] * 10 + digits[4]
        let serial = digits[5] * 1000 + digits[6] * 100 + digits[7] * 10 + digits[8]
        return area != 0 && area != 666 && area < 900 && group != 0 && serial != 0
    }

    private static func phoneCheck(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        let digits = trimmed.compactMap(\.wholeNumberValue)
        guard (7...15).contains(digits.count) else { return false }
        if matches(#"^\d{4}$"#, trimmed) { return false }
        if matches(#"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$"#, trimmed) { return false }
        if matches(#"^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$"#, trimmed) { return false }
        if matches(#"^(?:19|20)\d{6}$"#, trimmed) { return false }
        if matches(#"^0\d{1,2}[-/.]\d{1,2}[-/.]\d{1,2}$"#, trimmed) { return false }
        return true
    }

    private static func publicIPv4Check(_ value: String) -> Bool {
        if value == "127.0.0.1" || value == "0.0.0.0" { return false }
        if value.hasPrefix("192.168.") || value.hasPrefix("10.") || value.hasPrefix("172.") { return false }
        return true
    }

    private static func ibanCheck(_ value: String) -> Bool {
        let cleaned = value.replacingOccurrences(of: " ", with: "").uppercased()
        guard (15...34).contains(cleaned.count) else { return false }
        let rearranged = String(cleaned.dropFirst(4)) + String(cleaned.prefix(4))
        var remainder = 0
        for scalar in rearranged.unicodeScalars {
            let digits: String
            if CharacterSet.uppercaseLetters.contains(scalar) {
                digits = String(Int(scalar.value) - 55)
            } else {
                digits = String(scalar)
            }
            for digit in digits.compactMap(\.wholeNumberValue) {
                remainder = (remainder * 10 + digit) % 97
            }
        }
        return remainder == 1
    }

    private static func homeFolderCheck(_ value: String) -> Bool {
        let cleaned = value.replacingOccurrences(of: #"^(?:PS\s+)?(?:/home/|/Users/|[A-Z]:\\Users\\)"#, with: "", options: .regularExpression).lowercased()
        let username = cleaned.split(whereSeparator: { $0 == "/" || $0 == "\\" || $0 == ">" }).first.map(String.init) ?? cleaned
        return !["root", "admin", "shared", "public", "default", "guest", "nobody", "daemon", "www-data", "ubuntu"].contains(username)
    }

    private static func userAtHostnameCheck(_ value: String) -> Bool {
        let parts = value.lowercased().split(separator: "@", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return false }
        if ["github.com", "gitlab.com", "bitbucket.org", "ssh.dev.azure.com"].contains(parts[1]) { return false }
        return !["root", "admin", "guest", "nobody", "daemon", "www-data", "noreply", "no-reply", "git", "svn", "user", "test", "ubuntu"].contains(parts[0])
    }

    private static func macAddressCheck(_ value: String) -> Bool {
        let normalized = value.replacingOccurrences(of: ":", with: "").replacingOccurrences(of: "-", with: "").uppercased()
        return normalized != "000000000000" && normalized != "FFFFFFFFFFFF"
    }

    private static func matches(_ pattern: String, _ text: String) -> Bool {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return false }
        return regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
    }
}

actor BackgroundChatSender {
    struct DestinationChat: Identifiable, Decodable, Sendable {
        let id: String
        var title: String?
        let lastMessageAt: String?
        let createdAt: String
        let updatedAt: String?
        let appId: String?
        let encryptedTitle: String?
        let encryptedCategory: String?
        let encryptedIcon: String?
        let encryptedChatKey: String?
        let messagesV: Int?
        let titleV: Int?

        var displayTitle: String {
            let trimmed = title?.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed?.isEmpty == false ? trimmed! : "Untitled chat"
        }

        init(
            id: String,
            title: String?,
            lastMessageAt: String?,
            createdAt: String,
            updatedAt: String?,
            appId: String?,
            encryptedTitle: String?,
            encryptedCategory: String?,
            encryptedIcon: String?,
            encryptedChatKey: String?,
            messagesV: Int?,
            titleV: Int?
        ) {
            self.id = id
            self.title = title
            self.lastMessageAt = lastMessageAt
            self.createdAt = createdAt
            self.updatedAt = updatedAt
            self.appId = appId
            self.encryptedTitle = encryptedTitle
            self.encryptedCategory = encryptedCategory
            self.encryptedIcon = encryptedIcon
            self.encryptedChatKey = encryptedChatKey
            self.messagesV = messagesV
            self.titleV = titleV
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            id = try container.decodeIfPresent(String.self, forKey: .id)
                ?? container.decode(String.self, forKey: .chatId)
            title = try container.decodeIfPresent(String.self, forKey: .title)
            lastMessageAt = Self.decodeFlexibleDateString(container, .lastMessageAt)
                ?? Self.decodeFlexibleDateString(container, .lastMessageTimestamp)
                ?? Self.decodeFlexibleDateString(container, .lastEditedOverallTimestamp)
                ?? Self.decodeFlexibleDateString(container, .updatedAt)
            createdAt = Self.decodeFlexibleDateString(container, .createdAt)
                ?? Self.decodeFlexibleDateString(container, .updatedAt)
                ?? ISO8601DateFormatter().string(from: Date())
            updatedAt = Self.decodeFlexibleDateString(container, .updatedAt)
            appId = try container.decodeIfPresent(String.self, forKey: .appId)
            encryptedTitle = try container.decodeIfPresent(String.self, forKey: .encryptedTitle)
            encryptedCategory = try container.decodeIfPresent(String.self, forKey: .encryptedCategory)
            encryptedIcon = try container.decodeIfPresent(String.self, forKey: .encryptedIcon)
            encryptedChatKey = try container.decodeIfPresent(String.self, forKey: .encryptedChatKey)
            messagesV = try container.decodeIfPresent(Int.self, forKey: .messagesV)
            titleV = try container.decodeIfPresent(Int.self, forKey: .titleV)
        }

        private static func decodeFlexibleDateString(
            _ container: KeyedDecodingContainer<CodingKeys>,
            _ key: CodingKeys
        ) -> String? {
            if let value = try? container.decodeIfPresent(String.self, forKey: key) {
                return value
            }
            if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
                return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(value)))
            }
            if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
                return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: value))
            }
            return nil
        }

        private enum CodingKeys: String, CodingKey {
            case id
            case chatId
            case title
            case lastMessageAt
            case lastMessageTimestamp
            case lastEditedOverallTimestamp
            case createdAt
            case updatedAt
            case appId
            case encryptedTitle
            case encryptedCategory
            case encryptedIcon
            case encryptedChatKey
            case messagesV
            case titleV
        }
    }

    struct SendRequest: Sendable {
        let content: String
        let destination: DestinationChat?
        let embeds: [BackgroundPreparedEmbed]

        init(content: String, destination: DestinationChat?, embeds: [BackgroundPreparedEmbed] = []) {
            self.content = content
            self.destination = destination
            self.embeds = embeds
        }
    }

    struct SendResult: Sendable {
        let chatId: String
        let messageId: String
    }

    private struct TranscribeSkillRequest: Encodable {
        let requests: [[String: AnyCodable]]
    }

    private struct TranscribeSkillResponse: Decodable {
        struct ResponseData: Decodable {
            struct ResultGroup: Decodable {
                struct Result: Decodable {
                    let transcript: String?
                    let transcriptOriginal: String?
                    let transcriptCorrected: String?
                    let useCorrected: Bool?
                    let correctionModel: String?
                    let model: String?
                }

                let results: [Result]
            }

            let results: [ResultGroup]
        }

        let data: ResponseData
    }

    private struct CachedUser: Decodable {
        let id: String
    }

    private struct SessionRequest: Encodable {
        let sessionId: String
        let deviceInfo: DeviceInfo
    }

    private struct DeviceInfo: Encodable {
        let os: String
        let deviceModel: String
        let appVersion: String
    }

    private struct SessionResponse: Decodable {
        let success: Bool
        let user: CachedUser?
        let wsToken: String?
        let needsDeviceVerification: Bool?
        let reAuthRequired: String?
        let reAuthReason: String?
    }

    private struct ChatSyncWrapper: Decodable {
        let chatDetails: DestinationChat?
    }

    private struct ChatSyncPayload: Decodable {
        let chats: [ChatSyncWrapper]?
    }

    private struct WSEnvelope<T: Decodable>: Decodable {
        let type: String
        let data: T?
        let payload: T?
    }

    private struct InboundMessage: Decodable {
        let type: String
        let data: [String: AnyCodable]?
        let payload: [String: AnyCodable]?

        func stringField(_ key: String) -> String? {
            if let value = payload?[key]?.value as? String { return value }
            if let value = data?[key]?.value as? String { return value }
            return nil
        }

        func stringArrayField(_ key: String) -> [String] {
            if let values = payload?[key]?.value as? [String] { return values }
            if let values = payload?[key]?.value as? [Any] { return values.compactMap { $0 as? String } }
            if let values = data?[key]?.value as? [String] { return values }
            if let values = data?[key]?.value as? [Any] { return values.compactMap { $0 as? String } }
            return []
        }
    }

    private struct ChatMetadata {
        let title: String?
        let iconNames: [String]
        let category: String?
        let userMessageId: String?
        let encryptedChatKey: String?

        static func empty(userMessageId: String) -> ChatMetadata {
            ChatMetadata(
                title: nil,
                iconNames: [],
                category: nil,
                userMessageId: userMessageId,
                encryptedChatKey: nil
            )
        }
    }

    private let crypto = CryptoManager.shared
    private let decoder: JSONDecoder
    private let encoder = BackgroundChatHTTPContract.makeEncoder()
    private let session: URLSession
    private var chatKeyCache: [String: SymmetricKey] = [:]

    init() {
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        session = URLSession(configuration: config)
    }

    func loadRecentChats(limit: Int = 12) async throws -> [DestinationChat] {
        let auth = try await currentAuthenticatedUser()
        let ws = try await BackgroundWebSocket.open(session: session, sessionId: nativeSessionId, token: auth.wsToken)
        defer { ws.close() }

        try await ws.sendText(webSocketText(type: "phased_sync_request", payload: [
            "phase": "all",
            "client_chat_versions": [:],
            "client_chat_ids": [],
            "client_suggestions_count": 0,
            "client_embed_ids": []
        ]))

        let deadline = Date().addingTimeInterval(8)
        while Date() < deadline {
            let data = try await ws.receiveData()
            guard let envelope = try? decoder.decode(WSEnvelope<ChatSyncPayload>.self, from: data),
                  envelope.type == "phase_2_last_20_chats_ready" || envelope.type == "sync_metadata_chats_response",
                  let payload = envelope.payload ?? envelope.data else {
                continue
            }
            var chats = (payload.chats ?? []).compactMap(\.chatDetails)
            chats = try await decryptDisplayTitles(for: chats, userId: auth.userId)
            return Array(chats.prefix(limit))
        }
        return []
    }

    func send(_ request: SendRequest) async throws -> SendResult {
        let redactionResult = try BackgroundChatSendContract.redactedContentForSend(text: request.content, embeds: request.embeds)
        let sendContent = redactionResult.content

        let auth = try await currentAuthenticatedUser()
        let now = Date()
        let createdAtUnix = Int(now.timeIntervalSince1970)
        let chatId = request.destination?.id ?? BackgroundChatID.makeAuthenticatedChatId()
        let messageId = BackgroundChatID.makeMessageId(chatId: chatId)
        let keyIntent = try BackgroundChatSendContract.chatKeyIntent(
            isExistingChat: request.destination != nil,
            encryptedChatKey: request.destination?.encryptedChatKey
        )
        let keyMaterial = try await ensureChatKey(
            chatId: chatId,
            intent: keyIntent,
            userId: auth.userId
        )
        let encryptedContent = try await crypto.encryptContent(sendContent, key: keyMaterial.key)
        let encryptedPIIMappings = try await encryptPIIMappings(redactionResult.piiMappings, key: keyMaterial.key)
        let encryptedEmbedPayloads = try await encryptedEmbeds(
            request.embeds,
            chatId: chatId,
            messageId: messageId,
            userId: auth.userId,
            chatKey: keyMaterial.key
        )
        let nextMessagesV = max(request.destination?.messagesV ?? 0, 0) + 1

        let ws = try await BackgroundWebSocket.open(session: session, sessionId: nativeSessionId, token: auth.wsToken)
        defer { ws.close() }

        var messagePayload: [String: Any] = [
            "message_id": messageId,
            "role": "user",
            "content": sendContent,
            "created_at": createdAtUnix,
            "sender_name": "user",
            "chat_has_title": (request.destination?.titleV ?? 0) > 0
        ]
        if (request.destination?.titleV ?? 0) > 0 {
            messagePayload["current_chat_title"] = request.destination?.title
        }

        let sendableEmbeds = request.embeds.compactMap(\.serverPayload)
        var outboundPayload: [String: Any] = [
            "chat_id": chatId,
            "message": messagePayload,
            "encrypted_chat_key": keyMaterial.encryptedChatKey
        ]
        if !sendableEmbeds.isEmpty {
            outboundPayload["embeds"] = sendableEmbeds
        }
        if !encryptedEmbedPayloads.isEmpty {
            outboundPayload["encrypted_embeds"] = encryptedEmbedPayloads
        }
        if let encryptedPIIMappings {
            outboundPayload["encrypted_pii_mappings"] = encryptedPIIMappings
        }

        try await ws.sendText(webSocketText(type: "chat_message_added", payload: outboundPayload))

        let isNewChat = request.destination == nil || (request.destination?.titleV ?? 0) == 0
        if let storage = try await waitForAssistantStart(
            ws: ws,
            chatId: chatId,
            userMessageId: messageId,
            requiresCompleteNewChatMetadata: isNewChat
        ) {
            try await sendEncryptedUserStoragePackage(
                ws: ws,
                chatId: chatId,
                messageId: messageId,
                content: sendContent,
                encryptedContent: encryptedContent,
                createdAtUnix: createdAtUnix,
                encryptedChatKey: storage.metadata.encryptedChatKey ?? keyMaterial.encryptedChatKey,
                key: keyMaterial.key,
                encryptedPIIMappings: encryptedPIIMappings,
                taskId: storage.taskId,
                metadata: storage.metadata,
                isNewChat: isNewChat,
                messagesV: nextMessagesV,
                currentTitleV: request.destination?.titleV ?? 0
            )
        }

        return SendResult(chatId: chatId, messageId: messageId)
    }

    func prepareAttachment(
        data: Data,
        filename: String,
        contentType: String,
        chatId: String,
        durationSeconds: TimeInterval? = nil
    ) async throws -> BackgroundPreparedEmbed {
        guard BackgroundAttachmentClassifier.classification(filename: filename, contentType: contentType) != nil else {
            throw BackgroundChatSendError.unsupportedAttachment
        }
        let upload = try await uploadAttachment(data: data, filename: filename, contentType: contentType, chatId: chatId)
        let isAudio = BackgroundAttachmentClassifier.classification(filename: filename, contentType: contentType)?.embedType == "audio-recording"
        if isAudio {
            let metadata = try await transcribeUploadedAudio(upload, chatId: chatId)
            return try BackgroundPreparedEmbed.from(upload: upload, audioMetadata: metadata, durationSeconds: durationSeconds)
        }
        return try BackgroundPreparedEmbed.from(upload: upload, durationSeconds: durationSeconds)
    }

    func uploadAttachment(data: Data, filename: String, contentType: String, chatId: String) async throws -> BackgroundUploadFileResponse {
        _ = try await currentAuthenticatedUser()
        let boundary = UUID().uuidString
        var body = Data()
        appendMultipartField(name: "file", filename: filename, contentType: contentType, data: data, boundary: boundary, to: &body)
        appendMultipartField(name: "chat_id", value: chatId, boundary: boundary, to: &body)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        let uploadURL = ServerConfiguration.current.uploadBaseURL.appendingPathComponent("v1/upload/file")
        var request = URLRequest(url: uploadURL)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue(ServerConfiguration.current.webAppURL.absoluteString, forHTTPHeaderField: "Origin")
        request.setValue("OpenMates-Apple/\(appVersion)", forHTTPHeaderField: "User-Agent")
        request.setValue(platformIdentifier, forHTTPHeaderField: "X-OpenMates-Client")
        request.httpBody = body
        return try await execute(request)
    }

    func transcribeUploadedAudio(_ upload: BackgroundUploadFileResponse, chatId: String) async throws -> BackgroundAudioTranscriptionMetadata {
        let s3Key = upload.files["original"]?.s3Key ?? upload.files.values.first?.s3Key
        guard let s3Key else { throw BackgroundChatSendError.encoding }

        let item: [String: Any] = [
            "id": upload.embedId,
            "embed_id": upload.embedId,
            "s3_key": s3Key,
            "s3_base_url": upload.s3BaseUrl,
            "aes_key": upload.aesKey,
            "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey,
            "filename": upload.filename,
            "mime_type": upload.contentType,
            "chat_id": chatId
        ]

        let response: TranscribeSkillResponse = try await apiRequest(
            .post,
            path: "/v1/apps/audio/skills/transcribe",
            body: TranscribeSkillRequest(requests: [item.mapValues { AnyCodable($0) }])
        )
        let result = response.data.results.first?.results.first
        return BackgroundAudioTranscriptionMetadata(
            transcript: result?.transcript,
            transcriptOriginal: result?.transcriptOriginal,
            transcriptCorrected: result?.transcriptCorrected,
            useCorrected: result?.useCorrected,
            correctionModel: result?.correctionModel,
            model: result?.model
        )
    }

    private func waitForAssistantStart(
        ws: BackgroundWebSocket,
        chatId: String,
        userMessageId: String,
        requiresCompleteNewChatMetadata: Bool
    ) async throws -> (taskId: String, metadata: ChatMetadata)? {
        var taskId: String?
        var metadata: ChatMetadata?
        var deadline = Date().addingTimeInterval(20)

        func hasRequiredMetadata(_ metadata: ChatMetadata?) -> Bool {
            guard requiresCompleteNewChatMetadata else { return true }
            return BackgroundChatStorageContract.hasCompleteNewChatMetadata(
                title: metadata?.title,
                category: metadata?.category
            )
        }

        func shrinkDeadlineForMetadataGrace() {
            let metadataGraceDeadline = Date().addingTimeInterval(2)
            if metadataGraceDeadline < deadline {
                deadline = metadataGraceDeadline
            }
        }

        while Date() < deadline {
            guard let data = try await receiveData(ws, before: deadline) else { break }
            guard let inbound = try? decoder.decode(InboundMessage.self, from: data) else { continue }
            switch inbound.type {
            case "ai_task_initiated":
                if inbound.stringField("chat_id") == chatId,
                   inbound.stringField("user_message_id") == userMessageId {
                    taskId = inbound.stringField("ai_task_id") ?? inbound.stringField("task_id")
                    if let taskId {
                        if let metadata, hasRequiredMetadata(metadata) { return (taskId, metadata) }
                        shrinkDeadlineForMetadataGrace()
                    }
                }
            case "ai_typing_started":
                guard inbound.stringField("chat_id") == chatId else { continue }
                let candidate = ChatMetadata(
                    title: inbound.stringField("title"),
                    iconNames: inbound.stringArrayField("icon_names"),
                    category: inbound.stringField("category"),
                    userMessageId: inbound.stringField("user_message_id"),
                    encryptedChatKey: inbound.stringField("encrypted_chat_key")
                )
                if candidate.userMessageId == nil || candidate.userMessageId == userMessageId {
                    metadata = candidate
                }
            case "message_queued":
                guard BackgroundChatStorageContract.shouldSendEncryptedStoragePackage(afterInboundEventType: inbound.type),
                      inbound.stringField("chat_id") == chatId else {
                    continue
                }
                if let queuedUserMessageId = inbound.stringField("user_message_id"), queuedUserMessageId != userMessageId {
                    continue
                }
                if let queuedTaskId = BackgroundChatStorageContract.storageTaskId(
                    taskId: inbound.stringField("task_id"),
                    aiTaskId: inbound.stringField("ai_task_id"),
                    activeTaskId: inbound.stringField("active_task_id")
                ) {
                    taskId = queuedTaskId
                    if hasRequiredMetadata(metadata) {
                        return (queuedTaskId, metadata ?? ChatMetadata.empty(userMessageId: userMessageId))
                    }
                }
            default:
                break
            }
            if let taskId, let metadata, hasRequiredMetadata(metadata) {
                return (taskId, metadata)
            }
        }

        if let taskId {
            guard hasRequiredMetadata(metadata) else {
                throw BackgroundChatSendError.incompleteNewChatMetadata
            }
            return (taskId, metadata ?? ChatMetadata.empty(userMessageId: userMessageId))
        }
        return nil
    }

    private func receiveData(_ ws: BackgroundWebSocket, before deadline: Date) async throws -> Data? {
        let remainingSeconds = deadline.timeIntervalSinceNow
        guard remainingSeconds > 0 else { return nil }
        let remainingNanoseconds = UInt64(remainingSeconds * 1_000_000_000)

        return try await withThrowingTaskGroup(of: Data?.self) { group in
            group.addTask {
                try await ws.receiveData()
            }
            group.addTask {
                try await Task.sleep(nanoseconds: remainingNanoseconds)
                return nil
            }

            let result = try await group.next() ?? nil
            group.cancelAll()
            return result
        }
    }

    private func sendEncryptedUserStoragePackage(
        ws: BackgroundWebSocket,
        chatId: String,
        messageId: String,
        content: String,
        encryptedContent: String,
        createdAtUnix: Int,
        encryptedChatKey: String,
        key: SymmetricKey,
        encryptedPIIMappings: String?,
        taskId: String,
        metadata: ChatMetadata,
        isNewChat: Bool,
        messagesV: Int,
        currentTitleV: Int
    ) async throws {
        let encryptedTitle = isNewChat ? try await encryptOptional(metadata.title, key: key) : nil
        let icon = isNewChat ? preferredIcon(from: metadata.iconNames, category: metadata.category) : nil
        let encryptedIcon = try await encryptOptional(icon, key: key)
        let encryptedChatCategory = isNewChat ? try await encryptOptional(metadata.category, key: key) : nil
        let encryptedSenderName = try await crypto.encryptContent("user", key: key)
        let encryptedUserCategory = try await encryptOptional(metadata.category, key: key)

        let payload = BackgroundChatStoragePayload(
            chatId: chatId,
            messageId: messageId,
            encryptedContent: encryptedContent,
            createdAtUnix: createdAtUnix,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: encryptedTitle == nil ? currentTitleV : currentTitleV + 1,
            taskId: taskId,
            encryptedSenderName: encryptedSenderName,
            encryptedPIIMappings: encryptedPIIMappings,
            encryptedTitle: encryptedTitle,
            encryptedIcon: encryptedIcon,
            encryptedChatCategory: encryptedChatCategory,
            encryptedUserCategory: encryptedUserCategory
        ).dictionary

        try await ws.sendText(webSocketText(type: "encrypted_chat_metadata", payload: payload))
    }

    private func decryptDisplayTitles(for chats: [DestinationChat], userId: String) async throws -> [DestinationChat] {
        guard let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw BackgroundChatSendError.missingMasterKey
        }

        var decrypted: [DestinationChat] = []
        for var chat in chats {
            if let encryptedTitle = chat.encryptedTitle,
               let encryptedChatKey = chat.encryptedChatKey,
               let chatKey = try? await crypto.unwrapChatKey(encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey),
               let title = try? await crypto.decryptContent(base64String: encryptedTitle, key: chatKey) {
                chat.title = title
            }
            decrypted.append(chat)
        }
        return decrypted
    }

    private func ensureChatKey(
        chatId: String,
        intent: BackgroundChatKeyIntent,
        userId: String
    ) async throws -> (key: SymmetricKey, encryptedChatKey: String) {
        guard let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw BackgroundChatSendError.missingMasterKey
        }
        switch intent {
        case .loadExisting(let encryptedChatKey):
            let key = try await crypto.unwrapChatKey(encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey)
            chatKeyCache[chatId] = key
            return (key, encryptedChatKey)
        case .createNew:
            let key = await crypto.generateChatKey()
            chatKeyCache[chatId] = key
            return (key, try await crypto.wrapChatKey(key, masterKey: masterKey))
        }
    }

    private func encryptedEmbeds(
        _ embeds: [BackgroundPreparedEmbed],
        chatId: String,
        messageId: String,
        userId: String,
        chatKey: SymmetricKey
    ) async throws -> [[String: Any]] {
        guard !embeds.isEmpty else { return [] }
        guard let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw BackgroundChatSendError.missingMasterKey
        }

        let hashedChatId = sha256Hex(chatId)
        let hashedMessageId = sha256Hex(messageId)
        let hashedUserId = sha256Hex(userId)
        let now = Int(Date().timeIntervalSince1970)

        var encryptedPayloads: [[String: Any]] = []
        for embed in embeds {
            guard let content = BackgroundPreparedEmbed.jsonString(embed.content) else {
                throw BackgroundChatSendError.encoding
            }
            let embedKey = ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: embed.id)
            let hashedEmbedId = sha256Hex(embed.id)
            let wrappedWithMaster = try ComposerEmbedCrypto.wrapKey(embedKey, using: masterKey)
            let wrappedWithChat = try ComposerEmbedCrypto.wrapKey(embedKey, using: chatKey)
            var payload: [String: Any] = [
                "embed_id": embed.id,
                "encrypted_type": try ComposerEmbedCrypto.encryptContent(embed.type, using: embedKey),
                "encrypted_content": try ComposerEmbedCrypto.encryptContent(content, using: embedKey),
                "status": embed.status,
                "hashed_chat_id": hashedChatId,
                "hashed_message_id": hashedMessageId,
                "hashed_user_id": hashedUserId,
                "created_at": now,
                "updated_at": now,
                "embed_keys": [
                    [
                        "hashed_embed_id": hashedEmbedId,
                        "key_type": "master",
                        "hashed_chat_id": NSNull(),
                        "encrypted_embed_key": wrappedWithMaster,
                        "hashed_user_id": hashedUserId,
                        "created_at": now
                    ],
                    [
                        "hashed_embed_id": hashedEmbedId,
                        "key_type": "chat",
                        "hashed_chat_id": hashedChatId,
                        "encrypted_embed_key": wrappedWithChat,
                        "hashed_user_id": hashedUserId,
                        "created_at": now
                    ]
                ]
            ]
            if let textPreview = embed.textPreview {
                payload["encrypted_text_preview"] = try ComposerEmbedCrypto.encryptContent(textPreview, using: embedKey)
            }
            encryptedPayloads.append(payload)
        }
        return encryptedPayloads
    }

    private func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func encryptOptional(_ value: String?, key: SymmetricKey) async throws -> String? {
        guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return try await crypto.encryptContent(value, key: key)
    }

    private func encryptPIIMappings(_ mappings: [BackgroundPIIMapping], key: SymmetricKey) async throws -> String? {
        guard !mappings.isEmpty else { return nil }
        let data = try JSONEncoder().encode(mappings)
        guard let json = String(data: data, encoding: .utf8) else { return nil }
        return try await crypto.encryptContent(json, key: key)
    }

    private func preferredIcon(from iconNames: [String], category: String?) -> String {
        iconNames.first ?? categoryIconFallback(category)
    }

    private func categoryIconFallback(_ category: String?) -> String {
        switch category {
        case "web": return "search"
        case "travel": return "plane"
        case "videos": return "video"
        case "nutrition": return "utensils"
        case "code": return "code"
        default: return "sparkles"
        }
    }

    private func currentAuthenticatedUser() async throws -> (userId: String, wsToken: String?) {
        let response: SessionResponse = try await apiRequest(
            .post,
            path: "/v1/auth/session",
            body: SessionRequest(sessionId: nativeSessionId, deviceInfo: makeDeviceInfo())
        )
        guard response.success, response.needsDeviceVerification != true, let user = response.user else {
            if response.reAuthRequired != nil || response.reAuthReason != nil {
                throw BackgroundChatSendError.notAuthenticated
            }
            throw BackgroundChatSendError.notAuthenticated
        }
        guard (try? await crypto.loadMasterKey(for: user.id)) != nil else {
            throw BackgroundChatSendError.missingMasterKey
        }
        return (user.id, response.wsToken)
    }

    private var nativeSessionId: String {
        let key = "openmates.apple.auth.session_id"
        if let existing = OpenMatesSharedEnvironment.defaults.string(forKey: key) {
            return existing
        }
        if let existing = UserDefaults.standard.string(forKey: key) {
            OpenMatesSharedEnvironment.defaults.set(existing, forKey: key)
            return existing
        }
        let newValue = UUID().uuidString
        OpenMatesSharedEnvironment.defaults.set(newValue, forKey: key)
        UserDefaults.standard.set(newValue, forKey: key)
        return newValue
    }

    private func apiRequest<T: Decodable, Body: Encodable>(
        _ method: BackgroundHTTPMethod,
        path: String,
        body: Body
    ) async throws -> T {
        var request = buildRequest(method, path: path)
        request.httpBody = try encoder.encode(body)
        return try await execute(request)
    }

    private func buildRequest(_ method: BackgroundHTTPMethod, path: String) -> URLRequest {
        let normalizedPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        let pathAndQuery = normalizedPath.split(separator: "?", maxSplits: 1).map(String.init)
        var url = ServerConfiguration.current.apiBaseURL.appendingPathComponent(pathAndQuery[0])
        if pathAndQuery.count == 2, var components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            components.percentEncodedQuery = pathAndQuery[1]
            url = components.url ?? url
        }

        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(ServerConfiguration.current.webAppURL.absoluteString, forHTTPHeaderField: "Origin")
        request.setValue("OpenMates-Apple/\(appVersion)", forHTTPHeaderField: "User-Agent")
        request.setValue(platformIdentifier, forHTTPHeaderField: "X-OpenMates-Client")
        request.setValue(Bundle.main.bundleIdentifier ?? "org.openmates.app", forHTTPHeaderField: "X-OpenMates-Bundle-ID")
        if let cookieHeader = OpenMatesSharedEnvironment.cookieHeader(for: url) {
            request.setValue(cookieHeader, forHTTPHeaderField: "Cookie")
        }
        return request
    }

    private func execute<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw BackgroundChatSendError.network
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            if httpResponse.statusCode == 401 { throw BackgroundChatSendError.notAuthenticated }
            throw BackgroundChatSendError.server(httpResponse.statusCode)
        }
        return try decoder.decode(T.self, from: data)
    }

    private func webSocketText(type: String, payload: [String: Any]) throws -> String {
        let outbound = BackgroundWSOutboundMessage(type: type, payload: payload)
        let data = try JSONEncoder().encode(outbound)
        guard let text = String(data: data, encoding: .utf8) else {
            throw BackgroundChatSendError.encoding
        }
        return text
    }

    private func appendMultipartField(
        name: String,
        filename: String,
        contentType: String,
        data: Data,
        boundary: String,
        to body: inout Data
    ) {
        let safeName = safeMultipartHeaderValue(filename)
        let safeContentType = safeMultipartHeaderValue(contentType)
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(safeName)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(safeContentType)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n".data(using: .utf8)!)
    }

    private func safeMultipartHeaderValue(_ value: String) -> String {
        value.map { character -> String in
            character == "\r" || character == "\n" || character == "\"" ? "_" : String(character)
        }.joined()
    }

    private func appendMultipartField(
        name: String,
        value: String,
        boundary: String,
        to body: inout Data
    ) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        body.append(value.data(using: .utf8)!)
        body.append("\r\n".data(using: .utf8)!)
    }

    private func makeDeviceInfo() -> DeviceInfo {
        #if os(iOS)
        let os = "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        let model = "iOS Extension"
        #elseif os(macOS)
        let os = "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        let model = "macOS Extension"
        #else
        let os = "Apple \(ProcessInfo.processInfo.operatingSystemVersionString)"
        let model = "Apple Extension"
        #endif
        return DeviceInfo(os: os, deviceModel: model, appVersion: appVersion)
    }

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
    }

    private var platformIdentifier: String {
        #if os(iOS)
        return "ios-share-extension"
        #elseif os(macOS)
        return "macos-share-extension"
        #else
        return "apple-extension"
        #endif
    }
}

private final class BackgroundWebSocket: @unchecked Sendable {
    private let task: URLSessionWebSocketTask

    private init(task: URLSessionWebSocketTask) {
        self.task = task
    }

    static func open(session: URLSession, sessionId: String, token: String?) async throws -> BackgroundWebSocket {
        guard var components = URLComponents(url: ServerConfiguration.current.apiBaseURL, resolvingAgainstBaseURL: false) else {
            throw BackgroundChatSendError.network
        }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.path = "/v1/ws"
        var queryItems = [URLQueryItem(name: "sessionId", value: sessionId)]
        if let token, !token.isEmpty {
            queryItems.append(URLQueryItem(name: "token", value: token))
        }
        components.queryItems = queryItems
        guard let url = components.url else { throw BackgroundChatSendError.network }

        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.setValue(ServerConfiguration.current.webAppURL.absoluteString, forHTTPHeaderField: "Origin")
        request.setValue("OpenMates-Apple/\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0")", forHTTPHeaderField: "User-Agent")
        request.setValue(Bundle.main.bundleIdentifier ?? "org.openmates.app", forHTTPHeaderField: "X-OpenMates-Bundle-ID")
        if let cookieHeader = OpenMatesSharedEnvironment.cookieHeader(for: url) {
            request.setValue(cookieHeader, forHTTPHeaderField: "Cookie")
        }

        let task = session.webSocketTask(with: request)
        task.resume()
        let ws = BackgroundWebSocket(task: task)
        try await ws.waitForOpenSocket()
        return ws
    }

    func sendText(_ text: String) async throws {
        try await task.send(.string(text))
    }

    func receiveData() async throws -> Data {
        let message = try await task.receive()
        switch message {
        case .string(let text):
            guard let data = text.data(using: .utf8) else { throw BackgroundChatSendError.encoding }
            return data
        case .data(let data):
            return data
        @unknown default:
            throw BackgroundChatSendError.network
        }
    }

    func close() {
        task.cancel(with: .normalClosure, reason: nil)
    }

    private func waitForOpenSocket() async throws {
        try await Task.sleep(for: .milliseconds(650))
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            task.sendPing { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            }
        }
    }
}

private struct BackgroundWSOutboundMessage: Encodable {
    let type: String
    let payload: [String: AnyCodable]

    init(type: String, payload: [String: Any]) {
        self.type = type
        self.payload = payload.mapValues { AnyCodable($0) }
    }
}

enum BackgroundChatKeyIntent: Equatable {
    case createNew
    case loadExisting(String)
}

enum BackgroundChatSendError: LocalizedError {
    case emptyMessage
    case unsupportedAttachment
    case notAuthenticated
    case missingMasterKey
    case missingChatKey
    case incompleteNewChatMetadata
    case network
    case encoding
    case server(Int)

    var errorDescription: String? {
        switch self {
        case .emptyMessage:
            return "Nothing to send."
        case .unsupportedAttachment:
            return "This file type is not supported yet."
        case .notAuthenticated:
            return "Open OpenMates and sign in first."
        case .missingMasterKey:
            return "Open OpenMates and sign in again to unlock encryption on this device."
        case .missingChatKey:
            return "OpenMates could not unlock this chat. Open the app and try again."
        case .incompleteNewChatMetadata:
            return "The assistant did not return complete chat metadata. Please try again."
        case .network:
            return "OpenMates could not connect. Please try again."
        case .encoding:
            return "OpenMates could not prepare the message."
        case .server(let status):
            return "OpenMates server error (\(status))."
        }
    }
}

private enum BackgroundHTTPMethod: String {
    case get = "GET"
    case post = "POST"
}
