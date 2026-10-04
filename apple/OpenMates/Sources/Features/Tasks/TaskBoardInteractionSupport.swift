// Native drag/secondary-click adapters for the Tasks board. Payloads contain
// only a random session token; task plaintext and ciphertext never leave memory.
// Web source: frontend/packages/ui/src/components/tasks/TaskBoard.svelte
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.context-menu, apple-task-board.drag-move
import SwiftUI

struct TaskCardFramesKey: PreferenceKey {
    static var defaultValue: [String: CGRect] { [:] }
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}

struct TaskCardDragSource: ViewModifier {
    let task: UserTaskItem?
    let onBegin: (UserTaskItem) -> NSItemProvider
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @ViewBuilder func body(content: Content) -> some View {
        if let task {
            content.onDrag { onBegin(task) } preview: {
                Text(task.title).font(.omP.weight(.bold)).lineLimit(3)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.spacing4).frame(width: 240, alignment: .leading)
                    .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
                    .shadow(color: .black.opacity(0.2), radius: 12, y: 6)
                    .rotationEffect(.degrees(reduceMotion ? 0 : 3))
                    .scaleEffect(reduceMotion ? 1 : 1.01)
            }
        } else { content }
    }
}

/// Phone touch needs an independent OS drag recognizer because the title's
/// exclusive long-press recognizer owns the action menu. Pointer users can drag
/// the whole card; the phone handle also remains a real NSItemProvider drag.
struct TaskDragHandle: View {
    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<2) { _ in
                VStack(spacing: 3) {
                    ForEach(0..<3) { _ in Circle().fill(Color.fontSecondary).frame(width: 3, height: 3) }
                }
            }
        }
        .frame(width: 32, height: 32).contentShape(Rectangle())
        .accessibilityLabel(AppStrings.tasksDrag)
        .accessibilityIdentifier("task-drag-handle")
    }
}

#if os(macOS)
import AppKit

/// One monitor per workspace, rather than one monitor per bounded card. A
/// secondary click is consumed only over a standard task in this view/window.
struct TaskSecondaryClickReader: NSViewRepresentable {
    let onSecondaryClick: (CGPoint) -> Bool
    func makeNSView(context: Context) -> Reader {
        let view = Reader()
        view.onSecondaryClick = onSecondaryClick
        return view
    }
    func updateNSView(_ view: Reader, context: Context) { view.onSecondaryClick = onSecondaryClick }
    static func dismantleNSView(_ view: Reader, coordinator: ()) { view.removeMonitor() }

    final class Reader: NSView {
        var onSecondaryClick: (CGPoint) -> Bool = { _ in false }
        private var monitor: Any?
        override var isFlipped: Bool { true }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            removeMonitor()
            guard window != nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: [.rightMouseDown, .leftMouseDown]) { [weak self] event in
                guard let self, event.window === self.window,
                      event.type == .rightMouseDown || event.modifierFlags.contains(.control)
                else { return event }
                let point = self.convert(event.locationInWindow, from: nil)
                guard self.bounds.contains(point), self.onSecondaryClick(point) else { return event }
                return nil
            }
        }
        func removeMonitor() {
            if let monitor { NSEvent.removeMonitor(monitor) }
            monitor = nil
        }
        // AppKit window detachment and SwiftUI dismantleNSView own cleanup on
        // the main actor. A nonisolated deinit cannot safely read Any tokens.
    }
}
#endif
