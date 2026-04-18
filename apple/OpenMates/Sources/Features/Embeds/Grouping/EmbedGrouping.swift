// Embed grouping system — groups consecutive same-type embeds into carousels.
// Mirrors the web app's GroupRenderer + groupHandlers.
// Groups search results horizontally, code blocks vertically, etc.

import SwiftUI

struct EmbedGroup: Identifiable {
    let id: String
    let type: EmbedType
    let embeds: [EmbedRecord]

    var displayName: String { type.displayName }
    var appId: String? { type.appId }
    var isHorizontal: Bool {
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
    static func group(_ embeds: [EmbedRecord]) -> [EmbedGroup] {
        guard !embeds.isEmpty else { return [] }

        var groups: [EmbedGroup] = []
        var currentType: String?
        var currentBatch: [EmbedRecord] = []

        for embed in embeds {
            if embed.type == currentType {
                currentBatch.append(embed)
            } else {
                if !currentBatch.isEmpty, let type = EmbedType(rawValue: currentBatch[0].type) {
                    groups.append(EmbedGroup(
                        id: currentBatch[0].id,
                        type: type,
                        embeds: currentBatch
                    ))
                }
                currentType = embed.type
                currentBatch = [embed]
            }
        }

        if !currentBatch.isEmpty, let type = EmbedType(rawValue: currentBatch[0].type) {
            groups.append(EmbedGroup(
                id: currentBatch[0].id,
                type: type,
                embeds: currentBatch
            ))
        }

        return groups
    }
}

// MARK: - Grouped embed display

struct GroupedEmbedView: View {
    let group: EmbedGroup
    let onEmbedTap: (EmbedRecord) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if group.embeds.count > 1 {
                HStack(spacing: .spacing2) {
                    if let appId = group.appId {
                        AppIconView(appId: appId, size: 20)
                    }
                    Text("\(group.embeds.count) \(group.displayName.lowercased())")
                        .font(.omXs)
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
                ForEach(group.embeds) { embed in
                    EmbedPreviewCard(embed: embed) {
                        onEmbedTap(embed)
                    }
                    .frame(width: 240, height: 160)
                }
            }
        }
    }

    private var verticalStack: some View {
        VStack(spacing: .spacing3) {
            ForEach(group.embeds) { embed in
                EmbedPreviewCard(embed: embed) {
                    onEmbedTap(embed)
                }
                .frame(height: 180)
            }
        }
    }
}
