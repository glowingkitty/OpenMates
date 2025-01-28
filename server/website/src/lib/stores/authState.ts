import { writable, derived } from 'svelte/store';
import { AuthService } from '../services/authService';
import { browser } from '$app/environment';

export interface User {
    email: string;
    // Add other user properties as needed
}

interface AuthState {
    isAuthenticated: boolean;
    user: User | null;
    token: string | null;
}

// Create the main auth store with initial state from storage
function createAuthStore() {
    // Initialize with stored data if in browser
    let initialState: AuthState = {
        isAuthenticated: false,
        user: null,
        token: null
    };

    if (browser) {
        const { token, userData } = AuthService.loadStoredAuth();
        if (token && userData && AuthService.isTokenValid(token)) {
            initialState = {
                isAuthenticated: true,
                user: userData,
                token
            };
        }
    }

    const { subscribe, set, update } = writable<AuthState>(initialState);

    return {
        subscribe,
        login: (token: string, userData: User) => {
            AuthService.persistAuth(token, userData);
            set({
                isAuthenticated: true,
                user: userData,
                token
            });
            
            // Set body overflow to hidden when logged in
            if (typeof document !== 'undefined') {
                document.body.style.overflow = 'hidden';
            }
        },
        logout: () => {
            // Use AuthService to clear storage
            AuthService.clearAuth();
            
            // Reset store values
            set({
                isAuthenticated: false,
                user: null,
                token: null
            });
            
            // Clear all browser storage
            localStorage.clear();
            sessionStorage.clear();
            
            // Clear cookies
            document.cookie.split(";").forEach(cookie => {
                document.cookie = cookie
                    .replace(/^ +/, "")
                    .replace(/=.*/, `=;expires=${new Date().toUTCString()};path=/`);
            });
            
            // Reset body overflow when logged out
            if (typeof document !== 'undefined') {
                document.body.style.overflow = 'scroll';
            }
        }
    };
}

const authStore = createAuthStore();
export const isAuthenticated = derived(authStore, $auth => $auth.isAuthenticated);
export const currentUser = derived(authStore, $auth => $auth.user);
export const { login, logout } = authStore;

// Add reactive store subscription to handle initial state
if (typeof document !== 'undefined') {
    isAuthenticated.subscribe(($isAuthenticated) => {
        document.body.style.overflow = $isAuthenticated ? 'hidden' : 'scroll';
    });
} 