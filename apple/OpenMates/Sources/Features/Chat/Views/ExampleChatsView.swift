// Example chats browser — displays curated example conversations users can preview and clone.
// Mirrors the web app's example-chats-load and example-chat-clone flows:
// list examples, preview messages with embeds, and clone-on-send to create a real chat.

import SwiftUI

struct ExampleChat: Identifiable, Decodable {
    let id: String
    let title: String
    let description: String?
    let appId: String?
    let messageCount: Int?
    let previewMessages: [ExampleMessage]?
    let category: String?

    struct ExampleMessage: Identifiable, Decodable {
        let id: String
        let role: String
        let content: String
        let embedRefs: [EmbedRef]?
    }
}

// MARK: - Example chat list

struct ExampleChatsListView: View {
    @State private var examples: [ExampleChat] = []
    @State private var isLoading = true
    @State private var selectedExample: ExampleChat?
    @State private var error: String?
    let onClone: (String) -> Void

    var body: some View {
        Group {
            if isLoading {
                ProgressView("Loading examples...")
            } else if examples.isEmpty {
                ContentUnavailableView(
                    "No Examples",
                    systemImage: "text.bubble",
                    description: Text(LocalizationManager.shared.text("activity.examples"))
                )
            } else {
                List(examples) { example in
                    ExampleChatRow(example: example)
                        .contentShape(Rectangle())
                        .onTapGesture { selectedExample = example }
                }
            }
        }
        .navigationTitle("Example Chats")
        .sheet(item: $selectedExample) { example in
            ExampleChatPreviewView(example: example, onClone: onClone)
        }
        .task { await loadExamples() }
    }

    private func loadExamples() async {
        do {
            examples = try await APIClient.shared.request(.get, path: "/v1/example-chats")
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}

// MARK: - Example chat row

struct ExampleChatRow: View {
    let example: ExampleChat

    var body: some View {
        HStack(spacing: .spacing4) {
            if let appId = example.appId {
                AppIconView(appId: appId, size: 36)
            }

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(example.title)
                    .font(.omSmall).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)

                if let description = example.description {
                    Text(description)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(2)
                }

                if let count = example.messageCount {
                    Text("\(count) messages")
                        .font(.omTiny)
                        .foregroundStyle(Color.fontTertiary)
                }
            }

            Spacer()

            Icon("back", size: 12)
                .scaleEffect(x: -1, y: 1)
                .foregroundStyle(Color.fontTertiary)
        }
        .padding(.vertical, .spacing2)
    }
}

// MARK: - Example chat preview with clone-on-send

struct ExampleChatPreviewView: View {
    let example: ExampleChat
    let onClone: (String) -> Void
    @Environment(\.dismiss) var dismiss
    @State private var userMessage = ""
    @State private var isCloning = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    LazyVStack(spacing: .spacing4) {
                        if let messages = example.previewMessages {
                            ForEach(messages) { message in
                                ExampleMessageBubble(message: message)
                            }
                        }
                    }
                    .padding(.spacing4)
                }

                Divider()

                HStack(alignment: .bottom, spacing: .spacing3) {
                    TextField("Type to clone and continue...", text: $userMessage, axis: .vertical)
                        .textFieldStyle(.plain)
                        .font(.omP)
                        .lineLimit(1...4)
                        .padding(.spacing4)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius5))

                    Button { cloneAndSend() } label: {
                        if isCloning {
                            ProgressView()
                                .frame(width: 32, height: 32)
                        } else {
                            Icon("up", size: 20)
                                .foregroundStyle(userMessage.isEmpty ? Color.fontTertiary : Color.fontButton)
                                .frame(width: 32, height: 32)
                                .background(userMessage.isEmpty ? Color.grey20 : Color.buttonPrimary)
                                .clipShape(Circle())
                        }
                    }
                    .disabled(userMessage.isEmpty || isCloning)
                }
                .padding(.spacing4)
            }
            .navigationTitle(example.title)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                }
            }
        }
    }

    private func cloneAndSend() {
        isCloning = true
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/example-chats/\(example.id)/clone",
                    body: ["message": userMessage]
                )
                if let newChatId = response["chat_id"]?.value as? String {
                    dismiss()
                    onClone(newChatId)
                }
            } catch {
                print("[ExampleChats] Clone error: \(error)")
            }
            isCloning = false
        }
    }
}

// MARK: - Example message bubble

struct ExampleMessageBubble: View {
    let message: ExampleChat.ExampleMessage

    var body: some View {
        HStack {
            if message.role == "user" { Spacer(minLength: 60) }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(message.content)
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
            }
            .padding(.spacing4)
            .background(message.role == "user" ? Color.buttonPrimary.opacity(0.1) : Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))

            if message.role != "user" { Spacer(minLength: 60) }
        }
    }
}
