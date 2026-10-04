// Web sources: services/appsWorkspaceService.ts, services/appsWorkspaceResultsService.ts,
// services/appsWorkflowLibraryService.ts
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.execution.direct-shared-contract, apps.results.web-retained-graph,
// apps.library.embeds-account-paginated, apps.library.workflows-account-related
import CryptoKit
import Foundation

enum AppsWorkspacePaths {
    static let results = "/v1/apps/workspace/results"
    static func component(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }
    static func skill(_ app: String, _ skill: String) -> String { "/v1/apps/\(component(app))/skills/\(component(skill))" }
    static func scoped(_ path: String, teamID: String?) -> String {
        guard let teamID else { return path }
        return path + (path.contains("?") ? "&" : "?") + "team_id=" + component(teamID)
    }
    static func page(appID: String, offset: Int, teamID: String?) -> String {
        scoped(results + "?app_id=\(component(appID))&offset=\(max(0, offset))&limit=20", teamID: teamID)
    }
}

@MainActor
final class AppsWorkspaceService {
    private let api: APIClient
    init(api: APIClient = .shared) { self.api = api }

    func catalog(scope: WorkflowRequestScope?) async throws -> [SettingsAppsFullView.AppInfo] {
        let data: Data
        if let scope {
            let offline = try await NativeWorkspaceOfflineRuntime.configure(accountID: scope.accountId, teamID: scope.teamContext?.teamID)
            data = try await NativeWorkspaceOfflineRuntime.request(namespace: "apps", path: "/v1/apps/metadata", scope: offline, api: api)
        } else { data = try await request(.get, path: "/v1/apps/metadata", scope: nil) }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(SettingsAppsFullView.AppsMetadataResponse.self, from: data)
        return response.apps.values.map(SettingsAppsFullView.appInfo).filter { $0.id != "ai" }.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    func details(appID: String, skillID: String, scope: WorkflowRequestScope?) async throws -> AppsSkillDetails {
        let data = try await request(.get, path: AppsWorkspacePaths.skill(appID, skillID) + "/details", scope: scope)
        return try JSONDecoder().decode(AppsSkillDetails.self, from: data)
    }

    func request(_ method: HTTPMethod, path: String, body: Data? = nil, headers: [String: String]? = nil, scope: WorkflowRequestScope?) async throws -> Data {
        if let scope { try await scope.check() }
        let result: Data
        if let body {
            let rawBody = JSONRawBody(data: body)
            result = try await api.request(method, path: path, serverProfile: scope?.serverProfile ?? ServerProfile.current(),
                body: rawBody, headers: headers, expectedAccountID: scope?.accountId,
                expectedScope: scope?.offlineScope, expectedTeamContext: scope?.teamContext)
        } else {
            result = try await api.request(method, path: path, serverProfile: scope?.serverProfile ?? ServerProfile.current(),
                headers: headers, expectedAccountID: scope?.accountId,
                expectedScope: scope?.offlineScope, expectedTeamContext: scope?.teamContext)
        }
        if let scope { try await scope.check() }
        return result
    }

    func guestEligibility(details: AppsSkillDetails, input: [String: Any], scope: AppsGuestScope) async throws -> Bool {
        guard details.executionAvailable, details.anonymousAllowed, details.executionMode == "sync",
              AnonymousFreeUsageService.shared.status?.active == true,
              AppsSkillInput.validation(details.inputSchema.mapValues(\.value), input: input).isEmpty else { return false }
        try await scope.check()
        let path = AppsWorkspacePaths.skill(details.appID, details.skillID).replacingOccurrences(of: "/v1/apps/", with: "/v1/anonymous/apps/") + "/availability"
        let data = try await request(.post, path: path, body: JSONSerialization.data(withJSONObject: input),
            headers: ["X-OpenMates-Anonymous-ID": scope.anonymousID], scope: nil)
        try await scope.check()
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["allowed"] as? Bool == true
    }

    func dispatchGuest(details: AppsSkillDetails, input: [String: Any], scope: AppsGuestScope) async throws -> [String: Any] {
        guard try await guestEligibility(details: details, input: input, scope: scope) else { throw AppsWorkspaceError.unavailable }
        try await scope.check()
        let path = AppsWorkspacePaths.skill(details.appID, details.skillID).replacingOccurrences(of: "/v1/apps/", with: "/v1/anonymous/apps/")
        let response = try object(try await request(.post, path: path, body: JSONSerialization.data(withJSONObject: input),
            headers: ["X-OpenMates-Anonymous-ID": scope.anonymousID], scope: nil))
        try await scope.check()
        return response
    }

    func dispatch(details: AppsSkillDetails, input: [String: Any], scope: WorkflowRequestScope) async throws -> [String: Any] {
        guard details.executionAvailable, details.appID != "ai", AppsSkillInput.validation(details.inputSchema.mapValues(\.value), input: input).isEmpty else { throw AppsWorkspaceError.invalidInput }
        guard TeamWorkspaceContext.shared.selectedTeam?.canContribute != false else { throw AppsWorkspaceError.unavailable }
        let path = AppsWorkspacePaths.scoped(AppsWorkspacePaths.skill(details.appID, details.skillID), teamID: scope.teamContext?.teamID)
        return try object(try await request(.post, path: path, body: JSONSerialization.data(withJSONObject: input), scope: scope))
    }

    func poll(taskID: String, scope: WorkflowRequestScope) async throws -> Any {
        let deadline = Date().addingTimeInterval(600)
        while Date() < deadline {
            try Task.checkCancellation()
            let value = try object(try await request(.get, path: "/v1/tasks/" + AppsWorkspacePaths.component(taskID), scope: scope))
            if value["status"] as? String == "completed" { return value["result"] ?? [:] }
            if value["status"] as? String == "failed" { throw AppsWorkspaceError.failed }
            try await Task.sleep(for: .seconds(2))
        }
        throw AppsWorkspaceError.timedOut
    }

    func results(appID: String, offset: Int, scope: WorkflowRequestScope) async throws -> AppsResultsPage {
        try JSONDecoder().decode(AppsResultsPage.self, from: await request(.get,
            path: AppsWorkspacePaths.page(appID: appID, offset: offset, teamID: scope.teamContext?.teamID), scope: scope))
    }

    func upload(_ graph: AppsSavedGraph, scope: WorkflowRequestScope) async throws {
        guard graph.expectedUserID == scope.accountId, graph.teamID == scope.teamContext?.teamID else { throw CancellationError() }
        _ = try await request(.post, path: AppsWorkspacePaths.results, body: JSONEncoder().encode(graph), scope: scope)
    }

    func open(rootID: String, scope: WorkflowRequestScope, resume: Bool = true) async throws -> [EmbedRecord] {
        let offline = try await NativeWorkspaceOfflineRuntime.configure(accountID: scope.accountId, teamID: scope.teamContext?.teamID)
        let cached = try await NativeWorkspaceOfflineRuntime.cached(namespace: "apps-results", path: rootID, scope: offline)
        let localGraph = try cached.map { try JSONDecoder().decode(AppsSavedGraph.self, from: $0) }
        if let localGraph, localGraph.expectedUserID != scope.accountId || localGraph.teamID != scope.teamContext?.teamID { throw CancellationError() }
        let wrappingKey = try await wrappingKey(scope: scope)
        let detail: AppsResultDetail
        do {
            let data = try await request(.get, path: AppsWorkspacePaths.scoped(AppsWorkspacePaths.results + "/" + AppsWorkspacePaths.component(rootID), teamID: scope.teamContext?.teamID), scope: scope)
            detail = try JSONDecoder().decode(AppsResultDetail.self, from: data)
        } catch {
            try await scope.check()
            guard let localGraph else { throw error }
            let key = try ComposerEmbedCrypto.unwrapKey(localGraph.encryptedEmbedKey, using: wrappingKey)
            return try AppsResultGraph.records(rows: localGraph.embeds, key: key, appID: localGraph.appID, skillID: localGraph.skillID)
        }
        guard let wrapper = detail.key else {
            let original = EmbedRecord(id: detail.root.embedID, type: "app_skill_use", status: detail.root.status, data: nil,
                encryptedContent: detail.root.encryptedContent, encryptedType: detail.root.encryptedType,
                parentEmbedId: nil, appId: detail.root.appID, skillId: detail.root.skillID, embedIds: nil,
                hashedChatId: detail.root.hashedChatID, createdAt: nil)
            guard let key = await EmbedKeyManager.shared.key(for: original, chatId: "", allEmbeds: [:]) else { throw AppsWorkspaceError.missingKey }
            try await scope.check()
            return try AppsResultGraph.records(rows: [detail.root] + detail.children, key: key,
                appID: detail.root.appID ?? "", skillID: detail.root.skillID ?? "")
        }
        let key = try ComposerEmbedCrypto.unwrapKey(wrapper.encryptedEmbedKey, using: wrappingKey)
        var records = try AppsResultGraph.records(rows: [detail.root] + detail.children, key: key, appID: "", skillID: "")
        if let localGraph {
            let localKey = try ComposerEmbedCrypto.unwrapKey(localGraph.encryptedEmbedKey, using: wrappingKey)
            let existing = Set(records.map(\.id))
            records += try AppsResultGraph.records(rows: localGraph.embeds.filter { !existing.contains($0.embedID) }, key: localKey, appID: localGraph.appID, skillID: localGraph.skillID)
        }
        if let parent = records.first, let raw = parent.rawData?.mapValues(\.value) {
            for linked in detail.linked ?? [] where !records.contains(where: { $0.id == linked.embedID }) {
                // Single generated responses retain their exact result metadata on
                // the encrypted parent. Reuse that metadata and its original ID.
                if raw["embed_id"] as? String == linked.embedID {
                    records.append(EmbedRecord(id: linked.embedID, type: ["images": "image", "audio": "audio", "videos": "video", "music": "music"][parent.appId ?? ""] ?? "app_skill_use",
                        status: linked.status, data: .raw(raw.mapValues(AnyCodable.init)), parentEmbedId: nil,
                        appId: parent.appId, skillId: parent.skillId, embedIds: nil, createdAt: nil))
                }
            }
            if resume, detail.root.status == .processing, let appID = parent.appId, let skillID = parent.skillId {
                let tasks = AppsResultGraph.taskIDs(raw)
                var response: [String: Any]
                if tasks.isEmpty { response = ["status": "error", "error": "request_interrupted"] }
                else {
                    do {
                        var outputs: [Any] = []
                        for task in tasks { outputs.append(try await poll(taskID: task, scope: scope)) }
                        response = ["data": outputs.count == 1 ? outputs[0] : ["results": outputs], "success": true]
                    } catch AppsWorkspaceError.timedOut { return records }
                    catch AppsWorkspaceError.failed { response = ["status": "error"] }
                }
                let graph = try AppsResultGraph.make(rootID: rootID, appID: appID, skillID: skillID,
                    input: raw["input"] as? [String: Any] ?? [:], response: response, accountID: scope.accountId,
                    teamID: scope.teamContext?.teamID, key: key, wrapper: wrapper.encryptedEmbedKey)
                try await NativeWorkspaceOfflineCache.shared.retain(namespace: "apps-results", path: rootID,
                    data: JSONEncoder().encode(graph), scope: offline)
                try await upload(graph, scope: scope)
                records = try AppsResultGraph.records(rows: graph.embeds, key: key, appID: appID, skillID: skillID)
            }
        }
        return try await refreshGeneratedURLs(records, scope: scope)
    }

    private func refreshGeneratedURLs(_ records: [EmbedRecord], scope: WorkflowRequestScope) async throws -> [EmbedRecord] {
        var refreshed: [EmbedRecord] = []
        for record in records {
            guard record.childEmbedIds.isEmpty, ["images", "audio", "music", "videos"].contains(record.appId ?? ""),
                  var content = record.rawData?.mapValues(\.value), var files = content["files"] as? [String: [String: Any]] else { refreshed.append(record); continue }
            for (variant, file) in files {
                if file["s3_key"] is String && content["aes_key"] is String { continue }
                if scope.teamContext?.teamID == nil, file["download_url"] is String, (file["download_expires_at"] as? Int ?? 0) > Int(Date().timeIntervalSince1970) + 60 { continue }
                let path = AppsWorkspacePaths.scoped("/v1/generated-assets/\(AppsWorkspacePaths.component(record.id))/files/\(AppsWorkspacePaths.component(variant))/download-url", teamID: scope.teamContext?.teamID)
                do {
                    let response = try JSONSerialization.jsonObject(with: await request(.get, path: path, scope: scope)) as? [String: Any] ?? [:]
                    var next = file; next.merge(response) { _, new in new }; files[variant] = next
                } catch is CancellationError { throw CancellationError() }
                catch { /* A URL failure never makes saved ciphertext unsaved. */ }
            }
            content["files"] = files
            let original = files["original"]?["download_url"] as? String ?? ""
            let preview = files["preview"]?["download_url"] as? String ?? original
            switch record.appId {
            case "images": content["previewImageUrl"] = preview
            case "audio": content["previewAudioUrl"] = original; content["audio_url"] = original
            case "music": content["previewAudioUrl"] = original
            case "videos": content["previewVideoUrl"] = original; content["video_url"] = original
            default: break
            }
            refreshed.append(record.decryptedCopy(content: String(decoding: try JSONSerialization.data(withJSONObject: content), as: UTF8.self), type: record.type))
        }
        return refreshed
    }

    func wrappingKey(scope: WorkflowRequestScope) async throws -> SymmetricKey {
        try await scope.check()
        if let teamID = scope.teamContext?.teamID {
            guard let team = TeamWorkspaceContext.shared.selectedTeam, team.id == teamID, team.canRead else { throw AppsWorkspaceError.missingKey }
            return team.key
        }
        guard let key = try await CryptoManager.shared.loadMasterKey(for: scope.accountId) else { throw AppsWorkspaceError.missingKey }
        try await scope.check()
        return key
    }

    private func object(_ data: Data) throws -> [String: Any] {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw AppsWorkspaceError.invalidResponse }
        let nested = object["data"] as? [String: Any]
        guard object["success"] as? Bool != false, object["error"] as? String == nil,
              nested?["success"] as? Bool != false, nested?["error"] as? String == nil else { throw AppsWorkspaceError.failed }
        return object
    }
}

enum AppsResultGraph {
    static func promoting(_ graph: AppsSavedGraph, accountID: String, key: SymmetricKey, masterKey: SymmetricKey) throws -> AppsSavedGraph {
        guard graph.teamID == nil, !accountID.isEmpty,
              graph.expectedUserID.isEmpty || graph.expectedUserID == accountID else { throw CancellationError() }
        if !graph.expectedUserID.isEmpty { return graph }
        return AppsSavedGraph(appID: graph.appID, skillID: graph.skillID, teamID: nil, rootEmbedID: graph.rootEmbedID,
            embeds: graph.embeds, linkedEmbedIDs: graph.linkedEmbedIDs,
            encryptedEmbedKey: try ComposerEmbedCrypto.wrapKey(key, using: masterKey), expectedUserID: accountID)
    }
    static func taskIDs(_ response: [String: Any]) -> [String] {
        let data = response["data"] as? [String: Any] ?? response
        if let id = data["task_id"] as? String { return [id] }
        return data["task_ids"] as? [String] ?? []
    }

    static func extractedResults(_ response: Any) -> [Any] {
        if let array = response as? [Any] { return array.flatMap { item in let nested = extractedResults(item); return nested.isEmpty ? [item] : nested } }
        guard let outer = response as? [String: Any] else { return [] }
        if let data = outer["data"] { return extractedResults(data) }
        if let groups = outer["results"] as? [Any] {
            return groups.flatMap { ($0 as? [String: Any])?["results"] as? [Any] ?? [$0] }
        }
        return (outer["embed_id"] as? String).flatMap(UUID.init(uuidString:)) == nil ? [] : [outer]
    }

    static func childID(rootID: String, index: Int) -> String {
        var bytes = Array(SHA256.hash(data: Data("\(rootID):child:\(index)".utf8)).prefix(16))
        bytes[6] = (bytes[6] & 0x0f) | 0x40; bytes[8] = (bytes[8] & 0x3f) | 0x80
        let hex = bytes.map { String(format: "%02x", $0) }.joined()
        let parts = [0..<8, 8..<12, 12..<16, 16..<20, 20..<32].map { String(hex.dropFirst($0.lowerBound).prefix($0.count)) }
        return parts.joined(separator: "-")
    }

    static func make(rootID: String, appID: String, skillID: String, input: [String: Any], response: [String: Any],
                     accountID: String, teamID: String?, key: SymmetricKey, wrapper: String) throws -> AppsSavedGraph {
        let metadata = response["data"] as? [String: Any] ?? response
        let rawStatus = metadata["status"] as? String ?? "finished"
        let status = EmbedStatus(rawValue: rawStatus) ?? .finished
        let childType = EmbedType.normalized(rawValue: "app:\(appID):\(skillID)")?.childType?.rawValue
        let results = status == .processing ? [] : extractedResults(response)
        guard results.count <= 500 else { throw AppsWorkspaceError.invalidResponse }
        var rows: [AppsCipherRow] = [], ids: [String] = []
        var linked = (metadata["child_embed_ids"] ?? metadata["embed_ids"]) as? [String] ?? []
        for (index, result) in results.enumerated() {
            let object = result as? [String: Any] ?? [:]
            let assetID = (object["embed_id"] as? String).flatMap { UUID(uuidString: $0) == nil ? nil : $0 }
            guard childType != nil || assetID != nil else { continue }
            let id = assetID ?? childID(rootID: rootID, index: index)
            guard id != rootID, !ids.contains(id) else { continue }
            var content = object; content["app_id"] = appID; content["skill_id"] = skillID; content["result"] = result
            let type = object["type"] as? String ?? object["embed_type"] as? String ?? childType ?? ["images": "image", "audio": "audio", "videos": "video", "music": "music"][appID] ?? "app_skill_use"
            rows.append(try row(id: id, type: type, content: content, status: .finished, parent: rootID, children: nil, key: key)); ids.append(id)
        }
        linked = Array(Set(linked.filter { UUID(uuidString: $0) != nil && !ids.contains($0) })).sorted()
        var content = metadata; content.removeValue(forKey: "results")
        content["app_id"] = appID; content["skill_id"] = skillID; content["input"] = input
        content["result_count"] = results.count; content["embed_ids"] = ids + linked; content["status"] = status.rawValue
        if childType == nil { content["results"] = results }
        if let requests = input["requests"] as? [[String: Any]], let request = requests.first { content.merge(request) { current, _ in current } }
        let root = try row(id: rootID, type: "app_skill_use", content: content, status: status, parent: nil, children: ids + linked, key: key)
        return AppsSavedGraph(appID: appID, skillID: skillID, teamID: teamID, rootEmbedID: rootID,
            embeds: [root] + rows, linkedEmbedIDs: linked, encryptedEmbedKey: wrapper, expectedUserID: accountID)
    }

    private static func row(id: String, type: String, content: [String: Any], status: EmbedStatus,
                            parent: String?, children: [String]?, key: SymmetricKey) throws -> AppsCipherRow {
        let text = String(decoding: try JSONSerialization.data(withJSONObject: content), as: UTF8.self)
        return AppsCipherRow(embedID: id, encryptedType: try ComposerEmbedCrypto.encryptContent(type, using: key),
            encryptedContent: try ComposerEmbedCrypto.encryptContent(text, using: key), status: status, embedIDs: children, parentEmbedID: parent)
    }

    static func records(rows: [AppsCipherRow], key: SymmetricKey, appID: String, skillID: String) throws -> [EmbedRecord] {
        try rows.map { row in
            let type = try ComposerEmbedCrypto.decryptContent(row.encryptedType, using: key)
            let text = try ComposerEmbedCrypto.decryptContent(row.encryptedContent, using: key)
            let data = EmbedRecord.parseContent(text)
            let app = data["app_id"] as? String ?? appID, skill = data["skill_id"] as? String ?? skillID
            return EmbedRecord(id: row.embedID, type: type == "app_skill_use" ? "app:\(app):\(skill)" : type,
                status: row.status, data: .raw(data.mapValues(AnyCodable.init)), parentEmbedId: row.parentEmbedID,
                appId: app, skillId: skill, embedIds: row.embedIDs.map { String(decoding: (try? JSONEncoder().encode($0)) ?? Data(), as: UTF8.self) }, createdAt: nil)
        }
    }
}
