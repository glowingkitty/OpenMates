// Video button and live camera preview of the Apple voice call.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/voicecall/VoiceCallBar.svelte (data-testid voice-call-video, .camera-active)
//          frontend/packages/ui/src/components/voicecall/VoiceCallMedia.svelte (preview, flip, expand)
// CSS:     same files: .call-media (height min(60dvh,32rem), collapsed 6rem, radius-6, grey-90),
//          .round (2.5rem circle, grey-0), .flip top/left spacing-4, .expand bottom/right spacing-4
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Logic:   frontend/packages/ui/src/services/voiceCall.ts (setCameraEnabled, flipCamera, 2 s auto-collapse)
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.video.input-and-output, video-call.chat.call-strip-layout
#if !os(watchOS)
import AVFoundation
import SwiftUI

/// Camera state of a running call (web `cameraEnabled`/`cameraPending`/`cameraError`).
@MainActor
final class NativeVoiceCallCameraModel: ObservableObject {
    @Published private(set) var enabled = false
    @Published private(set) var pending = false
    @Published private(set) var error: NativeVoiceCallCameraError?
    @Published private(set) var session: AVCaptureSession?
    @Published var expanded = true
    @Published private(set) var mirrored = true

    private var camera: NativeVoiceCallCamera?
    private var generation = 0
    private var collapse: Task<Void, Never>?
    private let sendState: @MainActor (Bool) async -> Void
    private let sendFrame: @MainActor (NativeVoiceCallCameraFrame) async -> Void

    /// `sendState` writes `camera_state`, `sendFrame` writes `camera_frame` (see handback hookup).
    init(sendState: @escaping @MainActor (Bool) async -> Void,
         sendFrame: @escaping @MainActor (NativeVoiceCallCameraFrame) async -> Void) {
        self.sendState = sendState
        self.sendFrame = sendFrame
    }

    func toggle() async { await setEnabled(!enabled && !pending) }

    func setEnabled(_ on: Bool) async {
        if !on {
            generation += 1
            camera?.stop(); camera = nil
            collapse?.cancel()
            enabled = false; pending = false; session = nil
            await sendState(false)
            return
        }
        guard !enabled, !pending else { return }
        generation += 1
        let mine = generation
        #if os(iOS)
        let preferred = AVCaptureDevice.Position.back
        #else
        let preferred = AVCaptureDevice.Position.front
        #endif
        let camera = NativeVoiceCallCamera(
            position: preferred,
            onFrame: { [weak self] frame in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == mine, self.enabled else { return }
                    await self.sendFrame(frame)
                }
            },
            onError: { [weak self] failure in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == mine else { return }
                    await self.fail(failure)
                }
            })
        self.camera = camera
        error = nil; pending = true
        do {
            try await camera.start()
            guard generation == mine else { camera.stop(); return }
            session = camera.session
            mirrored = camera.position == .front
            enabled = true; pending = false; expanded = true
            await sendState(true)
            scheduleCollapse(mine)
        } catch {
            guard generation == mine else { return }
            await fail((error as? NativeVoiceCallCameraError) ?? .failed)
        }
    }

    func flip() async {
        guard enabled, !pending, let camera else { return }
        pending = true
        do {
            try await camera.flip()
            session = camera.session
            mirrored = camera.position == .front
            pending = false
        } catch { await fail((error as? NativeVoiceCallCameraError) ?? .failed) }
    }

    /// Call end or controller teardown: stop silently, no wire message.
    func shutdown() {
        generation += 1
        camera?.stop(); camera = nil
        collapse?.cancel()
        enabled = false; pending = false; session = nil
    }

    private func fail(_ failure: NativeVoiceCallCameraError) async {
        camera?.stop(); camera = nil
        collapse?.cancel()
        enabled = false; pending = false; session = nil
        error = failure
        await sendState(false)
    }

    private func scheduleCollapse(_ mine: Int) {
        collapse?.cancel()
        collapse = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled, let self, self.generation == mine else { return }
            self.expanded = false
        }
    }
}

/// The Video button of the call strip (web `voice-call-video`, `.round` 44pt on the gradient bar).
struct NativeVoiceCallVideoButton: View {
    @ObservedObject var model: NativeVoiceCallCameraModel
    let cameraAvailable: Bool
    let live: Bool
    var body: some View {
        Button { Task { await model.toggle() } } label: {
            Icon("videocall", size: 28).foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(.white.opacity(model.enabled ? 0.4 : 0.2)).clipShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(!live || !cameraAvailable)
        .accessibilityLabel(AppStrings.nativeCall(model.enabled ? "camera_off" : "video_call"))
        .accessibilityAddTraits(model.enabled ? .isSelected : [])
        .accessibilityIdentifier("voice-call-video")
    }
}

/// The live preview (web `voice-call-media` with `voice-call-camera-preview`).
struct NativeVoiceCallCameraPreview: View {
    @ObservedObject var model: NativeVoiceCallCameraModel
    var body: some View {
        if model.enabled, let session = model.session {
            ZStack {
                NativeVoiceCallCameraLayer(session: session, mirrored: model.mirrored)
                    .accessibilityLabel(AppStrings.nativeCall("camera_preview"))
                    .accessibilityIdentifier("voice-call-camera-preview")
                #if os(iOS)
                round("camera", id: "voice-call-camera-flip", label: "flip_camera") { Task { await model.flip() } }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                #endif
                round("up", id: "voice-call-media-expand", label: model.expanded ? "minimize" : "expand",
                      flipped: !model.expanded) { model.expanded.toggle() }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
            }
            .frame(maxWidth: .infinity)
            .frame(height: model.expanded ? 512 : 96)
            .background(Color.grey90)
            .clipShape(RoundedRectangle(cornerRadius: .radius6))
            .animation(.easeInOut(duration: 0.18), value: model.expanded)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("voice-call-media")
        }
    }

    private func round(_ icon: String, id: String, label: String, flipped: Bool = false,
                       action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 20).rotationEffect(.degrees(flipped ? 180 : 0)).foregroundStyle(Color.fontPrimary)
                .frame(width: 40, height: 40).background(Color.grey0).clipShape(Circle())
        }
        .buttonStyle(.plain).padding(.spacing4)
        .accessibilityLabel(AppStrings.nativeCall(label)).accessibilityIdentifier(id)
    }
}

/// Hosts an `AVCaptureVideoPreviewLayer` (platform video surface; aspect-fit like web `object-fit: contain`).
#if os(iOS)
private struct NativeVoiceCallCameraLayer: UIViewRepresentable {
    let session: AVCaptureSession
    let mirrored: Bool
    final class Host: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var preview: AVCaptureVideoPreviewLayer? { layer as? AVCaptureVideoPreviewLayer }
    }
    func makeUIView(context: Context) -> Host {
        let host = Host()
        host.preview?.videoGravity = .resizeAspect
        return host
    }
    func updateUIView(_ host: Host, context: Context) {
        host.preview?.session = session
        host.transform = CGAffineTransform(scaleX: mirrored ? -1 : 1, y: 1)
    }
}
#elseif os(macOS)
private struct NativeVoiceCallCameraLayer: NSViewRepresentable {
    let session: AVCaptureSession
    let mirrored: Bool
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        view.wantsLayer = true
        let layer = AVCaptureVideoPreviewLayer()
        layer.videoGravity = .resizeAspect
        view.layer = layer
        return view
    }
    func updateNSView(_ view: NSView, context: Context) {
        guard let layer = view.layer as? AVCaptureVideoPreviewLayer else { return }
        layer.session = session
        layer.setAffineTransform(CGAffineTransform(scaleX: mirrored ? -1 : 1, y: 1))
    }
}
#endif
#endif
