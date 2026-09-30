// Shared in-app notifications using the rendered web notification card.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/Notification.svelte
//         frontend/packages/ui/src/components/NotificationStack.svelte
// CSS: .notification, .notification-header, .notification-content,
//      .notification-progress, .notification-activity, notificationSlideIn/Out
// ────────────────────────────────────────────────────────────────────

import SwiftUI

@MainActor
final class ToastManager: ObservableObject {
    static let shared = ToastManager()
    @Published private(set) var notifications: [Toast] = []
    private var dismissTasks: [UUID: Task<Void, Never>] = [:]
    var currentToast: Toast? { notifications.last }
    var visibleNotifications: [Toast] { Array(notifications.suffix(3).reversed()) }

    struct Toast: Identifiable, Equatable {
        let id: UUID
        let message: String
        let type: ToastType
        let duration: TimeInterval
        let title: String
        let isProcessing: Bool
        let dedupeKey: String?
    }

    enum ToastType: Equatable {
        case success, error, info, warning, connection
        var icon: String {
            switch self {
            case .success: return "check"
            case .error, .warning: return "warning"
            case .info: return "reminder"
            case .connection: return "cloud"
            }
        }
        var color: Color {
            switch self {
            // Notification.svelte semantic icon fills are literal rgba values,
            // with no generated semantic tokens: (40,167,69), (220,53,69),
            // and (255,193,7), all at 15% opacity.
            case .success: return Color(red: 40 / 255, green: 167 / 255, blue: 69 / 255).opacity(0.15)
            case .error: return Color(red: 220 / 255, green: 53 / 255, blue: 69 / 255).opacity(0.15)
            case .warning: return Color(red: 1, green: 193 / 255, blue: 7 / 255).opacity(0.15)
            case .info, .connection: return .grey40
            }
        }
    }

    init() {}

    func show(_ message: String, type: ToastType = .info, duration: TimeInterval = 3,
              title: String = "", isProcessing: Bool = false, dedupeKey: String? = nil) {
        let existing = dedupeKey.flatMap { key in notifications.first { $0.dedupeKey == key } }
        let id = existing?.id ?? UUID()
        dismissTasks[id]?.cancel()
        dismissTasks[id] = nil
        let notification = Toast(id: id, message: message, type: type, duration: duration,
                                 title: title, isProcessing: isProcessing, dedupeKey: dedupeKey)
        if let index = notifications.firstIndex(where: { $0.id == id }) {
            notifications[index] = notification
        } else {
            notifications.append(notification)
        }
        AccessibilityAnnouncement.announce(message)
        guard duration > 0 else { return }
        dismissTasks[id] = Task {
            do { try await Task.sleep(for: .seconds(duration)) } catch { return }
            guard !Task.isCancelled else { return }
            dismiss(id: id)
        }
    }

    func dismiss(id: UUID) {
        dismissTasks[id]?.cancel()
        dismissTasks[id] = nil
        notifications.removeAll { $0.id == id }
    }

    func dismiss(dedupeKey: String) {
        if let id = notifications.first(where: { $0.dedupeKey == dedupeKey })?.id { dismiss(id: id) }
    }

    func dismiss() {
        if let id = currentToast?.id { dismiss(id: id) }
    }

    func dismissAll() {
        for task in dismissTasks.values { task.cancel() }
        dismissTasks.removeAll()
        notifications.removeAll()
    }

}

/// Values without token equivalents are measured CSS: width 430, shadow 4/16,
/// intro/outro 320/280ms, travel 120px, line-height 1.4, activity cycle 1.35s.
enum NotificationMotion {
    static let introDuration = 0.32
    static let outroDuration = 0.28
    static let offset: CGFloat = 120
    static func transition(reduceMotion: Bool) -> AnyTransition {
        .asymmetric(
            insertion: .offset(y: reduceMotion ? 0 : -offset).combined(with: .opacity)
                .animation(reduceMotion ? .linear(duration: 0.001) : .timingCurve(0.32, 0, 0.2, 1, duration: introDuration)),
            removal: .offset(y: reduceMotion ? 0 : -offset).combined(with: .opacity)
                .animation(reduceMotion ? .linear(duration: 0.001) : .timingCurve(0.4, 0, 1, 1, duration: outroDuration)))
    }
}

struct InAppNotificationCard: View {
    let title: String
    let message: String
    let type: ToastManager.ToastType
    var duration: TimeInterval = 0
    var isProcessing = false
    var compact = false
    var isInteractive = true
    let onDismiss: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var progress: CGFloat = 0
    @State private var activity = false
    @State private var dragOffset: CGFloat = 0

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing4) {
                Icon("reminder", size: .iconSizeXs).foregroundStyle(Color.grey50).accessibilityHidden(true)
                Text(title).font(.omXxs).fontWeight(.medium).foregroundStyle(Color.grey50)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("notification-title")
                Button(action: onDismiss) {
                    Icon("close", size: .iconSizeSm).foregroundStyle(Color.grey90)
                        .padding(.spacing2)
                }
                .buttonStyle(.plain).opacity(0.7)
                .accessibilityLabel(AppStrings.close)
                .accessibilityIdentifier(isInteractive ? "notification-dismiss" : "notification-dismiss-covered")
                .accessibilityHidden(!isInteractive)
                .disabled(!isInteractive)
            }
            .frame(minHeight: 28)
            HStack(alignment: .top, spacing: .spacing6) {
                Icon(type.icon, size: .iconSizeMd).foregroundStyle(Color.grey90)
                    .frame(width: .iconSizeXl, height: .iconSizeXl)
                    .background(type.color)
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    .accessibilityHidden(true)
                Text(message).font(.omSmall).fontWeight(.medium).foregroundStyle(Color.grey90)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("notification-message")
            }
        }
        .padding(.horizontal, compact ? .spacing6 : .spacing8)
        .padding(.vertical, compact ? .spacing5 : .spacing6)
        .background(Color.grey30)
        .overlay(alignment: .bottomLeading) {
            if duration > 0 {
                GeometryReader { geometry in
                    Color.grey50.frame(width: geometry.size.width * progress)
                }
                .frame(height: .spacing2)
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("notification-progress")
            } else if isProcessing {
                GeometryReader { geometry in
                    LinearGradient(colors: [.clear, .buttonPrimary, .clear], startPoint: .leading, endPoint: .trailing)
                        .frame(width: geometry.size.width * 0.38)
                        .offset(x: geometry.size.width * 0.38 * (activity ? 2.8 : -1.1))
                }
                .frame(height: .spacing2)
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("notification-activity")
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .shadow(color: .black.opacity(0.12), radius: 16, y: 4)
        .offset(y: dragOffset)
        .opacity(max(0.3, 1 - abs(dragOffset) / 150))
        .gesture(DragGesture(minimumDistance: 10).onChanged { value in
            dragOffset = value.translation.height < 0 ? value.translation.height : value.translation.height * 0.3
        }.onEnded { value in
            if value.translation.height < -50 || value.predictedEndTranslation.height < -100 { onDismiss() }
            withAnimation(.easeOut(duration: 0.2)) { dragOffset = 0 }
        })
        // Explicit containment keeps the card's identifier on its own bounds,
        // while preserving title/message and the independent dismiss control.
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("notification")
        .task(id: duration) {
            progress = 0
            if duration > 0 { withAnimation(.linear(duration: duration)) { progress = 1 } }
        }
        .task(id: isProcessing) {
            activity = false
            if isProcessing { withAnimation(.easeInOut(duration: reduceMotion ? 2.4 : 1.35).repeatForever(autoreverses: false)) { activity = true } }
        }
    }
}

struct ToastOverlay: View {
    @ObservedObject var manager = ToastManager.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geometry in
            VStack {
                ZStack(alignment: .top) {
                    // Covered cards are a separate view identity from the
                    // interactive foreground. Promoting a retained notice must
                    // create an enabled, untransformed dismiss control rather
                    // than reuse a formerly disabled back-card Button.
                    ForEach(Array(manager.visibleNotifications.dropFirst().enumerated()), id: \.element.id) { index, toast in
                        notificationCard(toast, depth: index + 1, width: geometry.size.width)
                    }
                    ForEach(Array(manager.visibleNotifications.prefix(1)), id: \.id) { toast in
                        notificationCard(toast, depth: 0, width: geometry.size.width)
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("notification-stack")
                Spacer()
            }
            .frame(maxWidth: .infinity)
            .padding(.top, geometry.size.width <= .breakpointMobile ? .spacing5 : .spacing10)
            .animation(reduceMotion ? .linear(duration: 0.001) : .timingCurve(0.32, 0, 0.2, 1,
                duration: NotificationMotion.introDuration), value: manager.notifications)
        }
        .allowsHitTesting(!manager.notifications.isEmpty)
    }

    private func notificationCard(_ toast: ToastManager.Toast, depth: Int, width: CGFloat) -> some View {
        InAppNotificationCard(title: toast.title, message: toast.message, type: toast.type,
            duration: toast.duration, isProcessing: toast.isProcessing,
            compact: width <= 450, isInteractive: depth == 0,
            onDismiss: { manager.dismiss(id: toast.id) })
            .frame(width: min(430, max(0, width - (width <= 450 ? 20 : 40))))
            .scaleEffect(1 - CGFloat(depth) * 0.045, anchor: .top)
            .offset(y: CGFloat(depth) * -10)
            .opacity(depth == 0 ? 1 : depth == 1 ? 0.72 : 0.48)
            .saturation(depth == 0 ? 1 : 0.9)
            .brightness(depth == 0 ? 0 : -0.1)
            .zIndex(Double(3 - depth))
            .allowsHitTesting(depth == 0)
            .accessibilityHidden(depth > 0)
            .transition(NotificationMotion.transition(reduceMotion: reduceMotion))
    }
}
