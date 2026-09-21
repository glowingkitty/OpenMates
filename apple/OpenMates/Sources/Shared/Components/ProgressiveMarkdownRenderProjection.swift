// Incremental semantic projection over the existing MarkdownParser grammar.
// Web: message_parsing/streamingMessageBlocks.ts and streamingDocDiff.ts.
// This state belongs to one mounted message, never a global plaintext cache.
// A completed prefix is reused; an open block remains the bounded invalidation
// region. A single very large unfinished paragraph/list/fence can still be large.

import Foundation
import SwiftUI

// A preview can request less motion without replacing the system's read-only
// accessibility preference. This can never override a user's reduced motion.
private struct ProgressiveMarkdownReducedMotionKey: EnvironmentKey {
    static let defaultValue = false
}
extension EnvironmentValues {
    var progressiveMarkdownReducedMotion: Bool {
        get { self[ProgressiveMarkdownReducedMotionKey.self] }
        set { self[ProgressiveMarkdownReducedMotionKey.self] = newValue }
    }
}

struct ProgressiveMarkdownIdentity: Hashable {
    let scopeID: String
    let chatID: String
    let messageID: String
}

struct ProgressiveMarkdownRequest: Equatable {
    let identity: ProgressiveMarkdownIdentity
    let content: String
    let isStreaming: Bool
    var sequence: Int? = nil
    var renderDocument: ChatHistoryRenderDocument? = nil
    var embedRefs: [EmbedRef] = []
}

struct ProgressiveMarkdownBlock: Identifiable, Equatable {
    let ordinal: Int
    let markdown: MarkdownBlock?
    let document: ChatHistoryRenderBlock
    let sourceStartUTF8: Int
    let sourceEndUTF8: Int
    var id: String { document.id }
}

struct ProgressiveMarkdownRenderProjection {
    private(set) var identity: ProgressiveMarkdownIdentity?
    private(set) var source = ""
    private(set) var blocks: [ProgressiveMarkdownBlock] = []
    private(set) var isStreaming = false
    private(set) var parsedUTF8 = 0
    private(set) var lastParsedUTF8 = 0
    private(set) var parseCount = 0
    private(set) var fadeRevision = 0
    private(set) var fadeBlockID: String?
    private(set) var reusedBlockCount = 0
    private var nextOrdinal = 0
    private var lastSequence: Int?
    private var completed = false
    private var embedRefs: [EmbedRef] = []
    private var hasSourceSpans = true

    @discardableResult
    mutating func update(_ request: ProgressiveMarkdownRequest) -> Bool {
        if identity != request.identity {
            self = Self()
            identity = request.identity
        }
        if request.isStreaming {
            guard !completed else { return false }
            if let sequence = request.sequence {
                guard lastSequence.map({ sequence > $0 }) ?? true else { return false }
                lastSequence = sequence
            }
        }
        let firstUpdate = parseCount == 0 && source.isEmpty && blocks.isEmpty
        let phaseChanged = isStreaming != request.isStreaming
        let refsChanged = embedRefs != request.embedRefs
        guard firstUpdate || source != request.content || phaseChanged || refsChanged else {
            lastParsedUTF8 = 0
            return false
        }
        let previous = blocks
        let previouslyStreaming = isStreaming
        isStreaming = request.isStreaming
        if !request.isStreaming { completed = true }
        let refs = Dictionary(request.embedRefs.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        embedRefs = request.embedRefs
        lastParsedUTF8 = 0
        reusedBlockCount = 0

        // Existing stored histories already own their canonical semantic document.
        // Never parse or animate them just because a row is mounted or scrolled.
        if firstUpdate, !request.isStreaming,
           let document = request.renderDocument,
           document.messageId == request.identity.messageID {
            blocks = document.blocks.enumerated().map { ordinal, block in
                ProgressiveMarkdownBlock(ordinal: ordinal, markdown: nil, document: block,
                    sourceStartUTF8: 0, sourceEndUTF8: request.content.utf8.count)
            }
            nextOrdinal = blocks.count
            hasSourceSpans = false
            source = request.content
            fadeBlockID = nil
            return true
        }

        // Changing only embed-ref metadata does not invalidate Markdown syntax.
        // Late EmbedRecord hydration is not even part of this request: the real
        // renderer receives the live lookup independently and keeps these IDs.
        if source == request.content, !phaseChanged, refsChanged, hasSourceSpans {
            blocks = blocks.map { block in
                guard let markdown = block.markdown else { return block }
                return Self.block(markdown, ordinal: block.ordinal, identity: request.identity,
                    start: block.sourceStartUTF8, end: block.sourceEndUTF8, refs: refs)
            }
            fadeBlockID = nil
            return true
        }

        // The last grammar block is volatile, including lists, tables, fences,
        // adjacent embed groups and multiline paragraphs. Appending reparses only
        // that block and new source. A correction rolls back one affected block
        // so a removed boundary may merge with its predecessor.
        var start = 0
        if hasSourceSpans, !refsChanged, request.isStreaming == previouslyStreaming {
            if request.content.hasPrefix(source) {
                start = blocks.last?.sourceStartUTF8 ?? 0
                // A partial next marker initially parses as a paragraph ("2",
                // "-", "[[embed:"). Once completed it may extend the preceding
                // list/table/embed group. Keep that grammar container volatile
                // until its following block is unambiguous, rather than freezing
                // two separate lists/groups permanently at a chunk boundary.
                if blocks.count > 1 {
                    let predecessor = blocks[blocks.count - 2]
                    switch predecessor.markdown {
                    case .unorderedList?, .orderedList?, .table?, .blockquote?, .embedGroup?:
                        start = predecessor.sourceStartUTF8
                    default: break
                    }
                }
            } else {
                let common = zip(source.utf8, request.content.utf8).prefix { pair in pair.0 == pair.1 }.count
                let affected = blocks.firstIndex(where: { $0.sourceEndUTF8 > common }) ?? blocks.count
                start = blocks.indices.contains(max(0, affected - 1))
                    ? blocks[max(0, affected - 1)].sourceStartUTF8 : 0
            }
        }
        let retained = hasSourceSpans ? blocks.prefix { $0.sourceEndUTF8 <= start } : []
        let oldTail = Array(blocks.dropFirst(retained.count))
        let suffix = String(decoding: request.content.utf8.dropFirst(start), as: UTF8.self)
        lastParsedUTF8 = suffix.utf8.count
        parsedUTF8 += lastParsedUTF8
        parseCount += 1
        let parsed = MarkdownParser.parseSpans(suffix, isStreaming: request.isStreaming)

        // Reconcile common prefix and suffix, then the changed middle. Stable
        // neighbors retain identity across authoritative edits and finalization;
        // repeated identical paragraphs retain their occurrence order.
        var ordinals = [Int?](repeating: nil, count: parsed.count)
        func matches(_ old: ProgressiveMarkdownBlock, _ span: MarkdownParsedBlock) -> Bool {
            if let markdown = old.markdown { return markdown == span.block }
            return Self.block(span.block, ordinal: old.ordinal, identity: request.identity,
                start: 0, end: 0, refs: refs).document == old.document
        }
        var prefix = 0
        while prefix < min(oldTail.count, parsed.count), matches(oldTail[prefix], parsed[prefix]) {
            ordinals[prefix] = oldTail[prefix].ordinal
            prefix += 1
        }
        var suffixCount = 0
        while suffixCount < min(oldTail.count, parsed.count) - prefix,
              matches(oldTail[oldTail.count - 1 - suffixCount], parsed[parsed.count - 1 - suffixCount]) {
            ordinals[parsed.count - 1 - suffixCount] = oldTail[oldTail.count - 1 - suffixCount].ordinal
            suffixCount += 1
        }
        for index in prefix..<(parsed.count - suffixCount) {
            if index - prefix < oldTail.count - prefix - suffixCount {
                ordinals[index] = oldTail[index].ordinal
            } else {
                ordinals[index] = nextOrdinal
                nextOrdinal += 1
            }
        }
        let newTail = parsed.enumerated().map { index, span in
            Self.block(span.block, ordinal: ordinals[index]!, identity: request.identity,
                start: start + span.sourceStartUTF8, end: start + span.sourceEndUTF8, refs: refs)
        }
        blocks = Array(retained) + newTail
        source = request.content
        hasSourceSpans = true
        let oldByID = Dictionary(uniqueKeysWithValues: previous.map { ($0.id, $0.document) })
        reusedBlockCount = blocks.filter { oldByID[$0.id] == $0.document }.count
        if request.isStreaming,
           let changedTail = blocks.last(where: { $0.document.kind != .hiddenProtocol && oldByID[$0.id] != $0.document }) {
            fadeBlockID = changedTail.id
            fadeRevision += 1
        } else {
            fadeBlockID = nil
        }
        return true
    }

    private static func block(_ markdown: MarkdownBlock, ordinal: Int,
                              identity: ProgressiveMarkdownIdentity, start: Int, end: Int,
                              refs: [String: EmbedRef]) -> ProgressiveMarkdownBlock {
        ProgressiveMarkdownBlock(ordinal: ordinal, markdown: markdown,
            document: ChatHistoryRenderBlock(messageId: identity.messageID, index: ordinal,
                markdownBlock: markdown, embedRefsById: refs),
            sourceStartUTF8: start, sourceEndUTF8: end)
    }
}

@MainActor
final class ProgressiveMarkdownRenderModel: ObservableObject {
    @Published private(set) var projection: ProgressiveMarkdownRenderProjection
    init(_ request: ProgressiveMarkdownRequest) {
        var projection = ProgressiveMarkdownRenderProjection()
        projection.update(request)
        self.projection = projection
    }
    func update(_ request: ProgressiveMarkdownRequest) {
        var next = projection
        if next.update(request) { projection = next }
    }
}

struct ProgressiveMarkdownBlocksView<BlockContent: View>: View {
    let request: ProgressiveMarkdownRequest
    let blockContent: (ProgressiveMarkdownBlock) -> BlockContent
    @StateObject private var model: ProgressiveMarkdownRenderModel
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.progressiveMarkdownReducedMotion) private var requestedReduceMotion
    private var reduceMotion: Bool { systemReduceMotion || requestedReduceMotion }

    init(request: ProgressiveMarkdownRequest,
         @ViewBuilder blockContent: @escaping (ProgressiveMarkdownBlock) -> BlockContent) {
        self.request = request
        self.blockContent = blockContent
        _model = StateObject(wrappedValue: ProgressiveMarkdownRenderModel(request))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            ForEach(model.projection.blocks) { block in
                blockContent(block)
                    .modifier(ProgressiveMarkdownTailFade(
                        revision: model.projection.fadeRevision,
                        active: model.projection.isStreaming && model.projection.fadeBlockID == block.id))
                    #if DEBUG
                    .overlay(alignment: .bottomLeading) {
                        if ProcessInfo.processInfo.arguments.contains("--ui-test-progressive-render") {
                            ProgressiveMarkdownMountProbe(blockID: block.id)
                        }
                    }
                    #endif
            }
        }
        .onChange(of: request) { _, value in model.update(value) }
        #if DEBUG
        .overlay(alignment: .bottomLeading) {
            if ProcessInfo.processInfo.arguments.contains("--ui-test-progressive-render") {
                Color.clear.frame(width: 1, height: 1).accessibilityElement()
                    .accessibilityIdentifier("progressive-render-state")
                    .accessibilityLabel("blocks=\(model.projection.blocks.count);ids=\(model.projection.blocks.map(\.id).joined(separator: ","));parsed=\(model.projection.parsedUTF8);lastParsed=\(model.projection.lastParsedUTF8);revision=\(model.projection.fadeRevision);streaming=\(model.projection.isStreaming);fade=\(reduceMotion ? "none" : "220ms-ease-out-0.5")")
                    .allowsHitTesting(false)
            }
        }
        #endif
    }
}

enum ProgressiveMarkdownAnimationPolicy {
    static let duration = 0.22
    static let initialOpacity = 0.5
    static func animates(isStreaming: Bool, reduceMotion: Bool) -> Bool {
        isStreaming && !reduceMotion
    }
}

#if DEBUG
private struct ProgressiveMarkdownMountProbe: View {
    let blockID: String
    @State private var instance = UUID()
    var body: some View {
        Color.clear.frame(width: 1, height: 1).accessibilityElement()
            .accessibilityIdentifier("progressive-block-\(blockID)")
            .accessibilityLabel(instance.uuidString)
            .allowsHitTesting(false)
    }
}
#endif

private struct ProgressiveMarkdownTailFade: ViewModifier {
    let revision: Int
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.progressiveMarkdownReducedMotion) private var requestedReduceMotion
    private var reduceMotion: Bool { systemReduceMotion || requestedReduceMotion }
    @State private var opacity = 1.0
    private var pulse: String { "\(revision):\(active):\(reduceMotion)" }

    func body(content: Content) -> some View {
        content.opacity(opacity)
            .task(id: pulse) {
                var transaction = Transaction()
                transaction.disablesAnimations = true
                withTransaction(transaction) { opacity = ProgressiveMarkdownAnimationPolicy.animates(isStreaming: active, reduceMotion: reduceMotion) ? ProgressiveMarkdownAnimationPolicy.initialOpacity : 1 }
                guard ProgressiveMarkdownAnimationPolicy.animates(isStreaming: active, reduceMotion: reduceMotion) else { return }
                await Task.yield()
                guard !Task.isCancelled else { return }
                withAnimation(.easeOut(duration: ProgressiveMarkdownAnimationPolicy.duration)) { opacity = 1 }
            }
    }
}
