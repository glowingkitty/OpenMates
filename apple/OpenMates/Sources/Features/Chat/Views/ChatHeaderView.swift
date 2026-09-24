// Compact fallback title shown only while a chat has no banner presentation.
// Generated/loading chats use ChatBannerView, matching the web header.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.layout.responsive-history, chats.surface.semantic-parity

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHeader.svelte
//          frontend/packages/ui/src/components/ChatMessage.svelte
//          Web has no compact category-icon variant. Generated and loaded chat
//          identity is presented by the in-scroll gradient banner.
// Tokens:  ColorTokens.generated.swift
//          TypographyTokens.generated.swift (Font.omSmall)
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ChatHeaderView: View {
    let chat: Chat?
    let titleOverride: String?
    /// Immediate client-side title derived from the first user message. This
    /// keeps the header useful while encrypted generated metadata is still in
    /// flight, then yields to the server title as soon as it arrives.
    let provisionalTitle: String?
    let isLoading: Bool

    init(
        chat: Chat?,
        titleOverride: String?,
        provisionalTitle: String? = nil,
        isLoading: Bool
    ) {
        self.chat = chat
        self.titleOverride = titleOverride
        self.provisionalTitle = provisionalTitle
        self.isLoading = isLoading
    }

    private var title: String {
        ChatHeaderPresentation.title(
            override: titleOverride,
            generated: chat?.title,
            provisional: provisionalTitle
        )
    }

    var body: some View {
        HStack(spacing: .spacing3) {
            VStack(alignment: .leading, spacing: 0) {
                Text(title)
                    .font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                    .accessibilityIdentifier("chat-header-title")
                    .accessibilityLabel(title)
            }

            Spacer()

            if isLoading {
                ProgressView()
                    .scaleEffect(0.6)
            }
        }
        .padding(.horizontal, .spacing4)
        .accessibilityElement(children: .contain)
    }

}

/// Presentation-only title policy shared by the rendered header and focused
/// tests. The generated encrypted title remains authoritative once available.
@MainActor
enum ChatHeaderPresentation {
    static let provisionalTitleLimit = 60

    static func title(override: String?, generated: String?, provisional: String?) -> String {
        firstNonEmpty([override, generated, provisional]) ?? AppStrings.newChat
    }

    static func provisionalTitle(from message: String) -> String? {
        let collapsed = message
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
        guard !collapsed.isEmpty else { return nil }
        guard collapsed.count > provisionalTitleLimit else { return collapsed }
        return String(collapsed.prefix(provisionalTitleLimit)).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
    }

    private static func firstNonEmpty(_ values: [String?]) -> String? {
        values.lazy.compactMap { value in
            let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return trimmed.isEmpty ? nil : trimmed
        }.first
    }
}

// MARK: - Assistant message identity

enum AssistantMessageSettingsTarget: Equatable, Identifiable {
    case mate(String)
    case model(String)

    var id: String {
        switch self {
        case .mate(let id): return "mate:\(id)"
        case .model(let id): return "model:\(id)"
        }
    }
}

/// Resolves the same settings targets as ChatMessage.svelte's
/// `openMateSettings` and `handleGeneratedByClick` handlers.
enum AssistantMessageIdentityRoutingPolicy {
    struct ModelTarget: Equatable {
        let id: String
        let displayName: String
    }

    static func mateID(category: String?, availableMateIDs: Set<String>) -> String? {
        guard let category = category?.trimmingCharacters(in: .whitespacesAndNewlines),
              !category.isEmpty,
              category != "openmates_official",
              availableMateIDs.contains(category) else {
            return nil
        }
        return category
    }

    static func modelTarget(
        nameOrID: String?,
        models: [NativeModelCatalog.Model]
    ) -> ModelTarget? {
        guard let value = nameOrID?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }

        let candidates = modelLookupCandidates(value)
        let normalizedCandidates = Set(candidates.map(normalizedModelLookupKey))
        guard let model = models.first(where: { model in
            candidates.contains(model.id)
                || candidates.contains(where: { $0.caseInsensitiveCompare(model.name) == .orderedSame })
                || normalizedCandidates.contains(normalizedModelLookupKey(model.id))
                || normalizedCandidates.contains(normalizedModelLookupKey(model.name))
        }) else {
            return nil
        }
        return ModelTarget(id: model.id, displayName: model.name)
    }

    private static func modelLookupCandidates(_ value: String) -> [String] {
        let withoutProviderPrefix = value.split(separator: "/").last.map(String.init) ?? value
        let withoutProviderSuffix = withoutProviderPrefix.split(separator: ":").first.map(String.init)
            ?? withoutProviderPrefix
        return Array(Set([value, withoutProviderPrefix, withoutProviderSuffix]))
    }

    private static func normalizedModelLookupKey(_ value: String) -> String {
        value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "[_-]+", with: " ", options: .regularExpression)
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
    }
}

/// The assistant name above a response and model attribution below it. Both
/// controls preserve their existing visual treatment while exposing the same
/// settings navigation as the rendered web message card.
struct AssistantMessageIdentityView: View {
    enum Placement {
        case mateName
        case modelAttribution
    }

    let placement: Placement
    let displayName: String
    let category: String?
    let modelName: String?
    let onOpenMateSettings: ((String) -> Void)?
    let onOpenModelSettings: ((String) -> Void)?

    @ObservedObject private var modelCatalog = NativeModelCatalogRuntime.shared

    private var mateID: String? {
        AssistantMessageIdentityRoutingPolicy.mateID(
            category: category,
            availableMateIDs: Set(CanonicalSettingsMateCatalog.all.map(\.id))
        )
    }

    private var modelTarget: AssistantMessageIdentityRoutingPolicy.ModelTarget? {
        AssistantMessageIdentityRoutingPolicy.modelTarget(
            nameOrID: modelName,
            models: modelCatalog.catalog?.models ?? []
        )
    }

    @ViewBuilder
    var body: some View {
        switch placement {
        case .mateName:
            mateName
        case .modelAttribution:
            modelAttribution
        }
    }

    @ViewBuilder
    private var mateName: some View {
        if let mateID, let onOpenMateSettings {
            Button {
                onOpenMateSettings(mateID)
            } label: {
                mateNameLabel
            }
            .buttonStyle(.plain)
            .contentShape(Rectangle())
            .accessibilityIdentifier("message-sender-name")
        } else {
            mateNameLabel
                .accessibilityIdentifier("message-sender-name")
        }
    }

    @ViewBuilder
    private var modelAttribution: some View {
        if let modelName, !modelName.isEmpty {
            if let modelTarget, let onOpenModelSettings {
                Button {
                    onOpenModelSettings(modelTarget.id)
                } label: {
                    modelAttributionLabel(modelTarget.displayName)
                }
                .buttonStyle(.plain)
                .contentShape(Rectangle())
                .accessibilityIdentifier("message-model-attribution")
            } else {
                modelAttributionLabel(modelTarget?.displayName ?? modelName)
                    .accessibilityIdentifier("message-model-attribution")
            }
        }
    }

    private var mateNameLabel: some View {
        Text(displayName)
            .font(.omP)
            .fontWeight(.medium)
            .foregroundStyle(LinearGradient.primary)
            .padding(.bottom, .spacing1)
    }

    private func modelAttributionLabel(_ resolvedModelName: String) -> some View {
        Text(AppStrings.generatedBy(resolvedModelName))
            .font(.omSmall)
            .fontWeight(.medium)
            .foregroundStyle(Color.grey60)
            .padding(.top, .spacing3)
            .padding(.leading, .spacing6)
            .padding(.bottom, .spacing5)
    }
}
