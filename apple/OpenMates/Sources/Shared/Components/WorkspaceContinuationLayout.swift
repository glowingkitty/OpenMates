// Web source: frontend/packages/ui/src/utils/continueCardLayout.ts and
// components/workspace/WorkspaceHomeShell.svelte (.workspace-link-row).
// Native phone expansion follows the approved available-gap contract: app
// chrome width does not disqualify a 300×200 card that fits its content lane.
// Specification: specifications/features/chats/specification.yml
//                specifications/features/projects/specification.yml
// Assertions: chats.surface.semantic-parity, projects.surface.semantic-parity
import SwiftUI
#if os(iOS)
import UIKit
#endif

enum WorkspaceContinuationLayoutPolicy {
    static let expandedCardHeight: CGFloat = 200
    static let minimumExpandedGap: CGFloat = 420
    struct Placement: Equatable {
        let top: CGFloat
        let bottom: CGFloat
        let expanded: Bool
        var availableHeight: CGFloat { bottom - top }
        var centerY: CGFloat { (top + bottom) / 2 }
    }
    static func resolve(width: CGFloat, height: CGFloat, bannerBottom: CGFloat, composerTop: CGFloat) -> Placement {
        let height = height.isFinite ? max(0, height) : 0
        let top = min(height, max(0, bannerBottom.isFinite ? bannerBottom : 0))
        let bottom = max(top, min(height, composerTop.isFinite ? composerTop : height))
        return .init(top: top, bottom: bottom,
            expanded: width.isFinite && width >= 300 && bottom - top >= minimumExpandedGap)
    }
}

/// Shared Show all/Search link appearance. Each workspace owns its destination.
struct WorkspaceContinuationLink: View {
    let title: String
    let icon: String
    let identifier: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: .spacing3) {
                LucideNativeIcon(icon, size: icon == "search" ? 18 : 14)
                Text(title)
            }
            .font(.omP.weight(.bold))
            .foregroundStyle(Color.grey60)
            .padding(.vertical, .spacing2)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }
}

/// Project metadata filtering stays inside the current store/account snapshot.
/// It never searches messages or dispatches to the chat search overlay.
enum WorkspaceProjectBrowsePolicy {
    static func matches(query: String, name: String, description: String) -> Bool {
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return query.isEmpty || name.localizedCaseInsensitiveContains(query) || description.localizedCaseInsensitiveContains(query)
    }
}

/// Accounts for keyboard overlap in fixed preview panes as well as production
/// panes. Already-resized safe-area geometry naturally computes zero overlap.
struct WorkspaceContinuationKeyboardTracking: ViewModifier {
    @Binding var minY: CGFloat?
    func body(content: Content) -> some View {
        #if os(iOS)
        content
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)) { notification in
                guard let frame = notification.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
                let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first(where: \.isKeyWindow)
                minY = window?.convert(frame, from: nil).minY ?? frame.minY
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in minY = nil }
        #else
        content
        #endif
    }
}
