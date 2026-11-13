// Listener adapter of the Rust view-model core (`ViewModelCore`, plan
// apple-client-core-migration A2 lane L8): receives each `ViewEventRecord` on a
// core thread and delivers it on the main actor, in the order the core emitted
// it. No state and no logic: the records are the core's view model unchanged.
// Not used by app screens yet (step A4).
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.apple.strangler-order

import Foundation

final class CoreViewEventRelay: ViewListener, @unchecked Sendable {
    private let deliver: @MainActor @Sendable (ViewEventRecord) -> Void

    /// `deliver` runs on the main actor once per event, in core order.
    init(deliver: @escaping @MainActor @Sendable (ViewEventRecord) -> Void) {
        self.deliver = deliver
    }

    func onEvent(event: ViewEventRecord) {
        // One FIFO main-queue hop per event keeps the core's order; the core
        // thread never waits for the UI.
        let deliver = self.deliver
        DispatchQueue.main.async {
            MainActor.assumeIsolated { deliver(event) }
        }
    }
}
