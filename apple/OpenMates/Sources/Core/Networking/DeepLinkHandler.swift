// Deep link handler — processes openmates:// URLs and universal links.
// Supports: chat-id, message-id, share links, settings deep links, app links.
// Mirrors the web app's hash-based routing (#chat-id=X, #share-chat-id=X).

import Foundation
import SwiftUI

@MainActor
final class DeepLinkHandler: ObservableObject {
    @Published var pendingChatId: String?
    @Published var pendingMessageId: String?
    @Published var pendingShareChatId: String?
    @Published var pendingShareKey: String?
    @Published var pendingSettingsPath: String?
    @Published var pendingAppId: String?
    @Published var pendingPairToken: String?
    @Published var pendingInspirationId: String?

    func handle(url: URL) {
        if url.scheme == "openmates" {
            handleCustomScheme(url)
        } else {
            handleUniversalLink(url)
        }
    }

    private func handleCustomScheme(_ url: URL) {
        guard let host = url.host else { return }

        switch host {
        case "chat":
            pendingChatId = url.pathComponents.last
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
        let path = url.path
        let fragment = url.fragment ?? ""

        // Parse hash parameters (web app format)
        let params = parseFragment(fragment)

        if let chatId = params["chat-id"] {
            pendingChatId = chatId
            pendingMessageId = params["message-id"]
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

    private func parseFragment(_ fragment: String) -> [String: String] {
        var params: [String: String] = [:]
        let pairs = fragment.split(separator: "&")
        for pair in pairs {
            let parts = pair.split(separator: "=", maxSplits: 1)
            if parts.count == 2 {
                params[String(parts[0])] = String(parts[1])
            }
        }
        return params
    }

    func clearPending() {
        pendingChatId = nil
        pendingMessageId = nil
        pendingShareChatId = nil
        pendingShareKey = nil
        pendingSettingsPath = nil
        pendingAppId = nil
        pendingPairToken = nil
        pendingInspirationId = nil
    }
}
