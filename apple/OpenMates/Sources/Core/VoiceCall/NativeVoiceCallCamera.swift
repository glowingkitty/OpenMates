// Camera capture for the Apple voice call (video input).
// Logic:   frontend/packages/ui/src/services/voiceCallCamera.ts (1 Hz sampling, 1280x720 bound,
//          JPEG quality ladder 0.72/0.5/0.3, 256 KiB cap) and voiceCall.ts setCameraEnabled
//          (camera_state / camera_frame messages, error mapping).
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.video.input-and-output, video-call.privacy
#if !os(watchOS)
import AVFoundation
import CoreImage
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Camera failures, using the web error codes so the same strings apply.
enum NativeVoiceCallCameraError: String, Error, Equatable, Sendable {
    /// The user (or the system) refused camera permission. Voice continues.
    case denied = "camera_denied"
    /// This device has no usable camera.
    case missing = "camera_missing"
    /// The camera could not start or stopped unexpectedly.
    case failed = "camera_failed"
}

/// One sampled, bounded JPEG observation (web `VoiceCallCameraFrame`).
struct NativeVoiceCallCameraFrame: Equatable, Sendable {
    let frameID: String
    let jpeg: Data
    /// Unix epoch milliseconds, like web `Date.now()`.
    let capturedAt: Int64
    let width: Int
    let height: Int
    /// Visual source the broker records with the frame: "camera", or "screen" for a
    /// frame from the iOS broadcast extension (backend voice_call_visuals.py).
    var source = "camera"
    /// The `camera_frame` wire message the broker accepts.
    func message(callID: String) -> NativeVoiceCallFrame {
        ["type": .string("camera_frame"), "call_id": .string(callID), "frame_id": .string(frameID),
         "data": .string(jpeg.base64EncodedString()), "captured_at": .number(Double(capturedAt)),
         "source": .string(source)]
    }
}

/// Bounds shared with web `voiceCallCamera.ts`.
enum NativeVoiceCallCameraLimits {
    static let maximumJPEGBytes = 256 * 1024
    static let maximumWidth = 1280
    static let maximumHeight = 720
    static let qualities: [Double] = [0.72, 0.5, 0.3]
    static let minimumInterval: TimeInterval = 1

    /// Fits the frame into 1280x720 without upscaling (web `Math.min(1, ...)`).
    static func scaledSize(width: Int, height: Int) -> (width: Int, height: Int) {
        guard width > 0, height > 0 else { return (1, 1) }
        let scale = min(1, Double(maximumWidth) / Double(width), Double(maximumHeight) / Double(height))
        return (max(1, Int((Double(width) * scale).rounded(.down))), max(1, Int((Double(height) * scale).rounded(.down))))
    }

    /// Walks the quality ladder and returns the first JPEG within the cap; `nil`
    /// (frame dropped, nothing sent) when even the lowest quality is too large.
    static func firstWithinCap(_ encode: (Double) -> Data?) -> Data? {
        for quality in qualities {
            guard let data = encode(quality), !data.isEmpty else { return nil }
            if data.count <= maximumJPEGBytes { return data }
        }
        return nil
    }
}

/// Admits at most one frame per second (web `now - lastCapture < 1000`).
struct NativeVoiceCallCameraPacer: Equatable, Sendable {
    private var last: TimeInterval?
    mutating func admit(now: TimeInterval) -> Bool {
        if let last, now - last < NativeVoiceCallCameraLimits.minimumInterval { return false }
        last = now
        return true
    }
    mutating func reset() { last = nil }
}

/// AVCaptureSession wrapper. All mutable state is confined to `queue`.
final class NativeVoiceCallCamera: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    typealias FrameHandler = @Sendable (NativeVoiceCallCameraFrame) -> Void
    typealias ErrorHandler = @Sendable (NativeVoiceCallCameraError) -> Void

    private let queue = DispatchQueue(label: "org.openmates.voicecall.camera")
    private let context = CIContext()
    private let onFrame: FrameHandler
    private let onError: ErrorHandler
    private var pacer = NativeVoiceCallCameraPacer()
    private var running = false
    private var observer: (any NSObjectProtocol)?
    /// The live session for a preview layer; set while the camera runs.
    private(set) var session: AVCaptureSession?
    private(set) var position: AVCaptureDevice.Position

    init(position: AVCaptureDevice.Position = .front, onFrame: @escaping FrameHandler, onError: @escaping ErrorHandler) {
        self.position = position
        self.onFrame = onFrame
        self.onError = onError
    }

    /// Requests permission if needed, then starts sampling. Throws a mapped error.
    func start() async throws {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: break
        case .notDetermined:
            guard await AVCaptureDevice.requestAccess(for: .video) else { throw NativeVoiceCallCameraError.denied }
        default: throw NativeVoiceCallCameraError.denied
        }
        let position = self.position
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, any Error>) in
            queue.async {
                do { try self.configureAndRun(position: position); continuation.resume() }
                catch { continuation.resume(throwing: error) }
            }
        }
    }

    func stop() {
        queue.sync { teardown() }
    }

    /// Switches front/rear (web `flip`). Rejects when the other camera is missing.
    func flip() async throws {
        stop()
        position = position == .front ? .back : .front
        try await start()
    }

    private func configureAndRun(position: AVCaptureDevice.Position) throws {
        teardown()
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: position)
                ?? AVCaptureDevice.default(for: .video) else { throw NativeVoiceCallCameraError.missing }
        let session = AVCaptureSession()
        session.beginConfiguration()
        if session.canSetSessionPreset(.hd1280x720) { session.sessionPreset = .hd1280x720 }
        guard let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) else {
            session.commitConfiguration()
            throw NativeVoiceCallCameraError.failed
        }
        session.addInput(input)
        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        guard session.canAddOutput(output) else {
            session.commitConfiguration()
            throw NativeVoiceCallCameraError.failed
        }
        session.addOutput(output)
        #if os(iOS)
        if let connection = output.connection(with: .video), connection.isVideoRotationAngleSupported(90) {
            connection.videoRotationAngle = 90
        }
        #endif
        session.commitConfiguration()
        observer = NotificationCenter.default.addObserver(
            forName: AVCaptureSession.runtimeErrorNotification, object: session, queue: nil
        ) { [weak self] _ in self?.queue.async { self?.failRunning() } }
        pacer.reset()
        self.session = session
        running = true
        session.startRunning()
        guard session.isRunning else {
            teardown()
            throw NativeVoiceCallCameraError.failed
        }
    }

    private func teardown() {
        running = false
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = nil
        session?.stopRunning()
        session = nil
    }

    private func failRunning() {
        guard running else { return }
        teardown()
        onError(.failed)
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard running, pacer.admit(now: ProcessInfo.processInfo.systemUptime),
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let capturedAt = Int64((Date().timeIntervalSince1970 * 1000).rounded())
        let image = CIImage(cvPixelBuffer: buffer)
        let size = NativeVoiceCallCameraLimits.scaledSize(width: Int(image.extent.width), height: Int(image.extent.height))
        let scale = Double(size.width) / max(1, Double(image.extent.width))
        let scaled = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { failRunning(); return }
        // Encoding from a bare CGImage carries no EXIF/GPS metadata (web strips it too).
        guard let jpeg = NativeVoiceCallCameraLimits.firstWithinCap({ Self.jpeg(cgImage, quality: $0) }) else { return }
        onFrame(NativeVoiceCallCameraFrame(frameID: UUID().uuidString.lowercased(), jpeg: jpeg, capturedAt: capturedAt,
                                           width: cgImage.width, height: cgImage.height))
    }

    private static func jpeg(_ image: CGImage, quality: Double) -> Data? {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(destination, image,
                                   [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        return CGImageDestinationFinalize(destination) ? data as Data : nil
    }
}
#endif
