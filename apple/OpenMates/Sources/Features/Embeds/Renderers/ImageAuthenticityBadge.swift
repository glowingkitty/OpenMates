// ImageAuthenticityBadge — collapsed status icon on uploaded images that expands on
// tap/hover to show the AI-generated probability, the detection provider and a
// limitations note. Web reads the detection result from the embed content key
// `aiDetection` (fallback `ai_detection`): { ai_generated: 0...1, provider, status }.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageAuthenticityBadge.svelte
//          frontend/packages/ui/src/components/embeds/images/imageAuthenticity.ts
// CSS:     ImageAuthenticityBadge.svelte <style>: .authenticity-badge (28pt preview /
//          32pt fullscreen circle, top/right 8/12pt), .authentic, .ai-generated, .failed,
//          .expanded, .authenticity-badge-details
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

/// View model of `buildAuthenticityBadgeViewModel`; nil when the score is in the undecided band.
struct ImageAuthenticityModel: Equatable {
    enum Status: String { case aiGenerated = "ai_generated", authentic, failed }

    static let aiGeneratedThreshold = 0.7
    static let authenticThreshold = 0.4
    static let sightengineURL = "https://sightengine.com/"

    let status: Status
    let probabilityLabel: String
    let providerLabel: String
    let providerURL: URL?
    let explanationLabel: String
    let accessibilityLabel: String

    @MainActor init?(data: [String: AnyCodable]?) {
        let raw = (data?["aiDetection"]?.value as? [String: Any]) ?? (data?["ai_detection"]?.value as? [String: Any])
        guard let raw else { return nil }
        let rawScore = (raw["ai_generated"] as? Double) ?? (raw["ai_generated"] as? Int).map(Double.init) ?? 0
        let score = rawScore.isFinite ? min(1, max(0, rawScore)) : 0
        let failed = (raw["status"] as? String) == "failed"
        if failed { status = .failed }
        else if score > Self.aiGeneratedThreshold { status = .aiGenerated }
        else if score <= Self.authenticThreshold { status = .authentic }
        else { return nil }

        let provider = raw["provider"] as? String
        let isSightengine = provider == nil || provider?.isEmpty == true || provider?.lowercased() == "sightengine"
        providerLabel = isSightengine ? "Sightengine" : (provider ?? "")
        providerURL = isSightengine ? URL(string: Self.sightengineURL) : nil
        let chance = AppStrings.imageAuthenticityChance(percentage: "\(Int((score * 100).rounded()))%")
        probabilityLabel = failed ? AppStrings.imageAuthenticityFailedRetry : chance
        explanationLabel = failed ? AppStrings.imageAuthenticityFailedDescription : AppStrings.imageAuthenticityLimitations
        let statusLabel = failed ? AppStrings.imageAuthenticityFailedTitle
            : (status == .aiGenerated ? AppStrings.imageAuthenticityAIGenerated : AppStrings.imageAuthenticityAuthentic)
        accessibilityLabel = "\(statusLabel). \(probabilityLabel). \(AppStrings.imageAuthenticityVia(provider: providerLabel)). \(explanationLabel)"
    }

    var iconName: String {
        switch status {
        case .authentic: return "check"
        case .aiGenerated: return "ai"
        case .failed: return "question"
        }
    }
}

struct ImageAuthenticityBadge: View {
    enum Variant { case preview, fullscreen }

    let model: ImageAuthenticityModel
    var variant: Variant = .preview
    @State private var expanded = false
    @Environment(\.openURL) private var openURL

    private var diameter: CGFloat { variant == .fullscreen ? 32 : 28 }
    private var inset: CGFloat { variant == .fullscreen ? 12 : 8 }

    private var fill: Color {
        switch model.status {
        case .authentic: return Color.success
        case .aiGenerated: return Color.grey70
        case .failed: return Color.warning
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: .spacing2) {
            Icon(model.iconName, size: variant == .fullscreen ? 15 : 14)
                .foregroundStyle(Color.grey0)
                .frame(width: expanded ? 15 : diameter, height: expanded ? 15 : diameter)
                .padding(.top, expanded ? 1 : 0)
            if expanded {
                VStack(alignment: .leading, spacing: .spacing1) {
                    HStack(spacing: .spacing2) {
                        Text(model.probabilityLabel).font(.omTiny).fontWeight(.semibold)
                        HStack(spacing: 2) {
                            Text("· \(AppStrings.imageAuthenticityViaPrefix)")
                            if let url = model.providerURL {
                                Button { openURL(url) } label: { Text(model.providerLabel).underline() }
                                    .buttonStyle(.plain)
                            } else {
                                Text(model.providerLabel)
                            }
                        }
                        .font(.omTiny).opacity(0.9)
                    }
                    Text(model.explanationLabel).font(.omTiny).opacity(0.9)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .foregroundStyle(Color.grey0)
                .frame(maxWidth: variant == .fullscreen ? 290 : 250, alignment: .leading)
            }
        }
        .padding(expanded ? EdgeInsets(top: variant == .fullscreen ? 6 : 4, leading: 8, bottom: variant == .fullscreen ? 6 : 4, trailing: 10) : EdgeInsets())
        .background(fill, in: RoundedRectangle(cornerRadius: expanded ? .radius6 : diameter / 2))
        .overlay(RoundedRectangle(cornerRadius: expanded ? .radius6 : diameter / 2).stroke(Color.grey0.opacity(0.58), lineWidth: 1))
        .shadow(color: .black.opacity(0.24), radius: 4, x: 0, y: 2)
        .padding(inset)
        .onTapGesture { withAnimation(.easeInOut(duration: 0.15)) { expanded.toggle() } }
        #if os(macOS)
        .onHover { hovering in withAnimation(.easeInOut(duration: 0.15)) { expanded = hovering } }
        #endif
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(model.accessibilityLabel)
        .accessibilityAddTraits(.isButton)
        .accessibilityValue(model.status.rawValue)
        .accessibilityIdentifier("image-authenticity-badge")
    }
}
