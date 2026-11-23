/**
 * Page client of the shared Worker's `e2bConsent` unit (VITE_OPENMATES_RUST_CORE
 * builds only). No logic here: the core reads and changes the account decision
 * and owns the refusals; failures reject with the core's stable code.
 * Specification: assertion code-run.e2b.upload-consent.
 */
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import { withServerSession } from '../projects/projectTimelineClient';
import { writable, type Readable } from 'svelte/store';
import {
	E2B_CONSENT_UNIT_CLOSE, type E2bConsentChoiceWire, type E2bConsentProtocol, type E2bConsentRecord, type E2bConsentStep, type E2bDecision
} from './e2bConsentProtocol';

export const E2B_CONSENT_RUST_ENABLED: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

const BIND_WAIT_MS = 15_000;
const BIND_POLL_MS = 50;
const CALL_TIMEOUT_MS = 20_000;

interface Opened { core: SharedRustCore; generation: number; unit: UnitPort<E2bConsentProtocol>; close(): void }
let current: { generation: number; opening: Promise<Opened> } | null = null;

async function boundGeneration(core: SharedRustCore): Promise<number> {
	const deadline = Date.now() + BIND_WAIT_MS;
	while (core.generation === null) {
		if (Date.now() >= deadline) throw new UnitPortError('e2b_consent_not_bound');
		await new Promise((resolve) => setTimeout(resolve, BIND_POLL_MS));
	}
	return core.generation;
}

async function open(core: SharedRustCore, generation: number): Promise<Opened> {
	const raw = await core.openUnit('e2bConsent');
	const unit = createUnitPort<E2bConsentProtocol>(raw);
	let stopCrash = () => {};
	const close = () => {
		stopCrash();
		if (unit.closed) return;
		raw.postMessage(E2B_CONSENT_UNIT_CLOSE);
		unit.close();
	};
	stopCrash = core.onCrash(close);
	return { core, generation, unit, close };
}

async function unit(): Promise<UnitPort<E2bConsentProtocol>> {
	if (!E2B_CONSENT_RUST_ENABLED) throw new UnitPortError('e2b_consent_unavailable');
	const core = requireSharedRustCore();
	const generation = await boundGeneration(core);
	if (current?.generation === generation) {
		const opened = await current.opening;
		if (opened.core === core && !opened.unit.closed) return opened.unit;
	}
	const stale = current;
	stale?.opening.then((opened) => opened.close(), () => undefined);
	const opening = open(core, generation);
	current = { generation, opening };
	opening.catch(() => { if (current?.opening === opening) current = null; });
	return (await opening).unit;
}

async function call<K extends keyof E2bConsentProtocol & string>(op: K,
	payload: E2bConsentProtocol[K]['request']): Promise<E2bConsentProtocol[K]['response']> {
	const core = requireSharedRustCore();
	const release = core.hold();
	try {
		return await withServerSession(async () => (await unit()).request(op, payload, { timeoutMs: CALL_TIMEOUT_MS }));
	} finally {
		release();
	}
}

/** The account's E2B upload decision (null decision: none yet for this wording version). */
export function readE2bConsent(): Promise<E2bConsentRecord> {
	return call('get', {});
}

/** Change the account decision (settings). */
export function writeE2bConsent(decision: E2bDecision): Promise<E2bConsentRecord> {
	return call('set', { decision });
}

/** Core step for a `request_e2b_upload_consent` frame: frames to send plus the encrypted message to store. */
export function e2bConsentRequestStep(frame: Record<string, unknown>, chatKey: Uint8Array): Promise<E2bConsentStep> {
	return call('requestStep', { frame, chatKey });
}

/** Core step for the user's choice: the answer frame plus the encrypted response message to store. */
export function e2bConsentAnswerStep(chatId: string, requestId: string, choice: E2bConsentChoiceWire,
	chatKey: Uint8Array): Promise<E2bConsentStep> {
	return call('answerStep', { chatId, requestId, choice, chatKey });
}

/** The core's answered check over decrypted system message contents: the choice, or null while unanswered. */
export function e2bConsentAnswerOf(systemContents: string[], requestId: string): Promise<E2bConsentChoiceWire | null> {
	return call('answer', { systemContents, requestId });
}

/** Decision pushed by `e2b_upload_consent_updated` (null until one arrives); the gating code reads it. */
const decisionStore = writable<E2bConsentRecord | null>(null);
export const e2bConsentDecision: Readable<E2bConsentRecord | null> = { subscribe: decisionStore.subscribe };

/** Store the decision of an `e2b_upload_consent_updated` frame `{decision, decided_at, version}`. */
export function recordE2bConsentUpdate(payload: { decision?: unknown; decided_at?: unknown; version?: unknown }): void {
	const decision = payload.decision;
	if ((decision !== 'allowed' && decision !== 'declined') || typeof payload.version !== 'number') return;
	decisionStore.set({
		decision,
		decidedAt: typeof payload.decided_at === 'number' ? payload.decided_at : null,
		version: payload.version
	});
}
