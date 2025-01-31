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
    isInitialized: boolean;  // Add this to track initialization
}

// Create the main auth store with initial state
function createAuthStore() {
    const { subscribe, set, update } = writable<AuthState>({
        isAuthenticated: false,
        user: null,
        isInitialized: false
    });

    return {
        subscribe,
        login: (userData: User) => {
            console.log('Setting auth state to logged in:', userData);
            set({
                isAuthenticated: true,
                user: userData,
                isInitialized: true
            });
            if (browser) {
                document.body.style.overflow = 'hidden';
                isMenuOpen.set(true);
            }
        },
        logout: () => {
            console.log('Setting auth state to logged out');
            AuthService.logout();
            set({
                isAuthenticated: false,
                user: null,
                isInitialized: true
            });
            if (browser) {
                document.body.style.overflow = '';
            }
        },
        checkAuth: async () => {
            if (browser) {
                console.log('Checking auth state...');
                const authResult = await AuthService.checkAuth();
                console.log('Auth check result:', authResult);
                
                if (authResult.isAuthenticated && authResult.email) {
                    console.log('Setting auth state to authenticated:', authResult.email);
                    set({
                        isAuthenticated: true,
                        user: { email: authResult.email },
                        isInitialized: true
                    });
                } else {
                    console.log('Setting auth state to not authenticated');
                    set({
                        isAuthenticated: false,
                        user: null,
                        isInitialized: true
                    });
                }
            }
        }
    };
}

const authStore = createAuthStore();
export const isAuthenticated = derived(authStore, $auth => $auth.isAuthenticated);
export const currentUser = derived(authStore, $auth => $auth.user);
export const isAuthInitialized = derived(authStore, $auth => $auth.isInitialized);
export const { login, logout, checkAuth } = authStore; 