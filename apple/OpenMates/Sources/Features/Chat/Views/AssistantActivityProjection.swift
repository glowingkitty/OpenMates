// Source-position grouping over the existing incremental semantic projection.
// Web: frontend/packages/ui/src/message_parsing/assistantActivityRuns.ts
//      frontend/packages/ui/src/message_parsing/assistantActivityCompletion.ts
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.streaming.progressive-presentation,
//             chats.rendering.assistant-document-convergence, chats.surface.semantic-parity

import Foundation

struct AssistantActivityItem: Equatable, Identifiable {
    enum Kind: Equatable { case skill, focus, subChats }
    let id: String
    let kind: Kind
    let appID: String?
    let terminal: Bool
}

struct AssistantActivityUnit: Identifiable, Equatable {
    let id: String
    let block: ProgressiveMarkdownBlock
    let items: [AssistantActivityItem]
}

struct AssistantActivitySegment: Identifiable, Equatable {
    let id: String
    let units: [AssistantActivityUnit]
    let isActivity: Bool
    var items: [AssistantActivityItem] { units.flatMap(\.items) }
    var appIDs: [String] {
        var seen = Set<String>()
        return items.filter { $0.kind == .skill }.compactMap(\.appID).filter { seen.insert($0).inserted }
    }
    /// Local disclosure can settle when every operation settles. It never ends
    /// the response lifecycle or removes the response glow.
    func isActive(responseActive: Bool, thinkingStreaming: Bool,
                  openFocusIDs: Set<String>, activeBatchIDs: Set<String>) -> Bool {
        thinkingStreaming || items.contains { item in
            switch item.kind {
            case .skill: return responseActive && !item.terminal
            case .focus: return openFocusIDs.contains(item.id)
            case .subChats: return activeBatchIDs.contains(item.id) || !item.terminal
            }
        }
    }
}

enum AssistantActivityProjection {
    static func segments(blocks: [ProgressiveMarkdownBlock], embeds: [String: EmbedRecord],
                         completedSubChatIDs: Set<String> = []) -> [AssistantActivitySegment] {
        var result: [AssistantActivitySegment] = []
        var pending: [AssistantActivityUnit] = []
        var seenSkills = Set<String>()
        func flush() {
            guard let first = pending.first else { return }
            result.append(.init(id: "activity:\(first.id)", units: pending, isActivity: true))
            pending = []
        }
        for block in blocks {
            // Protocol-only blocks must not split a visible activity run.
            guard block.document.kind != .hiddenProtocol else { continue }
            for unit in units(block: block, embeds: embeds, completedSubChatIDs: completedSubChatIDs) {
                if !unit.items.isEmpty {
                    let kept = unit.items.filter { item in
                        item.kind != .skill || seenSkills.insert(item.id).inserted
                    }
                    guard !kept.isEmpty else { continue }
                    pending.append(filtered(unit, keeping: Set(kept.map(\.id))))
                } else {
                    flush()
                    // Content blocks remain direct siblings with their existing
                    // semantic identity as later activity runs arrive.
                    result.append(.init(id: unit.id, units: [unit], isActivity: false))
                }
            }
        }
        flush()
        return result
    }

    static func updatingBatchStatuses(in blocks: [ProgressiveMarkdownBlock], parentID: String,
                                      messageID: String?, progress: SubChatProgress?, terminalChildIDs: Set<String>,
                                      retainedTerminalStatuses: [SubChatActivityIdentity: String] = [:]) -> [ProgressiveMarkdownBlock] {
        blocks.map { block in
            guard let batch = block.document.subChatBatch else { return block }
            let status = SubChatActivityProvenance.status(for: batch, parentID: parentID, messageID: messageID,
                progress: progress, terminalChildIDs: terminalChildIDs, retainedTerminalStatuses: retainedTerminalStatuses)
            guard status != batch.status else { return block }
            let updated = SubChatBatchDescriptor(batchID: batch.batchID, parentChatID: batch.parentChatID,
                status: status, subChatIDs: batch.subChatIDs, executionMode: batch.executionMode,
                taskID: batch.taskID, parentMessageID: batch.parentMessageID)
            let markdown = MarkdownBlock.subChatBatch(updated)
            return ProgressiveMarkdownBlock(ordinal: block.ordinal, markdown: markdown,
                document: ChatHistoryRenderBlock(messageId: block.document.messageId, index: block.ordinal,
                    markdownBlock: markdown, embedRefsById: [:]),
                sourceStartUTF8: block.sourceStartUTF8, sourceEndUTF8: block.sourceEndUTF8)
        }
    }

    static func visibleUnits(in segment: AssistantActivitySegment, automaticallyExpandedActive: Bool,
                             visibleFocusIDs: Set<String>, activeBatchIDs: Set<String>) -> [AssistantActivityUnit] {
        guard automaticallyExpandedActive else { return segment.units }
        return segment.units.compactMap { unit in
            guard !unit.items.isEmpty else { return unit }
            let ids = Set(unit.items.filter { item in
                switch item.kind {
                case .skill: return true
                case .focus: return visibleFocusIDs.contains(item.id)
                case .subChats: return activeBatchIDs.contains(item.id)
                }
            }.map(\.id))
            guard !ids.isEmpty else { return nil }
            return filtered(unit, keeping: ids)
        }
    }

    private static func units(block: ProgressiveMarkdownBlock, embeds: [String: EmbedRecord],
                              completedSubChatIDs: Set<String>) -> [AssistantActivityUnit] {
        if let batch = block.document.subChatBatch {
            let complete = terminal(batch.status) || (!batch.subChatIDs.isEmpty && batch.subChatIDs.allSatisfy(completedSubChatIDs.contains))
            return [.init(id: block.id, block: block, items: [.init(id: batch.batchID, kind: .subChats, appID: nil, terminal: complete)])]
        }
        guard block.document.kind == .embedGroup else {
            return [.init(id: block.id, block: block, items: [])]
        }
        // The native grammar coalesces adjacent embed references, including
        // result previews. Partition only that semantic group; keep its regular
        // result references in their original order and original renderer.
        var units: [AssistantActivityUnit] = []
        var references: [ChatHistoryEmbedReference] = []
        var items: [AssistantActivityItem] = []
        var activity: Bool?
        func flush() {
            guard let first = references.first else { return }
            units.append(.init(id: "\(block.id):ref:\(first.id)", block: replacingReferences(block, references), items: items))
            references = []; items = []
        }
        for ref in block.document.embedReferences {
            let embed = embeds[ref.id]
            let type = ref.type ?? embed?.type
            let kind: AssistantActivityItem.Kind?
            if embed?.isAppSkillUse == true || ["app-skill-use", "app_skill_use"].contains(type ?? "") { kind = .skill }
            else if type == "focus-mode-activation" { kind = .focus }
            else { kind = nil }
            let nextActivity = kind != nil
            if activity != nextActivity { flush(); activity = nextActivity }
            references.append(ref)
            if let kind {
                items.append(.init(id: ref.id, kind: kind,
                    appID: embed?.appId ?? embed?.rawData?["app_id"]?.value as? String,
                    terminal: embed.map { $0.status != .processing } ?? false))
            }
        }
        flush()
        return units
    }

    private static func filtered(_ unit: AssistantActivityUnit, keeping ids: Set<String>) -> AssistantActivityUnit {
        guard unit.block.document.kind == .embedGroup else { return unit }
        let references = unit.block.document.embedReferences.filter { ids.contains($0.id) }
        return .init(id: unit.id, block: replacingReferences(unit.block, references), items: unit.items.filter { ids.contains($0.id) })
    }

    private static func replacingReferences(_ block: ProgressiveMarkdownBlock,
                                            _ refs: [ChatHistoryEmbedReference]) -> ProgressiveMarkdownBlock {
        let markdown = MarkdownBlock.embedGroup(refs.map {
            MarkdownEmbedReference(value: $0.id, isRef: $0.isReference, isLargePreview: $0.isLargePreview, type: $0.type)
        })
        let document = ChatHistoryRenderBlock(messageId: block.document.messageId, index: block.ordinal,
            markdownBlock: markdown, embedRefsById: [:])
        return .init(ordinal: block.ordinal, markdown: markdown, document: document,
                     sourceStartUTF8: block.sourceStartUTF8, sourceEndUTF8: block.sourceEndUTF8)
    }

    static func terminal(_ status: String) -> Bool {
        ["finished", "completed", "error", "failed", "cancelled", "stopped"].contains(status)
    }
}

/// Manual choice belongs to one mounted source-position group, including after
/// terminal updates. A new turn/group gets a fresh state; no global cache.
struct AssistantActivityDisclosureState: Equatable {
    private(set) var expanded = false
    private(set) var userToggled = false
    mutating func synchronize(active: Bool) { if !userToggled { expanded = active } }
    mutating func toggle() { expanded.toggle(); userToggled = true }
}

/// Live Focus acknowledgement state, independent of animation preferences.
/// The synchronous visible set bridges the pending->confirmed render transaction;
/// timers only expire an acknowledgement that this mounted view actually saw live.
struct AssistantActivityFocusAcknowledgement: Equatable {
    private(set) var observedLiveIDs = Set<String>()
    private(set) var acknowledgedIDs = Set<String>()
    func visibleIDs(openIDs: Set<String>, confirmedIDs: Set<String>) -> Set<String> {
        openIDs.union(acknowledgedIDs).union(observedLiveIDs.intersection(confirmedIDs))
    }
    mutating func observe(openIDs: Set<String>, confirmedIDs: Set<String>) -> Set<String> {
        let newlyConfirmed = observedLiveIDs.subtracting(openIDs).intersection(confirmedIDs)
        acknowledgedIDs.formUnion(newlyConfirmed)
        observedLiveIDs = openIDs
        return newlyConfirmed
    }
    mutating func expire(_ id: String) { acknowledgedIDs.remove(id) }
}
