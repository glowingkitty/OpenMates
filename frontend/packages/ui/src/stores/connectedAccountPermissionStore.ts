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
	selectedActionIds: string[];
	selectedAccountIdsByActionId: Record<string, string>;
}

const initialState: ConnectedAccountPermissionState = {
	currentRequest: null,
	isVisible: false,
	isLoading: false,
	selectedAccountId: null,
	selectedActionIds: [],
	selectedAccountIdsByActionId: {}
};

function createConnectedAccountPermissionStore() {
	const { subscribe, set, update } = writable<ConnectedAccountPermissionState>(initialState);

	return {
		subscribe,

		showRequest(request: ConnectedAccountPermissionRequest) {
			const defaultAccountId = request.accounts[0]?.connected_account_id ?? null;
			const selectedActionIds = request.requests?.map((item) => item.action_id) ?? [];
			const selectedAccountIdsByActionId = Object.fromEntries(
				selectedActionIds.map((actionId) => [actionId, defaultAccountId ?? ''])
			);
			update((state) => ({
				...state,
				currentRequest: request,
				isVisible: true,
				isLoading: false,
				selectedAccountId: defaultAccountId,
				selectedActionIds,
				selectedAccountIdsByActionId
			}));
		},

		setSelectedAccount(accountId: string) {
			update((state) => ({
				...state,
				selectedAccountId: accountId,
				selectedAccountIdsByActionId: Object.fromEntries(
					(state.currentRequest?.requests ?? []).map((request) => [request.action_id, accountId])
				)
			}));
		},

		setSelectedAccountForAction(actionId: string, accountId: string) {
			update((state) => ({
				...state,
				selectedAccountIdsByActionId: {
					...state.selectedAccountIdsByActionId,
					[actionId]: accountId
				}
			}));
		},

		toggleAction(actionId: string, selected: boolean) {
			update((state) => {
				const selectedActionIds = selected
					? Array.from(new Set([...state.selectedActionIds, actionId]))
					: state.selectedActionIds.filter((selectedActionId) => selectedActionId !== actionId);
				return { ...state, selectedActionIds };
			});
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
		},

		getSelectedActionIds(): string[] {
			return get({ subscribe }).selectedActionIds;
		},

		getSelectedAccountIdForAction(actionId: string): string | null {
			const state = get({ subscribe });
			return state.selectedAccountIdsByActionId[actionId] || state.selectedAccountId;
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

export const selectedConnectedAccountPermissionActionIds = derived(
	connectedAccountPermissionStore,
	($store) => $store.selectedActionIds
);

export const selectedConnectedAccountPermissionAccountIdsByActionId = derived(
	connectedAccountPermissionStore,
	($store) => $store.selectedAccountIdsByActionId
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
