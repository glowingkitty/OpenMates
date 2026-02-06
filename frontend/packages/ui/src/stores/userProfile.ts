import { writable } from "svelte/store";
import { userDB } from "../services/userDB";

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
  push_notification_preferences?: {
    newMessages: boolean;
    serverEvents: boolean;
    softwareUpdates: boolean;
  };
  // AI model preferences for the AI Ask skill
  // Disabled models are excluded from @ mention dropdown and auto-selection
  disabled_ai_models?: string[]; // Array of disabled model IDs (e.g., ["claude-sonnet-4-5-20250929"])
  // Disabled servers per model - all servers are enabled by default as fallbacks
  // Only explicitly disabled servers are excluded from processing
  disabled_ai_servers?: Record<string, string[]>; // model_id -> array of disabled server IDs
  // Email notification settings (synced with server)
  // Only sends email when user is offline (no active WebSocket connections after 3 retry attempts)
  email_notifications_enabled?: boolean;
  email_notification_email?: string; // Decrypted notification email (separate from login email)
  email_notification_preferences?: {
    aiResponses: boolean; // Notify when AI completes a response
  };
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
      console.debug(
        "[UserProfileStore] Profile loaded from DB:",
        profileFromDB,
      );
    } else {
      console.debug(
        "[UserProfileStore] No profile found in DB, using default.",
      );
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
