// Chat search — full-text search across all chats.
// Mirrors the web app's SearchBar and searchService.

import SwiftUI

struct ChatSearchView: View {
    @State private var query = ""
    @State private var results: [ChatSearchResult] = []
    @State private var isSearching = false
    @Environment(\.dismiss) var dismiss
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @FocusState private var isFocused: Bool

    let onSelectChat: (String) -> Void

    struct ChatSearchResult: Identifiable, Decodable {
        let id: String
        let chatId: String
        let chatTitle: String?
        let messagePreview: String?
        let matchType: String?
        let createdAt: String?
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                HStack(spacing: .spacing3) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityHidden(true)
                    TextField("Search chats and messages...", text: $query)
                        .font(.omP)
                        .focused($isFocused)
                        .onSubmit { search() }
                        .onChange(of: query) { _, newValue in
                            if newValue.count >= 2 { search() }
                            else { results.removeAll() }
                        }
                        .accessibleInput("Search chats and messages", hint: "Type at least 2 characters to search")
                    if !query.isEmpty {
                        Button { query = ""; results.removeAll() } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(Color.fontTertiary)
                        }
                        .accessibleButton("Clear search", hint: "Clears the search field and results")
                    }
                }
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing3)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing3)

                Divider()

                if isSearching {
                    ProgressView()
                        .padding(.top, .spacing8)
                        .accessibilityLabel("Searching")
                    Spacer()
                } else if results.isEmpty && !query.isEmpty {
                    VStack(spacing: .spacing4) {
                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 36))
                            .foregroundStyle(Color.fontTertiary)
                            .accessibilityHidden(true)
                        Text(LocalizationManager.shared.text("chats.search.no_results"))
                            .font(.omP).foregroundStyle(Color.fontSecondary)
                    }
                    .padding(.top, .spacing16)
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("No results found")
                    Spacer()
                } else {
                    List {
                        ForEach(results) { result in
                            Button {
                                onSelectChat(result.chatId)
                                dismiss()
                            } label: {
                                VStack(alignment: .leading, spacing: .spacing2) {
                                    Text(result.chatTitle ?? "Chat")
                                        .font(.omSmall).fontWeight(.medium)
                                        .foregroundStyle(Color.fontPrimary)
                                    if let preview = result.messagePreview {
                                        Text(preview)
                                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                                            .lineLimit(2)
                                    }
                                }
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("\(result.chatTitle ?? "Chat")\(result.messagePreview.map { ", \($0)" } ?? "")")
                            .accessibilityHint("Opens this chat")
                            .accessibilityAddTraits(.isButton)
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Search")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .onAppear { isFocused = true }
    }

    private func search() {
        guard query.count >= 2 else { return }
        isSearching = true
        AccessibilityAnnouncement.announce("Searching for \(query)")

        Task {
            do {
                results = try await APIClient.shared.request(
                    .post, path: "/v1/chats/search",
                    body: ["query": query, "limit": 20]
                )
                AccessibilityAnnouncement.announce(results.isEmpty ? "No results found" : "\(results.count) result\(results.count == 1 ? "" : "s") found")
            } catch {
                print("[Search] Error: \(error)")
            }
            isSearching = false
        }
    }
}
