// Debug-only local embed version client for the dev embed preview gallery.
// With `--ui-test-code-edit-versions` the preview code embed behaves like a stored
// personal Project file: the header Edit button appears and Save commits the
// next version to this in-memory client instead of the server, so XCUITest can
// prove the edit/save flow without an account. Never compiled into release builds.
// Specification: specifications/features/embed-user-edits/specification.yml
// Assertions: embed-user-edits.edit.next-version, embed-user-edits.header.edit-save-button

#if DEBUG
import Foundation

final class DevPreviewEmbedVersions: EmbedVersionsCoreClient {
    static let launchArgument = "--ui-test-code-edit-versions"
    static let projectId = "dev-preview-project"
    static var enabled: Bool { ProcessInfo.processInfo.arguments.contains(launchArgument) }
    static let shared = DevPreviewEmbedVersions()

    private var heads: [String: Int64] = [:]
    private(set) var savedContents: [String: String] = [:]

    func commitEdit(embedId: String, scope: EmbedScopeRecord, baseVersion: Int64, content: String) async throws -> EmbedRevisionOutcomeRecord {
        let head = heads[embedId] ?? baseVersion
        guard head == baseVersion else { throw EmbedEditError.VersionConflict(currentVersion: head) }
        let next = head + 1
        heads[embedId] = next
        savedContents[embedId] = content
        return EmbedRevisionOutcomeRecord(embedId: embedId, operationId: UUID().uuidString, version: next, baseVersion: head,
                                          action: .edit, restoredFrom: nil, surface: .project, idempotent: false,
                                          cacheSynchronized: true, event: .written)
    }

    private func unsupported() -> EmbedEditError { .Internal(reason: "dev_preview_unsupported") }
    func versionHistory(embedId: String, scope: EmbedScopeRecord?) async throws -> EmbedVersionHistoryRecord {
        EmbedVersionHistoryRecord(embedId: embedId, currentVersion: heads[embedId] ?? 1, versions: [])
    }
    func restoreVersion(embedId: String, scope: EmbedScopeRecord, fromVersion: Int64) async throws -> EmbedRevisionOutcomeRecord { throw unsupported() }
    func startEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceJobRecord { throw unsupported() }
    func enhanceStatus(operationId: String) async throws -> ImageEnhanceJobRecord { throw unsupported() }
    func waitEnhance(operationId: String, deadlineMs: UInt64) async throws -> ImageEnhanceJobRecord { throw unsupported() }
    func saveEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceSavedRecord { throw unsupported() }
    func pendingEnhanceOperation(embedId: String) -> String? { nil }
    func rememberEnhanceOperation(_ operationId: String?, embedId: String) {}
}
#endif
