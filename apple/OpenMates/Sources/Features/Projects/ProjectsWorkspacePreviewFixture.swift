#if DEBUG
import CryptoKit
import Foundation

/// Public deployed reference: ProjectsPage.preview.ts. This data drives the
/// production Projects workspace and sidebar views in the account-free host.
@MainActor
enum ProjectsWorkspacePreviewFixture {
    struct State {
        let project: ProjectWorkspaceProject
        let folders: [ProjectWorkspaceFolder]
        let items: [ProjectWorkspaceItem]
        let sources: [ProjectWorkspaceSource]
        let readme: ProjectsWorkspaceStore.ReadmeState
        let rootPreviews: [String: [ProjectRemoteEntry]]
        let remoteEntries: [ProjectRemoteEntry]
    }

    static func state(for variant: String) -> State {
        let now = Int(Date().timeIntervalSince1970)
        let permissions = ProjectWorkspacePermissions(create: true, update: true,
            archive: false, delete: true, settings: true, manageAnyItems: true,
            manageAnySources: true, manageOwnItems: true, manageOwnSources: true)
        let project = ProjectWorkspaceProject(id: "preview-project", name: "OpenMates",
            description: "Digital team mates for everyday tasks, projects & learning. Privacy & user interests first.",
            icon: "folder", key: SymmetricKey(data: Data(repeating: 0, count: 32)),
            version: 1, createdAt: now, updatedAt: now, isShared: false,
            itemCount: 4, teamId: nil, permissions: permissions)
        let folders = [
            ProjectWorkspaceFolder(id: "backend", name: "Backend", parentHash: nil,
                position: 0, createdAt: now),
            ProjectWorkspaceFolder(id: "research", name: "Research", parentHash: nil,
                position: 1, createdAt: now - 20),
            ProjectWorkspaceFolder(id: "api", name: "api", parentHash: hash("backend"),
                position: 0, createdAt: now - 2),
            ProjectWorkspaceFolder(id: "design-references", name: "Design references",
                parentHash: hash("research"), position: 0, createdAt: now - 24),
        ]
        var items = [
            item("project-source", "preview-code", "ProjectsPage.svelte", "code-code", now - 10),
            item("project-brief", "preview-document", "Project brief", "docs-doc", now - 30),
            item("project-file", "preview-file", "architecture.pdf", "pdf", now - 40),
            ProjectWorkspaceItem(id: "backend-websockets", kind: "embed",
                targetID: "backend-websockets-target", name: "websockets.py",
                metadata: ["embed_type": "code-code", "size_bytes": "18432"],
                folderHash: hash("backend"), position: 1, createdAt: now - 2),
            ProjectWorkspaceItem(id: "backend-main-processor", kind: "embed",
                targetID: "backend-main-processor-target", name: "main_processor.py",
                metadata: ["embed_type": "code-code", "size_bytes": "31744"],
                folderHash: hash("backend"), position: 2, createdAt: now - 2),
            ProjectWorkspaceItem(id: "research-product-requirements", kind: "embed",
                targetID: "research-requirements-target", name: "Product requirements",
                metadata: ["embed_type": "docs-doc", "file_type": "DOCX"],
                folderHash: hash("research"), position: 0, createdAt: now - 22),
        ]
        items.append(contentsOf: (0..<12).map { index in
            ProjectWorkspaceItem(id: "backend-api-\(index)", kind: "embed",
                targetID: "backend-api-target-\(index)", name: "endpoint-\(index).py",
                metadata: ["embed_type": "code-code"], folderHash: hash("api"),
                position: index, createdAt: now - 3)
        })
        items.append(contentsOf: (0..<6).map { index in
            ProjectWorkspaceItem(id: "research-reference-\(index)", kind: "embed",
                targetID: "research-reference-target-\(index)", name: "reference-\(index).pdf",
                metadata: ["embed_type": "pdf"], folderHash: hash("design-references"),
                position: index, createdAt: now - 25)
        })
        if variant == "largeConnectedSource" {
            items.append(contentsOf: (0..<105).map { index in
                let name = index == 0 ? "needle-stored-root.md"
                    : "stored-file-\(String(format: "%03d", index)).md"
                return item("large-stored-\(index)", "large-stored-target-\(index)", name,
                    "code-code", now - 100 - index)
            })
            items.append(ProjectWorkspaceItem(id: "large-stored-nested", kind: "embed",
                targetID: "large-stored-nested-target", name: "needle-stored-nested.md",
                metadata: ["embed_type": "code-code", "source": "hosted_project_file",
                    "path": "guides/needle-stored-nested.md"], folderHash: nil,
                position: 109, createdAt: now - 210))
        }
        let sourceKind = variant == "localFolderSource" ? "local_folder" : "local_git_repository"
        let hasSource = ["connectedSource", "localFolderSource", "multipleSources",
            "largeConnectedSource", "legacyConnectedSource"].contains(variant)
        let source = ProjectWorkspaceSource(id: "source-preview", kind: sourceKind,
            name: "OpenMates repository", metadata: ["root": "/workspace/OpenMates"],
            capabilities: ["read"], status: "connected", sessionID: nil, keyEpoch: nil)
        var sources = hasSource ? [source] : []
        if variant == "multipleSources" {
            sources.append(ProjectWorkspaceSource(id: "source-second", kind: sourceKind,
                name: "Second repository", metadata: source.metadata, capabilities: ["read"],
                status: "connected", sessionID: nil, keyEpoch: nil))
        }
        let remoteEntries: [ProjectRemoteEntry]
        if variant == "largeConnectedSource" {
            remoteEntries = (0..<125).map { index in
                entry(index == 0 ? "needle-current.ts" : "remote-file-\(String(format: "%03d", index)).ts",
                    kind: "file", size: 1024 + index)
            } + [entry("nested", kind: "directory"), entry("nested/needle-child.ts",
                kind: "file", size: 2048)]
        } else if variant == "legacyConnectedSource" {
            remoteEntries = (0..<500).map { index in
                entry("legacy-file-\(String(format: "%03d", index)).ts", kind: "file",
                    size: 1024 + index)
            }
        } else if variant == "multipleSources" {
            remoteEntries = [entry("docs", kind: "directory"),
                entry("README.md", kind: "file", size: 1024)]
        } else {
            remoteEntries = [entry("frontend", kind: "directory", files: 1, folders: 1),
                entry("README.md", kind: "file", size: 1024)]
        }
        let readme: ProjectsWorkspaceStore.ReadmeState = variant == "readme"
            ? .ready(ProjectWorkspaceReadme(markdown: "# OpenMates\n\nA private workspace for planning, research, and shipping useful work.\n\n## What we are building\n\n- Calm collaboration\n- Useful project context\n- Clear next steps",
                truncated: false, origin: "stored")) : .empty
        let previews = sources.reduce(into: [String: [ProjectRemoteEntry]]()) { result, source in
            result[source.id] = Array(remoteEntries.prefix(3))
        }
        return State(project: project, folders: folders, items: items,
            sources: sources, readme: readme, rootPreviews: previews,
            remoteEntries: remoteEntries)
    }

    private static func item(_ id: String, _ target: String, _ name: String,
                             _ embedType: String, _ created: Int) -> ProjectWorkspaceItem {
        ProjectWorkspaceItem(id: id, kind: "embed", targetID: target, name: name,
            metadata: ["embed_type": embedType], folderHash: nil,
            position: 0, createdAt: created)
    }

    private static func entry(_ path: String, kind: String, size: Int? = nil,
                              files: Int? = nil, folders: Int? = nil) -> ProjectRemoteEntry {
        ProjectRemoteEntry(path: path, kind: kind, sizeBytes: size,
            childFileCount: files, childFolderCount: folders,
            childSummaryTruncated: false)
    }

    private static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
#endif
