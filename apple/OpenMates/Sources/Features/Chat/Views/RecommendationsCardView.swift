// RecommendationsCardView — the Recommendations container between the chat
// history and the follow-up suggestions: the chat-category gradient card with a
// heading naming the kind (memory/workflow) and whether it is new or an update,
// the entry as an embed preview card, a Create/Update pill button, an optional
// status line, and previous/next buttons with one dot per recommendation.
// Presentational only: the caller owns the items (already decrypted) and what
// the action opens. No dismiss control, like the web.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/RecommendationsCard.svelte
//          frontend/packages/ui/src/components/RecommendationEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/types/recommendations.ts
// CSS:     RecommendationsCard.svelte <style>: .recommendations-card, ::before highlights,
//          .heading, .recommendation, .action, .status, .pager, .icon-button, .dots, .dot
//          RecommendationEmbedPreview.svelte <style>: .recommendation-preview, strong, .summary
// Tokens:  ColorTokens.generated.swift (fontButton, fontPrimary, fontSecondary, grey25),
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift,
//          GradientTokens.generated.swift (primary, via CategoryMapping)
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.suggestions.post-processor
// Plan: docs/plans/apple-client-core-migration/plan.yml (parity_audit_2026_11_12, Recommendations card)
//
// Not mounted in ChatView yet: the Apple client-core binding exposes no chat
// recommendations (chats.encrypted_recommendations / post_processing_completed
// .recommendations) and no memory/workflow draft to open. The card renders from
// whatever items a caller passes.

import SwiftUI

/// One recommendation (`ChatRecommendation` in types/recommendations.ts).
struct ChatRecommendation: Identifiable, Equatable, Sendable {
    enum Kind: String, Sendable { case memory, workflow }
    enum Action: String, Sendable { case create, update }

    let id: String
    let kind: Kind
    let action: Action
    let targetID: String?
    let title: String
    let summary: String
}

struct RecommendationsCardView: View {
    private enum Layout {
        /// UnifiedEmbedPreview compact card: 300 × 200, radius 30px.
        static let embedWidth: CGFloat = 300
        static let embedHeight: CGFloat = 200
        static let embedCornerRadius: CGFloat = 30
        /// result-embeds.md: 48px left/right text safety gap on compact cards.
        static let embedTextInset: CGFloat = 48
        /// `.action` / `.icon-button` min-height and size: 2.25rem.
        static let controlSize: CGFloat = 36
        /// `.icon-button .clickable-icon`: 1.1rem.
        static let pagerIconSize: CGFloat = 17.6
        /// `.dot`: 0.5rem.
        static let dotSize: CGFloat = 8
        /// color-mix(font-button 24% / 45%) fills and highlight strengths.
        static let controlFill: Double = 0.24
        static let dotFill: Double = 0.45
        static let statusOpacity: Double = 0.9
    }

    let items: [ChatRecommendation]
    /// Chat category; selects the gradient the quick tips card used.
    let category: String?
    /// Recommendation whose draft is being prepared (actions disabled meanwhile).
    let busyID: String?
    /// Optional status line for the visible recommendation.
    let statusText: String?
    let onAction: (ChatRecommendation) -> Void

    @State private var index = 0

    private var current: Int { items.isEmpty ? 0 : min(index, items.count - 1) }
    private var item: ChatRecommendation? { items.indices.contains(current) ? items[current] : nil }
    private var multiple: Bool { items.count > 1 }

    var body: some View {
        if let item {
            VStack(spacing: .spacing4) {
                Text(AppStrings.recommendationsHeading(kind: item.kind.rawValue, action: item.action.rawValue))
                    .font(.omP.weight(.heavy))
                    .foregroundStyle(Color.fontButton)
                    .multilineTextAlignment(.center)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("recommendation-heading")
                recommendation(item)
                pager
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, .spacing5)
            .padding(.horizontal, .spacing4)
            .background { cardBackground }
            .clipShape(RoundedRectangle(cornerRadius: .radius6))
            .shadow(color: .black.opacity(0.16), radius: 12, x: 0, y: 8)
            .foregroundStyle(Color.fontButton)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(AppStrings.recommendationsCardTitle)
            .accessibilityIdentifier("recommendations-card")
            .accessibilityValue("\(current + 1)/\(items.count)")
        }
    }

    // MARK: - Background

    /// Category gradient (135deg) plus the two soft `::before` radial highlights.
    private var cardBackground: some View {
        ZStack {
            Rectangle().fill(category.map { CategoryMapping.gradient(for: $0) } ?? LinearGradient.primary)
            GeometryReader { geometry in
                let size = max(geometry.size.width, geometry.size.height)
                ZStack {
                    RadialGradient(colors: [Color.fontButton.opacity(0.45), Color.fontButton.opacity(0)],
                                   center: UnitPoint(x: 0.15, y: 0.2), startRadius: 0, endRadius: size * 0.24)
                    RadialGradient(colors: [Color.fontButton.opacity(0.22), Color.fontButton.opacity(0)],
                                   center: UnitPoint(x: 0.86, y: 0.82), startRadius: 0, endRadius: size * 0.32)
                }
            }
            .allowsHitTesting(false)
        }
        .accessibilityHidden(true)
    }

    // MARK: - Recommendation

    private func recommendation(_ item: ChatRecommendation) -> some View {
        VStack(spacing: .spacing4) {
            embedPreview(item)
                .id(item.id)
            Button { open(item) } label: {
                Text(item.action == .update ? AppStrings.recommendationsUpdate : AppStrings.recommendationsCreate)
                    .font(.omSmall.weight(.bold))
                    .foregroundStyle(Color.fontButton)
                    .padding(.vertical, .spacing2)
                    .padding(.horizontal, .spacing6)
                    .frame(minHeight: Layout.controlSize)
                    .background(Capsule().fill(Color.fontButton.opacity(Layout.controlFill)))
            }
            .buttonStyle(.plain)
            .disabled(busyID != nil)
            .accessibilityIdentifier("recommendation-action")
            if let status = busyID == item.id ? AppStrings.recommendationsPreparing : statusText {
                Text(status)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontButton)
                    .multilineTextAlignment(.center)
                    .opacity(Layout.statusOpacity)
                    .accessibilityIdentifier("recommendation-status")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recommendation-item")
        .accessibilityValue("\(item.kind.rawValue):\(item.action.rawValue):\(item.id)")
    }

    /// RecommendationEmbedPreview: presentation-only UnifiedEmbedPreview whose
    /// header names the type and whose body shows only title and summary.
    private func embedPreview(_ item: ChatRecommendation) -> some View {
        let isMemory = item.kind == .memory
        return Button { open(item) } label: {
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(item.title)
                        .font(.omSmall.weight(.bold))
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(2)
                        .accessibilityIdentifier("recommendation-title")
                    Text(item.summary)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(3)
                        .accessibilityIdentifier("recommendation-summary")
                }
                .multilineTextAlignment(.leading)
                .padding(.vertical, .spacing4)
                .padding(.horizontal, Layout.embedTextInset)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                EmbedBasicInfoBar(appId: isMemory ? "openmates" : "workflows",
                                  appIconName: isMemory ? "insight" : "workflow",
                                  skillIconName: isMemory ? "insight" : "workflow",
                                  title: isMemory ? AppStrings.recommendationsTypeMemory : AppStrings.recommendationsTypeWorkflow,
                                  subtitle: nil, faviconURL: nil, showSkillIcon: false)
            }
            .frame(width: Layout.embedWidth, height: Layout.embedHeight)
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: Layout.embedCornerRadius))
            .shadow(color: .black.opacity(0.16), radius: 12, x: 0, y: 8)
            .shadow(color: .black.opacity(0.1), radius: 3, x: 0, y: 2)
        }
        .buttonStyle(.plain)
        .disabled(busyID != nil)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recommendation-embed")
        .accessibilityValue(item.kind.rawValue)
    }

    // MARK: - Pager

    private var pager: some View {
        HStack(spacing: .spacing3) {
            if multiple {
                pagerButton(mirrored: false, label: AppStrings.recommendationsPrevious,
                            identifier: "recommendation-previous") { show(current - 1) }
            }
            HStack(spacing: .spacing2) {
                ForEach(Array(items.enumerated()), id: \.element.id) { position, _ in
                    Button { show(position) } label: {
                        Circle()
                            .fill(position == current ? Color.fontButton : Color.fontButton.opacity(Layout.dotFill))
                            .frame(width: Layout.dotSize, height: Layout.dotSize)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.recommendationsPosition(current: position + 1, total: items.count))
                    .accessibilityAddTraits(position == current ? .isSelected : [])
                    .accessibilityIdentifier("recommendation-dot")
                }
            }
            if multiple {
                pagerButton(mirrored: true, label: AppStrings.recommendationsNext,
                            identifier: "recommendation-next") { show(current + 1) }
            }
        }
    }

    private func pagerButton(mirrored: Bool, label: String, identifier: String,
                             action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon("back", size: Layout.pagerIconSize)
                .foregroundStyle(Color.fontButton)
                .scaleEffect(x: mirrored ? -1 : 1, y: 1)
                .frame(width: Layout.controlSize, height: Layout.controlSize)
                .background(Circle().fill(Color.fontButton.opacity(Layout.controlFill)))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier(identifier)
    }

    // MARK: - Actions

    private func show(_ next: Int) {
        guard !items.isEmpty else { return }
        index = (next % items.count + items.count) % items.count
    }

    private func open(_ target: ChatRecommendation) {
        guard busyID == nil else { return }
        onAction(target)
    }
}
