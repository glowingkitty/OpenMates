// Web: frontend/packages/ui/src/utils/assistantActivitySummary.ts
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
import Foundation

struct AssistantActivitySummaryState {
    var apps: [String] = []
    var memories: [String] = []
    var focuses: [String] = []
    var thinking = false
    var usingApps = false
    var thinkingStreaming = false
    var activatingFocus = false
    var subChats = false
    var workingSubChats = false
    var active = false
    var cancelledFocus = false
}

enum AssistantActivitySummary {
    typealias Translate = (String, [String: String]) -> String
    static func candidates(_ state: AssistantActivitySummaryState, translate: Translate) -> [String] {
        func t(_ key: String, _ values: [String: String] = [:]) -> String { translate("chat.response_activity." + key, values) }
        func join(_ parts: [String]) -> String { parts.reduce("") { $0.isEmpty ? $1 : t("join", ["first": $0, "last": $1]) } }
        func list(_ names: [String]) -> String {
            names.count > 1 ? t("list_last", ["items": names.dropLast().joined(separator: ", "), "last": names.last!]) : names.first ?? ""
        }
        func appCount() -> String { t(state.usingApps ? "using_count" : state.thinking && state.memories.isEmpty ? "thought_used_count" : "used_count", ["count": String(state.apps.count)]) }
        func focus(_ compact: Bool) -> String {
            t(compact ? state.activatingFocus ? "focus_activating_count" : "focus_activated_count" : state.activatingFocus ? "focus_activating" : "focus_activated",
              ["focus": state.focuses.joined(separator: "', '"), "count": String(state.focuses.count)])
        }
        func subChats() -> String { t(state.workingSubChats ? "sub_chats_working" : "sub_chats") }
        func memory(_ compact: Bool) -> String { t(!compact && state.memories.count == 1 ? "memory_loaded" : "memories_loaded", ["memory": state.memories.first ?? "", "count": String(state.memories.count)]) }
        func detailedApps() -> String {
            if state.apps.count > 3 {
                return t(state.usingApps ? "using_more" : state.thinking ? "thought_used_more" : "used_more", ["apps": state.apps.prefix(3).joined(separator: ", "), "count": String(state.apps.count - 3)])
            }
            let key = state.usingApps ? state.thinkingStreaming ? "thinking_using" : "using"
                : "\(state.thinking ? "thought_used" : "used")_\(state.apps.count == 1 ? "single" : "multiple")"
            return t(key, ["apps": list(state.apps)])
        }
        var result: [String] = []
        for compact in [false, true] {
            var parts: [String] = []
            if !state.memories.isEmpty {
                if !state.apps.isEmpty && state.memories.count == 1 && state.focuses.isEmpty && !state.subChats && !compact {
                    parts.append(t(state.usingApps ? "memory_using_apps" : "memory_used_apps", ["memory": state.memories[0], "count": String(state.apps.count)]))
                } else {
                    parts.append(memory(compact)); if !state.apps.isEmpty { parts.append(appCount()) }
                }
            } else if !state.apps.isEmpty { parts.append(compact ? appCount() : detailedApps()) }
            let combinedFocus = state.memories.isEmpty && state.apps.isEmpty && state.subChats && !state.activatingFocus && !state.workingSubChats && !compact
            if !state.focuses.isEmpty { parts.append(combinedFocus ? t("focus_sub_chats", ["focus": state.focuses.joined(separator: "', '")]) : focus(compact)) }
            if state.subChats && !(combinedFocus && !state.focuses.isEmpty) { parts.append(subChats()) }
            if !parts.isEmpty {
                let sentence = !compact && state.focuses.isEmpty && !state.subChats && ((state.memories.count == 1 && !state.apps.isEmpty) || (state.memories.isEmpty && state.apps.count > 3))
                result.append(sentence ? t("sentence", ["activity": join(parts)]) : join(parts))
            }
        }
        var counts: [String] = []
        if !state.memories.isEmpty { counts.append(t("memory_count", ["count": String(state.memories.count)])) }
        if !state.apps.isEmpty { counts.append(t("app_count", ["count": String(state.apps.count)])) }
        if !state.focuses.isEmpty { counts.append(t("focus_count", ["count": String(state.focuses.count)])) }
        if state.subChats { counts.append(t("sub_chat_count")) }
        if !counts.isEmpty { result.append(join(counts)) }
        if result.isEmpty && state.cancelledFocus { result.append(t("focus_cancelled")) }
        if result.isEmpty { result.append(translate(state.active ? "chat.thinking.header_streaming" : "chat.thinking.header_done", [:])) }
        result.append(t(state.active ? "activity_active" : "activity_done"))
        var seen = Set<String>()
        return result.filter { seen.insert($0).inserted }
    }
}

/// Only the simple argument/cardinal-plural grammar used by response_activity.
/// Malformed or unsupported messages return nil; callers discard that candidate.
/// Replacements are emitted as data, never parsed as message syntax.
/// This deliberately does not alter the global localization lookup behavior.
enum AssistantActivityMessageFormat {
    private indirect enum Node {
        case text(String), argument(String), number
        case plural(String, [String: [Node]])
    }
    private struct Parser {
        let chars: [Character]
        var index = 0
        var nodeCount = 0
        mutating func nodes(depth: Int = 0, nested: Bool = false) throws -> [Node] {
            guard depth < 8 else { throw Invalid.message }
            var result: [Node] = []
            var text = ""
            func flush() { if !text.isEmpty { result.append(.text(text)); text = "" } }
            while index < chars.count {
                let char = chars[index]
                if char == "}" {
                    guard nested else { throw Invalid.message }
                    flush(); index += 1; return result
                }
                if char == "'" {
                    if index + 1 < chars.count && chars[index + 1] == "'" { text.append("'"); index += 2; continue }
                    if index + 1 < chars.count && ["{", "}", "#"].contains(chars[index + 1]) {
                        index += 1
                        var closed = false
                        while index < chars.count {
                            if chars[index] == "'" {
                                if index + 1 < chars.count && chars[index + 1] == "'" { text.append("'"); index += 2; continue }
                                closed = true; index += 1; break
                            }
                            text.append(chars[index]); index += 1
                        }
                        guard closed else { throw Invalid.message }
                        continue
                    }
                }
                if char == "{" {
                    flush(); index += 1; nodeCount += 1
                    guard nodeCount <= 64 else { throw Invalid.message }
                    let name = token(until: [",", "}"])
                    guard !name.isEmpty, index < chars.count else { throw Invalid.message }
                    if chars[index] == "}" { result.append(.argument(name)); index += 1; continue }
                    index += 1
                    guard token(until: [","]) == "plural", index < chars.count else { throw Invalid.message }
                    index += 1
                    var branches: [String: [Node]] = [:]
                    while true {
                        whitespace()
                        guard index < chars.count else { throw Invalid.message }
                        if chars[index] == "}" { index += 1; break }
                        let selector = token(until: ["{"])
                        let valid = ["zero", "one", "two", "few", "many", "other"].contains(selector)
                            || (selector.hasPrefix("=") && Int(selector.dropFirst()) != nil)
                        guard valid, index < chars.count, branches[selector] == nil else { throw Invalid.message }
                        index += 1
                        branches[selector] = try nodes(depth: depth + 1, nested: true)
                    }
                    guard branches["other"] != nil else { throw Invalid.message }
                    result.append(.plural(name, branches)); continue
                }
                if char == "#" { flush(); result.append(.number); index += 1; continue }
                text.append(char); index += 1
            }
            guard !nested else { throw Invalid.message }
            flush(); return result
        }
        mutating func whitespace() { while index < chars.count && chars[index].isWhitespace { index += 1 } }
        mutating func token(until endings: Set<Character>) -> String {
            let start = index
            while index < chars.count && !endings.contains(chars[index]) { index += 1 }
            return String(chars[start..<index]).trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }
    private enum Invalid: Error { case message }
    static func format(_ message: String, values: [String: String], language: String) -> String? {
        guard message.count <= 16_000 else { return nil }
        var parser = Parser(chars: Array(message))
        guard let nodes = try? parser.nodes() else { return nil }
        return try? render(nodes, values: values, language: language, number: nil)
    }
    private static func render(_ nodes: [Node], values: [String: String], language: String, number: Int?) throws -> String {
        try nodes.map { node -> String in
            switch node {
            case .text(let text): return text
            case .argument(let key):
                guard let value = values[key] else { throw Invalid.message }; return value
            case .number: return number.map { String($0) } ?? "#"
            case .plural(let key, let options):
                guard let raw = values[key], let count = Int(raw), count >= 0,
                      let selected = options["=\(count)"] ?? options[category(count, language: language)] ?? options["other"] else { throw Invalid.message }
                return try render(selected, values: values, language: language, number: count)
            }
        }.joined()
    }
    private static func category(_ count: Int, language: String) -> String {
        let lang = language.lowercased().split(separator: "-").first.map(String.init) ?? language
        switch lang {
        case "ar":
            if count == 0 { return "zero" }; if count == 1 { return "one" }; if count == 2 { return "two" }
            if (3...10).contains(count % 100) { return "few" }; if (11...99).contains(count % 100) { return "many" }; return "other"
        case "cs", "sk": return count == 1 ? "one" : (2...4).contains(count) ? "few" : "other"
        case "pl":
            if count == 1 { return "one" }
            return (2...4).contains(count % 10) && !(12...14).contains(count % 100) ? "few" : "many"
        case "ru", "uk":
            if count % 10 == 1 && count % 100 != 11 { return "one" }
            return (2...4).contains(count % 10) && !(12...14).contains(count % 100) ? "few" : "many"
        case "he": return count == 1 ? "one" : count == 2 ? "two" : "other"
        case "fr", "pt", "hi": return count <= 1 ? "one" : "other"
        case "ja", "ko", "zh", "id", "th", "vi": return "other"
        default: return count == 1 ? "one" : "other"
        }
    }
}
