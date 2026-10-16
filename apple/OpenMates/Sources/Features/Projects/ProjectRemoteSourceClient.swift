// Web source: frontend/packages/ui/src/services/projectService.ts
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.files.no-server-decryption-authority, projects.files.connected-embed-previews, projects.surface.semantic-parity
import CryptoKit
import Foundation

struct ProjectRemoteEntryChild {
    let path: String
    let kind: String
    var name: String { path.split(separator: "/").last.map(String.init) ?? path }
}

struct ProjectRemoteEntry: Identifiable {
    let path: String
    let kind: String
    let sizeBytes: Int?
    let childFileCount: Int?
    let childFolderCount: Int?
    let childSummaryTruncated: Bool
    let children: [ProjectRemoteEntryChild]
    let childFileSizeBytes: Int?
    var id: String { path }
    var name: String { path.split(separator: "/").last.map(String.init) ?? path }

    init(path: String, kind: String, sizeBytes: Int?, childFileCount: Int?,
         childFolderCount: Int?, childSummaryTruncated: Bool,
         children: [ProjectRemoteEntryChild] = [], childFileSizeBytes: Int? = nil) {
        self.path = path
        self.kind = kind
        self.sizeBytes = sizeBytes
        self.childFileCount = childFileCount
        self.childFolderCount = childFolderCount
        self.childSummaryTruncated = childSummaryTruncated
        self.children = children
        self.childFileSizeBytes = childFileSizeBytes
    }

    /// Retain the web list DTO's optional folder summary without changing the
    /// connected source request, version fence or response authority.
    static func decode(_ row: [String: Any]) throws -> ProjectRemoteEntry {
        guard let path = row["path"] as? String, ProjectWorkspacePath.normalized(path) != nil,
              let kind = row["kind"] as? String, kind == "file" || kind == "directory" else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let children = try (row["children"] as? [[String: Any]] ?? []).map { child -> ProjectRemoteEntryChild in
            guard let childPath = child["path"] as? String, ProjectWorkspacePath.normalized(childPath) != nil,
                  let childKind = child["kind"] as? String, childKind == "file" || childKind == "directory" else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            return ProjectRemoteEntryChild(path: childPath, kind: childKind)
        }
        return ProjectRemoteEntry(path: path, kind: kind, sizeBytes: row["sizeBytes"] as? Int,
            childFileCount: row["childFileCount"] as? Int,
            childFolderCount: row["childFolderCount"] as? Int,
            childSummaryTruncated: row["childSummaryTruncated"] as? Bool ?? false,
            children: children, childFileSizeBytes: row["childFileSizeBytes"] as? Int)
    }
}

struct ProjectRemoteDirectory {
    let entries: [ProjectRemoteEntry]
    let omitted: Int
    let excluded: Int
    let nextCursor: String?
}

/// Matches projectRemoteSources.ts: unknown extensions may still be plain
/// text. The connected source enforces hidden/private/binary read policy.
enum ProjectRemotePreviewPolicy {
    private static let binaryExtensions: Set<String> = [
        "7z", "avi", "bin", "bmp", "dmg", "doc", "docx", "dylib", "exe", "gif", "gz", "ico", "jar",
        "avif", "svg", "jpeg", "jpg", "mov", "mp3", "mp4", "odt", "pdf", "png", "ppt", "pptx", "rar", "so", "tar",
        "ttf", "wasm", "webm", "webp", "woff", "woff2", "xls", "xlsx", "zip",
    ]

    private static let languages = ["c": "c", "cjs": "javascript", "cpp": "cpp", "css": "css",
        "entitlements": "entitlements", "go": "go", "gradle": "gradle", "h": "c", "hpp": "cpp",
        "html": "html", "java": "java", "js": "javascript", "jsx": "javascript", "kt": "kotlin",
        "mjs": "javascript", "php": "php", "plist": "plist", "py": "python", "rb": "ruby", "rs": "rust",
        "sh": "bash", "sql": "sql", "svelte": "svelte", "swift": "swift", "toml": "toml", "ts": "typescript",
        "tsx": "typescript", "xml": "xml", "yaml": "yaml", "yml": "yaml"]

    static func language(_ path: String) -> String {
        let name = path.split(separator: "/").last.map(String.init)?.lowercased() ?? ""
        if name == "dockerfile" || name == "makefile" { return name }
        let suffix = name.split(separator: ".").last.map(String.init) ?? ""
        if ["md", "mdx"].contains(suffix) { return "markdown" }
        if ["json", "jsonl"].contains(suffix) { return "json" }
        return languages[suffix] ?? "text"
    }

    static func appID(_ path: String) -> String {
        let suffix = path.split(separator: ".").last.map(String.init)?.lowercased() ?? ""
        if ["md", "mdx", "txt", "rst"].contains(suffix) { return "docs" }
        if ["png", "jpg", "jpeg", "gif", "webp", "avif", "svg"].contains(suffix) { return "images" }
        if suffix == "pdf" { return "pdf" }
        if ["xls", "xlsx", "csv", "ods"].contains(suffix) { return "sheets" }
        return language(path) == "text" ? "files" : "code"
    }

    static func kindLabel(_ path: String) -> String {
        let suffix = path.split(separator: ".").last.map(String.init)?.lowercased() ?? ""
        let labels = ["md": "Markdown", "mdx": "Markdown", "rst": "reStructuredText", "txt": "Text",
            "plist": "Property list", "pdf": "PDF", "csv": "CSV", "png": "PNG image", "jpg": "JPEG image",
            "jpeg": "JPEG image", "ts": "TypeScript", "tsx": "TypeScript", "js": "JavaScript", "jsx": "JavaScript",
            "json": "JSON", "yaml": "YAML", "yml": "YAML", "html": "HTML", "css": "CSS", "toml": "TOML"]
        return labels[suffix] ?? (language(path) == "text" ? "File" : language(path).capitalized)
    }

    static func embed(sourceID: String, sourceLabel: String, path: String, text: ProjectRemoteText) -> EmbedRecord {
        EmbedRecord(id: "remote:\(sourceID):\(path)", type: "code-code", status: .finished,
            data: .raw(["type": AnyCodable("remote_file_preview"), "source_id": AnyCodable(sourceID),
                "remote_source_label": AnyCodable(sourceLabel), "path": AnyCodable(path),
                "filename": AnyCodable(path.split(separator: "/").last.map(String.init) ?? path),
                "language": AnyCodable(language(path)), "code": AnyCodable(text.content),
                "line_count": AnyCodable(text.lineCount), "size_bytes": AnyCodable(text.sizeBytes),
                "safety_flags": AnyCodable(text.truncated ? ["truncated"] : [])]),
            parentEmbedId: nil, appId: appID(path), skillId: "code", embedIds: nil, createdAt: nil)
    }

    static func canReadText(_ path: String) -> Bool {
        guard ProjectWorkspacePath.normalized(path) != nil else { return false }
        let name = path.split(separator: "/").last.map(String.init)?.lowercased() ?? ""
        let suffix = name.contains(".") ? name.split(separator: ".", omittingEmptySubsequences: false).last.map(String.init) ?? "" : ""
        return !binaryExtensions.contains(suffix)
    }
}

/// Cursor-capable sources are paged remotely. Older connected CLIs return all
/// entries in one response, which is retained only in this scoped memory value.
struct ProjectRemotePagination {
    static let pageSize = 48
    private(set) var pageIndex = 0
    private(set) var nextCursor: String?
    private(set) var omitted = 0
    private(set) var entries: [ProjectRemoteEntry] = []
    private var cursors: [String?] = [nil]
    private var legacy: ProjectRemoteDirectory?

    var firstEntryNumber: Int { entries.isEmpty ? 0 : pageIndex * Self.pageSize + 1 }
    var lastEntryNumber: Int { pageIndex * Self.pageSize + entries.count }
    var totalEntryCount: Int { lastEntryNumber + omitted }

    func cursor(for index: Int) -> String? {
        cursors.indices.contains(index) ? cursors[index] : nil
    }

    func canShow(_ index: Int) -> Bool {
        index >= 0 && (index <= pageIndex || (index == pageIndex + 1 && nextCursor != nil))
    }

    mutating func install(_ directory: ProjectRemoteDirectory, page index: Int) {
        if directory.entries.count > Self.pageSize && directory.nextCursor == nil {
            legacy = directory
        }
        if let legacy {
            let start = index * Self.pageSize
            entries = Array(legacy.entries.dropFirst(start).prefix(Self.pageSize))
            nextCursor = start + entries.count < legacy.entries.count ? entries.last?.name : nil
            omitted = legacy.omitted + max(0, legacy.entries.count - start - entries.count)
        } else {
            entries = Array(directory.entries.prefix(Self.pageSize))
            nextCursor = directory.nextCursor
            omitted = directory.omitted + max(0, directory.entries.count - entries.count)
        }
        pageIndex = index
        cursors = Array(cursors.prefix(index + 1))
        cursors.append(nextCursor)
    }

    mutating func showLegacyPage(_ index: Int) -> Bool {
        guard let legacy, canShow(index) else { return false }
        install(legacy, page: index)
        return true
    }
}

struct ProjectRemoteText {
    let content: String
    let truncated: Bool
    let sizeBytes: Int
    let lineCount: Int
    let expectedBase: String?
}

struct ProjectRemoteTransferResult {
    let completed: [String]
    let failedCount: Int
}

struct ProjectRemoteSearchResult {
    let matches: [ProjectRemoteEntry]
    let omitted: Int
}

@MainActor
final class ProjectRemoteSourceClient {
    private struct Created: Decodable {
        let sourceSessionId: String?
        let keyEpoch: Int?
        let routingIdentity: RoutingIdentity?
    }
    private struct RoutingIdentity: Decodable {
        let contextType: String
        let contextIdHash: String
        let hostMemberHash: String
        let hostDeviceFingerprintHash: String
        let requesterMemberHash: String
        let requesterDeviceFingerprintHash: String
    }
    private struct Polled: Decodable { let encryptedEnvelope: String }
    private struct Routing {
        let sourceSessionID: String
        let keyEpoch: Int
        let team: ProjectRemoteBridgeCrypto.TeamRouting?
    }

    func list(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
              path: String = ".", cursor: String? = nil, maxEntries: Int = 48,
              fence: ProjectsWorkspaceFence) async throws -> ProjectRemoteDirectory {
        guard path == "." || ProjectWorkspacePath.normalized(path) != nil,
              maxEntries > 0, maxEntries <= 500 else { throw ProjectsWorkspaceError.invalidResponse }
        var arguments: [String: Any] = ["path": path, "maxEntries": maxEntries]
        if let cursor { arguments["cursor"] = cursor }
        let result = try await request(project: project, source: source, operation: "list", arguments: arguments, fence: fence)
        guard let rows = result["entries"] as? [[String: Any]], rows.count <= 512,
              let omitted = result["omitted"] as? Int, omitted >= 0 else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let entries = try rows.map(ProjectRemoteEntry.decode)
        return ProjectRemoteDirectory(entries: entries, omitted: omitted,
            excluded: result["excluded"] as? Int ?? 0, nextCursor: result["nextCursor"] as? String)
    }

    func searchFiles(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                     query: String, priorityPath: String?,
                     fence: ProjectsWorkspaceFence) async throws -> ProjectRemoteSearchResult {
        guard !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              query.utf8.count <= 200,
              priorityPath.map { $0 == "." || ProjectWorkspacePath.normalized($0) != nil } ?? true else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        var arguments: [String: Any] = ["query": query, "target": "files",
            "mode": "literal", "path": ".", "max_results": 100]
        if let priorityPath, priorityPath != "." { arguments["priority_path"] = priorityPath }
        let result = try await request(project: project, source: source,
            operation: "search", arguments: arguments, fence: fence)
        guard let rows = result["matches"] as? [[String: Any]], rows.count <= 100,
              let omitted = result["omitted"] as? Int, omitted >= 0 else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let matches = try rows.map { row -> ProjectRemoteEntry in
            guard let path = row["path"] as? String,
                  ProjectWorkspacePath.normalized(path) != nil else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            let kind = row["kind"] as? String ?? "file"
            guard kind == "file" || kind == "directory" else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            return ProjectRemoteEntry(path: path, kind: kind, sizeBytes: nil,
                childFileCount: nil, childFolderCount: nil, childSummaryTruncated: false)
        }
        return ProjectRemoteSearchResult(matches: matches, omitted: omitted)
    }

    /// Uses the existing encrypted remote-read exchange, with the web README bounds.
    func readReadmeImage(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                         path: String, fence: ProjectsWorkspaceFence) async throws -> Data {
        guard ProjectWorkspacePath.normalized(path) != nil else { throw ProjectsWorkspaceError.invalidContext }
        return try await Self.assembleReadmeImage { offset in
            try Task.checkCancellation()
            try await fence.check()
            return try await self.request(project: project, source: source, operation: "read_image_chunk",
                arguments: ["path": path, "offset": offset], fence: fence)
        }
    }

    static func assembleReadmeImage(read: (Int) async throws -> [String: Any]) async throws -> Data {
        var data = Data()
        var total: Int?
        var mime: String?
        var hash: String?
        repeat {
            let offset = data.count
            let result = try await read(offset)
            guard let size = result["size_bytes"] as? Int, size > 0, size <= 2 * 1024 * 1024,
                  let resultOffset = result["offset"] as? Int, resultOffset == offset,
                  let type = result["mime_type"] as? String,
                  ["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"].contains(type),
                  let identity = result["content_hash"] as? String, !identity.isEmpty,
                  let encoded = result["content_base64"] as? String, let chunk = Data(base64Encoded: encoded),
                  offset < size, chunk.count == min(128 * 1024, size - offset),
                  total == nil || (total == size && mime == type && hash == identity) else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            total = size; mime = type; hash = identity
            data.append(chunk)
        } while data.count < (total ?? 0)
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard digest == hash else { throw ProjectsWorkspaceError.invalidResponse }
        return data
    }

    func readText(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                  path: String, fence: ProjectsWorkspaceFence) async throws -> ProjectRemoteText {
        guard ProjectWorkspacePath.normalized(path) != nil else { throw ProjectsWorkspaceError.invalidResponse }
        let result = try await request(project: project, source: source, operation: "read_text",
            arguments: ["path": path, "max_bytes": 180 * 1024, "max_lines": 4_000], fence: fence)
        guard let content = result["content"] as? String,
              let truncated = result["truncated"] as? Bool,
              let sizeBytes = result["sizeBytes"] as? Int, sizeBytes >= 0,
              let lineCount = result["lineCount"] as? Int, lineCount >= 0,
              content.utf8.count <= 200 * 1024 else { throw ProjectsWorkspaceError.invalidResponse }
        let expectedBase = result["expected_base"] as? String
        guard !truncated || expectedBase == nil else { throw ProjectsWorkspaceError.invalidResponse }
        return ProjectRemoteText(content: content, truncated: truncated,
            sizeBytes: sizeBytes, lineCount: lineCount, expectedBase: expectedBase)
    }

    func downloadOriginal(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                          path: String, fence: ProjectsWorkspaceFence, maximumBytes: Int? = nil,
                          progress: @escaping (Int, Int) -> Void) async throws -> URL {
        guard ProjectWorkspacePath.normalized(path) != nil else { throw ProjectsWorkspaceError.invalidResponse }
        let unsafeName = path.split(separator: "/").last.map(String.init) ?? "download"
        let filename = String(unsafeName.map { character in
            character.isASCII && !"<>:\"/\\|?*".contains(character) && !character.isNewline ? character : "_"
        }.prefix(255))
        guard !filename.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("OpenMatesProjectDownloads", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.complete])
        let destination = directory.appendingPathComponent(filename)
        guard FileManager.default.createFile(atPath: destination.path, contents: nil,
            attributes: [.protectionKey: FileProtectionType.complete]) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let output = try FileHandle(forWritingTo: destination)
        var total: Int?
        var identity: String?
        var offset = 0
        do {
            repeat {
                try Task.checkCancellation()
                try await fence.check()
                let result = try await request(project: project, source: source,
                    operation: "read_file_chunk", arguments: ["path": path, "offset": offset], fence: fence)
                guard let size = result["size_bytes"] as? Int, size >= 0, offset <= size,
                      let resultOffset = result["offset"] as? Int, resultOffset == offset,
                      let fileIdentity = result["file_identity"] as? String,
                      let chunkHash = result["chunk_hash"] as? String,
                      let encoded = result["content_base64"] as? String,
                      let bytes = Data(base64Encoded: encoded),
                      bytes.count == min(128 * 1024, size - offset),
                      total == nil || (total == size && identity == fileIdentity) else {
                    throw ProjectsWorkspaceError.invalidResponse
                }
                try Self.validateDownloadSize(total: size, offset: offset, chunkBytes: bytes.count, maximumBytes: maximumBytes)
                let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
                guard digest == chunkHash else { throw ProjectsWorkspaceError.invalidResponse }
                try await fence.check()
                try output.write(contentsOf: bytes)
                offset += bytes.count
                total = size
                identity = fileIdentity
                progress(offset, size)
            } while offset < (total ?? 0)
            guard offset == total else { throw ProjectsWorkspaceError.invalidResponse }
            try output.close()
            try await fence.check()
            return destination
        } catch {
            try? output.close()
            try? FileManager.default.removeItem(at: directory)
            throw error
        }
    }

    /// Automatic previews are bounded before writing even the first received chunk.
    /// Explicit original downloads pass no limit and preserve their existing behavior.
    static func validateDownloadSize(total: Int, offset: Int, chunkBytes: Int,
                                     maximumBytes: Int?) throws {
        guard total >= 0, offset >= 0, offset <= total,
              chunkBytes >= 0, chunkBytes <= total - offset else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        if let maximumBytes {
            guard maximumBytes > 0, total <= maximumBytes,
                  chunkBytes <= maximumBytes - offset else {
                throw ProjectsWorkspaceError.invalidResponse
            }
        }
    }

    func executeProjectFileJob(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                               operation: String, arguments: [String: Any],
                               chatID: String, operationID: String,
                               proposalDigest: String?,
                               approvedIgnoredRead: String? = nil,
                               fence: ProjectsWorkspaceFence) async throws -> [String: Any] {
        let supported = ["list", "search", "read_text", "create_file", "update_file"]
        guard supported.contains(operation) else { throw ProjectsWorkspaceError.invalidResponse }
        let isWrite = operation == "create_file" || operation == "update_file"
        guard !isWrite || (proposalDigest != nil && source.capabilities.contains("write_request")) else {
            throw ProjectsWorkspaceError.invalidContext
        }
        var requestArguments = arguments
        if operation == "read_text" {
            requestArguments["max_bytes"] = 180 * 1024
            requestArguments["max_lines"] = 4_000
        }
        if isWrite {
            requestArguments = ["chat_id": chatID, "mutation": arguments]
        }
        return try await request(project: project, source: source, operation: operation,
                                 arguments: requestArguments, fence: fence,
                                 writeContext: isWrite ? (chatID, operationID, proposalDigest!) : nil,
                                 approvedIgnoredRead: approvedIgnoredRead.map { ($0, chatID, operationID) })
    }

    func transfer(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                  paths: [String], destinationPath: String, move: Bool,
                  fence: ProjectsWorkspaceFence) async throws -> ProjectRemoteTransferResult {
        func strict(_ path: String) -> Bool {
            guard path.utf8.count <= 4096, ProjectWorkspacePath.normalized(path) != nil else { return false }
            return path.split(separator: "/").allSatisfy { !$0.hasPrefix(".") }
        }
        guard (1...20).contains(paths.count), Set(paths).count == paths.count,
              paths.allSatisfy(strict), destinationPath == "." || strict(destinationPath),
              source.capabilities.contains("write_request") else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let operation = move ? "move_entries" : "copy_entries"
        let result = try await request(project: project, source: source,
            operation: operation, arguments: ["paths": paths,
                "destination_path": destinationPath, "user_initiated": true], fence: fence,
            userInitiated: true)
        guard result["operation"] as? String == operation,
              result["destination_path"] as? String == destinationPath,
              let completed = result["completed"] as? [String],
              let failed = result["failed"] as? [[String: Any]],
              completed.allSatisfy({ paths.contains($0) }),
              failed.allSatisfy({ row in paths.contains(row["path"] as? String ?? "") }) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        return ProjectRemoteTransferResult(completed: completed, failedCount: failed.count)
    }

    private func request(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                         operation: String, arguments: [String: Any],
                         fence: ProjectsWorkspaceFence,
                         writeContext: (chatID: String, operationID: String, proposalDigest: String)? = nil,
                         approvedIgnoredRead: (path: String, chatID: String, operationID: String)? = nil,
                         userInitiated: Bool = false) async throws -> [String: Any] {
        let requiredCapability = writeContext != nil || userInitiated
            ? "write_request" : (operation == "search" ? "search" : "read")
        if source.status == "offline" { throw ProjectsWorkspaceError.sourceOffline }
        guard source.status == "connected", source.capabilities.contains(requiredCapability) else {
            throw ProjectsWorkspaceError.unsupportedSource
        }
        try await fence.check()
        let routing: Routing
        if project.teamId != nil {
            routing = try await discoverTeamRouting(project: project, source: source, fence: fence)
        } else {
            guard let sourceSessionID = source.sessionID, let keyEpoch = source.keyEpoch,
                  keyEpoch > 0 else { throw ProjectsWorkspaceError.unsupportedSource }
            routing = Routing(sourceSessionID: sourceSessionID, keyEpoch: keyEpoch, team: nil)
        }
        let requestID = UUID().uuidString.lowercased()
        let clientID = UUID().uuidString.lowercased()
        if let approvedIgnoredRead {
            guard operation == "read_text", arguments["path"] as? String == approvedIgnoredRead.path else {
                throw ProjectsWorkspaceError.invalidContext
            }
        }
        let identity = ProjectRemoteBridgeCrypto.Identity(
            ownerID: routing.team?.contextID ?? fence.accountID,
            projectID: project.id, sourceID: source.id, sourceSessionID: routing.sourceSessionID,
            requestingClientID: clientID, keyEpoch: routing.keyEpoch, team: routing.team)
        let requester = try ProjectRemoteBridgeCrypto.makeRequester(projectKey: project.key, identity: identity)
        let handshake = try JSONSerialization.jsonObject(with: JSONEncoder().encode(requester.handshake))
        var envelope: [String: Any] = ["requesting_client_id": clientID,
            "requester_handshake": handshake, "operation": operation, "arguments": arguments]
        if let approvedIgnoredRead {
            envelope["ignored_read_grant"] = try ProjectIgnoredReadGrant.make(
                projectID: project.id, sourceID: source.id, requestID: requestID,
                chatID: approvedIgnoredRead.chatID, operationID: approvedIgnoredRead.operationID,
                path: approvedIgnoredRead.path, projectKey: project.key)
            envelope["ignored_read_context"] = ["chatId": approvedIgnoredRead.chatID,
                                                   "operationId": approvedIgnoredRead.operationID]
        }
        let encrypted = try await encryptEnvelope(envelope, key: project.key)
        var body: [String: Any] = ["request_id": requestID, "requesting_client_id": clientID,
            "operation": operation, "key_epoch": routing.keyEpoch, "encrypted_envelope": encrypted]
        if let writeContext {
            body["chat_id"] = writeContext.chatID
            body["operation_id"] = writeContext.operationID
            body["proposal_digest"] = writeContext.proposalDigest
        }
        if userInitiated { body["user_initiated"] = true }
        try await fence.check()
        let created: Created
        do {
            created = try await APIClient.shared.request(.post,
                path: requestPath(project: project, source: source), serverProfile: fence.serverProfile, body: body,
                expectedAccountID: fence.accountID, expectedScope: fence.scope)
        } catch { throw Self.classifySourceError(error) }
        try await fence.check()
        guard created.sourceSessionId == nil || created.sourceSessionId == routing.sourceSessionID,
              created.keyEpoch == nil || created.keyEpoch == routing.keyEpoch else {
            throw ProjectsWorkspaceError.unsupportedSource
        }
        let polled = try await poll(project: project, source: source, requestID: requestID,
                                    clientID: clientID, fence: fence)
        guard let data = polled.encryptedEnvelope.data(using: .utf8) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let payload = try JSONDecoder().decode(ProjectRemoteBridgeCrypto.ResultPayload.self, from: data)
        let result = try ProjectRemoteBridgeCrypto.openResult(payload, projectKey: project.key,
            identity: identity, requestID: requestID, requester: requester)
        try await fence.check()
        return result
    }

    private func discoverTeamRouting(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                                     fence: ProjectsWorkspaceFence) async throws -> Routing {
        let requestID = UUID().uuidString.lowercased()
        let clientID = UUID().uuidString.lowercased()
        let nonce = UUID().uuidString.lowercased()
        let envelope = try await encryptEnvelope(["type": "routing_discovery",
            "requesting_client_id": clientID, "nonce": nonce], key: project.key)
        let body: [String: Any] = ["request_id": requestID, "requesting_client_id": clientID,
            "operation": "list", "key_epoch": 1, "encrypted_envelope": envelope]
        try await fence.check()
        let created: Created
        do {
            created = try await APIClient.shared.request(.post,
                path: requestPath(project: project, source: source), serverProfile: fence.serverProfile, body: body,
                expectedAccountID: fence.accountID, expectedScope: fence.scope)
        } catch { throw Self.classifySourceError(error) }
        guard let routing = created.routingIdentity, routing.contextType == "team",
              let sourceSessionID = created.sourceSessionId,
              let keyEpoch = created.keyEpoch, keyEpoch > 0 else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let polled = try await poll(project: project, source: source, requestID: requestID,
                                    clientID: clientID, fence: fence)
        let plaintext = try await CryptoManager.shared.decryptContent(
            base64String: polled.encryptedEnvelope, key: project.key)
        guard let data = plaintext.data(using: .utf8),
              let response = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              response["type"] as? String == "routing_discovery_result",
              response["nonce"] as? String == nonce else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        try await fence.check()
        return Routing(sourceSessionID: sourceSessionID, keyEpoch: keyEpoch,
            team: ProjectRemoteBridgeCrypto.TeamRouting(contextID: routing.contextIdHash,
                hostMemberID: routing.hostMemberHash, hostDeviceID: routing.hostDeviceFingerprintHash,
                requesterMemberID: routing.requesterMemberHash,
                requesterDeviceID: routing.requesterDeviceFingerprintHash))
    }

    private func poll(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                      requestID: String, clientID: String,
                      fence: ProjectsWorkspaceFence) async throws -> Polled {
        let path = Self.resultPath(projectID: project.id, sourceID: source.id,
                                   requestID: requestID, clientID: clientID, teamID: project.teamId)
        let deadline = Date().addingTimeInterval(45)
        while Date() < deadline {
            try Task.checkCancellation()
            try await fence.check()
            do {
                let response: Polled = try await APIClient.shared.request(.get, path: path,
                    serverProfile: fence.serverProfile,
                    expectedAccountID: fence.accountID, expectedScope: fence.scope)
                try await fence.check()
                guard !response.encryptedEnvelope.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
                return response
            } catch APIError.httpError(let status, let detail) where status == 404 {
                // Pending encrypted results use 404 as well. Only the explicit
                // backend presence code establishes an unavailable remote host.
                if detail == "source_offline" { throw ProjectsWorkspaceError.sourceOffline }
                guard detail == "request_not_found" else { throw APIError.httpError(status: status, message: detail) }
                try await Task.sleep(for: .milliseconds(250))
            }
        }
        throw ProjectsWorkspaceError.sourceTimedOut
    }

    static func classifySourceError(_ error: Error) -> Error {
        if case APIError.httpError(status: 404, message: "source_offline") = error {
            return ProjectsWorkspaceError.sourceOffline
        }
        return error
    }

    private func encryptEnvelope(_ payload: [String: Any], key: SymmetricKey) async throws -> String {
        let data = try JSONSerialization.data(withJSONObject: payload)
        guard let text = String(data: data, encoding: .utf8), data.count <= 200 * 1024 else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        return try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: key)
    }

    private func requestPath(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource) -> String {
        let base = "/v1/projects/\(Self.escaped(project.id))/sources/\(Self.escaped(source.id))/requests"
        guard let teamID = project.teamId else { return base }
        return base + "?team_id=\(Self.escaped(teamID))"
    }

    /// Route components must precede query values, including Team routing discovery.
    static func resultPath(projectID: String, sourceID: String, requestID: String,
                           clientID: String, teamID: String?) -> String {
        let base = "/v1/projects/\(escaped(projectID))/sources/\(escaped(sourceID))/requests/\(escaped(requestID))"
        var path = base + "?requesting_client_id=\(escaped(clientID))"
        if let teamID { path += "&team_id=\(escaped(teamID))" }
        return path
    }

    private static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }
}
