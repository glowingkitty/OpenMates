// Isolated production inspiration layout with local, account-free video metadata.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/DailyInspirationBanner.svelte
//         frontend/packages/ui/src/components/embeds/videos/VideoEmbedPreview.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
#if DEBUG
import SwiftUI

struct DevDailyInspirationFixture: View {
    let variant: String
    let onAction: (String) -> Void

    var body: some View {
        GeometryReader { viewport in
            // Cap to the host: fixture width never overflows a phone canvas.
            let width = min(viewport.size.width, variant == "narrow" ? 390 : 1216)
            let height: CGFloat = variant == "short" ? 150 : width <= 730 ? 190 : 240
            VStack(spacing: .spacing4) {
                InspirationCard(
                    inspiration: DailyInspirationData(inspirationId: "local-inspiration-layout",
                        text: "What if you could redesign the entire onboarding experience of your product in one afternoon?",
                        category: "software_development",
                        video: DailyInspirationVideo(youtubeId: nil,
                            title: "How to Build a Great Developer Experience",
                            channelName: "TechTalks", thumbnailUrl: "", durationSeconds: 847,
                            viewCount: 1_240_000, publishedAt: "2024-01-15T10:00:00Z")),
                    containerSize: CGSize(width: width, height: viewport.size.height),
                    heightOverride: height
                ) { onAction("inspiration-started") }
                .frame(width: width, height: height)
                Spacer(minLength: 0)
            }
            .frame(width: viewport.size.width, height: viewport.size.height, alignment: .top)

        }
    }
}
#endif
