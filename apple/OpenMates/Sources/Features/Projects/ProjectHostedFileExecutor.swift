import CryptoKit
import Foundation
import Yams

struct ProjectHostedFile {
    let embedID: String
    let path: String
}

struct ProjectHostedHead {
    let embedKey: SymmetricKey
    let content: [String: Any]
    let revision: Int
    let hasInitialHistory: Bool
}

struct ProjectHostedFileError: Error {
    let code: String
}

@MainActor
protocol ProjectHostedFileAdapter {
    var projectID: String { get }
    var projectKey: SymmetricKey { get }
    var chatKey: SymmetricKey { get }
    var teamID: String? { get }
    func listFiles() async throws -> [ProjectHostedFile]
    func readHead(embedID: String) async throws -> ProjectHostedHead
    func privatePaths() async throws -> [String]
    func receipt(embedID: String, job: ProjectFileJob, digest: String) async throws -> [String: Any]?
    func commit(_ payload: [String: Any]) async throws -> [String: Any]
}

/// Native equivalent of hostedProjectFileExecutor.ts. The adapter owns fresh
/// first-party reads and the fenced WebSocket commit. No decrypted file bytes
/// are stored by this executor.
@MainActor
final class ProjectHostedFileExecutor {
    private let adapter: any ProjectHostedFileAdapter
    private let validateFence: @MainActor (ProjectsWorkspaceFence) async throws -> Void

    init(adapter: any ProjectHostedFileAdapter,
         validateFence: @escaping @MainActor (ProjectsWorkspaceFence) async throws -> Void = {
             try await $0.check()
         }) {
        self.adapter = adapter
        self.validateFence = validateFence
    }

    func execute(job: ProjectFileJob, mutation: ProjectFileMutation?,
                 approvedIgnoredRead: String?, fence: ProjectsWorkspaceFence,
                 validateAuthority: @MainActor () throws -> Void) async throws -> [String: Any] {
        try await validateFence(fence)
        try validateAuthority()
        let listed = try await adapter.listFiles()
        let loaded = try await loadPolicy(listed: listed, fence: fence)
        try await validateFence(fence)
        try validateAuthority()
        let files = loaded.files
        let policy = loaded.policy
        if job.operation == "list" {
            let raw = job.arguments["path"] as? String ?? "."
            let prefix = raw == "." || raw.isEmpty ? "" : try path(raw) + "/"
            let found = files.filter { file in
                file.path.hasPrefix(prefix) && !policy.isPrivate(file.path) && !policy.isIgnored(file.path)
            }
            return ["entries": found.prefix(500).map { ["path": $0.path, "kind": "file"] },
                    "truncated": found.count > 500]
        }
        if job.operation == "search" {
            return try await search(job: job, files: files, policy: policy,
                excluded: loaded.excluded, fence: fence, validateAuthority: validateAuthority)
        }
        guard let rawPath = job.arguments["path"] as? String else { throw failure("invalid_path") }
        let normalized = try path(rawPath)
        if policy.isPrivate(normalized) || normalized == ".openmates/permissions.yml" {
            throw failure("protected_path")
        }
        if job.operation != "read_text" && (normalized == ".gitignore" ||
            normalized.hasSuffix("/.gitignore")) { throw failure("protected_path") }
        if policy.isIgnored(normalized) &&
            !(job.operation == "read_text" && approvedIgnoredRead == normalized) {
            throw failure("ignored_path_requires_approval")
        }
        let matching = files.filter { $0.path == normalized }
        guard matching.count <= 1 else { throw failure("ambiguous_file_path") }
        if job.operation == "read_text" {
            guard let file = matching.first else { throw failure("file_not_found") }
            let head = try await adapter.readHead(embedID: file.embedID)
            let content = try textContent(head)
            try await validateFence(fence)
            try validateAuthority()
            return ["path": normalized, "content": content,
                "expected_base": Self.sha256(content), "revision": head.revision,
                "size_bytes": content.utf8.count, "truncated": false]
        }
        guard let mutation, mutation.path == normalized,
              mutation.operation == job.operation else { throw failure("invalid_file_mutation") }
        return try await write(job: job, mutation: mutation, path: normalized,
            found: matching.first, fence: fence, validateAuthority: validateAuthority)
    }

    private func write(job: ProjectFileJob, mutation: ProjectFileMutation, path: String,
                       found: ProjectHostedFile?, fence: ProjectsWorkspaceFence,
                       validateAuthority: @MainActor () throws -> Void) async throws -> [String: Any] {
        let creating = mutation.operation == "create_file"
        let embedID = try found?.embedID ?? Self.identity(key: adapter.projectKey, path: path, kind: "embed")
        let digest = try mutation.commitment(projectID: adapter.projectID, chatID: job.chatID,
            key: adapter.projectKey)
        if let receipt = try await adapter.receipt(embedID: embedID, job: job, digest: digest),
           receipt["status"] as? String == "committed" {
            try await validateFence(fence)
            try validateAuthority()
            return ["path": path, "operation_id": job.operationID,
                "revision": receipt["current_revision"] as? Int ?? 0, "idempotent": true]
        }
        if creating && found != nil { throw failure("file_exists") }
        if !creating && found == nil { throw failure("file_not_found") }
        let current = creating ? nil : try await adapter.readHead(embedID: embedID)
        let original = try current.map(textContent) ?? ""
        if let current, Self.sha256(original) != mutation.expectedBase { throw failure("stale_base") }
        let content: String
        if creating {
            content = mutation.content ?? ""
        } else {
            guard let patch = mutation.patch else { throw failure("invalid_patch") }
            do { content = try ProjectHostedPatch.apply(patch, to: original, path: path) }
            catch { throw failure("invalid_patch") }
        }
        guard content.utf8.count <= 200 * 1024, !content.contains("\0") else {
            throw failure("file_too_large")
        }
        let now = Int(Date().timeIntervalSince1970)
        let key = current?.embedKey ?? SymmetricKey(size: .bits256)
        let revision = (current?.revision ?? 0) + 1
        let field = current?.content["code"] == nil && current?.content["content"] is String
            ? "content" : "code"
        var contentObject = current?.content ?? ["type": "code", "language": "text", "filename": path]
        contentObject[field] = content
        contentObject["version_number"] = revision
        contentObject["status"] = "finished"
        contentObject["line_count"] = content.components(separatedBy: "\n").count
        let encoded = try JSONSerialization.data(withJSONObject: contentObject)
        guard let encodedText = String(data: encoded, encoding: .utf8) else { throw failure("unsupported_file_content") }
        var history: [[String: Any]] = []
        if creating || (current?.revision == 1 && current?.hasInitialHistory == false) {
            history.append(["version_number": 1,
                "encrypted_snapshot": try await encrypt(creating ? content : original, key: key),
                "created_at": now])
        }
        if !creating, let patch = mutation.patch {
            history.append(["version_number": revision,
                "encrypted_patch": try await encrypt(patch, key: key),
                "created_at": now])
        }
        var payload: [String: Any] = ["operation_id": job.operationID,
            "embed_id": embedID, "project_id": adapter.projectID, "chat_id": job.chatID,
            "proposal_digest": digest, "expected_revision": current?.revision ?? 0,
            "head": ["encrypted_content": try await encrypt(encodedText, key: key),
                "encrypted_text_preview": try await encrypt("\(path) (\(content.components(separatedBy: "\n").count) lines)", key: key),
                "status": "finished", "updated_at": now],
            "history_rows": history]
        if let teamID = adapter.teamID { payload["team_id"] = teamID }
        if creating {
            let itemID = try Self.identity(key: adapter.projectKey, path: path, kind: "item")
            let metadata = try JSONSerialization.data(withJSONObject: ["path": path, "source": "hosted_project_file"])
            guard let metadataText = String(data: metadata, encoding: .utf8) else {
                throw failure("invalid_request")
            }
            payload["create"] = ["project_item_id": itemID,
                "encrypted_type": try await encrypt("code-code", key: key),
                "target_id_encrypted": try await encrypt(embedID, key: adapter.projectKey),
                "encrypted_display_name": try await encrypt(path, key: adapter.projectKey),
                "encrypted_metadata": try await encrypt(metadataText, key: adapter.projectKey),
                "key_wrappers": [
                    ["key_type": "project", "encrypted_embed_key": try await CryptoManager.shared.wrapChatKey(key, masterKey: adapter.projectKey), "created_at": now],
                    ["key_type": "chat", "encrypted_embed_key": try await CryptoManager.shared.wrapChatKey(key, masterKey: adapter.chatKey), "created_at": now]
                ]]
        }
        try await validateFence(fence)
        try validateAuthority()
        let result = try await adapter.commit(payload)
        try await validateFence(fence)
        try validateAuthority()
        if result["status"] as? String == "conflict" { throw failure("revision_conflict") }
        guard result["status"] as? String == "committed" else {
            throw failure(result["code"] as? String ?? "commit_rejected")
        }
        return ["path": path, "operation_id": job.operationID, "embed_id": embedID,
            "revision": result["current_revision"] as? Int ?? revision,
            "expected_base": Self.sha256(content),
            "applied_diff": mutation.patch.map { $0 as Any } ?? NSNull(),
            "created": creating]
    }

    private func search(job: ProjectFileJob, files: [ProjectHostedFile],
                        policy: ProjectHostedPathPolicy, excluded: Int,
                        fence: ProjectsWorkspaceFence,
                        validateAuthority: @MainActor () throws -> Void) async throws -> [String: Any] {
        let search = try SearchRequest(job.arguments)
        guard search.mode == "literal" else { throw failure("regex_search_unavailable") }
        let prefix = search.path == "." ? "" : search.path
        var blocked = excluded
        let candidates = files.filter { file in
            if policy.isPrivate(file.path) || policy.isIgnored(file.path) {
                blocked += 1
                return false
            }
            return (prefix.isEmpty || file.path == prefix || file.path.hasPrefix(prefix + "/")) &&
                ProjectHostedPathPolicy.matchesSearchGlob(file.path, glob: search.glob)
        }
        var matches: [[String: Any]] = []
        var omitted = 0
        let examined = min(candidates.count, 100)
        var incomplete = false
        for file in candidates.prefix(100) {
            try await validateFence(fence)
            try validateAuthority()
            if search.target == "files" {
                if file.path.contains(search.query) {
                    if matches.count < search.maxResults { matches.append(["path": file.path]) } else { omitted += 1 }
                }
                continue
            }
            guard let head = try? await adapter.readHead(embedID: file.embedID),
                  let content = try? textContent(head) else { blocked += 1; continue }
            let lines = content.components(separatedBy: "\n")
            if lines.count > 4_000 { incomplete = true }
            for (offset, line) in lines.prefix(4_000).enumerated() where line.contains(search.query) {
                if matches.count < search.maxResults {
                    matches.append(["path": file.path, "line": offset + 1,
                        "snippet": String(line.prefix(500))])
                } else { omitted += 1 }
            }
        }
        return ["matches": matches, "excluded": blocked, "omitted": omitted,
            "truncated": omitted > 0 || incomplete || candidates.count > examined]
    }

    /// Mirrors normalizeProjectSearchRequest. Search paths intentionally accept
    /// dot and redundant separators; direct file paths remain strict.
    private struct SearchRequest {
        let target: String
        let mode: String
        let query: String
        let path: String
        let glob: String?
        let maxResults: Int

        init(_ value: [String: Any]) throws {
            let target = value["target"] as? String ?? "content"
            guard (value["target"] == nil || value["target"] is String),
                  target == "files" || target == "content" else {
                throw ProjectHostedFileError(code: "invalid_search_target")
            }
            let mode = value["mode"] as? String ?? "literal"
            guard (value["mode"] == nil || value["mode"] is String),
                  mode == "literal" || mode == "regex" else {
                throw ProjectHostedFileError(code: "invalid_search_mode")
            }
            guard let query = value["query"] as? String,
                  !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  query.count <= 2_000, !Self.hasControl(query) else {
                throw ProjectHostedFileError(code: "invalid_search_query")
            }
            let rawPath = value["path"] as? String ?? "."
            guard (value["path"] == nil || value["path"] is String),
                  !rawPath.isEmpty, rawPath.count <= 2_048,
                  !rawPath.hasPrefix("/"), !rawPath.contains("\\"), !Self.hasControl(rawPath),
                  !rawPath.split(separator: "/", omittingEmptySubsequences: false).contains("..") else {
                throw ProjectHostedFileError(code: "invalid_search_path")
            }
            let path = rawPath.split(separator: "/").filter { $0 != "." }.joined(separator: "/")
            let glob: String?
            if let rawGlob = value["glob"] {
                guard let candidate = rawGlob as? String,
                      !candidate.isEmpty, candidate.count <= 512,
                      !candidate.hasPrefix("!"), !candidate.hasPrefix("/"),
                      !candidate.contains("\\"), !candidate.contains("["), !candidate.contains("]"),
                      !candidate.contains("{"), !candidate.contains("}"),
                      !Self.hasControl(candidate),
                      !candidate.split(separator: "/", omittingEmptySubsequences: false).contains("..") else {
                    throw ProjectHostedFileError(code: "invalid_search_glob")
                }
                glob = candidate
            } else { glob = nil }
            let maxResults = value["max_results"] as? Int ?? 20
            guard (value["max_results"] == nil || value["max_results"] is Int),
                  (1...100).contains(maxResults) else {
                throw ProjectHostedFileError(code: "invalid_search_limit")
            }
            self.target = target
            self.mode = mode
            self.query = query
            self.path = path.isEmpty ? "." : path
            self.glob = glob
            self.maxResults = maxResults
        }

        private static func hasControl(_ value: String) -> Bool {
            value.unicodeScalars.contains { $0.value < 32 || $0.value == 127 }
        }
    }

    private func loadPolicy(listed: [ProjectHostedFile], fence: ProjectsWorkspaceFence) async throws
        -> (files: [ProjectHostedFile], policy: ProjectHostedPathPolicy, excluded: Int) {
        var files: [ProjectHostedFile] = []
        var taintedIDs: Set<String> = []
        var excluded = 0
        for file in listed {
            if Self.validPath(file.path) { files.append(file) }
            else { taintedIDs.insert(file.embedID); excluded += 1 }
        }
        let authoritativePrivatePaths = try await adapter.privatePaths()
        let permissions = files.filter { $0.path == ".openmates/permissions.yml" }
        let ignoreFiles = files.filter { $0.path == ".gitignore" || $0.path.hasSuffix("/.gitignore") }
        let allControls = permissions + ignoreFiles
        guard permissions.count <= 1, ignoreFiles.count <= 64,
              Set(allControls.map(\.path)).count == allControls.count else {
            throw failure("protected_path")
        }
        var controlBytes = 0
        var filePrivatePaths: [String] = []
        if let control = permissions.first {
            guard !taintedIDs.contains(control.embedID) else { throw failure("protected_path") }
            let source: String
            do { source = try textContent(await adapter.readHead(embedID: control.embedID)) }
            catch { throw failure("protected_path") }
            controlBytes += source.utf8.count
            guard source.utf8.count <= 64 * 1024, controlBytes <= 256 * 1024 else {
                throw failure("protected_path")
            }
            filePrivatePaths = try Self.permissionsPrivatePaths(source)
        }
        let privateOnly = try policy(ignoreFiles: [],
            privatePaths: authoritativePrivatePaths + filePrivatePaths)
        for file in files where privateOnly.isPrivate(file.path) {
            taintedIDs.insert(file.embedID)
        }
        var controls: [ProjectHostedPathPolicy.IgnoreFile] = []
        for control in ignoreFiles.sorted(by: {
            let leftDepth = $0.path.split(separator: "/").count
            let rightDepth = $1.path.split(separator: "/").count
            return leftDepth == rightDepth ? $0.path < $1.path : leftDepth < rightDepth
        }) {
            if taintedIDs.contains(control.embedID) {
                if control.path == ".gitignore" { throw failure("protected_path") }
                continue
            }
            // Git does not load nested controls inside a directory already
            // excluded by a parent control. Do not decrypt that file either.
            let currentPolicy = try policy(ignoreFiles: controls,
                privatePaths: authoritativePrivatePaths + filePrivatePaths)
            if currentPolicy.isIgnored(control.path) { continue }
            let source: String
            do { source = try textContent(await adapter.readHead(embedID: control.embedID)) }
            catch { throw failure("protected_path") }
            controlBytes += source.utf8.count
            guard source.utf8.count <= 64 * 1024, controlBytes <= 256 * 1024 else {
                throw failure("protected_path")
            }
            controls.append(.init(path: control.path, content: source))
        }
        let policy = try policy(ignoreFiles: controls,
            privatePaths: authoritativePrivatePaths + filePrivatePaths)
        try await validateFence(fence)
        let visible = files.filter { file in
            if taintedIDs.contains(file.embedID) { excluded += 1; return false }
            return true
        }
        return (visible, policy, excluded)
    }

    private static func permissionsPrivatePaths(_ source: String) throws -> [String] {
        // YAML aliases and merge keys can hide a second policy map. Web parses
        // this document with aliases disabled and unique keys required. Allow
        // glob `*` inside private path values, but reject YAML alias tokens.
        let alias = try NSRegularExpression(pattern: #"(?:^|\s)[&*][A-Za-z0-9_-]+"#,
            options: [.anchorsMatchLines])
        let range = NSRange(source.startIndex..<source.endIndex, in: source)
        let accessKeys = source.components(separatedBy: .newlines).filter { line in
            let key = line.trimmingCharacters(in: .whitespaces).lowercased()
            return key.hasPrefix("file_access:") || key.hasPrefix("'file_access':") ||
                key.hasPrefix("\"file_access\":")
        }
        let privateKeys = source.components(separatedBy: .newlines).filter { line in
            let key = line.trimmingCharacters(in: .whitespaces).lowercased()
            return key.hasPrefix("private_paths:") || key.hasPrefix("'private_paths':") ||
                key.hasPrefix("\"private_paths\":")
        }
        guard alias.firstMatch(in: source, range: range) == nil,
              !source.contains("<<:"), accessKeys.count <= 1, privateKeys.count <= 1 else {
            throw failure("protected_path")
        }
        let document: Any?
        do { document = try Yams.load(yaml: source) }
        catch { throw failure("protected_path") }
        guard let document else { return [] }
        guard let root = document as? [String: Any] else { throw failure("protected_path") }
        guard let access = root["file_access"] else { return [] }
        guard let access = access as? [String: Any] else { throw failure("protected_path") }
        guard let raw = access["private_paths"] else { return [] }
        guard let paths = raw as? [String], paths.count <= 256,
              paths.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 4096 }) else {
            throw failure("protected_path")
        }
        return paths
    }

    private func policy(ignoreFiles: [ProjectHostedPathPolicy.IgnoreFile],
                        privatePaths: [String]) throws -> ProjectHostedPathPolicy {
        do { return try ProjectHostedPathPolicy(ignoreFiles: ignoreFiles, privatePaths: privatePaths) }
        catch { throw failure("protected_path") }
    }

    private func textContent(_ head: ProjectHostedHead) throws -> String {
        guard let text = (head.content["code"] ?? head.content["content"]) as? String,
              text.utf8.count <= 200 * 1024, !text.contains("\0") else {
            throw failure("unsupported_file_content")
        }
        return text
    }

    private static func validPath(_ path: String) -> Bool {
        ProjectHostedPathPolicy.normalized(path) != nil
    }

    private func path(_ raw: String) throws -> String {
        guard let path = ProjectHostedPathPolicy.normalized(raw) else { throw failure("invalid_path") }
        return path
    }

    private func encrypt(_ value: String, key: SymmetricKey) async throws -> String {
        try await CryptoManager.shared.encryptWithMasterKey(value, masterKey: key)
    }

    static func identity(key: SymmetricKey, path: String, kind: String) throws -> String {
        let values = ["openmates-hosted-file-v1", kind, path]
        let input = try JSONSerialization.data(withJSONObject: values, options: [.withoutEscapingSlashes])
        var bytes = Array(HMAC<SHA256>.authenticationCode(for: input, using: key).prefix(16))
        bytes[6] = (bytes[6] & 15) | 0x50
        bytes[8] = (bytes[8] & 63) | 0x80
        let hex = bytes.map { String(format: "%02x", $0) }.joined()
        let boundaries = [8, 12, 16, 20]
        var output = ""
        for (index, character) in hex.enumerated() {
            if boundaries.contains(index) { output.append("-") }
            output.append(character)
        }
        return output
    }

    static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func failure(_ code: String) -> ProjectHostedFileError { .init(code: code) }
    private func failure(_ code: String) -> ProjectHostedFileError { Self.failure(code) }
}
