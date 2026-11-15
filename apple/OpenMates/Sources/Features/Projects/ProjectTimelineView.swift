// Specification: specifications/features/projects/specification.yml
// Assertions: projects.surface.semantic-parity
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/projects/ProjectTimeline.svelte
// CSS:     same file (<style>): .pt-entry, .pt-row, .pt-chip, .pt-detail, .pt-actions
//          frontend/packages/ui/src/styles/buttons.css (global button → OMPrimaryButtonStyle)
// Tokens:  ColorTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import Foundation
import SwiftUI

/// Presentation state of the Project Timeline tab; data and restore come from the core.
@MainActor
final class ProjectTimelineModel: ObservableObject {
    enum RestoreStatus: Equatable { case busy, done, failed }

    @Published private(set) var entries: [ProjectTimelineEntry] = []
    @Published private(set) var loading = false
    @Published private(set) var loadedOnce = false
    @Published private(set) var error: String?
    @Published var expandedId: String?
    @Published var confirmId: String?
    @Published private(set) var status: (id: String, state: RestoreStatus)?
    private var cursor: String?
    private let loader: ProjectTimelineLoading
    private let projectId: String
    private let teamId: String?

    init(loader: ProjectTimelineLoading, projectId: String, teamId: String?) {
        self.loader = loader
        self.projectId = projectId
        self.teamId = teamId
    }

    var hasMore: Bool { cursor != nil }

    func load(reset: Bool) async {
        guard !loading else { return }
        loading = true
        error = nil
        defer { loading = false; loadedOnce = true }
        do {
            let page = try await loader.page(projectId: projectId, teamId: teamId, before: reset ? nil : cursor)
            entries = reset ? page.entries : entries + page.entries
            cursor = page.nextCursor
        } catch {
            self.error = String(describing: error)
        }
    }

    func toggle(_ id: String) {
        expandedId = expandedId == id ? nil : id
        confirmId = nil
    }

    func restore(commitId: String) async {
        confirmId = nil
        status = (commitId, .busy)
        do {
            try await loader.restore(projectId: projectId, teamId: teamId, commitId: commitId)
            status = (commitId, .done)
            await load(reset: true)
        } catch {
            status = (commitId, .failed)
        }
    }
}

struct ProjectTimelineView: View {
    @StateObject var model: ProjectTimelineModel

    private static let actions: Set<String> = ["created", "updated", "edited", "restored", "renamed", "deleted", "adopted"]

    private func t(_ key: String) -> String { AppStrings.localized("projects.timeline_\(key)") }

    private func t(_ key: String, _ replacements: [String: String]) -> String {
        LocalizationManager.shared.text("projects.timeline_\(key)", replacements: replacements)
    }

    /// "1 file" / "{count} files" (web: ProjectTimeline.svelte uses the same two keys).
    private func filesCount(_ count: Int) -> String {
        t(count == 1 ? "files_count_singular" : "files_count", ["count": String(count)])
    }

    /// Same icon per row kind as web ProjectTimeline.svelte `ICONS`.
    private func icon(_ kind: String) -> String {
        kind == "commit" ? "project" : kind == "file_version" ? "docs" : "edit"
    }

    private func relative(_ seconds: UInt64) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        return formatter.localizedString(for: Date(timeIntervalSince1970: TimeInterval(seconds)), relativeTo: Date())
    }

    var body: some View {
        VStack(spacing: 12) {
            if let error = model.error {
                Text("\(t("error")) \(error)").foregroundStyle(Color.error)
                    .accessibilityIdentifier("project-timeline-error")
            }
            if model.error == nil, !model.loading, model.loadedOnce, model.entries.isEmpty {
                Text(t("empty")).foregroundStyle(Color.fontSecondary).padding(24)
                    .accessibilityIdentifier("project-timeline-empty")
            }
            ForEach(model.entries) { entry in
                entryView(entry)
            }
            if model.loading { Text(t("loading")).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            if model.hasMore, !model.loading {
                Button(t("load_more")) { Task { await model.load(reset: false) } }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .accessibilityIdentifier("project-timeline-load-more")
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 16)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-timeline")
        .task { await model.load(reset: true) }
    }

    private func entryView(_ entry: ProjectTimelineEntry) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if entry.commit != nil {
                Button { model.toggle(entry.id) } label: { row(entry) }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("project-timeline-commit-toggle-\(entry.id)")
                    .accessibilityAddTraits(model.expandedId == entry.id ? .isSelected : [])
            } else {
                row(entry)
            }
            if let commit = entry.commit, model.expandedId == entry.id { detail(entry, commit) }
        }
        .background(Color.grey10, in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-timeline-entry-\(entry.id)")
    }

    private func row(_ entry: ProjectTimelineEntry) -> some View {
        HStack(alignment: .top, spacing: 12) {
            // web `.pt-icon` fills the mask with --color-primary (the primary gradient).
            Icon(icon(entry.kind), size: 20).foregroundStyle(LinearGradient.primary).padding(.top, 2)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(t("author_\(entry.author)")).font(.omSmall.weight(.semibold))
                    if let action = entry.action.flatMap(Self.actionName), Self.actions.contains(action) {
                        Text(t("action_\(action)")).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                    Text(relative(entry.createdAt)).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
                if let commit = entry.commit {
                    Text(commit.message).foregroundStyle(Color.fontPrimary)
                    Text(commit.restoredFrom.map {
                        filesCount(commit.files.count) + " · " + t("restored_from", ["id": String($0.prefix(7))])
                    } ?? filesCount(commit.files.count))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                } else {
                    Text(entry.path ?? t("removed_file")).foregroundStyle(Color.fontPrimary)
                    if let from = entry.restoredFromVersion {
                        Text(t("restored_from_version", ["version": String(from)]))
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                }
            }
            Spacer(minLength: 0)
            if let version = entry.version {
                Text("v\(version)").font(.omXs).padding(.horizontal, 6)
                    .background(Color.grey20, in: Capsule())
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .contentShape(Rectangle())
    }

    /// The server sends `create`, `update`, `restore`, ...; the web strings use past tense.
    private static func actionName(_ action: String) -> String {
        switch action {
        case "create": "created"
        case "update": "updated"
        case "edit": "edited"
        case "restore": "restored"
        case "rename": "renamed"
        case "delete": "deleted"
        case "adopt": "adopted"
        default: action
        }
    }

    private func detail(_ entry: ProjectTimelineEntry, _ commit: ProjectTimelineCommit) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(commit.files.enumerated()), id: \.offset) { _, file in
                HStack {
                    Text(file.path ?? t("removed_file")).frame(maxWidth: .infinity, alignment: .leading)
                    if let change = file.change {
                        Text(t("change_\(change)")).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                    Text("v\(file.version)").font(.omXs).padding(.horizontal, 6)
                        .background(Color.grey20, in: Capsule())
                }
            }
            if model.confirmId == commit.id {
                Text(t("restore_prompt"))
                HStack {
                    Button(t("restore_confirm")) { Task { await model.restore(commitId: commit.id) } }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .accessibilityIdentifier("project-timeline-restore-confirm")
                    Button(t("restore_cancel")) { model.confirmId = nil }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("project-timeline-restore-cancel")
                }
            } else {
                Button(t("restore_button")) { model.confirmId = commit.id }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(model.status?.state == .busy)
                    .accessibilityIdentifier("project-timeline-restore-\(entry.id)")
            }
            if let status = model.status, status.id == commit.id {
                Text(status.state == .busy ? t("restore_busy") : status.state == .done ? t("restore_done") : t("restore_failed"))
                    .foregroundStyle(status.state == .failed ? Color.error : Color.fontSecondary)
                    .accessibilityIdentifier("project-timeline-restore-status")
                    .accessibilityValue(status.state == .busy ? "busy" : status.state == .done ? "done" : "error")
            }
        }
        .padding(.horizontal, 12).padding(.bottom, 12)
    }
}

#if DEBUG
/// Network-free loader with the web preview's "Recipe Manager" history
/// (ProjectTimeline.preview.ts); restore succeeds after a short pause.
@MainActor
final class ProjectTimelinePreviewLoader: ProjectTimelineLoading {
    func page(projectId: String, teamId: String?, before: String?) async throws -> ProjectTimelinePage {
        let now = UInt64(Date().timeIntervalSince1970)
        let files = [
            ProjectTimelineCommitFile(path: "web-app/index.html", version: 3, change: "modified"),
            ProjectTimelineCommitFile(path: "web-app/app.js", version: 3, change: "modified"),
        ]
        return ProjectTimelinePage(entries: [
            ProjectTimelineEntry(id: "commit-2", kind: "commit", createdAt: now - 600, author: "assistant",
                path: nil, version: nil, action: nil, restoredFromVersion: nil,
                commit: ProjectTimelineCommit(id: "c2c2c2c2c2", message: "Add recipe search and shopping list",
                                              restoredFrom: nil, files: files)),
            ProjectTimelineEntry(id: "version-1", kind: "file_version", createdAt: now - 3_600, author: "user",
                path: "web-app/styles.css", version: 2, action: "edit", restoredFromVersion: nil, commit: nil),
            ProjectTimelineEntry(id: "op-1", kind: "file_operation", createdAt: now - 7_200, author: "assistant",
                path: nil, version: nil, action: "delete", restoredFromVersion: nil, commit: nil),
            ProjectTimelineEntry(id: "commit-1", kind: "commit", createdAt: now - 86_400, author: "assistant",
                path: nil, version: nil, action: nil, restoredFromVersion: nil,
                commit: ProjectTimelineCommit(id: "c1c1c1c1c1", message: "Create the Recipe Manager app",
                    restoredFrom: nil,
                    files: [ProjectTimelineCommitFile(path: "web-app/app.js", version: 1, change: "added")])),
        ], nextCursor: nil)
    }

    func restore(projectId: String, teamId: String?, commitId: String) async throws {
        try await Task.sleep(for: .milliseconds(400))
    }
}
#endif
