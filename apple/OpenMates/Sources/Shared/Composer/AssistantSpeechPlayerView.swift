import SwiftUI

// Web source: frontend/packages/ui/src/components/AssistantSpeechPlayer.svelte
// Rendered contract: 82pt desktop / 92pt <=730pt, gradient-primary, 40pt controls.
// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
struct AssistantSpeechPlayerView: View {
    @ObservedObject var speech: NativeAssistantSpeech
    var viewportWidth: CGFloat = 390
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.width <= 730
            let previous = speech.playbackSegments.last { $0.kind != "app_use_announcement" && ($0.sequence ?? -1) >= 0 && ($0.sequence ?? -1) < speech.activeSequence }
            let next = speech.playbackSegments.first { $0.kind != "app_use_announcement" && ($0.sequence ?? -1) >= 0 && ($0.sequence ?? -1) > speech.activeSequence }
            let waveformWidth: CGFloat = compact ? 185 : previous == nil ? 220 : 300
            ZStack(alignment: .top) {
                LinearGradient.primary.allowsHitTesting(false)
                VStack(spacing: 0) {
                    HStack(spacing: 1) {
                        waveform(previous, active: false)
                        waveform(speech.activeSegment, active: true)
                        waveform(next, active: false)
                    }
                    .frame(width: min(waveformWidth, max(0, geometry.size.width - (compact ? 32 : 48))), height: compact ? 42 : 38)
                    .frame(height: compact ? 54 : 46, alignment: .top)
                    .allowsHitTesting(false)
                    .accessibilityIdentifier("assistant-speech-waveform")
                    HStack(spacing: compact ? .spacing2 : .spacing4) {
                        HStack(spacing: 3) {
                            Spacer(minLength: 0)
                            if let previous {
                                Button { speech.previous() } label: {
                                    HStack(spacing: 3) {
                                        if !compact { Text(speech.chapter(for: previous)).lineLimit(1).frame(maxWidth: 150).fixedSize(horizontal: true, vertical: false) }
                                        SpeechPlayerGlyph(kind: .previous).frame(width: 9, height: 9)
                                    }
                                }.buttonStyle(.plain).opacity(0.54)
                                    .accessibilityLabel("Previous chapter: \(speech.chapter(for: previous))")
                                    .accessibilityIdentifier("assistant-speech-previous-chapter")
                            }
                        }.frame(maxWidth: .infinity)
                        VStack(spacing: 1) {
                            Text(speech.chapter(for: speech.activeSegment)).fontWeight(.bold).lineLimit(1)
                                .accessibilityIdentifier("assistant-speech-current-chapter")
                            if speech.playbackStatus == .waitingForSegment {
                                Text(AppStrings.loading).modifier(AssistantSpeechLoadingShimmer())
                                    .accessibilityIdentifier("assistant-speech-loading")
                            } else if speech.playbackStatus == .failed {
                                Text(LocalizationManager.shared.text("chat.assistant_speech.unavailable")).lineLimit(1)
                                    .accessibilityIdentifier("assistant-speech-error")
                            }
                        }.frame(maxWidth: compact ? 170 : 210).fixedSize(horizontal: true, vertical: false)
                        HStack(spacing: 3) {
                            if let next {
                                Button { speech.next() } label: {
                                    HStack(spacing: 3) {
                                        SpeechPlayerGlyph(kind: .next).frame(width: 9, height: 9)
                                        if !compact { Text(speech.chapter(for: next)).lineLimit(1).frame(maxWidth: 150).fixedSize(horizontal: true, vertical: false) }
                                    }
                                }.buttonStyle(.plain).opacity(0.54)
                                    .accessibilityLabel("Next chapter: \(speech.chapter(for: next))")
                                    .accessibilityIdentifier("assistant-speech-next-chapter")
                            }
                            Spacer(minLength: 0)
                        }.frame(maxWidth: .infinity)
                    }.font(.omXxs).frame(height: compact ? 24 : 22)
                }.padding(.top, .spacing2).padding(.horizontal, compact ? .spacing4 : .spacing6)
                HStack(spacing: .spacing2) {
                    control(speech.canPause ? .pause : .play, id: "assistant-speech-primary-control",
                            label: speech.playbackStatus == .failed ? AppStrings.retry : speech.canPause ? "Pause voice response" : "Play voice response") {
                        if speech.canPause { speech.pause() } else { speech.play() }
                    }
                    if !speech.canPause {
                        control(.close, id: "assistant-speech-close", label: AppStrings.close) { Task { await speech.stop() } }
                    }
                }.padding(.top, compact ? 14 : 12)
                if !compact {
                    avatar.frame(width: 34, height: 34)
                        .allowsHitTesting(false)
                        .position(x: geometry.size.width / 2 - (previous == nil ? 78 : 173), y: 30)
                }
            }
            .foregroundStyle(Color.fontButton)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 1)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: speech.canPause)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Voice response player")
            .accessibilityValue(speech.playbackStatus.rawValue)
            .accessibilityIdentifier("assistant-speech-player")
        }.frame(height: viewportWidth <= 730 ? 92 : 82)
    }
    private func waveform(_ segment: AssistantSpeechSegment?, active: Bool) -> some View {
        let samples = segment?.segment_id.flatMap { speech.waveforms[$0] } ?? []
        return GeometryReader { geometry in
            HStack(spacing: 1) {
                ForEach(0..<32, id: \.self) { index in
                    let level = samples.isEmpty ? 8 : samples[Int((Double(index) / 31 * Double(samples.count - 1)).rounded())]
                    Capsule().frame(maxWidth: 2).frame(height: max(4, level) / 100 * geometry.size.height)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
                .opacity(active ? samples.isEmpty ? 0.55 : 1 : 0.42)
        }.frame(maxWidth: .infinity)
    }
    private func control(_ kind: SpeechPlayerGlyph.Kind, id: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            SpeechPlayerGlyph(kind: kind).frame(width: 18, height: 18)
                .foregroundStyle(Color.fontPrimary)
                .frame(width: 40, height: 40).background(Color.grey0).clipShape(Circle())
                // Plain custom Canvas buttons need a hit region independent of
                // the drawn glyph; the pause icon's center is an empty gap.
                .contentShape(Circle())
                .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 1)
        }.buttonStyle(.plain).accessibilityLabel(label).accessibilityIdentifier(id)
    }
    private var avatar: some View {
        let category = CategoryMapping.isKnownCategory(speech.mateCategory) ? speech.mateCategory : "general_knowledge"
        let image = AssistantSpeechMateImageCache.image(category)
        return Group {
            if let image { image.resizable().scaledToFill() }
                }.clipShape(Circle()).overlay(alignment: .bottomTrailing) {
            Icon("ai", size: 9).foregroundStyle(Color.fontPrimary).frame(width: 15, height: 15)
                .background(Color.grey0).clipShape(Circle()).offset(x: 3, y: 3)
        }.accessibilityLabel(speech.mateName).accessibilityIdentifier("assistant-speech-mate")
    }
}

// CSS pseudo-elements are custom geometry; avoid mismatched platform glyphs.
private struct SpeechPlayerGlyph: View {
    enum Kind { case play, pause, close, previous, next }
    let kind: Kind
    var body: some View {
        Canvas { context, size in
            var path = Path()
            switch kind {
            case .play:
                path.move(to: CGPoint(x: 5, y: 1)); path.addLine(to: CGPoint(x: 17, y: 9)); path.addLine(to: CGPoint(x: 5, y: 17)); path.closeSubpath()
                context.fill(path, with: .foreground)
            case .pause:
                path.addRoundedRect(in: CGRect(x: 2, y: 2, width: 5, height: 14), cornerSize: CGSize(width: 2.5, height: 2.5))
                path.addRoundedRect(in: CGRect(x: 11, y: 2, width: 5, height: 14), cornerSize: CGSize(width: 2.5, height: 2.5))
                context.fill(path, with: .foreground)
            case .close:
                path.move(to: CGPoint(x: 4, y: 4)); path.addLine(to: CGPoint(x: 14, y: 14))
                path.move(to: CGPoint(x: 14, y: 4)); path.addLine(to: CGPoint(x: 4, y: 14))
                context.stroke(path, with: .foreground, style: StrokeStyle(lineWidth: 4, lineCap: .round))
            case .previous, .next:
                let left = kind == .previous
                path.move(to: CGPoint(x: left ? 7 : 2, y: 1)); path.addLine(to: CGPoint(x: left ? 2 : 7, y: size.height / 2)); path.addLine(to: CGPoint(x: left ? 7 : 2, y: size.height - 1))
                context.stroke(path, with: .foreground, lineWidth: 2)
            }
        }
    }
}

struct AssistantSpeechPlayerHostView: View {
    let chatID: String
    let viewportWidth: CGFloat
    @ObservedObject private var speech: NativeAssistantSpeech
    init(chatID: String, viewportWidth: CGFloat = 390) {
        self.chatID = chatID
        self.viewportWidth = viewportWidth
        self.speech = AssistantSpeechAppRuntime.shared.controller(for: chatID)
    }
    var body: some View {
        Group { if speech.playerVisible { AssistantSpeechPlayerView(speech: speech, viewportWidth: viewportWidth) } }
            .onDisappear { AssistantSpeechAppRuntime.shared.stopPublic(chatID: chatID) }
    }
}


// ChatMessage.svelte: compact 20pt action expands its label on hover/focus.
struct AssistantMessageSpeakButton: View {
    let action: () -> Void
    @State private var hovered = false
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        Button(action: action) {
            HStack(spacing: .spacing2) {
                Icon("audio", size: 16).fixedSize()
                Text(LocalizationManager.shared.text("chat.assistant_speech.speak_response"))
                    .font(.omSmall).lineLimit(1).opacity(hovered || focused ? 1 : 0)
            }.padding(.spacing1).frame(maxWidth: hovered || focused ? 180 : 20, minHeight: 28, alignment: .leading)
                .clipped().contentShape(RoundedRectangle(cornerRadius: .radius4))
        }.buttonStyle(.plain).foregroundStyle(hovered || focused ? Color.buttonPrimary : Color.grey60)
            .focused($focused).onHover { hovered = $0 }
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: hovered || focused)
            .accessibilityLabel(LocalizationManager.shared.text("chat.assistant_speech.speak_response"))
            .accessibilityIdentifier("assistant-message-speak")
    }
}

private struct AssistantSpeechLoadingShimmer: ViewModifier {
    @State private var phase: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func body(content: Content) -> some View {
        content.foregroundStyle(reduceMotion ? AnyShapeStyle(Color.fontButton) : AnyShapeStyle(
            LinearGradient(stops: [.init(color: .grey60, location: 0), .init(color: .grey40, location: 0.5), .init(color: .grey60, location: 1)],
                startPoint: UnitPoint(x: phase - 1, y: 0.5), endPoint: UnitPoint(x: phase, y: 0.5))))
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) { phase = 2 }
            }
    }
}


@MainActor
private enum AssistantSpeechMateImageCache {
    private static var images: [String: Image] = [:]
    private static var missing = Set<String>()
    static func image(_ category: String) -> Image? {
        if let image = images[category] { return image }
        guard !missing.contains(category) else { return nil }
        let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg")
        #if os(iOS)
        guard let path, let native = UIImage(contentsOfFile: path) else { missing.insert(category); return nil }
        let image = Image(uiImage: native)
        #elseif os(macOS)
        guard let path, let native = NSImage(contentsOfFile: path) else { missing.insert(category); return nil }
        let image = Image(nsImage: native)
        #endif
        images[category] = image
        return image
    }
}
