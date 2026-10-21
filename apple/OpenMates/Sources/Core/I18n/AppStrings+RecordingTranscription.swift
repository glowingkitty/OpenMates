// Native-only recording STT choices; keys supplied separately for root's i18n generation.
import Foundation

extension AppStrings {
    static var recordingTranscriptionTitle: String { LocalizationManager.shared.text("apple.recording_transcription.title") }
    static var recordingWhistleName: String { LocalizationManager.shared.text("apple.recording_transcription.whistle") }
    static var recordingWhistleIncluded: String { LocalizationManager.shared.text("apple.recording_transcription.included") }
    static var recordingWhistleUnavailable: String { LocalizationManager.shared.text("apple.recording_transcription.unavailable") }
    static var recordingWhistleMemory: String { LocalizationManager.shared.text("apple.recording_transcription.memory") }
    static var recordingBundledSize: String { LocalizationManager.shared.text("apple.recording_transcription.bundled_size") }
    static var recordingBlockedByCall: String { LocalizationManager.shared.text("apple.recording_transcription.blocked_by_call") }
    static func recordingTranscriptionLabel(_ choice: RecordingTranscriptionPreference) -> String {
        LocalizationManager.shared.text("apple.recording_transcription.choice.\(choice.rawValue)")
    }
    static func recordingTranscriptionDescription(_ choice: RecordingTranscriptionPreference) -> String {
        LocalizationManager.shared.text("apple.recording_transcription.description.\(choice.rawValue)")
    }
}
