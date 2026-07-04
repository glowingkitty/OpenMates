// Network status indicator — shows connection state at top of screen.
// Mirrors networkStatusStore.ts: offline banner, reconnecting indicator.

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

    deinit {
        monitor.cancel()
    }
}

struct NetworkStatusBanner: View {
    static let reconnectDelayNanoseconds: UInt64 = 1_500_000_000

    @StateObject private var networkMonitor = NetworkMonitor()
    @ObservedObject var wsManager: WebSocketManager
    @State private var showReconnectBanner = false
    @State private var reconnectBannerTask: Task<Void, Never>?

    var body: some View {
        VStack(spacing: 0) {
            if !networkMonitor.isConnected {
                banner(
                    icon: "offline",
                    message: AppStrings.offlineBanner,
                    color: Color.error,
                    identifier: "network-status-offline"
                )
            } else if case .reconnecting = wsManager.connectionState, showReconnectBanner {
                banner(
                    icon: "reload",
                    message: AppStrings.reconnectingBanner,
                    color: Color.warning,
                    identifier: "network-status-reconnecting"
                )
            }
        }
        .animation(.easeInOut(duration: 0.3), value: networkMonitor.isConnected)
        .animation(.easeInOut(duration: 0.3), value: wsManager.connectionState)
        .onChange(of: wsManager.connectionState) { _, newState in
            scheduleReconnectBanner(for: newState)
        }
        .onDisappear {
            reconnectBannerTask?.cancel()
        }
    }

    private func banner(icon: String, message: String, color: Color, identifier: String) -> some View {
        HStack(spacing: .spacing3) {
            Icon(icon, size: 14)
            Text(message)
                .font(.omXs)
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .padding(.vertical, .spacing2)
        .background(color)
        .accessibilityIdentifier(identifier)
    }

    private func scheduleReconnectBanner(for state: WebSocketManager.ConnectionState) {
        reconnectBannerTask?.cancel()

        guard case .reconnecting = state else {
            showReconnectBanner = false
            return
        }

        reconnectBannerTask = Task {
            try? await Task.sleep(nanoseconds: Self.reconnectDelayNanoseconds)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                if case .reconnecting = wsManager.connectionState {
                    showReconnectBanner = true
                }
            }
        }
    }
}
