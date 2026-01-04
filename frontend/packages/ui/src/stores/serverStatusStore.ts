/**
 * Server Status Store
 * 
 * Stores server configuration status (self-hosted, payment enabled, etc.)
 * that is fetched once at app initialization and shared across all components.
 * 
 * This prevents multiple API calls to /v1/settings/server-status and avoids
 * UI flashing issues (e.g., legal chats briefly showing on self-hosted instances).
 */

import { writable, derived, get } from 'svelte/store';
import { getApiEndpoint } from '../config/api';

// --- Types ---

interface ServerStatus {
    /** Whether this is a self-hosted instance (localhost or custom domain) */
    is_self_hosted: boolean;
    /** Whether payment features are enabled */
    payment_enabled: boolean;
    /** Server edition: "production" | "development" | "self_hosted" */
    server_edition: string | null;
    /** The domain of the server */
    domain: string | null;
}

interface ServerStatusState {
    /** The server status data */
    status: ServerStatus | null;
    /** Whether the status has been fetched */
    initialized: boolean;
    /** Whether the fetch is in progress */
    loading: boolean;
    /** Error message if fetch failed */
    error: string | null;
}

// --- Initial State ---

const initialState: ServerStatusState = {
    status: null,
    initialized: false,
    loading: false,
    error: null
};

// --- Store ---

const serverStatusStore = writable<ServerStatusState>(initialState);

// --- Derived Values ---

/**
 * Whether this is a self-hosted instance.
 * Returns false until status is fetched (safe default - shows legal chats).
 * After fetch, returns the actual self-hosted status.
 * 
 * IMPORTANT: Components should use this derived value instead of checking
 * the raw status object to handle the loading state correctly.
 */
export const isSelfHosted = derived(
    serverStatusStore,
    ($state) => $state.status?.is_self_hosted ?? false
);

/**
 * Whether payment features are enabled.
 * Returns true until status is fetched (safe default - assumes payment enabled).
 * After fetch, returns the actual payment enabled status.
 */
export const isPaymentEnabled = derived(
    serverStatusStore,
    ($state) => $state.status?.payment_enabled ?? true
);

/**
 * Server edition: "production" | "development" | "self_hosted" | null
 */
export const serverEdition = derived(
    serverStatusStore,
    ($state) => $state.status?.server_edition ?? null
);

/**
 * Whether the server status has been initialized (fetched at least once).
 * Components can use this to conditionally render content that depends on server status.
 */
export const isServerStatusInitialized = derived(
    serverStatusStore,
    ($state) => $state.initialized
);

// --- Actions ---

/**
 * Fetches the server status from the API.
 * This should be called once at app initialization (e.g., in +layout.svelte or App.svelte).
 * 
 * If already initialized, this is a no-op unless `force` is true.
 * 
 * @param force - If true, refetch even if already initialized
 * @returns The fetched server status, or null if fetch failed
 */
export async function initializeServerStatus(force: boolean = false): Promise<ServerStatus | null> {
    const currentState = get(serverStatusStore);
    
    // Skip if already initialized (unless force refresh)
    if (currentState.initialized && !force) {
        console.debug('[ServerStatusStore] Already initialized, skipping fetch');
        return currentState.status;
    }
    
    // Skip if already loading
    if (currentState.loading) {
        console.debug('[ServerStatusStore] Already loading, skipping duplicate fetch');
        return null;
    }
    
    // Set loading state
    serverStatusStore.update(state => ({
        ...state,
        loading: true,
        error: null
    }));
    
    try {
        console.debug('[ServerStatusStore] Fetching server status...');
        const response = await fetch(getApiEndpoint('/v1/settings/server-status'));
        
        if (!response.ok) {
            throw new Error(`Failed to fetch server status: ${response.status}`);
        }
        
        const data = await response.json();
        
        const status: ServerStatus = {
            is_self_hosted: data.is_self_hosted ?? false,
            payment_enabled: data.payment_enabled ?? true,
            server_edition: data.server_edition ?? null,
            domain: data.domain ?? null
        };
        
        console.debug('[ServerStatusStore] Server status fetched:', status);
        
        // Update store with fetched status
        serverStatusStore.set({
            status,
            initialized: true,
            loading: false,
            error: null
        });
        
        return status;
    } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        console.error('[ServerStatusStore] Error fetching server status:', errorMessage);
        
        // Update store with error (but mark as initialized to prevent retry loops)
        serverStatusStore.update(state => ({
            ...state,
            initialized: true, // Mark as initialized even on error to prevent infinite retries
            loading: false,
            error: errorMessage
        }));
        
        return null;
    }
}

/**
 * Resets the server status store to initial state.
 * Useful for testing or when the user logs out.
 */
export function resetServerStatus(): void {
    serverStatusStore.set(initialState);
}

// Export the store for direct access if needed
export { serverStatusStore };

