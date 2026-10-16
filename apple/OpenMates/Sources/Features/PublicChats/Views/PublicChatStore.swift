// Public chat store — loads and caches intro, example, legal, and newsletter chats.
// Fetches from the backend API and provides categorized access.

import Foundation
import SwiftUI

@MainActor
final class PublicChatStore: ObservableObject {
    @Published var introChats: [DemoChat] = []
    @Published var exampleChats: [DemoChat] = []
    @Published var legalChats: [DemoChat] = []
    @Published var announcementChats: [DemoChat] = []
    @Published var tipsChats: [DemoChat] = []
    @Published var isLoading = false

    private let api = APIClient.shared

    var allPublicChats: [DemoChat] {
        introChats + exampleChats + announcementChats + tipsChats
    }

    func loadAll() async {
        isLoading = true

        async let examples = loadCategory("example")
        async let legals = loadCategory("legal")
        async let announcements = loadCategory("announcement")
        async let tips = loadCategory("tips")

        introChats = []
        exampleChats = await examples
        legalChats = await legals
        announcementChats = await announcements
        tipsChats = await tips

        isLoading = false
    }

    func loadCategory(_ category: String) async -> [DemoChat] {
        guard category != "intro" else { return [] }
        do {
            let chats: [DemoChat] = try await api.request(.get, path: "/v1/public/chats/\(category)")
            return chats.filter { !RetiredIntroChatPolicy.excludes($0.chatId) }
        } catch {
            print("[PublicChats] Failed to load \(category): \(error)")
            return []
        }
    }

    func chat(for slug: String) -> DemoChat? {
        allPublicChats.first { $0.slug == slug }
            ?? legalChats.first { $0.slug == slug }
    }
}
