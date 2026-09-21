// Embed grouping system — groups consecutive same-type embeds into carousels.
// Mirrors the web app's GroupRenderer + groupHandlers.
// Groups search results horizontally, code blocks vertically, etc.

import SwiftUI

struct EmbedGroup: Identifiable {
    let id: String
    let type: EmbedType
    let embeds: [EmbedRecord]
    let isAppSkillUse: Bool

    var displayName: String {
        if isAppSkillUse {
            return "\(embeds.count) app skill\(embeds.count == 1 ? "" : "s") used:"
        }
        return type.displayName
    }

    var appId: String? { isAppSkillUse ? nil : type.appId }
    var isHorizontal: Bool {
        if isAppSkillUse {
            return true
        }
        switch type {
        case .webWebsite, .videosVideo, .imagesImageResult, .mapsPlace,
             .travelConnection, .travelStay, .shoppingProduct, .nutritionRecipe,
             .eventsEvent, .homeListing, .healthAppointment:
            return true
        default:
            return false
        }
    }
}

/// Keep the selected result stable while hydration inserts/reorders siblings.
/// A disappeared selection falls back to the requested route, then the first
/// remaining result. Parent routing remains owned by the presenting ChatView.
struct EmbedFullscreenSelection: Equatable {
    private(set) var selectedID: String?

    init() { selectedID = nil }

    func resolvedID(in embeds: [EmbedRecord], initialID: String) -> String? {
        if let selectedID, embeds.contains(where: { $0.id == selectedID }) { return selectedID }
        if embeds.contains(where: { $0.id == initialID }) { return initialID }
        return embeds.first?.id
    }

    mutating func reconcile(in embeds: [EmbedRecord], initialID: String) {
        selectedID = resolvedID(in: embeds, initialID: initialID)
    }

    @discardableResult
    mutating func move(by offset: Int, in embeds: [EmbedRecord], initialID: String) -> Bool {
        guard let active = resolvedID(in: embeds, initialID: initialID),
              let index = embeds.firstIndex(where: { $0.id == active }),
              embeds.indices.contains(index + offset) else { return false }
        selectedID = embeds[index + offset].id
        return true
    }
}

enum EmbedGrouper {
    private static let appSkillUseGroupKey = "app-skill-use"
    private static let inlineDisplayLimit = 6

    /// Web WebSearchEmbedFullscreen opens a result within its ordered result
    /// group. Its parent remains a separate route restored by Minimize; it is
    /// never an extra "previous result". Use the same group in chat and preview.
    static func fullscreenNavigationEmbeds(
        selected: EmbedRecord,
        messageEmbeds: [EmbedRecord],
        allRecords: [String: EmbedRecord],
        parent explicitParent: EmbedRecord? = nil
    ) -> [EmbedRecord] {
        let parent = explicitParent.map { allRecords[$0.id] ?? $0 }
            ?? selected.parentEmbedId.flatMap { allRecords[$0] }
            ?? allRecords.values.filter { $0.childEmbedIds.contains(selected.id) }
                .sorted { $0.id < $1.id }.first
        if let parent, parent.id != selected.id {
            let ids = parent.childEmbedIds.isEmpty
                ? allRecords.values.filter { $0.parentEmbedId == parent.id }
                    .sorted { ($0.createdAt ?? "", $0.id) < ($1.createdAt ?? "", $1.id) }
                    .map(\.id)
                : parent.childEmbedIds
            var seen = Set<String>()
            let siblings = ids.compactMap { id -> EmbedRecord? in
                guard id != parent.id, seen.insert(id).inserted else { return nil }
                return id == selected.id ? selected : allRecords[id]
            }
            if siblings.contains(where: { $0.id == selected.id }) { return siblings }
        }
        var seen = Set<String>()
        let messageIDs = Set(messageEmbeds.map(\.id))
        let groupedChildIDs = Set(messageEmbeds.flatMap(\.childEmbedIds))
        let messageGroup = messageEmbeds.compactMap { embed -> EmbedRecord? in
            guard seen.insert(embed.id).inserted else { return nil }
            if embed.id == selected.id { return selected }
            // Inline citations can put children and their parent in the same
            // message refs. A parent-level route still navigates only peers.
            guard !groupedChildIDs.contains(embed.id),
                  !(embed.parentEmbedId.map(messageIDs.contains) ?? false) else { return nil }
            return embed
        }
        return messageGroup.contains(where: { $0.id == selected.id }) ? messageGroup : [selected]
    }

    static func group(_ embeds: [EmbedRecord]) -> [EmbedGroup] {
        guard !embeds.isEmpty else { return [] }

        var groups: [EmbedGroup] = []
        var currentGroupKey: String?
        var currentBatch: [EmbedRecord] = []

        func appendCurrentBatch() {
            guard !currentBatch.isEmpty,
                  let type = EmbedType(rawValue: currentBatch[0].type) else { return }
            groups.append(EmbedGroup(
                id: currentBatch[0].id,
                type: type,
                embeds: currentBatch,
                isAppSkillUse: currentGroupKey == appSkillUseGroupKey
            ))
        }

        for embed in embeds {
            let groupKey = groupKey(for: embed)
            if groupKey == currentGroupKey {
                currentBatch.append(embed)
            } else {
                appendCurrentBatch()
                currentGroupKey = groupKey
                currentBatch = [embed]
            }
        }

        appendCurrentBatch()

        return groups
    }

    static func groupForInlineDisplay(_ embeds: [EmbedRecord]) -> [EmbedGroup] {
        group(Array(embeds.prefix(inlineDisplayLimit)))
    }

    private static func groupKey(for embed: EmbedRecord) -> String {
        if let data = embed.data,
           case .raw(let dict) = data,
           (dict["type"]?.value as? String) == "app_skill_use" {
            return appSkillUseGroupKey
        }
        return embed.type
    }
}

// MARK: - Grouped embed display

struct GroupedEmbedView: View {
    let group: EmbedGroup
    let allEmbedRecords: [String: EmbedRecord]
    let onEmbedTap: (EmbedRecord) -> Void

    init(group: EmbedGroup, allEmbedRecords: [String: EmbedRecord] = [:], onEmbedTap: @escaping (EmbedRecord) -> Void) {
        self.group = group
        self.allEmbedRecords = allEmbedRecords
        self.onEmbedTap = onEmbedTap
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if group.embeds.count > 1 || group.isAppSkillUse {
                HStack(spacing: .spacing2) {
                    if let appId = group.appId {
                        AppIconView(appId: appId, size: 20)
                    }
                    Text(group.isAppSkillUse ? group.displayName : "\(group.embeds.count) \(group.displayName.lowercased())")
                        .font(.omXs)
                        .fontWeight(group.isAppSkillUse ? .bold : .regular)
                        .foregroundStyle(Color.fontTertiary)
                }
            }

            if group.isHorizontal {
                horizontalCarousel
            } else {
                verticalStack
            }
        }
    }

    private var horizontalCarousel: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            LazyHStack(spacing: .spacing3) {
                ForEach(Array(group.embeds.reversed())) { embed in
                    EmbedPreviewCard(embed: embed, allEmbedRecords: allEmbedRecords) {
                        onEmbedTap(embed)
                    }
                    .frame(width: 300, height: 200)
                }
            }
        }
        .frame(height: 200)
    }

    private var verticalStack: some View {
        VStack(spacing: .spacing3) {
            ForEach(Array(group.embeds.reversed())) { embed in
                EmbedPreviewCard(embed: embed, allEmbedRecords: allEmbedRecords) {
                    onEmbedTap(embed)
                }
                .frame(height: 200)
            }
        }
    }
}
