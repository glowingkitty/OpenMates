// Canonical message-scoped render document for stable Apple chat history.
// Converts the existing native markdown parser output into codable semantic blocks.
// Preserves web document order, message ownership, inline entities, and embed IDs.
// Built when stable content changes, never from frequently evaluated SwiftUI bodies.
// Contains no rendering code and records no plaintext in diagnostics.
//
// ─── Web source ─────────────────────────────────────────────────────
// TypeScript: frontend/packages/ui/src/message_parsing/parse_message.ts
//             frontend/packages/ui/src/message_parsing/embedParsing.ts
//             frontend/packages/ui/src/message_parsing/types.ts
// ────────────────────────────────────────────────────────────────────

import Foundation

struct ChatHistoryRenderDocument: Codable, Equatable, Sendable {
    static let schemaVersion = 1

    let version: Int
    let messageId: String
    let identity: ChatHistoryMessageIdentity
    let blocks: [ChatHistoryRenderBlock]

    static func build(for message: Message) -> ChatHistoryRenderDocument? {
        guard message.isStreaming != true,
              let content = message.content,
              !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }

        let identity = ChatHistoryMessageIdentity(
            messageId: message.id,
            chatId: message.chatId,
            role: message.role,
            senderName: message.senderName,
            category: message.category,
            modelName: message.modelName,
            appId: message.appId
        )
        let embedRefsById = Dictionary(
            (message.embedRefs ?? []).map { ($0.id, $0) },
            uniquingKeysWith: { first, _ in first }
        )
        let blocks = MarkdownParser.parse(content).enumerated().map { index, block in
            ChatHistoryRenderBlock(
                messageId: message.id,
                index: index,
                markdownBlock: block,
                embedRefsById: embedRefsById
            )
        }

        return ChatHistoryRenderDocument(
            version: schemaVersion,
            messageId: message.id,
            identity: identity,
            blocks: blocks
        )
    }
}

struct ChatHistoryMessageIdentity: Codable, Equatable, Sendable {
    let messageId: String
    let chatId: String
    let role: MessageRole
    let senderName: String?
    let category: String?
    let modelName: String?
    let appId: String?
}

struct ChatHistoryRenderBlock: Codable, Equatable, Identifiable, Sendable {
    enum Kind: String, Codable, Sendable {
        case paragraph
        case heading
        case codeBlock
        case blockquote
        case sourceQuote
        case horizontalRule
        case unorderedList
        case orderedList
        case table
        case embedGroup
        case interactiveQuestion
        case interactiveQuestionFallback
        case hiddenProtocol
        case demoGroup
    }

    let id: String
    let messageId: String
    let kind: Kind
    let text: String?
    let headingLevel: Int?
    let language: String?
    let items: [String]
    let tableHeaders: [String]
    let tableRows: [[String]]
    let embedReferences: [ChatHistoryEmbedReference]
    let inlineEntities: [ChatHistoryInlineEntity]

    init(
        messageId: String,
        index: Int,
        markdownBlock: MarkdownBlock,
        embedRefsById: [String: EmbedRef]
    ) {
        id = "\(messageId):block:\(index)"
        self.messageId = messageId

        var resolvedKind: Kind
        var resolvedText: String? = nil
        var resolvedHeadingLevel: Int? = nil
        var resolvedLanguage: String? = nil
        var resolvedItems: [String] = []
        var resolvedTableHeaders: [String] = []
        var resolvedTableRows: [[String]] = []
        var resolvedEmbedReferences: [ChatHistoryEmbedReference] = []

        switch markdownBlock {
        case .paragraph(let text):
            resolvedKind = .paragraph
            resolvedText = text
        case .codeBlock(let language, let code):
            resolvedKind = .codeBlock
            resolvedText = code
            resolvedLanguage = language
        case .blockquote(let text):
            if let sourceQuote = Self.sourceQuote(in: text, embedRefsById: embedRefsById) {
                resolvedKind = .sourceQuote
                resolvedText = sourceQuote.text
                resolvedEmbedReferences = [sourceQuote.reference]
            } else {
                resolvedKind = .blockquote
                resolvedText = text
            }
        case .header(let level, let text):
            resolvedKind = .heading
            resolvedText = text
            resolvedHeadingLevel = level
        case .horizontalRule:
            resolvedKind = .horizontalRule
        case .unorderedList(let items):
            resolvedKind = .unorderedList
            resolvedItems = items
        case .orderedList(let items):
            resolvedKind = .orderedList
            resolvedItems = items
        case .table(let headers, let rows):
            resolvedKind = .table
            resolvedTableHeaders = headers
            resolvedTableRows = rows
        case .embedGroup(let references):
            resolvedKind = .embedGroup
            resolvedEmbedReferences = references.map { reference in
                Self.embedReference(reference, embedRefsById: embedRefsById)
            }
        case .interactiveQuestion:
            resolvedKind = .interactiveQuestion
        case .interactiveQuestionFallback:
            resolvedKind = .interactiveQuestionFallback
        case .hiddenProtocol:
            resolvedKind = .hiddenProtocol
        case .demoGroup:
            resolvedKind = .demoGroup
        }

        kind = resolvedKind
        text = resolvedText
        headingLevel = resolvedHeadingLevel
        language = resolvedLanguage
        items = resolvedItems
        tableHeaders = resolvedTableHeaders
        tableRows = resolvedTableRows
        embedReferences = resolvedEmbedReferences
        inlineEntities = ChatHistoryInlineEntity.parse(
            [resolvedText, resolvedItems.joined(separator: "\n")]
                .compactMap { $0 }
                .joined(separator: "\n")
        )
    }

    private static func sourceQuote(
        in text: String,
        embedRefsById: [String: EmbedRef]
    ) -> (text: String, reference: ChatHistoryEmbedReference)? {
        let pattern = #"^\[([^\]]+)\]\(embed:([^\)]+)\)$"#
        guard let expression = try? NSRegularExpression(pattern: pattern),
              let match = expression.firstMatch(
                  in: text,
                  range: NSRange(text.startIndex..., in: text)
              ),
              match.range.location != NSNotFound,
              let quoteRange = Range(match.range(at: 1), in: text),
              let idRange = Range(match.range(at: 2), in: text) else {
            return nil
        }
        let embedId = String(text[idRange])
        return (
            String(text[quoteRange]),
            ChatHistoryEmbedReference(
                id: embedId,
                type: embedRefsById[embedId]?.type,
                isReference: true,
                isLargePreview: false
            )
        )
    }

    private static func embedReference(
        _ reference: MarkdownEmbedReference,
        embedRefsById: [String: EmbedRef]
    ) -> ChatHistoryEmbedReference {
        ChatHistoryEmbedReference(
            id: reference.value,
            type: embedRefsById[reference.value]?.type,
            isReference: reference.isRef,
            isLargePreview: reference.isLargePreview
        )
    }
}

struct ChatHistoryEmbedReference: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let type: String?
    let isReference: Bool
    let isLargePreview: Bool
}

struct ChatHistoryInlineEntity: Codable, Equatable, Identifiable, Sendable {
    enum Kind: String, Codable, Sendable {
        case embed
        case wiki
        case mention
        case link
    }

    let id: String
    let kind: Kind
    let displayText: String
    let target: String
    let location: Int
    let length: Int

    static func parse(_ text: String) -> [ChatHistoryInlineEntity] {
        let patterns: [(Kind, String)] = [
            (.embed, #"\[([^\]]*)\]\(embed:([^\)]+)\)"#),
            (.wiki, #"\[([^\]]*)\]\(wiki:([^\)]+)\)"#),
            (.link, #"\[([^\]]+)\]\((https?://[^\)]+)\)"#),
            (.mention, #"(?<![\w@])@([\p{L}\p{N}_-]+)"#),
        ]
        var entities: [ChatHistoryInlineEntity] = []

        for (kind, pattern) in patterns {
            guard let expression = try? NSRegularExpression(pattern: pattern) else { continue }
            for match in expression.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
                guard Range(match.range, in: text) != nil,
                      let displayRange = Range(match.range(at: 1), in: text) else { continue }
                let displayText = String(text[displayRange])
                let target: String
                if match.numberOfRanges > 2,
                   let targetRange = Range(match.range(at: 2), in: text) {
                    target = String(text[targetRange])
                } else {
                    target = displayText
                }
                entities.append(ChatHistoryInlineEntity(
                    id: "\(kind.rawValue):\(match.range.location):\(target)",
                    kind: kind,
                    displayText: displayText,
                    target: target,
                    location: match.range.location,
                    length: match.range.length
                ))
            }
        }

        return entities.sorted {
            if $0.location == $1.location { return $0.kind.rawValue < $1.kind.rawValue }
            return $0.location < $1.location
        }
    }
}
