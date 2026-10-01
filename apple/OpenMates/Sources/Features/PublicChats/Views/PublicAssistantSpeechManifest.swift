import Foundation

// Web: demo_chats/types.ts, exampleChatStore.ts, assistantSpeechController.ts.
// Reads reviewed static metadata without executing bundled TypeScript.
// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
struct PublicAssistantSpeechSegment: Codable, Equatable {
    let segmentId: String
    let sequence: Int
    let publicUrl: String
    let sha256: String
    let durationSeconds: Double
    var waveform: [Double]? = nil
    var valid: Bool {
        !segmentId.isEmpty && sequence >= 0 && durationSeconds.isFinite && durationSeconds >= 0 &&
        sha256.count == 64 && sha256.allSatisfy { $0.isHexDigit } && Self.url(publicUrl) != nil
    }
    static func url(_ value: String, origin: URL = ServerProfile.current().webBaseURL) -> URL? {
        let value = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, !value.contains(where: { $0.isNewline || $0.asciiValue.map { $0 < 32 } == true }),
              let url = URL(string: value, relativeTo: origin)?.absoluteURL,
              url.scheme == "https", url.host != nil, url.user == nil, url.password == nil else { return nil }
        return url
    }
}

@MainActor
enum PublicAssistantSpeechManifest {
    struct MessageIdentity: Equatable {
        let id: String
        let role: String
        let contentKey: String
    }
    struct Document {
        let chatID: String
        let speech: [String: [PublicAssistantSpeechSegment]]
        let identities: [MessageIdentity]
        func originalID(contentKey: String, role: String) -> String? {
            let matches = identities.filter { $0.contentKey == contentKey && $0.role == role }
            return matches.count == 1 ? matches[0].id : nil
        }
        func segments(messageID: String) -> [PublicAssistantSpeechSegment] {
            guard let rows = speech[messageID], !rows.isEmpty, rows.allSatisfy(\.valid),
                  Set(rows.map(\.segmentId)).count == rows.count,
                  Set(rows.map(\.sequence)).count == rows.count else { return [] }
            return rows.sorted { $0.sequence < $1.sequence }
        }
    }
    private static var documents: [String: Document] = [:]
    private static var missing = Set<String>()
    private static var aliases: [String: [String: String]] = [:]
    static func registerMessage(chatID: String, nativeID: String, contentKey: String, role: String) {
        guard let original = document(chatID)?.originalID(contentKey: contentKey, role: role) else { return }
        aliases[chatID, default: [:]][nativeID] = original
    }
    static func segments(chatID: String, nativeMessageID: String) -> [PublicAssistantSpeechSegment] {
        guard let document = document(chatID) else { return [] }
        return document.segments(messageID: aliases[chatID]?[nativeMessageID] ?? nativeMessageID)
    }
    static func document(_ chatID: String) -> Document? {
        if let cached = documents[chatID] { return cached }
        guard !missing.contains(chatID) else { return nil }
        let names: [String: String] = [
            "example-gigantic-airplanes": "gigantic-airplanes",
            "example-artemis-ii-mission": "artemis-ii-mission",
            "example-beautiful-single-page-html": "beautiful-single-page-html",
            "example-eu-chat-control-law": "eu-chat-control-law-criticisms",
            "example-flights-berlin-bangkok": "flights-berlin-to-bangkok",
            "example-creativity-drawing-meetups-berlin": "creativity-drawing-meetups-berlin"
        ]
        let name = names[chatID] ?? String(chatID.dropFirst("example-".count))
        guard chatID.hasPrefix("example-"), !name.contains("/"),
              let url = Bundle.main.url(forResource: name, withExtension: "ts", subdirectory: "example_chats")
                ?? Bundle.main.url(forResource: name, withExtension: "ts"),
              let source = try? String(contentsOf: url, encoding: .utf8),
              let parsed = parse(source), parsed.chatID == chatID else { missing.insert(chatID); return nil }
        documents[chatID] = parsed
        return parsed
    }
    static func parse(_ source: String) -> Document? {
        guard source.utf8.count <= 10_485_760, let chat = value("chat_id", source),
              let chatID = decodeString(chat), let manifest = value("public_speech", source) else { return nil }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase; decoder.allowsJSON5 = true
        guard let data = manifest.data(using: .utf8),
              let speech = try? decoder.decode([String: [PublicAssistantSpeechSegment]].self, from: data) else { return nil }
        let messageSource = value("messages", source) ?? "[]"
        let identities = objects(messageSource).compactMap { object -> MessageIdentity? in
            guard let id = value("id", object).flatMap(decodeString),
                  let role = value("role", object).flatMap(decodeString),
                  let key = value("content", object).flatMap(decodeString) else { return nil }
            return .init(id: id, role: role, contentKey: key)
        }
        return .init(chatID: chatID, speech: speech, identities: identities)
    }
    private static func decodeString(_ value: String) -> String? {
        let decoder = JSONDecoder(); decoder.allowsJSON5 = true
        return value.data(using: .utf8).flatMap { try? decoder.decode(String.self, from: $0) }
    }
    // A small lexer skips comments and all quote styles, including template
    // literals containing nested JSON or fake property names. No JS evaluation.
    static func value(_ property: String, _ source: String) -> String? {
        let chars = Array(source)
        var index = 0
        while index < chars.count {
            if chars[index] == "\"" || chars[index] == "'" {
                let start = index
                _ = skipTriviaOrString(chars, &index)
                let token = decodeString(String(chars[start..<index]))
                while index < chars.count, chars[index].isWhitespace { index += 1 }
                if token == property, index < chars.count, chars[index] == ":" {
                    index += 1
                    while index < chars.count, chars[index].isWhitespace { index += 1 }
                    let begin = index
                    guard let end = valueEnd(chars, index) else { return nil }
                    return String(chars[begin..<end])
                }
                continue
            }
            if skipTriviaOrString(chars, &index) { continue }
            let start = index
            if chars[index].isLetter || chars[index] == "_" || chars[index] == "$" {
                while index < chars.count, chars[index].isLetter || chars[index].isNumber || chars[index] == "_" || chars[index] == "$" { index += 1 }
                let token = String(chars[start..<index])
                if token == property {
                    while index < chars.count, chars[index].isWhitespace { index += 1 }
                    if index < chars.count, chars[index] == ":" {
                        index += 1
                        while index < chars.count, chars[index].isWhitespace { index += 1 }
                        let begin = index
                        guard let end = valueEnd(chars, index) else { return nil }
                        return String(chars[begin..<end])
                    }
                }
            } else { index += 1 }
        }
        return nil
    }
    // JSON5 does not accept TypeScript template literals. Convert only static
    // literals to JSON strings; interpolation or unsupported escapes fail closed.
    static func json5WithStaticTemplates(_ source: String) -> String? {
        guard source.utf8.count <= 10_485_760 else { return nil }
        let chars = Array(source); var index = 0; var result = ""
        while index < chars.count {
            if chars[index] != "`" {
                let start = index
                if skipTriviaOrString(chars, &index) { result += String(chars[start..<index]) }
                else { result.append(chars[index]); index += 1 }
                continue
            }
            index += 1; var literal = ""; var closed = false
            while index < chars.count {
                let character = chars[index]; index += 1
                if character == "`" { closed = true; break }
                if character == "$", index < chars.count, chars[index] == "{" { return nil }
                if character == "\\" {
                    guard index < chars.count else { return nil }
                    let escape = chars[index]; index += 1
                    switch escape {
                    case "n": literal.append("\n")
                    case "r": literal.append("\r")
                    case "t": literal.append("\t")
                    case "b": literal.append("\u{08}")
                    case "f": literal.append("\u{0C}")
                    case "v": literal.append("\u{0B}")
                    case "0": literal.append("\0")
                    case "\\", "`", "$", "\"", "'": literal.append(escape)
                    case "\n": break
                    case "\r": if index < chars.count, chars[index] == "\n" { index += 1 }
                    default: return nil
                    }
                } else { literal.append(character) }
            }
            guard closed, let encoded = try? JSONEncoder().encode(literal), let token = String(data: encoded, encoding: .utf8) else { return nil }
            result += token
        }
        return result
    }
    private static func objects(_ source: String) -> [String] {
        let chars = Array(source); var index = 0; var result: [String] = []
        while index < chars.count {
            if skipTriviaOrString(chars, &index) { continue }
            if chars[index] == "{", let end = valueEnd(chars, index) {
                result.append(String(chars[index..<end])); index = end
            } else { index += 1 }
        }
        return result
    }
    private static func valueEnd(_ chars: [Character], _ start: Int) -> Int? {
        guard start < chars.count else { return nil }
        var index = start
        if chars[index] == "\"" || chars[index] == "'" || chars[index] == "`" {
            return skipTriviaOrString(chars, &index) ? index : nil
        }
        guard chars[index] == "{" || chars[index] == "[" else { return nil }
        let closing: Character = chars[index] == "{" ? "}" : "]"
        index += 1
        while index < chars.count {
            if skipTriviaOrString(chars, &index) { continue }
            if chars[index] == "{" || chars[index] == "[" {
                guard let end = valueEnd(chars, index) else { return nil }; index = end
            } else if chars[index] == closing { return index + 1 }
            else { index += 1 }
        }
        return nil
    }
    private static func skipTriviaOrString(_ chars: [Character], _ index: inout Int) -> Bool {
        guard index < chars.count else { return false }
        if chars[index].isWhitespace { index += 1; return true }
        if chars[index] == "\"" || chars[index] == "'" || chars[index] == "`" {
            let quote = chars[index]; index += 1
            while index < chars.count {
                if chars[index] == "\\" { index = min(chars.count, index + 2) }
                else if chars[index] == quote { index += 1; return true }
                else { index += 1 }
            }
            return true
        }
        if chars[index] == "/", index + 1 < chars.count {
            if chars[index + 1] == "/" {
                index += 2; while index < chars.count, !chars[index].isNewline { index += 1 }; return true
            }
            if chars[index + 1] == "*" {
                index += 2
                while index + 1 < chars.count {
                    if chars[index] == "*", chars[index + 1] == "/" { index += 2; return true }; index += 1
                }
                index = chars.count; return true
            }
        }
        return false
    }
}
