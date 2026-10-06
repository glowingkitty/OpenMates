// Native drag/secondary-click adapters for the Tasks board. Payloads contain
// only a random session token; task plaintext and ciphertext never leave memory.
// Web source: frontend/packages/ui/src/components/tasks/TaskBoard.svelte
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.context-menu, apple-task-board.drag-move
import SwiftUI

// DEBUG receipts are enabled only in disposable component previews. No IDs,
// titles, payload tokens, or account values enter this bounded trace.
@MainActor enum NativeDragDiagnostics {
    #if DEBUG
    private static var events: [String] = []
    private static var counts: [String: Int] = [:]
    static var enabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--dev-preview") &&
        ProcessInfo.processInfo.arguments.contains("--ui-test-drag-diagnostics")
    }
    static var receipt: String { counts.keys.sorted().map { "\($0)=\(counts[$0] ?? 0)" }.joined(separator: ",") + "|" + events.joined(separator: ";") }
    #endif
    static func record(_ event: String) {
        #if DEBUG
        guard enabled else { return }
        let key = String(event.prefix { $0 != "=" && $0 != ";" })
        counts[key, default: 0] += 1
        events.append("\(Int(ProcessInfo.processInfo.systemUptime * 1000)):\(event)")
        if events.count > 48 { events.removeFirst(events.count - 48) }
        #endif
    }
}
#if DEBUG && os(iOS)
struct NativeDragDiagnosticProbe: UIViewRepresentable {
    func makeUIView(context: Context) -> Probe { Probe() }
    func updateUIView(_ view: Probe, context: Context) {}
    final class Probe: UIView {
        override init(frame: CGRect) {
            super.init(frame: frame)
            isAccessibilityElement = true
            accessibilityIdentifier = "native-drag-diagnostics"
            accessibilityLabel = "Synthetic drag lifecycle receipt"
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) unsupported") }
        override var accessibilityValue: String? {
            get { NativeDragDiagnostics.receipt }
            set {}
        }
        override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? { nil }
    }
}
#endif

/// Pointer emphasis never changes the layout slot or the separate native lift.
/// Reduced Motion is handled by the caller's existing nil board animation:
/// the requested 1.1 highlight remains visible without animated interpolation.
enum TaskCardHoverPolicy {
    static func scale(isHovered: Bool, isDraggable: Bool, isDragging: Bool, isEnabled: Bool) -> CGFloat {
        isHovered && isDraggable && !isDragging && isEnabled ? 1.1 : 1
    }
}

enum TaskBoardRenderWindow {
    static let initial = 20
    static func expanded(_ current: Int) -> Int { current + 20 }
}

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
        #if os(iOS)
        // The workspace UIKit source also owns release after a native lift.
        content
        #else
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
        #endif
    }
}

/// Movement after a held press belongs to drag; small finger jitter retains
/// stationary hold actions without opening the task detail.
enum TaskCardHoldIntent {
    static func opensActions(translation: CGSize) -> Bool {
        abs(translation.width) <= 8 && abs(translation.height) <= 8
    }
}

/// A moved hold remains moved if the pointer returns to its origin. This
/// prevents a cancelled/returned drag from reopening the stationary menu.
struct TaskCardHoldTracking {
    private var origin = CGPoint.zero
    private var beganAt: TimeInterval = 0
    private(set) var moved = false
    mutating func begin(at point: CGPoint, time: TimeInterval) {
        origin = point; beganAt = time; moved = false
    }
    mutating func record(_ point: CGPoint) {
        moved = moved || !TaskCardHoldIntent.opensActions(translation:
            CGSize(width: point.x - origin.x, height: point.y - origin.y))
    }
    func opensActions(at time: TimeInterval) -> Bool { !moved && time - beganAt >= 0.5 }
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

#if os(iOS)
import UIKit

/// One native drag source per Tasks workspace. Its hit-test callback accepts
/// only regular task cards, never projection cards, controls or another pane.
/// UIKit drag session completion distinguishes stationary pickup from movement
/// even when UIKit cancels the simultaneous hold recognizer during its lift.
struct TaskTouchBoardReader: UIViewRepresentable {
    let taskAtPoint: (CGPoint) -> UserTaskItem?
    let onBegin: (UserTaskItem) -> NSItemProvider
    let onStationaryHold: (String) -> Void
    let onCancelledDrag: () -> Void

    func makeUIView(context: Context) -> Reader { Reader() }
    func updateUIView(_ view: Reader, context: Context) {
        view.taskAtPoint = taskAtPoint
        view.onBegin = onBegin
        view.onStationaryHold = onStationaryHold
        view.onCancelledDrag = onCancelledDrag
    }
    static func dismantleUIView(_ view: Reader, coordinator: ()) { view.detach() }

    final class Reader: UIView, UIGestureRecognizerDelegate, UIDragInteractionDelegate {
        var taskAtPoint: (CGPoint) -> UserTaskItem? = { _ in nil }
        var onBegin: (UserTaskItem) -> NSItemProvider = { _ in NSItemProvider() }
        var onStationaryHold: (String) -> Void = { _ in }
        var onCancelledDrag: () -> Void = {}
        private weak var observedWindow: UIWindow?
        private var hold: UILongPressGestureRecognizer?
        private var drag: UIDragInteraction?
        private var source: UserTaskItem?
        private weak var activeTouch: UITouch?
        private var pickupCenterInWindow: CGPoint?
        private var holdTracking = TaskCardHoldTracking()
        private var dragging = false
        private var sessionStarted = false
        private var previewHost: UIHostingController<AnyView>?

        override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? { nil }
        override func didMoveToWindow() {
            super.didMoveToWindow()
            detach()
            guard let window else { return }
            observedWindow = window
            let hold = UILongPressGestureRecognizer(target: self, action: #selector(observeHold(_:)))
            // Observe from touch-down, without consuming ordinary taps. The
            // reducer applies the hold duration and retains peak movement.
            hold.minimumPressDuration = 0
            hold.allowableMovement = .greatestFiniteMagnitude
            hold.cancelsTouchesInView = false
            hold.delaysTouchesBegan = false
            hold.delaysTouchesEnded = false
            hold.delegate = self
            window.addGestureRecognizer(hold)
            self.hold = hold
            let drag = UIDragInteraction(delegate: self)
            drag.isEnabled = true
            window.addInteraction(drag)
            NativeDragDiagnostics.record("task.attach.window")
            self.drag = drag
        }
        func detach() {
            // Removing an active interaction can synchronously cancel it. Clear
            // the held source first so teardown cannot reopen its action menu.
            NativeDragDiagnostics.record("task.detach")
            activeTouch = nil; pickupCenterInWindow = nil
            source = nil; dragging = false; sessionStarted = false; previewHost = nil
            if let hold { observedWindow?.removeGestureRecognizer(hold) }
            if let drag { observedWindow?.removeInteraction(drag) }
            hold = nil; drag = nil; observedWindow = nil
        }
        private func task(at point: CGPoint) -> UserTaskItem? {
            // Intersect every clipping ancestor's bounds. Compact Project boards
            // can extend beyond the Project viewport; invisible cards cannot own touches.
            NativeDragDiagnostics.record("task.lookup.xy=\(Int(point.x)),\(Int(point.y));bounds=\(Int(bounds.width)),\(Int(bounds.height))")
            guard bounds.contains(point) else { NativeDragDiagnostics.record("task.lookup.outside"); return nil }
            var ancestor = superview
            while let view = ancestor {
                if view.clipsToBounds, !view.bounds.contains(convert(point, to: view)) { NativeDragDiagnostics.record("task.lookup.clipped"); return nil }
                ancestor = view.superview
            }
            let candidate = taskAtPoint(point)
            NativeDragDiagnostics.record("task.lookup.candidate=\(candidate != nil)")
            return candidate
        }
        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
            let point = touch.location(in: self)
            guard !dragging, touch.window === observedWindow,
                  touch.phase == .began || touch.phase == .stationary || touch.phase == .moved,
                  let item = task(at: point) else {
                activeTouch = nil
                if !dragging { source = nil }
                return false
            }
            activeTouch = touch
            source = item
            holdTracking.begin(at: point, time: touch.timestamp)
            NativeDragDiagnostics.record("task.touch.active")
            return true
        }
        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool { true }
        @objc private func observeHold(_ gesture: UILongPressGestureRecognizer) {
            let point = gesture.location(in: self)
            switch gesture.state {
            case .began:
                NativeDragDiagnostics.record("task.hold.began")
                if !dragging {
                    source = task(at: point)
                    holdTracking.begin(at: point, time: ProcessInfo.processInfo.systemUptime)
                }
            case .changed:
                recordMovement(point)
            case .ended:
                activeTouch = nil
                NativeDragDiagnostics.record("task.hold.ended")
                recordMovement(point)
                // UIKit may lift an item, then receive touch-up before the
                // session starts. That cancelled lift has no session-end callback.
                guard !sessionStarted else { return }
                let heldID = holdTracking.opensActions(at: ProcessInfo.processInfo.systemUptime)
                    && source.map({ task(at: point)?.id == $0.id }) == true ? source?.id : nil
                let cancelledPendingLift = dragging
                source = nil; dragging = false; sessionStarted = false
                pickupCenterInWindow = nil; previewHost = nil
                if cancelledPendingLift {
                    NativeDragDiagnostics.record("task.hold.pendingLiftReleased;eligible=\(heldID != nil)")
                    onCancelledDrag()
                }
                if let heldID { onStationaryHold(heldID) }
            case .cancelled, .failed:
                NativeDragDiagnostics.record("task.hold.cancelled")
                if let touch = activeTouch, touch.phase == .ended || touch.phase == .cancelled {
                    activeTouch = nil
                }
                // A native lift may cancel the hold recognizer. Its session end
                // owns the stationary/moved decision and custom menu handoff.
                // Keep the observed origin for a lift whose delegate starts
                // immediately after this recognizer is cancelled. A new touch
                // overwrites it; cancellation never opens the menu itself.
                break
            default: break
            }
        }
        private func recordMovement(_ point: CGPoint) {
            holdTracking.record(point)
        }
        func dragInteraction(_ interaction: UIDragInteraction, itemsForBeginning session: UIDragSession) -> [UIDragItem] {
            NativeDragDiagnostics.record("task.itemsForBeginning")
            // At itemsForBeginning UIKit has not initialized session.location;
            // the retained, still-active touch is the authoritative pickup origin.
            guard let touch = activeTouch, touch.window === observedWindow,
                  touch.phase == .began || touch.phase == .stationary || touch.phase == .moved else {
                activeTouch = nil; source = nil
                NativeDragDiagnostics.record("task.pickup.noActiveTouch")
                return []
            }
            let point = touch.location(in: self)
            guard let item = task(at: point) else {
                activeTouch = nil; source = nil
                NativeDragDiagnostics.record("task.pickup.currentScopeRejected")
                return []
            }
            pickupCenterInWindow = convert(point, to: observedWindow)
            NativeDragDiagnostics.record("task.pickup.activeTouch")
            if source?.id != item.id {
                holdTracking.begin(at: point, time: ProcessInfo.processInfo.systemUptime - 0.5)
            }
            source = item; dragging = true; sessionStarted = false
            let dragItem = UIDragItem(itemProvider: onBegin(item))
            dragItem.localObject = item.id // Local ID only; transferable payload stays a random token.
            dragItem.previewProvider = { [weak self] in self?.preview(for: item) }
            return [dragItem]
        }
        // The default lift preview targets interaction.view's superview. Our
        // source is UIWindow, so provide an explicit, attached target instead.
        func dragInteraction(_ interaction: UIDragInteraction, previewForLifting item: UIDragItem,
                             session: UIDragSession) -> UITargetedDragPreview? {
            guard let window = observedWindow, self.window === window,
                  let source, let center = pickupCenterInWindow else { return nil }
            let preview = preview(for: source)
            NativeDragDiagnostics.record("task.preview.explicitLiftTarget")
            return UITargetedDragPreview(view: preview.view, parameters: UIDragPreviewParameters(),
                target: UIPreviewTarget(container: window, center: center))
        }

        private func preview(for task: UserTaskItem) -> UIDragPreview {
            if let previewHost { return UIDragPreview(view: previewHost.view) }
            let dark = traitCollection.userInterfaceStyle == .dark
            let host = UIHostingController(rootView: AnyView(
                Text(task.title).font(.omP.weight(.bold)).lineLimit(3)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.spacing4).frame(width: 240, alignment: .leading)
                    .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
                    .shadow(color: .black.opacity(0.2), radius: 12, y: 6)
                    .rotationEffect(.degrees(UIAccessibility.isReduceMotionEnabled ? 0 : 3))
                    .scaleEffect(UIAccessibility.isReduceMotionEnabled ? 1 : 1.01)
                    .preferredColorScheme(dark ? .dark : .light)))
            let size = host.sizeThatFits(in: CGSize(width: 240, height: 200))
            host.view.frame = CGRect(origin: .zero, size: size)
            host.view.backgroundColor = .clear
            host.view.layoutIfNeeded()
            previewHost = host
            return UIDragPreview(view: host.view)
        }
        func dragInteraction(_ interaction: UIDragInteraction, sessionWillBegin session: UIDragSession) {
            sessionStarted = true
            NativeDragDiagnostics.record("task.session.willBegin")
        }
        func dragInteraction(_ interaction: UIDragInteraction, sessionAllowsMoveOperation session: UIDragSession) -> Bool { true }
        func dragInteraction(_ interaction: UIDragInteraction, sessionIsRestrictedToDraggingApplication session: UIDragSession) -> Bool { true }
        func dragInteraction(_ interaction: UIDragInteraction, sessionDidMove session: UIDragSession) {
            let point = session.location(in: self)
            NativeDragDiagnostics.record("task.session.move.xy=\(Int(point.x)),\(Int(point.y));movedBefore=\(holdTracking.moved)")
            recordMovement(point)
        }
        func dragInteraction(_ interaction: UIDragInteraction, session: UIDragSession, didEndWith operation: UIDropOperation) {
            activeTouch = nil; pickupCenterInWindow = nil
            NativeDragDiagnostics.record("task.session.end.operation=\(operation.rawValue)")
            let point = session.location(in: self)
            NativeDragDiagnostics.record("task.session.end.xy=\(Int(point.x)),\(Int(point.y));movedBefore=\(holdTracking.moved)")
            recordMovement(point)
            NativeDragDiagnostics.record("task.hold.finalEligible=\(holdTracking.opensActions(at: ProcessInfo.processInfo.systemUptime));movedAfter=\(holdTracking.moved)")
            let heldID = holdTracking.opensActions(at: ProcessInfo.processInfo.systemUptime)
                && operation == .cancel ? source?.id : nil
            source = nil; dragging = false; sessionStarted = false; previewHost = nil
            if operation == .cancel || operation == .forbidden { onCancelledDrag() }
            // A successful destination drop still awaits its provider's token
            // decode; do not clear root dragToken before that async guard executes.
            if let heldID { onStationaryHold(heldID) }
        }
    }
}

#endif
