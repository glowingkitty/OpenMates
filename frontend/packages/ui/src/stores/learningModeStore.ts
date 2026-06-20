/**
 * Learning Mode Store
 *
 * Purpose: keep the browser UI aligned with the account-wide backend policy.
 * Architecture: authenticated REST state, not localStorage, so clearing browser
 * state cannot disable Learning Mode. Used by settings and chat send payloads.
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
}

const INITIAL_STATE: LearningModeStoreState = {
	enabled: false,
	age_group: null,
	failed_attempts: 0,
	deactivation_blocked_until: null,
	loaded: false,
	loading: false
};

function normalizeStatus(status: LearningModeStatus): LearningModeStoreState {
	return {
		enabled: status.enabled === true,
		age_group: status.age_group ?? null,
		failed_attempts: status.failed_attempts ?? 0,
		deactivation_blocked_until: status.deactivation_blocked_until ?? null,
		loaded: true,
		loading: false
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
				update((state) => ({ ...state, loading: false }));
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
		reset: () => set(INITIAL_STATE)
	};
}

export const learningMode = createLearningModeStore();
