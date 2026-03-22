// frontend/packages/ui/src/stores/mostUsedAppsStore.ts
//
// Store for managing most used apps state.
// Compatible with Svelte 5 components using $state().
//
// This store manages the state of most used apps fetched from the API.
// The fetch is triggered from +page.svelte on app load to ensure data is
// available when the App Store opens.

import { writable } from 'svelte/store';

/**
 * Most used apps store state interface.
 */
export interface MostUsedAppsState {
    /**
     * Array of app IDs sorted by usage (most used first).
     */
    appIds: string[];
    
    /**
     * Whether the fetch is currently in progress.
     */
    loading: boolean;
    
    /**
     * Timestamp of the last successful fetch.
     * Used for cache duration checks (1 hour).
     */
    lastFetch: number | null;
    
    /**
     * Current retry attempt count.
     */
    retryCount: number;
}

/**
 * Initial state for most used apps store.
 */
const initialState: MostUsedAppsState = {
    appIds: [],
    loading: false,
    lastFetch: null,
    retryCount: 0
};

// Constants for retry mechanism
const CACHE_DURATION = 60 * 60 * 1000; // 1 hour in milliseconds
const RETRY_DELAYS = [1000, 5000, 15000]; // Progressive delays: 1s, 5s, 15s
const MAX_RETRIES = 3;

// Create the writable store
const { subscribe, set, update } = writable<MostUsedAppsState>(initialState);

/**
 * Most used apps store for managing most used apps state.
 * 
 * This store manages the state of most used apps fetched from the API.
 * The fetch is triggered from +page.svelte on app load to ensure data is
 * available when the App Store opens.
 * 
 * **Usage in components (Svelte 5)**:
 * ```svelte
 * <script>
 *   import { mostUsedAppsStore } from '@repo/ui/stores/mostUsedAppsStore';
 *   
 *   // Subscribe to store state
 *   let mostUsedApps = $state($mostUsedAppsStore);
 *   
 *   // Access app IDs reactively
 *   $effect(() => {
 *     console.log('Most used apps:', mostUsedApps.appIds);
 *   });
 * </script>
 * ```
 */
export const mostUsedAppsStore = {
    subscribe,
    
    /**
     * Get the current state.
     * Components should use this with $state() for reactivity.
     */
    getState(): MostUsedAppsState {
        let state: MostUsedAppsState = initialState;
        subscribe(current => {
            state = current;
        })();
        return state;
    },
    
    /**
     * Fetch most used apps from API with retry mechanism.
     * This is a public endpoint that doesn't require authentication.
     * 
     * Implements:
     * - Cache duration check (1 hour)
     * - Progressive retry delays (1s, 5s, 15s)
     * - Maximum retry limit
     * - Prevents duplicate concurrent requests
     * 
     * @param retryAttempt - Current retry attempt number (default: 0)
     */
    async fetchMostUsedApps(retryAttempt: number = 0): Promise<void> {
        const now = Date.now();
        
        // Check current state to prevent duplicate concurrent requests
        let currentState: MostUsedAppsState = initialState;
        subscribe(state => {
            currentState = state;
        })();
        
        // Prevent duplicate concurrent requests
        if (currentState.loading) {
            console.debug('[MostUsedAppsStore] Most used apps fetch already in progress, skipping');
            return;
        }
        
        // Check if we have recent cached data (within cache duration)
        if (currentState.lastFetch !== null) {
            const cacheAge = now - currentState.lastFetch;
            if (cacheAge < CACHE_DURATION) {
                console.debug(`[MostUsedAppsStore] Most used apps cache still valid (${Math.round(cacheAge / 1000)}s old), skipping fetch`);
                return;
            }
        }
        
        // Check retry limit
        if (retryAttempt >= MAX_RETRIES) {
            console.warn('[MostUsedAppsStore] Max retries reached for most used apps, giving up');
            update(state => ({
                ...state,
                loading: false
            }));
            return;
        }
        
        // Set loading state
        update(state => ({
            ...state,
            loading: true
        }));
        
        try {
            const { getApiEndpoint } = await import('../config/api');
            const { apiEndpoints } = await import('../config/api');
            const response = await fetch(getApiEndpoint(apiEndpoints.apps.mostUsed));
            
            if (response.ok) {
                const data = await response.json();
                // Extract app IDs from the response
                const fetchedAppIds = data.apps?.map((app: { app_id: string }) => app.app_id) || [];
                
                // Update state with fetched data
                update(state => ({
                    ...state,
                    appIds: fetchedAppIds,
                    lastFetch: now,
                    retryCount: 0,
                    loading: false
                }));
                
                // Use Array.from() to avoid $state proxy warning in console.debug
                console.debug('[MostUsedAppsStore] Successfully fetched most used apps:', Array.from(fetchedAppIds));
            } else {
                console.warn(`[MostUsedAppsStore] Failed to fetch most used apps: ${response.status} ${response.statusText}`);
                
                // Retry on server errors (5xx) or rate limiting (429)
                if (response.status >= 500 || response.status === 429) {
                    await mostUsedAppsStore.scheduleRetry(retryAttempt);
                } else {
                    // Don't retry on client errors (4xx except 429)
                    update(state => ({
                        ...state,
                        appIds: [],
                        loading: false,
                        lastFetch: now // Update timestamp to prevent immediate retry
                    }));
                }
            }
        } catch (error) {
            console.error('[MostUsedAppsStore] Error fetching most used apps:', error);
            await mostUsedAppsStore.scheduleRetry(retryAttempt);
        }
    },
    
    /**
     * Schedule a retry with progressive delay.
     * 
     * @param retryAttempt - Current retry attempt number
     */
    async scheduleRetry(retryAttempt: number): Promise<void> {
        if (retryAttempt >= MAX_RETRIES) {
            update(state => ({
                ...state,
                loading: false
            }));
            return;
        }
        
        const delay = RETRY_DELAYS[retryAttempt] || RETRY_DELAYS[RETRY_DELAYS.length - 1];
        
        // Update retry count
        update(state => ({
            ...state,
            retryCount: retryAttempt + 1
        }));
        
        console.debug(`[MostUsedAppsStore] Scheduling retry ${retryAttempt + 1}/${MAX_RETRIES} for most used apps in ${delay}ms`);
        
        // Wait for the delay before retrying
        await new Promise(resolve => setTimeout(resolve, delay));
        
        // Retry the fetch
        await mostUsedAppsStore.fetchMostUsedApps(retryAttempt + 1);
    },
    
    /**
     * Reset the store to initial state.
     */
    reset(): void {
        set(initialState);
    }
};

