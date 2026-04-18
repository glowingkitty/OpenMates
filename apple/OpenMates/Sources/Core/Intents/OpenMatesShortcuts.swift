// App Shortcuts provider — registers OpenMates intents with Siri and the
// Shortcuts app. These appear automatically under "OpenMates" in the Shortcuts
// app and can be triggered via Siri with the defined phrases.
//
// Apple caps AppShortcutsProvider at 10 AppShortcut entries. All other intents
// (30+ total) are still discoverable in the Shortcuts app via "Add Action" and
// can be added to Siri manually — they just don't get proactive phrase suggestions.
// We pick the 10 most voice-natural actions for the slots.
//
// Note: AppShortcut phrase parameters require AppEntity/AppEnum types,
// so we use plain phrases without parameter interpolation. Siri will
// prompt users for required values when triggered.

import AppIntents

struct OpenMatesShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        // 1. Core AI chat
        AppShortcut(
            intent: AskOpenMatesIntent(),
            phrases: [
                "Ask \(.applicationName)",
                "Question for \(.applicationName)",
            ],
            shortTitle: "Ask OpenMates",
            systemImageName: "bubble.left.and.text.bubble.right"
        )

        // 2. Daily Inspiration
        AppShortcut(
            intent: TodaysInspirationIntent(),
            phrases: [
                "Today's inspiration from \(.applicationName)",
                "Daily inspiration from \(.applicationName)",
            ],
            shortTitle: "Today's Inspiration",
            systemImageName: "lightbulb"
        )

        // 3. Web Search
        AppShortcut(
            intent: WebSearchIntent(),
            phrases: [
                "Search the web with \(.applicationName)",
                "\(.applicationName) web search",
            ],
            shortTitle: "Web Search",
            systemImageName: "globe"
        )

        // 4. News
        AppShortcut(
            intent: NewsSearchIntent(),
            phrases: [
                "Search news with \(.applicationName)",
                "\(.applicationName) news",
            ],
            shortTitle: "Search News",
            systemImageName: "newspaper"
        )

        // 5. Events
        AppShortcut(
            intent: EventsSearchIntent(),
            phrases: [
                "Find events with \(.applicationName)",
                "\(.applicationName) events",
            ],
            shortTitle: "Find Events",
            systemImageName: "calendar"
        )

        // 6. Flights & trains
        AppShortcut(
            intent: SearchConnectionsIntent(),
            phrases: [
                "Search flights with \(.applicationName)",
                "\(.applicationName) flights",
            ],
            shortTitle: "Search Flights",
            systemImageName: "airplane"
        )

        // 7. Hotels
        AppShortcut(
            intent: SearchStaysIntent(),
            phrases: [
                "Find hotels with \(.applicationName)",
                "\(.applicationName) hotels",
            ],
            shortTitle: "Search Hotels",
            systemImageName: "bed.double"
        )

        // 8. Set Reminder
        AppShortcut(
            intent: SetReminderIntent(),
            phrases: [
                "Set \(.applicationName) reminder",
                "Remind me with \(.applicationName)",
            ],
            shortTitle: "Set Reminder",
            systemImageName: "bell"
        )

        // 9. List Reminders
        AppShortcut(
            intent: ListRemindersIntent(),
            phrases: [
                "List \(.applicationName) reminders",
                "My \(.applicationName) reminders",
                "Show \(.applicationName) reminders",
            ],
            shortTitle: "List Reminders",
            systemImageName: "bell.badge"
        )

        // 10. Calculate
        AppShortcut(
            intent: MathCalculateIntent(),
            phrases: [
                "Calculate with \(.applicationName)",
                "\(.applicationName) calculate",
            ],
            shortTitle: "Calculate",
            systemImageName: "function"
        )
    }
}
