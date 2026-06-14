/**
 * Server Status Store
 * 
 * Stores server configuration status (self-hosted, AI model readiness, etc.)
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
    /** Cloud-only payment status. Self-hosted responses omit this field. */
    payment_enabled?: boolean;
    /** Server edition: "production" | "development" | "self_hosted" */
    server_edition: string | null;
    /** The domain of the server */
    domain: string | null;
    /** Whether at least one server-side AI model provider key is configured */
    ai_models_configured: boolean;
    /** Safe public metadata for signup Free testing credits promotion */
    free_testing_credits?: {
        active: boolean;
        grant_credits: number;
    } | null;
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

export const FREE_TESTING_CREDITS_DEVICE_GRANT_STORAGE_KEY = 'openmates_free_testing_credits_granted';
export const PENDING_GIFT_CARD_CODE_STORAGE_KEY = 'pending_gift_card_code';

function readFreeTestingCreditsDeviceGrantFlag(): boolean {
    if (typeof localStorage === 'undefined') {
        return false;
    }

    try {
        return localStorage.getItem(FREE_TESTING_CREDITS_DEVICE_GRANT_STORAGE_KEY) === 'true';
    } catch (error) {
        console.warn('[ServerStatusStore] Failed to read Free testing credits device flag:', error);
        return false;
    }
}

function readPendingGiftCardCode(): string | null {
    if (typeof sessionStorage === 'undefined') {
        return null;
    }

    try {
        return sessionStorage.getItem(PENDING_GIFT_CARD_CODE_STORAGE_KEY);
    } catch (error) {
        console.warn('[ServerStatusStore] Failed to read pending gift card code:', error);
        return null;
    }
}

// --- Store ---

const serverStatusStore = writable<ServerStatusState>(initialState);
export const freeTestingCreditsDeviceGrantReceived = writable<boolean>(readFreeTestingCreditsDeviceGrantFlag());
export const pendingGiftCardRedemption = writable<boolean>(!!readPendingGiftCardCode());

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
 * Server edition: "production" | "development" | "self_hosted" | null
 */
export const serverEdition = derived(
    serverStatusStore,
    ($state) => $state.status?.server_edition ?? null
);

export const freeTestingCreditsPromotion = derived(
    serverStatusStore,
    ($state) => $state.status?.free_testing_credits ?? null
);

export const signupFreeTestingCreditsPromotion = derived(
    [freeTestingCreditsPromotion, freeTestingCreditsDeviceGrantReceived, pendingGiftCardRedemption],
    ([$promotion, $deviceGrantReceived, $pendingGiftCardRedemption]) => {
        if (!$promotion?.active || $deviceGrantReceived || $pendingGiftCardRedemption) {
            return null;
        }
        return $promotion;
    }
);

export function getPendingGiftCardRedemptionCode(): string | null {
    return readPendingGiftCardCode();
}

export function refreshPendingGiftCardRedemptionFromStorage(): void {
    pendingGiftCardRedemption.set(!!readPendingGiftCardCode());
}

export function markPendingGiftCardRedemption(code: string): void {
    if (typeof sessionStorage !== 'undefined') {
        try {
            sessionStorage.setItem(PENDING_GIFT_CARD_CODE_STORAGE_KEY, code);
        } catch (error) {
            console.warn('[ServerStatusStore] Failed to persist pending gift card code:', error);
        }
    }
    pendingGiftCardRedemption.set(true);
}

export function clearPendingGiftCardRedemption(): void {
    if (typeof sessionStorage !== 'undefined') {
        try {
            sessionStorage.removeItem(PENDING_GIFT_CARD_CODE_STORAGE_KEY);
        } catch (error) {
            console.warn('[ServerStatusStore] Failed to clear pending gift card code:', error);
        }
    }
    pendingGiftCardRedemption.set(false);
}

export function hasDeviceReceivedFreeTestingCredits(): boolean {
    return get(freeTestingCreditsDeviceGrantReceived);
}

export function refreshFreeTestingCreditsDeviceGrantFromStorage(): void {
    freeTestingCreditsDeviceGrantReceived.set(readFreeTestingCreditsDeviceGrantFlag());
}

export function markDeviceReceivedFreeTestingCredits(): void {
    if (typeof localStorage !== 'undefined') {
        try {
            localStorage.setItem(FREE_TESTING_CREDITS_DEVICE_GRANT_STORAGE_KEY, 'true');
        } catch (error) {
            console.warn('[ServerStatusStore] Failed to persist Free testing credits device flag:', error);
        }
    }
    freeTestingCreditsDeviceGrantReceived.set(true);
}

export function markDeviceReceivedFreeTestingCreditsFromNotification(messageKey?: string): void {
    if (messageKey === 'signup.free_testing_credits_received') {
        markDeviceReceivedFreeTestingCredits();
    }
}

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
            payment_enabled: data.is_self_hosted ? false : data.payment_enabled ?? true,
            server_edition: data.server_edition ?? null,
            domain: data.domain ?? null,
            ai_models_configured: data.ai_models_configured ?? true,
            free_testing_credits: data.free_testing_credits ?? null
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

// Export the store for direct access if needed
export { serverStatusStore };
