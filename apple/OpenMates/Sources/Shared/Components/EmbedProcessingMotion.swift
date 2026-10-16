// Processing motion shared by native embed preview footers and Watch status text.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte/CSS: frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Classes: .status-value.processing-shimmer; .stop-button .icon_stop_processing
// Keyframes: shimmer (1.5s linear), stopButtonPulse (1.2s ease-in-out)
// Tokens: ColorTokens.generated.swift (grey70, grey50)
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

#if DEBUG && targetEnvironment(simulator)
/// Synthetic accessibility input for isolated Simulator pixel tests. Production
/// always reads the system setting; fixtures can only additionally reduce motion.
private struct EmbedProcessingFixtureReducedMotionKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var embedProcessingFixtureReducedMotion: Bool {
        get { self[EmbedProcessingFixtureReducedMotionKey.self] }
        set { self[EmbedProcessingFixtureReducedMotionKey.self] = newValue }
    }
}
#endif

#if DEBUG
extension View {
    @ViewBuilder
    func embedProcessingReducedMotionFixture(_ enabled: Bool) -> some View {
        #if targetEnvironment(simulator)
        environment(\.embedProcessingFixtureReducedMotion, enabled)
        #else
        self
        #endif
    }
}
#endif

/// CSS background-size 200%; background-position 200% → -200% moves a
/// two-width repeating gradient by four content widths during each 1.5s cycle.
enum EmbedProcessingMotion {
    static func isActive(processing: Bool, reducedMotion: Bool, visible: Bool, sceneActive: Bool) -> Bool {
        processing && !reducedMotion && visible && sceneActive
    }

    static let shimmerDuration: TimeInterval = 1.5
    static let stopPulseDuration: TimeInterval = 1.2

    static func shimmerOffset(elapsed: TimeInterval, width: CGFloat) -> CGFloat {
        let phase = max(0, elapsed).truncatingRemainder(dividingBy: shimmerDuration) / shimmerDuration
        return width * CGFloat(-2 + 4 * phase)
    }

    static func stopOpacity(elapsed: TimeInterval, reduceMotion: Bool = false) -> Double {
        guard !reduceMotion else { return 1 }
        let phase = max(0, elapsed).truncatingRemainder(dividingBy: stopPulseDuration) / stopPulseDuration
        if phase <= 0.5 { return 1 - 0.5 * cssEaseInOut(phase * 2) }
        return 0.5 + 0.5 * cssEaseInOut((phase - 0.5) * 2)
    }

    /// CSS ease-in-out is cubic-bezier(0.42, 0, 0.58, 1), applied separately
    /// between the 0%, 50%, 100% pulse keyframes. Solve x(t), then evaluate y(t).
    private static func cssEaseInOut(_ progress: Double) -> Double {
        let x = min(1, max(0, progress))
        var lower = 0.0, upper = 1.0
        for _ in 0..<28 {
            let t = (lower + upper) / 2
            let sample = 3 * (1 - t) * (1 - t) * t * 0.42 + 3 * (1 - t) * t * t * 0.58 + t * t * t
            if sample < x { lower = t } else { upper = t }
        }
        let t = (lower + upper) / 2
        return 3 * (1 - t) * t * t + t * t * t
    }
}

/// Changes only the painted text. Original text layout/accessibility is retained;
/// terminal states destroy the animated overlay and offscreen timelines pause.
struct EmbedProcessingTextShimmer: ViewModifier {
    let isProcessing: Bool
    var staticColor: Color = .grey70
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    #if DEBUG && targetEnvironment(simulator)
    @Environment(\.embedProcessingFixtureReducedMotion) private var fixtureReduceMotion
    #endif
    @Environment(\.scenePhase) private var scenePhase
    @State private var start = Date()
    @State private var visible = false

    private var reduceMotion: Bool {
        #if DEBUG && targetEnvironment(simulator)
        systemReduceMotion || fixtureReduceMotion
        #else
        systemReduceMotion
        #endif
    }

    private var motionActive: Bool {
        EmbedProcessingMotion.isActive(processing: isProcessing, reducedMotion: reduceMotion,
                                       visible: visible, sceneActive: scenePhase == .active)
    }

    func body(content: Content) -> some View {
        content
            .foregroundStyle(motionActive ? Color.clear : staticColor)
            .overlay {
                if motionActive {
                    GeometryReader { geometry in
                        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !visible)) { timeline in
                            let width = geometry.size.width
                            let offset = EmbedProcessingMotion.shimmerOffset(elapsed: timeline.date.timeIntervalSince(start), width: width)
                            ZStack(alignment: .leading) {
                                ForEach(-2...2, id: \.self) { tile in
                                    LinearGradient(stops: [
                                        .init(color: .grey70, location: 0),
                                        .init(color: .grey70, location: 0.4),
                                        .init(color: .grey50, location: 0.5),
                                        .init(color: .grey70, location: 0.6),
                                        .init(color: .grey70, location: 1)
                                    ], startPoint: .leading, endPoint: .trailing)
                                    .frame(width: width * 2, height: geometry.size.height)
                                    .offset(x: offset + CGFloat(tile) * width * 2)
                                }
                            }
                            .frame(width: width, height: geometry.size.height, alignment: .leading)
                            .clipped()
                        }
                    }
                    .mask(content.foregroundStyle(.white))
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
                }
            }
            .onAppear { start = Date(); visible = true }
            .onDisappear { visible = false }
            .onChange(of: isProcessing) { _, active in if active { start = Date() } }
            .onChange(of: reduceMotion) { _, _ in start = Date() }
            .onChange(of: scenePhase) { _, phase in if phase == .active { start = Date() } }
    }
}

#if !os(watchOS)
/// Animation of the existing stop glyph, without inventing cancellation actions.
/// The 35px painted icon stays inside the existing fixed 40px control allocation.
struct EmbedProcessingStopGlyph: View {
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    #if DEBUG && targetEnvironment(simulator)
    @Environment(\.embedProcessingFixtureReducedMotion) private var fixtureReduceMotion
    #endif
    @Environment(\.scenePhase) private var scenePhase
    @State private var start = Date()
    @State private var visible = false
    @State private var pauseStarted: Date?
    @State private var pausedDuration: TimeInterval = 0

    private var reduceMotion: Bool {
        #if DEBUG && targetEnvironment(simulator)
        systemReduceMotion || fixtureReduceMotion
        #else
        systemReduceMotion
        #endif
    }

    var body: some View {
        Group {
            if !EmbedProcessingMotion.isActive(processing: true, reducedMotion: reduceMotion, visible: visible, sceneActive: scenePhase == .active) {
                glyph.opacity(1)
            } else {
                TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !visible || pauseStarted != nil)) { timeline in
                    glyph.opacity(EmbedProcessingMotion.stopOpacity(
                        elapsed: (pauseStarted ?? timeline.date).timeIntervalSince(start) - pausedDuration))
                }
            }
        }
        .frame(width: 40, height: 40)
        .onAppear { start = Date(); pausedDuration = 0; pauseStarted = nil; visible = true }
        .onDisappear { visible = false }
        .onChange(of: reduceMotion) { _, _ in start = Date(); pausedDuration = 0; pauseStarted = nil }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { start = Date(); pausedDuration = 0; pauseStarted = nil }
        }
        .onHover { hovering in
            if hovering && pauseStarted == nil { pauseStarted = Date() }
            else if !hovering, let paused = pauseStarted {
                pausedDuration += Date().timeIntervalSince(paused)
                pauseStarted = nil
            }
        }
    }

    private var glyph: some View {
        Icon("stop_processing", size: 35)
            .foregroundStyle(pauseStarted == nil ? Color(red: 1, green: 0, blue: 0) : Color(red: 139.0 / 255, green: 0, blue: 0))
            .accessibilityIdentifier("embed-processing-stop-icon")
    }
}

#endif
