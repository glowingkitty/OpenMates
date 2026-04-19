// Mention dropdown — shows @-mention suggestions for apps, skills, and memories.
// Mirrors the web app's enter_message/MentionDropdown.svelte: triggered when user
// types @ in the message input, shows filterable list of mentionable items.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MentionDropdown.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct MentionDropdownView: View {
    let query: String
    let onSelect: (MentionItem) -> Void
    let onDismiss: () -> Void

    @State private var items: [MentionItem] = []
    @State private var isLoading = true

    struct MentionItem: Identifiable {
        let id: String
        let type: MentionType
        let name: String
        let description: String?
        let iconName: String?

        enum MentionType: String {
            case app, skill, memory, focusMode
        }
    }

    private var filteredItems: [MentionItem] {
        guard !query.isEmpty else { return items }
        let q = query.lowercased()
        return items.filter {
            $0.name.lowercased().contains(q) ||
            ($0.description?.lowercased().contains(q) ?? false)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            if isLoading {
                ProgressView().padding(.spacing4)
                    .accessibilityLabel("Loading mention suggestions")
            } else if filteredItems.isEmpty {
                Text(LocalizationManager.shared.text("chat.suggestions.filter_no_match"))
                    .font(.omSmall).foregroundStyle(Color.fontTertiary)
                    .padding(.spacing4)
                    .accessibilityLabel("No mention suggestions match \(query)")
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(filteredItems) { item in
                            Button {
                                onSelect(item)
                            } label: {
                                HStack(spacing: .spacing3) {
                                    if let icon = item.iconName {
                                        AppIconView(appId: icon, size: 24)
                                            .accessibilityHidden(true)
                                    } else {
                                        Image(systemName: iconForType(item.type))
                                            .frame(width: 24, height: 24)
                                            .foregroundStyle(Color.fontSecondary)
                                            .accessibilityHidden(true)
                                    }

                                    VStack(alignment: .leading, spacing: 0) {
                                        Text(item.name)
                                            .font(.omSmall).fontWeight(.medium)
                                            .foregroundStyle(Color.fontPrimary)
                                        if let desc = item.description {
                                            Text(desc)
                                                .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                                .lineLimit(1)
                                        }
                                    }

                                    Spacer()

                                    Text(item.type.rawValue)
                                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                }
                                .padding(.horizontal, .spacing4)
                                .padding(.vertical, .spacing2)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("\(item.name), \(item.type.rawValue)\(item.description.map { ", \($0)" } ?? "")")
                            .accessibilityHint("Inserts @\(item.name) mention into the message")
                            .accessibilityAddTraits(.isButton)
                        }
                    }
                }
                .frame(maxHeight: 240)
                .accessibilityLabel("Mention suggestions, \(filteredItems.count) available")
            }
        }
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .shadow(color: .black.opacity(0.1), radius: 8, y: -4)
        .task { await loadMentionItems() }
    }

    private func iconForType(_ type: MentionItem.MentionType) -> String {
        switch type {
        case .app: return "square.grid.2x2"
        case .skill: return "wand.and.stars"
        case .memory: return "brain.head.profile"
        case .focusMode: return "target"
        }
    }

    private func loadMentionItems() async {
        do {
            let response: [[String: AnyCodable]] = try await APIClient.shared.request(
                .get, path: "/v1/mentions/suggestions"
            )
            items = response.compactMap { dict in
                guard let id = dict["id"]?.value as? String,
                      let name = dict["name"]?.value as? String,
                      let typeStr = dict["type"]?.value as? String,
                      let type = MentionItem.MentionType(rawValue: typeStr) else { return nil }
                return MentionItem(
                    id: id, type: type, name: name,
                    description: dict["description"]?.value as? String,
                    iconName: dict["icon"]?.value as? String
                )
            }
        } catch {
            print("[Mention] Load error: \(error)")
        }
        isLoading = false
    }
}
