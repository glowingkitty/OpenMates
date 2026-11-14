// Video timeline string accessors for the native app.
//
// Source keys: frontend/packages/ui/src/i18n/sources/embeds/video_generate.yml
// (existing keys only; no new keys are introduced).

import Foundation

extension AppStrings {
    static var videoTimeline: String { LocalizationManager.shared.text("embeds.video_generate.timeline") }
    static var videoTimelineClip: String { LocalizationManager.shared.text("embeds.video_generate.clip") }
    static func videoTimelinePartAria(label: String, start: String, end: String) -> String {
        LocalizationManager.shared.text(
            "embeds.video_generate.part_aria",
            replacements: ["label": label, "start": start, "end": end]
        )
    }
    static func videoTimelineAudioTrack(_ kind: String) -> String {
        LocalizationManager.shared.text("embeds.video_generate.timeline_audio_\(kind)")
    }
}
