import { writable, derived, get } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import { currentSignupStep, isInSignupProcess, getStepFromPath, isResettingTFA } from './signupState'; // Import isResettingTFA
import { userDB } from '../services/userDB';
import { chatDB } from '../services/db'; // Import chatDB
import { userProfile, defaultProfile, updateProfile, type UserProfile } from './userProfile'; // Import store, defaultProfile and type
import { resetTwoFAData } from './twoFAState'; // Import the reset function
import { processedImageUrl } from './profileImage'; // Import processedImageUrl store
import { locale, waitLocale } from 'svelte-i18n'; // Import i18n functions
// Removed duplicate: import { get } from 'svelte/store'; // Import get to read locale store value

// Define the types for the auth store
interface AuthState {
  isAuthenticated: boolean; // Represents full authentication (session valid AND device known)
  isInitialized: boolean;
}

// Define return type for session check
interface SessionCheckResult {
    success: boolean;
    user?: UserProfile; // Use UserProfile type
    message?: string;
    re_auth_required?: '2fa' | null; // Add this field
    token_refresh_needed?: boolean;
}

// Define return type for the login function
interface LoginResult {
  success: boolean;
  tfa_required: boolean;
  message?: string;
  tfa_app_name?: string | null;
  inSignupFlow?: boolean;
  backup_code_used?: boolean; // Added
  remaining_backup_codes?: number; // Added
}

// Create the initial state
const initialState: AuthState = {
  isAuthenticated: false,
  isInitialized: false
};

// Export auth checking state - moved from authCheckState.ts
export const isCheckingAuth = writable(false);
// Export state for device verification requirement
export const needsDeviceVerification = writable(false);

// Create the writable store
function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>(initialState);

  return {
    subscribe,
    
    // Check authentication status using session endpoint
    checkAuth: async (deviceSignals?: Record<string, string | null>): Promise<boolean> => { // Add deviceSignals param, Returns true if fully authenticated, false otherwise
      isCheckingAuth.set(true);
      needsDeviceVerification.set(false); // Reset verification need at the start of check

      try {
        console.debug("Checking authentication with session endpoint...");
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.session), {
          method: 'POST',
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Origin': window.location.origin
          },
          body: JSON.stringify({ deviceSignals: deviceSignals || {} }), // Send signals if available
          credentials: 'include' // Critical for sending cookies
        });

        // Process the response
        const data: SessionCheckResult = await response.json(); // Use defined type
        console.debug("Session check response:", data);

        // --- Handle Device Verification Required ---
        if (!data.success && data.re_auth_required === '2fa') {
            console.warn("Session check indicates device 2FA verification is required.");
            needsDeviceVerification.set(true);
            update(state => ({
                ...state,
                isAuthenticated: false, // Not fully authenticated yet
                isInitialized: true
            }));
            // Clear potentially stale user data from profile store if re-auth is needed
            updateProfile({
                username: null,
                profile_image_url: null,
                tfa_app_name: null,
                tfa_enabled: false, // Assume false until re-verified
                credits: 0,
                is_admin: false,
                last_opened: null,
                consent_privacy_and_apps_default_settings: false,
                consent_mates_default_settings: false,
                darkmode: defaultProfile.darkmode // Reset darkmode
            });
            return false; // Indicate not fully authenticated
        }

        // --- Handle Successful Authentication (Device Known) ---
        if (data.success && data.user) {
          needsDeviceVerification.set(false); // Ensure flag is false on success
          const inSignupFlow = data.user.last_opened?.startsWith('/signup/');

          if (inSignupFlow) {
            console.debug("User is in signup process:", data.user.last_opened);
            const step = getStepFromPath(data.user.last_opened);
            currentSignupStep.set(step);
            isInSignupProcess.set(true);
          } else {
            isInSignupProcess.set(false);
          }

          update(state => ({
            ...state,
            isAuthenticated: true, // Fully authenticated
            isInitialized: true
          }));

          // Save the user data to IndexedDB
          try {
            await userDB.saveUserData(data.user);
            
            // Extract tfa_enabled status and consent flags
            const tfa_enabled = !!data.user.tfa_enabled;
            const consent_privacy_and_apps_default_settings = !!data.user.consent_privacy_and_apps_default_settings;
            const consent_mates_default_settings = !!data.user.consent_mates_default_settings;
            const userLanguage = data.user.language || defaultProfile.language; // Use default if null/undefined
            const userDarkMode = data.user.darkmode ?? defaultProfile.darkmode; // Use default if null/undefined

            // --- Apply Language Setting ---
            if (userLanguage && userLanguage !== get(locale)) {
              console.debug(`Applying user language from session: ${userLanguage}`);
              locale.set(userLanguage);
              // No need to await waitLocale here, UI updates should handle it
            }
            // --- End Apply Language Setting ---

            // Update the user profile store
            updateProfile({
              username: data.user.username,
              profile_image_url: data.user.profile_image_url, // Corrected: camelCase
              tfa_app_name: data.user.tfa_app_name,           // Corrected: camelCase
              tfa_enabled: tfa_enabled, // Pass status
              credits: data.user.credits,
              is_admin: data.user.is_admin,                 // Corrected: camelCase
              last_opened: data.user.last_opened,
              consent_privacy_and_apps_default_settings: consent_privacy_and_apps_default_settings,
              consent_mates_default_settings: consent_mates_default_settings,
              language: userLanguage, // Add language
              darkmode: userDarkMode // Add darkmode
            });
          } catch (dbError) {
            console.error("Failed to save user data to database:", dbError);
          }
          
          return true; // Indicate fully authenticated
        } else {
          // --- Handle Other Failures (Not logged in, expired token etc.) ---
          console.info("Session check failed or user not logged in:", data.message);
          needsDeviceVerification.set(false); // Ensure flag is false on failure
          update(state => ({
            ...state,
            isAuthenticated: false, // Not authenticated
            isInitialized: true
          }));
          // Clear profile on any auth failure
           updateProfile({
                username: null,
                profile_image_url: null,
                tfa_app_name: null,
                tfa_enabled: false,
                credits: 0,
                is_admin: false,
                last_opened: null,
                consent_privacy_and_apps_default_settings: false,
                consent_mates_default_settings: false
            });
          return false; // Indicate not authenticated
        }
      } catch (error) {
        console.error("Auth check error:", error);
        
        // On network/fetch error, assume not authenticated
        needsDeviceVerification.set(false); // Reset flag on error
        update(state => ({
            ...state,
            isAuthenticated: false, // Not authenticated
            isInitialized: true
        }));
         // Clear profile on error
        updateProfile({
            username: null,
            profile_image_url: null,
            tfa_app_name: null,
            tfa_enabled: false,
            credits: 0,
            is_admin: false,
            last_opened: null,
            consent_privacy_and_apps_default_settings: false,
            consent_mates_default_settings: false
            });
        return false; // Indicate not authenticated
      } finally {
        // Always set isCheckingAuth to false when done
        isCheckingAuth.set(false);
      }
    },

    // Setup 2FA Provider
    setup2FAProvider: async (appName: string): Promise<{ success: boolean, message: string }> => {
      console.debug(`Calling setup2FAProvider API with appName: ${appName}`);
      try {
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.setup_2fa_provider), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': window.location.origin
          },
          body: JSON.stringify({ provider: appName }),
          credentials: 'include'
        });

        const data = await response.json();

        if (!response.ok) {
          console.error('setup2FAProvider API call failed:', data.message || response.statusText);
          return { success: false, message: data.message || 'Failed to save 2FA provider name' };
        }

        if (data.success) {
          console.debug('setup2FAProvider API call successful. Updating IndexedDB.');
          try {
            await userDB.updateUserData({ tfa_app_name: appName });
            console.debug('IndexedDB updated with tfa_app_name.');
          } catch (dbError) {
            console.error('Failed to update tfa_app_name in IndexedDB:', dbError);
            // Proceed even if DB update fails, but log error. API call succeeded.
          }
          return { success: true, message: data.message };
        } else {
          console.error('setup2FAProvider API returned success=false:', data.message);
          return { success: false, message: data.message || 'Failed to save 2FA provider name' };
        }

      } catch (error) {
        console.error('Error calling setup2FAProvider API:', error);
        return { success: false, message: 'An error occurred while saving the 2FA provider name' };
      }
    },
    
    // Login the user - updated for 2FA flow including backup codes and device signals
    login: async (
        email: string,
        password: string,
        tfaCode?: string,
        codeType?: 'otp' | 'backup',
        deviceSignals?: Record<string, string | null> // Add deviceSignals param
    ): Promise<LoginResult> => {
      try {
        console.debug(`Attempting login... (TFA Code Provided: ${!!tfaCode}, Type: ${codeType || 'otp'}, Signals Provided: ${!!deviceSignals})`);

        // Construct request body
        const requestBody: any = {
          email: email.trim(),
          password: password
        };
        if (tfaCode) {
          requestBody.tfa_code = tfaCode;
          requestBody.code_type = codeType || 'otp'; // Send code type if code is present
        }
        
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': window.location.origin
          },
          body: JSON.stringify(requestBody), // Use constructed body
          credentials: 'include'
        });

        if (response.status === 429) {
           // Rate limited - Ensure return type matches LoginResult
          return { success: false, tfa_required: !!tfaCode, message: "Too many login attempts. Please try again later." };
        }

        const data = await response.json(); // Assuming backend returns fields matching LoginResponse schema
        console.debug("Login response data:", data);

        // Handle different scenarios based on response
        if (data.success) {
          if (data.tfa_required) {
            // Scenario: Password OK, but 2FA code needed (first step)
            console.debug("Login step 1 successful, 2FA required.");
             // Ensure return type matches LoginResult
            return { 
              success: true, 
              tfa_required: true, 
              tfa_app_name: data.user?.tfa_app_name // Pass app name if available
            };
          } else {
            // Scenario: Full success (either no 2FA, or 2FA code was provided and valid, or backup code used)
            console.debug("Login fully successful.");
            const inSignupFlow = data.user?.last_opened?.startsWith('/signup/');
            
            if (inSignupFlow) {
              console.debug("User is in signup process:", data.user.last_opened);
              const step = getStepFromPath(data.user.last_opened);
              currentSignupStep.set(step);
              isInSignupProcess.set(true);
            } else {
              isInSignupProcess.set(false);
            }
            
            update(state => ({ ...state, isAuthenticated: true, isInitialized: true }));
            
            try {
              if (data.user) {
                await userDB.saveUserData(data.user);
                // Extract flags before updating profile store
                const tfa_enabled = !!data.user.tfa_enabled; 
                const consent_privacy_and_apps_default_settings = !!data.user.consent_privacy_and_apps_default_settings;
                const consent_mates_default_settings = !!data.user.consent_mates_default_settings;
                const userLanguage = data.user.language || defaultProfile.language;
                const userDarkMode = data.user.darkmode ?? defaultProfile.darkmode;

                // --- Apply Language Setting on Login ---
                if (userLanguage && userLanguage !== get(locale)) {
                  console.debug(`Applying user language from login: ${userLanguage}`);
                  locale.set(userLanguage);
                }
                // --- End Apply Language Setting ---
                
                updateProfile({
                  username: data.user.username,
                  profile_image_url: data.user.profile_image_url,
                  tfa_app_name: data.user.tfa_app_name,
                  tfa_enabled: tfa_enabled,
                  credits: data.user.credits,
                  is_admin: data.user.is_admin,
                  last_opened: data.user.last_opened,
                  // Pass consent flags
                  consent_privacy_and_apps_default_settings: consent_privacy_and_apps_default_settings,
                  consent_mates_default_settings: consent_mates_default_settings,
                  language: userLanguage, // Add language
                  darkmode: userDarkMode // Add darkmode
                });
              } else {
                 console.warn("Login successful but no user data received in response.");
              }
            } catch (dbError) {
              console.error("Failed to save user data to database:", dbError);
            }
            
             // Ensure return type matches LoginResult, include backup code info if present
            return { 
              success: true, 
              tfa_required: false, 
              inSignupFlow,
              backup_code_used: data.backup_code_used || false,
              remaining_backup_codes: data.remaining_backup_codes 
            };
          }
        } else {
          // Scenario: Login failed
          if (data.tfa_required) {
            // Specific failure: Invalid 2FA code provided
            console.warn("Login failed: Invalid 2FA code.");
             // Ensure return type matches LoginResult
            return { success: false, tfa_required: true, message: data.message || "Invalid 2FA code" };
          } else {
            // General failure (e.g., invalid password)
            console.warn("Login failed:", data.message);
             // Ensure return type matches LoginResult
            return { success: false, tfa_required: false, message: data.message || "Login failed" };
          }
        }
      } catch (error) {
        console.error("Login fetch/network error:", error);
         // Ensure return type matches LoginResult
        return { success: false, tfa_required: false, message: "An error occurred during login" };
      }
    },
    
    // Handle signup completion and auto-login
    completeSignup: (userData: any) => {
      if (userData && userData.id) {
        // Explicitly check for signup state
        const inSignupFlow = userData.last_opened?.startsWith('/signup/');
        if (inSignupFlow) {
          const step = getStepFromPath(userData.last_opened);
          console.debug("Setting signup state from completeSignup:", step);
          currentSignupStep.set(step);
          isInSignupProcess.set(true);
        }
        
        update(state => ({
          ...state,
          isAuthenticated: true,
          isInitialized: true
        }));
        
        return true;
      }
      return false;
    },
    
    // Update user information
    updateUser: (userData: Partial<UserProfile>) => { // Use UserProfile type
      updateProfile(userData);
    },
    
    // Set authentication state directly (useful for API responses that confirm auth)
    setAuthenticated: (value: boolean) => {
      update(state => ({
        ...state,
        isAuthenticated: value,
        isInitialized: true
      }));
    },
    
    // Initialize auth state - call this once on app startup
    initialize: async (deviceSignals?: Record<string, string | null>) => { // Add deviceSignals param
      console.debug("Initializing auth state...");
      return await authStore.checkAuth(deviceSignals); // Pass signals to checkAuth
    },
    
    // Logout the user with optional callbacks for complex logout flows
    logout: async (callbacks?: {
      beforeServerLogout?: () => void | Promise<void>,
      afterServerLogout?: () => void | Promise<void>,
      onError?: (error: any) => void | Promise<void>,
      finalLogout?: () => void | Promise<void>,
      skipServerLogout?: boolean,
      isPolicyViolation?: boolean  // Add flag for policy violation
    }) => {
      try {
        console.debug('Logging out...');
        
        // Call pre-logout callback if provided
        if (callbacks?.beforeServerLogout) {
          await callbacks.beforeServerLogout();
        }
        
        // Make the logout request to the server only if not skipped
        if (!callbacks?.skipServerLogout) {
          try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.logout), {
              method: 'POST',
              credentials: 'include',
              headers: {
                'Content-Type': 'application/json'
              }
            });
  
            if (!response.ok) {
              console.error('Logout request failed:', response.statusText);
            }
          } catch (e) {
            console.error("Logout API error:", e);
          }
        } else if (callbacks?.isPolicyViolation) {
          // Special case: Policy violation requires cookie cleanup
          try {
            // Call a special endpoint to clear cookies and cache for policy violations
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.policyViolationLogout), {
              method: 'POST',
              credentials: 'include',
              headers: {
                'Content-Type': 'application/json'
              }
            });
            console.debug('Policy violation logout response:', response.ok);
          } catch (e) {
            console.error("Policy violation logout error:", e);
          }
        }
        
        // Call post-server-logout callback if provided
        if (callbacks?.afterServerLogout) {
          await callbacks.afterServerLogout();
        }
        
        // Clear user data from IndexedDB
        try {
          await userDB.clearUserData();
          console.debug("[AuthStore] UserDB data cleared.");
        } catch (dbError) {
          console.error("[AuthStore] Failed to clear userDB data:", dbError);
        }
        try {
          await chatDB.clearAllChatData(); // Clear chat and draft data
          console.debug("[AuthStore] ChatDB data cleared.");
        } catch (dbError) {
          console.error("[AuthStore] Failed to clear chatDB data:", dbError);
        }

        // Reset user profile store IN MEMORY to defaults, EXCEPT language
        updateProfile({
            username: defaultProfile.username,
            profile_image_url: defaultProfile.profile_image_url,
            credits: defaultProfile.credits,
            is_admin: defaultProfile.is_admin,
            last_opened: defaultProfile.last_opened,
            tfa_app_name: defaultProfile.tfa_app_name,
            tfa_enabled: defaultProfile.tfa_enabled,
            consent_privacy_and_apps_default_settings: defaultProfile.consent_privacy_and_apps_default_settings,
            consent_mates_default_settings: defaultProfile.consent_mates_default_settings
        });
        
        // Reset temporary processed image URL
        processedImageUrl.set(null);

        // Reset 2FA state
        resetTwoFAData();
        
        // Reset signup step
        currentSignupStep.set(1);

        // Reset the TFA resetting flag
        isResettingTFA.set(false);

        // Reset device verification flag
        needsDeviceVerification.set(false);
        
        // Reset the store state
        set({
          ...initialState,
          isInitialized: true
        });
        
        // Call final logout callback if provided
        if (callbacks?.finalLogout) {
          await callbacks.finalLogout();
        }
        
        return true;
      } catch (error) {
        console.error("Logout error:", error);
        
        // Call error callback if provided
        if (callbacks?.onError) {
          await callbacks?.onError(error);
        }
        
        // Attempt to clear DBs even on other logout errors
        try {
            await userDB.clearUserData();
            console.debug("[AuthStore] UserDB data cleared on error path.");
          } catch (dbError) {
            console.error("[AuthStore] Failed to clear userDB data on error path:", dbError);
          }
        try {
            await chatDB.clearAllChatData();
            console.debug("[AuthStore] ChatDB data cleared on error path.");
        } catch (dbError) {
            console.error("[AuthStore] Failed to clear chatDB data on error path:", dbError);
        }

        // Reset user profile store IN MEMORY to defaults even on error, EXCEPT language
        updateProfile({
            username: defaultProfile.username,
            profile_image_url: defaultProfile.profile_image_url,
            credits: defaultProfile.credits,
            is_admin: defaultProfile.is_admin,
            last_opened: defaultProfile.last_opened,
            tfa_app_name: defaultProfile.tfa_app_name,
            tfa_enabled: defaultProfile.tfa_enabled,
            consent_privacy_and_apps_default_settings: defaultProfile.consent_privacy_and_apps_default_settings,
            consent_mates_default_settings: defaultProfile.consent_mates_default_settings
        });

        // Reset temporary processed image URL even on error
        processedImageUrl.set(null);
        
        // Reset 2FA state even on error
        resetTwoFAData();
        
        // Reset signup step even on error
        currentSignupStep.set(1);

        // Reset the TFA resetting flag even on error
        isResettingTFA.set(false);

        // Reset device verification flag even on error
        needsDeviceVerification.set(false);
        
        // Reset the store state even on error
        set({
          ...initialState,
          isInitialized: true
        });
        
        // Call final logout callback even on error
        if (callbacks?.finalLogout) {
          await callbacks.finalLogout();
        }
        
        return false;
      }
    }
  };
}

// Create and export the auth store as a singleton
const authStoreInstance = createAuthStore();
export const authStore = authStoreInstance;

// Create a derived store for profile image URL with default fallback logic
export const profileImage = derived(
  authStore, // Depends on authStore to know if user is authenticated
  $authStore => {
    if ($authStore.isAuthenticated) {
      // Use get(userProfile) to access the store's value reactively
      return get(userProfile).profile_image_url || '@openmates/ui/static/images/placeholders/userprofileimage.jpeg';
    }
    // Return default placeholder if not authenticated
    return '@openmates/ui/static/images/placeholders/userprofileimage.jpeg';
  }
);
