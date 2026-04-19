// Toast notification system — non-intrusive messages that auto-dismiss.
// Mirrors the web app's notificationStore with success/error/info types.

import SwiftUI

@MainActor
final class ToastManager: ObservableObject {
    static let shared = ToastManager()

    @Published var currentToast: Toast?
    private var dismissTask: Task<Void, Never>?

    struct Toast: Identifiable, Equatable {
        let id = UUID()
        let message: String
        let type: ToastType
        let duration: TimeInterval

        static func == (lhs: Toast, rhs: Toast) -> Bool { lhs.id == rhs.id }
    }

    enum ToastType {
        case success, error, info, warning

        var icon: String {
            switch self {
            case .success: return "check"
            case .error: return "warning"
            case .info: return "question"
            case .warning: return "warning"
            }
        }

        var color: Color {
            switch self {
            case .success: return .green
            case .error: return .error
            case .info: return .buttonPrimary
            case .warning: return .warning
            }
        }
    }

    private init() {}

    func show(_ message: String, type: ToastType = .info, duration: TimeInterval = 3) {
        dismissTask?.cancel()
        withAnimation(.spring(duration: 0.3)) {
            currentToast = Toast(message: message, type: type, duration: duration)
        }
        AccessibilityAnnouncement.announce(message)
        dismissTask = Task {
            try? await Task.sleep(for: .seconds(duration))
            withAnimation(.spring(duration: 0.3)) {
                currentToast = nil
            }
        }
    }

    func dismiss() {
        dismissTask?.cancel()
        withAnimation(.spring(duration: 0.3)) {
            currentToast = nil
        }
    }
}

struct ToastOverlay: View {
    @ObservedObject var manager = ToastManager.shared
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    var body: some View {
        VStack {
            if let toast = manager.currentToast {
                HStack(spacing: .spacing3) {
                    Icon(toast.type.icon, size: 18)
                        .foregroundStyle(toast.type.color)
                        .accessibilityHidden(true)
                    Text(toast.message)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                    Button { manager.dismiss() } label: {
                        Icon("close", size: 14)
                            .foregroundStyle(Color.fontTertiary)
                    }
                    .accessibleButton("Dismiss notification", hint: "Closes this toast notification")
                }
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing3)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
                .shadow(color: .black.opacity(0.1), radius: 8, y: 4)
                .padding(.horizontal, .spacing6)
                .transition(reduceMotion ? .opacity : .move(edge: .top).combined(with: .opacity))
                .accessibilityElement(children: .combine)
                .accessibilityLabel(toast.message)
                .accessibilityAddTraits(.isStaticText)
            }
            Spacer()
        }
        .padding(.top, .spacing2)
        .allowsHitTesting(manager.currentToast != nil)
    }
}
