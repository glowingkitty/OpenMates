// Strings of the Memory draft banner, draft diff and references hint. Keys
// already exist in frontend/packages/ui/src/i18n/sources/memories.yml.
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.suggestions.post-processor, app-memories.references.embeds

import Foundation

extension AppStrings {
    /// `memories.draft_unsaved`: banner above an unsaved suggestion.
    static var memoriesDraftUnsaved: String { localized("memories.draft_unsaved") }
    /// `memories.draft_current`: suffix of a diff heading ("Title: current").
    static var memoriesDraftCurrent: String { localized("memories.draft_current") }
    /// `memories.references_hint`: how to add an embed to a Memory.
    static var memoriesReferencesHint: String { localized("memories.references_hint") }
    /// `memories.practices`: heading of the Memory text.
    static var memoriesPractices: String { localized("memories.practices") }
}
