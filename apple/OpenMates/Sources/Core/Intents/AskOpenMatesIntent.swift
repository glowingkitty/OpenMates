// "Ask OpenMates" Shortcut — sends a message to a new chat and returns the AI response.
// This is the primary Siri / Shortcuts integration: "Hey Siri, ask OpenMates..."
// The send runs through the shared client core (`CoreChatActions`), which streams,
// persists and post-processes the chat; the intent returns the core's reply text.

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
        let response = try await performChatRequest()
        return .result(value: response)
    }

    /// User-facing results. The turn itself (send, stream, persistence and
    /// post-processing) runs in the client core; the intent only reads its end.
    enum Message {
        static let signIn = "Open OpenMates and sign in before using this shortcut."
        static let notConnected = "OpenMates could not connect. Open the app and try again."
        static let stillProcessing = "Response is still processing. Open the app to see the full answer."
        static func failed(_ reason: String) -> String { "OpenMates could not finish the response: \(reason)" }
    }

    /// Seconds the shortcut waits for the core's reply before pointing to the app.
    static let replyTimeoutSeconds = 180

    /// The shortcut result for how the core ended the turn (`nil`: no end arrived in time).
    @MainActor
    static func result(forEnd end: CoreTurnEnd?) -> String {
        guard let end else { return Message.stillProcessing }
        switch end.outcome {
        case .completed:
            guard let reply = end.replyText, !reply.isEmpty else { return Message.stillProcessing }
            return reply
        case .failed(let error):
            return Message.failed(CoreSession.errorClass(error))
        case .cancelled:
            return Message.stillProcessing
        }
    }

    /// The shortcut result for a turn the core did not admit (`.accepted` has none).
    @MainActor
    static func result(forRefusal acceptance: CoreTurnAcceptance) -> String? {
        switch acceptance {
        case .accepted: return nil
        case .rejected(let error): return Message.failed(CoreSession.errorClass(error))
        case .cancelled, .noCore: return Message.notConnected
        }
    }

    /// The core exists from app start (`OpenMatesApp.init`); this repeats the same
    /// launch calls when the intent runs before them (each is a no-op once done).
    @MainActor
    private func readyCore() async -> CoreSession? {
        CoreSession.launch()
        if !CoreChatWindow.shared.isAttached { CoreChatWindow.launch() }
        if !CoreChatActions.shared.isAttached { CoreChatActions.launch() }
        guard let session = CoreSession.shared else { return nil }
        if session.state == .notStarted {
            try? await session.start()
        } else {
            await session.settled()
        }
        return session
    }

    @MainActor
    private func performChatRequest() async throws -> String {
        guard let session = await readyCore() else { return Message.notConnected }
        switch session.state {
        case .admitted, .restored: break
        case .notStarted, .starting, .failed: return Message.notConnected
        case .signedOut, .expired, .accessDenied, .verificationRequired: return Message.signIn
        }

        let chatId = UUID().uuidString.lowercased()
        let options = CoreSendMapping.options(reservedChatId: chatId)
        let (ends, endContinuation) = AsyncStream.makeStream(of: CoreTurnEnd.self)
        let acceptance = await CoreChatActions.shared.startTurn(
            .send(text: question, options: options), chatId: nil
        ) { end in
            endContinuation.yield(end)
            endContinuation.finish()
        }
        if let refusal = Self.result(forRefusal: acceptance) {
            endContinuation.finish()
            return refusal
        }
        let timeout = Task {
            try? await Task.sleep(for: .seconds(Self.replyTimeoutSeconds))
            endContinuation.finish()
        }
        defer { timeout.cancel() }
        var end: CoreTurnEnd?
        for await value in ends { end = value }
        return Self.result(forEnd: end)
    }
}
