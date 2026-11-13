/**
 * Page side of the shared Rust core Worker `chatState` unit.
 *
 * Opens the pre-bind `chatState` namespace lazily (unbound: it holds no account
 * state, so unbind/account switch does not close it) and reopens it after a
 * Worker crash. Every call holds a registry lease so idle retirement never cuts
 * an in-flight decision. There is no TypeScript fallback: a refused or failed
 * call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import type { ChatStateUnitProtocol } from './chatListProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustChatStateStats = {
	calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number>,
	/** performance.now() marks (ms since navigation start): prepare/first call start, core ready, port open, first answer. */
	phases: {} as Record<string, number>,
};
const mark = (name: string): void => { rustChatStateStats.phases[name] ??= Math.round(performance.now()); };
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustChatStateStats?: () => typeof rustChatStateStats }).__openmatesRustChatStateStats =
		() => ({ ...rustChatStateStats, ops: { ...rustChatStateStats.ops }, phases: { ...rustChatStateStats.phases } });
}

let port: UnitPort<ChatStateUnitProtocol> | null = null;
let opening: Promise<UnitPort<ChatStateUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<ChatStateUnitProtocol>> {
	mark('openStart');
	const opened = createUnitPort<ChatStateUnitProtocol>(await core.openUnit('chatState', { unbound: true }));
	mark('opened');
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustChatStateStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<ChatStateUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

/**
 * Opens the unit ahead of the first chat-list decision (app start, while the
 * sidebar data is still being read): the Worker, WASM binding and installer
 * chunk load in parallel with the first chat-list fetch instead of after it.
 * Not a fallback: the first call still awaits the same port.
 */
export async function prepareChatStateUnit(): Promise<void> {
	mark('prepareStart');
	const core = await whenSharedRustCore();
	mark('coreReady');
	await unit(core);
}

export async function chatStateCall<K extends keyof ChatStateUnitProtocol & string>(
	op: K, payload: ChatStateUnitProtocol[K]['request'],
): Promise<ChatStateUnitProtocol[K]['response']> {
	mark('firstCall');
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustChatStateStats.calls++;
	rustChatStateStats.ops[op] = (rustChatStateStats.ops[op] ?? 0) + 1;
	try {
		const answer = await (await unit(core)).request(op, payload);
		mark('firstAnswer');
		return answer;
	} catch (error) {
		rustChatStateStats.failures++;
		throw error;
	} finally {
		release();
	}
}
