// Draft service — auto-saves message drafts per chat to UserDefaults.
// Mirrors the web app's draftService.ts: debounced save on every keystroke,
// restores draft when re-opening a chat, clears on send.

import Foundation
import Combine

@MainActor
final class DraftService: ObservableObject {
    static let shared = DraftService()

    @Published private(set) var currentDraft: String = ""

    private var currentChatId: String?
    private var saveTask: Task<Void, Never>?
    private let debounceInterval: TimeInterval = 0.5
    private let storageKey = "openmates.drafts"

    private init() {}

    // MARK: - Load draft for a chat

    func loadDraft(chatId: String) -> String {
        currentChatId = chatId
        let draft = allDrafts()[chatId] ?? ""
        currentDraft = draft
        return draft
    }

    // MARK: - Update draft (debounced save)

    func updateDraft(_ text: String, chatId: String) {
        currentDraft = text
        currentChatId = chatId

        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(Int(debounceInterval * 1000)))
            guard !Task.isCancelled else { return }
            saveDraft(text, chatId: chatId)
        }
    }

    // MARK: - Clear draft (on send or explicit clear)

    func clearDraft(chatId: String) {
        currentDraft = ""
        var drafts = allDrafts()
        drafts.removeValue(forKey: chatId)
        UserDefaults.standard.set(drafts, forKey: storageKey)
    }

    // MARK: - Check if draft exists

    func hasDraft(chatId: String) -> Bool {
        guard let draft = allDrafts()[chatId] else { return false }
        return !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    // MARK: - List all chats with drafts

    func chatIdsWithDrafts() -> [String] {
        allDrafts().filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }.map(\.key)
    }

    // MARK: - Clear all drafts (on logout)

    func clearAll() {
        UserDefaults.standard.removeObject(forKey: storageKey)
        currentDraft = ""
        currentChatId = nil
    }

    // MARK: - Private

    private func saveDraft(_ text: String, chatId: String) {
        var drafts = allDrafts()
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            drafts.removeValue(forKey: chatId)
        } else {
            drafts[chatId] = text
        }
        UserDefaults.standard.set(drafts, forKey: storageKey)
    }

    private func allDrafts() -> [String: String] {
        UserDefaults.standard.dictionary(forKey: storageKey) as? [String: String] ?? [:]
    }
}
