// Synthetic Specifications for the Projects preview (`--ui-test-project-specifications`):
// one Specification with an approved revision 1 and a newer draft revision 2 (approval
// state "stale"), so the reader shows history, read-only older revisions and Approve.
// Approve updates the state locally; no account or network is used.
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.revision.exact-approval, contracts.surface.semantic-parity
#if DEBUG
import Foundation

@MainActor
final class ProjectSpecificationsPreviewLoader: ProjectSpecificationsLoading {
    static let launchArgument = "--ui-test-project-specifications"
    static var enabled: Bool { ProcessInfo.processInfo.arguments.contains(launchArgument) }

    private let now = UInt64(Date().timeIntervalSince1970)
    private var approvedRevisionId = "rev-1"
    private var approvedAt: UInt64

    init() { approvedAt = UInt64(Date().timeIntervalSince1970) - 86_400 }

    private var revisions: [ProjectSpecificationRevision] {
        [
            .init(id: "rev-1", number: 1, createdAt: now - 172_800, summary: "First version agreed with the family.",
                  status: approvedRevisionId == "rev-1" ? "approved" : "superseded", contentHash: "hash-1"),
            .init(id: "rev-2", number: 2, createdAt: now - 3_600, summary: "Adds sharing the shopping list.",
                  status: approvedRevisionId == "rev-2" ? "approved" : "draft", contentHash: "hash-2"),
        ]
    }

    private func document(_ revisionId: String) -> ProjectSpecificationDocument {
        let sharing = revisionId == "rev-2"
        var requirements: [ProjectSpecRequirement] = [
            .init(id: "recipes.search.by-ingredient", statement: "Searching by an ingredient lists every saved recipe that uses it.",
                  appliesTo: ["Web", "Apple"], example: "Searching “basil” finds Pesto and Caprese.",
                  proofState: "passed", proofTitle: "Recipe search finds saved recipes",
                  proofExplanation: "The end-to-end search Check passed on the current revision."),
            .init(id: "recipes.list.phone-readable", statement: "The shopping list stays readable on a phone.",
                  appliesTo: ["Apple"], example: "Every item can be ticked off with one thumb.",
                  proofState: nil, proofTitle: nil, proofExplanation: nil),
        ]
        if sharing {
            requirements.append(.init(id: "recipes.list.share", statement: "The shopping list can be shared with one family member.",
                                      appliesTo: ["Web", "Apple"], example: "Anna shares the list with Ben; Ben sees new items.",
                                      proofState: "stale", proofTitle: "Shared list stays in sync",
                                      proofExplanation: "The Check last passed on revision 1 and must run again."))
        }
        return ProjectSpecificationDocument(
            title: "Family recipe book", project: "Kitchen renovation", category: "Product",
            summary: "A shared recipe book the whole family can search and cook from.",
            outcome: "Everyone finds a recipe by what is in the fridge and shops from one list.",
            role: "product",
            scopeIncluded: ["Saving and searching recipes", "One shopping list"] + (sharing ? ["Sharing the list"] : []),
            scopeExcluded: ["Meal planning", "Payments"],
            assumptions: ["Recipes are entered by hand at first."],
            designDecisions: ["The list opens on the last used recipe."],
            chapters: [
                .init(id: "search", title: "Finding recipes", introduction: "How the family finds something to cook.",
                      requirementIds: ["recipes.search.by-ingredient"], flowIds: ["flow-search"], modelIds: ["recipe"]),
                .init(id: "shopping", title: "Shopping", introduction: "",
                      requirementIds: ["recipes.list.phone-readable"], flowIds: ["edge-empty"], modelIds: []),
            ],
            requirements: requirements,
            flows: [
                .init(id: "flow-search", title: "Find a recipe by ingredient", kind: "user_flow",
                      steps: ["Open the recipe book", "Type an ingredient", "Open a matching recipe", "Add its items to the list"]),
                .init(id: "edge-empty", title: "No recipe matches", kind: "edge_case",
                      steps: ["Type an ingredient no recipe uses", "See a friendly empty state"]),
            ],
            models: [.init(id: "recipe", description: "One saved recipe.",
                           fields: [.init(name: "title", type: "text", description: "Name of the dish"),
                                    .init(name: "ingredients", type: "list", description: "What it needs")])],
            related: [.init(title: "Recipe book design", role: "design", relation: "Shows how these screens look")])
    }

    private var approvalState: String { approvedRevisionId == "rev-2" ? "approved" : "stale" }

    func list(projectId: String, teamId: String?) async throws -> [ProjectSpecificationListItem] {
        [.init(id: "spec-recipes", title: "Family recipe book", kind: "Product",
               status: approvalState == "approved" ? "approved" : "draft",
               revisionNumber: 2, updatedAt: now - 3_600, requirementCount: 3,
               proofPassed: 1, proofOpen: 1, proofStale: 1)]
    }

    func open(projectId: String, teamId: String?, specificationId: String, revisionId: String?) async throws
        -> ProjectSpecificationOpened {
        guard specificationId == "spec-recipes" else { throw ProjectSpecificationsError.notFound }
        let viewed = revisionId ?? "rev-2"
        guard let revision = revisions.first(where: { $0.id == viewed }) else { throw ProjectSpecificationsError.notFound }
        return ProjectSpecificationOpened(
            id: specificationId, document: document(viewed), revisions: revisions, currentRevisionId: "rev-2",
            viewedRevisionId: viewed, viewedContentHash: revision.contentHash, approvalState: approvalState,
            approvedRevisionId: approvedRevisionId, approvedAt: approvedAt)
    }

    func approve(projectId: String, teamId: String?, specificationId: String, revisionId: String,
                 contentHash: String) async throws {
        guard let revision = revisions.first(where: { $0.id == revisionId }), revision.contentHash == contentHash
        else { throw ProjectSpecificationsError.notFound }
        approvedRevisionId = revisionId
        approvedAt = UInt64(Date().timeIntervalSince1970)
    }
}
#endif
