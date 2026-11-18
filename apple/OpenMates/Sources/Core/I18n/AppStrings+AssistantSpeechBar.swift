// Accessibility labels of the assistant voice response player (chat.assistant_speech.* keys, shared with web).
import Foundation
extension AppStrings {
    static var assistantSpeechPlayerLabel: String { localized("chat.assistant_speech.player_label") }
    static var assistantSpeechPause: String { localized("chat.assistant_speech.pause") }
    static var assistantSpeechPlay: String { localized("chat.assistant_speech.play") }
    static func assistantSpeechPreviousChapter(_ chapter: String) -> String {
        LocalizationManager.shared.text("chat.assistant_speech.previous_chapter", replacements: ["chapter": chapter])
    }
    static func assistantSpeechNextChapter(_ chapter: String) -> String {
        LocalizationManager.shared.text("chat.assistant_speech.next_chapter", replacements: ["chapter": chapter])
    }
}
