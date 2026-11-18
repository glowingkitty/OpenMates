// Tests of the chat Recommendations container state (hydration mapping,
// stale-result guard, action keeps the item).
// Specification: specifications/features/app-memories/specification.yml
import XCTest
@testable import OpenMates

@MainActor
private final class FakeRecommendationsSource: ChatRecommendationsSource {
    var result: Result<[ChatRecommendationRecord], Error> = .success([])
    var draft: Result<RecommendationDraftRecord, Error> = .success(
        RecommendationDraftRecord(status: .requestFailed, fields: nil, existingId: nil))
    var resolved: [String] = []
    func chatRecommendations(chatId: String) async throws -> [ChatRecommendationRecord] {
        try result.get()
    }
    func recommendationMemoryDraft(chatId: String, recommendation: ChatRecommendationRecord) async throws -> RecommendationDraftRecord {
        try draft.get()
    }
    func resolveChatRecommendation(chatId: String, recommendationId: String) async throws {
        resolved.append(recommendationId)
    }
}

@MainActor
final class ChatRecommendationsContainerTests: XCTestCase {
    private func record(_ id: String, kind: RecommendationKindRecord, action: RecommendationActionRecord) -> ChatRecommendationRecord {
        ChatRecommendationRecord(id: id, kind: kind, action: action, targetId: action == .update ? "target-1" : nil,
                                 title: "Title \(id)", summary: "Summary \(id)")
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.suggestions.post-processor
    func testHydrateMapsCoreRecordsToCardItems() async {
        let source = FakeRecommendationsSource()
        source.result = .success([record("a", kind: .memory, action: .create),
                                  record("b", kind: .workflow, action: .update)])
        let model = ChatRecommendationsModel(source: source)
        await model.hydrate(chatId: "chat-1")
        // Workflow suggestions are hidden (no Apple workflow draft surface).
        XCTAssertEqual(model.items.map(\.id), ["a"])
        XCTAssertEqual(model.items[0].kind, .memory)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.suggestions.post-processor
    func testFailedReadHidesTheCard() async {
        struct Boom: Error {}
        let source = FakeRecommendationsSource()
        source.result = .success([record("a", kind: .memory, action: .create)])
        let model = ChatRecommendationsModel(source: source)
        await model.hydrate(chatId: "chat-1")
        source.result = .failure(Boom())
        await model.hydrate(chatId: "chat-1")
        XCTAssertTrue(model.items.isEmpty)
    }

    private func accepted(_ draft: Result<RecommendationDraftRecord, Error>,
                          kind: RecommendationActionRecord = .create) async -> (ChatRecommendationsModel, FakeRecommendationsSource, [String?]) {
        let source = FakeRecommendationsSource()
        source.result = .success([record("a", kind: .memory, action: kind)])
        source.draft = draft
        let opened = OpenedEditors()
        let model = ChatRecommendationsModel(source: source, openMemoryEditor: { opened.ids.append($0) })
        await model.hydrate(chatId: "chat-1")
        await model.run(model.items[0])
        return (model, source, opened.ids)
    }

    private func status(_ status: RecommendationDraftStatusRecord) -> Result<RecommendationDraftRecord, Error> {
        .success(RecommendationDraftRecord(status: status, fields: nil, existingId: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.suggestions.billing
    func testFailureStatusesShowTheWebTextsAndKeepTheItem() async {
        let cases: [(RecommendationDraftStatusRecord, String)] = [
            (.insufficientCredits, AppStrings.recommendationsInsufficientCredits),
            (.networkUnavailable, AppStrings.recommendationsConnectionProblem),
            (.memoryNotFound, AppStrings.recommendationsMemoryNotFound),
            (.requestFailed, AppStrings.recommendationsDraftFailed),
            (.upToDate, AppStrings.recommendationsMemoryUpToDate),
        ]
        for (code, text) in cases {
            let (model, _, opened) = await accepted(status(code))
            XCTAssertEqual(model.statusText, text)
            XCTAssertEqual(model.items.count, 1)
            XCTAssertNil(model.busyID)
            XCTAssertTrue(opened.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.suggestions.post-processor
    func testDraftOpensTheMemoryEditorAndSaveResolves() async {
        let fields = MemoryFieldsRecord(title: "Tea", description: nil, whenToUse: "Drinks", body: "Green",
                                        loadMode: nil, validFrom: nil, validUntil: nil, references: [], appId: nil)
        let (model, source, opened) = await accepted(
            .success(RecommendationDraftRecord(status: .draft, fields: fields, existingId: "personal:1")), kind: .update)
        XCTAssertEqual(opened, ["personal:1"])
        XCTAssertEqual(model.items.count, 1)
        let store = MemoryDraftSuggestionStore.shared
        XCTAssertEqual(store.draft(forExisting: "personal:1")?.title, "Tea")
        XCTAssertNil(store.draft(forExisting: nil))
        store.didSave()
        try? await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(source.resolved, ["a"])
        XCTAssertNil(store.pending)
    }
}

/// Records the Memory editors the model asked to open.
@MainActor
private final class OpenedEditors {
    var ids: [String?] = []
}
