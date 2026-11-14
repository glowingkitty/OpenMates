import Foundation

// The stored timeline is validated, sorted and defaulted by the shared Rust core
// (`video_timeline` in packages/openmates-apple-bindings, mirroring web
// normalizeTimeline). This file only adds identity and pure geometry on top of
// the generated records.
typealias VideoMadeBy = VideoMadeByRecord
typealias VideoTrackKind = VideoTrackKindRecord
typealias VideoPartKind = VideoPartKindRecord
typealias VideoAudioEntryKind = VideoAudioKindRecord
typealias VideoTimelinePart = VideoPartRecord
typealias VideoTimelineAudioEntry = VideoAudioEntryRecord
typealias VideoTimelineTrack = VideoTrackRecord

extension VideoAudioKindRecord: CaseIterable {
    public static var allCases: [VideoAudioKindRecord] { [.speech, .sound, .music] }
    var rowId: String {
        switch self {
        case .speech: "speech"
        case .sound: "sound"
        case .music: "music"
        }
    }
}
extension VideoPartRecord: Identifiable {}
extension VideoAudioEntryRecord: Identifiable {}
extension VideoTrackRecord: Identifiable {}

struct VideoTimelineAudioRow: Equatable, Identifiable, Sendable {
    let kind: VideoAudioEntryKind
    let entries: [VideoTimelineAudioEntry]
    var id: String { kind.rowId }
}

struct VideoTimelineModel: Equatable, Sendable {
    static let defaultFps = 30
    /// Ruler steps in seconds; the first one giving at most eight marks wins.
    static let rulerSteps = [1, 2, 5, 10, 15, 30, 60, 120, 300]

    let record: VideoTimelineRecord

    var fps: Int { Int(record.fps) }
    var durationInFrames: Int { Int(record.durationInFrames) }
    var width: Int { Int(record.width) }
    var height: Int { Int(record.height) }
    var madeBy: VideoMadeBy { record.madeBy }
    var tracks: [VideoTimelineTrack] { record.tracks }
    var audio: [VideoTimelineAudioEntry] { record.audio }

    // MARK: Geometry (VideoTimeline.svelte)

    var totalFrames: Int { max(1, durationInFrames) }
    var totalSeconds: Double { Double(totalFrames) / Double(fps) }

    /// Position of a frame as a 0...1 fraction of the timeline width.
    func fraction(ofFrame frames: UInt32) -> Double { Double(frames) / Double(totalFrames) }

    /// Playhead position as a 0...1 fraction, clamped like the web playhead.
    func playheadFraction(currentTime: Double) -> Double {
        min(max(currentTime / totalSeconds, 0), 1)
    }

    /// Time in seconds for a pointer position given as a 0...1 ratio of the bar.
    func seekTime(ratio: Double) -> Double { min(1, max(0, ratio)) * totalSeconds }

    /// Ruler marks in seconds.
    var rulerMarks: [Int] {
        let step = Self.rulerSteps.first { totalSeconds / Double($0) <= 8 } ?? 600
        let count = Int(totalSeconds / Double(step))
        return (0...count).map { $0 * step }
    }

    /// Audio rows: one per kind that has entries, below the tracks.
    var audioRows: [VideoTimelineAudioRow] {
        VideoAudioEntryKind.allCases.compactMap { kind in
            let entries = audio.filter { $0.kind == kind }
            return entries.isEmpty ? nil : VideoTimelineAudioRow(kind: kind, entries: entries)
        }
    }

    func showsTrackNames(compact: Bool) -> Bool {
        !compact && (tracks.count > 1 || !audioRows.isEmpty)
    }

    /// Whether a part of the given width fraction shows its label.
    static func showsLabel(widthFraction: Double, compact: Bool) -> Bool {
        (!compact || widthFraction * 100 > 15) && widthFraction * 100 >= 7
    }

    /// Whether a part of the given width fraction shows its length.
    static func showsLength(widthFraction: Double, compact: Bool) -> Bool {
        !compact && widthFraction * 100 >= 16
    }

    // MARK: Text

    /// "8 s", "1:05" style length for labels.
    static func formatSeconds(_ seconds: Double) -> String {
        let rounded = (seconds * 10).rounded(.toNearestOrAwayFromZero) / 10
        if rounded >= 60 {
            let minutes = Int(rounded / 60)
            let rest = Int((rounded - Double(minutes) * 60).rounded(.toNearestOrAwayFromZero))
            return "\(minutes):" + (rest < 10 ? "0\(rest)" : "\(rest)")
        }
        if rounded == rounded.rounded() { return "\(Int(rounded)) s" }
        return String(format: "%.1f s", rounded)
    }

    /// Start and end labels of a range in frames.
    func rangeLabels(from: UInt32, durationInFrames: UInt32) -> (start: String, end: String) {
        (
            Self.formatSeconds(Double(from) / Double(fps)),
            Self.formatSeconds(Double(from + durationInFrames) / Double(fps))
        )
    }

    // MARK: Decoding (normalizeTimeline / synthesizeTimeline)

    /// The stored timeline of decoded embed content, or nil when there is none (older videos).
    /// Stored timeline, else a one-clip timeline, else nil: decided by the core.
    static func resolve(content: [String: AnyCodable], loadedSeconds: Double, clipLabel: String) -> VideoTimelineModel? {
        let plain = content.mapValues { $0.value }
        guard JSONSerialization.isValidJSONObject(plain),
              let data = try? JSONSerialization.data(withJSONObject: plain),
              let json = String(data: data, encoding: .utf8),
              let record = videoTimeline(contentJson: json, loadedSeconds: loadedSeconds, clipLabel: clipLabel)
        else { return nil }
        return VideoTimelineModel(record: record)
    }
}
