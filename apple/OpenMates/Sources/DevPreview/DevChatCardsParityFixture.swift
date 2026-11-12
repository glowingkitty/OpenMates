// Debug-only synthetic fixtures for the chat cards that close the 2026-11-12
// web parity audit gaps: image-generate card states, the Recommendations card
// and the assistant-created Project card. Launch with
//   --dev-preview embeds --dev-chat-cards-fixture <image-generate|recommendations|project-created>
// All content is synthetic and already plain (no account, sync, crypto or
// provider calls). This file is compiled in Debug builds only.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/RecommendationsCard.svelte
//          frontend/packages/ui/src/components/embeds/focus_mode/FocusModeActivationEmbed.svelte
// Tokens:  SpacingTokens.generated.swift, ColorTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Plan: docs/plans/apple-client-core-migration/plan.yml (parity_audit_2026_11_12)

#if DEBUG
import SwiftUI

enum DevChatCardsFixtureKind: String {
    case imageGenerate = "image-generate"
    case recommendations
    case projectCreated = "project-created"

    static let argument = "--dev-chat-cards-fixture"

    static func fromLaunchArguments(_ arguments: [String] = ProcessInfo.processInfo.arguments) -> Self? {
        guard let index = arguments.firstIndex(of: argument), arguments.indices.contains(index + 1) else { return nil }
        return Self(rawValue: arguments[index + 1])
    }
}

struct DevChatCardsParityFixture: View {
    let kind: DevChatCardsFixtureKind

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing8) {
                // The fixture marker is its own element. As a modifier on this stack
                // (or on the ScrollView, which the preview host names
                // "dev-preview-root") it replaced the identifier of a card that is
                // itself an accessibility container, such as the Project card.
                Color.clear
                    .frame(height: 1)
                    .accessibilityElement()
                    .accessibilityIdentifier("dev-chat-cards-fixture")
                    .accessibilityValue(kind.rawValue)
                switch kind {
                case .imageGenerate: DevImageGenerateStatesFixture()
                case .recommendations: DevRecommendationsCardFixture()
                case .projectCreated: DevProjectCreatedCardFixture()
                }
            }
            .padding(.spacing8)
            .frame(maxWidth: .infinity)
        }
        .background(Color.grey0)
    }
}

// MARK: - Image generate states

private struct DevImageGenerateStatesFixture: View {
    private struct Case: Identifiable {
        let id: String
        let record: EmbedRecord
    }

    private static let prompt = "A lighthouse on a rocky coast at dawn, soft watercolor"

    private static func record(id: String, skillId: String, status: EmbedStatus,
                               extra: [String: Any] = [:]) -> EmbedRecord {
        var raw: [String: Any] = ["type": "app_skill_use", "app_id": "images", "skill_id": skillId,
                                  "prompt": prompt, "model": "example-image-model"]
        raw.merge(extra) { _, new in new }
        let type: String
        switch skillId {
        case "generate": type = EmbedType.imagesGenerate.rawValue
        case "generate_draft": type = EmbedType.imagesGenerateDraft.rawValue
        default: type = "app_skill_use"
        }
        return EmbedRecord(id: "dev-chat-card-image-\(id)", type: type, status: status,
                           data: .raw(raw.mapValues { AnyCodable($0) }), parentEmbedId: nil,
                           appId: "images", skillId: skillId, embedIds: nil,
                           createdAt: "2026-11-12T08:30:00Z")
    }

    private var cases: [Case] { [
        Case(id: "processing", record: Self.record(id: "processing", skillId: "generate", status: .processing)),
        Case(id: "scripting", record: Self.record(id: "scripting", skillId: "generate_draft", status: .processing,
                                             extra: ["draft_stage": "scripting"])),
        Case(id: "svg-draft", record: Self.record(id: "svg-draft", skillId: "generate_draft", status: .processing,
                                             extra: ["draft_stage": "checking",
                                                     "svg_draft": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 4 3\"><rect width=\"4\" height=\"3\"/></svg>"])),
        Case(id: "modify", record: Self.record(id: "modify", skillId: "modify", status: .processing,
                                          extra: ["draft_stage": "running", "draft_attempt": 2])),
        Case(id: "error", record: Self.record(id: "error", skillId: "generate", status: .error,
                                         extra: ["error": "The image provider rejected the request."])),
        Case(id: "cancelled", record: Self.record(id: "cancelled", skillId: "generate", status: .cancelled)),
        Case(id: "draft-finished", record: Self.record(id: "draft-finished", skillId: "generate_draft", status: .finished))
    ] }

    var body: some View {
        ForEach(cases) { item in
            VStack(spacing: 0) {
                EmbedPreviewCard(embed: item.record) {}
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("dev-chat-card-image-\(item.id)")
        }
    }
}

// MARK: - Recommendations

private struct DevRecommendationsCardFixture: View {
    @State private var lastActionID = ""

    private let items: [ChatRecommendation] = [
        ChatRecommendation(id: "rec-memory-1", kind: .memory, action: .create, targetID: nil,
                           title: "Prefers vegetarian recipes",
                           summary: "Suggest meat-free dishes first when planning weekly meals."),
        ChatRecommendation(id: "rec-workflow-1", kind: .workflow, action: .update, targetID: "workflow-example-1",
                           title: "Weekly meal plan",
                           summary: "Add a shopping list step after the plan is drafted."),
        ChatRecommendation(id: "rec-memory-2", kind: .memory, action: .update, targetID: "memory-example-2",
                           title: "Cooks for four people",
                           summary: "Scale recipe quantities to four servings by default.")
    ]

    var body: some View {
        RecommendationsCardView(items: items, category: "cooking_food", busyID: nil, statusText: nil) { item in
            lastActionID = item.id
        }
        .frame(maxWidth: 600)
        // Debug-only probe so the UI test can prove the action callback fired.
        Text(lastActionID)
            .font(.omMicro)
            .foregroundStyle(Color.fontSecondary)
            .accessibilityIdentifier("dev-recommendation-last-action")
            .accessibilityValue(lastActionID)
    }
}

// MARK: - Assistant-created Project

private struct DevProjectCreatedCardFixture: View {
    private static let projectID = "4f1c2a7e-3b5d-4c8e-9a10-2b3c4d5e6f70"

    private static var fields: [String: Any] { [
        "focus_id": "project-\(projectID)",
        "focus_mode_name": "Work on Kitchen renovation",
        "project_created": true,
        "project_id": projectID,
        "project_name": "Kitchen renovation"
    ] }

    var body: some View {
        EmbedContentView(embed: EmbedRecord(
            id: "dev-chat-card-project-created",
            type: EmbedType.focusModeActivation.rawValue,
            status: .finished,
            data: .raw(Self.fields.mapValues { AnyCodable($0) }),
            parentEmbedId: nil, appId: "projects", skillId: nil, embedIds: nil,
            createdAt: "2026-11-12T08:30:00Z"), mode: .preview)
    }
}
#endif
