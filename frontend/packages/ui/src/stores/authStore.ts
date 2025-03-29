import { writable, derived, get } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import { currentSignupStep, isInSignupProcess, getStepFromPath, isResettingTFA } from './signupState'; // Import isResettingTFA
import { userDB } from '../services/userDB';
import { userProfile, updateProfile, type UserProfile } from './userProfile'; // Import store and type
import { resetTwoFAData } from './twoFAState'; // Import the reset function

// Define the types for the auth store
interface AuthState {
  isAuthenticated: boolean;
  isInitialized: boolean;
}

// Define return type for the login function
interface LoginResult {
  success: boolean;
  tfa_required: boolean;
  message?: string;
  tfa_app_name?: string | null;
  inSignupFlow?: boolean;
}

// Create the initial state
const initialState: AuthState = {
  isAuthenticated: false,
  isInitialized: false
};

// Export auth checking state - moved from authCheckState.ts
export const isCheckingAuth = writable(false);

// Create the writable store
function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>(initialState);

  return {
    subscribe,
    
    // Check authentication status using session endpoint
    checkAuth: async (): Promise<boolean> => {
      isCheckingAuth.set(true);
      
      try {
        console.debug("Checking authentication with session endpoint...");
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.session), {
          method: 'POST',
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Origin': window.location.origin
          },
          body: JSON.stringify({}),  // Send empty body
          credentials: 'include' // Critical for sending cookies
        });

        // Process the response
        const data = await response.json();
        
        if (data.success && data.user) {
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
            isAuthenticated: true,
            isInitialized: true
          }));
          
          // Save the user data to IndexedDB
          try {
            await userDB.saveUserData(data.user);
            
            // Extract tfa_enabled status and consent flags
            const tfa_enabled = !!data.user.tfa_enabled;
            const consent_privacy_and_apps_default_settings = !!data.user.consent_privacy_and_apps_default_settings;
            const consent_mates_default_settings = !!data.user.consent_mates_default_settings;

            // Update the user profile store
            updateProfile({
              username: data.user.username,
              profileImageUrl: data.user.profile_image_url,
              tfaAppName: data.user.tfa_app_name,
              tfa_enabled: tfa_enabled, // Pass status
              credits: data.user.credits,
              isAdmin: data.user.is_admin,
              last_opened: data.user.last_opened,
              // Pass consent flags
              consent_privacy_and_apps_default_settings: consent_privacy_and_apps_default_settings,
              consent_mates_default_settings: consent_mates_default_settings
            });
          } catch (dbError) {
            console.error("Failed to save user data to database:", dbError);
          }
          
          return true;
        } else {
          // Not logged in or failed auth
          update(state => ({
            ...state,
            isAuthenticated: false,
            isInitialized: true
          }));
          
          return false;
        }
      } catch (error) {
        console.error("Auth check error:", error);
        
        // On error, assume not authenticated
        update(state => ({
            ...state,
            isAuthenticated: false,
            isInitialized: true
        }));
        
        return false;
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
            await userDB.updateUserData({ tfaAppName: appName });
            console.debug('IndexedDB updated with tfaAppName.');
          } catch (dbError) {
            console.error('Failed to update tfaAppName in IndexedDB:', dbError);
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
    
    // Login the user - updated for 2FA flow
    login: async (email: string, password: string, tfaCode?: string): Promise<LoginResult> => { // Add tfaCode param and return type
      try {
        console.debug(`Attempting login... (TFA Code Provided: ${!!tfaCode})`);
        
        // Construct request body
        const requestBody: any = {
          email: email.trim(),
          password: password
        };
        if (tfaCode) {
          requestBody.tfa_code = tfaCode;
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
            // Scenario: Full success (either no 2FA, or 2FA code was provided and valid)
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
                
                updateProfile({
                  username: data.user.username,
                  profileImageUrl: data.user.profile_image_url,
                  tfaAppName: data.user.tfa_app_name,
                  tfa_enabled: tfa_enabled, // Pass status
                  credits: data.user.credits,
                  isAdmin: data.user.is_admin,
                  last_opened: data.user.last_opened,
                  // Pass consent flags
                  consent_privacy_and_apps_default_settings: consent_privacy_and_apps_default_settings,
                  consent_mates_default_settings: consent_mates_default_settings
                });
              } else {
                 console.warn("Login successful but no user data received in response.");
              }
            } catch (dbError) {
              console.error("Failed to save user data to database:", dbError);
            }
            
             // Ensure return type matches LoginResult
            return { success: true, tfa_required: false, inSignupFlow };
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
    initialize: async () => {
      console.debug("Initializing auth state...");
      return await authStore.checkAuth();
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
        } catch (dbError) {
          console.error("Failed to clear user data from database:", dbError);
        }

        // Reset 2FA state
        resetTwoFAData();
        
        // Reset signup step
        currentSignupStep.set(1);

        // Reset the TFA resetting flag
        isResettingTFA.set(false);
        
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

        // Reset 2FA state even on error
        resetTwoFAData();
        
        // Reset signup step even on error
        currentSignupStep.set(1);

        // Reset the TFA resetting flag even on error
        isResettingTFA.set(false);
        
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
      return get(userProfile).profileImageUrl || '@openmates/ui/static/images/placeholders/userprofileimage.jpeg';
    }
    // Return default placeholder if not authenticated
    return '@openmates/ui/static/images/placeholders/userprofileimage.jpeg';
  }
);
