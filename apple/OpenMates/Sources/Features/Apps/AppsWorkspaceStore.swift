// Web sources: components/apps/AppsWorkspace.svelte, services/appsWorkspaceService.ts,
// services/appsWorkspaceResultsService.ts
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.discovery.public-catalog, apps.forms.metadata-driven,
// apps.execution.direct-shared-contract, apps.results.web-retained-graph,
// apps.library.embeds-account-paginated, apps.library.workflows-account-related,
// apps.anonymous.cli-equivalent-gate, apps.anonymous.local-results-and-promotion
import Combine
import CryptoKit
import CoreFoundation
import Foundation

@MainActor
final class AppsWorkspaceStore: ObservableObject {
    @Published private(set) var apps: [SettingsAppsFullView.AppInfo] = []
    @Published private(set) var homeApps: [SettingsAppsFullView.AppInfo] = []
    @Published private(set) var visibleApps: [SettingsAppsFullView.AppInfo] = []
    @Published private(set) var selectedApp: SettingsAppsFullView.AppInfo?
    @Published private(set) var selectedSkill: SettingsAppsFullView.AppSkill?
    @Published private(set) var details: AppsSkillDetails?
    @Published private(set) var primarySchema: [String: Any]?
    @Published private(set) var advancedSchema: [String: Any]?
    @Published private(set) var requirementsPath: String?
    @Published private(set) var executionMetadata: [String] = []
    @Published private(set) var input: [String: Any] = [:]
    @Published private(set) var validationIssues: [String] = []
    @Published private(set) var tab: AppsWorkspaceTab = .overview
    @Published var search = "" { didSet { projectCatalog() } }
    @Published var showingAll = false
    @Published private(set) var isLoading = false
    @Published private(set) var metadataLoading = false
    @Published private(set) var isSubmitting = false
    @Published private(set) var checkingGuest = false
    @Published private(set) var guestAllowed = false
    @Published private(set) var errorKey: String?
    @Published private(set) var libraryLoading = false
    @Published private(set) var libraryError = false
    @Published private(set) var results: [AppsResultRow] = []
    @Published private(set) var workflows: [AppsWorkflowRow] = []
    @Published private(set) var offset = 0
    @Published private(set) var hasMore = false
    @Published private(set) var records: [String: EmbedRecord] = [:]
    @Published private(set) var inlineResult: EmbedRecord?
    @Published var selectedResult: EmbedRecord?
    @Published private(set) var saveState: String?
    @Published private(set) var headerEmbed: EmbedRecord?
    @Published private(set) var accountID: String?
    private var recentIDs: [String] = []
    private var generation = UUID()
    private var selectionGeneration = UUID()
    private var metadataTask: Task<Void, Never>?
    private var guestQuoteTask: Task<Void, Never>?
    private var executionTask: Task<Void, Never>?
    private var libraryTask: Task<Void, Never>?
    private let service: AppsWorkspaceService
    private var pending: [String: AppsSavedGraph] = [:]
    private var inlineRootID: String?
    private var pendingRoute: String?
    private var scope: WorkflowRequestScope?
    private var offlineScope: NativeWorkspaceOfflineScope?
    private var loadInFlight = false
    private var hydrations: [String: Task<Void, Never>] = [:]
    private(set) var usesPreviewData = false
    @Published private(set) var previewDispatchCount = 0

    struct AppsWorkflowRow: Decodable, Identifiable { let id: String; let title: String }
    private struct WorkflowPage: Decodable {
        let workflows: [AppsWorkflowRow]; let hasMore: Bool
        enum CodingKeys: String, CodingKey { case workflows, hasMore = "has_more" }
    }

    init(service: AppsWorkspaceService = AppsWorkspaceService()) { self.service = service }
    var viewer: Bool { TeamWorkspaceContext.shared.selectedTeam?.canContribute == false }
    var guest: Bool { accountID == nil }

    func reset(accountId: String?) {
        generation = UUID(); selectionGeneration = UUID()
        metadataTask?.cancel(); executionTask?.cancel(); libraryTask?.cancel(); guestQuoteTask?.cancel()
        for task in hydrations.values { task.cancel() }; hydrations = [:]; loadInFlight = false
        accountID = accountId; scope = nil; offlineScope = nil
        selectedApp = nil; selectedSkill = nil; details = nil; input = [:]
        headerEmbed = nil; primarySchema = nil; advancedSchema = nil; requirementsPath = nil; executionMetadata = []
        selectedResult = nil; inlineResult = nil; records = [:]; pending = [:]; recentIDs = []
        results = []; workflows = []; offset = 0; hasMore = false; saveState = nil; inlineRootID = nil
        isLoading = false; metadataLoading = false; libraryLoading = false; isSubmitting = false; checkingGuest = false; guestAllowed = false; errorKey = nil
        projectCatalog()
    }

    func load() async {
        if ProcessInfo.processInfo.arguments.contains("--ui-test-apps-workspace") { installPreviewFixture(); return }
        guard !loadInFlight else { return }
        let owner = generation; loadInFlight = true; isLoading = apps.isEmpty
        defer { if generation == owner { isLoading = false; loadInFlight = false } }
        do {
            let capturedScope: WorkflowRequestScope?
            if let accountID {
                let accountScope = try await WorkflowRequestScope.capture(accountId: accountID)
                guard generation == owner else { return }
                let offline = try await NativeWorkspaceOfflineRuntime.configure(accountID: accountID, teamID: accountScope.teamContext?.teamID)
                try await accountScope.check()
                guard generation == owner else { return }
                capturedScope = accountScope; scope = accountScope; offlineScope = offline
                if let cached = try await NativeWorkspaceOfflineRuntime.cached(namespace: "apps", path: "/v1/apps/metadata", scope: offline) {
                    try await accountScope.check()
                    guard generation == owner else { return }
                    let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
                    let catalog = try decoder.decode(SettingsAppsFullView.AppsMetadataResponse.self, from: cached)
                    apps = catalog.apps.values.map(SettingsAppsFullView.appInfo).filter { $0.id != "ai" }.sorted { $0.name < $1.name }
                    isLoading = false; projectCatalog()
                }
            } else {
                capturedScope = nil
                await AnonymousFreeUsageService.shared.refreshStatus()
                guard generation == owner else { return }
            }
            let catalog = try await service.catalog(scope: capturedScope)
            guard generation == owner else { return }
            apps = catalog; errorKey = nil; isLoading = false; projectCatalog()
            if let route = pendingRoute { pendingRoute = nil; openRoute(route) }
            // Publish the catalog before any private result recovery or promotion.
            if let capturedScope {
                await recoverPending()
                try await capturedScope.check()
                guard generation == owner else { return }
                if capturedScope.teamContext?.teamID == nil { await promoteGuestResults() }
            }
        } catch is CancellationError { }
        catch { if generation == owner && apps.isEmpty { errorKey = "metadata_error" } }
    }

    private func projectCatalog() {
        let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
        visibleApps = query.isEmpty ? apps : apps.filter { $0.name.localizedCaseInsensitiveContains(query) || ($0.description ?? "").localizedCaseInsensitiveContains(query) }
        let ids = recentIDs + ["web", "news", "health", "travel", "weather", "audio"]
        var seen = Set<String>()
        homeApps = ids.filter { seen.insert($0).inserted }.compactMap { id in apps.first { $0.id == id } }.prefix(6).map { $0 }
    }

    func selectApp(_ app: SettingsAppsFullView.AppInfo) {
        selectionGeneration = UUID(); metadataTask?.cancel(); guestQuoteTask?.cancel(); libraryTask?.cancel()
        selectedApp = app; selectedSkill = nil; details = nil; tab = .overview
        headerEmbed = EmbedRecord(id: "apps-detail-" + app.id, type: "app_skill_use", status: .finished,
            data: nil, parentEmbedId: nil, appId: app.id, skillId: nil, embedIds: nil, createdAt: nil)
        errorKey = nil; inlineResult = nil; selectedResult = nil; results = []; workflows = []; offset = 0
    }
    func closeDetail() {
        if selectedSkill != nil, let app = selectedApp { selectApp(app) }
        else { selectionGeneration = UUID(); metadataTask?.cancel(); guestQuoteTask?.cancel(); selectedApp = nil; selectedSkill = nil }
    }
    func selectSkill(_ skill: SettingsAppsFullView.AppSkill) {
        guard let app = selectedApp else { return }
        let selection = UUID(); selectionGeneration = selection
        metadataTask?.cancel(); guestQuoteTask?.cancel()
        selectedSkill = skill; details = nil; metadataLoading = true; input = [:]; validationIssues = []
        tab = .overview; inlineResult = nil; saveState = nil; inlineRootID = nil; errorKey = nil
        let context = generation, capturedScope = scope
        if usesPreviewData {
            applyDetails(AppsWorkspacePreviewFixture.details); metadataLoading = false; guestAllowed = true; return
        }
        metadataTask = Task {
            defer { if selectionGeneration == selection { metadataLoading = false } }
            do {
                let value = try await service.details(appID: app.id, skillID: skill.id, scope: capturedScope)
                guard generation == context, selectionGeneration == selection, value.appID == app.id, value.skillID == skill.id else { return }
                applyDetails(value)
            } catch is CancellationError { }
            catch { if generation == context && selectionGeneration == selection { errorKey = "metadata_error" } }
        }
    }

    private func applyDetails(_ value: AppsSkillDetails) {
        details = value; input = value.defaults.mapValues(\.value)
        let schema = value.inputSchema.mapValues(\.value)
        let primary = AppsSkillInput.expandingComposite(Array(value.primaryFields.prefix(2)), schema: schema)
        let leaves = AppsSkillInput.leaves(schema)
        requirementsPath = leaves.first { ($0 == "relevance_criteria" || $0.hasSuffix(".relevance_criteria")) && !primary.contains($0) }
        primarySchema = AppsSkillInput.select(schema, paths: primary)
        advancedSchema = AppsSkillInput.select(schema, paths: leaves.filter { path in path != requirementsPath && !primary.contains(where: { path == $0 || path.hasPrefix($0 + ".") || path.hasPrefix($0 + "[].") }) })
        executionMetadata = Self.executionLabels(value)
        updateInput(input)
    }

    static func executionLabels(_ details: AppsSkillDetails) -> [String] {
        func tr(_ key: String) -> String { AppStrings.localized("apps.skill_form." + key) }
        func names(_ values: [[String: AnyCodable]]) -> [String] {
            var seen = Set<String>()
            return values.compactMap { $0["name"]?.value as? String }.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty && seen.insert($0).inserted }
        }
        func amount(_ value: Any?) -> NSNumber? {
            guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite, number.doubleValue >= 0 else { return nil }
            return number
        }
        func pricing(_ value: [String: Any]) -> [String] {
            let credits = AppStrings.localized("common.credits")
            var rates: [String] = []
            for (field, key) in [("fixed", "per_request"), ("per_second", "per_second"), ("per_minute", "per_minute")] {
                if let number = amount(value[field]) { rates.append(number.stringValue + " " + credits + " " + tr(key)) }
            }
            if let unit = value["per_unit"] as? [String: Any], let number = amount(unit["credits"]) {
                let name = (unit["unit_name"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                rates.append(number.stringValue + " " + credits + " " + tr("per_unit").replacingOccurrences(of: "{unit}", with: name.isEmpty ? tr("request") : name))
            }
            if let tokens = value["tokens"] as? [String: Any] {
                for direction in ["input", "output"] {
                    if let rate = tokens[direction] as? [String: Any], let count = amount(rate["per_credit_unit"]), count.doubleValue > 0 {
                        rates.append(tr("one_credit_per") + " " + count.stringValue + " " + tr(direction + "_tokens"))
                    }
                }
            }
            return rates
        }
        var labels: [String] = []
        let providers = names(details.providers)
        if !providers.isEmpty { labels.append(tr("via") + " " + providers.joined(separator: ", ")) }
        labels += pricing(details.pricing?.mapValues(\.value) ?? [:])
        let models = names(details.models)
        if !models.isEmpty { labels.append(tr(models.count == 1 ? "model" : "models") + " " + models.joined(separator: ", ")) }
        for model in details.models {
            let name = model["name"]?.value as? String ?? ""
            labels += pricing(model["pricing"]?.value as? [String: Any] ?? [:]).map { name.isEmpty ? $0 : name + ": " + $0 }
        }
        return labels
    }

    func updateInput(_ next: [String: Any]) {
        input = next; validationIssues = []
        if usesPreviewData { guestAllowed = true; return }
        guestQuoteTask?.cancel(); guestAllowed = false
        guard guest, let details else { return }
        let prepared = AppsSkillInput.prepare(details.inputSchema.mapValues(\.value), input: next)
        guard AppsSkillInput.validation(details.inputSchema.mapValues(\.value), input: prepared).isEmpty else { checkingGuest = false; return }
        let context = generation, selection = selectionGeneration, guestScope = AppsGuestScope.capture()
        checkingGuest = true
        guestQuoteTask = Task {
            defer { if generation == context && selectionGeneration == selection { checkingGuest = false } }
            do {
                try await Task.sleep(for: .milliseconds(250))
                let allowed = try await service.guestEligibility(details: details, input: prepared, scope: guestScope)
                guard !Task.isCancelled, generation == context, selectionGeneration == selection else { return }
                guestAllowed = allowed
            } catch { }
        }
    }

    func submit() {
        guard !isSubmitting, let details, details.executionAvailable, !viewer else { return }
        let prepared = AppsSkillInput.prepare(details.inputSchema.mapValues(\.value), input: input)
        validationIssues = AppsSkillInput.validation(details.inputSchema.mapValues(\.value), input: prepared)
        guard validationIssues.isEmpty, !guest || guestAllowed else { return }
        let context = generation, selection = selectionGeneration
        let rootID = UUID().uuidString.lowercased(), key = SymmetricKey(size: .bits256)
        let capturedScope = scope, guestScope = AppsGuestScope.capture()
        isSubmitting = true; errorKey = nil
        if usesPreviewData {
            previewDispatchCount += 1
            executionTask = Task {
                defer { isSubmitting = false }
                do {
                    let graph = try AppsResultGraph.make(rootID: rootID, appID: details.appID, skillID: details.skillID, input: prepared,
                        response: AppsWorkspacePreviewFixture.response, accountID: "", teamID: nil, key: key, wrapper: "fixture-only")
                    guard generation == context else { return }
                    try publish(graph, key: key); saveState = "saved"
                } catch { errorKey = "request_error" }
            }
            return
        }
        executionTask = Task {
            defer { if generation == context { isSubmitting = false; if guest { updateInput(input) } } }
            var storedWrapper: String?
            var acceptedTaskIDs: [String] = []
            do {
                let wrapper: String
                if let capturedScope { wrapper = try ComposerEmbedCrypto.wrapKey(key, using: await service.wrappingKey(scope: capturedScope)) }
                else { wrapper = try AnonymousFreeUsageService.shared.wrapAppsResultKey(key) }
                storedWrapper = wrapper
                let initial = try AppsResultGraph.make(rootID: rootID, appID: details.appID, skillID: details.skillID,
                    input: prepared, response: ["status": "processing"], accountID: capturedScope?.accountId ?? "",
                    teamID: capturedScope?.teamContext?.teamID, key: key, wrapper: wrapper)
                if let capturedScope { try await retain(initial, key: key, scope: capturedScope, selection: selection) }
                else { try await retainGuest(initial, key: key, scope: guestScope, selection: selection) }
                var response: [String: Any]
                if let capturedScope { response = try await service.dispatch(details: details, input: prepared, scope: capturedScope) }
                else { response = try await service.dispatchGuest(details: details, input: prepared, scope: guestScope) }
                guard generation == context else { return }
                let taskIDs = AppsResultGraph.taskIDs(response)
                acceptedTaskIDs = taskIDs
                if !taskIDs.isEmpty, let capturedScope {
                    let processing = try AppsResultGraph.make(rootID: rootID, appID: details.appID, skillID: details.skillID,
                        input: prepared, response: ["status": "processing", "task_ids": taskIDs], accountID: capturedScope.accountId,
                        teamID: capturedScope.teamContext?.teamID, key: key, wrapper: wrapper)
                    try await retain(processing, key: key, scope: capturedScope, selection: selection)
                    var values: [Any] = []
                    for taskID in taskIDs { values.append(try await service.poll(taskID: taskID, scope: capturedScope)) }
                    response = ["data": values.count == 1 ? values[0] : ["results": values], "success": true]
                }
                let graph = try AppsResultGraph.make(rootID: rootID, appID: details.appID, skillID: details.skillID, input: prepared,
                    response: response, accountID: capturedScope?.accountId ?? "", teamID: capturedScope?.teamContext?.teamID, key: key, wrapper: wrapper)
                if let capturedScope { try await retain(graph, key: key, scope: capturedScope, selection: selection) }
                else {
                    try await retainGuest(graph, key: key, scope: guestScope, selection: selection)
                }
                guard generation == context else { return }
                recentIDs.removeAll { $0 == details.appID }; recentIDs.insert(details.appID, at: 0); projectCatalog()
            } catch is CancellationError { }
            catch {
                if generation == context, let wrapper = storedWrapper {
                    let terminalFailure = (error as? AppsWorkspaceError) == .failed
                    let state: [String: Any] = acceptedTaskIDs.isEmpty || terminalFailure ? ["status": "error"] : ["status": "processing", "task_ids": acceptedTaskIDs]
                    if let graph = try? AppsResultGraph.make(rootID: rootID, appID: details.appID, skillID: details.skillID,
                        input: prepared, response: state, accountID: capturedScope?.accountId ?? "", teamID: capturedScope?.teamContext?.teamID, key: key, wrapper: wrapper) {
                        if let capturedScope { try? await retain(graph, key: key, scope: capturedScope, selection: selection) }
                        else { try? await retainGuest(graph, key: key, scope: guestScope, selection: selection) }
                    }
                }
                if generation == context && selectionGeneration == selection { errorKey = "request_error" }
            }
        }
    }

    private func retainGuest(_ graph: AppsSavedGraph, key: SymmetricKey, scope: AppsGuestScope, selection: UUID) async throws {
        try await scope.check()
        let receipt = AppsGuestReceipt(graph: graph, createdAt: Int(Date().timeIntervalSince1970),
            server: scope.profile.apiBaseURL.absoluteString, anonymousID: scope.anonymousID)
        let encrypted = try AnonymousFreeUsageService.shared.encryptAppsResultReceipt(JSONEncoder().encode(receipt))
        try await AppsGuestResults.shared.save(id: graph.rootEmbedID, ciphertext: encrypted)
        try await scope.check()
        if selectionGeneration == selection { try publish(graph, key: key); saveState = "saved" }
    }

    private func publish(_ graph: AppsSavedGraph, key: SymmetricKey) throws {
        let rows = try AppsResultGraph.records(rows: graph.embeds, key: key, appID: graph.appID, skillID: graph.skillID)
        records = EmbedRecord.dictionaryById(rows, context: "apps_result")
        inlineResult = records[graph.rootEmbedID]; inlineRootID = graph.rootEmbedID
    }

    private func retain(_ graph: AppsSavedGraph, key: SymmetricKey, scope: WorkflowRequestScope, selection: UUID) async throws {
        let owner = generation
        try await scope.check()
        guard let offlineScope else { throw CancellationError() }
        try await NativeWorkspaceOfflineCache.shared.retain(namespace: "apps-results", path: graph.rootEmbedID,
            data: JSONEncoder().encode(graph), scope: offlineScope)
        try await scope.check()
        guard generation == owner else { throw CancellationError() }
        pending[graph.rootEmbedID] = graph
        try await NativeWorkspaceOfflineCache.shared.retain(namespace: "apps-result-outbox", path: "receipts",
            data: JSONEncoder().encode(pending), scope: offlineScope)
        try await scope.check()
        guard generation == owner else { throw CancellationError() }
        if selectionGeneration == selection { try publish(graph, key: key); saveState = "saving" }
        do {
            try await service.upload(graph, scope: scope)
            try await scope.check()
            guard generation == owner else { throw CancellationError() }
            pending.removeValue(forKey: graph.rootEmbedID)
            try await NativeWorkspaceOfflineCache.shared.retain(namespace: "apps-result-outbox", path: "receipts",
                data: JSONEncoder().encode(pending), scope: offlineScope)
            try await scope.check()
            if generation == owner && selectionGeneration == selection { saveState = "saved" }
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            if generation == owner && selectionGeneration == selection { saveState = "error" }
        }
    }

    func retrySave() async {
        guard let id = inlineRootID, let graph = pending[id], let scope else { return }
        let owner = generation, selection = selectionGeneration
        do {
            let key = try ComposerEmbedCrypto.unwrapKey(graph.encryptedEmbedKey, using: await service.wrappingKey(scope: scope))
            guard generation == owner, selectionGeneration == selection else { return }
            try await retain(graph, key: key, scope: scope, selection: selection)
        } catch is CancellationError { }
        catch { if generation == owner && selectionGeneration == selection { saveState = "error" } }
    }

    private func recoverPending() async {
        guard let offlineScope, let scope else { return }
        let owner = generation
        do {
            if let data = try await NativeWorkspaceOfflineRuntime.cached(namespace: "apps-result-outbox", path: "receipts", scope: offlineScope) {
                try await scope.check()
                guard generation == owner else { return }
                let recovered = try JSONDecoder().decode([String: AppsSavedGraph].self, from: data)
                pending.merge(recovered) { current, _ in current }
                for graph in recovered.values {
                    try await scope.check()
                    try await service.upload(graph, scope: scope)
                    try await scope.check()
                    guard generation == owner else { return }
                    pending.removeValue(forKey: graph.rootEmbedID)
                }
                try await NativeWorkspaceOfflineCache.shared.retain(namespace: "apps-result-outbox", path: "receipts", data: JSONEncoder().encode(pending), scope: offlineScope)
            }
        } catch { /* Retained exact ciphertext remains retryable. */ }
    }

    private func promoteGuestResults() async {
        guard let scope, scope.teamContext?.teamID == nil else { return }
        do {
            for (id, ciphertext) in try await AppsGuestResults.shared.receipts() {
                try await scope.check()
                let receipt = try JSONDecoder().decode(AppsGuestReceipt.self, from: AnonymousFreeUsageService.shared.decryptAppsResultReceipt(ciphertext))
                guard receipt.matches(server: scope.serverProfile.apiBaseURL.absoluteString,
                    anonymousID: AnonymousFreeUsageService.shared.anonymousId) else { continue }
                let original = receipt.graph
                guard original.expectedUserID.isEmpty || original.expectedUserID == scope.accountId else { continue }
                let graph: AppsSavedGraph
                if original.expectedUserID.isEmpty {
                    let key = try AnonymousFreeUsageService.shared.unwrapAppsResultKey(original.encryptedEmbedKey)
                    graph = try AppsResultGraph.promoting(original, accountID: scope.accountId, key: key, masterKey: await service.wrappingKey(scope: scope))
                    let promoted = AppsGuestReceipt(graph: graph, createdAt: receipt.createdAt,
                        server: receipt.server, anonymousID: receipt.anonymousID)
                    let encrypted = try AnonymousFreeUsageService.shared.encryptAppsResultReceipt(JSONEncoder().encode(promoted))
                    try await AppsGuestResults.shared.save(id: id, ciphertext: encrypted)
                } else { graph = original }
                try await scope.check()
                try await service.upload(graph, scope: scope)
                try await scope.check()
                try await AppsGuestResults.shared.remove(id: id)
            }
        } catch { /* Never delete the only encrypted guest copy on failed promotion. */ }
    }

    func selectTab(_ next: AppsWorkspaceTab) {
        tab = next; offset = 0; hasMore = false; results = []; workflows = []
        if next == .embeds || next == .workflows { loadLibrary(offset: 0) }
    }
    func loadLibrary(offset nextOffset: Int) {
        guard let app = selectedApp else { return }
        let selection = selectionGeneration, context = generation, selectedTab = tab
        libraryTask?.cancel(); libraryLoading = true; libraryError = false
        libraryTask = Task {
            defer { if generation == context && selectionGeneration == selection && tab == selectedTab { libraryLoading = false } }
            do {
                if guest && selectedTab == .workflows { workflows = []; hasMore = false; offset = 0; return }
                if let scope {
                    if selectedTab == .embeds {
                        let page = try await service.results(appID: app.id, offset: nextOffset, scope: scope)
                        guard generation == context, selectionGeneration == selection, tab == selectedTab, !Task.isCancelled else { return }
                        results = page.items; hasMore = page.hasMore; offset = page.offset
                    } else {
                        let path = AppsWorkspacePaths.scoped("/v1/workflows?app_id=\(AppsWorkspacePaths.component(app.id))&offset=\(nextOffset)&limit=20", teamID: scope.teamContext?.teamID)
                        let page = try JSONDecoder().decode(WorkflowPage.self, from: await service.request(.get, path: path, scope: scope))
                        guard generation == context, selectionGeneration == selection, tab == selectedTab, !Task.isCancelled else { return }
                        workflows = page.workflows; hasMore = page.hasMore; offset = nextOffset
                    }
                } else {
                    var rows: [AppsResultRow] = []
                    for (_, ciphertext) in try await AppsGuestResults.shared.receipts() {
                        let receipt = try JSONDecoder().decode(AppsGuestReceipt.self, from: AnonymousFreeUsageService.shared.decryptAppsResultReceipt(ciphertext))
                        if receipt.matches(server: ServerProfile.current().apiBaseURL.absoluteString,
                            anonymousID: AnonymousFreeUsageService.shared.anonymousId), receipt.graph.appID == app.id && receipt.graph.expectedUserID.isEmpty {
                            rows.append(AppsResultRow(embedID: receipt.graph.rootEmbedID, appID: app.id, skillID: receipt.graph.skillID,
                                status: receipt.graph.embeds.first?.status ?? .finished, createdAt: receipt.createdAt))
                        }
                    }
                    guard generation == context, selectionGeneration == selection, !Task.isCancelled else { return }
                    let sorted = rows.sorted { $0.createdAt > $1.createdAt }
                    results = Array(sorted.dropFirst(nextOffset).prefix(20)); hasMore = sorted.count > nextOffset + 20; offset = nextOffset
                }
            } catch is CancellationError { }
            catch { if generation == context && selectionGeneration == selection { libraryError = true } }
        }
    }

    func openResult(_ id: String) async {
        if usesPreviewData, let record = records[id] { selectedResult = record; return }
        let context = generation, selection = selectionGeneration
        do {
            var rows: [EmbedRecord]
            if let scope { rows = try await service.open(rootID: id, scope: scope) }
            else {
                guard let receipt = try await AppsGuestResults.shared.receipt(id: id) else { throw AppsWorkspaceError.unavailable }
                let guest = try JSONDecoder().decode(AppsGuestReceipt.self, from: AnonymousFreeUsageService.shared.decryptAppsResultReceipt(receipt))
                guard guest.matches(server: ServerProfile.current().apiBaseURL.absoluteString,
                    anonymousID: AnonymousFreeUsageService.shared.anonymousId), guest.graph.expectedUserID.isEmpty else { throw CancellationError() }
                let key = try AnonymousFreeUsageService.shared.unwrapAppsResultKey(guest.graph.encryptedEmbedKey)
                rows = try AppsResultGraph.records(rows: guest.graph.embeds, key: key, appID: guest.graph.appID, skillID: guest.graph.skillID)
            }
            guard generation == context, selectionGeneration == selection else { return }
            records = EmbedRecord.dictionaryById(rows, context: "apps_library"); selectedResult = records[id]
        } catch is CancellationError { }
        catch { if generation == context { errorKey = "result_unavailable" } }
    }

    func hydrateResult(_ id: String) {
        guard records[id] == nil, hydrations[id] == nil else { return }
        let context = generation, selection = selectionGeneration
        hydrations[id] = Task {
            defer { if generation == context { hydrations.removeValue(forKey: id) } }
            do {
                guard let scope else { return }
                let loaded = try await service.open(rootID: id, scope: scope, resume: false)
                guard generation == context, selectionGeneration == selection, !Task.isCancelled else { return }
                for row in loaded { records[row.id] = row }
            } catch { /* The truthful status fallback remains openable. */ }
        }
    }

    func openRoute(_ path: String) {
        guard !apps.isEmpty else { pendingRoute = path; return }
        let parts = path.replacingOccurrences(of: "#", with: "").split(separator: "/").map(String.init)
        guard let start = parts.firstIndex(of: "apps"), parts.indices.contains(start + 1) else { return }
        if parts[start + 1] == "all" { showingAll = true; return }
        let appID = parts[start + 1].replacingOccurrences(of: "-", with: "_")
        guard let app = apps.first(where: { $0.id == appID || $0.id == parts[start + 1] }) else { errorKey = "not_found"; return }
        selectApp(app)
        if parts.indices.contains(start + 2) {
            let raw = parts[start + 2] == "skill" && parts.indices.contains(start + 3) ? parts[start + 3] : parts[start + 2]
            if let skill = app.skills?.first(where: { $0.id == raw || $0.id.replacingOccurrences(of: "_", with: "-") == raw }) { selectSkill(skill) }
            else if let tab = AppsWorkspaceTab(rawValue: raw) { selectTab(tab) }
        }
    }

    func installPreviewFixture() {
        reset(accountId: nil); usesPreviewData = true
        apps = [AppsWorkspacePreviewFixture.app]; projectCatalog()
    }
}
