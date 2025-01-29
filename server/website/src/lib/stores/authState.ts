import { writable, derived } from 'svelte/store';
import { AuthService } from '../services/authService';
import { browser } from '$app/environment';
import { isMenuOpen } from './menuState';

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
            // Set initial overflow state if user is authenticated
            document.body.style.overflow = 'hidden';
        }
    }

    const { subscribe, set, update } = writable<AuthState>(initialState);

    return {
        subscribe,
        login: (token: string, userData: User, isMobile: boolean = false) => {
            AuthService.persistAuth(token, userData);
            // Set body overflow to hidden when user logs in
            if (browser) {
                document.body.style.overflow = 'hidden';
                // Only set isMenuOpen to true if not on mobile
                if (!isMobile) {
                    isMenuOpen.set(true);
                }
            }
            set({
                isAuthenticated: true,
                user: userData,
                token
            });
        },
        logout: () => {
            AuthService.clearAuth();
            // Remove overflow hidden style when user logs out
            if (browser) {
                document.body.style.overflow = '';
            }
            set({
                isAuthenticated: false,
                user: null,
                token: null
            });
            
            localStorage.clear();
            sessionStorage.clear();
            
            document.cookie.split(";").forEach(cookie => {
                document.cookie = cookie
                    .replace(/^ +/, "")
                    .replace(/=.*/, `=;expires=${new Date().toUTCString()};path=/`);
            });
        }
    };
}

const authStore = createAuthStore();
export const isAuthenticated = derived(authStore, $auth => $auth.isAuthenticated);
export const currentUser = derived(authStore, $auth => $auth.user);
export const { login, logout } = authStore; 