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
}

// Create the main auth store with initial state
function createAuthStore() {
    const { subscribe, set, update } = writable<AuthState>({
        isAuthenticated: false,
        user: null,
    });

    return {
        subscribe,
        login: (userData: User) => {
            set({
                isAuthenticated: true,
                user: userData,
            });
            // Set overflow hidden style if user is authenticated
            if (browser) {
                document.body.style.overflow = 'hidden';
                isMenuOpen.set(true);
            }
        },
        logout: () => {
            AuthService.logout();
            set({
                isAuthenticated: false,
                user: null,
            });
            // Remove overflow hidden style when user logs out
            if (browser) {
                document.body.style.overflow = '';
            }
        },
        checkAuth: async () => {
            if (browser) {
                const isAuthed = await AuthService.checkAuth();
                if (!isAuthed) {
                    set({
                        isAuthenticated: false,
                        user: null
                    });
                }
            }
        }
    };
}

const authStore = createAuthStore();
export const isAuthenticated = derived(authStore, $auth => $auth.isAuthenticated);
export const currentUser = derived(authStore, $auth => $auth.user);
export const { login, logout, checkAuth } = authStore; 