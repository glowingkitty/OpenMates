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
    case projectCreatedUndo = "project-created-undo"
    case testResultPreviews = "test-result-previews"
    case testResultFullscreen = "test-result-fullscreen"

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
                case .projectCreatedUndo: DevProjectCreatedUndoFixture()
                case .testResultPreviews: DevTestResultPreviewsFixture()
                case .testResultFullscreen: DevTestResultFullscreenFixture()
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
/// Project-created card with an Undo button wired to a local closure (no network).
private struct DevProjectCreatedUndoFixture: View {
    private static let projectID = "4f1c2a7e-3b5d-4c8e-9a10-2b3c4d5e6f70"
    private static let focusID = "project-\(projectID)"
    /// Counts calls of the local undo closure, so a UI test can tell a lost tap
    /// from a card whose undo state was reset.
    @MainActor
    private final class UndoCalls: ObservableObject { @Published var count = 0 }
    @StateObject private var calls = UndoCalls()
    @StateObject private var undoModel: ProjectCreatedUndoModel

    init() {
        let calls = UndoCalls()
        _calls = StateObject(wrappedValue: calls)
        _undoModel = StateObject(wrappedValue: ProjectCreatedUndoModel(chatID: "dev-chat-example-1") { @MainActor _ in
            calls.count += 1
        })
    }

    var body: some View {
        let created = ProjectCreatedFocus(
            data: ["project_created": AnyCodable(true), "project_id": AnyCodable(Self.projectID),
                   "project_name": AnyCodable("Kitchen renovation")],
            focusName: "Work on Kitchen renovation")
        VStack(spacing: .spacing4) {
            if let created {
                ProjectCreatedCardView(created: created, focusID: Self.focusID, undoModel: undoModel)
            }
            Color.clear
                .frame(height: 1)
                .accessibilityElement()
                .accessibilityIdentifier("dev-project-undo-calls")
                .accessibilityValue("calls:\(calls.count)")
        }
    }
}

private enum DevTestResultFixtureData {
    static func obj(_ value: [String: Any]) -> [String: Any] { value }

    static func record(id: String, _ fields: [String: Any]) -> EmbedRecord {
        EmbedRecord(id: "dev-test-result-\(id)", type: EmbedType.codeTestResult.rawValue, status: .finished,
                    data: .raw(fields.mapValues { AnyCodable($0) }), parentEmbedId: nil,
                    appId: "code", skillId: "test_result", embedIds: nil, createdAt: "2026-11-12T08:30:00Z")
    }

    static var browser: EmbedRecord {
        record(id: "browser", [
            "kind": "browser", "run_status": "passed", "target": "Checkout flow", "duration_ms": 8200,
            "passed": 3, "failed": 0, "skipped": 0, "is_current": true, "preview_step_index": 1,
            "steps": [
                obj(["name": "Open https://example.org/shop", "start_ms": 0, "end_ms": 1800, "status": "passed"]),
                obj(["name": "Add the kettle to the basket", "start_ms": 1800, "end_ms": 4600, "status": "passed"]),
                obj(["name": "Pay with the test card", "start_ms": 4600, "end_ms": 8200, "status": "passed"])
            ],
            "evidence": [
                obj(["kind": "video", "path": "runs/checkout.webm", "mime_type": "video/webm",
                 "asset_id": "dev-test-result-video"]),
                obj(["kind": "preview_frame", "path": "runs/checkout.png", "mime_type": "image/png",
                 "asset_id": "dev-test-result-frame", "at_step": 1])
            ]
        ])
    }

    static var cli: EmbedRecord {
        record(id: "cli", [
            "kind": "cli", "run_status": "failed", "target": "npm run build", "exit_code": 1,
            "duration_ms": 12400, "passed": 0, "failed": 1, "skipped": 0, "is_current": true,
            "error": "Build failed: example.org module not found",
            "steps": [obj(["name": "npm run build", "start_ms": 0, "end_ms": 12400, "status": "failed",
                       "command": "npm run build", "output": "Error: cannot resolve ./kitchen"])]
        ])
    }

    static var unit: EmbedRecord {
        record(id: "unit", [
            "kind": "unit", "run_status": "passed", "target": "tests/test_kettle.py", "duration_ms": 640,
            "passed": 4, "failed": 0, "skipped": 1, "is_current": false,
            "stale_reason": "Files changed after this run",
            "tests": [obj(["name": "test_boils_water", "status": "passed", "duration_ms": 120]),
                      obj(["name": "test_shuts_off", "status": "passed", "duration_ms": 90])]
        ])
    }
}

private struct DevTestResultPreviewsFixture: View {
    var body: some View {
        ForEach([("browser", DevTestResultFixtureData.browser), ("cli", DevTestResultFixtureData.cli),
                 ("unit", DevTestResultFixtureData.unit)], id: \.0) { item in
            EmbedPreviewCard(embed: item.1) {}
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("dev-test-result-card-\(item.0)")
        }
    }
}

private struct DevTestResultFullscreenFixture: View {
    var body: some View {
        EmbedContentView(embed: DevTestResultFixtureData.browser, mode: .fullscreen)
    }
}
#endif
