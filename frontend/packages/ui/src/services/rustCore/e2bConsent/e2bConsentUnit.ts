/**
 * `e2bConsent` namespace installer of the shared Rust core Worker
 * (VITE_OPENMATES_RUST_CORE builds only). Marshalling only: each call runs on
 * the ADMITTED client of the bound history `core` lease (coreClientBorrow); the
 * consent route, version and refusals are the core's.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { CoreBorrowRefusal, CoreClientBorrow } from '../drafts/coreClientBorrow';
import { isE2bConsentUnitClose, type E2bConsentChoiceWire, type E2bConsentProtocol, type E2bConsentRecord, type E2bConsentStep } from './e2bConsentProtocol';

export const E2B_CONSENT_BORROW_TIMEOUT_MS = 10_000;

/** BrowserCoreClient exports of browser_e2b_consent.rs (JSON strings). */
export interface E2bConsentClient {
	e2b_consent_get(handle: string, generation: number): Promise<string>;
	e2b_consent_set(handle: string, generation: number, decision: string): Promise<string>;
	e2b_consent_request_step(handle: string, generation: number, frameJson: string, chatKey: Uint8Array): string;
	e2b_consent_answer_step(handle: string, generation: number, chatId: string, requestId: string, choice: string, chatKey: Uint8Array): string;
	e2b_consent_request_answer(systemContentsJson: string, requestId: string): string | undefined;
}

export interface E2bConsentDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal>;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

/** Core rejections are stable code strings; keep them, never internal text. */
function code(error: unknown): string {
	if (error instanceof UnitRefusal) return error.code;
	const raw = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return CODE.test(raw) ? raw : 'e2b_consent_failed';
}

function isDecision(value: unknown): value is E2bConsentRecord['decision'] {
	return value === null || value === 'allowed' || value === 'declined';
}

function parseRecord(raw: unknown): E2bConsentRecord {
	let value: unknown;
	try {
		value = typeof raw === 'string' ? JSON.parse(raw) : null;
	} catch {
		throw new UnitRefusal('e2b_consent_protocol');
	}
	const record = value as { decision?: unknown; decidedAt?: unknown; version?: unknown } | null;
	const decision = record?.decision;
	if (!record || !isDecision(decision)
		|| typeof record.version !== 'number' || (record.decidedAt !== null && typeof record.decidedAt !== 'number')) {
		throw new UnitRefusal('e2b_consent_protocol');
	}
	return { decision, decidedAt: record.decidedAt as number | null, version: record.version };
}

function parseStep(raw: unknown): E2bConsentStep {
	try {
		const step = typeof raw === 'string' ? (JSON.parse(raw) as E2bConsentStep) : null;
		if (step && Array.isArray(step.frames) && step.message && typeof step.message.message_id === 'string') return step;
	} catch {
		/* falls through to the refusal */
	}
	throw new UnitRefusal('e2b_consent_protocol');
}

function asChoice(value: unknown): E2bConsentChoiceWire {
	if (value === 'allow' || value === 'own_machine' || value === 'not_now') return value;
	throw new UnitRefusal('e2b_consent_bad_choice');
}

const defaultDeps = (): E2bConsentDeps => ({
	borrow: (principal, signal, timeoutMs) => borrowCoreClient(principal, signal, timeoutMs)
});

export function createE2bConsentHandlers(principal: string, deps: E2bConsentDeps,
	lifetime: AbortSignal): UnitHandlers<E2bConsentProtocol> {
	async function withClient<T>(run: (client: E2bConsentClient, handle: string, generation: number) => Promise<T>): Promise<T> {
		const borrow = await deps.borrow(principal, lifetime, E2B_CONSENT_BORROW_TIMEOUT_MS);
		if (borrow === 'none') throw new UnitRefusal('not_admitted');
		if (borrow === 'busy') throw new UnitRefusal('core_busy');
		if (borrow === 'local') throw new UnitRefusal('local_session');
		try {
			return await run(borrow.client as unknown as E2bConsentClient, borrow.status.handle, borrow.status.generation);
		} catch (error) {
			throw new UnitRefusal(code(error));
		} finally {
			borrow.release();
		}
	}
	return {
		requestStep: (payload) => {
			const { frame, chatKey } = payload as { frame?: unknown; chatKey?: unknown };
			if (!frame || typeof frame !== 'object' || !(chatKey instanceof Uint8Array)) throw new UnitRefusal('e2b_consent_bad_request');
			return withClient(async (client, handle, generation) =>
				parseStep(client.e2b_consent_request_step(handle, generation, JSON.stringify(frame), chatKey)));
		},
		answerStep: (payload) => {
			const { chatId, requestId, choice, chatKey } = payload as { chatId?: unknown; requestId?: unknown; choice?: unknown; chatKey?: unknown };
			if (typeof chatId !== 'string' || typeof requestId !== 'string' || !(chatKey instanceof Uint8Array)) throw new UnitRefusal('e2b_consent_bad_request');
			const wire = asChoice(choice);
			return withClient(async (client, handle, generation) =>
				parseStep(client.e2b_consent_answer_step(handle, generation, chatId, requestId, wire, chatKey)));
		},
		answer: (payload) => {
			const { systemContents, requestId } = payload as { systemContents?: unknown; requestId?: unknown };
			if (!Array.isArray(systemContents) || typeof requestId !== 'string') throw new UnitRefusal('e2b_consent_bad_request');
			return withClient(async (client) => {
				const choice = client.e2b_consent_request_answer(JSON.stringify(systemContents), requestId);
				return choice === undefined || choice === null ? null : asChoice(choice);
			});
		},
		get: () => withClient(async (client, handle, generation) => parseRecord(await client.e2b_consent_get(handle, generation))),
		set: (payload) => {
			const decision = (payload as { decision?: unknown } | null)?.decision;
			if (decision !== 'allowed' && decision !== 'declined') throw new UnitRefusal('e2b_consent_bad_decision');
			return withClient(async (client, handle, generation) =>
				parseRecord(await client.e2b_consent_set(handle, generation, decision)));
		}
	};
}

export function installE2bConsentUnit(context: UnitInstallContext, deps: E2bConsentDeps = defaultDeps()): () => void {
	const principal = context.principal;
	if (context.ports.length !== 1 || !principal) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<E2bConsentProtocol>(port, createE2bConsentHandlers(principal, deps, context.signal));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		port.removeEventListener('message', control);
		stop();
		port.close();
	};
	function control(event: MessageEvent<unknown>): void {
		if (isE2bConsentUnitClose(event.data)) dispose();
	}
	port.addEventListener('message', control);
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
