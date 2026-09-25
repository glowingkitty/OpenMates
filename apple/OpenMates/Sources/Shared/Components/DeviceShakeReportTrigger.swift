// Privacy-safe iPhone shake detection for opening the existing Report Issue flow.
// The detector records only an event category and never inspects screen, chat,
// input, clipboard, sensor, or account content.

// Specification: specifications/features/issue-reporting/specification.yml
// Assertions: issue-reporting.entry.device-shake

import SwiftUI

struct DeviceShakeReportGate {
    static let minimumInterval: TimeInterval = 1.5

    private(set) var lastActivation: TimeInterval?

    mutating func shouldActivate(at timestamp: TimeInterval) -> Bool {
        if let lastActivation,
           timestamp - lastActivation < Self.minimumInterval {
            return false
        }
        lastActivation = timestamp
        return true
    }
}

enum DeviceShakeReportTesting {
    static let triggerLaunchArgument = "--ui-test-trigger-device-shake-report"
}

#if os(iOS)
import UIKit

private struct DeviceShakeReportDetector: UIViewControllerRepresentable {
    let onShake: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onShake: onShake)
    }

    func makeUIViewController(context: Context) -> ShakeResponderViewController {
        let controller = ShakeResponderViewController()
        controller.onShake = { context.coordinator.handleShake() }
        return controller
    }

    func updateUIViewController(_ uiViewController: ShakeResponderViewController, context: Context) {
        context.coordinator.onShake = onShake
    }

    final class Coordinator {
        var onShake: () -> Void
        private var gate = DeviceShakeReportGate()

        init(onShake: @escaping () -> Void) {
            self.onShake = onShake
        }

        func handleShake(now: TimeInterval = ProcessInfo.processInfo.systemUptime) {
            guard gate.shouldActivate(at: now) else { return }
            NativeDiagnostics.event("device_shake", category: "report_issue")
            onShake()
        }
    }
}

private final class ShakeResponderViewController: UIViewController {
    var onShake: (() -> Void)?
    #if DEBUG
    private var hasTriggeredUITestShake = false
    #endif

    override var canBecomeFirstResponder: Bool { true }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        becomeFirstResponder()
        #if DEBUG
        if !hasTriggeredUITestShake,
           ProcessInfo.processInfo.arguments.contains(DeviceShakeReportTesting.triggerLaunchArgument) {
            hasTriggeredUITestShake = true
            onShake?()
        }
        #endif
    }

    override func viewWillDisappear(_ animated: Bool) {
        resignFirstResponder()
        super.viewWillDisappear(animated)
    }

    override func motionEnded(_ motion: UIEvent.EventSubtype, with event: UIEvent?) {
        guard motion == .motionShake else {
            super.motionEnded(motion, with: event)
            return
        }
        onShake?()
    }
}
#endif

extension View {
    /// Opens Report Issue from a physical iPhone shake. The modifier is a no-op
    /// on platforms that do not deliver UIKit motion events.
    @ViewBuilder
    func onDeviceShakeToReportIssue(perform action: @escaping () -> Void) -> some View {
        #if os(iOS)
        background {
            DeviceShakeReportDetector(onShake: action)
                .frame(width: 0, height: 0)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
        #else
        self
        #endif
    }
}
