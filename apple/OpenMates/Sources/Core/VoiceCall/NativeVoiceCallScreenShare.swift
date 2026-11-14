// Live screen sharing in a call (iOS): system broadcast picker + App Group frame reader.
// Target: OpenMates iOS. The extension (OpenMatesBroadcastExtension) writes one JPEG per second;
// this file exposes the newest one for `voice_source_frame` requests with source "screen".
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/voicecall/VoiceCallBar.svelte (camera toggle states:
//          off / on / denied-or-failed notice; the web has no screen-share button yet, so the
//          screen button mirrors the camera button treatment)
// Logic:   frontend/packages/ui/src/services/voiceCallCamera.ts, voiceCall.ts (source: 'screen')
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-strip-layout, video-call.video.apple-screen-share
#if os(iOS)
import Foundation
import ReplayKit
import SwiftUI
import UIKit

/// Watches the App Group frame file and keeps the latest screen frame.
@MainActor
final class NativeVoiceCallScreenShareReader: ObservableObject {
    private typealias Shared = NativeVoiceCallScreenShareShared
    /// True between the extension's "started" and "finished" state.
    @Published private(set) var isBroadcasting = false
    @Published private(set) var latestFrame: NativeVoiceCallScreenShareShared.Frame?
    private var observing = false

    /// Begin observing Darwin notifications from the extension. Call when a call goes live.
    func start() {
        guard !observing else { return }
        observing = true
        let pointer = Unmanaged.passUnretained(self).toOpaque()
        let center = CFNotificationCenterGetDarwinNotifyCenter()
        for name in [Shared.frameNotification, Shared.stateNotification] {
            CFNotificationCenterAddObserver(center, pointer, { _, observer, name, _, _ in
                guard let observer, let name else { return }
                let reader = Unmanaged<NativeVoiceCallScreenShareReader>.fromOpaque(observer)
                let isFrame = name.rawValue as String == NativeVoiceCallScreenShareShared.frameNotification
                Task { @MainActor in reader.takeUnretainedValue().refresh(frameChanged: isFrame) }
            }, name as CFString, nil, .deliverImmediately)
        }
        refresh(frameChanged: true)
        refresh(frameChanged: false)
    }

    /// Stop observing and drop the frame. Call on hang-up.
    func stop() {
        guard observing else { return }
        observing = false
        CFNotificationCenterRemoveEveryObserver(CFNotificationCenterGetDarwinNotifyCenter(),
            Unmanaged.passUnretained(self).toOpaque())
        isBroadcasting = false
        latestFrame = nil
    }

    /// The latest broadcast frame, sent to the broker as a `camera_frame` with source
    /// "screen" (the broker picks the turn's source frame and asks the app to save it).
    /// Nil when sharing is off or the frame is older than the broker accepts.
    func freshFrame(now: Date = Date()) -> NativeVoiceCallScreenShareShared.Frame? {
        guard isBroadcasting, let frame = latestFrame else { return nil }
        let age = now.timeIntervalSince1970 - Double(frame.capturedAtMilliseconds) / 1000
        guard age <= Shared.maximumFrameAge else { return nil }
        return frame
    }

    private func refresh(frameChanged: Bool) {
        if frameChanged {
            if let url = Shared.frameURL(), let data = try? Data(contentsOf: url) {
                latestFrame = Shared.decode(data)
            } else {
                latestFrame = nil
            }
        } else if let url = Shared.stateURL(), let data = try? Data(contentsOf: url) {
            isBroadcasting = String(data: data, encoding: .utf8) == "started"
        } else {
            isBroadcasting = false
        }
    }
}

/// `RPSystemBroadcastPickerView` limited to the broadcast extension. The system shows its own
/// start sheet; ReplayKit gives the app no callback for a cancelled picker.
struct NativeVoiceCallBroadcastPicker: UIViewRepresentable {
    /// Bundle id of the OpenMatesBroadcastExtension target.
    static let extensionBundleIdentifier = "org.openmates.app.broadcast"
    /// Incremented by the owner to open the system picker programmatically.
    var trigger: Int

    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 1, height: 1))
        picker.preferredExtension = Self.extensionBundleIdentifier
        picker.showsMicrophoneButton = false
        picker.alpha = 0.01
        return picker
    }

    func updateUIView(_ picker: RPSystemBroadcastPickerView, context: Context) {
        guard trigger != context.coordinator.lastTrigger else { return }
        context.coordinator.lastTrigger = trigger
        guard trigger > 0 else { return }
        // The picker has no public "present" API; its inner button starts the sheet.
        for case let button as UIButton in picker.subviews { button.sendActions(for: .touchUpInside) }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var lastTrigger = 0 }
}

/// Screen-share button for the call strip, same size and tokens as the camera button.
/// States: off (tap opens the system picker), on (tap opens it again to stop; the system
/// sheet owns stopping), failed notice is shown through the shared call notice line.
struct NativeVoiceCallScreenShareButton: View {
    @ObservedObject var reader: NativeVoiceCallScreenShareReader
    @State private var trigger = 0
    var body: some View {
        ZStack {
            NativeVoiceCallBroadcastPicker(trigger: trigger).frame(width: 1, height: 1).allowsHitTesting(false)
            OMIconButton(icon: "desktop",
                         label: reader.isBroadcasting ? AppStrings.nativeCall("screen_share_off")
                                                      : AppStrings.nativeCall("screen_share_on"),
                         isProminent: reader.isBroadcasting) { trigger += 1 }
                .accessibilityIdentifier("voice-call-screen-share")
        }
    }
}
#endif
