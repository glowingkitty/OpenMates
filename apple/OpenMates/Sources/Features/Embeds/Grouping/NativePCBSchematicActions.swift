// Owner-authorized PCB compile actions. The backend owns compilation and artifact storage.
// Web: electronics/PcbSchematicEmbedFullscreen.svelte, pcbSchematicCompileService.ts
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.persistence.client-encrypted
import Foundation
import SwiftUI

struct NativePCBArtifact: Decodable, Identifiable, Equatable {
    let id: String
    let name: String
    let type: String?
}
struct NativePCBCompileResponse: Decodable {
    struct Manifest: Decodable { let files: [NativePCBArtifact]? }
    let compile_id: String
    let status: String
    let artifact_manifest: Manifest?
    let error: String?
    let logs: String?
}

/// Injected only by deterministic fixtures/tests. Requests carry IDs and force:false, never source.
struct NativePCBTransport {
    let request: @MainActor (HTTPMethod, String, Data?) async throws -> Data
    let validate: @MainActor () async throws -> Void
}
private struct NativePCBTransportKey: EnvironmentKey {
    static let defaultValue: NativePCBTransport? = nil
}
extension EnvironmentValues {
    var nativePCBTransport: NativePCBTransport? {
        get { self[NativePCBTransportKey.self] }
        set { self[NativePCBTransportKey.self] = newValue }
    }
}

@MainActor
final class NativePCBSchematicActions: ObservableObject {
    @Published private(set) var status = "idle"
    @Published private(set) var compileID: String?
    @Published private(set) var logs = ""
    @Published private(set) var error: String?
    @Published private(set) var artifacts: [NativePCBArtifact] = []
    @Published var showLogs = false
    @Published private(set) var preparing = false
    private var generation = UUID()

    func initialize(_ data: [String: AnyCodable]?) {
        cancel()
        status = data?["compile_status"]?.value as? String ?? "idle"
        compileID = data?["compile_id"]?.value as? String
        logs = data?["compile_logs"]?.value as? String ?? ""
        error = data?["compile_error"]?.value as? String ?? data?["error"]?.value as? String
        artifacts = []
        if let manifest = data?["artifact_manifest"]?.value as? [String: Any],
           let files = manifest["files"], JSONSerialization.isValidJSONObject(files),
           let bytes = try? JSONSerialization.data(withJSONObject: files) {
            artifacts = (try? JSONDecoder().decode([NativePCBArtifact].self, from: bytes)) ?? []
        }
        showLogs = false
    }
    func cancel() { generation = UUID(); preparing = false }

    static func segment(_ id: String) throws -> String {
        // APIClient appends decoded path components. Compile/embed IDs and manifest IDs
        // are opaque backend identifiers; reject separators rather than cross routes.
        guard !id.isEmpty, id != ".", id != "..", id.unicodeScalars.allSatisfy({
            CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~").contains($0)
        }) else { throw URLError(.badURL) }
        return id
    }

    static func accountTransport() async throws -> NativePCBTransport {
        guard let account = await AuthManager.currentUserId() else { throw CancellationError() }
        let scope = OfflineStore.shared.scopeGeneration
        let profile = ServerProfile.current()
        let team = APIRequestTeamContext(epoch: TeamWorkspaceContext.shared.contextEpoch, teamID: TeamWorkspaceContext.shared.teamID)
        let validate: @MainActor () async throws -> Void = {
            try Task.checkCancellation()
            guard await AuthManager.currentUserId() == account,
                  OfflineStore.shared.scopeGeneration == scope,
                  ServerProfile.current() == profile,
                  TeamWorkspaceContext.shared.contextEpoch == team.epoch,
                  TeamWorkspaceContext.shared.teamID == team.teamID else { throw CancellationError() }
        }
        return NativePCBTransport(request: { method, path, bytes in
            try await validate()
            let result: Data
            if let bytes {
                result = try await APIClient.shared.request(method, path: path, serverProfile: profile,
                    body: JSONRawBody(data: bytes), expectedAccountID: account, expectedScope: scope,
                    expectedTeamContext: team)
            } else {
                result = try await APIClient.shared.request(method, path: path, serverProfile: profile,
                    expectedAccountID: account, expectedScope: scope, expectedTeamContext: team)
            }
            try await validate()
            return result
        }, validate: validate)
    }

    func prepare(embedID: String, transport: NativePCBTransport) async {
        guard !preparing else { return }
        let token = generation
        preparing = true; status = "running"; error = nil; showLogs = false
        defer { if generation == token { preparing = false } }
        do {
            try await transport.validate()
            let id = try Self.segment(embedID)
            let bytes = try await transport.request(.post,
                path(id: id), Data(#"{"force":false}"#.utf8))
            try await transport.validate(); try Task.checkCancellation()
            guard token == generation else { return }
            let response = try JSONDecoder().decode(NativePCBCompileResponse.self, from: bytes)
            apply(response)
        } catch is CancellationError { }
        catch {
            guard token == generation else { return }
            status = "failed"; self.error = error.localizedDescription; logs = error.localizedDescription
        }
    }
    private func path(id: String) -> String { "/v1/electronics/pcb-schematic/embeds/\(id)/prepare-files" }

    func refresh(transport: NativePCBTransport) async throws {
        guard let compileID else { return }
        let token = generation
        try await transport.validate()
        let bytes = try await transport.request(.get, "/v1/electronics/pcb-schematic/compile/\(try Self.segment(compileID))", nil)
        try await transport.validate(); try Task.checkCancellation()
        guard token == generation else { throw CancellationError() }
        apply(try JSONDecoder().decode(NativePCBCompileResponse.self, from: bytes))
    }
    func download(_ artifact: NativePCBArtifact, transport: NativePCBTransport) async throws -> NativeEmbedExportFile {
        guard let compileID, artifacts.contains(artifact) else { throw URLError(.badURL) }
        let token = generation
        try await transport.validate()
        let path = "/v1/electronics/pcb-schematic/compile/\(try Self.segment(compileID))/artifacts/\(try Self.segment(artifact.id))"
        let bytes = try await transport.request(.get, path, nil)
        try await transport.validate(); try Task.checkCancellation()
        guard token == generation else { throw CancellationError() }
        return NativeEmbedExportFile(filename: artifact.name, bytes: bytes, mimeType: "application/octet-stream")
    }
    private func apply(_ response: NativePCBCompileResponse) {
        compileID = response.compile_id; status = response.status
        error = response.error; artifacts = response.artifact_manifest?.files ?? []
        if let logs = response.logs, !logs.isEmpty { self.logs = logs }
    }
}
