// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability, apple-controls.quick-actions, apple-controls.workflow, apple-controls.project, apple-controls.private-cache
// Deep link handler — processes openmates:// URLs and universal links.
// Supports: chat-id, message-id, share links, settings deep links, app links.
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.new-task-shortcuts
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.navigation.hash-and-forwarding
// Specification: specifications/features/apple-tasks-widget/specification.yml
// Assertions: apple-tasks-widget.links
// Mirrors the web app's hash-based routing (#chat-id=X, #share-chat-id=X).

import Foundation
import SwiftUI

struct WorkflowTemplateLink: Equatable, Identifiable {
    let templateID: String
    let fragmentKey: String
    let webDomain: String
    var id: String { templateID }
}

struct TaskDetailDeepLinkRequest: Equatable, Identifiable {
    let taskID: String
    let id = UUID()
}

struct WorkflowCompletionRoute: Equatable {
    let workflowID: String
    let runID: String
    let chatID: String?
    let messageID: String?
    let deliveryID: String?

    static func parse(_ fields: [String: String]) -> Self? {
        guard let workflowID = fields["workflow_id"] ?? fields["workflow-id"],
              let runID = fields["run_id"] ?? fields["run-id"],
              UUID(uuidString: workflowID) != nil, UUID(uuidString: runID) != nil else { return nil }
        let chatID = fields["chat_id"] ?? fields["chat-id"]
        let messageID = fields["message_id"] ?? fields["message-id"]
        let deliveryID = fields["delivery_id"] ?? fields["delivery-id"]
        let targets = [chatID, messageID, deliveryID]
        guard targets.allSatisfy({ $0 == nil }) || targets.allSatisfy({ $0.flatMap(UUID.init(uuidString:)) != nil }) else { return nil }
        return Self(workflowID: workflowID, runID: runID, chatID: chatID,
                    messageID: messageID, deliveryID: deliveryID)
    }
}

struct ShortShareLink: Equatable {
    let token: String
    let fragmentKey: String

    static func parse(_ url: URL, selectedDomain: String) -> Self? {
        guard url.scheme == "https", url.host?.lowercased() == selectedDomain.lowercased(),
              url.user == nil, url.password == nil, url.port == nil else { return nil }
        let parts = url.pathComponents
        let token: String
        let key: String
        if parts.count == 3, parts[1] == "s" {
            token = parts[2]
            key = url.fragment ?? ""
        } else if parts.count == 2, parts[1] == "s",
                  let fragment = url.fragment,
                  let split = fragment.firstIndex(of: "-") {
            token = String(fragment[..<split])
            key = String(fragment[fragment.index(after: split)...])
        } else { return nil }
        guard token.range(of: "^[A-Za-z0-9]{6,12}$", options: .regularExpression) != nil,
              key.range(of: "^[A-Za-z0-9]{4,22}$", options: .regularExpression) != nil else { return nil }
        return .init(token: token, fragmentKey: key)
    }

    func requestURL(apiBaseURL: URL) -> URL {
        // Construct from the public token only. Never forward the incoming URL
        // or its fragment to the API, redirects, cache, or diagnostics.
        apiBaseURL.appendingPathComponent("v1/share/short-url/\(token)")
    }
}

@MainActor
final class DeepLinkHandler: ObservableObject {
    typealias ShortLinkResolver = @MainActor (ShortShareLink, ServerProfile) async throws -> URL
    private let shortLinkResolver: ShortLinkResolver
    private var shortLinkGeneration = UUID()
    private(set) var shortLinkResolutionTask: Task<Void, Never>?
    @Published var pendingShortLinkError = false
    @Published var pendingSharedBrowserURL: URL?
    @Published var pendingSharedChatURL: URL?
    @Published var pendingChatId: String?
    @Published var pendingActiveChatsWidgetLink: WidgetActiveChatsRoute?
    @Published var pendingEmbedId: String?
    @Published var pendingMessageId: String?
    @Published var pendingShareChatId: String?
    @Published var pendingShareKey: String?
    @Published var pendingSettingsPath: String?
    @Published var pendingAppId: String?
    @Published var pendingPairToken: String?
    @Published var pendingInspirationId: String?
    @Published var pendingMessageText: String?
    @Published var pendingWorkflowTemplate: WorkflowTemplateLink?
    @Published var pendingControlProject: ControlProjectRoute?
    @Published var pendingProjectsWorkspace = false
    @Published var pendingWorkflowWidgetRun: WidgetWorkflowRunRoute?
    @Published var pendingProjectID: String?
    @Published var pendingWorkflowID: String?
    @Published var pendingWorkflowCompletion: WorkflowCompletionRoute?
    @Published var pendingWorkflowsWorkspace = false
    @Published var pendingTasksWorkspace = false
    @Published var pendingTaskID: String? {
        didSet { pendingTaskRequest = pendingTaskID.map { TaskDetailDeepLinkRequest(taskID: $0) } }
    }
    @Published private(set) var pendingTaskRequest: TaskDetailDeepLinkRequest?
    @Published var pendingNewTask = false
    @Published var pendingAppsPath: String?
    @Published var pendingNewChat = false
    @Published var pendingSearch = false

    init(shortLinkResolver: @escaping ShortLinkResolver = DeepLinkHandler.resolveShortLink) {
        self.shortLinkResolver = shortLinkResolver
    }

    func handle(url: URL) {
        invalidateShortLinkResolution()
        pendingShortLinkError = false
        pendingSharedBrowserURL = nil
        pendingSharedChatURL = nil
        pendingWorkflowTemplate = nil
        pendingWorkflowWidgetRun = nil
        pendingWorkflowsWorkspace = false
        pendingControlProject = nil
        pendingProjectsWorkspace = false
        pendingProjectID = nil
        pendingWorkflowID = nil
        pendingWorkflowCompletion = nil
        pendingActiveChatsWidgetLink = nil
        pendingTaskID = nil
        pendingTasksWorkspace = false
        pendingNewTask = false
        // Public recipient decryption is independent of the signed-in account
        // and selected server. Keep the full fragment inside the native viewer.
        if Self.isNativeChatShareURL(url) {
            pendingSharedChatURL = url
            return
        }
        if url.scheme == "openmates" {
            handleCustomScheme(url)
        } else {
            handleUniversalLink(url)
        }
    }

    private func handleCustomScheme(_ url: URL) {
        guard let host = url.host else { return }
        if host == "control-project" {
            pendingControlProject = ControlProjectRoute.parse(url)
            return
        }
        if host == "run-workflow" {
            pendingWorkflowWidgetRun = WidgetWorkflowsLinks.route(url)
            return
        }
        // Every owner-bearing widget link is parsed separately. Malformed or
        // foreign-owner links must never fall through to ordinary chat routing.
        let hasWidgetOwner = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
            .contains(where: { $0.name == "owner" }) == true
        if host == "active-chats" || hasWidgetOwner {
            pendingChatId = nil; pendingEmbedId = nil; pendingMessageId = nil
            pendingActiveChatsWidgetLink = WidgetActiveChatsLinks.route(url)
            return
        }

        switch host {
        case "new-chat", "newchat":
            pendingNewChat = true
        case "tasks":
            pendingTasksWorkspace = true
        case "projects":
            if url.pathComponents.count == 2, let id = url.pathComponents.last, UUID(uuidString: id) != nil { pendingProjectID = id }
            else { pendingProjectsWorkspace = true }
        case "workflows":
            if url.pathComponents.count == 2, let id = url.pathComponents.last, UUID(uuidString: id) != nil { pendingWorkflowID = id }
            else { pendingWorkflowsWorkspace = true }
        case "task":
            if url.pathComponents.count == 2,
               let id = url.pathComponents.last, UUID(uuidString: id) != nil { pendingTaskID = id }
        case "new-task", "newtask":
            pendingNewTask = true
        case "apps":
            pendingAppsPath = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        case "search":
            pendingSearch = true
        case "chat":
            pendingChatId = url.pathComponents.last
            if let components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
                pendingEmbedId = components.queryItems?.first(where: { $0.name == "embed-id" || $0.name == "embed_id" })?.value
            }
        case "share":
            pendingShareChatId = url.pathComponents.last
            if let key = url.fragment { pendingShareKey = key }
        case "settings":
            pendingSettingsPath = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        case "app":
            pendingAppId = url.pathComponents.last
        case "inspiration":
            pendingInspirationId = url.pathComponents.last
        default:
            break
        }
    }

    private func handleUniversalLink(_ url: URL) {
        let selectedDomain = ServerConfiguration.current.selectedDomain
        if Self.isOtherProfileShare(url, selectedDomain: selectedDomain) {
            // Both app hosts claim public shares. Keep a link for the other
            // profile in its web recipient flow; never send it through the
            // selected account's API or switch the active server implicitly.
            pendingSharedBrowserURL = url
            return
        }
        guard Self.isSelectedWebURL(url, selectedDomain: selectedDomain) else { return }
        if url.path == "/s" || url.path.hasPrefix("/s/") {
            beginShortLinkResolution(url)
            return
        }
        if url.path.hasPrefix("/share/workflow-template/") {
            pendingWorkflowTemplate = Self.workflowTemplateLink(from: url,
                selectedDomain: ServerConfiguration.current.selectedDomain)
            return
        }
        let path = url.path
        let fragment = url.fragment ?? ""

        // Parse hash parameters (web app format)
        let params = parseFragment(fragment)
        if let route = WorkflowCompletionRoute.parse(params) {
            pendingWorkflowCompletion = route
            return
        }
        // A malformed completion link cannot fall through to ordinary chat
        // routing and skip the owner delivery claim.
        if params["workflow-id"] != nil || params["workflow_id"] != nil ||
           params["run-id"] != nil || params["run_id"] != nil {
            return
        }

        let normalizedFragment = fragment.hasPrefix("/") ? String(fragment.dropFirst()) : fragment
        if normalizedFragment == "tasks" { pendingTasksWorkspace = true }
        if let id = params["task-id"], UUID(uuidString: id) != nil { pendingTaskID = id }
        if normalizedFragment == "new-task" || normalizedFragment == "newtask" {
            pendingNewTask = true
        } else if normalizedFragment == "apps" || normalizedFragment.hasPrefix("apps/") {
            pendingAppsPath = String(normalizedFragment.dropFirst("apps".count))
                .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        }
        if normalizedFragment == "settings" || normalizedFragment.hasPrefix("settings/") {
            pendingSettingsPath = String(normalizedFragment.dropFirst("settings".count))
                .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        } else if let settings = params["settings"] {
            pendingSettingsPath = settings.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        }
        if normalizedFragment.hasPrefix("message="),
           let text = String(normalizedFragment.dropFirst("message=".count)).removingPercentEncoding {
            // Imported text is a draft, never permission to submit a message.
            pendingMessageText = text
        }

        if let chatId = params["chat-id"] ?? params["chat_id"] ?? params["chatid"] {
            pendingChatId = chatId
            pendingMessageId = params["message-id"]
            pendingEmbedId = params["embed-id"] ?? params["embed_id"]
        } else if let shareChatId = params["share-chat-id"] {
            pendingShareChatId = shareChatId
            pendingShareKey = params["key"]
        } else if let pairToken = params["pair-login"] {
            pendingPairToken = pairToken
        } else if let pairToken = params["pair"] {
            pendingPairToken = pairToken
        }

        // Path-based routing
        if path.hasPrefix("/share/chat/") {
            pendingShareChatId = String(path.dropFirst("/share/chat/".count))
        } else if path.hasPrefix("/share/embed/") {
            // Embed share - open in browser for now
        } else if path == "/new-chat" || path == "/newchat" {
            pendingNewChat = true
        } else if path == "/tasks" {
            pendingTasksWorkspace = true
        } else if path.hasPrefix("/task/"), url.pathComponents.count == 3,
                  let id = url.pathComponents.last, UUID(uuidString: id) != nil {
            pendingTaskID = id
        } else if path == "/new-task" || path == "/newtask" {
            pendingNewTask = true
        } else if path == "/apps" || path.hasPrefix("/apps/") {
            pendingAppsPath = String(path.dropFirst("/apps".count))
                .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        } else if path == "/search" {
            pendingSearch = true
        } else if path == "/settings" || path.hasPrefix("/settings/") {
            pendingSettingsPath = String(path.dropFirst("/settings".count))
                .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        } else if path == "/" && fragment.isEmpty {
            pendingNewChat = true
        } else if path.hasPrefix("/pair") {
            // /pair?code=TOKEN or /pair/TOKEN
            if let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
               let code = components.queryItems?.first(where: { $0.name == "code" })?.value {
                pendingPairToken = code
            } else {
                let token = String(path.dropFirst("/pair/".count))
                if !token.isEmpty { pendingPairToken = token }
            }
        } else if path.hasPrefix("/legal/") {
            pendingSettingsPath = "legal"
        }
    }

    private func beginShortLinkResolution(_ url: URL) {
        let profile = ServerProfile.current()
        guard let link = ShortShareLink.parse(url, selectedDomain: profile.displayDomain) else {
            pendingShortLinkError = true
            return
        }
        let generation = shortLinkGeneration
        let scopeID = OfflineStore.shared.activeScopeId
        let scopeGeneration = OfflineStore.shared.scopeGeneration
        let resolver = shortLinkResolver
        shortLinkResolutionTask = Task { @MainActor [weak self] in
            do {
                let target = try await resolver(link, profile)
                try Task.checkCancellation()
                guard let self, self.shortLinkGeneration == generation,
                      ServerProfile.current() == profile,
                      OfflineStore.shared.activeScopeId == scopeID,
                      OfflineStore.shared.scopeGeneration == scopeGeneration else { return }
                // The default Workflow share URL is encrypted twice. Resolve
                // its outer key locally, then use the existing strict parser.
                if let template = Self.workflowTemplateLink(from: target,
                    selectedDomain: profile.displayDomain) {
                    self.pendingWorkflowTemplate = template
                } else if Self.isNativeChatShareURL(target) {
                    self.pendingSharedChatURL = url
                } else if Self.isBrowserShareTarget(target, selectedDomain: profile.displayDomain) {
                    // Chat and embed recipients retain the web share flow. Show
                    // the original encrypted URL inside the app so Universal
                    // Links cannot reopen the app in a loop.
                    self.pendingSharedBrowserURL = url
                } else {
                    self.pendingShortLinkError = true
                }
            } catch is CancellationError {
                return
            } catch {
                guard let self, self.shortLinkGeneration == generation,
                      ServerProfile.current() == profile,
                      OfflineStore.shared.activeScopeId == scopeID,
                      OfflineStore.shared.scopeGeneration == scopeGeneration else { return }
                self.pendingShortLinkError = true
            }
        }
    }

    private static func resolveShortLink(_ link: ShortShareLink, profile: ServerProfile) async throws -> URL {
        struct Response: Decodable { let encrypted_url: String }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: link.requestURL(apiBaseURL: profile.apiBaseURL),
                                 cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        request.httpShouldHandleCookies = false
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              data.count <= 131_072 else { throw ShareLinkCryptoError.invalidShortURL }
        let body = try JSONDecoder().decode(Response.self, from: data)
        return try await ShareLinkCrypto.decryptShortURL(body.encrypted_url,
            token: link.token, shortKey: link.fragmentKey)
    }

    private func invalidateShortLinkResolution() {
        shortLinkGeneration = UUID()
        shortLinkResolutionTask?.cancel()
        shortLinkResolutionTask = nil
    }

    private func parseFragment(_ fragment: String) -> [String: String] {
        var params: [String: String] = [:]
        let normalized = fragment.hasPrefix("/") ? String(fragment.dropFirst()) : fragment
        let pairs = normalized.split(separator: "&")
        for pair in pairs {
            let parts = pair.split(separator: "=", maxSplits: 1)
            if parts.count == 2 {
                let key = String(parts[0])
                let value = String(parts[1]).removingPercentEncoding ?? String(parts[1])
                params[key] = value
            }
        }
        return params
    }

    static func workflowTemplateLink(from url: URL, selectedDomain: String) -> WorkflowTemplateLink? {
        guard url.scheme == "https", url.host?.lowercased() == selectedDomain.lowercased(),
              url.user == nil, url.password == nil, url.port == nil,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        let path = url.pathComponents
        guard path.count == 4, path[1] == "share", path[2] == "workflow-template",
              path[3].range(of: "^[A-Za-z0-9_-]{1,128}$", options: .regularExpression) != nil else { return nil }
        let keys = (components.fragment ?? "").split(separator: "&").compactMap { part -> String? in
            let pair = part.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2, pair[0] == "key" else { return nil }
            return String(pair[1]).removingPercentEncoding
        }
        guard keys.count == 1, let key = keys.first,
              key.range(of: "^[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil else { return nil }
        return WorkflowTemplateLink(templateID: path[3], fragmentKey: key, webDomain: selectedDomain)
    }

    static func shouldHandleInApp(_ url: URL, selectedDomain: String) -> Bool {
        isNativeChatShareURL(url) || ShortShareLink.parse(url, selectedDomain: selectedDomain) != nil ||
            workflowTemplateLink(from: url, selectedDomain: selectedDomain) != nil
    }

    static func isNativeChatShareURL(_ url: URL) -> Bool {
        guard url.scheme == "https", url.user == nil, url.password == nil, url.port == nil,
              let host = url.host?.lowercased(),
              ["openmates.org", "app.openmates.org", "app.dev.openmates.org"].contains(host) else { return false }
        let parts = url.pathComponents
        return parts.count == 4 && parts[1] == "share" && parts[2] == "chat"
            && parts[3].range(of: "^[A-Za-z0-9_-]{1,128}$", options: .regularExpression) != nil
    }

    static func shouldInterceptShareURL(_ url: URL, selectedDomain: String) -> Bool {
        shouldHandleInApp(url, selectedDomain: selectedDomain) ||
            isOtherProfileShare(url, selectedDomain: selectedDomain)
    }

    static func shouldInterceptAppURL(_ url: URL, selectedDomain: String) -> Bool {
        if shouldInterceptShareURL(url, selectedDomain: selectedDomain) { return true }
        if url.scheme == "openmates" {
            return ["new-chat", "newchat", "new-task", "newtask", "tasks", "task", "apps", "search", "chat", "active-chats", "control-project", "projects", "run-workflow", "workflows", "share", "settings", "app", "inspiration"]
                .contains(url.host ?? "")
        }
        guard isSelectedWebURL(url, selectedDomain: selectedDomain) else { return false }
        let path = url.path
        if ["/new-chat", "/newchat", "/new-task", "/newtask", "/tasks", "/apps", "/search", "/settings"].contains(path)
            || path.hasPrefix("/task/") || path.hasPrefix("/apps/") || path.hasPrefix("/settings/") || path.hasPrefix("/pair/")
            || path.hasPrefix("/share/chat/") { return true }
        // Marketing and documentation paths stay in the website. App hash
        // destinations are rooted in the selected web app, never foreign hosts.
        guard path.isEmpty || path == "/" else { return false }
        let fragment = (url.fragment ?? "").trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if ["new-task", "newtask", "tasks", "apps"].contains(fragment) || fragment.hasPrefix("apps/") { return true }
        if fragment.isEmpty || fragment == "settings" || fragment.hasPrefix("settings/") { return true }
        return ["task-id=", "workflow-id=", "chat-id=", "chat_id=", "chatid=", "share-chat-id=", "message=", "pair=", "pair-login=", "settings="]
            .contains { fragment.hasPrefix($0) }
    }

    private static func isOtherProfileShare(_ url: URL, selectedDomain: String) -> Bool {
        guard let host = url.host?.lowercased(), host != selectedDomain.lowercased(),
              ["openmates.org", "app.openmates.org", "app.dev.openmates.org"].contains(host) else { return false }
        return shouldHandleInApp(url, selectedDomain: host)
    }

    private static func isSelectedWebURL(_ url: URL, selectedDomain: String) -> Bool {
        url.scheme == "https" && url.host?.lowercased() == selectedDomain.lowercased() &&
            url.user == nil && url.password == nil && url.port == nil
    }

    private static func isBrowserShareTarget(_ url: URL, selectedDomain: String) -> Bool {
        guard isSelectedWebURL(url, selectedDomain: selectedDomain) else { return false }
        let parts = url.pathComponents
        if parts.count == 4, parts[1] == "share", ["chat", "embed"].contains(parts[2]) {
            return parts[3].range(of: "^[A-Za-z0-9_-]{1,128}$", options: .regularExpression) != nil
        }
        // Existing chat shares also use root hash routing.
        guard url.path == "/" || url.path.isEmpty,
              let fragment = url.fragment else { return false }
        return fragment.split(separator: "&").contains { part in
            let pair = part.split(separator: "=", maxSplits: 1)
            return pair.count == 2 && pair[0] == "share-chat-id" &&
                pair[1].range(of: "^[A-Za-z0-9_-]{1,128}$", options: .regularExpression) != nil
        }
    }

    func clearPending() {
        invalidateShortLinkResolution()
        pendingShortLinkError = false
        pendingSharedBrowserURL = nil
        pendingSharedChatURL = nil
        pendingChatId = nil
        pendingActiveChatsWidgetLink = nil
        pendingEmbedId = nil
        pendingMessageId = nil
        pendingShareChatId = nil
        pendingShareKey = nil
        pendingSettingsPath = nil
        pendingAppId = nil
        pendingPairToken = nil
        pendingInspirationId = nil
        pendingMessageText = nil
        pendingWorkflowTemplate = nil
        pendingWorkflowWidgetRun = nil
        pendingProjectID = nil
        pendingWorkflowID = nil
        pendingWorkflowCompletion = nil
        pendingWorkflowsWorkspace = false
        pendingControlProject = nil
        pendingProjectsWorkspace = false
        pendingTasksWorkspace = false
        pendingTaskID = nil
        pendingNewTask = false
        pendingAppsPath = nil
        pendingNewChat = false
        pendingSearch = false
    }
}
