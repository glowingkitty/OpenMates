// frontend/packages/ui/src/stores/appHealthStore.ts
//
// Store for managing app health status from the /v1/health endpoint.
// Filters apps based on their health status to ensure only healthy apps
// are shown in the app store.
//
// **Data Source**: 
// - API endpoint: /v1/health (public, no auth required)
// - Fetched once at app initialization
// - Health status is cached and updated periodically

import { writable, derived, get } from 'svelte/store';
import { getApiEndpoint } from '../config/api';

// --- Types ---

/**
 * Health status for an app's API and worker.
 */
interface AppHealthStatus {
    /** Overall app status: "healthy" | "degraded" | "unhealthy" */
    status: string;
    /** API health status */
    api: {
        status: string;
        last_error: string | null;
    };
    /** Worker health status */
    worker: {
        status: string;
        last_error: string | null;
    };
    /** Last health check timestamp */
    last_check: number | null;
}

/**
 * Health endpoint response structure.
 */
interface HealthResponse {
    status: string;
    providers: Record<string, any>;
    apps: Record<string, AppHealthStatus>;
    external_services: Record<string, any>;
}

interface AppHealthState {
    /** Map of app_id to health status */
    appHealth: Record<string, AppHealthStatus>;
    /** Whether health status has been fetched */
    initialized: boolean;
    /** Whether the fetch is in progress */
    loading: boolean;
    /** Error message if fetch failed */
    error: string | null;
    /** Last fetch timestamp */
    lastFetch: number | null;
}

// --- Initial State ---

const initialState: AppHealthState = {
    appHealth: {},
    initialized: false,
    loading: false,
    error: null,
    lastFetch: null
};

// --- Store ---

const appHealthStore = writable<AppHealthState>(initialState);

// --- Derived Values ---

/**
 * Get health status for a specific app.
 * Returns null if app health status is not available.
 */
export const getAppHealth = derived(
    appHealthStore,
    ($state) => (appId: string): AppHealthStatus | null => {
        return $state.appHealth[appId] || null;
    }
);

/**
 * Check if an app's API is healthy (api.status === "healthy").
 * Returns false if app health status is not available (safe default - hide app if health unknown).
 * 
 * Note: We check the API status, not the overall app status, because an app can be "degraded"
 * (e.g., worker is unhealthy) but still have a healthy API that can serve requests.
 */
export const isAppHealthy = derived(
    appHealthStore,
    ($state) => (appId: string): boolean => {
        const health = $state.appHealth[appId];
        if (!health) {
            // If health status is not available, return false to hide the app
            // This ensures apps that aren't in the health endpoint are filtered out
            return false;
        }
        // Check if the API is healthy (not the overall app status)
        // An app can be "degraded" (e.g., worker unhealthy) but still have a healthy API
        return health.api?.status === 'healthy';
    }
);

/**
 * Whether the app health status has been initialized (fetched at least once).
 */
export const isAppHealthInitialized = derived(
    appHealthStore,
    ($state) => $state.initialized
);

// --- Actions ---

/**
 * Fetches app health status from the /v1/health endpoint.
 * This should be called once at app initialization (e.g., in +page.svelte or +layout.svelte).
 * 
 * If already initialized, this is a no-op unless `force` is true.
 * 
 * @param force - If true, refetch even if already initialized
 * @returns The fetched health data, or null if fetch failed
 */
export async function initializeAppHealth(force: boolean = false): Promise<HealthResponse | null> {
    const currentState = get(appHealthStore);
    
    // Skip if already initialized (unless force refresh)
    if (currentState.initialized && !force) {
        console.debug('[AppHealthStore] Already initialized, skipping fetch');
        return {
            status: currentState.appHealth ? 'healthy' : 'unknown',
            providers: {},
            apps: currentState.appHealth,
            external_services: {}
        };
    }
    
    // Skip if already loading
    if (currentState.loading) {
        console.debug('[AppHealthStore] Already loading, skipping duplicate fetch');
        return null;
    }
    
    // Set loading state
    appHealthStore.update(state => ({
        ...state,
        loading: true,
        error: null
    }));
    
    try {
        console.debug('[AppHealthStore] Fetching app health status...');
        const response = await fetch(getApiEndpoint('/v1/health'));
        
        if (!response.ok) {
            throw new Error(`Failed to fetch health status: ${response.status}`);
        }
        
        const data: HealthResponse = await response.json();
        
        console.debug('[AppHealthStore] Health status fetched:', {
            totalApps: Object.keys(data.apps || {}).length,
            appIds: Object.keys(data.apps || {})
        });
        
        // Update store with fetched health data
        appHealthStore.set({
            appHealth: data.apps || {},
            initialized: true,
            loading: false,
            error: null,
            lastFetch: Date.now()
        });
        
        return data;
    } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        console.error('[AppHealthStore] Error fetching app health status:', errorMessage);
        
        // Update store with error (but mark as initialized to prevent retry loops)
        appHealthStore.update(state => ({
            ...state,
            initialized: true, // Mark as initialized even on error to prevent infinite retries
            loading: false,
            error: errorMessage,
            lastFetch: Date.now()
        }));
        
        return null;
    }
}

/**
 * Resets the app health store to initial state.
 * Useful for testing or when the user logs out.
 */
export function resetAppHealth(): void {
    appHealthStore.set(initialState);
}

// Export the store for direct access if needed
export { appHealthStore };
