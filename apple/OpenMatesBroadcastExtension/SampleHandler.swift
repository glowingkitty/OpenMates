// ReplayKit Broadcast Upload Extension for live screen sharing in a voice call.
// Target: OpenMatesBroadcastExtension (also compiles NativeVoiceCallScreenShareShared.swift).
// Samples the screen at most once per second, downsizes to 1280x720, JPEG-encodes under
// 256 KiB (same limits as the web call camera, frontend/packages/ui/src/services/voiceCallCamera.ts)
// and hands the latest frame to the app through the App Group. No network, no other logic.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.video.apple-screen-share
import CoreImage
import CoreMedia
import Foundation
import ImageIO
import ReplayKit

final class SampleHandler: RPBroadcastSampleHandler, @unchecked Sendable {
    private typealias Shared = NativeVoiceCallScreenShareShared
    private let context = CIContext(options: [.cacheIntermediates: false])
    private var lastFrameTime: CFAbsoluteTime = 0

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        guard let directory = Shared.directoryURL() else {
            finishBroadcastWithError(NSError(domain: "org.openmates.app.broadcast", code: 1))
            return
        }
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        writeState("started")
    }

    override func broadcastFinished() {
        if let url = Shared.frameURL() { try? FileManager.default.removeItem(at: url) }
        writeState("finished")
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        let now = CFAbsoluteTimeGetCurrent()
        guard now - lastFrameTime >= Shared.minimumFrameInterval,
              let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastFrameTime = now
        var image = CIImage(cvPixelBuffer: pixels)
        if let raw = CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString, attachmentModeOut: nil)
            as? NSNumber, let orientation = CGImagePropertyOrientation(rawValue: raw.uint32Value) {
            image = image.oriented(orientation)
        }
        let extent = image.extent
        let scale = min(1, Shared.maximumEdgeWidth / extent.width, Shared.maximumEdgeHeight / extent.height)
        if scale < 1 { image = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale)) }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB), let jpeg = encode(image, space: space),
              let url = Shared.frameURL() else { return }
        let frame = Shared.Frame(jpeg: jpeg, capturedAtMilliseconds: UInt64(Date().timeIntervalSince1970 * 1000))
        do {
            // Atomic replace: the app never reads a half-written frame.
            try Shared.encode(frame).write(to: url, options: .atomic)
            Shared.postDarwinNotification(Shared.frameNotification)
        } catch {
            return
        }
    }

    private func encode(_ image: CIImage, space: CGColorSpace) -> Data? {
        for quality in Shared.jpegQualities {
            let options = [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: quality]
            if let data = context.jpegRepresentation(of: image, colorSpace: space, options: options),
               data.count <= Shared.maximumJPEGBytes { return data }
        }
        return nil
    }

    private func writeState(_ value: String) {
        if let url = Shared.stateURL() { try? Data(value.utf8).write(to: url, options: .atomic) }
        Shared.postDarwinNotification(Shared.stateNotification)
    }
}
