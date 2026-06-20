/**
 * Learning Mode Store
 *
 * Purpose: keep the browser UI aligned with Learning Mode policy.
 * Architecture: authenticated users use backend account policy; guests use
 * sessionStorage-only request opt-in for anonymous free chat.
 * Tests: covered through Learning Mode specs and focused sender/store tests.
 */

import { writable } from 'svelte/store';
import { getApiEndpoint } from '../config/api';

export type LearningModeAgeGroup = 'under_10' | '10_12' | '13_15' | '16_18' | 'adult';

export interface LearningModeStatus {
	enabled: boolean;
	age_group: LearningModeAgeGroup | null;
	failed_attempts: number;
	deactivation_blocked_until: number | null;
}

interface LearningModeStoreState extends LearningModeStatus {
	loaded: boolean;
	loading: boolean;
	source: 'account' | 'guest_session' | null;
}

export interface AnonymousLearningModeContext {
	enabled: true;
	age_group: LearningModeAgeGroup;
	source: 'anonymous_session';
}

const GUEST_ENABLED_STORAGE_KEY = 'openmates.learningMode.enabled';
const GUEST_AGE_GROUP_STORAGE_KEY = 'openmates.learningMode.ageGroup';
const DEFAULT_GUEST_AGE_GROUP: LearningModeAgeGroup = '13_15';
const VALID_AGE_GROUPS = new Set<LearningModeAgeGroup>(['under_10', '10_12', '13_15', '16_18', 'adult']);

const INITIAL_STATE: LearningModeStoreState = {
	enabled: false,
	age_group: null,
	failed_attempts: 0,
	deactivation_blocked_until: null,
	loaded: false,
	loading: false,
	source: null
};

function normalizeStatus(status: LearningModeStatus): LearningModeStoreState {
	return {
		enabled: status.enabled === true,
		age_group: status.age_group ?? null,
		failed_attempts: status.failed_attempts ?? 0,
		deactivation_blocked_until: status.deactivation_blocked_until ?? null,
		loaded: true,
		loading: false,
		source: 'account'
	};
}

function getSessionStorage(): Storage | null {
	if (typeof window === 'undefined' || !window.sessionStorage) return null;
	return window.sessionStorage;
}

function normalizeAgeGroup(value: string | null | undefined): LearningModeAgeGroup {
	return VALID_AGE_GROUPS.has(value as LearningModeAgeGroup)
		? value as LearningModeAgeGroup
		: DEFAULT_GUEST_AGE_GROUP;
}

function readGuestStatus(): LearningModeStoreState {
	const storage = getSessionStorage();
	const enabled = storage?.getItem(GUEST_ENABLED_STORAGE_KEY) === 'true';
	const ageGroup = normalizeAgeGroup(storage?.getItem(GUEST_AGE_GROUP_STORAGE_KEY));
	return {
		enabled,
		age_group: enabled ? ageGroup : null,
		failed_attempts: 0,
		deactivation_blocked_until: null,
		loaded: true,
		loading: false,
		source: 'guest_session'
	};
}

function writeGuestStatus(enabled: boolean, ageGroup: LearningModeAgeGroup): LearningModeStoreState {
	const storage = getSessionStorage();
	if (storage) {
		storage.setItem(GUEST_ENABLED_STORAGE_KEY, String(enabled));
		storage.setItem(GUEST_AGE_GROUP_STORAGE_KEY, ageGroup);
	}
	return readGuestStatus();
}

export function getAnonymousLearningModeContext(): AnonymousLearningModeContext | undefined {
	const status = readGuestStatus();
	if (!status.enabled || !status.age_group) return undefined;
	return {
		enabled: true,
		age_group: status.age_group,
		source: 'anonymous_session'
	};
}

async function parseError(response: Response, fallback: string): Promise<Error> {
	try {
		const body = await response.json();
		const detail = body?.detail;
		if (typeof detail === 'string') return new Error(detail);
		if (detail?.reason) return new Error(String(detail.reason));
	} catch {
		// Response body is optional; fall back to the explicit status message below.
	}
	return new Error(`${fallback} (HTTP ${response.status})`);
}

function createLearningModeStore() {
	const { subscribe, set, update } = writable<LearningModeStoreState>(INITIAL_STATE);

	async function request(path: string, body?: Record<string, unknown>): Promise<LearningModeStatus> {
		const endpoint = getApiEndpoint(path);
		let response: Response;
		try {
			response = await fetch(endpoint, {
				method: body ? 'POST' : 'GET',
				credentials: 'include',
				headers: body ? { 'Content-Type': 'application/json' } : undefined,
				body: body ? JSON.stringify(body) : undefined
			});
		} catch (error) {
			throw new Error(`Learning Mode request failed for ${endpoint}: ${error instanceof Error ? error.message : String(error)}`);
		}
		if (!response.ok) {
			throw await parseError(response, 'Learning Mode request failed');
		}
		return await response.json() as LearningModeStatus;
	}

	return {
		subscribe,
		load: async () => {
			update((state) => ({ ...state, loading: true }));
			try {
				const status = await request('/v1/learning-mode');
				const normalized = normalizeStatus(status);
				set(normalized);
				return normalized;
			} catch (error) {
				update((state) => ({ ...state, loaded: true, loading: false, source: 'account' }));
				throw error;
			}
		},
		activate: async (passcode: string, ageGroup: LearningModeAgeGroup) => {
			const status = await request('/v1/learning-mode/activate', {
				passcode,
				age_group: ageGroup
			});
			const normalized = normalizeStatus(status);
			set(normalized);
			return normalized;
		},
		deactivate: async (passcode: string) => {
			const status = await request('/v1/learning-mode/deactivate', { passcode });
			const normalized = normalizeStatus(status);
			set(normalized);
			return normalized;
		},
		loadGuest: () => {
			const status = readGuestStatus();
			set(status);
			return status;
		},
		activateGuest: (ageGroup: LearningModeAgeGroup) => {
			const status = writeGuestStatus(true, ageGroup);
			set(status);
			return status;
		},
		deactivateGuest: () => {
			const status = writeGuestStatus(false, normalizeAgeGroup(getSessionStorage()?.getItem(GUEST_AGE_GROUP_STORAGE_KEY)));
			set(status);
			return status;
		},
		reset: () => set(INITIAL_STATE)
	};
}

export const learningMode = createLearningModeStore();
