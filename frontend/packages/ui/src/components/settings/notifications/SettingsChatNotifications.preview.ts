/** Fictional account for isolated notification-settings previews: ?email=1 turns email on, ?push=1 marks push as set up. */
import { userProfile } from "../../../stores/userProfile";

const params = new URLSearchParams(window.location.search);
userProfile.update((profile) => ({
  ...profile,
  email_notifications_enabled: params.get("email") === "1",
  push_notification_enabled: params.get("push") === "1",
  email_notification_preferences: {
    aiResponses: true,
    workflowRuns: true,
    includeContent: params.get("content") === "1",
    backupReminder: false,
    webhookChats: false,
  },
}));

export default {};
