// Public chat browser — shows intro, example, announcement, and tips chats.
// Shown from the main app's "Explore" tab or from the sidebar.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/+page.svelte (explore/public chats)
//          frontend/packages/ui/src/components/ChatHistory.svelte (chat list)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

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
                        icon: "ai",
                        chats: store.introChats
                    )
                }

                if !store.exampleChats.isEmpty {
                    chatSection(
                        title: "Example Conversations",
                        icon: "messages",
                        chats: store.exampleChats
                    )
                }

                if !store.announcementChats.isEmpty {
                    chatSection(
                        title: "Announcements",
                        icon: "mail",
                        chats: store.announcementChats
                    )
                }

                if !store.tipsChats.isEmpty {
                    chatSection(
                        title: "Tips & Tricks",
                        icon: "ai",
                        chats: store.tipsChats
                    )
                }
            }
            .padding(.horizontal, .spacing6)
            .padding(.vertical, .spacing4)
        }
        .task { await store.loadAll() }
        .overlay {
            if showChatDetail, let chat = selectedChat {
                ZStack {
                    Color.black.opacity(0.35)
                        .ignoresSafeArea()
                        .onTapGesture {
                            showChatDetail = false
                        }

                    VStack(spacing: 0) {
                        HStack {
                            Text(chat.title)
                                .font(.omH3)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontPrimary)
                                .lineLimit(1)
                            Spacer()
                            OMIconButton(icon: "close", label: AppStrings.close, size: 34) {
                                showChatDetail = false
                            }
                        }
                        .padding(.spacing6)

                        PublicChatDetailView(chat: chat)
                    }
                    .frame(maxWidth: 760, maxHeight: 760)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .overlay(
                        RoundedRectangle(cornerRadius: .radius8)
                            .stroke(Color.grey20, lineWidth: 1)
                    )
                    .padding(.spacing8)
                }
            }
        }
    }

    private func chatSection(title: String, icon: String, chats: [DemoChat]) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing3) {
                Icon(icon, size: 18)
                    .foregroundStyle(Color.fontSecondary)
                Text(title)
                    .font(.omH4)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
            }

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

    var body: some View {
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

                        InlineMarkdownText(content: message.content, isUserMessage: message.role == "user")
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
    }
}
