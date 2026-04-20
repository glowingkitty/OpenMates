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
    @StateObject private var networkMonitor = NetworkMonitor()
    @ObservedObject var wsManager: WebSocketManager

    var body: some View {
        VStack(spacing: 0) {
            if !networkMonitor.isConnected {
                banner(
                    icon: "offline",
                    message: "No internet connection",
                    color: Color.error
                )
            } else if case .reconnecting(let attempt) = wsManager.connectionState {
                banner(
                    icon: "reload",
                    message: "Reconnecting... (attempt \(attempt))",
                    color: Color.warning
                )
            }
        }
        .animation(.easeInOut(duration: 0.3), value: networkMonitor.isConnected)
        .animation(.easeInOut(duration: 0.3), value: wsManager.connectionState)
    }

    private func banner(icon: String, message: String, color: Color) -> some View {
        HStack(spacing: .spacing3) {
            Icon(icon, size: 14)
            Text(message)
                .font(.omXs)
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .padding(.vertical, .spacing2)
        .background(color)
    }
}
