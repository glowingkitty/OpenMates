import SwiftUI

struct ProjectFileApprovalCard: View {
    let entry: ProjectFileReviewCoordinator.Entry
    let onDecision: (ProjectFileReviewCoordinator.Entry, Bool) -> Void
    @State private var showsChange = true

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(entry.status == "applied" ? AppStrings.projectFileApplied :
                    entry.readPath != nil ? AppStrings.projectReadApprovalTitle : AppStrings.projectWriteApprovalTitle)
                .font(.omP).fontWeight(.bold)
            Text(entry.readPath ?? entry.mutation?.path ?? "")
                .font(.omSmall.monospaced())
                .textSelection(.enabled)
                .accessibilityIdentifier("project-file-path")
            if entry.readPath != nil {
                Text(AppStrings.projectReadApprovalDescription)
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            } else if let change = entry.mutation?.patch ?? entry.mutation?.content {
                DisclosureGroup(AppStrings.projectReviewChanges, isExpanded: $showsChange) {
                    ScrollView([.vertical, .horizontal]) {
                        Text(change).font(.omSmall.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(14)
                    }
                    .frame(maxHeight: 320)
                    .background(Color.grey0, in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityIdentifier("project-file-change-diff")
                }
            }
            if entry.status == "awaiting_approval" {
                HStack(spacing: 12) {
                    Button(entry.readPath != nil ? AppStrings.projectApproveRead : AppStrings.projectApproveWrite) {
                        onDecision(entry, true)
                    }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("project-file-approve")
                    Button(AppStrings.projectReject) { onDecision(entry, false) }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("project-file-reject")
                }
            }
        }
        .foregroundStyle(Color.fontPrimary)
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(Color.grey25, lineWidth: 1))
        .accessibilityIdentifier("project-file-approval-card")
    }
}

struct ProjectRemoteCommandReviewCard: View {
    let entry: ProjectRemoteCommandCoordinator.Entry
    let onDecision: (ProjectRemoteCommandCoordinator.Entry, Bool) -> Void
    let onStop: (ProjectRemoteCommandCoordinator.Entry) -> Void

    private var command: ProjectRemoteCommandPolicy { entry.review.command }
    private var canStop: Bool {
        ["preparing", "waiting_for_executor", "authorizing", "running"].contains(entry.status)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(AppStrings.projectCommandTitle).font(.omP).fontWeight(.bold)
            Text("\(entry.projectName) · \(entry.sourceName)")
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("remote-command-target")
            Text(AppStrings.projectCommandStatus(entry.status))
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
            Text(entry.review.explanation.summary).font(.omSmall)
            points(AppStrings.projectCommandEffects, entry.review.explanation.effects)
            points(AppStrings.projectCommandRisks, entry.review.explanation.risks)
            points(AppStrings.projectCommandUncertainty, entry.review.explanation.uncertainty)
            Text(AppStrings.projectCommandArguments).font(.omSmall).fontWeight(.semibold)
            let argv = command.argv.map { "  \($0)" }.joined(separator: "\n")
            codeBlock("[\n\(argv)\n]", id: "remote-command-argv")
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 8) {
                detail(AppStrings.projectCommandDirectory, command.cwd)
                detail(AppStrings.projectCommandAccess, command.sourceAccess == "read_only"
                    ? AppStrings.projectCommandReadOnly : AppStrings.projectCommandReadWrite)
                detail(AppStrings.projectCommandMode, command.mode == "foreground"
                    ? AppStrings.projectCommandForeground : AppStrings.projectCommandBackground)
                detail(AppStrings.projectCommandNetwork, command.networkProfile ?? AppStrings.projectCommandNone)
                detail(AppStrings.projectCommandWritable, command.writableProfiles.joined(separator: ", ").ifEmpty(AppStrings.projectCommandNone))
                detail(AppStrings.projectCommandCredentials, command.credentialProfiles.joined(separator: ", ").ifEmpty(AppStrings.projectCommandNone))
                detail(AppStrings.projectCommandLimit, "\(command.deadlineMs / 1000) s")
            }
            if !entry.latestOutput.isEmpty {
                DisclosureGroup(AppStrings.projectCommandOutput) {
                    codeBlock(entry.latestOutput, id: "remote-command-output")
                }
            }
            if let errorCode = entry.errorCode {
                Text("\(AppStrings.projectCommandFailed): \(errorCode)")
                    .font(.omSmall).foregroundStyle(Color.warning)
                    .accessibilityIdentifier("remote-command-error")
            }
            if entry.status == "pending" {
                HStack(spacing: 12) {
                    Button(AppStrings.projectCommandApprove) { onDecision(entry, true) }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("remote-command-approve")
                    Button(AppStrings.projectReject) { onDecision(entry, false) }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("remote-command-reject")
                }
            } else if canStop {
                Button(AppStrings.projectCommandStop) { onStop(entry) }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("remote-command-stop")
            }
        }
        .foregroundStyle(Color.fontPrimary)
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(Color.grey25, lineWidth: 1))
        .accessibilityIdentifier("remote-command-review-card")
    }

    @ViewBuilder private func points(_ title: String, _ values: [String]) -> some View {
        if !values.isEmpty {
            Text(title).font(.omSmall).fontWeight(.semibold)
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                Text("• \(value)").font(.omSmall)
            }
        }
    }

    private func codeBlock(_ content: String, id: String) -> some View {
        ScrollView([.vertical, .horizontal]) {
            Text(content).font(.omSmall.monospaced())
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
        }
        .frame(maxHeight: 320)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: 12))
        .accessibilityIdentifier(id)
    }

    private func detail(_ title: String, _ value: String) -> some View {
        GridRow {
            Text(title).foregroundStyle(Color.fontSecondary)
            Text(value).textSelection(.enabled)
        }
        .font(.omSmall)
    }
}

private extension String {
    func ifEmpty(_ fallback: String) -> String { isEmpty ? fallback : self }
}
