import { writable } from 'svelte/store';
import { getApiEndpoint, apiEndpoints } from '../config/api';

// Define user type
interface User {
  id: string;
  username: string;
  isAdmin?: boolean;
  avatarUrl?: string;
}

// Create the auth store
function createAuthStore() {
  const { subscribe, set, update } = writable<{
    isAuthenticated: boolean;
    isLoading: boolean;
    user: User | null;
  }>({
    isAuthenticated: false,
    isLoading: true,
    user: null,
  });

  return {
    subscribe,
    
    // Initialize the auth store by checking if user is logged in
    init: async () => {
      try {
        // Check if user is logged in by getting user session status
        const response = await fetch(getApiEndpoint('/v1/auth/session'), {
          method: 'GET',
          credentials: 'include',
        });
        
        if (response.ok) {
          const userData = await response.json();
          set({
            isAuthenticated: true,
            isLoading: false,
            user: {
              id: userData.id,
              username: userData.username,
              isAdmin: userData.is_admin,
              avatarUrl: userData.avatar_url,
            },
          });
          
          // Store username in localStorage for components that need it
          localStorage.setItem('user_display_name', userData.username);
          
          return true;
        } else {
          set({
            isAuthenticated: false,
            isLoading: false,
            user: null,
          });
          
          return false;
        }
      } catch (error) {
        console.error('Error initializing auth store:', error);
        set({
          isAuthenticated: false,
          isLoading: false,
          user: null,
        });
        
        return false;
      }
    },
    
    // Login method
    login: async (email: string, password: string) => {
      try {
        update(state => ({ ...state, isLoading: true }));
        
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ email, password }),
          credentials: 'include',
        });
        
        const data = await response.json();
        
        if (response.ok && data.success) {
          set({
            isAuthenticated: true,
            isLoading: false,
            user: data.user,
          });
          
          // Store username in localStorage for components that need it
          localStorage.setItem('user_display_name', data.user.username);
          
          return { success: true, message: data.message };
        } else {
          update(state => ({ ...state, isLoading: false }));
          return { success: false, message: data.message };
        }
      } catch (error) {
        console.error('Login error:', error);
        update(state => ({ ...state, isLoading: false }));
        return { 
          success: false, 
          message: 'An error occurred while trying to log in.'
        };
      }
    },
    
    // Set authentication state directly (useful after email verification)
    setAuthenticated: (isAuthenticated: boolean) => {
      update(state => ({
        ...state,
        isAuthenticated,
        isLoading: false
      }));
    },
    
    // Logout method
    logout: async () => {
      try {
        update(state => ({ ...state, isLoading: true }));
        
        const response = await fetch(getApiEndpoint(apiEndpoints.auth.logout), {
          method: 'POST',
          credentials: 'include',
        });
        
        // Clear user data regardless of server response
        set({
          isAuthenticated: false,
          isLoading: false,
          user: null,
        });
        
        // Clear local storage
        localStorage.removeItem('user_display_name');
        
        return response.ok;
      } catch (error) {
        console.error('Logout error:', error);
        
        // Still clear user data on error
        set({
          isAuthenticated: false,
          isLoading: false,
          user: null,
        });
        
        localStorage.removeItem('user_display_name');
        
        return false;
      }
    },
    
    // Update user data
    updateUser: (userData: Partial<User>) => {
      update(state => ({
        ...state,
        user: state.user ? { ...state.user, ...userData } : userData as User,
      }));
      
      if (userData.username) {
        localStorage.setItem('user_display_name', userData.username);
      }
    }
  };
}

export const authStore = createAuthStore();
