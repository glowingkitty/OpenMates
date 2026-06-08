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
    case phone = "PHONE"
    case openAIKey = "OPENAI_KEY"
    case githubToken = "GITHUB_TOKEN"
    case genericSecret = "SECRET"
    case creditCard = "CREDIT_CARD"
    case ipAddress = "IP_ADDRESS"
    case privateKey = "PRIVATE_KEY"
    case jwt = "JWT"
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
                try Pattern(.privateKey, #"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"#),
                try Pattern(.openAIKey, #"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,200}\b"#),
                try Pattern(.githubToken, #"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}|gho_[A-Za-z0-9]{36})\b"#),
                try Pattern(.jwt, #"\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\b"#),
                try Pattern(.genericSecret, #"(?:api[_-]?key|api[_-]?secret|secret[_-]?key|auth[_-]?token|access[_-]?token|password|passwd|credential|client[_-]?secret)['\":\s=]+['\"]?([A-Za-z0-9_\-/.+=]{8,200})['\"]?"#, options: [.caseInsensitive]),
                try Pattern(.creditCard, #"\b(?:\d[ -]*?){13,19}\b"#, validator: luhnCheck),
                try Pattern(.email, #"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"#, options: [.caseInsensitive]),
                try Pattern(.ipAddress, #"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"#),
                try Pattern(.phone, #"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}(?!\w)"#)
            ]
        } catch {
            fatalError("Invalid PII detector regex: \(error)")
        }
    }()

    static func detect(in text: String) -> [PIIMatch] {
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        var occupied: [NSRange] = []
        var counters: [PIIType: Int] = [:]
        var matches: [PIIMatch] = []

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

    static func summary(for matches: [PIIMatch]) -> String {
        let counts = Dictionary(grouping: matches, by: \.type).mapValues(\.count)
        return counts.keys.sorted { $0.rawValue < $1.rawValue }
            .map { "\(counts[$0] ?? 0) \($0.rawValue.lowercased().replacingOccurrences(of: "_", with: " "))" }
            .joined(separator: ", ")
    }

    private static func placeholder(for type: PIIType, count: Int, value: String) -> String {
        switch type {
        case .openAIKey, .githubToken, .genericSecret:
            return "[\(type.rawValue)_\(count)_\(suffix(value))]"
        case .ipAddress:
            return "[IP_\(count)]"
        default:
            return "[\(type.rawValue)_\(count)]"
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
