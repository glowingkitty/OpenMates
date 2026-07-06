// PII detection UI — warns user about personal data in messages.
// Shows detected PII count with option to exclude individual entries.
// Replaces PII with placeholders like [EMAIL_1], [PHONE_1] on send.

import SwiftUI
import CryptoKit

struct PIIMatch: Identifiable, Equatable, Sendable {
    let id: String
    let type: PIIType
    let value: String
    let range: NSRange
    let placeholder: String
}

struct PersonalDataForDetection: Equatable, Sendable {
    let id: String
    let textToHide: String
    let replaceWith: String
    let additionalTexts: [String]
    let type: PIIType?

    init(id: String, textToHide: String, replaceWith: String, additionalTexts: [String] = [], type: PIIType? = nil) {
        self.id = id
        self.textToHide = textToHide
        self.replaceWith = replaceWith
        self.additionalTexts = additionalTexts
        self.type = type
    }
}

struct PIIDetectionOptions: Equatable, Sendable {
    let excludedIds: Set<String>
    let disabledCategories: Set<String>
    let personalDataEntries: [PersonalDataForDetection]

    init(
        excludedIds: Set<String> = [],
        disabledCategories: Set<String> = [],
        personalDataEntries: [PersonalDataForDetection] = []
    ) {
        self.excludedIds = excludedIds
        self.disabledCategories = disabledCategories
        self.personalDataEntries = personalDataEntries
    }
}

struct PIIRedactionResult: Equatable, Sendable {
    let originalText: String
    let redactedText: String
    let matches: [PIIMatch]
    let mappings: [PIIMapping]
}

struct PIIPrivacySettings: Equatable, Sendable {
    let masterEnabled: Bool
    let disabledCategories: Set<String>
    let personalDataEntries: [PersonalDataForDetection]

    static let enabled = PIIPrivacySettings(
        masterEnabled: true,
        disabledCategories: [],
        personalDataEntries: []
    )

    var detectionOptions: PIIDetectionOptions {
        guard masterEnabled else {
            return PIIDetectionOptions(disabledCategories: Set(PIIPrivacyCategory.allCategoryKeys))
        }
        return PIIDetectionOptions(
            disabledCategories: disabledCategories,
            personalDataEntries: personalDataEntries
        )
    }
}

enum PIIPrivacyCategory {
    static let allCategoryKeys: [String] = [
        "email_addresses",
        "addresses",
        "phone_numbers",
        "credit_card_numbers",
        "iban_bank_account",
        "tax_id_vat",
        "crypto_wallets",
        "social_security_numbers",
        "passport_numbers",
        "api_keys",
        "jwt_tokens",
        "private_keys",
        "generic_secrets",
        "ip_addresses",
        "mac_addresses",
        "user_at_hostname",
        "home_folder",
        "vehicle_plate"
    ]
}

@MainActor
final class PIIPrivacySettingsStore: ObservableObject {
    static let shared = PIIPrivacySettingsStore()

    @Published private(set) var settings: PIIPrivacySettings = .enabled

    init(settings: PIIPrivacySettings = .enabled) {
        self.settings = settings
    }

    func update(_ settings: PIIPrivacySettings) {
        self.settings = settings
    }

    func detectionOptions() -> PIIDetectionOptions {
        settings.detectionOptions
    }
}

enum PIIType: String, CaseIterable, Sendable {
    case email = "EMAIL"
    case address = "ADDRESS"
    case phone = "PHONE"
    case awsAccessKey = "AWS_ACCESS_KEY"
    case awsSecretKey = "AWS_SECRET_KEY"
    case openAIKey = "OPENAI_KEY"
    case anthropicKey = "ANTHROPIC_KEY"
    case githubToken = "GITHUB_PAT"
    case stripeKey = "STRIPE_KEY"
    case googleAPIKey = "GOOGLE_API_KEY"
    case slackToken = "SLACK_TOKEN"
    case twilioKey = "TWILIO_KEY"
    case sendgridKey = "SENDGRID_KEY"
    case azureKey = "AZURE_KEY"
    case huggingFaceKey = "HUGGINGFACE_KEY"
    case databricksToken = "DATABRICKS_TOKEN"
    case firebaseKey = "FIREBASE_KEY"
    case genericSecret = "GENERIC_SECRET"
    case creditCard = "CREDIT_CARD"
    case ssn = "SSN"
    case ipv4 = "IPV4"
    case ipv6 = "IPV6"
    case privateKey = "PRIVATE_KEY"
    case jwt = "JWT"
    case iban = "IBAN"
    case homeFolder = "HOME_FOLDER"
    case userAtHostname = "USER_AT_HOSTNAME"
    case macAddress = "MAC_ADDRESS"
    case passport = "PASSPORT"
    case taxId = "TAX_ID"
    case vehiclePlate = "VEHICLE_PLATE"
    case cryptoWallet = "CRYPTO_WALLET"
}

enum PIIDetector {
    private struct Pattern: Sendable {
        let type: PIIType
        let expression: NSRegularExpression
        let validator: (@Sendable (String) -> Bool)?

        init(_ type: PIIType, _ pattern: String, options: NSRegularExpression.Options = [], validator: (@Sendable (String) -> Bool)? = nil) throws {
            self.type = type
            self.expression = try NSRegularExpression(pattern: pattern, options: options)
            self.validator = validator
        }
    }

    private static let patterns: [Pattern] = {
        do {
            return [
                try Pattern(.awsAccessKey, #"\bAKIA[0-9A-Z]{16}\b"#),
                try Pattern(.openAIKey, #"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,200}\b"#),
                try Pattern(.anthropicKey, #"\bsk-ant-api03-[A-Za-z0-9_-]{90,110}\b"#),
                try Pattern(.githubToken, #"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}|gho_[A-Za-z0-9]{36})\b"#),
                try Pattern(.stripeKey, #"\b[sr]k_(?:live|test)_[0-9a-zA-Z]{24,99}\b"#),
                try Pattern(.googleAPIKey, #"\bAIza[0-9A-Za-z\-_]{35}\b"#),
                try Pattern(.slackToken, #"\bxox[bpras]-[0-9a-zA-Z-]{10,250}\b"#),
                try Pattern(.awsSecretKey, #"(?:aws_secret|secret_key|secretkey|secret_access_key)['\":\s=]+([0-9a-zA-Z/+=]{40})\b"#, options: [.caseInsensitive]),
                try Pattern(.twilioKey, #"\b(?:AC[a-f0-9]{32}|SK[a-f0-9]{32})\b"#),
                try Pattern(.sendgridKey, #"\bSG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}\b"#),
                try Pattern(.azureKey, #"(?:azure|subscription|ocp-apim)[_-]?(?:key|secret|token)['\":\s=]+([0-9a-f]{32})\b"#, options: [.caseInsensitive]),
                try Pattern(.huggingFaceKey, #"\bhf_[a-zA-Z0-9]{34,}\b"#),
                try Pattern(.databricksToken, #"\bdapi[a-f0-9]{32,40}\b"#),
                try Pattern(.firebaseKey, #"\bAAAA[A-Za-z0-9_-]{100,200}\b"#),
                try Pattern(.genericSecret, #"(?:api[_-]?key|api[_-]?secret|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|private[_-]?key|password|passwd|credential|client[_-]?secret|app[_-]?secret|signing[_-]?key|encryption[_-]?key)['\":\s=]+['\"]?([A-Za-z0-9_\-/.+=]{8,200})['\"]?"#, options: [.caseInsensitive]),
                try Pattern(.privateKey, #"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"#),
                try Pattern(.jwt, #"\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+"#),
                try Pattern(.email, #"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"#, options: [.caseInsensitive]),
                try Pattern(.creditCard, #"\b(?:4[0-9]{3}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|5[1-5][0-9]{2}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|3[47][0-9]{2}[-\s]?[0-9]{6}[-\s]?[0-9]{5}|6(?:011|5[0-9]{2})[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4})\b"#, validator: luhnCheck),
                try Pattern(.ssn, #"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"#, validator: ssnCheck),
                try Pattern(.phone, #"(?:(?:\+|00)[1-9]\d{0,2}[-.\s/]?(?:\(?\d{1,5}\)?[-.\s/]?){1,4}\d{2,4})|(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}|(?:0\d[-.\s/]?(?:\(?\d{1,5}\)?[-.\s/]?){1,4}\d{2,4})"#, validator: phoneCheck),
                try Pattern(.ipv4, #"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"#, validator: publicIPv4Check),
                try Pattern(.ipv6, #"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"#),
                try Pattern(.iban, #"\b[A-Z]{2}\d{2}[\s]?[\dA-Z]{4}[\s]?(?:[\dA-Z]{4}[\s]?){1,7}[\dA-Z]{1,4}\b"#, validator: ibanCheck),
                try Pattern(.homeFolder, #"(?:/home/|/Users/|[A-Z]:\\Users\\)[a-zA-Z0-9_.-]{1,64}(?=[/\\]|\b)|PS [A-Z]:\\Users\\[a-zA-Z0-9_.-]{1,64}(?=[\\>]|\b)|PS /(?:home|Users)/[a-zA-Z0-9_.-]{1,64}(?=[/>]|\b)"#, validator: homeFolderCheck),
                try Pattern(.userAtHostname, #"\b[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,31}@[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}(?=[\s:~])"#, validator: userAtHostnameCheck),
                try Pattern(.macAddress, #"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"#, validator: macAddressCheck),
                try Pattern(.passport, #"(?:passport|reisepass|passeport|pass(?:port)?[\s._-]?(?:no|nr|num(?:ber)?|#))[:\s#=]*([A-Z0-9]{6,9})\b"#, options: [.caseInsensitive]),
                try Pattern(.taxId, #"\b(?:AT ?U\d{8}|BE ?0?\d{9,10}|BG ?\d{9,10}|HR ?\d{11}|CY ?\d{8}[A-Z]|CZ ?\d{8,10}|DK ?\d{8}|EE ?\d{9}|FI ?\d{8}|FR ?[0-9A-Z]{2}\d{9}|DE ?\d{9}|EL ?\d{9}|HU ?\d{8}|IE ?\d{7}[A-Z]{1,2}|IT ?\d{11}|LV ?\d{11}|LT ?\d{9,12}|LU ?\d{8}|MT ?\d{8}|NL ?\d{9}B\d{2}|PL ?\d{10}|PT ?\d{9}|RO ?\d{2,10}|SK ?\d{10}|SI ?\d{8}|ES ?[A-Z0-9]\d{7}[A-Z0-9]|SE ?\d{12}|GB ?\d{9}(?:\d{3})?)\b|(?:tax[\s_-]?(?:id|number|no|nr)|steuer(?:nummer|identifikationsnummer|nr|ident(?:nummer)?)|tin[\s_-]?(?:number|no|nr)|vat[\s_-]?(?:id|number|no|nr)|tax[\s_-]?identification(?:[\s_-]?number)?)[:\s#=]+([A-Z0-9\s/-]{5,20})"#, options: [.caseInsensitive]),
                try Pattern(.vehiclePlate, #"(?:license[\s_-]?plate|plate[\s_-]?(?:number|no|nr)|kennzeichen|nummernschild|kfz[\s_-]?kennzeichen|immatriculation|registration[\s_-]?(?:number|no|nr|plate)|vrm|numberplate)[:\s#=]*([A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,6})\b"#, options: [.caseInsensitive]),
                try Pattern(.cryptoWallet, #"\b(?:bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|0x[0-9a-fA-F]{40})\b"#)
            ]
        } catch {
            fatalError("Invalid PII detector regex: \(error)")
        }
    }()

    private static let typeToCategory: [PIIType: String] = [
        .email: "email_addresses",
        .address: "addresses",
        .phone: "phone_numbers",
        .creditCard: "credit_card_numbers",
        .ssn: "social_security_numbers",
        .iban: "iban_bank_account",
        .taxId: "tax_id_vat",
        .passport: "passport_numbers",
        .cryptoWallet: "crypto_wallets",
        .vehiclePlate: "vehicle_plate",
        .awsAccessKey: "api_keys",
        .awsSecretKey: "api_keys",
        .openAIKey: "api_keys",
        .anthropicKey: "api_keys",
        .githubToken: "api_keys",
        .stripeKey: "api_keys",
        .googleAPIKey: "api_keys",
        .slackToken: "api_keys",
        .twilioKey: "api_keys",
        .sendgridKey: "api_keys",
        .azureKey: "api_keys",
        .huggingFaceKey: "api_keys",
        .databricksToken: "api_keys",
        .firebaseKey: "api_keys",
        .genericSecret: "generic_secrets",
        .privateKey: "private_keys",
        .jwt: "jwt_tokens",
        .ipv4: "ip_addresses",
        .ipv6: "ip_addresses",
        .homeFolder: "home_folder",
        .userAtHostname: "user_at_hostname",
        .macAddress: "mac_addresses"
    ]

    static func detect(in text: String, options: PIIDetectionOptions = PIIDetectionOptions()) -> [PIIMatch] {
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        let urlExclusionRanges = regexMatches(#"https?://[^\s]+"#, in: text).map(\.range)
        var occupied: [NSRange] = []
        var counters: [PIIType: Int] = [:]
        var matches: [PIIMatch] = []

        for pattern in patterns {
            if let category = typeToCategory[pattern.type], options.disabledCategories.contains(category) {
                continue
            }
            pattern.expression.enumerateMatches(in: text, options: [], range: fullRange) { result, _, _ in
                guard let result else { return }
                let range = result.range(at: result.numberOfRanges > 1 && result.range(at: 1).location != NSNotFound ? 1 : 0)
                guard range.location != NSNotFound, range.length > 0 else { return }
                guard !urlExclusionRanges.contains(where: { NSIntersectionRange($0, range).length == range.length }) else { return }
                guard !occupied.contains(where: { NSIntersectionRange($0, range).length > 0 }) else { return }

                let value = nsText.substring(with: range)
                if let validator = pattern.validator, !validator(value) { return }
                let id = "pii-\(pattern.type.rawValue)-\(range.location)"
                guard !options.excludedIds.contains(id) else { return }

                let count = (counters[pattern.type] ?? 0) + 1
                counters[pattern.type] = count
                occupied.append(range)
                matches.append(
                    PIIMatch(
                        id: id,
                        type: pattern.type,
                        value: value,
                        range: range,
                        placeholder: placeholder(for: pattern.type, count: count, value: value)
                    )
                )
            }
        }

        appendPersonalDataMatches(
            text: text,
            nsText: nsText,
            entries: options.personalDataEntries,
            excludedIds: options.excludedIds,
            occupied: &occupied,
            matches: &matches
        )

        return matches.sorted { $0.range.location < $1.range.location }
    }

    static func redactionResult(
        in text: String,
        matches: [PIIMatch]? = nil,
        excludedIds: Set<String> = [],
        options: PIIDetectionOptions = PIIDetectionOptions()
    ) -> PIIRedactionResult {
        let effectiveOptions = PIIDetectionOptions(
            excludedIds: options.excludedIds.union(excludedIds),
            disabledCategories: options.disabledCategories,
            personalDataEntries: options.personalDataEntries
        )
        let allMatches = matches ?? detect(in: text, options: effectiveOptions)
        let redacted = redactedText(text, matches: allMatches, excludedIds: effectiveOptions.excludedIds)
        let mappingList = mappings(for: allMatches, excludedIds: effectiveOptions.excludedIds)
        return PIIRedactionResult(
            originalText: text,
            redactedText: redacted,
            matches: allMatches,
            mappings: mappingList
        )
    }

    static func redactedText(_ text: String, matches: [PIIMatch], excludedIds: Set<String>) -> String {
        let mutable = NSMutableString(string: text)
        for match in matches.sorted(by: { $0.range.location > $1.range.location }) where !excludedIds.contains(match.id) {
            mutable.replaceCharacters(in: match.range, with: match.placeholder)
        }
        return mutable as String
    }

    static func mappings(for matches: [PIIMatch], excludedIds: Set<String>) -> [PIIMapping] {
        matches
            .filter { !excludedIds.contains($0.id) }
            .map { PIIMapping(placeholder: $0.placeholder, original: $0.value, type: $0.type.rawValue) }
    }

    static func restorePII(in text: String, mappings: [PIIMapping]) -> String {
        guard !mappings.isEmpty else { return text }
        var restored = text
        for mapping in mappings.sorted(by: { $0.placeholder.count > $1.placeholder.count }) {
            restored = restored.replacingOccurrences(of: mapping.placeholder, with: mapping.original)
        }
        return restored
    }

    static func restorePII(in embed: EmbedRecord, mappings: [PIIMapping]) -> EmbedRecord {
        guard !mappings.isEmpty, var rawData = embed.rawData else { return embed }
        let restorableFields = ["content", "html", "code", "transcript", "summary", "title"]
        var changed = false

        for field in restorableFields {
            guard let current = rawData[field]?.value as? String else { continue }
            let restored = restorePII(in: current, mappings: mappings)
            guard restored != current else { continue }
            rawData[field] = AnyCodable(restored)
            changed = true
        }

        guard changed else { return embed }
        return EmbedRecord(
            id: embed.id,
            type: embed.type,
            status: embed.status,
            data: .raw(rawData),
            encryptedContent: embed.encryptedContent,
            encryptedType: embed.encryptedType,
            encryptedTextPreview: embed.encryptedTextPreview,
            parentEmbedId: embed.parentEmbedId,
            appId: embed.appId,
            skillId: embed.skillId,
            embedIds: embed.embedIds,
            hashedChatId: embed.hashedChatId,
            hashedUserId: embed.hashedUserId,
            versionNumber: embed.versionNumber,
            contentHash: embed.contentHash,
            versionHistory: embed.versionHistory,
            versionHistoryReadonly: embed.versionHistoryReadonly,
            createdAt: embed.createdAt
        )
    }

    static func summary(for matches: [PIIMatch]) -> String {
        let counts = Dictionary(grouping: matches, by: \.type).mapValues(\.count)
        return counts.keys.sorted { $0.rawValue < $1.rawValue }
            .map { "\(counts[$0] ?? 0) \($0.rawValue.lowercased().replacingOccurrences(of: "_", with: " "))" }
            .joined(separator: ", ")
    }

    static func placeholder(for type: PIIType, count: Int, value: String) -> String {
        switch type {
        case .awsAccessKey: return "[AWS_KEY_\(count)_\(suffix(value))]"
        case .awsSecretKey: return "[AWS_SECRET_\(count)_\(suffix(value))]"
        case .openAIKey: return "[OPENAI_KEY_\(count)_\(suffix(value))]"
        case .anthropicKey: return "[ANTHROPIC_KEY_\(count)_\(suffix(value))]"
        case .githubToken: return "[GITHUB_TOKEN_\(count)_\(suffix(value))]"
        case .stripeKey: return "[STRIPE_KEY_\(count)_\(suffix(value))]"
        case .googleAPIKey: return "[GOOGLE_KEY_\(count)_\(suffix(value))]"
        case .slackToken: return "[SLACK_TOKEN_\(count)_\(suffix(value))]"
        case .twilioKey: return "[TWILIO_KEY_\(count)_\(suffix(value))]"
        case .sendgridKey: return "[SENDGRID_KEY_\(count)_\(suffix(value))]"
        case .azureKey: return "[AZURE_KEY_\(count)_\(suffix(value))]"
        case .huggingFaceKey: return "[HF_TOKEN_\(count)_\(suffix(value))]"
        case .databricksToken: return "[DATABRICKS_TOKEN_\(count)_\(suffix(value))]"
        case .firebaseKey: return "[FIREBASE_KEY_\(count)_\(suffix(value))]"
        case .genericSecret: return "[SECRET_\(count)_\(suffix(value))]"
        case .privateKey: return "[PRIVATE_KEY_\(count)_\(suffix(value))]"
        case .jwt: return "[JWT_TOKEN_\(count)_\(suffix(value))]"
        case .email: return "[EMAIL_\(count)_\(suffix(value))]"
        case .creditCard: return "[CARD_\(count)_\(suffix(value))]"
        case .ssn: return "[SSN_\(count)_\(suffix(value))]"
        case .phone: return "[PHONE_\(count)_\(suffix(value))]"
        case .ipv4: return "[IP_\(count)_\(suffix(value))]"
        case .ipv6: return "[IPV6_\(count)_\(suffix(value))]"
        case .iban: return "[IBAN_\(count)_\(suffix(value))]"
        case .homeFolder: return "[HOME_PATH_\(count)_\(suffix(value))]"
        case .userAtHostname: return "[USER_HOST_\(count)_\(suffix(value))]"
        case .macAddress: return "[MAC_\(count)_\(suffix(value))]"
        case .passport: return "[PASSPORT_\(count)_\(suffix(value))]"
        case .taxId: return "[TAX_ID_\(count)_\(suffix(value))]"
        case .vehiclePlate: return "[PLATE_\(count)_\(suffix(value))]"
        case .cryptoWallet: return "[WALLET_\(count)_\(suffix(value))]"
        case .address: return "[ADDRESS_\(count)_\(suffix(value))]"
        }
    }

    private static func suffix(_ value: String) -> String {
        let cleaned = value.trimmingCharacters(in: CharacterSet(charactersIn: "'\"; \n\t"))
        return String(cleaned.suffix(3))
    }

    private static func appendPersonalDataMatches(
        text: String,
        nsText: NSString,
        entries: [PersonalDataForDetection],
        excludedIds: Set<String>,
        occupied: inout [NSRange],
        matches: inout [PIIMatch]
    ) {
        for entry in entries {
            let searchTexts = ([entry.textToHide] + entry.additionalTexts)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            for searchText in searchTexts {
                var start = text.startIndex
                while start < text.endIndex {
                    guard let stringRange = text.range(of: searchText, options: [.caseInsensitive], range: start..<text.endIndex) else { break }
                    let range = NSRange(stringRange, in: text)
                    let id = "pii-PERSONAL_DATA-\(entry.id)-\(range.location)"
                    if !excludedIds.contains(id), !occupied.contains(where: { NSIntersectionRange($0, range).length > 0 }) {
                        let placeholder = entry.replaceWith.hasPrefix("[") ? entry.replaceWith : "[\(entry.replaceWith)]"
                        matches.append(
                            PIIMatch(
                                id: id,
                                type: entry.type ?? .email,
                                value: nsText.substring(with: range),
                                range: range,
                                placeholder: placeholder
                            )
                        )
                        occupied.append(range)
                    }
                    start = stringRange.upperBound
                }
            }
        }
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

    private static func regexMatches(_ pattern: String, in text: String) -> [NSTextCheckingResult] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        return regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
    }

    private static func matches(_ pattern: String, _ text: String) -> Bool {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return false }
        return regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
    }
}

enum PrivacyFilterSpanSource: String, Sendable {
    case regex
    case model
}

enum PrivacyFilterModelLabel: String, CaseIterable, Sendable {
    case accountNumber = "account_number"
    case privateAddress = "private_address"
    case privateDate = "private_date"
    case privateEmail = "private_email"
    case privatePerson = "private_person"
    case privatePhone = "private_phone"
    case privateURL = "private_url"
    case secret

    var categoryKeys: Set<String> {
        switch self {
        case .privateEmail:
            return ["email_addresses"]
        case .privatePhone:
            return ["phone_numbers"]
        case .privateAddress:
            return ["addresses"]
        case .accountNumber:
            return ["credit_card_numbers", "iban_bank_account"]
        case .secret, .privateDate, .privatePerson, .privateURL:
            return ["generic_secrets"]
        }
    }

    var piiType: PIIType {
        switch self {
        case .privateEmail:
            return .email
        case .privatePhone:
            return .phone
        case .privateAddress:
            return .address
        case .accountNumber, .secret, .privateDate, .privatePerson, .privateURL:
            return .genericSecret
        }
    }
}

struct PrivacyFilterModelSpan: Equatable, Sendable {
    let label: PrivacyFilterModelLabel
    let range: NSRange
    let score: Double
}

struct PrivacyFilterTokenPrediction: Equatable, Sendable {
    let label: String
    let range: NSRange
    let score: Double
}

enum PrivacyFilterTokenSpanDecoder {
    static func decode(_ predictions: [PrivacyFilterTokenPrediction], in text: String) -> [PrivacyFilterModelSpan] {
        let nsText = text as NSString
        var spans: [PrivacyFilterModelSpan] = []
        var currentLabel: PrivacyFilterModelLabel?
        var currentRange: NSRange?
        var currentScores: [Double] = []

        func flushCurrent() {
            guard let label = currentLabel, let range = currentRange, !currentScores.isEmpty else { return }
            let score = currentScores.reduce(0, +) / Double(currentScores.count)
            spans.append(PrivacyFilterModelSpan(label: label, range: range, score: score))
            currentLabel = nil
            currentRange = nil
            currentScores = []
        }

        func appendCurrent(label: PrivacyFilterModelLabel, range: NSRange, score: Double) {
            if currentLabel == label, let existing = currentRange {
                currentRange = NSUnionRange(existing, range)
                currentScores.append(score)
            } else {
                flushCurrent()
                currentLabel = label
                currentRange = range
                currentScores = [score]
            }
        }

        for prediction in predictions.sorted(by: { $0.range.location < $1.range.location }) {
            guard prediction.range.location >= 0,
                  prediction.range.length > 0,
                  NSMaxRange(prediction.range) <= nsText.length else {
                continue
            }
            guard let decoded = decodeLabel(prediction.label) else {
                flushCurrent()
                continue
            }

            switch decoded.prefix {
            case "S":
                flushCurrent()
                spans.append(PrivacyFilterModelSpan(label: decoded.label, range: prediction.range, score: prediction.score))
            case "B":
                flushCurrent()
                currentLabel = decoded.label
                currentRange = prediction.range
                currentScores = [prediction.score]
            case "I":
                appendCurrent(label: decoded.label, range: prediction.range, score: prediction.score)
            case "E":
                appendCurrent(label: decoded.label, range: prediction.range, score: prediction.score)
                flushCurrent()
            default:
                flushCurrent()
                spans.append(PrivacyFilterModelSpan(label: decoded.label, range: prediction.range, score: prediction.score))
            }
        }
        flushCurrent()
        return spans.sorted { $0.range.location < $1.range.location }
    }

    private static func decodeLabel(_ rawLabel: String) -> (prefix: String?, label: PrivacyFilterModelLabel)? {
        guard rawLabel != "O" else { return nil }
        let parts = rawLabel.split(separator: "-", maxSplits: 1).map(String.init)
        if parts.count == 2, ["B", "I", "E", "S"].contains(parts[0]) {
            guard let label = PrivacyFilterModelLabel(rawValue: parts[1]) else { return nil }
            return (prefix: parts[0], label: label)
        }
        guard let label = PrivacyFilterModelLabel(rawValue: rawLabel) else { return nil }
        return (prefix: nil, label: label)
    }
}

struct PrivacyFilterMergedSpan: Equatable, Sendable {
    let source: PrivacyFilterSpanSource
    let label: String
    let range: NSRange
    let score: Double?
}

protocol PrivacyFilterModelRunning: Sendable {
    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan]
}

struct PrivacyFilterNativeDetector: Sendable {
    static let defaultMinimumScore = 0.5

    let runner: any PrivacyFilterModelRunning
    let minimumScore: Double

    init(runner: any PrivacyFilterModelRunning, minimumScore: Double = defaultMinimumScore) {
        self.runner = runner
        self.minimumScore = minimumScore
    }

    func detectModelSpans(
        in text: String,
        options: PIIDetectionOptions = PIIDetectionOptions()
    ) async throws -> [PrivacyFilterModelSpan] {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return [] }
        let nsText = text as NSString
        return try await runner.detectedSpans(in: text)
            .filter { span in
                span.score >= minimumScore
                    && span.range.location >= 0
                    && span.range.length > 0
                    && NSMaxRange(span.range) <= nsText.length
                    && options.disabledCategories.isDisjoint(with: span.label.categoryKeys)
            }
            .sorted { $0.range.location < $1.range.location }
    }

    func mergedSpans(
        in text: String,
        regexMatches: [PIIMatch],
        options: PIIDetectionOptions = PIIDetectionOptions()
    ) async throws -> [PrivacyFilterMergedSpan] {
        let modelSpans = try await detectModelSpans(in: text, options: options)
        return PrivacyFilterSpanMerger.merge(regexMatches: regexMatches, modelSpans: modelSpans)
    }

    func detectedMatches(
        in text: String,
        options: PIIDetectionOptions = PIIDetectionOptions()
    ) async throws -> [PIIMatch] {
        let regexMatches = PIIDetector.detect(in: text, options: options)
        let modelSpans = try await detectModelSpans(in: text, options: options)
        return PrivacyFilterSpanMerger.mergeMatches(
            text: text,
            regexMatches: regexMatches,
            modelSpans: modelSpans,
            excludedIds: options.excludedIds
        )
    }
}

enum PrivacyFilterSpanMerger {
    static func merge(regexMatches: [PIIMatch], modelSpans: [PrivacyFilterModelSpan]) -> [PrivacyFilterMergedSpan] {
        var merged = regexMatches.map { match in
            PrivacyFilterMergedSpan(
                source: .regex,
                label: match.type.rawValue,
                range: match.range,
                score: nil
            )
        }
        for span in selectedModelSpans(regexMatches: regexMatches, modelSpans: modelSpans) {
            merged.append(
                PrivacyFilterMergedSpan(
                    source: .model,
                    label: span.label.rawValue,
                    range: span.range,
                    score: span.score
                )
            )
        }
        return merged.sorted { $0.range.location < $1.range.location }
    }

    static func mergeMatches(
        text: String,
        regexMatches: [PIIMatch],
        modelSpans: [PrivacyFilterModelSpan],
        excludedIds: Set<String>
    ) -> [PIIMatch] {
        let nsText = text as NSString
        var counters = Dictionary(grouping: regexMatches, by: \.type).mapValues(\.count)
        var matches = regexMatches

        for span in selectedModelSpans(regexMatches: regexMatches, modelSpans: modelSpans) {
            let type = span.label.piiType
            let id = "pii-model-\(span.label.rawValue)-\(span.range.location)"
            guard !excludedIds.contains(id) else { continue }
            let value = nsText.substring(with: span.range)
            let count = (counters[type] ?? 0) + 1
            counters[type] = count
            matches.append(
                PIIMatch(
                    id: id,
                    type: type,
                    value: value,
                    range: span.range,
                    placeholder: PIIDetector.placeholder(for: type, count: count, value: value)
                )
            )
        }

        return matches.sorted { $0.range.location < $1.range.location }
    }

    private static func selectedModelSpans(
        regexMatches: [PIIMatch],
        modelSpans: [PrivacyFilterModelSpan]
    ) -> [PrivacyFilterModelSpan] {
        var occupied = regexMatches.map(\.range)
        var selected: [PrivacyFilterModelSpan] = []
        let ranked = modelSpans.sorted {
            if $0.score != $1.score { return $0.score > $1.score }
            if $0.range.length != $1.range.length { return $0.range.length > $1.range.length }
            return $0.range.location < $1.range.location
        }

        for span in ranked where !occupied.contains(where: { NSIntersectionRange($0, span.range).length > 0 }) {
            selected.append(span)
            occupied.append(span.range)
        }
        return selected.sorted { $0.range.location < $1.range.location }
    }
}

enum EnhancedPIIModelConfiguration {
    // Set this once the OpenMates-hosted artifact URL, SHA-256, and size are finalized.
    static let productionManifest: EnhancedPIIModelManifest? = nil
}

struct EnhancedPIIModelManifest: Equatable, Sendable {
    let version: String
    let sizeBytes: Int
    let remoteURL: URL
    let sha256: String
}

enum EnhancedPIIModelFailureReason: String, Equatable, Sendable {
    case modelNotConfigured = "model_not_configured"
    case downloadFailed = "download_failed"
    case removalFailed = "removal_failed"
    case timeout
    case runtimeFailed = "runtime_failed"
}

enum EnhancedPIIModelStatus: Equatable, Sendable {
    case notDownloaded
    case downloading(progress: Double)
    case ready(version: String, sizeBytes: Int)
    case failed(reason: EnhancedPIIModelFailureReason)
    case updateAvailable(currentVersion: String, newVersion: String, sizeBytes: Int)
    case removing

    var isReady: Bool {
        if case .ready = self { return true }
        return false
    }

    var canRecommendDownload: Bool {
        switch self {
        case .notDownloaded, .failed, .updateAvailable:
            return true
        case .downloading, .ready, .removing:
            return false
        }
    }
}

protocol EnhancedPIIModelDownloading: Sendable {
    func download(_ manifest: EnhancedPIIModelManifest, progress: (Double) async -> Void) async throws -> URL
}

struct URLSessionEnhancedPIIModelDownloader: EnhancedPIIModelDownloading {
    enum DownloadError: Error {
        case checksumMismatch
    }

    func download(_ manifest: EnhancedPIIModelManifest, progress: (Double) async -> Void) async throws -> URL {
        await progress(0.05)
        let (temporaryURL, _) = try await URLSession.shared.download(from: manifest.remoteURL)
        await progress(0.85)
        let digest = try sha256Hex(for: temporaryURL)
        guard digest.caseInsensitiveCompare(manifest.sha256) == .orderedSame else {
            throw DownloadError.checksumMismatch
        }

        let directory = try modelDirectory()
        let targetURL = directory.appendingPathComponent("privacy-filter-\(manifest.version).onnx")
        try removeExistingModelArtifacts(in: directory, excluding: targetURL)
        if FileManager.default.fileExists(atPath: targetURL.path) {
            try FileManager.default.removeItem(at: targetURL)
        }
        try FileManager.default.moveItem(at: temporaryURL, to: targetURL)
        await progress(1.0)
        return targetURL
    }

    private func modelDirectory() throws -> URL {
        let appSupport = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = appSupport.appendingPathComponent("EnhancedPIIModel", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func removeExistingModelArtifacts(in directory: URL, excluding targetURL: URL) throws {
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        for file in files where file.lastPathComponent.hasPrefix("privacy-filter-") && file != targetURL {
            try FileManager.default.removeItem(at: file)
        }
    }

    private func sha256Hex(for url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let data = try handle.read(upToCount: 1024 * 1024) ?? Data()
            guard !data.isEmpty else { break }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

typealias EnhancedPIIModelRunnerFactory = @Sendable (URL) -> (any PrivacyFilterModelRunning)?

@MainActor
final class EnhancedPIIModelDownloadController: ObservableObject {
    static let shared = EnhancedPIIModelDownloadController(
        manifest: EnhancedPIIModelConfiguration.productionManifest,
        downloader: URLSessionEnhancedPIIModelDownloader(),
        defaults: .standard
    )

    @Published private(set) var status: EnhancedPIIModelStatus = .notDownloaded

    private let manifest: EnhancedPIIModelManifest?
    private let downloader: any EnhancedPIIModelDownloading
    private let defaults: UserDefaults?
    private let runnerFactory: EnhancedPIIModelRunnerFactory?
    private var artifactURL: URL?

    init(
        manifest: EnhancedPIIModelManifest?,
        downloader: any EnhancedPIIModelDownloading,
        defaults: UserDefaults? = nil,
        runnerFactory: EnhancedPIIModelRunnerFactory? = nil
    ) {
        self.manifest = manifest
        self.downloader = downloader
        self.defaults = defaults
        self.runnerFactory = runnerFactory
        if let defaults,
           let version = defaults.string(forKey: Self.versionKey),
           let path = defaults.string(forKey: Self.pathKey) {
            let sizeBytes = defaults.integer(forKey: Self.sizeKey)
            let url = URL(fileURLWithPath: path)
            if FileManager.default.fileExists(atPath: url.path) {
                self.artifactURL = url
                self.status = .ready(version: version, sizeBytes: sizeBytes)
            }
        }
    }

    var isDownloadConfigured: Bool { manifest != nil }

    var modelDetector: PrivacyFilterNativeDetector? {
        guard case .ready = status,
              let artifactURL,
              let runner = runnerFactory?(artifactURL) else { return nil }
        return PrivacyFilterNativeDetector(runner: runner)
    }

    var sizeCopy: String {
        guard let sizeBytes = manifest?.sizeBytes ?? status.sizeBytes else { return "" }
        return Self.sizeCopy(for: sizeBytes)
    }

    static func sizeCopy(for sizeBytes: Int) -> String {
        String(format: "%.2f MB", Double(sizeBytes) / 1_048_576)
    }

    var statusCopy: String {
        switch status {
        case .notDownloaded:
            return "\(AppStrings.enhancedPIIModelStatusNotDownloaded) \(AppStrings.enhancedPIIModelDescription)"
        case .downloading:
            return AppStrings.enhancedPIIModelDownloading
        case .ready:
            return AppStrings.enhancedPIIModelStatusLocalReady
        case .failed:
            return AppStrings.enhancedPIIModelFailed
        case .updateAvailable:
            return AppStrings.enhancedPIIModelUpdateAvailable
        case .removing:
            return AppStrings.enhancedPIIModelRemove
        }
    }

    var actionTitle: String {
        switch status {
        case .ready, .removing:
            return AppStrings.enhancedPIIModelRemove
        case .failed:
            return AppStrings.retry
        case .downloading:
            return AppStrings.enhancedPIIModelDownloading
        case .notDownloaded, .updateAvailable:
            return AppStrings.enhancedPIIModelDownload
        }
    }

    var isActionDisabled: Bool {
        switch status {
        case .downloading, .removing:
            return true
        case .notDownloaded, .failed, .updateAvailable:
            return !isDownloadConfigured
        case .ready:
            return false
        }
    }

    func performPrimaryAction() async {
        switch status {
        case .ready:
            await remove()
        case .notDownloaded, .failed, .updateAvailable:
            await download()
        case .downloading, .removing:
            break
        }
    }

    func download() async {
        guard let manifest else {
            status = .failed(reason: .modelNotConfigured)
            return
        }
        status = .downloading(progress: 0)
        do {
            let url = try await downloader.download(manifest) { [weak self] progress in
                await MainActor.run {
                    self?.status = .downloading(progress: min(max(progress, 0), 1))
                }
            }
            artifactURL = url
            persistReady(version: manifest.version, sizeBytes: manifest.sizeBytes, url: url)
            status = .ready(version: manifest.version, sizeBytes: manifest.sizeBytes)
        } catch {
            status = .failed(reason: .downloadFailed)
        }
    }

    func markUpdateAvailable(version: String, sizeBytes: Int) {
        let currentVersion: String
        switch status {
        case .ready(let version, _):
            currentVersion = version
        case .updateAvailable(let version, _, _):
            currentVersion = version
        default:
            currentVersion = manifest?.version ?? "unknown"
        }
        status = .updateAvailable(currentVersion: currentVersion, newVersion: version, sizeBytes: sizeBytes)
    }

    func remove() async {
        status = .removing
        if let artifactURL, FileManager.default.fileExists(atPath: artifactURL.path) {
            do {
                try FileManager.default.removeItem(at: artifactURL)
            } catch {
                status = .failed(reason: .removalFailed)
                return
            }
        }
        self.artifactURL = nil
        clearPersistedReadyState()
        status = .notDownloaded
    }

    private func persistReady(version: String, sizeBytes: Int, url: URL) {
        defaults?.set(version, forKey: Self.versionKey)
        defaults?.set(sizeBytes, forKey: Self.sizeKey)
        defaults?.set(url.path, forKey: Self.pathKey)
    }

    private func clearPersistedReadyState() {
        defaults?.removeObject(forKey: Self.versionKey)
        defaults?.removeObject(forKey: Self.sizeKey)
        defaults?.removeObject(forKey: Self.pathKey)
    }

    private static let versionKey = "enhanced_pii_model.version"
    private static let sizeKey = "enhanced_pii_model.size_bytes"
    private static let pathKey = "enhanced_pii_model.path"
}

struct EnhancedPIIRecommendationPolicy: Equatable, Sendable {
    static let defaultDismissalBackoff: TimeInterval = 30 * 24 * 60 * 60

    var dismissedAt: Date?
    var dismissalBackoff: TimeInterval = defaultDismissalBackoff

    func shouldRecommend(regexMatches: [PIIMatch], modelStatus: EnhancedPIIModelStatus, now: Date = Date()) -> Bool {
        guard !regexMatches.isEmpty, modelStatus.canRecommendDownload else { return false }
        guard let dismissedAt else { return true }
        return now.timeIntervalSince(dismissedAt) >= dismissalBackoff
    }

    mutating func dismiss(now: Date = Date()) {
        dismissedAt = now
    }
}

@MainActor
final class EnhancedPIIRecommendationStore: ObservableObject {
    static let shared = EnhancedPIIRecommendationStore(defaults: .standard)

    @Published private(set) var policy: EnhancedPIIRecommendationPolicy

    private let defaults: UserDefaults
    private static let dismissedAtKey = "enhanced_pii_model.recommendation_dismissed_at"

    init(defaults: UserDefaults) {
        self.defaults = defaults
        let timestamp = defaults.double(forKey: Self.dismissedAtKey)
        self.policy = EnhancedPIIRecommendationPolicy(
            dismissedAt: timestamp > 0 ? Date(timeIntervalSince1970: timestamp) : nil
        )
    }

    func shouldRecommend(regexMatches: [PIIMatch], modelStatus: EnhancedPIIModelStatus, now: Date = Date()) -> Bool {
        policy.shouldRecommend(regexMatches: regexMatches, modelStatus: modelStatus, now: now)
    }

    func dismiss(now: Date = Date()) {
        policy.dismiss(now: now)
        defaults.set(now.timeIntervalSince1970, forKey: Self.dismissedAtKey)
    }
}

enum EnhancedPIIDetectionMode: Equatable, Sendable {
    case regexOnly
    case enhanced
    case regexFallback(reason: EnhancedPIIModelFailureReason)
}

struct EnhancedPIIDetectionResult: Equatable, Sendable {
    let matches: [PIIMatch]
    let mode: EnhancedPIIDetectionMode

    var sanitizedStatus: String {
        switch mode {
        case .regexOnly:
            return "mode=regex_only matches=\(matches.count)"
        case .enhanced:
            return "mode=enhanced matches=\(matches.count)"
        case .regexFallback(let reason):
            return "mode=regex_fallback reason=\(reason.rawValue) matches=\(matches.count)"
        }
    }
}

struct EnhancedPIIDetector: Sendable {
    static let defaultModelTimeoutNanoseconds: UInt64 = 250_000_000

    let modelDetector: PrivacyFilterNativeDetector?
    let modelTimeoutNanoseconds: UInt64

    init(
        modelDetector: PrivacyFilterNativeDetector?,
        modelTimeoutNanoseconds: UInt64 = defaultModelTimeoutNanoseconds
    ) {
        self.modelDetector = modelDetector
        self.modelTimeoutNanoseconds = modelTimeoutNanoseconds
    }

    func detect(in text: String, options: PIIDetectionOptions = PIIDetectionOptions()) async -> EnhancedPIIDetectionResult {
        let regexMatches = PIIDetector.detect(in: text, options: options)
        guard let modelDetector else {
            return EnhancedPIIDetectionResult(matches: regexMatches, mode: .regexOnly)
        }

        do {
            guard let matches = try await withModelTimeout({
                try await modelDetector.detectedMatches(in: text, options: options)
            }) else {
                return EnhancedPIIDetectionResult(matches: regexMatches, mode: .regexFallback(reason: .timeout))
            }
            return EnhancedPIIDetectionResult(matches: matches, mode: .enhanced)
        } catch {
            return EnhancedPIIDetectionResult(matches: regexMatches, mode: .regexFallback(reason: .runtimeFailed))
        }
    }

    private func withModelTimeout(_ operation: @escaping @Sendable () async throws -> [PIIMatch]) async throws -> [PIIMatch]? {
        try await withThrowingTaskGroup(of: [PIIMatch]?.self) { group in
            group.addTask { try await operation() }
            group.addTask {
                try await Task.sleep(nanoseconds: modelTimeoutNanoseconds)
                return nil
            }
            let result = try await group.next() ?? nil
            group.cancelAll()
            return result
        }
    }
}

private extension EnhancedPIIModelStatus {
    var sizeBytes: Int? {
        switch self {
        case .ready(_, let sizeBytes), .updateAvailable(_, _, let sizeBytes):
            return sizeBytes
        case .notDownloaded, .downloading, .failed, .removing:
            return nil
        }
    }
}

struct PIIWarningBanner: View {
    let matches: [PIIMatch]
    let onUndoAll: () -> Void

    var body: some View {
        if !matches.isEmpty {
            HStack(spacing: .spacing5) {
                Icon("shield", size: 20)
                    .foregroundStyle(Color.warning)
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(AppStrings.piiBannerTitle)
                        .font(.omXs.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                    Text(AppStrings.piiBannerDescription(summary: PIIDetector.summary(for: matches)))
                        .font(.omTiny)
                        .foregroundStyle(Color.grey60)
                }

                Spacer()

                Button(action: onUndoAll) {
                    Text(AppStrings.piiUndoAllShort)
                        .font(.omTiny.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing3)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius2))
                        .overlay(
                            RoundedRectangle(cornerRadius: .radius2)
                                .stroke(Color.grey30, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.piiUndoAll)
                .accessibilityIdentifier("pii-undo-all")
            }
            .padding(.vertical, .spacing4)
            .padding(.horizontal, .spacing6)
            .background(Color.warning.opacity(0.1))
            .overlay(
                RoundedRectangle(cornerRadius: .radius3)
                    .stroke(Color.warning.opacity(0.3), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("pii-warning-banner")
        }
    }
}

struct EnhancedPIIModelSuggestionBanner: View {
    let onDownload: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: .spacing5) {
            Icon("shield", size: 20)
                .foregroundStyle(Color.buttonPrimary)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(AppStrings.enhancedPIIModelComposerSuggestionTitle)
                    .font(.omXs.weight(.semibold))
                    .foregroundStyle(Color.fontPrimary)
                Text(AppStrings.enhancedPIIModelComposerSuggestionDescription)
                    .font(.omTiny)
                    .foregroundStyle(Color.grey60)
            }

            Spacer(minLength: .spacing4)

            Button(action: onDownload) {
                Text(AppStrings.enhancedPIIModelDownload)
                    .font(.omTiny.weight(.semibold))
                    .foregroundStyle(Color.fontButton)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing3)
                    .background(Color.buttonPrimary)
                    .clipShape(RoundedRectangle(cornerRadius: .radius2))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("enhanced-pii-model-download")

            OMIconButton(icon: "close", label: AppStrings.close, size: 28, iconSize: 14, action: onDismiss)
                .accessibilityIdentifier("enhanced-pii-model-dismiss")
        }
        .padding(.vertical, .spacing4)
        .padding(.horizontal, .spacing6)
        .background(Color.grey10)
        .overlay(
            RoundedRectangle(cornerRadius: .radius3)
                .stroke(Color.grey30, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("enhanced-pii-model-suggestion")
    }
}

struct PIIHighlightStrip: View {
    let matches: [PIIMatch]
    let onExclude: (PIIMatch) -> Void

    var body: some View {
        if !matches.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    ForEach(matches) { match in
                        Button {
                            onExclude(match)
                        } label: {
                            Text(match.value)
                                .font(.omTiny.weight(.semibold))
                                .lineLimit(1)
                                .foregroundStyle(Color.fontPrimary)
                                .padding(.horizontal, .spacing5)
                                .padding(.vertical, .spacing3)
                                .background(Color.warning.opacity(0.22))
                                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                                .overlay(
                                    RoundedRectangle(cornerRadius: .radiusFull)
                                        .stroke(Color.warning.opacity(0.45), lineWidth: 1)
                                )
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(match.value)
                        .accessibilityValue(match.type.rawValue)
                        .accessibilityHint(AppStrings.piiUndoAllShort)
                        .accessibilityIdentifier("pii-highlight-\(match.type.rawValue)")
                    }
                }
                .padding(.horizontal, .spacing2)
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("pii-highlights")
        }
    }
}
