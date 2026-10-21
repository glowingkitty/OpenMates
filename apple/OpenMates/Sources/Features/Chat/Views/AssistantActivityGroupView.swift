// Web: frontend/packages/ui/src/components/AssistantActivityGroup.svelte
//      frontend/packages/ui/src/components/LoadedMemoryPills.svelte
//      frontend/packages/ui/src/utils/loadedMemoryDisplay.ts
// Desktop metrics: root's pinned 78e8d990 browser-computed receipt (2026-10-19).
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.streaming.progressive-presentation,
//             chats.rendering.assistant-document-convergence, chats.surface.semantic-parity

import SwiftUI

struct AssistantActivityConfiguration {
    let chatID: String
    let responseActive: Bool
    let thinkingContent: String
    let thinkingStreaming: Bool
    let memories: [ChatAppliedMemory]
    let embeds: [String: EmbedRecord]
    let completedSubChatIDs: Set<String>
    let viewportWidth: CGFloat
    var messageID: String? = nil
    var subChatProgress: SubChatProgress? = nil
    var childStore: ChatStore? = nil
}

/// Request activity belongs only to the final overall run. Live Focus and
/// sub-chat work can keep earlier groups open without making their skills live.
struct AssistantActivityRunState {
    let active: Bool
    let usingApps: Bool

    init(segment: AssistantActivitySegment, finalSegmentID: String?, responseActive: Bool,
         thinkingStreaming: Bool, openFocusIDs: Set<String>, activeBatchIDs: Set<String>) {
        let requestActive = responseActive && segment.id == finalSegmentID
        usingApps = requestActive && segment.items.contains { $0.kind == .skill && !$0.terminal }
        active = segment.isActive(responseActive: requestActive, thinkingStreaming: thinkingStreaming,
            openFocusIDs: openFocusIDs, activeBatchIDs: activeBatchIDs)
    }
}

struct AssistantActivitySegmentsView<BlockContent: View>: View {
    let configuration: AssistantActivityConfiguration
    let blockContent: (ProgressiveMarkdownBlock) -> BlockContent
    private let blocks: [ProgressiveMarkdownBlock]
    @StateObject private var childObserver: SubChatActivityStoreObserver
    @ObservedObject private var pendingFocus = PendingProjectFocusStore.shared
    @State private var focusAcknowledgement = AssistantActivityFocusAcknowledgement()
    @State private var batchCompletion = SubChatActivityCompletionState()
    @State private var acknowledgementTasks: [String: Task<Void, Never>] = [:]

    init(blocks: [ProgressiveMarkdownBlock], configuration: AssistantActivityConfiguration,
         @ViewBuilder blockContent: @escaping (ProgressiveMarkdownBlock) -> BlockContent) {
        self.configuration = configuration
        self.blockContent = blockContent
        self.blocks = blocks
        let hasBatches = blocks.contains { $0.document.subChatBatch != nil }
        _childObserver = StateObject(wrappedValue: SubChatActivityStoreObserver(store: hasBatches ? configuration.childStore : nil))
    }

    private var observedChildStore: ChatStore? {
        blocks.contains { $0.document.subChatBatch != nil } ? configuration.childStore : nil
    }

    private var openFocusIDs: Set<String> {
        Set(pendingFocus.entries.values.filter {
            $0.record.chatID == configuration.chatID && ($0.status == .waiting || $0.status == .confirming || $0.status == .committing)
        }.map { $0.record.embedID })
    }

    private var confirmedFocusIDs: Set<String> {
        Set(pendingFocus.entries.values.filter {
            $0.record.chatID == configuration.chatID && $0.status == .activated
        }.map { $0.record.embedID })
    }

    var body: some View {
        let batches = blocks.compactMap { $0.document.subChatBatch }
        let knownChildIDs = Set(batches.flatMap(\.subChatIDs))
        let terminalChildIDs = childObserver.terminalChildIDs(descriptors: batches, parentID: configuration.chatID)
            .union(configuration.completedSubChatIDs.intersection(knownChildIDs))
        let updatedBlocks = AssistantActivityProjection.updatingBatchStatuses(in: blocks, parentID: configuration.chatID,
            messageID: configuration.messageID, progress: configuration.subChatProgress, terminalChildIDs: terminalChildIDs,
            retainedTerminalStatuses: batchCompletion.terminalStatuses)
        let segments = AssistantActivityProjection.segments(blocks: updatedBlocks, embeds: configuration.embeds,
            completedSubChatIDs: terminalChildIDs)
        let firstActivityID = segments.first(where: \.isActivity)?.id
        let finalSegmentID = segments.last?.id
        let activeBatchIDs = Set(segments.flatMap(\.items).filter { $0.kind == .subChats && !$0.terminal }.map(\.id))
        let visibleFocusIDs = focusAcknowledgement.visibleIDs(openIDs: openFocusIDs, confirmedIDs: confirmedFocusIDs)
        VStack(alignment: .leading, spacing: .spacing3) {
            if firstActivityID == nil && (!configuration.thinkingContent.isEmpty || configuration.thinkingStreaming || !configuration.memories.isEmpty) {
                AssistantActivityGroupView(configuration: configuration, segment: nil,
                    thinking: configuration.thinkingContent, thinkingStreaming: configuration.thinkingStreaming, memories: configuration.memories,
                    active: configuration.thinkingStreaming || (configuration.responseActive && !configuration.memories.isEmpty),
                    openFocusIDs: [], content: { EmptyView() })
                    .id("response-activity")
            }
            ForEach(segments) { segment in
                if segment.isActivity {
                    let first = segment.id == firstActivityID
                    let state = AssistantActivityRunState(segment: segment, finalSegmentID: finalSegmentID,
                        responseActive: configuration.responseActive,
                        thinkingStreaming: first && configuration.thinkingStreaming,
                        openFocusIDs: visibleFocusIDs, activeBatchIDs: activeBatchIDs)
                    AssistantActivityGroupView(configuration: configuration, segment: segment,
                        thinking: first ? configuration.thinkingContent : "", thinkingStreaming: first && configuration.thinkingStreaming,
                        memories: first ? configuration.memories : [], active: state.active, usingApps: state.usingApps,
                        openFocusIDs: openFocusIDs) {
                            AssistantActivityRunBody(segment: segment, active: state.active,
                                visibleFocusIDs: visibleFocusIDs, activeBatchIDs: activeBatchIDs, blockContent: blockContent)
                        }
                } else {
                    ForEach(segment.units) { unit in blockContent(unit.block) }
                }
            }
        }
        .onAppear {
            childObserver.bind(observedChildStore)
            batchCompletion.observe(configuration.subChatProgress, descriptors: batches,
                parentID: configuration.chatID, messageID: configuration.messageID)
            _ = focusAcknowledgement.observe(openIDs: openFocusIDs, confirmedIDs: confirmedFocusIDs)
        }
        .onChange(of: configuration.subChatProgress) { _, current in
            batchCompletion.observe(current, descriptors: batches, parentID: configuration.chatID, messageID: configuration.messageID)
        }
        .onChange(of: observedChildStore.map { ObjectIdentifier($0) }) { _, _ in childObserver.bind(observedChildStore) }
        .onChange(of: openFocusIDs) { _, current in
            // A history mount has no prior live waiting entry and cannot replay
            // the acknowledgement. Only an observed live activation lingers.
            for id in focusAcknowledgement.observe(openIDs: current, confirmedIDs: confirmedFocusIDs) {
                acknowledgementTasks[id]?.cancel()
                acknowledgementTasks[id] = Task { @MainActor in
                    try? await Task.sleep(for: .seconds(1))
                    guard !Task.isCancelled else { return }
                    focusAcknowledgement.expire(id); acknowledgementTasks.removeValue(forKey: id)
                }
            }
        }
        .onDisappear {
            acknowledgementTasks.values.forEach { $0.cancel() }
            acknowledgementTasks = [:]; focusAcknowledgement = AssistantActivityFocusAcknowledgement()
        }
    }
}

private struct AssistantActivityManualDisclosureKey: EnvironmentKey {
    static let defaultValue = false
}
private extension EnvironmentValues {
    var assistantActivityManuallyControlled: Bool {
        get { self[AssistantActivityManualDisclosureKey.self] }
        set { self[AssistantActivityManualDisclosureKey.self] = newValue }
    }
}

private struct AssistantActivityRunBody<BlockContent: View>: View {
    let segment: AssistantActivitySegment
    let active: Bool
    let visibleFocusIDs: Set<String>
    let activeBatchIDs: Set<String>
    let blockContent: (ProgressiveMarkdownBlock) -> BlockContent
    @Environment(\.assistantActivityManuallyControlled) private var manuallyControlled
    var body: some View {
        ForEach(AssistantActivityProjection.visibleUnits(in: segment,
            automaticallyExpandedActive: active && !manuallyControlled,
            visibleFocusIDs: visibleFocusIDs, activeBatchIDs: activeBatchIDs)) { unit in
            blockContent(unit.block)
        }
    }
}

struct AssistantActivityGroupView<Content: View>: View {
    let configuration: AssistantActivityConfiguration
    let segment: AssistantActivitySegment?
    let thinking: String
    let thinkingStreaming: Bool
    let memories: [ChatAppliedMemory]
    let active: Bool
    var usingApps: Bool = false
    let openFocusIDs: Set<String>
    @ViewBuilder let content: Content
    @State private var disclosure = AssistantActivityDisclosureState()
    @ObservedObject private var pendingFocus = PendingProjectFocusStore.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var summaryState: AssistantActivitySummaryState {
        let items = segment?.items ?? []
        let cancelled = items.filter { item in
            item.kind == .focus && pendingFocus.entry(chatID: configuration.chatID, embedID: item.id)?.status == .cancelled
        }
        let focuses = items.filter { item in item.kind == .focus && !cancelled.contains(where: { $0.id == item.id }) }
        return .init(apps: (segment?.appIDs ?? []).map(AssistantActivityCopy.appName),
            memories: memories.map(AssistantActivityCopy.memoryName),
            focuses: focuses.compactMap { item in
                guard let embed = configuration.embeds[item.id] else { return nil }
                let focusID = embed.rawData?["focus_id"]?.value as? String ?? ""
                let fallback = focusID.split(separator: "-").dropFirst().joined(separator: " ").replacingOccurrences(of: "_", with: " ").localizedCapitalized
                let name = embed.rawData?["focus_mode_name"]?.value as? String ?? fallback
                let translated = AppStrings.localized(name)
                return translated == name && name.contains(".") ? fallback : translated
            },
            thinking: !thinking.isEmpty,
            usingApps: usingApps,
            thinkingStreaming: thinkingStreaming,
            activatingFocus: focuses.contains { openFocusIDs.contains($0.id) },
            subChats: items.contains { $0.kind == .subChats },
            workingSubChats: items.contains { $0.kind == .subChats && !$0.terminal },
            active: active, cancelledFocus: !cancelled.isEmpty)
    }
    private var summaries: [String] { AssistantActivityCopy.summaries(summaryState) }
    private var iconIDs: [String] {
        var seen = Set<String>()
        let values = (!thinking.isEmpty ? ["ai"] : []) + memories.compactMap(\.appId)
            + (segment?.appIDs ?? []) + (segment?.items.filter { $0.kind == .focus }.compactMap(\.appID) ?? [])
            + ((segment?.items.contains { $0.kind == .subChats } ?? false) ? ["ai"] : [])
        return Array(values.filter { seen.insert($0).inserted }.prefix(3))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.15)) { disclosure.toggle() }
            } label: {
                HStack(spacing: .spacing2) {
                    HStack(spacing: -CGFloat.spacing4) {
                        ForEach(Array(iconIDs.enumerated()), id: \.element) { index, app in
                            AppIconView(appId: app, size: 18)
                                .frame(width: 22, height: 22)
                                .background(Color.grey0, in: Circle())
                                .overlay(Circle().strokeBorder(Color.grey0, lineWidth: 2))
                                .clipShape(Circle()).zIndex(Double(3 - index))
                        }
                        if iconIDs.isEmpty { Icon("reasoning", size: 16) }
                    }.accessibilityHidden(true)
                    ActivitySummaryLabel(candidates: summaries, lines: configuration.viewportWidth >= 768 ? 1 : 2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Icon(disclosure.expanded ? "up" : "down", size: 8).accessibilityHidden(true)
                }
                .font(.omSmall.weight(.medium)).foregroundStyle(Color.fontPrimary)
                .padding(.vertical, .spacing1).padding(.horizontal, .spacing3)
                .frame(maxWidth: .infinity, minHeight: 30, alignment: .leading)
                .background(Color.grey10)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.trailing, .spacing5)
            .accessibilityLabel(summaries.first ?? AppStrings.thinkingHeaderDone)
            .accessibilityValue(disclosure.expanded ? AppStrings.thinkingCollapse : AppStrings.thinkingExpand)
            .accessibilityIdentifier("assistant-activity-toggle")
            if disclosure.expanded {
                VStack(alignment: .leading, spacing: .spacing3) {
                    if !memories.isEmpty { LoadedMemoryPillsView(memories: memories) }
                    if !thinking.isEmpty || thinkingStreaming {
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(AppStrings.localized("chat.response_activity.response_thinking"))
                                .font(.omSmall.weight(.semibold)).foregroundStyle(Color.grey70)
                            ThinkingSectionView(content: thinking, isStreaming: thinkingStreaming)
                        }.accessibilityIdentifier("assistant-response-thinking")
                    }
                    content.environment(\.assistantActivityManuallyControlled, disclosure.userToggled)
                }
                .padding(.top, .spacing2).padding(.horizontal, .spacing4).padding(.bottom, .spacing4)
                .frame(maxWidth: .infinity, alignment: .leading).background(Color.grey10)
                .accessibilityIdentifier("assistant-activity-body")
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .padding(.vertical, .spacing2)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("assistant-activity-group")
        .onAppear { disclosure.synchronize(active: active) }
        .onChange(of: active) { _, value in disclosure.synchronize(active: value) }
    }
}

private struct ActivitySummaryLabel: View {
    let candidates: [String]
    let lines: Int
    var body: some View {
        ViewThatFits(in: .vertical) {
            ForEach(candidates, id: \.self) { candidate in
                Text(candidate).fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxHeight: 18.9 * CGFloat(lines), alignment: .leading)
        .clipped().accessibilityHidden(true)
    }
}

@MainActor
enum AssistantActivityCopy {
    static func appName(_ id: String) -> String {
        let key = "apps." + id
        let localized = AppStrings.localized(key)
        return localized == key ? id.replacingOccurrences(of: "_", with: " ").localizedCapitalized : localized
    }
    static func memoryName(_ memory: ChatAppliedMemory) -> String {
        if memory.source == "app", let app = memory.appId, memory.id.hasPrefix("app:\(app):"),
           let colon = memory.title.firstIndex(of: ":") {
            let suffix = memory.title[memory.title.index(after: colon)...].trimmingCharacters(in: .whitespacesAndNewlines)
            if !suffix.isEmpty { return suffix }
        }
        return memory.title
    }
    static func summaries(_ state: AssistantActivitySummaryState) -> [String] {
        let manager = LocalizationManager.shared
        let candidates = AssistantActivitySummary.candidates(state) { key, values in
            let raw = manager.text(key)
            guard raw != key else { return "" }
            return AssistantActivityMessageFormat.format(raw, values: values, language: manager.currentLanguage.code) ?? ""
        }.filter { !$0.isEmpty }
        return candidates.isEmpty ? [AppStrings.thinkingHeaderDone] : candidates
    }
}

struct LoadedMemoryPillsView: View {
    let memories: [ChatAppliedMemory]
    var body: some View {
        LoadedMemoryFlowLayout {
            ForEach(memories, id: \.id) { memory in LoadedMemoryPill(memory: memory).id(memory.id + ":" + memory.revision) }
        }
        .accessibilityIdentifier("loaded-memory-pills")
    }
}

private struct LoadedMemoryPill: View {
    let memory: ChatAppliedMemory
    @State private var expanded = false
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Button { expanded.toggle() } label: {
                HStack(spacing: .spacing3) {
                    AppIconView(appId: memory.appId ?? "ai", size: 18).accessibilityHidden(true)
                    Text(AssistantActivityCopy.memoryName(memory)).font(.omSmall).multilineTextAlignment(.leading)
                }
                .foregroundStyle(Color.fontPrimary)
                .padding(.vertical, .spacing2).padding(.leading, .spacing2).padding(.trailing, .spacing4)
                .frame(minHeight: 32).background(Color.grey0, in: Capsule())
                .overlay(Capsule().stroke(Color.grey30, lineWidth: 1))
            }.buttonStyle(.plain).accessibilityIdentifier("loaded-memory-pill")
            if expanded {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(memory.title).font(.omSmall.weight(.semibold))
                    Text(([AppStrings.localized("memories.source_" + memory.source), memory.appId, memory.projectId].compactMap { $0 }).joined(separator: " · "))
                    Text(AppStrings.localized("rules.revision") + " " + memory.revision)
                        .font(.omSmall.monospaced()).textSelection(.enabled).accessibilityIdentifier("applied-rule-revision")
                    ViewThatFits(in: .vertical) {
                        memoryBody.fixedSize(horizontal: false, vertical: true)
                        ScrollView { memoryBody }
                    }.frame(maxHeight: 512)
                }
                .font(.omSmall).foregroundStyle(Color.fontPrimary).padding(.spacing4)
                .frame(maxWidth: 544, alignment: .leading)
                .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius4))
                .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(Color.grey25, lineWidth: 1))
                .accessibilityIdentifier("applied-memory")
            }
        }.accessibilityElement(children: .contain).accessibilityIdentifier("loaded-memory-details")
    }
    private var memoryBody: some View {
        Text(memory.body).font(.omSmall).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
            .accessibilityIdentifier("applied-memory-body")
            .padding(.spacing4).background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius4))
    }
}

private struct LoadedMemoryFlowLayout: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrangement(width: proposal.width ?? 544, subviews: subviews).size
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrangement(width: bounds.width, subviews: subviews)
        for (index, item) in subviews.enumerated() {
            item.place(at: CGPoint(x: bounds.minX + result.origins[index].x, y: bounds.minY + result.origins[index].y),
                proposal: ProposedViewSize(width: result.sizes[index].width, height: result.sizes[index].height))
        }
    }
    private func arrangement(width: CGFloat, subviews: Subviews) -> (size: CGSize, origins: [CGPoint], sizes: [CGSize]) {
        var origins: [CGPoint] = []; var sizes: [CGSize] = []
        var x: CGFloat = 0; var y: CGFloat = 0; var rowHeight: CGFloat = 0; var usedWidth: CGFloat = 0
        for item in subviews {
            let size = item.sizeThatFits(ProposedViewSize(width: max(0, width), height: nil))
            if x > 0 && x + size.width > width { x = 0; y += rowHeight + .spacing3; rowHeight = 0 }
            origins.append(CGPoint(x: x, y: y)); sizes.append(size)
            usedWidth = max(usedWidth, x + size.width); x += size.width + .spacing3; rowHeight = max(rowHeight, size.height)
        }
        return (CGSize(width: usedWidth, height: y + rowHeight), origins, sizes)
    }
}
