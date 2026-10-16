// Vertical Watch scrolling driven by the real ScrollView's geometry and a
// focused, explicit Crown binding. Content remains caller-owned and can be lazy.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/tasks/TaskBoard.svelte
//         frontend/packages/ui/src/components/workflows/WorkflowGraphRenderer.svelte
// Native difference: Digital Crown input moves the visible vertical viewport.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.lists.read-only-private, apple-watch.workflows.compact-editor.
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Callers deactivate this view when a menu, another page, or text input owns
/// focus. Keep identity stable for the same column/graph, and change it when the
/// actual content identity changes. External ScrollViewReader.scrollTo and touch
/// scrolling remain authoritative through the native geometry callbacks.
struct WatchCrownScrollView<Content: View>: View {
    let active: Bool
    let identity: String
    let externalScrollRevision: Int
    private let content: () -> Content

    init(active: Bool, identity: String, externalScrollRevision: Int = 0,
         @ViewBuilder content: @escaping () -> Content) {
        self.active = active
        self.identity = identity
        self.externalScrollRevision = externalScrollRevision
        self.content = content
    }

    @ViewBuilder var body: some View {
        if #available(watchOS 11.0, *) {
            WatchPositionedCrownScrollView(active: active,
                externalScrollRevision: externalScrollRevision, content: content)
                .id(identity)
        } else {
            // Retain native scrolling on the supported watchOS 10 baseline.
            // Continuous position/geometry APIs are unavailable there.
            ScrollView(.vertical) { content() }
                .id(identity)
        }
    }
}

@available(watchOS 11.0, *)
private struct WatchPositionedCrownScrollView<Content: View>: View {
    let active: Bool
    let externalScrollRevision: Int
    let content: () -> Content
    @FocusState private var crownFocused: Bool
    @State private var position = ScrollPosition()
    @State private var crownValue = 0.0
    @State private var geometry = CrownScrollGeometry.empty
    @State private var pendingOffset: CGFloat?
    @State private var touchScrolling = false

    var body: some View {
        ScrollView(.vertical) { content() }
            .scrollPosition($position)
            .onScrollGeometryChange(for: CrownScrollGeometry.self) { geometry in
                CrownScrollGeometry(geometry)
            } action: { _, updated in
                acceptGeometry(updated)
            }
            .onScrollPhaseChange { _, phase in
                // Finger tracking/deceleration and external animated scrollTo
                // supersede any prior Crown command. None writes Crown state.
                switch phase {
                case .tracking, .interacting, .decelerating:
                    touchScrolling = true
                    pendingOffset = nil
                case .animating:
                    touchScrolling = false
                    pendingOffset = nil
                case .idle:
                    touchScrolling = false
                @unknown default:
                    touchScrolling = false
                    pendingOffset = nil
                }
            }
            .focusable(active)
            .focused($crownFocused)
            .digitalCrownRotation(crownBinding, onIdle: { pendingOffset = nil })
            .onAppear { crownFocused = active }
            .onChange(of: active) { _, isActive in
                pendingOffset = nil
                crownFocused = isActive
            }
            .onChange(of: externalScrollRevision) { _, _ in
                // An immediate ScrollViewReader jump may have no animated
                // scroll phase. Its new geometry owns the next Crown delta.
                pendingOffset = nil
            }
            .onDisappear {
                pendingOffset = nil
                crownFocused = false
            }
    }

    private var crownBinding: Binding<Double> {
        Binding(get: { crownValue }, set: { value in
            guard value.isFinite else { return }
            // The public Watch XCTest rotation uses negative input for down.
            // Its unbounded binding already reports point-sized deltas.
            let delta = CGFloat(crownValue - value)
            crownValue = value
            guard active, crownFocused, !touchScrolling, geometry.isReady,
                  delta.isFinite else { return }
            let start = pendingOffset ?? geometry.offset
            let target = geometry.clamp(start + delta)
            guard abs(target - start) > 0.01 else { return }
            pendingOffset = target
            scroll(to: target)
        })
    }

    private func acceptGeometry(_ updated: CrownScrollGeometry) {
        geometry = updated
        guard active, let pendingOffset else { return }
        let clamped = updated.clamp(pendingOffset)
        if abs(updated.offset - clamped) < 1 {
            self.pendingOffset = nil
        } else if abs(clamped - pendingOffset) > 0.01 {
            // A shrinking/expanding lazy layout can alter the valid range.
            // Reissue only when bounds force a different target, not on every
            // intermediate callback from our own previous scroll command.
            self.pendingOffset = clamped
            scroll(to: clamped)
        }
    }

    private func scroll(to offset: CGFloat) {
        var transaction = Transaction(animation: nil)
        transaction.disablesAnimations = true
        withTransaction(transaction) { position.scrollTo(y: offset) }
    }
}

@available(watchOS 11.0, *)
private struct CrownScrollGeometry: Equatable {
    let offset: CGFloat
    let minimum: CGFloat
    let maximum: CGFloat
    let isReady: Bool

    static let empty = CrownScrollGeometry(offset: 0, minimum: 0, maximum: 0, isReady: false)

    init(_ geometry: ScrollGeometry) {
        let minimum = -geometry.contentInsets.top
        let maximum = max(minimum,
            geometry.contentSize.height + geometry.contentInsets.bottom - geometry.containerSize.height)
        self.minimum = minimum
        self.maximum = maximum
        offset = min(maximum, max(minimum, geometry.contentOffset.y))
        isReady = geometry.containerSize.height > 0 && geometry.contentSize.height.isFinite &&
            minimum.isFinite && maximum.isFinite && offset.isFinite
    }

    private init(offset: CGFloat, minimum: CGFloat, maximum: CGFloat, isReady: Bool) {
        self.offset = offset
        self.minimum = minimum
        self.maximum = maximum
        self.isReady = isReady
    }

    func clamp(_ offset: CGFloat) -> CGFloat { min(maximum, max(minimum, offset)) }
}
