// Compact connection feedback beside the profile; routine status creates no toast.
// Specification: specifications/architecture/sync/specification.yml
// Assertions: sync.surface.semantic-parity, sync.startup.bounded-phases, sync.access.first-party-authenticated
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/ConnectionStatusIndicator.svelte
//         frontend/packages/ui/src/components/ConnectionStatusSlot.svelte
// State:  frontend/packages/ui/src/stores/connectionFeedbackStore.ts
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import SwiftUI
import Network

@MainActor
final class NetworkMonitor: ObservableObject {
    @Published var isConnected = true
    @Published var connectionType: NWInterface.InterfaceType?
    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "NetworkMonitor")
    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isConnected = path.status == .satisfied
                self?.connectionType = path.availableInterfaces.first?.type
            }
        }
        monitor.start(queue: queue)
    }
    deinit { monitor.cancel() }
}

// Retains the existing debounce contract name for supporting tests.
enum NetworkStatusBanner {
    static let reconnectDelayNanoseconds: UInt64 = 3_000_000_000
}

enum NativeConnectionFeedbackState: String, Equatable { case idle, offline, reconnecting, syncing }
struct NativeConnectionFeedbackInputs: Equatable {
    var online: Bool
    var authenticated: Bool
    var checkingAuth: Bool
    var connected: Bool
    var syncing: Bool
    var foregroundGeneration: Int = 0
}

/// Only presentation delays; no transport retry, authentication or sync mutation.
struct NativeConnectionFeedbackPolicy {
    private(set) var state: NativeConnectionFeedbackState = .idle
    private var reconnectStarted: Double?
    private var authStarted: Double?
    private var syncStarted: Double?
    private var resumeDeadline: Double?
    mutating func resume(now: Double) {
        reconnectStarted = nil
        resumeDeadline = now + 10
    }
    mutating func update(_ input: NativeConnectionFeedbackInputs, now: Double) {
        if input.connected { resumeDeadline = nil }
        if input.online && input.authenticated && !input.connected {
            if let deadline = resumeDeadline, now < deadline { reconnectStarted = nil }
            else if let deadline = resumeDeadline {
                reconnectStarted = deadline - 3
                resumeDeadline = nil
            } else { reconnectStarted = reconnectStarted ?? now }
        } else { reconnectStarted = nil }
        if input.online && input.checkingAuth { authStarted = authStarted ?? now }
        else { authStarted = nil }
        if input.online && input.authenticated && input.connected && input.syncing {
            syncStarted = syncStarted ?? now
        } else { syncStarted = nil }
        state = !input.online ? .offline : !input.authenticated ? .idle
            : elapsed(reconnectStarted, now: now, delay: 3) || elapsed(authStarted, now: now, delay: 12) ? .reconnecting
            : elapsed(syncStarted, now: now, delay: 0.6) ? .syncing : .idle
    }
    func nextUpdateDelay(now: Double) -> Double? {
        [(reconnectStarted, 3.0), (authStarted, 12.0), (syncStarted, 0.6), (resumeDeadline, 0.0)]
            .compactMap { start, delay -> Double? in
                guard let start, start + delay > now else { return nil }
                return start + delay - now
            }.min()
    }
    private func elapsed(_ start: Double?, now: Double, delay: Double) -> Bool {
        start.map { now - $0 >= delay } ?? false
    }
}

struct NativeConnectionStatusIndicator: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var foregroundGeneration = 0
    @StateObject private var networkMonitor = NetworkMonitor()
    @ObservedObject var wsManager: WebSocketManager
    let authenticated: Bool
    let checkingAuth: Bool
    let syncing: Bool
    let onReconnect: () -> Void
    var onFeedbackChange: (NativeConnectionFeedbackState) -> Void = { _ in }
    @State private var policy = NativeConnectionFeedbackPolicy()
    @State private var animating = false
    private var inputs: NativeConnectionFeedbackInputs {
        .init(online: networkMonitor.isConnected, authenticated: authenticated,
            checkingAuth: checkingAuth, connected: wsManager.connectionState == .connected, syncing: syncing,
            foregroundGeneration: foregroundGeneration)
    }
    private var displayedState: NativeConnectionFeedbackState {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        if let index = arguments.firstIndex(of: "--ui-test-connection-status"), index + 1 < arguments.count,
           let state = NativeConnectionFeedbackState(rawValue: arguments[index + 1]) { return state }
        #endif
        return policy.state
    }
    private var label: String {
        switch displayedState {
        case .offline: AppStrings.offlineBanner
        case .reconnecting: AppStrings.reconnectingBanner
        case .syncing: AppStrings.syncing
        case .idle: ""
        }
    }
    var body: some View {
        // Group forwards accessibility to the 18/20px glyph. A real layout
        // container owns the 30px status slot and preserves the retry child.
        ZStack {
            if displayedState == .reconnecting {
                Button(action: onReconnect) {
                    icon.frame(width: 30, height: 30).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.retry)
                .accessibilityIdentifier("connection-status-retry")
            } else if displayedState != .idle { icon.frame(width: 30, height: 30) }
        }
        .foregroundStyle(Color.grey60)
        .frame(width: displayedState == .idle ? 0 : 30, height: 30)
        .contentShape(Rectangle())
        .clipped()
        .opacity(displayedState == .idle ? 0 : 1)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: displayedState)
        .accessibilityElement(children: displayedState == .reconnecting ? .contain : .ignore)
        .accessibilityLabel(label)
        .accessibilityValue(displayedState.rawValue)
        .accessibilityIdentifier("connection-status-indicator")
        .accessibilityHidden(displayedState == .idle)
        .help(Text(label))
        .onAppear { onFeedbackChange(displayedState) }
        .onChange(of: displayedState) { _, state in onFeedbackChange(state) }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                policy.resume(now: ProcessInfo.processInfo.systemUptime)
                foregroundGeneration += 1
            }
        }
        .task(id: displayedState) {
            animating = false
            await Task.yield()
            guard !Task.isCancelled else { return }
            animating = true
        }
        .task(id: inputs) {
            let captured = inputs
            policy.update(captured, now: ProcessInfo.processInfo.systemUptime)
            while let delay = policy.nextUpdateDelay(now: ProcessInfo.processInfo.systemUptime) {
                do { try await Task.sleep(for: .seconds(delay)) } catch { return }
                guard !Task.isCancelled else { return }
                policy.update(captured, now: ProcessInfo.processInfo.systemUptime)
            }
        }
    }
    @ViewBuilder private var icon: some View {
        switch displayedState {
        case .offline: LucideNativeIcon("plane", size: 18)
        case .reconnecting:
            ZStack {
                NativeWifiPath(arc: nil).stroke(style: .init(lineWidth: 1.75 * 20 / 24, lineCap: .round))
                ForEach(0..<3) { arc in
                    NativeWifiPath(arc: arc).stroke(style: .init(lineWidth: 1.75 * 20 / 24, lineCap: .round))
                        .opacity(reduceMotion || animating ? 1 : 0.3)
                        .animation(reduceMotion ? nil : .easeInOut(duration: 0.9)
                            .repeatForever(autoreverses: true).delay([0.36, 0.18, 0.0][arc]), value: animating)
                }
            }.frame(width: 20, height: 20)
        case .syncing:
            LucideNativeIcon("refresh-cw", size: 18)
                .rotationEffect(.degrees(animating && !reduceMotion ? 360 : 0))
                .animation(reduceMotion ? nil : .linear(duration: 2.4).repeatForever(autoreverses: false), value: animating)
        case .idle: EmptyView()
        }
    }
}

// Lucide wifi.svg paths: fixed dot, then outer/middle/inner circular arcs.
// Source: https://github.com/lucide-icons/lucide/blob/main/icons/wifi.svg
private struct NativeWifiPath: Shape {
    let arc: Int?
    func path(in rect: CGRect) -> Path {
        var path = Path()
        if let arc {
            let radii: [Double] = [15, 10, 5]
            let halves: [Double] = [10, 7, 3.5]
            let starts: [Double] = [8.82, 12.859, 16.429]
            let radius = radii[arc], half = halves[arc]
            let rise = (radius * radius - half * half).squareRoot()
            path.addArc(center: CGPoint(x: 12, y: CGFloat(starts[arc] + rise)), radius: CGFloat(radius),
                startAngle: .radians(atan2(-rise, -half)), endAngle: .radians(atan2(-rise, half)), clockwise: false)
        } else {
            path.move(to: CGPoint(x: 12, y: 20)); path.addLine(to: CGPoint(x: 12.01, y: 20))
        }
        return path.applying(CGAffineTransform(scaleX: rect.width / 24, y: rect.height / 24))
    }
}
