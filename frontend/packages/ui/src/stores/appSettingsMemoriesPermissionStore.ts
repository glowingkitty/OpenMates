// frontend/packages/ui/src/stores/appSettingsMemoriesPermissionStore.ts
/**
 * Store for managing the App Settings & Memories Permission Dialog state.
 * 
 * This store handles the display of permission dialogs when the AI assistant
 * requests access to app settings/memories that could be relevant for answering
 * the user's question.
 * 
 * Architecture:
 * 1. Server preprocessor determines which app settings/memories could be relevant
 * 2. Server sends "request_app_settings_memories" WebSocket message
 * 3. Client handler parses the request and updates this store
 * 4. Dialog component subscribes to this store and displays the permission UI
 * 5. User accepts/rejects and the store handles the response flow
 */

import { writable, derived, get } from 'svelte/store';
import type { PendingPermissionRequest } from '../services/chatSyncServiceHandlersAppSettings';

/**
 * State shape for the permission dialog store
 */
interface PermissionDialogState {
    /** Current pending request being shown (or null if no dialog is open) */
    currentRequest: PendingPermissionRequest | null;
    /** Whether the dialog is visible */
    isVisible: boolean;
    /** Loading state while processing confirmation */
    isLoading: boolean;
}

const initialState: PermissionDialogState = {
    currentRequest: null,
    isVisible: false,
    isLoading: false
};

/**
 * Create the permission dialog store
 */
function createPermissionDialogStore() {
    const { subscribe, set, update } = writable<PermissionDialogState>(initialState);
    
    return {
        subscribe,
        
        /**
         * Show the permission dialog with a new request
         */
        showDialog(request: PendingPermissionRequest) {
            console.info('[PermissionDialogStore] Showing dialog for request:', request.requestId);
            update(state => ({
                ...state,
                currentRequest: request,
                isVisible: true,
                isLoading: false
            }));
        },
        
        /**
         * Hide the dialog without any action
         */
        hideDialog() {
            console.info('[PermissionDialogStore] Hiding dialog');
            update(state => ({
                ...state,
                isVisible: false
            }));
        },
        
        /**
         * Update selection state for a category.
         * When toggling a category off, all its entries are deselected.
         * When toggling a category on, all its entries are re-selected.
         */
        toggleCategory(categoryKey: string) {
            update(state => {
                if (!state.currentRequest) return state;
                
                const updatedCategories = state.currentRequest.categories.map(cat => {
                    if (cat.key !== categoryKey) return cat;
                    const newSelected = !cat.selected;
                    // Also toggle all entries to match category state
                    const updatedEntries = cat.entries?.map(entry => ({
                        ...entry,
                        selected: newSelected,
                    }));
                    return { ...cat, selected: newSelected, entries: updatedEntries };
                });
                
                return {
                    ...state,
                    currentRequest: {
                        ...state.currentRequest,
                        categories: updatedCategories
                    }
                };
            });
        },

        /**
         * Toggle selection state for an individual entry within a category.
         * If all entries in a category are deselected, the category is also deselected.
         * If any entry is selected, the category is marked as selected.
         */
        toggleEntry(categoryKey: string, entryId: string) {
            update(state => {
                if (!state.currentRequest) return state;
                
                const updatedCategories = state.currentRequest.categories.map(cat => {
                    if (cat.key !== categoryKey || !cat.entries) return cat;
                    
                    const updatedEntries = cat.entries.map(entry =>
                        entry.id === entryId ? { ...entry, selected: !entry.selected } : entry
                    );
                    
                    // Category is selected if any entry is selected
                    const anySelected = updatedEntries.some(e => e.selected);
                    
                    return { ...cat, selected: anySelected, entries: updatedEntries };
                });
                
                return {
                    ...state,
                    currentRequest: {
                        ...state.currentRequest,
                        categories: updatedCategories
                    }
                };
            });
        },
        
        /**
         * Set loading state
         */
        setLoading(loading: boolean) {
            update(state => ({
                ...state,
                isLoading: loading
            }));
        },
        
        /**
         * Clear the dialog and reset state
         */
        clear() {
            console.info('[PermissionDialogStore] Clearing dialog state');
            set(initialState);
        },
        
        /**
         * Get selected category keys from current request
         */
        getSelectedKeys(): string[] {
            const state = get({ subscribe });
            if (!state.currentRequest) return [];
            return state.currentRequest.categories
                .filter(cat => cat.selected)
                .map(cat => cat.key);
        },

        /**
         * Get selected entry IDs per category key.
         * Returns a map of categoryKey -> entryIds[].
         * If a category has no entries array (legacy), returns null (meaning "all entries").
         */
        getSelectedEntryIdsByCategory(): Map<string, string[] | null> {
            const state = get({ subscribe });
            const result = new Map<string, string[] | null>();
            if (!state.currentRequest) return result;
            
            for (const cat of state.currentRequest.categories) {
                if (!cat.selected) continue;
                if (!cat.entries) {
                    // No entry-level info available — select all
                    result.set(cat.key, null);
                } else {
                    const selectedIds = cat.entries
                        .filter(e => e.selected)
                        .map(e => e.id);
                    if (selectedIds.length > 0) {
                        result.set(cat.key, selectedIds);
                    }
                }
            }
            return result;
        },
        
        /**
         * Get current request ID
         */
        getCurrentRequestId(): string | null {
            const state = get({ subscribe });
            return state.currentRequest?.requestId || null;
        },
        
        /**
         * Get current chat ID
         */
        getCurrentChatId(): string | null {
            const state = get({ subscribe });
            return state.currentRequest?.chatId || null;
        }
    };
}

// Export the store singleton
export const appSettingsMemoriesPermissionStore = createPermissionDialogStore();

// Derived stores for convenience
export const isPermissionDialogVisible = derived(
    appSettingsMemoriesPermissionStore,
    $store => $store.isVisible
);

export const currentPermissionRequest = derived(
    appSettingsMemoriesPermissionStore,
    $store => $store.currentRequest
);

export const permissionDialogLoading = derived(
    appSettingsMemoriesPermissionStore,
    $store => $store.isLoading
);

/**
 * Payload for dismiss event dispatched when server auto-rejects a pending request
 * (e.g., user sent a new message without responding to the permission dialog)
 */
interface DismissDialogEventDetail {
    requestId: string;
    chatId: string;
    reason: string;
    messageId: string;
}

/**
 * Initialize the store to listen for show and dismiss events.
 * Call this once at app startup (e.g., in app.ts or a layout component)
 * 
 * Events handled:
 * - showAppSettingsMemoriesPermissionDialog: Display the dialog for a new request
 * - dismissAppSettingsMemoriesPermissionDialog: Auto-dismiss (user sent new message without responding)
 */
export function initPermissionDialogListener() {
    if (typeof window === 'undefined') return;
    
    // Handler for showing the permission dialog
    const handleShowDialog = (event: CustomEvent<PendingPermissionRequest>) => {
        const request = event.detail;
        if (request) {
            appSettingsMemoriesPermissionStore.showDialog(request);
        }
    };
    
    // Handler for auto-dismissing the dialog (server rejected due to new user message)
    const handleDismissDialog = (event: CustomEvent<DismissDialogEventDetail>) => {
        const { requestId, reason } = event.detail;
        const currentRequestId = appSettingsMemoriesPermissionStore.getCurrentRequestId();
        
        // Only dismiss if this is the currently shown dialog
        if (currentRequestId && currentRequestId === requestId) {
            console.info(
                `[PermissionDialogStore] Auto-dismissing dialog for request ${requestId} ` +
                `(reason: ${reason})`
            );
            appSettingsMemoriesPermissionStore.clear();
        } else {
            console.debug(
                `[PermissionDialogStore] Ignoring dismiss for request ${requestId} ` +
                `(current: ${currentRequestId || 'none'})`
            );
        }
    };
    
    window.addEventListener('showAppSettingsMemoriesPermissionDialog', handleShowDialog as EventListener);
    window.addEventListener('dismissAppSettingsMemoriesPermissionDialog', handleDismissDialog as EventListener);
    
    console.info('[PermissionDialogStore] Initialized event listeners for permission dialog');
    
    // Return cleanup function
    return () => {
        window.removeEventListener('showAppSettingsMemoriesPermissionDialog', handleShowDialog as EventListener);
        window.removeEventListener('dismissAppSettingsMemoriesPermissionDialog', handleDismissDialog as EventListener);
    };
}
