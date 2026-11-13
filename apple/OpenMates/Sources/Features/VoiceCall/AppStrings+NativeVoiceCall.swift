// Source keys: frontend/packages/ui/src/i18n/sources/voicecall.yml
#if !os(watchOS)
import Foundation
extension AppStrings {
    static func nativeCall(_ key: String) -> String { LocalizationManager.shared.text("voicecall." + key) }
    static func nativeCallError(_ error: NativeVoiceCallError) -> String {
        let key: String
        switch error {
        case .consentRequired: key = "privacy_title"
        case .consentUnavailable: key = "privacy_save_failed"
        case .contextUnavailable: key = "context_unavailable"
        case .contextTooLarge: key = "context_too_large"
        case .persistenceFailed: key = "transcript_save_failed"
        case .audioUnavailable, .audioQueueFull: key = "microphone_failed"
        case .scopeChanged: key = "session_expired"
        case .invalidResponse: key = "invalid_response"
        case .startupTimedOut: key = "connection_failed"
        case .connectionLost: key = "connection_lost"
        case .textRejected: key = "unsupported_content"
        case .endedInBackground: key = "ended_in_background"
        default: key = "call_unavailable"
        }
        return nativeCall(key)
    }
    static func nativeCallCameraNotice(_ notice: NativeVoiceCallCameraNotice) -> String { nativeCall(notice.rawValue) }
}
#endif
