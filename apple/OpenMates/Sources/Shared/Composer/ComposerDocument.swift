// Product-owned native composer document contract.
// Canonical markdown remains durable; TextKit and Tiptap are transient adapters.
// Parsing and serialization are deterministic across native Apple and web.
// Encryption material and platform editor objects must never enter this model.
// Invalid runtime documents fail explicitly rather than losing partial content.

import Foundation

struct ComposerDocumentV1: Codable, Equatable {
    let version: Int
    let nodes: [ComposerNodeV1]
}

struct ComposerNodeV1: Codable, Equatable {
    let kind: String
    let id: String
    let source: String?
    let mentionKind: String?
    let targetId: String?
    let canonicalSyntax: String?
    let displayLabel: String?
    let embedType: String?
    let status: String?
    let contentRef: String?
    let referenceOnly: Bool?
    let canonicalSource: String?
    let display: ComposerEmbedDisplayV1?

    static func text(id: String, source: String) -> Self {
        Self(kind: "text", id: id, source: source)
    }

    static func mention(
        id: String,
        mentionKind: String,
        targetId: String,
        canonicalSyntax: String,
        displayLabel: String
    ) -> Self {
        Self(
            kind: "mention",
            id: id,
            mentionKind: mentionKind,
            targetId: targetId,
            canonicalSyntax: canonicalSyntax,
            displayLabel: displayLabel
        )
    }

    static func embed(
        id: String,
        embedType: String,
        canonicalSource: String,
        referenceOnly: Bool,
        display: ComposerEmbedDisplayV1,
        contentRef: String? = nil
    ) -> Self {
        Self(
            kind: "embed",
            id: id,
            embedType: embedType,
            status: "finished",
            contentRef: contentRef,
            referenceOnly: referenceOnly,
            canonicalSource: canonicalSource,
            display: display
        )
    }

    init(
        kind: String,
        id: String,
        source: String? = nil,
        mentionKind: String? = nil,
        targetId: String? = nil,
        canonicalSyntax: String? = nil,
        displayLabel: String? = nil,
        embedType: String? = nil,
        status: String? = nil,
        contentRef: String? = nil,
        referenceOnly: Bool? = nil,
        canonicalSource: String? = nil,
        display: ComposerEmbedDisplayV1? = nil
    ) {
        self.kind = kind
        self.id = id
        self.source = source
        self.mentionKind = mentionKind
        self.targetId = targetId
        self.canonicalSyntax = canonicalSyntax
        self.displayLabel = displayLabel
        self.embedType = embedType
        self.status = status
        self.contentRef = contentRef
        self.referenceOnly = referenceOnly
        self.canonicalSource = canonicalSource
        self.display = display
    }
}

struct ComposerEmbedDisplayV1: Codable, Equatable {
    let title: String
    let mediaKind: String
}

enum ComposerDocumentError: Error, Equatable {
    case unsupportedVersion(Int)
    case unsupportedNode(String)
    case invalidNode(kind: String, id: String, missingField: String)
    case duplicateNodeID(String)

    var code: String {
        switch self {
        case .unsupportedVersion: "unsupported-version"
        case .unsupportedNode: "unsupported-node"
        case .invalidNode: "invalid-node"
        case .duplicateNodeID: "duplicate-node-id"
        }
    }
}

enum ComposerMarkdownAdapter {
    static func parse(_ markdown: String) throws -> ComposerDocumentV1 {
        let source = markdown
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        let embedPattern = #"```(json_embed|json)\n([\s\S]*?)\n```"#
        let embedRegex = try NSRegularExpression(pattern: embedPattern)
        let fullRange = NSRange(source.startIndex..<source.endIndex, in: source)
        var nodes: [ComposerNodeV1] = []
        var counters = NodeCounters()
        var cursor = source.startIndex

        for match in embedRegex.matches(in: source, range: fullRange) {
            guard
                let matchRange = Range(match.range, in: source),
                let fenceRange = Range(match.range(at: 1), in: source),
                let jsonRange = Range(match.range(at: 2), in: source),
                let embed = embedNode(
                    canonicalSource: String(source[matchRange]),
                    fence: String(source[fenceRange]),
                    jsonSource: String(source[jsonRange]),
                    nodeId: "composer:embed:\(counters.embed)"
                )
            else { continue }

            appendTextAndMentions(
                String(source[cursor..<matchRange.lowerBound]),
                to: &nodes,
                counters: &counters
            )
            nodes.append(embed)
            counters.embed += 1
            cursor = matchRange.upperBound
        }

        appendTextAndMentions(String(source[cursor...]), to: &nodes, counters: &counters)
        return ComposerDocumentV1(version: 1, nodes: nodes)
    }

    static func serialize(_ document: ComposerDocumentV1) throws -> String {
        guard document.version == 1 else {
            throw ComposerDocumentError.unsupportedVersion(document.version)
        }

        var seenNodeIds = Set<String>()
        return try document.nodes.map { node in
            guard !node.id.isEmpty else {
                throw ComposerDocumentError.invalidNode(
                    kind: node.kind,
                    id: node.id,
                    missingField: "id"
                )
            }
            guard seenNodeIds.insert(node.id).inserted else {
                throw ComposerDocumentError.duplicateNodeID(node.id)
            }

            switch node.kind {
            case "text":
                guard let source = node.source else {
                    throw ComposerDocumentError.invalidNode(
                        kind: node.kind,
                        id: node.id,
                        missingField: "source"
                    )
                }
                return source
            case "hardBreak":
                return "\n"
            case "mention":
                guard let canonicalSyntax = node.canonicalSyntax else {
                    throw ComposerDocumentError.invalidNode(
                        kind: node.kind,
                        id: node.id,
                        missingField: "canonicalSyntax"
                    )
                }
                return canonicalSyntax
            case "embed":
                guard let canonicalSource = node.canonicalSource else {
                    throw ComposerDocumentError.invalidNode(
                        kind: node.kind,
                        id: node.id,
                        missingField: "canonicalSource"
                    )
                }
                return canonicalSource
            default:
                throw ComposerDocumentError.unsupportedNode(node.kind)
            }
        }.joined()
    }

    private static func appendTextAndMentions(
        _ source: String,
        to nodes: inout [ComposerNodeV1],
        counters: inout NodeCounters
    ) {
        let pattern = #"@(best-model|ai-model|mate|skill|focus|project|memory):([a-zA-Z0-9_.-]+(?::[a-zA-Z0-9_.-]+)*)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            appendText(source, to: &nodes, counters: &counters)
            return
        }

        let fullRange = NSRange(source.startIndex..<source.endIndex, in: source)
        var cursor = source.startIndex
        for match in regex.matches(in: source, range: fullRange) {
            guard
                let matchRange = Range(match.range, in: source),
                let typeRange = Range(match.range(at: 1), in: source),
                let targetRange = Range(match.range(at: 2), in: source)
            else { continue }

            appendText(String(source[cursor..<matchRange.lowerBound]), to: &nodes, counters: &counters)
            let rawKind = String(source[typeRange])
            let targetId = String(source[targetRange])
            nodes.append(.mention(
                id: "composer:mention:\(counters.mention)",
                mentionKind: mentionKind(rawKind),
                targetId: targetId,
                canonicalSyntax: String(source[matchRange]),
                displayLabel: "@\(displayName(targetId))"
            ))
            counters.mention += 1
            cursor = matchRange.upperBound
        }
        appendText(String(source[cursor...]), to: &nodes, counters: &counters)
    }

    private static func appendText(
        _ source: String,
        to nodes: inout [ComposerNodeV1],
        counters: inout NodeCounters
    ) {
        guard !source.isEmpty else { return }
        nodes.append(.text(id: "composer:text:\(counters.text)", source: source))
        counters.text += 1
    }

    private static func embedNode(
        canonicalSource: String,
        fence: String,
        jsonSource: String,
        nodeId: String
    ) -> ComposerNodeV1? {
        guard
            let data = jsonSource.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data),
            let value = object as? [String: Any]
        else { return nil }

        if
            let embedId = value["embed_id"] as? String,
            let embedType = value["type"] as? String
        {
            return .embed(
                id: nodeId,
                embedType: embedType,
                canonicalSource: canonicalSource,
                referenceOnly: value["reference_only"] as? Bool == true,
                display: ComposerEmbedDisplayV1(
                    title: value["title"] as? String ?? displayName(embedType),
                    mediaKind: embedType
                ),
                contentRef: "embed:\(embedId)"
            )
        }

        if
            fence == "json_embed",
            value["type"] as? String == "website",
            value["url"] is String
        {
            return .embed(
                id: nodeId,
                embedType: "web-website",
                canonicalSource: canonicalSource,
                referenceOnly: false,
                display: ComposerEmbedDisplayV1(
                    title: value["title"] as? String ?? "Website",
                    mediaKind: "web-website"
                )
            )
        }

        return nil
    }

    private static func mentionKind(_ value: String) -> String {
        switch value {
        case "ai-model": "aiModel"
        case "best-model": "bestModel"
        default: value
        }
    }

    private static func displayName(_ value: String) -> String {
        if value == "pdf" { return "PDF" }
        return value
            .split(whereSeparator: { "-_:".contains($0) })
            .map { part in
                part.prefix(1).uppercased() + part.dropFirst()
            }
            .joined(separator: " ")
    }
}

private struct NodeCounters {
    var text = 0
    var mention = 0
    var embed = 0
}

enum ComposerPositionMap {
    static func utf16Length(_ value: String) -> Int {
        value.utf16.count
    }
}
