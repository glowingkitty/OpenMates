// Public chat browser — shows intro, example, announcement, and tips chats.
// Shown from the main app's "Explore" tab or from the sidebar.

import SwiftUI

struct PublicChatListView: View {
    @StateObject private var store = PublicChatStore()
    @State private var selectedChat: DemoChat?
    @State private var showChatDetail = false

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .spacing8) {
                if store.isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.top, .spacing16)
                }

                if !store.introChats.isEmpty {
                    chatSection(
                        title: "Welcome",
                        icon: "hand.wave",
                        chats: store.introChats
                    )
                }

                if !store.exampleChats.isEmpty {
                    chatSection(
                        title: "Example Conversations",
                        icon: "text.bubble",
                        chats: store.exampleChats
                    )
                }

                if !store.announcementChats.isEmpty {
                    chatSection(
                        title: "Announcements",
                        icon: "megaphone",
                        chats: store.announcementChats
                    )
                }

                if !store.tipsChats.isEmpty {
                    chatSection(
                        title: "Tips & Tricks",
                        icon: "lightbulb",
                        chats: store.tipsChats
                    )
                }
            }
            .padding(.horizontal, .spacing6)
            .padding(.vertical, .spacing4)
        }
        .navigationTitle("Explore")
        .task { await store.loadAll() }
        .sheet(isPresented: $showChatDetail) {
            if let chat = selectedChat {
                PublicChatDetailView(chat: chat)
            }
        }
    }

    private func chatSection(title: String, icon: String, chats: [DemoChat]) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Label(title, systemImage: icon)
                .font(.omH4)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(spacing: .spacing4) {
                    ForEach(chats) { chat in
                        PublicChatCard(chat: chat) {
                            selectedChat = chat
                            showChatDetail = true
                        }
                    }
                }
            }
        }
    }
}

struct PublicChatCard: View {
    let chat: DemoChat
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(chat.title)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                if let description = chat.description {
                    Text(description)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(3)
                        .multilineTextAlignment(.leading)
                }

                Spacer()

                if let category = chat.metadata?.category {
                    Text(category.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.omTiny)
                        .foregroundStyle(Color.fontTertiary)
                }
            }
            .padding(.spacing4)
            .frame(width: 200, height: 140, alignment: .topLeading)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
            .overlay(
                RoundedRectangle(cornerRadius: .radius4)
                    .stroke(Color.grey20, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Public chat detail (read-only conversation)

struct PublicChatDetailView: View {
    let chat: DemoChat
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: .spacing4) {
                    ForEach(chat.messages) { message in
                        VStack(alignment: .leading, spacing: .spacing2) {
                            HStack {
                                Text(message.role == "user" ? "You" : "OpenMates")
                                    .font(.omXs)
                                    .fontWeight(.bold)
                                    .foregroundStyle(Color.fontTertiary)
                                Spacer()
                            }

                            InlineMarkdownText(content: message.content ?? "", isUserMessage: message.role == "user")
                                .padding(.spacing4)
                                .background(
                                    message.role == "user"
                                        ? AnyShapeStyle(LinearGradient.primary)
                                        : AnyShapeStyle(Color.grey10)
                                )
                                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                        }
                    }
                }
                .padding(.spacing6)
            }
            .navigationTitle(chat.title)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
