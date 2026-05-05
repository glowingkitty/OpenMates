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

enum EmbedGrouper {
    private static let appSkillUseGroupKey = "app-skill-use"

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
