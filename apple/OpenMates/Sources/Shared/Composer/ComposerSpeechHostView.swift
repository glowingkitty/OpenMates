import SwiftUI

// The same production control is mounted by saved-chat and welcome composers.
// No default fake dependencies: the app session configures the real runtime.
struct ComposerSpeechHostView: View {
    let chatID: String
    let supported: Bool
    @State private var ownerID = UUID()
    @State private var controller: NativeAssistantSpeech?
    var body: some View {
        ZStack {
            // A stable mounted node starts the activation task even before its
            // asynchronous controller exists; an empty conditional Group may not.
            Color.clear.frame(width: 0, height: 0).accessibilityHidden(true)
            if supported, let controller { ComposerSpeechControl(speech: controller) }
        }
        .onDisappear { AssistantSpeechAppRuntime.shared.deactivate(chatID: chatID, ownerID: ownerID, controller: controller) }
        .task(id: "\(chatID):\(supported):\(OfflineStore.shared.scopeGeneration)") {
            let value = await AssistantSpeechAppRuntime.shared.activate(chatID: chatID, supported: supported, ownerID: ownerID)
            guard !Task.isCancelled else { return }
            controller = value
        }
    }
}
