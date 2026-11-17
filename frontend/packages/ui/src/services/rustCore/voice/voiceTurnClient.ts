/**
 * Page client of the shared Worker's `voiceTurn` unit (VITE_OPENMATES_RUST_CORE
 * builds only). One port per bound generation, opened lazily, as the project
 * timeline client does. No logic here: the core builds the snapshot request and
 * the encrypted `chat_turn_admit` payload; the page only carries frames on its
 * one main socket. Failures reject with the core's stable code.
 */
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import { withServerSession } from '../projects/projectTimelineClient';
import { VOICE_TURN_UNIT_CLOSE, type VoiceTurnProtocol } from './voiceTurnProtocol';

export const VOICE_TURN_RUST_ENABLED: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

const BIND_WAIT_MS = 15_000;
const BIND_POLL_MS = 50;
const CALL_TIMEOUT_MS = 20_000;

/** Read-only diagnostics (E2E asserts the unit served the call turn). */
export const rustVoiceTurnStats = { begins: 0, commits: 0, failures: 0 };
// Test-only read hook under browser automation (navigator.webdriver) only.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustVoiceTurnStats?: () => typeof rustVoiceTurnStats })
		.__openmatesRustVoiceTurnStats = () => ({ ...rustVoiceTurnStats });
}

interface Opened { core: SharedRustCore; generation: number; unit: UnitPort<VoiceTurnProtocol>; close(): void }
let current: { generation: number; opening: Promise<Opened> } | null = null;

async function boundGeneration(core: SharedRustCore): Promise<number> {
	const deadline = Date.now() + BIND_WAIT_MS;
	while (core.generation === null) {
		if (Date.now() >= deadline) throw new UnitPortError('voice_turn_not_bound');
		await new Promise((resolve) => setTimeout(resolve, BIND_POLL_MS));
	}
	return core.generation;
}

async function open(core: SharedRustCore, generation: number): Promise<Opened> {
	const raw = await core.openUnit('voiceTurn');
	const unit = createUnitPort<VoiceTurnProtocol>(raw);
	let stopCrash = () => {};
	const close = () => {
		stopCrash();
		if (unit.closed) return;
		raw.postMessage(VOICE_TURN_UNIT_CLOSE);
		unit.close();
	};
	stopCrash = core.onCrash(close);
	return { core, generation, unit, close };
}

async function unit(): Promise<UnitPort<VoiceTurnProtocol>> {
	if (!VOICE_TURN_RUST_ENABLED) throw new UnitPortError('voice_turn_unavailable');
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

async function call<K extends keyof VoiceTurnProtocol & string>(op: K,
	payload: VoiceTurnProtocol[K]['request']): Promise<VoiceTurnProtocol[K]['response']> {
	const core = requireSharedRustCore();
	const release = core.hold();
	try {
		return await withServerSession(async () => (await unit()).request(op, payload, { timeoutMs: CALL_TIMEOUT_MS }));
	} catch (error) {
		rustVoiceTurnStats.failures++;
		throw error;
	} finally {
		release();
	}
}

/** Start a turn: the core returns the snapshot request frame and an opaque id. */
export function beginVoiceTurn(chatId: string, turnId: string): Promise<VoiceTurnProtocol['begin']['response']> {
	rustVoiceTurnStats.begins++;
	return call('begin', { chatId, turnId });
}

/** Hand the socket's snapshot result to the core (text-independent stage). */
export async function prepareVoiceTurn(voiceId: string, snapshotResult: Record<string, unknown>): Promise<void> {
	await call('prepare', { voiceId, snapshotResult });
}

/** Final transcript: the core returns the encrypted admit payload. */
export function commitVoiceTurn(request: VoiceTurnProtocol['commit']['request']): Promise<VoiceTurnProtocol['commit']['response']> {
	rustVoiceTurnStats.commits++;
	return call('commit', request);
}

/** Drop a begun or prepared turn; nothing is sent. Never throws. */
export async function discardVoiceTurn(voiceId: string): Promise<void> {
	try {
		await call('discard', { voiceId });
	} catch (error) {
		console.warn('[voiceTurnClient] Discard unavailable:', error instanceof UnitPortError ? error.code : 'failed');
	}
}
