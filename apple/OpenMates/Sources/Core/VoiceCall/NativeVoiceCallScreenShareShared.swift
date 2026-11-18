// Shared by the app and the broadcast extension: frame file location and wire format.
// Targets: OpenMates (iOS), OpenMatesBroadcastExtension. Foundation only, no UI.
// Web counterpart of the frame limits: frontend/packages/ui/src/services/voiceCallCamera.ts
// (<=1280x720, JPEG quality 0.72/0.5/0.3, <=256 KiB decoded, one frame per second).
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.video.apple-screen-share
import Foundation

/// Location and encoding of the latest shared-screen frame in the App Group.
enum NativeVoiceCallScreenShareShared {
    static let appGroup = "group.org.openmates.app.shared"
    static let directoryName = "voice_call_screen_share"
    static let frameFileName = "latest_frame.bin"
    /// Posted by the extension after each new frame is written.
    static let frameNotification = "org.openmates.app.voicecall.screen_frame"
    /// Posted by the extension when the broadcast starts or finishes.
    static let stateNotification = "org.openmates.app.voicecall.screen_state"
    static let stateFileName = "broadcast_state"
    static let maximumEdgeWidth = 1280.0
    static let maximumEdgeHeight = 720.0
    static let maximumJPEGBytes = 256 * 1024
    static let jpegQualities: [Double] = [0.72, 0.5, 0.3]
    static let minimumFrameInterval: TimeInterval = 1.0
    /// A frame older than this is not offered to the model as the current screen.
    static let maximumFrameAge: TimeInterval = 5.0
    private static let magic: [UInt8] = [0x4F, 0x4D, 0x53, 0x46] // "OMSF"

    struct Frame: Equatable, Sendable {
        let jpeg: Data
        /// Milliseconds since 1970, matching the web `captured_at`.
        let capturedAtMilliseconds: UInt64
    }

    static func directoryURL() -> URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)?
            .appendingPathComponent(directoryName, isDirectory: true)
    }

    static func frameURL() -> URL? { directoryURL()?.appendingPathComponent(frameFileName) }
    static func stateURL() -> URL? { directoryURL()?.appendingPathComponent(stateFileName) }

    /// Layout: "OMSF" + big-endian UInt64 capture time (ms) + JPEG bytes.
    static func encode(_ frame: Frame) -> Data {
        var data = Data(magic)
        var value = frame.capturedAtMilliseconds.bigEndian
        withUnsafeBytes(of: &value) { data.append(contentsOf: $0) }
        data.append(frame.jpeg)
        return data
    }

    static func decode(_ data: Data) -> Frame? {
        guard data.count > 12, Array(data.prefix(4)) == magic else { return nil }
        let milliseconds = data.subdata(in: 4..<12).reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
        let jpeg = data.subdata(in: 12..<data.count)
        guard jpeg.count <= maximumJPEGBytes, jpeg.prefix(3) == Data([0xFF, 0xD8, 0xFF]) else { return nil }
        return Frame(jpeg: jpeg, capturedAtMilliseconds: milliseconds)
    }

    static func postDarwinNotification(_ name: String) {
        CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(name as CFString), nil, nil, true)
    }
}
