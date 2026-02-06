// frontend/packages/ui/src/stores/pushNotificationStore.ts
/**
 * @file pushNotificationStore.ts
 * @description Svelte store for managing push notification state, permissions, and user preferences.
 *
 * This store handles:
 * - Browser permission state tracking
 * - User preference toggles for notification categories
 * - Session state for banner dismissal
 * - Push subscription management
 *
 * The store persists user preferences to localStorage and syncs with the server
 * when the user is authenticated.
 */
import { writable, derived, get } from "svelte/store";

// Browser check for SSR safety
const browser = typeof window !== "undefined";

/**
 * Browser notification permission states
 */
export type NotificationPermission = "default" | "granted" | "denied";

/**
 * User preferences for notification categories
 */
export interface PushNotificationPreferences {
  /** Notifications when an assistant completes a response */
  newMessages: boolean;
  /** Notifications for server events (connection issues, maintenance) */
  serverEvents: boolean;
  /** Notifications when software updates are available */
  softwareUpdates: boolean;
}

/**
 * Push notification store state
 */
export interface PushNotificationState {
  /** Current browser permission state */
  permission: NotificationPermission;
  /** Whether push notifications are enabled by the user */
  enabled: boolean;
  /** Category-specific notification preferences */
  preferences: PushNotificationPreferences;
  /** Whether the user clicked "Not Yet" on the banner this session */
  bannerDismissedThisSession: boolean;
  /** Whether we've ever shown the permission banner to this user */
  bannerShownBefore: boolean;
  /** Current push subscription (null if not subscribed) */
  subscription: PushSubscription | null;
  /** Whether push notifications are supported on this platform */
  isSupported: boolean;
  /** Whether the app is running as an installed PWA */
  isPWA: boolean;
  /** Whether the platform is iOS (needs special handling) */
  isIOS: boolean;
}

// localStorage keys
const STORAGE_KEY_PREFERENCES = "openmates_push_preferences";
const STORAGE_KEY_ENABLED = "openmates_push_enabled";
const STORAGE_KEY_BANNER_SHOWN = "openmates_push_banner_shown";

/**
 * Default notification preferences
 */
const defaultPreferences: PushNotificationPreferences = {
  newMessages: true,
  serverEvents: true,
  softwareUpdates: false,
};

/**
 * Detect if the current platform is iOS
 */
function detectIsIOS(): boolean {
  if (!browser) return false;
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

/**
 * Detect if the app is running as an installed PWA
 */
function detectIsPWA(): boolean {
  if (!browser) return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone ===
      true
  );
}

/**
 * Check if push notifications are supported on this platform
 */
function checkPushSupport(): boolean {
  if (!browser) return false;

  // Check for Notification API
  if (!("Notification" in window)) return false;

  // Check for Service Worker API
  if (!("serviceWorker" in navigator)) return false;

  // Check for Push API
  if (!("PushManager" in window)) return false;

  return true;
}

/**
 * Get the current browser notification permission
 */
function getCurrentPermission(): NotificationPermission {
  if (!browser || !("Notification" in window)) return "default";
  return Notification.permission as NotificationPermission;
}

/**
 * Load preferences from localStorage
 */
function loadPreferences(): PushNotificationPreferences {
  if (!browser) return defaultPreferences;

  try {
    const stored = localStorage.getItem(STORAGE_KEY_PREFERENCES);
    if (stored) {
      return { ...defaultPreferences, ...JSON.parse(stored) };
    }
  } catch (e) {
    console.error("[PushNotificationStore] Failed to load preferences:", e);
  }

  return defaultPreferences;
}

/**
 * Load enabled state from localStorage
 */
function loadEnabled(): boolean {
  if (!browser) return false;

  try {
    const stored = localStorage.getItem(STORAGE_KEY_ENABLED);
    if (stored !== null) {
      return JSON.parse(stored);
    }
  } catch (e) {
    console.error("[PushNotificationStore] Failed to load enabled state:", e);
  }

  return false;
}

/**
 * Load banner shown state from localStorage
 */
function loadBannerShown(): boolean {
  if (!browser) return false;

  try {
    const stored = localStorage.getItem(STORAGE_KEY_BANNER_SHOWN);
    if (stored !== null) {
      return JSON.parse(stored);
    }
  } catch (e) {
    console.error("[PushNotificationStore] Failed to load banner state:", e);
  }

  return false;
}

/**
 * Initial state for the push notification store
 */
const initialState: PushNotificationState = {
  permission: getCurrentPermission(),
  enabled: loadEnabled(),
  preferences: loadPreferences(),
  bannerDismissedThisSession: false,
  bannerShownBefore: loadBannerShown(),
  subscription: null,
  isSupported: checkPushSupport(),
  isPWA: detectIsPWA(),
  isIOS: detectIsIOS(),
};

// Create the writable store
const { subscribe, update, set } =
  writable<PushNotificationState>(initialState);

/**
 * Push notification store with methods for managing state
 */
export const pushNotificationStore = {
  subscribe,

  /**
   * Update the browser permission state
   * Called after permission request or when permission changes
   */
  setPermission: (permission: NotificationPermission) => {
    update((state) => ({ ...state, permission }));
  },

  /**
   * Enable or disable push notifications globally
   */
  setEnabled: (enabled: boolean) => {
    update((state) => {
      // Persist to localStorage
      if (browser) {
        try {
          localStorage.setItem(STORAGE_KEY_ENABLED, JSON.stringify(enabled));
        } catch (e) {
          console.error(
            "[PushNotificationStore] Failed to save enabled state:",
            e,
          );
        }
      }
      return { ...state, enabled };
    });
  },

  /**
   * Update notification preferences
   */
  setPreferences: (preferences: Partial<PushNotificationPreferences>) => {
    update((state) => {
      const newPreferences = { ...state.preferences, ...preferences };

      // Persist to localStorage
      if (browser) {
        try {
          localStorage.setItem(
            STORAGE_KEY_PREFERENCES,
            JSON.stringify(newPreferences),
          );
        } catch (e) {
          console.error(
            "[PushNotificationStore] Failed to save preferences:",
            e,
          );
        }
      }

      return { ...state, preferences: newPreferences };
    });
  },

  /**
   * Toggle a specific preference
   */
  togglePreference: (key: keyof PushNotificationPreferences) => {
    update((state) => {
      const newPreferences = {
        ...state.preferences,
        [key]: !state.preferences[key],
      };

      // Persist to localStorage
      if (browser) {
        try {
          localStorage.setItem(
            STORAGE_KEY_PREFERENCES,
            JSON.stringify(newPreferences),
          );
        } catch (e) {
          console.error(
            "[PushNotificationStore] Failed to save preferences:",
            e,
          );
        }
      }

      return { ...state, preferences: newPreferences };
    });
  },

  /**
   * Mark the banner as dismissed for this session
   * Called when user clicks "Not Yet"
   */
  dismissBannerForSession: () => {
    update((state) => ({
      ...state,
      bannerDismissedThisSession: true,
      bannerShownBefore: true,
    }));

    // Persist banner shown state
    if (browser) {
      try {
        localStorage.setItem(STORAGE_KEY_BANNER_SHOWN, JSON.stringify(true));
      } catch (e) {
        console.error(
          "[PushNotificationStore] Failed to save banner state:",
          e,
        );
      }
    }
  },

  /**
   * Mark the banner as having been shown (but not necessarily dismissed)
   */
  markBannerShown: () => {
    update((state) => ({ ...state, bannerShownBefore: true }));

    if (browser) {
      try {
        localStorage.setItem(STORAGE_KEY_BANNER_SHOWN, JSON.stringify(true));
      } catch (e) {
        console.error(
          "[PushNotificationStore] Failed to save banner state:",
          e,
        );
      }
    }
  },

  /**
   * Set the push subscription
   */
  setSubscription: (subscription: PushSubscription | null) => {
    update((state) => ({ ...state, subscription }));
  },

  /**
   * Refresh the permission state from the browser
   */
  refreshPermission: () => {
    const permission = getCurrentPermission();
    update((state) => ({ ...state, permission }));
  },

  /**
   * Check if we should show the permission banner
   * Returns true if:
   * - Push is supported and permission is not already granted or denied
   * - OR device is iOS (non-PWA) where push becomes available after home screen install
   * - AND user hasn't dismissed the banner this session
   * - AND the banner hasn't been shown before (persisted across sessions)
   */
  shouldShowBanner: (): boolean => {
    const state = get(pushNotificationStore);

    // User dismissed this session, don't show
    if (state.bannerDismissedThisSession) return false;

    // Banner was already shown in a previous session, don't show again
    if (state.bannerShownBefore) return false;

    // iOS Safari (non-PWA): push is unsupported but becomes available after PWA install
    if (!state.isSupported) {
      return state.isIOS && !state.isPWA;
    }

    // Already have permission decision, don't show
    if (state.permission === "granted" || state.permission === "denied") {
      return false;
    }

    return true;
  },

  /**
   * Get current state synchronously
   */
  getState: (): PushNotificationState => {
    return get(pushNotificationStore);
  },

  /**
   * Load preferences from user profile (server-synced state)
   * Called when user logs in or profile is loaded
   */
  loadFromUserProfile: (profile: {
    push_notification_enabled?: boolean;
    push_notification_preferences?: PushNotificationPreferences;
  }) => {
    update((state) => {
      const newState = { ...state };

      // Load enabled state from profile if available
      if (typeof profile.push_notification_enabled === "boolean") {
        newState.enabled = profile.push_notification_enabled;
        // Also update localStorage for offline consistency
        if (browser) {
          try {
            localStorage.setItem(
              STORAGE_KEY_ENABLED,
              JSON.stringify(profile.push_notification_enabled),
            );
          } catch (e) {
            console.error(
              "[PushNotificationStore] Failed to save enabled state:",
              e,
            );
          }
        }
      }

      // Load preferences from profile if available
      if (profile.push_notification_preferences) {
        newState.preferences = {
          ...defaultPreferences,
          ...profile.push_notification_preferences,
        };
        // Also update localStorage for offline consistency
        if (browser) {
          try {
            localStorage.setItem(
              STORAGE_KEY_PREFERENCES,
              JSON.stringify(newState.preferences),
            );
          } catch (e) {
            console.error(
              "[PushNotificationStore] Failed to save preferences:",
              e,
            );
          }
        }
      }

      console.debug(
        "[PushNotificationStore] Loaded from user profile:",
        newState,
      );
      return newState;
    });
  },

  /**
   * Get data to sync to server (for saving to user profile)
   * Returns only the fields that should be persisted server-side
   */
  getServerSyncData: (): {
    push_notification_enabled: boolean;
    push_notification_preferences: PushNotificationPreferences;
  } => {
    const state = get(pushNotificationStore);
    return {
      push_notification_enabled: state.enabled,
      push_notification_preferences: state.preferences,
    };
  },

  /**
   * Reset store to initial state (for testing/logout)
   */
  reset: () => {
    set({
      ...initialState,
      permission: getCurrentPermission(),
      isSupported: checkPushSupport(),
      isPWA: detectIsPWA(),
      isIOS: detectIsIOS(),
    });
  },
};

/**
 * Derived store: Whether the user can receive push notifications
 * True if supported, permission granted, and enabled
 */
export const canReceivePushNotifications = derived(
  pushNotificationStore,
  ($store) =>
    $store.isSupported && $store.permission === "granted" && $store.enabled,
);

/**
 * Derived store: Whether to show the permission banner
 *
 * Shows the banner when:
 * - Push is supported and permission is still "default" (not yet requested)
 * - OR on iOS (non-PWA) where push isn't technically supported in Safari
 *   but becomes available after installing the app to the home screen
 * - AND the banner hasn't been dismissed this session
 * - AND the banner hasn't been shown before (persisted across sessions in localStorage)
 */
export const shouldShowPushBanner = derived(
  pushNotificationStore,
  ($store) =>
    ($store.isSupported
      ? $store.permission === "default"
      : $store.isIOS && !$store.isPWA) &&
    !$store.bannerDismissedThisSession &&
    !$store.bannerShownBefore,
);

/**
 * Derived store: Whether the platform requires PWA installation for push
 * (iOS requires the app to be added to home screen)
 *
 * On iOS Safari (non-PWA), the Push API and PushManager are not available,
 * so checkPushSupport() returns false. However, push IS supported once the
 * user installs the app as a PWA via "Add to Home Screen". This store
 * detects that scenario so the UI can show installation instructions
 * instead of a generic "not supported" message.
 */
export const requiresPWAInstall = derived(
  pushNotificationStore,
  ($store) => $store.isIOS && !$store.isPWA,
);
