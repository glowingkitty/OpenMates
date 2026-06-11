// Remotion video-create string accessors for the native app.
//
// Keeps the code-backed video embed UI labels typed while avoiding hardcoded
// user-visible strings in Swift renderers.
//
// Source keys: frontend/packages/ui/src/i18n/sources/app_skills/videos.yml

import Foundation

extension AppStrings {
    static var videoCreate: String { L("app_skills.videos.create") }
    static var videoCreateVideo: String { L("app_skills.videos.create.view.video") }
    static var videoCreateTimeline: String { L("app_skills.videos.create.view.timeline") }
    static var videoCreateCode: String { L("app_skills.videos.create.view.code") }
    static var videoCreateStatusRendering: String { L("app_skills.videos.create.status.rendering") }
    static var videoCreateStatusProcessing: String { L("app_skills.videos.create.status.processing") }
    static var videoCreateStatusCancelled: String { L("app_skills.videos.create.status.cancelled") }
    static var videoCreateStatusNeedsRerender: String { L("app_skills.videos.create.status.needs_rerender") }
    static var videoCreateStatusError: String { L("app_skills.videos.create.status.error") }
    static var videoCreateStatusUnavailable: String { L("app_skills.videos.create.status.unavailable") }
    static var videoCreateActionRerender: String { L("app_skills.videos.create.action.rerender") }
    static var videoCreateActionRenderThisVersion: String { L("app_skills.videos.create.action.render_this_version") }
    static var videoCreateActionStopRender: String { L("app_skills.videos.create.action.stop_render") }

    static func videoCreateHeaderSubtitle(version: String, status: String) -> String {
        LocalizationManager.shared.text(
            "app_skills.videos.create.header.subtitle",
            replacements: ["version": version, "status": status]
        )
    }
}
