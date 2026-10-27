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
    @State private var previewBounds: [String: CGRect] = [:]
    @State private var presentedWiki: EmbedRecord?
    @State private var loaded = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var scopeRevision: UInt64 = 0
    @State private var fixtureGeneration = UUID()
    private var loading: Bool { (variant == "loading" && !loaded) || (variant == "scope-switch" && scopeRevision > 0) }
    private var fixtureScope: NativeWorkspaceOfflineScope {
        .init(accountID: "local-fixture-owner-\(scopeRevision)", server: "https://fixture.invalid", teamID: nil,
            accountGeneration: fixtureGeneration, teamEpoch: scopeRevision)
    }

    var body: some View {
        GeometryReader { viewport in
            // Cap to the host: fixture width never overflows a phone canvas.
            let width = min(viewport.size.width, variant == "narrow" ? 390 : 1216)
            let height: CGFloat = variant == "short" ? 150 : width <= 730 ? 190 : 240
            VStack(spacing: .spacing4) {
                ZStack {
                    if loading {
                        InspirationCard(inspiration: .init(text: "", category: "general_knowledge"),
                            containerSize: CGSize(width: width, height: viewport.size.height),
                            heightOverride: height, isInteractive: false, isPlaceholder: true, onTap: {})
                            .transition(.opacity)
                    } else {
                        InspirationCard(
                            inspiration: DailyInspirationData(inspirationId: "local-inspiration-layout",
                                text: "What if you could redesign the entire onboarding experience of your product in one afternoon?",
                                category: "software_development",
                                video: variant == "wiki" ? nil : DailyInspirationVideo(youtubeId: nil,
                                    title: variant == "long-title"
                                        ? "Mentorship in Software Engineering: Finding the Right Mentor for Your Next Project"
                                        : "How to Build a Great Developer Experience",
                                    channelName: "TechTalks", thumbnailUrl: "", durationSeconds: 847,
                                    viewCount: 1_240_000, publishedAt: "2024-01-15T10:00:00Z"),
                                contentType: variant == "wiki" ? "wiki" : "video",
                                wiki: variant == "wiki" ? DailyInspirationWiki(title: "Inter-process communication",
                                    wikiTitle: "Inter-process communication", description: "Communication between computer processes",
                                    thumbnailUrl: nil, wikidataId: "Q214466", extract: nil) : nil),
                            containerSize: CGSize(width: width, height: viewport.size.height),
                            heightOverride: height,
                            isInteractive: variant != "read-only",
                            onOpenWiki: { presentedWiki = $0 }
                        ) { onAction("inspiration-started") }
                            .transition(.opacity)
                    }
                }
                .frame(width: width, height: height)
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: loading)
                .modifier(DailyInspirationScopeBoundary(scope: fixtureScope))
                .coordinateSpace(name: "responsive-preview-fixture")
                .onPreferenceChange(EmbedPreviewGeometryKey.self) { previewBounds = $0 }
                if variant == "scope-switch" {
                    Button {
                        scopeRevision &+= 1
                        onAction("inspiration-owner-switched")
                    } label: {
                        Text("Switch inspiration owner")
                            .frame(minHeight: 44)
                            .contentShape(Rectangle())
                    }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("inspiration-fixture-switch-owner")
                }
                if variant == "loading" {
                    Button {
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) { loaded = true }
                        onAction("inspiration-loaded")
                    } label: {
                        Text("Load inspirations")
                            .frame(minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("inspiration-fixture-load")
                }
                Spacer(minLength: 0)
            }
            .overlay {
                if let wiki = presentedWiki {
                    EmbedFullscreenContainer(embeds: [wiki], initialEmbedId: wiki.id,
                        allEmbedRecords: [wiki.id: wiki], chatId: nil, onClose: { presentedWiki = nil })
                }
            }
            .frame(width: viewport.size.width, height: viewport.size.height, alignment: .top)
            .overlay(alignment: .bottomLeading) {
                VStack(spacing: 0) {
                    ForEach(["card", "footer", "circle"], id: \.self) { key in
                        let rect = previewBounds[key] ?? .zero
                        Text(" ").font(.omTiny).foregroundStyle(Color.clear)
                            .frame(width: 1, height: 1).allowsHitTesting(false)
                            .accessibilityLabel("\(rect.minX),\(rect.minY),\(rect.width),\(rect.height)")
                            .accessibilityIdentifier("inspiration-preview-\(key)-bounds")
                    }
                }
            }

        }
    }
}
#endif
