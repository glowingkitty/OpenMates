// frontend/packages/ui/src/stores/authMiscActions.ts
/**
 * @fileoverview Contains miscellaneous authentication-related actions like 2FA setup,
 * handling signup completion, updating user profile data within the auth context,
 * and directly setting the authentication state.
 */

import { get } from "svelte/store";
import { getApiEndpoint, apiEndpoints } from "../config/api";
import {
  currentSignupStep,
  isInSignupProcess,
  getStepFromPath,
  isResettingTFA,
  isSignupPath,
} from "./signupState";
import { userDB } from "../services/userDB";
import {
  userProfile,
  defaultProfile,
  updateProfile,
  type UserProfile,
} from "./userProfile";
import { resetTwoFAData } from "./twoFAState";
import { processedImageUrl } from "./profileImage";
import { locale } from "svelte-i18n";

// Import core auth state and related flags
import {
  authStore,
  needsDeviceVerification,
  deviceVerificationType,
  deviceVerificationReason,
} from "./authState";

/**
 * Sets up the 2FA provider name via API and updates local DB.
 * @param appName The name of the 2FA application.
 * @returns Object indicating success and a message.
 */
export async function setup2FAProvider(
  appName: string,
): Promise<{ success: boolean; message: string }> {
  console.debug(`Calling setup2FAProvider API with appName: ${appName}`);
  try {
    const response = await fetch(
      getApiEndpoint(apiEndpoints.auth.setup_2fa_provider),
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          Origin: window.location.origin,
        },
        body: JSON.stringify({ provider: appName }),
        credentials: "include",
      },
    );

    const data = await response.json();

    if (!response.ok) {
      console.error(
        "setup2FAProvider API call failed:",
        data.message || response.statusText,
      );
      return {
        success: false,
        message: data.message || "Failed to save 2FA provider name",
      };
    }

    if (data.success) {
      console.debug(
        "setup2FAProvider API call successful. Updating IndexedDB.",
      );
      try {
        // Update profile store directly as well for immediate UI feedback
        updateProfile({ tfa_app_name: appName });
        // Update DB in background
        await userDB.updateUserData({ tfa_app_name: appName });
        console.debug("IndexedDB updated with tfa_app_name.");
      } catch (dbError) {
        console.error("Failed to update tfa_app_name in IndexedDB:", dbError);
        // Don't necessarily fail the whole operation if DB fails, but log it.
      }
      return { success: true, message: data.message };
    } else {
      console.error(
        "setup2FAProvider API returned success=false:",
        data.message,
      );
      return {
        success: false,
        message: data.message || "Failed to save 2FA provider name",
      };
    }
  } catch (error) {
    console.error("Error calling setup2FAProvider API:", error);
    return {
      success: false,
      message: "An error occurred while saving the 2FA provider name",
    };
  }
}

/**
 * Handles the state update after a successful signup process completion.
 * Assumes the user data provided confirms authentication.
 * Updates auth state and user profile.
 * @param userData User data received after signup completion (should conform to UserProfile).
 * @returns True if state updated successfully, false otherwise.
 */
export function completeSignup(userData: UserProfile): boolean {
  // Use UserProfile type for better checking
  if (userData && userData.username) {
    // Check for a key field like username
    const inSignupFlow = isSignupPath(userData.last_opened);
    if (inSignupFlow && userData.last_opened) {
      const step = getStepFromPath(userData.last_opened);
      console.debug("Setting signup state from completeSignup:", step);
      currentSignupStep.set(step);
      isInSignupProcess.set(true);
    } else {
      isInSignupProcess.set(false);
    }

    authStore.update((state) => ({
      ...state,
      isAuthenticated: true,
      isInitialized: true,
    }));

    // Update profile store using the provided userData
    try {
      // Ensure boolean flags are correctly handled
      const tfa_enabled = !!userData.tfa_enabled;
      const consent_privacy =
        !!userData.consent_privacy_and_apps_default_settings;
      const consent_mates = !!userData.consent_mates_default_settings;
      const userLanguage = userData.language || defaultProfile.language;
      const userDarkMode = userData.darkmode ?? defaultProfile.darkmode;

      if (userLanguage && userLanguage !== get(locale)) {
        locale.set(userLanguage);
      }

      // Update profile with the full userData received
      updateProfile({
        ...userData, // Spread the received data
        // Ensure boolean flags are correctly typed
        tfa_enabled: tfa_enabled,
        consent_privacy_and_apps_default_settings: consent_privacy,
        consent_mates_default_settings: consent_mates,
        language: userLanguage, // Apply default if needed
        darkmode: userDarkMode, // Apply default if needed
      });
      // Save to DB as well
      userDB.saveUserData(userData).catch((dbError) => {
        console.error(
          "Failed to save user data to database after signup:",
          dbError,
        );
      });
    } catch (profileError) {
      console.error(
        "Error updating profile store after signup completion:",
        profileError,
      );
      // Still return true as auth state was set, but profile might be inconsistent
    }

    return true;
  }
  console.warn("completeSignup called with invalid userData:", userData);
  return false;
}

/**
 * Directly updates the user profile store with partial data.
 * Also persists the changes to IndexedDB.
 * @param userData Partial user profile data to update.
 */
export function updateUser(userData: Partial<UserProfile>) {
  updateProfile(userData);
  // Persist changes to DB
  userDB.updateUserData(userData).catch((dbError) => {
    console.error("Failed to update user data in database:", dbError);
  });
}

/**
 * Directly sets the authentication state. Useful for scenarios where auth is confirmed externally.
 * Handles clearing related state if setting to unauthenticated.
 * @param value The desired authentication state (true or false).
 */
export function setAuthenticated(value: boolean) {
  authStore.update((state) => ({
    ...state,
    isAuthenticated: value,
    isInitialized: true, // Setting manually implies initialization is complete
  }));

  // If setting to false, clear profile and related states (similar to logout)
  if (!value) {
    // Use undefined for potentially string fields when clearing
    updateProfile({
      username: undefined,
      profile_image_url: undefined,
      credits: defaultProfile.credits,
      is_admin: defaultProfile.is_admin,
      last_opened: undefined,
      tfa_app_name: undefined,
      tfa_enabled: defaultProfile.tfa_enabled,
      consent_privacy_and_apps_default_settings:
        defaultProfile.consent_privacy_and_apps_default_settings,
      consent_mates_default_settings:
        defaultProfile.consent_mates_default_settings,
      // Keep language and darkmode from current profile if possible, otherwise use default
      language: get(userProfile)?.language || defaultProfile.language,
      darkmode: get(userProfile)?.darkmode ?? defaultProfile.darkmode,
    });
    // Also reset related states
    processedImageUrl.set(null);
    resetTwoFAData();
    currentSignupStep.set("basics");
    isResettingTFA.set(false);
    needsDeviceVerification.set(false);
    deviceVerificationType.set(null);
    deviceVerificationReason.set(null);
    isInSignupProcess.set(false); // Ensure signup process is reset
  }
}
