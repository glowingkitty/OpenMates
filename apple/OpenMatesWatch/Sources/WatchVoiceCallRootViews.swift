// Compact Watch presentation of the approved shared call processing disclosure.
// Web: frontend/packages/ui/src/components/EnterMessage.svelte; styles/chat.css
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy.first-call-warning
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
import SwiftUI

@MainActor
private enum WatchCallRootCopy {
    static var title: String { WatchLocalization.text("voicecall.privacy_title") }
    static var description: String { WatchLocalization.text("voicecall.privacy_description") }
    static var accept: String { WatchLocalization.text("voicecall.privacy_continue") }
    static var terms: String { WatchLocalization.text("voicecall.privacy_terms") }
    static var cancel: String { WatchLocalization.text("common.cancel") }
    static func probe(_ suffix: String) -> String { WatchLocalization.text("watch.voice_probe." + suffix) }
}

struct WatchVoiceCallConsentView: View {
    @ObservedObject var consent: WatchVoiceCallConsent
    var body: some View {
        ScrollView {
            VStack(spacing: .spacing3) {
                Text(WatchCallRootCopy.title).font(.omSmall.weight(.semibold))
                Text(WatchCallRootCopy.description).font(.omXs)
                Link(WatchCallRootCopy.terms, destination: URL(string: "https://legal.mistral.ai/terms/privacy-policy")!)
                    .font(.omXs).foregroundStyle(Color.buttonPrimary)
                Button { consent.finish(true) } label: {
                    Text(WatchCallRootCopy.accept).font(.omSmall.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: .spacing8)
                        .background(LinearGradient.primary, in: Capsule())
                }.buttonStyle(.plain).accessibilityIdentifier("watch-voice-consent-accept")
                Button { consent.cancel() } label: {
                    Text(WatchCallRootCopy.cancel).font(.omSmall).frame(maxWidth: .infinity, minHeight: .spacing8)
                }.buttonStyle(.plain).accessibilityIdentifier("watch-voice-consent-cancel")
            }.padding(.spacing3)
        }
        .foregroundStyle(WatchWorkspacePalette.foreground)
        .background(WatchWorkspacePalette.background.ignoresSafeArea())
        .accessibilityIdentifier("watch-voice-consent")
    }
}

// Existing development Settings route now hosts explicit hardware and paid
// evaluation stages, while preserving the ordinary root's unavailable call gate.
struct WatchVoiceHardwareProbeView: View {
    @ObservedObject var auth: WatchAuthStore
    @ObservedObject var runtime: WatchChatRuntime
    @ObservedObject var consent: WatchVoiceCallConsent
    let close: () -> Void
    var body: some View {
        WatchVoiceEvaluationView(auth: auth, runtime: runtime, consent: consent, close: close)
    }
}

#if DEBUG
struct WatchVoiceCallConsentFixtureView: View {
    @StateObject private var consent = WatchVoiceCallConsent()
    @State private var finished = false
    var body: some View {
        ZStack {
            WatchWorkspacePalette.background.ignoresSafeArea()
            if consent.isPresented { WatchVoiceCallConsentView(consent: consent) }
            if finished {
                Text(WatchLocalization.text("common.done"))
                    .accessibilityIdentifier("watch-voice-consent-fixture-finished")
            }
        }.task { _ = await consent.request(); finished = true }
            .onDisappear { consent.cancel() }
    }
}
#endif
