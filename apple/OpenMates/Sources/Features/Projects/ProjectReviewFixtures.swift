#if DEBUG
import SwiftUI

enum ProjectReviewFixtures {
    static func fileEntry(status: String = "awaiting_approval") -> ProjectFileReviewCoordinator.Entry {
        let mutation = try! ProjectFileMutation(operation: "update_file", operationID: "preview-file-1",
            arguments: ["path": "docs/plan.md", "expected_base": String(repeating: "a", count: 64),
                        "patch": "@@ -1 +1 @@\n-Old project plan\n+Updated project plan"])
        return ProjectFileReviewCoordinator.Entry(id: "preview-file-1", accountID: "preview",
            scope: UUID(), chatID: "preview-chat", projectID: "preview-project",
            sourceID: "preview-source", mutation: mutation, readPath: nil,
            commitment: String(repeating: "b", count: 64), status: status, errorCode: nil)
    }

    static func commandEntry(status: String = "pending") -> ProjectRemoteCommandCoordinator.Entry {
        let review = ProjectRemoteCommandReview(protocolVersion: 1, executionId: "preview-run-1",
            chatId: "preview-chat", projectId: "preview-project", sourceId: "preview-source",
            state: "REVIEW_REQUIRED", createdAt: 1_700_000_000,
            reviewExpiresAt: 1_700_000_600, reviewToken: String(repeating: "x", count: 32),
            approvalRequirement: "one_run",
            command: ProjectRemoteCommandPolicy(argv: ["npm", "test", "--", "projects"],
                cwd: "src", mode: "foreground", sourceAccess: "read_only", deadlineMs: 60_000,
                writableProfiles: [], networkProfile: nil, credentialProfiles: []),
            explanation: ProjectRemoteCommandExplanation(
                summary: "Run the Project checks in the connected source.",
                effects: ["Runs the Projects test target"], risks: ["May take one minute"],
                uncertainty: ["The tests may report failures"]))
        return ProjectRemoteCommandCoordinator.Entry(id: review.executionId,
            accountID: "preview", scope: UUID(), review: review,
            projectName: "Website redesign", sourceName: "Source repository",
            status: status, latestOutput: "")
    }
}

/// Deliberately isolated debug data: no live approval or command is dispatched.
struct ProjectReviewFixtureView: View {
    @State private var file = ProjectReviewFixtures.fileEntry()
    @State private var command = ProjectReviewFixtures.commandEntry()

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                ProjectFileApprovalCard(entry: file) { _, accepted in
                    file.status = accepted ? "applied" : "rejected"
                }
                ProjectRemoteCommandReviewCard(entry: command, onDecision: { _, accepted in
                    command.status = accepted ? "running" : "rejected"
                    if accepted { command.latestOutput = "Projects tests passed.\n" }
                }, onStop: { _ in command.status = "stopped" })
            }
            .padding(16)
        }
        .background(Color.grey0.ignoresSafeArea())
        .accessibilityIdentifier("project-review-fixture")
    }
}
#endif
