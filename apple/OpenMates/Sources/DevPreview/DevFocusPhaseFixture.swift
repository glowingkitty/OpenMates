// Deterministic native phase display data. Never starts an inference request.
import SwiftUI
import CryptoKit

#if DEBUG
enum DevFocusPhaseFixture {
    static let chatID = "22222222-2222-4222-8222-222222222222"
    static let projectID = "44444444-4444-4444-8444-444444444444"
    static let instructions = """
    ---
    phases_version: 1
    phases:
      - id: understand
        title: Understand your situation
        instructions: Ask one question at a time. The user may skip or batch questions.
        requirements:
          - id: context
            text: Enough context or an explicit request to proceed.
      - id: confirm_profile
        title: Confirm your career profile
        instructions: Summarize the profile and ask the user to confirm.
        requirements:
          - id: approved
            text: The user confirms the career profile.
            type: user_confirmation
      - id: explore
        title: Explore career directions
        instructions: Research plausible career directions and explain assumptions.
        requirements:
          - id: selected
            text: The user selects a direction.
      - id: next_steps
        title: Plan your next steps
        instructions: Agree on practical next steps.
        requirements:
          - id: plan
            text: A practical plan is available.
    ---
    Global synthetic focus instruction.
    """
    static func projectResponse(path: String, accountID: String) async throws -> Data {
        guard accountID == "ui-test-chat-navigation-user" else { throw CancellationError() }
        let key = SymmetricKey(data: Data(repeating: 0x51, count: 32))
        // The opt-in account settings fixture uses a synthetic identity. Keep
        // key material isolated under that identity and never read real files.
        let existingMaster = try await CryptoManager.shared.loadMasterKey(for: accountID)
        let master = existingMaster ?? SymmetricKey(data: Data(repeating: 0x52, count: 32))
        if existingMaster == nil { try await CryptoManager.shared.saveMasterKey(master, for: accountID) }
        let body: [String: Any]
        if path.hasSuffix("/sources") {
            body = ["sources": []]
        } else if path.hasSuffix("/settings") {
            let settings = ["default_focus": ["instructions": instructions]]
            let plaintext = String(decoding: try JSONSerialization.data(withJSONObject: settings), as: UTF8.self)
            body = ["settings": ["encrypted_settings": try await CryptoManager.shared.encryptContent(plaintext, key: key)]]
        } else {
            body = ["projects": [["project_id": projectID,
                "encrypted_project_key": try await CryptoManager.shared.wrapChatKey(key, masterKey: master),
                "encrypted_name": try await CryptoManager.shared.encryptContent("Synthetic phase Project", key: key)]]]
        }
        return try JSONSerialization.data(withJSONObject: body)
    }

    static func event(project: Bool = false, chatID: String? = nil) -> FocusPhaseEvent {
        FocusPhaseEvent(type: "focus_phase_changed",
            eventId: project ? "55555555-5555-4555-8555-555555555555" : "11111111-1111-4111-8111-111111111111",
            chatId: chatID ?? Self.chatID, focusId: "weather-travel_weather", runId: "33333333-3333-4333-8333-333333333333",
            version: 2, previousPhaseId: "understand", phaseId: "confirm_profile",
            phaseTitle: "Confirm your career profile", direction: project ? "backward" : "forward",
            createdAt: 1, projectId: project ? projectID : nil)
    }
}

// Explicit opt-in observation of the production encrypted snapshot. This probe
// only reads/decrypts the current chat and never creates or advances state.
struct DevFocusPhaseStateProbe: View {
    let chatID: String?
    let ciphertext: String?
    @State private var snapshot = "unavailable"
    var body: some View {
        Text(snapshot).font(.system(size: 1)).frame(width: 1, height: 1)
            .accessibilityIdentifier("focus-phase-state-probe")
            .task(id: "\(chatID ?? ""):\(ciphertext ?? "")") {
                snapshot = "unavailable"
                guard let chatID, let ciphertext, let key = ChatKeyManager.shared.key(for: chatID),
                      let text = try? await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key),
                      let data = text.data(using: .utf8) else { return }
                let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
                guard let states = try? decoder.decode([String: FocusPhaseState].self, from: data) else { return }
                snapshot = states.values.sorted { $0.focusId < $1.focusId }.map { state in
                    "chat=\(chatID);focus=\(state.focusId);phase=\(state.phaseId);version=\(state.version);receipts=\(state.transitions.map(\.eventId).joined(separator: ","))"
                }.joined(separator: "|")
            }
    }
}
#endif
