// frontend/packages/ui/src/stores/adminStatusStore.ts
/**
 * Store for managing server admin status
 *
 * This store tracks whether the current user has server admin privileges
 * and provides methods for checking and updating admin status.
 */

import { writable, derived, get } from 'svelte/store';
import { getApiEndpoint } from '../config/api';
import { authStore } from './authState';

// Admin status state
interface AdminStatus {
    isAdmin: boolean;
    isLoading: boolean;
    error: string | null;
    lastChecked: number | null;
}

const initialState: AdminStatus = {
    isAdmin: false,
    isLoading: false,
    error: null,
    lastChecked: null
};

// Create the store
export const adminStatusStore = writable<AdminStatus>(initialState);

// Derived store for easier access to isAdmin flag
export const isAdmin = derived(adminStatusStore, ($status) => $status.isAdmin);

// Check cache validity (5 minutes)
const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes

function isCacheValid(lastChecked: number | null): boolean {
    if (!lastChecked) return false;
    return Date.now() - lastChecked < CACHE_DURATION;
}

/**
 * Check admin status from server
 */
export async function checkAdminStatus(forceRefresh = false): Promise<void> {
    const currentStatus = get(adminStatusStore);

    // Return cached result if valid and not forcing refresh
    if (!forceRefresh && isCacheValid(currentStatus.lastChecked)) {
        return;
    }

    // Check if user is authenticated first
    const authState = get(authStore);
    if (!authState || !authState.isAuthenticated) {
        adminStatusStore.set({
            isAdmin: false,
            isLoading: false,
            error: null,
            lastChecked: Date.now()
        });
        return;
    }

    try {
        adminStatusStore.update(state => ({
            ...state,
            isLoading: true,
            error: null
        }));

        const response = await fetch(getApiEndpoint('/v1/admin/status'), {
            method: 'GET',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            if (response.status === 401) {
                // User not authenticated
                adminStatusStore.set({
                    isAdmin: false,
                    isLoading: false,
                    error: null,
                    lastChecked: Date.now()
                });
                return;
            }
            throw new Error(`Failed to check admin status: ${response.statusText}`);
        }

        const data = await response.json();

        adminStatusStore.set({
            isAdmin: data.is_admin || false,
            isLoading: false,
            error: null,
            lastChecked: Date.now()
        });

    } catch (error) {
        console.error('Error checking admin status:', error);

        adminStatusStore.set({
            isAdmin: false,
            isLoading: false,
            error: error instanceof Error ? error.message : 'Unknown error',
            lastChecked: Date.now()
        });
    }
}

/**
 * Clear admin status (on logout)
 */
export function clearAdminStatus(): void {
    adminStatusStore.set(initialState);
}

/**
 * Mark user as admin (after successful become-admin flow)
 */
export function setAdminStatus(isAdmin: boolean): void {
    adminStatusStore.update(state => ({
        ...state,
        isAdmin,
        lastChecked: Date.now()
    }));
}

/**
 * Initialize admin status checking
 * Should be called when the app starts or user logs in
 */
export function initAdminStatus(): void {
    // Check immediately
    checkAdminStatus();

    // Subscribe to auth state changes to update admin status
    authStore.subscribe(($authState) => {
        if ($authState && $authState.isAuthenticated) {
            // User logged in, check admin status
            checkAdminStatus();
        } else {
            // User logged out, clear admin status
            clearAdminStatus();
        }
    });
}

// Auto-initialize when store is imported
if (typeof window !== 'undefined') {
    initAdminStatus();
}