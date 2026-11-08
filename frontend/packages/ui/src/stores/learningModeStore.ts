/**
 * Learning Mode Store
 *
 * Purpose: keep the browser UI aligned with Learning Mode policy.
 * Architecture: authenticated users use backend account policy; guests use a
 * browser-local (localStorage), passcode-locked record that is never sent to the
 * server. Only the non-secret request context (enabled, age group,
 * collaborative flag) is attached to anonymous free chat requests.
 * Tests: stores/__tests__/learningModeStore.test.ts and services/__tests__/learningModePasscode.test.ts.
 */

import { writable } from 'svelte/store';
import { getApiEndpoint } from '../config/api';
import {
	createLearningModePasscodeRecord,
	isLearningModePasscodeRecord,
	isValidLearningModePasscode,
	verifyLearningModePasscode,
	type LearningModePasscodeRecord
} from '../services/learningModePasscode';

export type LearningModeAgeGroup = 'under_10' | '10_12' | '13_15' | '16_18' | 'adult';

export interface LearningModeStatus {
	enabled: boolean;
	age_group: LearningModeAgeGroup | null;
	collaborative_build: boolean;
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
	collaborative_build: boolean;
	source: 'anonymous_session';
}

export type LearningModeFailureReason = 'wrong_passcode' | 'blocked' | 'invalid_passcode' | 'not_allowed';

export class LearningModeRequestError extends Error {
	constructor(
		message: string,
		public readonly status: number,
		public readonly reason: string | null = null,
		public readonly learningModeStatus: Partial<LearningModeStatus> | null = null
	) {
		super(message);
		this.name = 'LearningModeRequestError';
	}
}

/** Persisted guest record. Lives only in this browser's localStorage. */
interface GuestLearningModeRecord {
	enabled: boolean;
	age_group: LearningModeAgeGroup;
	collaborative_build: boolean;
	passcode: LearningModePasscodeRecord | null;
	failed_attempts: number;
	blocked_until: number | null;
}

export const GUEST_RECORD_STORAGE_KEY = 'openmates.learningMode.guest';
export const MAX_FAILED_PASSCODE_ATTEMPTS = 5;
export const PASSCODE_BLOCK_SECONDS = 24 * 60 * 60;
const DEFAULT_GUEST_AGE_GROUP: LearningModeAgeGroup = '13_15';
const VALID_AGE_GROUPS = new Set<LearningModeAgeGroup>(['under_10', '10_12', '13_15', '16_18', 'adult']);

const INITIAL_STATE: LearningModeStoreState = {
	enabled: false,
	age_group: null,
	collaborative_build: false,
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
		collaborative_build: status.enabled === true && status.collaborative_build === true,
		failed_attempts: status.failed_attempts ?? 0,
		deactivation_blocked_until: status.deactivation_blocked_until ?? null,
		loaded: true,
		loading: false,
		source: 'account'
	};
}

function getLocalStorage(): Storage | null {
	if (typeof window === 'undefined' || !window.localStorage) return null;
	return window.localStorage;
}

function nowSeconds(): number {
	return Math.floor(Date.now() / 1000);
}

function normalizeAgeGroup(value: string | null | undefined): LearningModeAgeGroup {
	return VALID_AGE_GROUPS.has(value as LearningModeAgeGroup)
		? value as LearningModeAgeGroup
		: DEFAULT_GUEST_AGE_GROUP;
}

function emptyGuestRecord(): GuestLearningModeRecord {
	return {
		enabled: false,
		age_group: DEFAULT_GUEST_AGE_GROUP,
		collaborative_build: false,
		passcode: null,
		failed_attempts: 0,
		blocked_until: null
	};
}

function readGuestRecord(): GuestLearningModeRecord {
	const raw = getLocalStorage()?.getItem(GUEST_RECORD_STORAGE_KEY);
	if (!raw) return emptyGuestRecord();
	let parsed: Record<string, unknown>;
	try {
		parsed = JSON.parse(raw) as Record<string, unknown>;
	} catch (error) {
		console.error('[learningModeStore] Ignoring unreadable guest Learning Mode record:', error);
		return emptyGuestRecord();
	}
	const passcode = isLearningModePasscodeRecord(parsed.passcode) ? parsed.passcode : null;
	const ageGroup = normalizeAgeGroup(typeof parsed.age_group === 'string' ? parsed.age_group : null);
	// A record without a passcode cannot be unlocked, so it never counts as enabled.
	const enabled = parsed.enabled === true && passcode !== null;
	return {
		enabled,
		age_group: ageGroup,
		collaborative_build: enabled && ageGroup !== 'under_10' && parsed.collaborative_build === true,
		passcode,
		failed_attempts: typeof parsed.failed_attempts === 'number' ? parsed.failed_attempts : 0,
		blocked_until: typeof parsed.blocked_until === 'number' ? parsed.blocked_until : null
	};
}

function writeGuestRecord(record: GuestLearningModeRecord): void {
	getLocalStorage()?.setItem(GUEST_RECORD_STORAGE_KEY, JSON.stringify(record));
}

function guestRecordToState(record: GuestLearningModeRecord): LearningModeStoreState {
	const blockedUntil = record.blocked_until !== null && record.blocked_until > nowSeconds()
		? record.blocked_until
		: null;
	return {
		enabled: record.enabled,
		age_group: record.enabled ? record.age_group : null,
		collaborative_build: record.enabled && record.collaborative_build,
		failed_attempts: record.failed_attempts,
		deactivation_blocked_until: blockedUntil,
		loaded: true,
		loading: false,
		source: 'guest_session'
	};
}

function guestStatusPayload(record: GuestLearningModeRecord): Partial<LearningModeStatus> {
	const { enabled, age_group, collaborative_build, failed_attempts, deactivation_blocked_until } = guestRecordToState(record);
	return { enabled, age_group, collaborative_build, failed_attempts, deactivation_blocked_until };
}

/**
 * Verify the guest passcode, applying the same lockout rules as accounts:
 * 5 wrong attempts block passcode-gated actions for 24 hours.
 */
async function requireGuestPasscode(record: GuestLearningModeRecord, passcode: string): Promise<GuestLearningModeRecord> {
	if (record.blocked_until !== null && record.blocked_until > nowSeconds()) {
		throw new LearningModeRequestError('blocked', 403, 'blocked', guestStatusPayload(record));
	}
	if (!record.passcode) {
		throw new LearningModeRequestError('not_allowed', 400, 'not_allowed', guestStatusPayload(record));
	}
	if (await verifyLearningModePasscode(passcode, record.passcode)) {
		const cleared = { ...record, failed_attempts: 0, blocked_until: null };
		writeGuestRecord(cleared);
		return cleared;
	}
	const attempts = record.failed_attempts + 1;
	const failed: GuestLearningModeRecord = {
		...record,
		failed_attempts: attempts,
		blocked_until: attempts >= MAX_FAILED_PASSCODE_ATTEMPTS ? nowSeconds() + PASSCODE_BLOCK_SECONDS : record.blocked_until
	};
	writeGuestRecord(failed);
	throw new LearningModeRequestError(
		attempts >= MAX_FAILED_PASSCODE_ATTEMPTS ? 'blocked' : 'wrong_passcode',
		403,
		attempts >= MAX_FAILED_PASSCODE_ATTEMPTS ? 'blocked' : 'wrong_passcode',
		guestStatusPayload(failed)
	);
}

function assertValidPasscode(passcode: string): void {
	if (!isValidLearningModePasscode(passcode)) {
		throw new LearningModeRequestError('invalid_passcode', 400, 'invalid_passcode');
	}
}

/** Collaborative building defaults to on, except for under_10 where it is always off. */
function resolveCollaborativeBuild(ageGroup: LearningModeAgeGroup, requested: boolean): boolean {
	return ageGroup !== 'under_10' && requested;
}

export function getAnonymousLearningModeContext(): AnonymousLearningModeContext | undefined {
	const status = guestRecordToState(readGuestRecord());
	if (!status.enabled || !status.age_group) return undefined;
	// Only non-secret policy fields; the passcode record and attempt counters stay local.
	return {
		enabled: true,
		age_group: status.age_group,
		collaborative_build: status.collaborative_build,
		source: 'anonymous_session'
	};
}

export function isLearningModeAuthError(error: unknown): boolean {
	return error instanceof LearningModeRequestError
		&& (error.status === 401 || error.status === 403);
}

async function parseError(response: Response, fallback: string): Promise<Error> {
	try {
		const body = await response.json();
		const detail = body?.detail;
		if (typeof detail === 'string') return new LearningModeRequestError(detail, response.status);
		if (detail?.reason) {
			const { reason, ...statusFields } = detail as Record<string, unknown>;
			return new LearningModeRequestError(
				String(reason),
				response.status,
				String(reason),
				statusFields as Partial<LearningModeStatus>
			);
		}
	} catch {
		// Response body is optional; fall back to the explicit status message below.
	}
	return new LearningModeRequestError(`${fallback} (HTTP ${response.status})`, response.status);
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

	/** Keep attempts/lockout in sync with the status a rejected passcode check returns. */
	function applyFailureStatus(error: unknown): void {
		if (!(error instanceof LearningModeRequestError) || !error.learningModeStatus) return;
		const failed = error.learningModeStatus;
		update((state) => ({
			...state,
			failed_attempts: failed.failed_attempts ?? state.failed_attempts,
			deactivation_blocked_until: failed.deactivation_blocked_until ?? state.deactivation_blocked_until
		}));
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
		activate: async (passcode: string, ageGroup: LearningModeAgeGroup, collaborativeBuild = true) => {
			const status = await request('/v1/learning-mode/activate', {
				passcode,
				age_group: ageGroup,
				collaborative_build: resolveCollaborativeBuild(ageGroup, collaborativeBuild)
			});
			const normalized = normalizeStatus(status);
			set(normalized);
			return normalized;
		},
		deactivate: async (passcode: string) => {
			try {
				const status = await request('/v1/learning-mode/deactivate', { passcode });
				const normalized = normalizeStatus(status);
				set(normalized);
				return normalized;
			} catch (error) {
				applyFailureStatus(error);
				throw error;
			}
		},
		/** Turning collaborative building ON needs the passcode; turning it OFF does not. */
		setCollaborativeBuild: async (enabled: boolean, passcode?: string) => {
			try {
				const status = await request('/v1/learning-mode/collaborative', enabled
					? { enabled, passcode }
					: { enabled });
				const normalized = normalizeStatus(status);
				set(normalized);
				return normalized;
			} catch (error) {
				applyFailureStatus(error);
				throw error;
			}
		},
		loadGuest: () => {
			const status = guestRecordToState(readGuestRecord());
			set(status);
			return status;
		},
		activateGuest: async (
			passcode: string,
			ageGroup: LearningModeAgeGroup,
			collaborativeBuild = true
		) => {
			assertValidPasscode(passcode);
			const record: GuestLearningModeRecord = {
				enabled: true,
				age_group: ageGroup,
				collaborative_build: resolveCollaborativeBuild(ageGroup, collaborativeBuild),
				passcode: await createLearningModePasscodeRecord(passcode),
				failed_attempts: 0,
				blocked_until: null
			};
			writeGuestRecord(record);
			const status = guestRecordToState(record);
			set(status);
			return status;
		},
		deactivateGuest: async (passcode: string) => {
			const current = readGuestRecord();
			if (!current.enabled) {
				const status = guestRecordToState(current);
				set(status);
				return status;
			}
			try {
				const unlocked = await requireGuestPasscode(current, passcode);
				const record: GuestLearningModeRecord = {
					...emptyGuestRecord(),
					age_group: unlocked.age_group
				};
				writeGuestRecord(record);
				const status = guestRecordToState(record);
				set(status);
				return status;
			} catch (error) {
				applyFailureStatus(error);
				throw error;
			}
		},
		setGuestCollaborativeBuild: async (enabled: boolean, passcode?: string) => {
			let current = readGuestRecord();
			if (!current.enabled || current.age_group === 'under_10') {
				throw new LearningModeRequestError('not_allowed', 400, 'not_allowed', guestStatusPayload(current));
			}
			try {
				if (enabled) {
					current = await requireGuestPasscode(current, passcode ?? '');
				}
				const record = { ...current, collaborative_build: enabled };
				writeGuestRecord(record);
				const status = guestRecordToState(record);
				set(status);
				return status;
			} catch (error) {
				applyFailureStatus(error);
				throw error;
			}
		},
		reset: () => set(INITIAL_STATE)
	};
}

export const learningMode = createLearningModeStore();
