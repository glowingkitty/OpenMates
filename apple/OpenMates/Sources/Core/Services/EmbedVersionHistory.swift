// Bounded encrypted artifact history; metadata and selected ciphertext travel separately.
// Web source: frontend/packages/ui/src/services/embedDiffStore.ts,
//             frontend/packages/ui/src/utils/embedVersionReconstruction.ts
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.versions.metadata-and-payload, storage.versions.bounded-reconstruction,
//             storage.cold.shared-team-authorized, storage.privacy.ciphertext-boundary
import Foundation
import Combine
import CryptoKit

struct EmbedVersionPage: Decodable, Sendable {
    let embedID: String
    let currentVersion: Int
    let versions: [EmbedVersionMetadata]
    let nextCursor: Int?
    let readonly: Bool
    enum CodingKeys: String, CodingKey {
        case embedID = "embed_id", currentVersion = "current_version", versions
        case nextCursor = "next_cursor", readonly
    }
}

struct EmbedVersionRow: Decodable, Sendable {
    let versionNumber: Int
    let encryptedSnapshot: String?
    let encryptedPatch: String?
    enum CodingKeys: String, CodingKey {
        case versionNumber = "version_number", encryptedSnapshot = "encrypted_snapshot", encryptedPatch = "encrypted_patch"
    }
}

struct EmbedVersionContent: Decodable, Sendable {
    let embedID: String
    let versionNumber: Int
    let currentVersion: Int
    let rows: [EmbedVersionRow]
    let bounded: Bool
    let readonly: Bool
    enum CodingKeys: String, CodingKey {
        case embedID = "embed_id", versionNumber = "version_number", currentVersion = "current_version", rows, bounded, readonly
    }
}

enum EmbedVersionHistoryFailure: Error, Equatable {
    case unavailable, invalidResponse, snapshotRequired, accessChanged, payloadTooLarge
    static func classify(_ error: Error) -> Self {
        if let failure = error as? Self { return failure }
        if error is CancellationError { return .accessChanged }
        if case APIError.httpError(let status, let message) = error {
            if status == 409 && message == "snapshot_required" { return .snapshotRequired }
            if status == 401 || status == 403 || status == 404 { return .accessChanged }
        }
        return .unavailable
    }
}

/// Captures one authenticated owner/Team context. Neither metadata nor content
/// may publish across any account, Team, deletion or server-profile transition.
@MainActor struct EmbedVersionHistorySession {
    let fetch: (String) async throws -> Data
    let decrypt: (String) async throws -> String
    let validate: () async throws -> Void
    let context: EmbedVersionReadContext
}

struct EmbedVersionReadContext: Equatable, Sendable {
    var chatID: String? = nil
    var projectID: String? = nil
    var teamID: String? = nil
    func path(embedID: String, version: Int? = nil, cursor: Int? = nil) throws -> String {
        guard !embedID.isEmpty, embedID.utf8.count <= 128,
              !(chatID != nil && projectID != nil),
              teamID == nil || chatID != nil || projectID != nil,
              version.map({ $0 > 0 }) ?? true, cursor.map({ $0 > 0 }) ?? true else {
            throw EmbedVersionHistoryFailure.invalidResponse
        }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        guard let id = embedID.addingPercentEncoding(withAllowedCharacters: allowed) else { throw EmbedVersionHistoryFailure.invalidResponse }
        var components = URLComponents()
        components.path = "/v1/embeds/" + id + "/versions" + (version.map { "/" + String($0) } ?? "")
        var query: [URLQueryItem] = []
        if let chatID { query.append(URLQueryItem(name: "chat_id", value: chatID)) }
        if let projectID { query.append(URLQueryItem(name: "project_id", value: projectID)) }
        if let teamID { query.append(URLQueryItem(name: "team_id", value: teamID)) }
        if version != nil { query.append(URLQueryItem(name: "capability", value: "bounded-v1")) }
        else {
            query += [URLQueryItem(name: "order", value: "desc"), URLQueryItem(name: "limit", value: "32")]
            if let cursor { query.append(URLQueryItem(name: "cursor", value: String(cursor))) }
        }
        components.queryItems = query
        // URLComponents would escape an already encoded embed ID a second time.
        guard let queryText = components.percentEncodedQuery else { throw EmbedVersionHistoryFailure.invalidResponse }
        return "/v1/embeds/" + id + "/versions" + (version.map { "/" + String($0) } ?? "") + "?" + queryText
    }
}

enum EmbedVersionReconstruction {
    static let maximumRows = 33
    static let maximumResponseBytes = 4 * 1024 * 1024
    static let maximumContentBytes = 2 * 1024 * 1024

    @MainActor static func reconstruct(_ response: EmbedVersionContent, embedID: String, version: Int,
        decrypt: (String) async throws -> String, validate: () async throws -> Void) async throws -> String {
        guard version > 0, version < Int.max, response.currentVersion < Int.max, response.bounded, response.embedID == embedID, response.versionNumber == version,
              response.currentVersion >= version, !response.rows.isEmpty,
              response.rows.count <= maximumRows, response.rows.first?.encryptedSnapshot != nil,
              response.rows.last?.versionNumber == version else { throw EmbedVersionHistoryFailure.invalidResponse }
        var expected = response.rows[0].versionNumber
        guard expected > 0, version - expected <= 32 else { throw EmbedVersionHistoryFailure.invalidResponse }
        var content: String?
        for row in response.rows {
            try await validate(); try Task.checkCancellation()
            guard row.versionNumber == expected, expected <= version else { throw EmbedVersionHistoryFailure.invalidResponse }
            expected += 1
            if let snapshot = row.encryptedSnapshot, !snapshot.isEmpty {
                content = try await decrypt(snapshot)
            } else if let patch = row.encryptedPatch, !patch.isEmpty, let previous = content {
                content = try EmbedVersionPatch.apply(try await decrypt(patch), to: previous)
            } else { throw EmbedVersionHistoryFailure.invalidResponse }
            try await validate(); try Task.checkCancellation()
            guard let value = content, value.utf8.count <= maximumContentBytes else { throw EmbedVersionHistoryFailure.payloadTooLarge }
        }
        guard let content else { throw EmbedVersionHistoryFailure.invalidResponse }
        return content
    }
}

@MainActor final class EmbedVersionHistoryController: ObservableObject {
    @Published private(set) var versions: [EmbedVersionMetadata] = []
    @Published private(set) var currentVersion = 1
    @Published private(set) var selectedVersion = 1
    /// Identity of the supplied EmbedRecord payload, independent of the server head.
    @Published private(set) var payloadVersion = 1
    @Published private(set) var content: String?
    @Published private(set) var loadingMetadata = false
    @Published private(set) var loadingContent = false
    @Published private(set) var nextCursor: Int?
    @Published private(set) var failure: EmbedVersionHistoryFailure?
    private var session: EmbedVersionHistorySession?
    private var embedID = ""
    private var generation = UUID()
    private var selectionGeneration = UUID()
    private var failedSelection: Int?
    var isHistorical: Bool { selectedVersion != currentVersion }
    /// Verified selections stay read-only even when they represent a newer head.
    var requiresVersionContent: Bool { isHistorical || selectedVersion != payloadVersion || failure == .accessChanged }

    func reset() {
        generation = UUID(); selectionGeneration = UUID(); session = nil
        versions = []; content = nil; failure = nil; nextCursor = nil
        loadingContent = false; loadingMetadata = false; failedSelection = nil
        currentVersion = 1; selectedVersion = 1; payloadVersion = 1
    }
    func open(embedID: String, currentVersion: Int, session: EmbedVersionHistorySession?) async {
        reset(); self.embedID = embedID; self.currentVersion = max(1, currentVersion); selectedVersion = self.currentVersion
        payloadVersion = self.currentVersion
        self.session = session
        guard session != nil else { failure = .unavailable; return }
        await loadMore()
    }
    func loadMore() async {
        guard !loadingMetadata, !loadingContent, let session else { return }
        let request = generation; let cursor = nextCursor
        guard versions.isEmpty || cursor != nil else { return }
        loadingMetadata = true; failure = nil; failedSelection = nil
        defer { if request == generation { loadingMetadata = false } }
        do {
            try await session.validate()
            let data = try await session.fetch(try session.context.path(embedID: embedID, cursor: cursor))
            try await session.validate(); try Task.checkCancellation()
            guard request == generation else { return }
            let page = try Self.decodePage(data, embedID: embedID, cursor: cursor)
            // An edit racing a second page requires a refresh, never a mixed timeline.
            guard versions.isEmpty || page.currentVersion == currentVersion else { throw EmbedVersionHistoryFailure.invalidResponse }
            guard Set(versions.map(\.versionNumber)).isDisjoint(with: Set(page.versions.map(\.versionNumber))) else { throw EmbedVersionHistoryFailure.invalidResponse }
            let firstPage = versions.isEmpty
            if firstPage { currentVersion = page.currentVersion; selectedVersion = currentVersion }
            versions += page.versions; nextCursor = page.nextCursor
            if firstPage, selectedVersion != payloadVersion {
                // Metadata cannot relabel the original cached payload as a newer head.
                loadingMetadata = false
                await select(selectedVersion)
            }
        } catch { if request == generation { reject(error) } }
    }
    func select(_ version: Int) async {
        guard !loadingMetadata, version == currentVersion || versions.contains(where: { $0.versionNumber == version }), let session else { return }
        selectionGeneration = UUID(); let selection = selectionGeneration; let request = generation
        selectedVersion = version; content = nil; failure = nil; failedSelection = nil
        loadingContent = requiresVersionContent
        defer { if selection == selectionGeneration && request == generation { loadingContent = false } }
        do {
            try await session.validate(); try Task.checkCancellation()
            guard request == generation, selection == selectionGeneration else { return }
            if !requiresVersionContent { return }
            let data = try await session.fetch(try session.context.path(embedID: embedID, version: version))
            try await session.validate(); try Task.checkCancellation()
            guard request == generation, selection == selectionGeneration else { return }
            guard data.count <= EmbedVersionReconstruction.maximumResponseBytes else { throw EmbedVersionHistoryFailure.payloadTooLarge }
            let response = try JSONDecoder().decode(EmbedVersionContent.self, from: data)
            // A head change between metadata and payload reads needs a fresh index.
            // Never publish content under a stale claim that it is the latest version.
            guard response.currentVersion == currentVersion else {
                versions = []; nextCursor = nil
                throw EmbedVersionHistoryFailure.invalidResponse
            }
            let text = try await EmbedVersionReconstruction.reconstruct(response, embedID: embedID, version: version,
                decrypt: session.decrypt, validate: {
                    try await session.validate()
                    guard request == self.generation, selection == self.selectionGeneration else { throw CancellationError() }
                })
            try await session.validate()
            guard request == generation, selection == selectionGeneration else { return }
            content = text
        } catch {
            if request == generation, selection == selectionGeneration { failedSelection = version; reject(error) }
        }
    }
    func retry() async {
        if let failedSelection, !versions.isEmpty { await select(failedSelection) }
        else { await loadMore() }
    }
    private func reject(_ error: Error) {
        content = nil; failure = .classify(error)
        if failure == .accessChanged { versions = []; nextCursor = nil }
    }
    static func decodePage(_ data: Data, embedID: String, cursor: Int?) throws -> EmbedVersionPage {
        guard data.count <= 64 * 1024,
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rows = value["versions"] as? [[String: Any]], rows.count <= 32,
              rows.allSatisfy({ $0["encrypted_snapshot"] == nil && $0["encrypted_patch"] == nil }) else {
            throw EmbedVersionHistoryFailure.invalidResponse
        }
        let page = try JSONDecoder().decode(EmbedVersionPage.self, from: data)
        guard page.embedID == embedID, page.currentVersion > 0, page.currentVersion < Int.max else { throw EmbedVersionHistoryFailure.invalidResponse }
        var previous = cursor ?? (page.currentVersion < Int.max ? page.currentVersion + 1 : Int.max)
        for row in page.versions {
            guard row.versionNumber > 0, row.versionNumber <= page.currentVersion, row.versionNumber < previous,
                  row.createdAt >= 0 else { throw EmbedVersionHistoryFailure.invalidResponse }
            previous = row.versionNumber
        }
        if let next = page.nextCursor {
            guard next > 1, !page.versions.isEmpty, next == page.versions.last?.versionNumber,
                  cursor.map({ next < $0 }) ?? true else { throw EmbedVersionHistoryFailure.invalidResponse }
        }
        return page
    }
}

#if os(iOS) || os(macOS)
extension EmbedVersionHistorySession {
    static func capture(embed: EmbedRecord, chatID: String?, allEmbeds: [String: EmbedRecord]) async -> Self? {
        guard let chatID, !chatID.isEmpty, let accountID = await AuthManager.currentUserId() else { return nil }
        let profile = ServerProfile.current(), scope = OfflineStore.shared.scopeGeneration
        let workspace = TeamWorkspaceContext.shared
        let team = APIRequestTeamContext(epoch: workspace.contextEpoch, teamID: workspace.teamID)
        let deletion = OfflineStore.shared.chatDeletionVersion(chatID)
        // A Team request needs both its active workspace and this chat's stored Team.
        let storedTeam = OfflineStore.shared.loadChat(id: chatID)?.teamId
        guard storedTeam == team.teamID else { return nil }
        let context = EmbedVersionReadContext(chatID: chatID, teamID: storedTeam)
        let validate: () async throws -> Void = {
            try Task.checkCancellation()
            guard await AuthManager.currentUserId() == accountID,
                  scope == OfflineStore.shared.scopeGeneration, profile == ServerProfile.current(),
                  team.epoch == workspace.contextEpoch, team.teamID == workspace.teamID,
                  deletion == OfflineStore.shared.chatDeletionVersion(chatID) else { throw CancellationError() }
        }
        return Self(fetch: { path in
            try await validate()
            let data: Data = try await APIClient.shared.request(.get, path: path, serverProfile: profile,
                expectedAccountID: accountID, expectedScope: scope, expectedTeamContext: team)
            try await validate(); return data
        }, decrypt: { ciphertext in
            try await validate()
            guard let key = await EmbedKeyManager.shared.key(for: embed, chatId: chatID, allEmbeds: allEmbeds) else {
                throw EmbedVersionHistoryFailure.accessChanged
            }
            try await validate()
            let text = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
            try await validate(); return text
        }, validate: validate, context: context)
    }
}
#endif
