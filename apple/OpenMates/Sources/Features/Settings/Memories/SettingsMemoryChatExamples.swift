// Web source: frontend/packages/ui/src/demo_chats/data/example_chats/memory-*.ts,
// frontend/packages/ui/src/components/settings/ChatPreviewCard.svelte.
// Public example metadata only; no chat plaintext is copied or persisted.
import Foundation

struct SettingsMemoryChatExample: Identifiable, Sendable {
    let id: String
    let titleKey: String
    let summaryKey: String
    let icon: String
    @MainActor var title: String { AppStrings.localized(titleKey) }
    @MainActor var summary: String { AppStrings.localized(summaryKey) }
}
enum SettingsMemoryChatExamples {
    static func examples(app: String, category: String) -> [SettingsMemoryChatExample] { byCategory["\(app).\(category)"] ?? [] }
    private static let byCategory: [String: [SettingsMemoryChatExample]] = [
        "books.currently_reading": [
            .init(id: "example-memory-books-currently-reading", titleKey: "example_chats.memory_books_currently_reading.title", summaryKey: "example_chats.memory_books_currently_reading.summary", icon: "book"),
        ],
        "books.favorite_books": [
            .init(id: "example-memory-books-favorite-books", titleKey: "example_chats.memory_books_favorite_books.title", summaryKey: "example_chats.memory_books_favorite_books.summary", icon: "book"),
        ],
        "books.to_read_list": [
            .init(id: "example-memory-books-to-read", titleKey: "example_chats.memory_books_to_read_list.title", summaryKey: "example_chats.memory_books_to_read_list.summary", icon: "task"),
        ],
        "code.coding_setup": [
            .init(id: "example-memory-code-coding-setup", titleKey: "example_chats.memory_code_coding_setup.title", summaryKey: "example_chats.memory_code_coding_setup.summary", icon: "coding"),
        ],
        "code.preferred_tech": [
            .init(id: "example-memory-code-preferred-tech", titleKey: "example_chats.memory_code_preferred_tech.title", summaryKey: "example_chats.memory_code_preferred_tech.summary", icon: "coding"),
        ],
        "code.projects": [
            .init(id: "example-memory-code-projects", titleKey: "example_chats.memory_code_projects.title", summaryKey: "example_chats.memory_code_projects.summary", icon: "project"),
        ],
        "code.want_to_learn": [
            .init(id: "example-memory-code-want-to", titleKey: "example_chats.memory_code_want_to_learn.title", summaryKey: "example_chats.memory_code_want_to_learn.summary", icon: "library"),
        ],
        "docs.writing_style": [
            .init(id: "example-memory-docs-writing-style", titleKey: "example_chats.memory_docs_writing_style.title", summaryKey: "example_chats.memory_docs_writing_style.summary", icon: "docs"),
        ],
        "events.saved_events": [
            .init(id: "example-memory-events-saved-events", titleKey: "example_chats.memory_events_saved_events.title", summaryKey: "example_chats.memory_events_saved_events.summary", icon: "events"),
        ],
        "health.appointments": [
            .init(id: "example-memory-health-appointments", titleKey: "example_chats.memory_health_appointments.title", summaryKey: "example_chats.memory_health_appointments.summary", icon: "heart"),
        ],
        "health.medical_history": [
            .init(id: "example-memory-health-medical-history", titleKey: "example_chats.memory_health_medical_history.title", summaryKey: "example_chats.memory_health_medical_history.summary", icon: "heart"),
        ],
        "home.saved_listings": [
            .init(id: "example-memory-home-saved-listings", titleKey: "example_chats.memory_home_saved_listings.title", summaryKey: "example_chats.memory_home_saved_listings.summary", icon: "home"),
        ],
        "images.preferred_styles": [
            .init(id: "example-memory-images-preferred-styles", titleKey: "example_chats.memory_images_preferred_styles.title", summaryKey: "example_chats.memory_images_preferred_styles.summary", icon: "image"),
        ],
        "mail.writing_styles": [
            .init(id: "example-memory-mail-writing-styles", titleKey: "example_chats.memory_mail_writing_styles.title", summaryKey: "example_chats.memory_mail_writing_styles.summary", icon: "mail"),
        ],
        "reminder.saved_item_reminder_defaults": [
            .init(id: "example-memory-reminder-defaults", titleKey: "example_chats.memory_reminder_defaults.title", summaryKey: "example_chats.memory_reminder_defaults.summary", icon: "reminder"),
        ],
        "study.learning_goals": [
            .init(id: "example-memory-study-learning-goals", titleKey: "example_chats.memory_study_learning_goals.title", summaryKey: "example_chats.memory_study_learning_goals.summary", icon: "study"),
        ],
        "travel.preferred_activities": [
            .init(id: "example-memory-travel-preferred-activities", titleKey: "example_chats.memory_travel_preferred_activities.title", summaryKey: "example_chats.memory_travel_preferred_activities.summary", icon: "planning"),
        ],
        "travel.preferred_airlines": [
            .init(id: "example-memory-travel-preferred-airlines", titleKey: "example_chats.memory_travel_preferred_airlines.title", summaryKey: "example_chats.memory_travel_preferred_airlines.summary", icon: "travel"),
        ],
        "travel.preferred_transport_methods": [
            .init(id: "example-memory-travel-preferred-transport", titleKey: "example_chats.memory_travel_preferred_transport.title", summaryKey: "example_chats.memory_travel_preferred_transport.summary", icon: "travel"),
        ],
        "travel.saved_connections": [
            .init(id: "example-memory-travel-saved-connections", titleKey: "example_chats.memory_travel_saved_connections.title", summaryKey: "example_chats.memory_travel_saved_connections.summary", icon: "travel"),
        ],
        "travel.saved_stays": [
            .init(id: "example-memory-travel-saved-stays", titleKey: "example_chats.memory_travel_saved_stays.title", summaryKey: "example_chats.memory_travel_saved_stays.summary", icon: "home"),
        ],
        "travel.trips": [
            .init(id: "example-memory-travel-trips", titleKey: "example_chats.memory_travel_trips.title", summaryKey: "example_chats.memory_travel_trips.summary", icon: "travel"),
        ],
        "tv.to_watch_list": [
            .init(id: "example-memory-tv-to-watch", titleKey: "example_chats.memory_tv_to_watch_list.title", summaryKey: "example_chats.memory_tv_to_watch_list.summary", icon: "task"),
        ],
        "tv.watched_movies": [
            .init(id: "example-memory-tv-watched-movies", titleKey: "example_chats.memory_tv_watched_movies.title", summaryKey: "example_chats.memory_tv_watched_movies.summary", icon: "movies"),
        ],
        "tv.watched_tv_shows": [
            .init(id: "example-memory-tv-watched-shows", titleKey: "example_chats.memory_tv_watched_shows.title", summaryKey: "example_chats.memory_tv_watched_shows.summary", icon: "tv"),
        ],
        "videos.to_watch_list": [
            .init(id: "example-memory-videos-to-watch", titleKey: "example_chats.memory_videos_to_watch_list.title", summaryKey: "example_chats.memory_videos_to_watch_list.summary", icon: "videos"),
        ],
        "web.bookmarks": [
            .init(id: "example-memory-web-bookmarks", titleKey: "example_chats.memory_web_bookmarks.title", summaryKey: "example_chats.memory_web_bookmarks.summary", icon: "web"),
        ],
        "web.read_later": [
            .init(id: "example-memory-web-read-later", titleKey: "example_chats.memory_web_read_later.title", summaryKey: "example_chats.memory_web_read_later.summary", icon: "task"),
        ],
    ]
}
