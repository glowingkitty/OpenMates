// frontend/packages/ui/src/stores/connectedAccountPermissionStore.ts
//
// Holds the browser-only approval state for connected-account action requests.
// Approval decrypts account rows locally and sends only opaque turn-token refs
// back to the backend continuation handler.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { derived, get, writable } from 'svelte/store';

export interface ConnectedAccountPermissionAccount {
	connected_account_id: string;
	app_id: string;
	account_ref?: string;
	label: string;
	capabilities: string[];
	runtime_modes?: Record<string, string>;
}

export interface ConnectedAccountPermissionRequest {
	requestId: string;
	chatId: string;
	messageId?: string;
	appId: string;
	skillId: string;
	action: string;
	requiredActions: string[];
	accounts: ConnectedAccountPermissionAccount[];
	requests?: Array<{
		action_id: string;
		action: string;
		action_scope?: Record<string, unknown>;
		summary?: Record<string, unknown>;
	}>;
	createdAt: number;
}

interface ConnectedAccountPermissionState {
	currentRequest: ConnectedAccountPermissionRequest | null;
	isVisible: boolean;
	isLoading: boolean;
	selectedAccountId: string | null;
}

const initialState: ConnectedAccountPermissionState = {
	currentRequest: null,
	isVisible: false,
	isLoading: false,
	selectedAccountId: null
};

function createConnectedAccountPermissionStore() {
	const { subscribe, set, update } = writable<ConnectedAccountPermissionState>(initialState);

	return {
		subscribe,

		showRequest(request: ConnectedAccountPermissionRequest) {
			update((state) => ({
				...state,
				currentRequest: request,
				isVisible: true,
				isLoading: false,
				selectedAccountId: request.accounts[0]?.connected_account_id ?? null
			}));
		},

		setSelectedAccount(accountId: string) {
			update((state) => ({ ...state, selectedAccountId: accountId }));
		},

		setLoading(isLoading: boolean) {
			update((state) => ({ ...state, isLoading }));
		},

		clear() {
			set(initialState);
		},

		getCurrentRequest(): ConnectedAccountPermissionRequest | null {
			return get({ subscribe }).currentRequest;
		},

		getSelectedAccountId(): string | null {
			return get({ subscribe }).selectedAccountId;
		}
	};
}

export const connectedAccountPermissionStore = createConnectedAccountPermissionStore();

export const isConnectedAccountPermissionVisible = derived(
	connectedAccountPermissionStore,
	($store) => $store.isVisible
);

export const currentConnectedAccountPermissionRequest = derived(
	connectedAccountPermissionStore,
	($store) => $store.currentRequest
);

export const connectedAccountPermissionLoading = derived(
	connectedAccountPermissionStore,
	($store) => $store.isLoading
);

export const selectedConnectedAccountPermissionAccountId = derived(
	connectedAccountPermissionStore,
	($store) => $store.selectedAccountId
);

export function initConnectedAccountPermissionListener() {
	if (typeof window === 'undefined') return;

	const handleShowRequest = (event: CustomEvent<ConnectedAccountPermissionRequest>) => {
		if (event.detail) {
			connectedAccountPermissionStore.showRequest(event.detail);
		}
	};

	window.addEventListener(
		'showConnectedAccountPermissionRequest',
		handleShowRequest as EventListener
	);

	return () => {
		window.removeEventListener(
			'showConnectedAccountPermissionRequest',
			handleShowRequest as EventListener
		);
	};
}
