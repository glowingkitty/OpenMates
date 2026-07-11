// Native Mates catalog and details sourced from the canonical web metadata contract.
// The deterministic catalog is audited against matesMetadata.ts to prevent identity drift.
// Artwork is bundled from the shared web mates directory and all copy resolves through i18n.
// Chat actions hand a canonical mention to the native composer without browser navigation.

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
        mate(id: "onboarding_support", nameKey: "mates.onboarding_support", icon: "compass"),
    ]

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
        NotificationCenter.default.post(name: .newChat, object: nil)
        NotificationCenter.default.post(name: .settingsComposerHandoffRequested, object: mention)
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
    @State private var selectedMate: SettingsMateMetadata?

    var body: some View {
        ZStack {
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(CanonicalSettingsMateCatalog.all) { mate in
                        Button {
                            selectedMate = mate
                        } label: {
                            SettingsMateRow(mate: mate)
                        }
                        .buttonStyle(.plain)
                        .disabled(!mate.isAvailable)
                        .accessibilityIdentifier("settings-mate-\(mate.id)")
                    }
                }
                .padding(.top, .spacing4)
                .padding(.bottom, .spacing12)
            }
            .accessibilityIdentifier("settings-mates-page")

            OMSheet(
                isPresented: Binding(
                    get: { selectedMate != nil },
                    set: { if !$0 { selectedMate = nil } }
                ),
                title: selectedMate?.name
            ) {
                if let selectedMate {
                    SettingsMateDetailView(mate: selectedMate)
                }
            }
        }
    }
}

private struct SettingsMateRow: View {
    let mate: SettingsMateMetadata

    var body: some View {
        HStack(spacing: 0) {
            Image(mate.artworkName)
                .resizable()
                .scaledToFill()
                .frame(width: 46, height: 46)
                .clipShape(Circle())
                .padding(.vertical, .spacing3)
                .padding(.leading, .spacing5)
                .padding(.trailing, .spacing6)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(mate.name)
                    .font(.omP.weight(.semibold))
                    .foregroundStyle(LinearGradient.primary)
                    .lineLimit(1)
                Text(mate.description)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            }

            Spacer(minLength: .spacing4)
            Icon("chevron-right", size: 16)
                .foregroundStyle(Color.fontTertiary)
                .padding(.trailing, .spacing6)
                .accessibilityHidden(true)
        }
        .contentShape(Rectangle())
    }
}

private struct SettingsMateDetailView: View {
    let mate: SettingsMateMetadata
    @State private var showsFullPrompt = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                HStack(spacing: .spacing6) {
                    Image(mate.artworkName)
                        .resizable()
                        .scaledToFill()
                        .frame(width: 80, height: 80)
                        .clipShape(Circle())
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: .spacing2) {
                        Text(mate.name)
                            .font(.omH3.weight(.bold))
                            .foregroundStyle(Color.fontPrimary)
                        Text(mate.description)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }

                OMSettingsSectionHeading(title: AppStrings.mateInstructions, icon: "ai")

                if mate.processBullets.isEmpty {
                    Text(mate.description)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                } else {
                    VStack(alignment: .leading, spacing: .spacing4) {
                        ForEach(mate.processBullets, id: \.self) { bullet in
                            HStack(alignment: .top, spacing: .spacing4) {
                                Circle()
                                    .fill(Color.buttonPrimary)
                                    .frame(width: .spacing2, height: .spacing2)
                                    .padding(.top, .spacing3)
                                Text(bullet)
                                    .font(.omSmall)
                                    .foregroundStyle(Color.fontPrimary)
                            }
                        }
                    }
                    .padding(.horizontal, .spacing5)
                }

                if showsFullPrompt {
                    HStack(alignment: .top, spacing: .spacing5) {
                        Icon("quote", size: 20)
                            .foregroundStyle(Color.fontTertiary)
                        Text(mate.systemPrompt)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                            .textSelection(.enabled)
                            .accessibilityIdentifier("mate-system-prompt")
                    }
                    .padding(.spacing8)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .overlay(
                        RoundedRectangle(cornerRadius: .radius5)
                            .stroke(Color.grey20, lineWidth: 1)
                    )
                }

                Button(showsFullPrompt ? AppStrings.mateHideFullPrompt : AppStrings.mateShowFullPrompt) {
                    showsFullPrompt.toggle()
                }
                .buttonStyle(OMSecondaryButtonStyle())
                .accessibilityIdentifier("settings-mate-prompt-toggle")

                Button(AppStrings.chatWithMate(mate.name)) {
                    SettingsComposerHandoff.request(mention: mate.mentionSyntax)
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("settings-mate-start-chat")
            }
        }
        .frame(maxHeight: 620)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-mate-detail")
    }
}
