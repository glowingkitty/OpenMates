import { writable } from "svelte/store";
import { userDB } from "../services/userDB";
import { pushNotificationStore } from "./pushNotificationStore";

export interface UserProfile {
  user_id: string | null;
  username: string;
  profile_image_url: string | null;
  credits: number;
  is_admin: boolean;
  last_opened: string;
  last_sync_timestamp: number;
  tfa_app_name: string | null;
  tfa_enabled: boolean; // Added field for 2FA status
  // Use boolean flags received from backend
  consent_privacy_and_apps_default_settings?: boolean;
  consent_mates_default_settings?: boolean;
  consent_recovery_key_stored_timestamp?: number; // Timestamp when user confirmed they stored recovery key
  language: string | null; // User's preferred language
  darkmode: boolean; // User's dark mode preference
  timezone: string | null; // User's timezone in IANA format (e.g., 'Europe/Berlin'). Auto-detected from browser, can be manually overridden.
  currency: string | null; // User's preferred currency
  encrypted_key?: string;
  salt?: string;
  // Low balance auto top-up settings
  auto_topup_low_balance_enabled?: boolean;
  auto_topup_low_balance_threshold?: number;
  auto_topup_low_balance_amount?: number;
  auto_topup_low_balance_currency?: string;
  // Demo chats that user has dismissed/deleted (syncs across devices)
  hidden_demo_chats?: string[];
  // Top recommended apps (decrypted on-demand, never stored in plaintext)
  top_recommended_apps?: string[]; // Array of top 5 app IDs, computed from encrypted_top_recommended_apps
  encrypted_top_recommended_apps?: string | null; // Encrypted array of top 5 app IDs, encrypted with master key
  // Random apps for "Explore & discover" category (when no personalized recommendations exist)
  random_explore_apps?: string[]; // Array of app IDs for random selection
  random_explore_apps_timestamp?: number; // Unix timestamp when random apps were generated (for daily refresh)
  // Push notification settings (synced with server)
  push_notification_enabled?: boolean;
  push_notification_subscription?: PushSubscriptionJSON | null; // Browser push subscription object (stored server-side)
  push_notification_preferences?: {
    newMessages: boolean;
    serverEvents: boolean;
    softwareUpdates: boolean;
  };
  push_notification_banner_shown?: boolean; // Whether the banner has been shown (persists across devices)
  // AI model preferences for the AI Ask skill
  // Disabled models are excluded from @ mention dropdown and auto-selection
  disabled_ai_models?: string[]; // Array of disabled model IDs (e.g., ["claude-sonnet-4-6"])
  // Disabled servers per model - all servers are enabled by default as fallbacks
  // Only explicitly disabled servers are excluded from processing
  disabled_ai_servers?: Record<string, string[]>; // model_id -> array of disabled server IDs
  // Refund policy consent — true if user has consented to the limited refund / withdrawal waiver
  // (set at signup, updated on each purchase). Used to skip redundant consent screens in settings.
  has_accepted_refund_policy?: boolean;
  // Chat auto-deletion period (null = never delete, positive int = delete after N days)
  // Managed via Privacy → Auto Deletion → Chats. Persisted to server via POST /v1/settings/auto-delete-chats.
  auto_delete_chats_after_days?: number | null;
  // Usage data auto-deletion period (null = platform default of 3 years / 1095 days)
  // Managed via Privacy → Auto Deletion → Usage Data. Persisted via POST /v1/settings/auto-delete-usage.
  auto_delete_usage_after_days?: number | null;
  // Email notification settings (synced with server)
  // Only sends email when user is offline (no active WebSocket connections after 3 retry attempts)
  email_notifications_enabled?: boolean;
  email_notification_email?: string; // Decrypted notification email (separate from login email)
  email_notification_preferences?: {
    aiResponses: boolean; // Notify when AI completes a response
    backupReminder: boolean; // Periodic backup reminder emails (Settings → Notifications → Backup Reminders)
    webhookChats?: boolean; // Notify when an incoming webhook creates a new chat (default: true)
  };
  // Backup reminder fields — synced with server via the email notification settings WebSocket flow.
  // last_export_at: set server-side when the user fetches the export manifest.
  // backup_reminder_dismissed_at: set when user dismisses an in-app backup reminder banner.
  // backup_reminder_interval_days: user-configurable cadence in Settings → Notifications → Backup Reminders.
  last_export_at?: string | null;
  backup_reminder_dismissed_at?: string | null;
  backup_reminder_interval_days?: number;
  // Incognito mode explainer screen: once the user activates incognito for the first time and
  // confirms the explainer, we set this flag so the explainer is never shown again.
  // Stored in IndexedDB only — no backend sync needed (device-local UX preference).
  incognito_explainer_seen?: boolean;
  // Default model overrides for AI Ask skill (null = auto-select).
  // Synced cross-device via Directus + Redis cache via POST /v1/settings/ai-model-defaults.
  // Format: "provider/model_id" (e.g., "anthropic/claude-haiku-4-5-20251001").
  default_ai_model_simple?: string | null;
  default_ai_model_complex?: string | null;
  // Total chat count as reported by the server during Phase 3 sync.
  // Stored in IndexedDB so it persists across sessions without a server round-trip.
  // Used by: ActiveChat.svelte overflow "+N" counter, SettingsAccountChats.svelte display.
  // Updated on: Phase 3 sync completion, chat deletion. Cleared on logout.
  total_chat_count?: number;
}

// Default currency is now EUR
export const defaultProfile: UserProfile = {
  user_id: null,
  username: "",
  profile_image_url: null,
  credits: 0,
  is_admin: false,
  last_opened: "",
  last_sync_timestamp: 0,
  tfa_app_name: null,
  tfa_enabled: false, // Added default value
  // Add default values for boolean flags
  consent_privacy_and_apps_default_settings: false,
  consent_mates_default_settings: false,
  language: "en", // Default language
  darkmode: false, // Default dark mode
  timezone: null, // Auto-detected from browser on login, can be manually set
  currency: "EUR", // Default currency set to EUR
};

export const userProfile = writable<UserProfile>(defaultProfile);

// Load user profile data from IndexedDB on startup
export async function loadUserProfileFromDB(): Promise<void> {
  try {
    const profileFromDB = await userDB.getUserProfile();

    if (profileFromDB) {
      // Update the store with the comprehensive profile data from DB
      userProfile.update((currentProfile) => ({
        ...currentProfile, // Keep any existing non-persistent state if needed
        ...profileFromDB, // Overwrite with fresh data from DB (includes consents)
      }));

      // Sync push notification settings from profile to push notification store
      // This ensures bannerShownBefore, enabled, and preferences are loaded from server-synced data
      pushNotificationStore.loadFromUserProfile({
        push_notification_enabled: profileFromDB.push_notification_enabled,
        push_notification_preferences:
          profileFromDB.push_notification_preferences,
        push_notification_banner_shown:
          profileFromDB.push_notification_banner_shown,
      });
    }
  } catch (error) {
    console.error("Failed to load user profile from database:", error);
  }
}

// Helper function to update just the username
export function updateUsername(username: string): void {
  userProfile.update((profile) => ({
    ...profile,
    username,
  }));

  // Also persist to database
  userDB.updateUserData({ username });
}

// Helper function to update just the profile image
export function updateProfileImage(imageUrl: string | null): void {
  userProfile.update((profile) => ({
    ...profile,
    profile_image_url: imageUrl,
  }));

  // Also persist to database
  userDB.updateUserData({ profile_image_url: imageUrl });
}

// Helper function to update just the credits
export function updateCredits(credits: number): void {
  userProfile.update((profile) => ({
    ...profile,
    credits,
  }));

  // Also persist to database
  userDB.updateUserData({ credits });
}

// This becomes the single point of update for user data
export function updateProfile(profile: Partial<UserProfile>): void {
  // Update store
  userProfile.update((currentProfile) => ({
    ...currentProfile,
    ...profile,
  }));

  // Persist to IndexedDB
  userDB.updateUserData(profile);
}

// Add getter for components that need user data
export function getUserProfile(): UserProfile {
  let profile: UserProfile;
  userProfile.subscribe((value) => (profile = value))();
  return profile;
}

/**
 * Update the total chat count in both the in-memory store and IndexedDB.
 * Called by chatSyncServiceHandlersPhasedSync on Phase 3 completion,
 * and decremented by chat deletion handlers.
 */
export function updateTotalChatCount(count: number): void {
  userProfile.update((profile) => ({ ...profile, total_chat_count: count }));
  userDB
    .updateUserData({ total_chat_count: count })
    .catch((err) =>
      console.warn(
        "[UserProfileStore] Failed to persist total_chat_count:",
        err,
      ),
    );
}
