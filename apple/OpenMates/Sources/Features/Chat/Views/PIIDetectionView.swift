// PII detection UI — warns user about personal data in messages.
// Shows detected PII count with option to exclude individual entries.
// Replaces PII with placeholders like [EMAIL_1], [PHONE_1] on send.

import SwiftUI

struct PIIMatch: Identifiable, Equatable {
    let id: String
    let type: PIIType
    let value: String
    let range: NSRange
    let placeholder: String
}

enum PIIType: String, CaseIterable {
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

    static func detect(in text: String) -> [PIIMatch] {
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        let urlExclusionRanges = regexMatches(#"https?://[^\s]+"#, in: text).map(\.range)
        var occupied: [NSRange] = []
        var counters: [PIIType: Int] = [:]
        var matches: [PIIMatch] = []

        for pattern in patterns {
            pattern.expression.enumerateMatches(in: text, options: [], range: fullRange) { result, _, _ in
                guard let result else { return }
                let range = result.range(at: result.numberOfRanges > 1 && result.range(at: 1).location != NSNotFound ? 1 : 0)
                guard range.location != NSNotFound, range.length > 0 else { return }
                guard !urlExclusionRanges.contains(where: { NSIntersectionRange($0, range).length == range.length }) else { return }
                guard !occupied.contains(where: { NSIntersectionRange($0, range).length > 0 }) else { return }

                let value = nsText.substring(with: range)
                if let validator = pattern.validator, !validator(value) { return }

                let count = (counters[pattern.type] ?? 0) + 1
                counters[pattern.type] = count
                occupied.append(range)
                matches.append(
                    PIIMatch(
                        id: "pii-\(pattern.type.rawValue)-\(range.location)",
                        type: pattern.type,
                        value: value,
                        range: range,
                        placeholder: placeholder(for: pattern.type, count: count, value: value)
                    )
                )
            }
        }

        return matches.sorted { $0.range.location < $1.range.location }
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

    static func summary(for matches: [PIIMatch]) -> String {
        let counts = Dictionary(grouping: matches, by: \.type).mapValues(\.count)
        return counts.keys.sorted { $0.rawValue < $1.rawValue }
            .map { "\(counts[$0] ?? 0) \($0.rawValue.lowercased().replacingOccurrences(of: "_", with: " "))" }
            .joined(separator: ", ")
    }

    private static func placeholder(for type: PIIType, count: Int, value: String) -> String {
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
            }
            .padding(.vertical, .spacing4)
            .padding(.horizontal, .spacing6)
            .background(Color.warning.opacity(0.1))
            .overlay(
                RoundedRectangle(cornerRadius: .radius3)
                    .stroke(Color.warning.opacity(0.3), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
        }
    }
}
