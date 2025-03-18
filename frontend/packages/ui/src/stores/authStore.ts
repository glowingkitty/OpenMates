import { writable, derived } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import type { User } from '../types/user';

// Define the types for the auth store
interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  isInitialized: boolean;
}

// Create the initial state
const initialState: AuthState = {
  isAuthenticated: false,
  user: null,
  isInitialized: false
};

// Export auth checking state - moved from authCheckState.ts
export const isCheckingAuth = writable(false);

// Create the writable store
function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>(initialState);

  return {
    subscribe,
    
    // Initialize the auth state by checking for existing session
    init: async () => {
      try {
        isCheckingAuth.set(true);
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.session), {
          credentials: 'include',
          headers: {
            'Accept': 'application/json'
          }
        });

        if (response.ok) {
          const userData = await response.json();
          
          update(state => ({
            ...state,
            isAuthenticated: true,
            user: {
              id: userData.id,
              username: userData.username || 'User',
              isAdmin: userData.is_admin || false,
              profileImageUrl: userData.avatar_url || null
            },
            isInitialized: true
          }));
          
          return true;
        } else {
          set({
            ...initialState,
            isInitialized: true
          });
          return false;
        }
      } catch (error) {
        console.error("Auth init error:", error);
        set({
          ...initialState,
          isInitialized: true
        });
        return false;
      } finally {
        isCheckingAuth.set(false);
      }
    },
    
    // Login the user
    login: async (email: string, password: string) => {
      try {
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': window.location.origin
          },
          body: JSON.stringify({
            email: email.trim(),
            password: password
          }),
          credentials: 'include'
        });

        if (response.status === 429) {
          return { success: false, message: "Too many login attempts. Please try again later." };
        }

        const data = await response.json();

        if (!response.ok) {
          return { success: false, message: data.message || "Login failed" };
        }

        if (data.success && data.user) {
          update(state => ({
            ...state,
            isAuthenticated: true,
            user: {
              id: data.user.id,
              username: data.user.username || 'User',
              isAdmin: data.user.is_admin || false,
              profileImageUrl: data.user.avatar_url || null
            }
          }));
          return { success: true };
        } else {
          return { success: false, message: data.message || "Login failed" };
        }
      } catch (error) {
        console.error("Login error:", error);
        return { success: false, message: "An error occurred during login" };
      }
    },
    
    // Handle signup completion and auto-login
    completeSignup: (userData: any) => {
      if (userData && userData.id) {
        update(state => ({
          ...state,
          isAuthenticated: true,
          user: {
            id: userData.id,
            username: userData.username || 'User',
            isAdmin: userData.is_admin || false,
            profileImageUrl: null // New users won't have a profile image yet
          }
        }));
        return true;
      }
      return false;
    },
    
    // Update user information
    updateUser: (userData: Partial<User>) => {
      update(state => ({
        ...state,
        user: state.user ? { ...state.user, ...userData } : null
      }));
    },
    
    // Set authentication state directly (useful for API responses that confirm auth)
    setAuthenticated: (value: boolean) => {
      update(state => ({
        ...state,
        isAuthenticated: value
      }));
    },
    
    // Logout the user with optional callbacks for complex logout flows
    logout: async (callbacks?: {
      beforeServerLogout?: () => void | Promise<void>,
      afterServerLogout?: () => void | Promise<void>,
      onError?: (error: any) => void | Promise<void>,
      finalLogout?: () => void | Promise<void>
    }) => {
      try {
        console.log('Logging out...');
        
        // Call pre-logout callback if provided
        if (callbacks?.beforeServerLogout) {
          await callbacks.beforeServerLogout();
        }
        
        // Make the logout request to the server
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
        
        // Call post-server-logout callback if provided
        if (callbacks?.afterServerLogout) {
          await callbacks.afterServerLogout();
        }
        
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

// Create and export the auth store
export const authStore = createAuthStore();

// Create a derived store for profile image URL with default fallback logic
export const profileImage = derived(
  authStore,
  $authStore => {
    if ($authStore.isAuthenticated && $authStore.user?.profileImageUrl) {
      return $authStore.user.profileImageUrl;
    }
    return '@openmates/ui/static/images/placeholders/userprofileimage.jpeg';
  }
);
