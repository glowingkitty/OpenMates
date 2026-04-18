// Reminder creation view — set reminders from within chats.
// Supports chat reminders (notify in this chat) and task reminders (with prompt).

import SwiftUI

struct ReminderCreationView: View {
    let chatId: String
    @Environment(\.dismiss) var dismiss

    @State private var reminderType: ReminderType = .chat
    @State private var title = ""
    @State private var taskPrompt = ""
    @State private var selectedDate = Date().addingTimeInterval(3600)
    @State private var repeatInterval: RepeatInterval = .none
    @State private var isCreating = false
    @State private var error: String?

    enum ReminderType: String, CaseIterable {
        case chat = "Chat Reminder"
        case task = "Task Reminder"

        var description: String {
            switch self {
            case .chat: return "Get notified in this chat at the chosen time."
            case .task: return "The AI will process a task prompt at the chosen time."
            }
        }
    }

    enum RepeatInterval: String, CaseIterable {
        case none = "Don't repeat"
        case daily = "Daily"
        case weekly = "Weekly"
        case monthly = "Monthly"
    }

    private var isValid: Bool {
        !title.isEmpty && selectedDate > Date() &&
        (reminderType == .chat || !taskPrompt.isEmpty)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Type", selection: $reminderType) {
                        ForEach(ReminderType.allCases, id: \.self) { type in
                            Text(type.rawValue).tag(type)
                        }
                    }
                    Text(reminderType.description)
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }

                Section("Details") {
                    TextField("Reminder title", text: $title)

                    if reminderType == .task {
                        TextField("Task prompt for the AI", text: $taskPrompt, axis: .vertical)
                            .lineLimit(2...5)
                    }
                }

                Section("When") {
                    DatePicker("Date & Time", selection: $selectedDate, in: Date()...,
                              displayedComponents: [.date, .hourAndMinute])

                    Picker("Repeat", selection: $repeatInterval) {
                        ForEach(RepeatInterval.allCases, id: \.self) { interval in
                            Text(interval.rawValue).tag(interval)
                        }
                    }
                }

                if let error {
                    Text(error).font(.omXs).foregroundStyle(Color.error)
                }

                Section {
                    Button(action: createReminder) {
                        Group {
                            if isCreating {
                                ProgressView().tint(.fontButton)
                                    .accessibilityHidden(true)
                            } else {
                                Text(AppStrings.setReminder)
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(!isValid || isCreating)
                    .accessibleButton(
                        isCreating ? "Setting reminder" : "Set reminder",
                        hint: isCreating ? nil : "Creates a reminder for this chat"
                    )
                }
            }
            .navigationTitle("New Reminder")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private func createReminder() {
        isCreating = true
        error = nil

        Task {
            do {
                let body: [String: Any] = [
                    "chat_id": chatId,
                    "title": title,
                    "type": reminderType.rawValue,
                    "task_prompt": taskPrompt,
                    "datetime": ISO8601DateFormatter().string(from: selectedDate),
                    "repeat": repeatInterval.rawValue
                ]
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/reminders", body: body
                )
                AccessibilityAnnouncement.announce("Reminder set for \(title)")
                ToastManager.shared.show("Reminder set", type: .success)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
            isCreating = false
        }
    }
}
