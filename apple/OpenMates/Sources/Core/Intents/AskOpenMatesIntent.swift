// "Ask OpenMates" Shortcut — sends a message to a new chat and returns the AI response.
// This is the primary Siri / Shortcuts integration: "Hey Siri, ask OpenMates..."
// Creates a new chat, sends the user's question, waits for the streaming response
// to complete, and returns the full answer as a string result.

import AppIntents
import Foundation

struct AskOpenMatesIntent: AppIntent {
    static let title: LocalizedStringResource = "Ask OpenMates"
    static let description: IntentDescription = "Send a question to OpenMates AI and get a response."
    static let openAppWhenRun = false

    @Parameter(title: "Question", description: "What would you like to ask?")
    var question: String

    @Parameter(title: "App", description: "Which app to use (e.g., ai, web, code, travel)", default: "ai")
    var appId: String

    static var parameterSummary: some ParameterSummary {
        Summary("Ask OpenMates \(\.$question)") {
            \.$appId
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let chatId = UUID().uuidString
        let messageId = UUID().uuidString

        let body: [String: Any] = [
            "chat_id": chatId,
            "message": [
                "message_id": messageId,
                "role": "user",
                "content": question,
                "created_at": Int(Date().timeIntervalSince1970),
                "chat_has_title": false
            ] as [String: Any]
        ]

        // Send the message — the response streams via WebSocket, but we poll
        // the REST endpoint for the completed assistant response.
        let _: Data = try await APIClient.shared.request(
            .post, path: "/v1/chat/message", body: body
        )

        // Poll for the assistant response (streaming completes server-side)
        let response = try await pollForResponse(chatId: chatId, maxAttempts: 30)
        return .result(value: response)
    }

    /// Polls the chat messages endpoint until an assistant response appears.
    private func pollForResponse(chatId: String, maxAttempts: Int) async throws -> String {
        for attempt in 0..<maxAttempts {
            // Wait progressively longer between attempts
            let delay = attempt < 5 ? 1.0 : 2.0
            try await Task.sleep(for: .seconds(delay))

            let messages: [ShortcutMessage] = try await APIClient.shared.request(
                .get, path: "/v1/chats/\(chatId)/messages"
            )

            if let assistant = messages.last(where: { $0.role == "assistant" }),
               let content = assistant.content,
               !content.isEmpty {
                return content
            }
        }

        return "Response is still processing. Open the app to see the full answer."
    }
}

/// Lightweight message model for Shortcuts (avoids importing full ChatModels).
private struct ShortcutMessage: Decodable {
    let id: String
    let role: String
    let content: String?
}
