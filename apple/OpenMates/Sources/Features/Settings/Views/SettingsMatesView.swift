// Native Mates catalog and details sourced from the canonical web metadata contract.
// The deterministic catalog is audited against matesMetadata.ts to prevent identity drift.
// Artwork is bundled from the shared web mates directory and all copy resolves through i18n.
// Chat actions hand a canonical mention to the native composer without browser navigation.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.navigation.parent-return, settings-ui.parity.web-apple-shell

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsMates.svelte
//          frontend/packages/ui/src/components/settings/MateDetails.svelte
// TS:      frontend/packages/ui/src/data/matesMetadata.ts
// CSS:     frontend/packages/ui/src/styles/settings.css
//          frontend/packages/ui/src/styles/mates.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Foundation
import SwiftUI

@MainActor
struct SettingsMateMetadata: Identifiable, Equatable {
    let id: String
    let nameKey: String
    let descriptionKey: String
    let systemPromptKey: String
    let processKey: String
    let artworkName: String
    let iconName: String
    let isAvailable: Bool

    var name: String { AppStrings.localized(nameKey) }
    var description: String { AppStrings.localized(descriptionKey) }
    var systemPrompt: String { AppStrings.localized(systemPromptKey) }
    var process: String { AppStrings.localized(processKey) }
    var mentionSyntax: String { "@mate:\(id)" }
    var settingsPath: String { "mates/\(id)" }

    var processBullets: [String] {
        process.split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { $0.hasPrefix("- ") }
            .map { String($0.dropFirst(2)).trimmingCharacters(in: .whitespacesAndNewlines) }
    }
}

@MainActor
enum CanonicalSettingsMateCatalog {
    // Generated field-for-field from frontend/packages/ui/src/data/matesMetadata.ts.
    static let all: [SettingsMateMetadata] = [
        mate(id: "software_development", nameKey: "mates.software_development", icon: "code"),
        mate(id: "business_development", nameKey: "mates.business_development", icon: "business"),
        mate(id: "life_coach_psychology", nameKey: "mates.life_coach_psychology", icon: "psychology"),
        mate(id: "medical_health", nameKey: "mates.medical_health", icon: "health"),
        mate(id: "legal_law", nameKey: "mates.legal_law", icon: "law"),
        mate(id: "finance", nameKey: "mates.finance", icon: "finance"),
        mate(id: "design", nameKey: "mates.design", icon: "design"),
        mate(id: "marketing_sales", nameKey: "mates.marketing_sales", icon: "marketing"),
        mate(id: "science", nameKey: "mates.science", icon: "science"),
        mate(id: "history", nameKey: "mates.history", icon: "history"),
        mate(id: "cooking_food", nameKey: "mates.cooking_food", icon: "cooking"),
        mate(id: "electrical_engineering", nameKey: "mates.electrical_engineering", icon: "engineering"),
        mate(id: "maker_prototyping", nameKey: "mates.maker_prototyping", icon: "maker"),
        mate(id: "movies_tv", nameKey: "mates.movies_tv", icon: "entertainment"),
        mate(id: "activism", nameKey: "mates.activism", icon: "activism"),
        mate(id: "general_knowledge", nameKey: "mates.general_knowledge", icon: "general"),
    ]

    static func mate(id: String?) -> SettingsMateMetadata? {
        guard let id else { return nil }
        return all.first { $0.id == id }
    }

    private static func mate(id: String, nameKey: String, icon: String) -> SettingsMateMetadata {
        SettingsMateMetadata(
            id: id,
            nameKey: nameKey,
            descriptionKey: "mate_descriptions.\(id)",
            systemPromptKey: "mates.\(id).systemprompt",
            processKey: "mates.\(id).process",
            artworkName: "Mates/\(id)",
            iconName: icon,
            isAvailable: true
        )
    }
}

@MainActor
enum SettingsComposerHandoff {
    private static var pendingMention: String?

    static var hasPendingMention: Bool { pendingMention != nil }

    static func request(mention: String) {
        pendingMention = mention
        NotificationCenter.default.post(name: .settingsComposerHandoffRequested, object: mention)
    }

    // The web editor inserts the mention without discarding the current draft.
    static func appending(mention: String, to draft: String) -> String {
        let separator = draft.isEmpty || draft.last?.isWhitespace == true ? "" : " "
        return "\(draft)\(separator)\(mention) "
    }

    static func consume() -> String? {
        defer { pendingMention = nil }
        return pendingMention
    }
}

extension Notification.Name {
    static let settingsComposerHandoffRequested = Notification.Name("openmates.settingsComposerHandoffRequested")
}

struct SettingsMatesView: View {
    var onNavigate: (String) -> Void = { _ in }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                ForEach(CanonicalSettingsMateCatalog.all) { mate in
                    Button {
                        onNavigate(mate.settingsPath)
                    } label: {
                        SettingsMateRow(mate: mate)
                    }
                    .buttonStyle(SettingsMateRowButtonStyle())
                    .disabled(!mate.isAvailable)
                    .accessibilityLabel(mate.name)
                    .accessibilityIdentifier("settings-mate-\(mate.id)")
                }
            }
            .padding(.top, .spacing4)
            .padding(.bottom, .spacing24)
        }
        .accessibilityIdentifier("settings-mates-page")
    }
}

private struct SettingsMateRowButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(configuration.isPressed ? Color.grey20 : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }
}

private struct SettingsMateRow: View {
    let mate: SettingsMateMetadata

    var body: some View {
        HStack(spacing: 0) {
            Image(mate.artworkName)
                .resizable()
                .scaledToFill()
                // .mate-profile-settings: fixed 46px artwork, without the AI badge.
                .frame(width: 46, height: 46)
                .clipShape(Circle())
                .padding(.vertical, .spacing3)
                .padding(.leading, .spacing5)
                .padding(.trailing, .spacing6)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(mate.name)
                    // .mate-name: 0.95rem; no generated 15.2pt font token.
                    .font(Font.custom("Lexend Deca", size: 15.2).weight(.semibold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                Text(mate.description)
                    // .mate-description: 0.8rem, inherited 500 weight, line-height 1.3.
                    .font(Font.custom("Lexend Deca", size: 12.8).weight(.medium))
                    .foregroundStyle(Color.grey60)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // CSS .mate-chevron: 8px sides, 2px stroke, rotate(45deg).
            SettingsMateChevron()
                .stroke(Color.grey50, lineWidth: 2)
                .frame(width: .spacing4, height: .spacing4)
                .padding(.leading, .spacing4)
                .accessibilityHidden(true)
        }
        .padding(.vertical, .spacing3)
        .padding(.trailing, .spacing6)
        .contentShape(Rectangle())
    }
}

private struct SettingsMateChevron: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        return path
    }
}

// The routed settings shell owns the mate avatar, title and parent navigation.
// MateDetails.svelte renders only this body below the submenu-info header.
struct SettingsMateDetailView: View {
    let mate: SettingsMateMetadata
    @State private var showsFullPrompt = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text(mate.description)
                    .font(.omP.weight(.medium))
                    .foregroundStyle(Color.grey100)
                    .modifier(SettingsMateWebLineHeight(fontSize: 16, multiplier: 1.6))
                    .frame(maxWidth: .infinity, alignment: .leading)

                VStack(alignment: .leading, spacing: 0) {
                    OMSettingsSectionHeading(title: AppStrings.mateInstructions, icon: "ai")

                    if !mate.processBullets.isEmpty {
                        VStack(alignment: .leading, spacing: 6.4) { // .process-bullets gap: 0.4rem.
                            ForEach(mate.processBullets, id: \.self) { bullet in
                                HStack(alignment: .top, spacing: .spacing8) {
                                    Circle()
                                        .fill(Color.buttonPrimary)
                                        .frame(width: .spacing2, height: .spacing2)
                                        .padding(.top, .spacing4)
                                    Text(bullet)
                                        .font(Font.custom("Lexend Deca", size: 15.2).weight(.medium))
                                        .foregroundStyle(Color.grey100)
                                        .fixedSize(horizontal: false, vertical: true)
                                        .modifier(SettingsMateWebLineHeight(fontSize: 15.2, multiplier: 1.5))
                                }
                                .padding(.vertical, 3.04) // Rendered global li margin: 0.2em.
                            }
                        }
                        .padding(.leading, .spacing5 + .spacing10)
                    }

                    if !mate.systemPrompt.isEmpty {
                        if showsFullPrompt {
                            HStack(alignment: .top, spacing: .spacing4) {
                                Icon("quote", size: 20)
                                    .foregroundStyle(Color.grey50.opacity(0.6))
                                Text(mate.systemPrompt)
                                    // .instructions-text: 0.9rem / 1.5.
                                    .font(Font.custom("Lexend Deca", size: 14.4).weight(.medium))
                                    .modifier(SettingsMateWebLineHeight(fontSize: 14.4, multiplier: 1.5))
                                    .foregroundStyle(Color.grey100)
                                    .textSelection(.enabled)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .accessibilityIdentifier("mate-system-prompt")
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, .spacing8)
                            .padding(.leading, .spacing6)
                            .padding(.trailing, .spacing10)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius5))
                            .overlay(
                                RoundedRectangle(cornerRadius: .radius5)
                                    .stroke(Color.grey20, lineWidth: 1)
                            )
                            .padding(.top, .spacing6)
                        }

                        Button {
                            showsFullPrompt.toggle()
                        } label: {
                            Text(showsFullPrompt ? AppStrings.mateHideFullPrompt : AppStrings.mateShowFullPrompt)
                                .font(.omSmall.weight(.medium))
                                .foregroundStyle(Color.fontPrimary)
                                .padding(.vertical, 5.6)
                                .padding(.horizontal, 9.6)
                                .frame(height: 41)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .padding(.top, .spacing6)
                        .padding(.leading, .spacing5)
                        .accessibilityIdentifier("settings-mate-prompt-toggle")
                        .accessibilityValue(showsFullPrompt ? AppStrings.mateHideFullPrompt : AppStrings.mateShowFullPrompt)
                    }
                }
                // Block margins collapse to 32px on the web; the shared heading
                // contributes its 24px top margin, leaving an 8px section gap.
                .padding(.top, .spacing4)

                Button {
                    SettingsComposerHandoff.request(mention: mate.mentionSyntax)
                } label: {
                    Text(AppStrings.chatWithMate(mate.name))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(SettingsMateChatButtonStyle())
                .padding(.top, .spacing20)
                .padding(.bottom, .spacing16)
                .accessibilityIdentifier("settings-mate-start-chat")
            }
            .padding(.spacing6 + .spacing1) // .mate-details padding: 14px.
            .frame(maxWidth: 1400) // .mate-details max-width.
            .frame(maxWidth: .infinity)
        }
        .accessibilityIdentifier("settings-mate-detail")
    }
}

private struct SettingsMateChatButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP.weight(.semibold))
            .foregroundStyle(Color.grey0)
            .padding(.horizontal, .spacing10)
            .frame(height: 41) // Rendered .chat-cta-button includes the global fixed height.
            .background(LinearGradient.primary)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .opacity(configuration.isPressed ? 0.9 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }
}

// Lexend Deca's bundled hhea metrics are ascent 1000, descent -250, lineGap 0
// per 1000 units. SwiftUI's native line is 1.25em; CSS line-height also includes
// half-leading on the first/last lines, which lineSpacing alone does not add.
private struct SettingsMateWebLineHeight: ViewModifier {
    let fontSize: CGFloat
    let multiplier: CGFloat

    func body(content: Content) -> some View {
        let leading = max(0, fontSize * (multiplier - 1.25))
        content
            .lineSpacing(leading)
            .padding(.vertical, leading / 2)
    }
}
