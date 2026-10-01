import CryptoKit
import Foundation
import UniformTypeIdentifiers

/// Mirrors projectService.uploadFileToProject. Server rows contain only
/// encrypted Project/Embed fields and opaque routing hashes.
@MainActor
final class ProjectUploadService {
    func upload(url: URL, project: ProjectWorkspaceProject, folderID: String?,
                fence: ProjectsWorkspaceFence) async throws {
        try await fence.check()
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        let data = try Data(contentsOf: url)
        let filename = url.lastPathComponent
        guard !filename.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
        let inline = filename.lowercased() == "readme.md"
        let contentType = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
            ?? "application/octet-stream"
        if inline {
            guard let text = String(data: data, encoding: .utf8), !text.contains("\0") else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            try await uploadInlineCode(text: text, filename: filename,
                project: project, folderID: folderID, metadata: ["readme_uploaded_at_ms":
                    Int(Date().timeIntervalSince1970 * 1_000)], fence: fence)
            return
        }
        // Upload transport is shared with chat attachments, but Project uploads
        // carry no fabricated chat id. The Project-scoped encrypted link is
        // published only after the upload succeeds.
        let responseData = try await APIClient.shared.uploadProjectFile(data: data,
            filename: filename, contentType: contentType, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let upload = try decoder.decode(UploadFileResponse.self, from: responseData)
        try await fence.check()
        let embedType = Self.embedType(filename: filename, contentType: upload.contentType)
        var files: [String: Any] = [:]
        for (kind, variant) in upload.files {
            var item: [String: Any] = ["s3_key": variant.s3Key]
            if let bytes = variant.sizeBytes { item["size_bytes"] = bytes }
            if let width = variant.width { item["width"] = width }
            if let height = variant.height { item["height"] = height }
            if let format = variant.format { item["format"] = format }
            if let encryption = variant.encryption { item["encryption"] = encryption }
            files[kind] = item
        }
        let content: [String: Any] = ["app_id": embedType.split(separator: "-").first.map(String.init) ?? "files",
            "skill_id": "upload", "type": embedType, "status": "finished",
            "filename": upload.filename, "file_size": data.count,
            "file_type": upload.contentType, "content_hash": upload.contentHash.map { $0 as Any } ?? NSNull(),
            "s3_base_url": upload.s3BaseUrl, "files": files,
            "aes_key": upload.aesKey, "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey,
            "page_count": upload.pageCount.map { $0 as Any } ?? NSNull()]
        try await commit(embedID: upload.embedId, filename: upload.filename,
            type: embedType, content: content, contentHash: upload.contentHash,
            metadata: ["embed_type": embedType], project: project,
            folderID: folderID, fence: fence)
    }

    func uploadInlineCode(text: String, filename: String,
                          project: ProjectWorkspaceProject, folderID: String?,
                          metadata: [String: Any] = [:],
                          fence: ProjectsWorkspaceFence) async throws {
        guard text.utf8.count <= 200 * 1024, !filename.isEmpty else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let id = UUID().uuidString.lowercased()
        let hash = Self.sha256(text)
        let language = filename.lowercased().hasSuffix(".md") ? "markdown" : "text"
        let content: [String: Any] = ["type": "code", "app_id": "code", "skill_id": "code",
            "language": language, "code": text, "filename": filename,
            "status": "finished", "line_count": text.components(separatedBy: "\n").count,
            "content_hash": hash]
        var storedMetadata = metadata
        storedMetadata["embed_type"] = "code-code"
        try await commit(embedID: id, filename: filename, type: "code-code",
            content: content, contentHash: hash, metadata: storedMetadata,
            project: project, folderID: folderID, fence: fence)
    }

    private func commit(embedID: String, filename: String, type: String,
                        content: [String: Any], contentHash: String?,
                        metadata: [String: Any], project: ProjectWorkspaceProject,
                        folderID: String?, fence: ProjectsWorkspaceFence) async throws {
        try await fence.check()
        guard project.permissions.manageOwnItems || project.permissions.manageAnyItems,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: fence.accountID),
              let contentText = String(data: try JSONSerialization.data(withJSONObject: content), encoding: .utf8),
              let metadataText = String(data: try JSONSerialization.data(withJSONObject: metadata), encoding: .utf8) else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let embedKey = SymmetricKey(size: .bits256)
        let now = Int(Date().timeIntervalSince1970)
        func encrypt(_ text: String, key: SymmetricKey) async throws -> String {
            try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: key)
        }
        let embed: [String: Any] = ["embed_id": embedID,
            "encrypted_type": try await encrypt(type, key: embedKey),
            "status": "finished", "encrypted_content": try await encrypt(contentText, key: embedKey),
            "encrypted_text_preview": try await encrypt(filename, key: embedKey),
            "content_hash": contentHash.map { $0 as Any } ?? NSNull(),
            "created_at": now, "updated_at": now, "encryption_mode": "client",
            "is_private": true, "is_shared": false]
        let hashedEmbedID = Self.sha256(embedID)
        let keys: [[String: Any]] = [
            ["hashed_embed_id": hashedEmbedID, "key_type": "master",
             "encrypted_embed_key": try await CryptoManager.shared.wrapChatKey(embedKey, masterKey: masterKey),
             "created_at": now],
            ["hashed_embed_id": hashedEmbedID, "key_type": "project",
             "hashed_project_id": Self.sha256(project.id),
             "encrypted_embed_key": try await CryptoManager.shared.wrapChatKey(embedKey, masterKey: project.key),
             "created_at": now]
        ]
        let item: [String: Any] = ["project_item_id": UUID().uuidString.lowercased(),
            "folder_id": folderID.map { $0 as Any } ?? NSNull(),
            "item_type": "embed", "target_id": embedID,
            "target_id_encrypted": try await encrypt(embedID, key: project.key),
            "encrypted_display_name": try await encrypt(filename, key: project.key),
            "encrypted_note": try await encrypt("", key: project.key),
            "encrypted_metadata": try await encrypt(metadataText, key: project.key),
            "created_at": now, "updated_at": now, "position": now]
        let escaped = project.id.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
        guard !escaped.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
        let path = "/v1/projects/\(escaped)/upload-embed" +
            (project.teamId.map { team in
                "?team_id=\(team.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? "")"
            } ?? "")
        try await fence.check()
        let _: Data = try await APIClient.shared.request(.post, path: path,
            serverProfile: fence.serverProfile,
            body: ["embed": embed, "embed_keys": keys, "item": item],
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
    }

    private static func sha256(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func embedType(filename: String, contentType: String) -> String {
        let lower = filename.lowercased()
        if contentType == "application/pdf" || lower.hasSuffix(".pdf") { return "pdf" }
        if contentType.hasPrefix("image/") { return "images-image" }
        if contentType.hasPrefix("video/") { return "video" }
        if contentType.hasPrefix("audio/") { return "audio" }
        if [".csv", ".tsv", ".xlsx"].contains(where: lower.hasSuffix) { return "sheet" }
        if [".eml", ".msg"].contains(where: lower.hasSuffix) { return "mail" }
        if [".ts", ".tsx", ".js", ".jsx", ".py", ".swift", ".go", ".rs", ".java",
            ".c", ".cpp", ".h", ".css", ".html", ".svelte", ".json", ".yml",
            ".yaml", ".md"].contains(where: lower.hasSuffix) { return "code-code" }
        return "file"
    }
}
