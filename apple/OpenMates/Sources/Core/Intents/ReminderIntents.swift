// Reminder Shortcuts — set, list, and cancel reminders via REST API.
// These use both the reminder skill endpoints and the settings REST endpoints.

import AppIntents
import Foundation

// MARK: - Set Reminder

struct SetReminderIntent: AppIntent {
    static let title: LocalizedStringResource = "Set OpenMates Reminder"
    static let description: IntentDescription = "Create a reminder that OpenMates AI will process at the scheduled time."
    static let openAppWhenRun = false

    @Parameter(title: "Prompt", description: "What to remind about or what AI should do")
    var prompt: String

    @Parameter(title: "When", description: "When to trigger (ISO 8601, e.g., '2026-04-20T09:00:00')")
    var triggerDatetime: String

    @Parameter(title: "Timezone", description: "Timezone (e.g., 'Europe/Berlin')", default: "UTC")
    var timezone: String

    static var parameterSummary: some ParameterSummary {
        Summary("Remind me to \(\.$prompt) at \(\.$triggerDatetime)") {
            \.$timezone
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [[
                "id": 1,
                "prompt": prompt,
                "trigger_datetime": triggerDatetime,
                "timezone": timezone
            ]]
        ]

        let response = try await SkillExecutor.execute(
            appId: "reminder", skillId: "set-reminder", body: body
        )

        return .result(value: "Reminder set: \"\(prompt)\" at \(triggerDatetime)")
    }
}

// MARK: - List Reminders

struct ListRemindersIntent: AppIntent {
    static let title: LocalizedStringResource = "List OpenMates Reminders"
    static let description: IntentDescription = "List all active reminders."
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let data: Data = try await APIClient.shared.request(
            .get, path: "/v1/settings/reminders"
        )

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let reminders = json["reminders"] as? [[String: Any]] else {
            return .result(value: "Could not load reminders.")
        }

        if reminders.isEmpty {
            return .result(value: "No active reminders.")
        }

        let lines = reminders.map { reminder -> String in
            let prompt = reminder["prompt"] as? String ?? "No description"
            let triggerAt = reminder["trigger_at"] as? Int ?? 0
            let date = Date(timeIntervalSince1970: TimeInterval(triggerAt))
            let formatter = DateFormatter()
            formatter.dateStyle = .medium
            formatter.timeStyle = .short
            return "• \(prompt) — \(formatter.string(from: date))"
        }

        return .result(value: "\(reminders.count) reminder\(reminders.count == 1 ? "" : "s"):\n\(lines.joined(separator: "\n"))")
    }
}

// MARK: - Cancel Reminder

struct CancelReminderIntent: AppIntent {
    static let title: LocalizedStringResource = "Cancel OpenMates Reminder"
    static let description: IntentDescription = "Cancel an active reminder by its ID."
    static let openAppWhenRun = false

    @Parameter(title: "Reminder ID", description: "The ID of the reminder to cancel")
    var reminderId: String

    static var parameterSummary: some ParameterSummary {
        Summary("Cancel reminder \(\.$reminderId)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let _: Data = try await APIClient.shared.request(
            .delete, path: "/v1/settings/reminders/\(reminderId)"
        )
        return .result(value: "Reminder cancelled.")
    }
}
