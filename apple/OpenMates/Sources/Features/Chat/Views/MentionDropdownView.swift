// Mention dropdown — shows @-mention suggestions for models, mates, skills, and focus modes.
// Mirrors the web app's enter_message/MentionDropdown.svelte trigger and insertion contract:
// @ at the start of a word opens suggestions, selection inserts backend mention syntax.
// Uses local native suggestions because the web source builds mention data client-side.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MentionDropdown.svelte
// TS:      frontend/packages/ui/src/components/enter_message/services/mentionSearchService.ts
// CSS:     MentionDropdown.svelte .mention-dropdown, .mention-result
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct MentionDropdownView: View {
    let query: String
    let onSelect: (MentionItem) -> Void
    let onDismiss: () -> Void

    private var filteredItems: [MentionItem] {
        let allItems = MentionItem.defaultItems
        guard !query.isEmpty else { return allItems }
        let normalized = query.lowercased()
        return allItems.filter { item in
            item.searchTerms.contains { $0.contains(normalized) }
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            header

            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(filteredItems) { item in
                        Button {
                            onSelect(item)
                        } label: {
                            row(for: item)
                        }
                        .buttonStyle(.plain)
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel("\(item.name), \(item.type.label)")
                        .accessibilityIdentifier("mention-result")
                    }
                }
            }
            .frame(maxHeight: 240)

            if !query.isEmpty {
                Text(LocalizationManager.shared.text("enter_message.mention_dropdown.autocomplete_hint"))
                    .font(.omTiny)
                    .foregroundStyle(Color.fontTertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, .spacing8)
                    .padding(.vertical, .spacing4)
            }
        }
        .frame(maxWidth: 380)
        .background(Color.greyBlue)
        .clipShape(RoundedRectangle(cornerRadius: .radius7))
        .shadow(color: .black.opacity(0.15), radius: 20, x: 0, y: 4)
        .accessibilityIdentifier("mention-dropdown")
    }

    private var header: some View {
        HStack(alignment: .top, spacing: .spacing6) {
            Text(LocalizationManager.shared.text("enter_message.mention_dropdown.header"))
                .font(.omP)
                .foregroundStyle(Color.fontTertiary)
                .lineLimit(2)

            Spacer()

            Button(action: onDismiss) {
                Icon("close", size: 16)
                    .foregroundStyle(Color.fontTertiary)
                    .frame(width: 32, height: 32)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.close)
        }
        .padding(.horizontal, .spacing8)
        .padding(.top, .spacing8)
        .padding(.bottom, .spacing6)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.grey20)
                .frame(height: 1)
        }
    }

    private func row(for item: MentionItem) -> some View {
        HStack(spacing: .spacing6) {
            AppIconView(appId: item.iconAppId, size: 32)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 0) {
                Text(item.name)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                Text(item.subtitle)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontTertiary)
                    .lineLimit(1)
            }

            Spacer(minLength: .spacing3)

            Text(item.type.label)
                .font(.omTiny)
                .foregroundStyle(Color.fontTertiary)
        }
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing5)
        .contentShape(Rectangle())
    }
}

@MainActor
struct MentionItem: Identifiable, Equatable {
    let id: String
    let type: MentionType
    let nameKey: String
    let subtitleKey: String
    let iconAppId: String
    let mentionSyntax: String
    let searchTerms: [String]

    var name: String { AppStrings.localized(nameKey) }
    var subtitle: String { AppStrings.localized(subtitleKey) }

    @MainActor
    enum MentionType: String, Equatable {
        case modelAlias
        case mate
        case skill
        case focusMode

        var label: String {
            switch self {
            case .modelAlias:
                return AppStrings.localized("enter_message.mention_dropdown.type_labels.model_alias")
            case .mate:
                return AppStrings.localized("enter_message.mention_dropdown.type_labels.mate")
            case .skill:
                return AppStrings.localized("enter_message.mention_dropdown.type_labels.skill")
            case .focusMode:
                return AppStrings.localized("enter_message.mention_dropdown.type_labels.focus_mode")
            }
        }
    }

    static let defaultItems: [MentionItem] = [
        MentionItem(
            id: "alias:best",
            type: .modelAlias,
            nameKey: "enter_message.mention_dropdown.model_alias.best.name",
            subtitleKey: "enter_message.mention_dropdown.model_alias.best.description",
            iconAppId: "ai",
            mentionSyntax: "@best-model:best",
            searchTerms: ["best", "model", "ai"]
        ),
        MentionItem(
            id: "alias:fast",
            type: .modelAlias,
            nameKey: "enter_message.mention_dropdown.model_alias.fast.name",
            subtitleKey: "enter_message.mention_dropdown.model_alias.fast.description",
            iconAppId: "ai",
            mentionSyntax: "@best-model:fast",
            searchTerms: ["fast", "quick", "model", "ai"]
        ),
        MentionItem(
            id: "mate:software_development",
            type: .mate,
            nameKey: "mates.software_development",
            subtitleKey: "mate_descriptions.software_development",
            iconAppId: "code",
            mentionSyntax: "@mate:software_development",
            searchTerms: ["developer", "software", "code", "mate"]
        ),
        MentionItem(
            id: "skill:web:search",
            type: .skill,
            nameKey: "app_skills.web.search",
            subtitleKey: "app_skills.web.search.description",
            iconAppId: "web",
            mentionSyntax: "@skill:web:search",
            searchTerms: ["web", "search", "internet"]
        ),
        MentionItem(
            id: "skill:images:generate",
            type: .skill,
            nameKey: "app_skills.images.generate",
            subtitleKey: "app_skills.images.generate.description",
            iconAppId: "images",
            mentionSyntax: "@skill:images:generate",
            searchTerms: ["image", "images", "generate", "photo"]
        ),
        MentionItem(
            id: "skill:code:get_docs",
            type: .skill,
            nameKey: "app_skills.code.get_docs",
            subtitleKey: "app_skills.code.get_docs.description",
            iconAppId: "code",
            mentionSyntax: "@skill:code:get_docs",
            searchTerms: ["code", "docs", "documentation"]
        ),
        MentionItem(
            id: "skill:travel:search_connections",
            type: .skill,
            nameKey: "app_skills.travel.search_connections",
            subtitleKey: "app_skills.travel.search_connections.description",
            iconAppId: "travel",
            mentionSyntax: "@skill:travel:search_connections",
            searchTerms: ["travel", "flight", "flights", "connections"]
        ),
        MentionItem(
            id: "focus:web:research",
            type: .focusMode,
            nameKey: "app_focus_modes.web.check_reputation",
            subtitleKey: "app_focus_modes.web.check_reputation.description",
            iconAppId: "web",
            mentionSyntax: "@focus:web:check_reputation",
            searchTerms: ["focus", "research", "web"]
        ),
        MentionItem(
            id: "focus:jobs:career_insights",
            type: .focusMode,
            nameKey: "app_focus_modes.jobs.career_insights",
            subtitleKey: "app_focus_modes.jobs.career_insights.description",
            iconAppId: "jobs",
            mentionSyntax: "@focus:jobs:career_insights",
            searchTerms: ["focus", "career", "jobs", "professional"]
        )
    ]
}
