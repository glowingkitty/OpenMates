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
export const rustChatStateStats = { calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number> };
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustChatStateStats?: () => typeof rustChatStateStats }).__openmatesRustChatStateStats =
		() => ({ ...rustChatStateStats, ops: { ...rustChatStateStats.ops } });
}

let port: UnitPort<ChatStateUnitProtocol> | null = null;
let opening: Promise<UnitPort<ChatStateUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<ChatStateUnitProtocol>> {
	const opened = createUnitPort<ChatStateUnitProtocol>(await core.openUnit('chatState', { unbound: true }));
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

export async function chatStateCall<K extends keyof ChatStateUnitProtocol & string>(
	op: K, payload: ChatStateUnitProtocol[K]['request'],
): Promise<ChatStateUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustChatStateStats.calls++;
	rustChatStateStats.ops[op] = (rustChatStateStats.ops[op] ?? 0) + 1;
	try {
		return await (await unit(core)).request(op, payload);
	} catch (error) {
		rustChatStateStats.failures++;
		throw error;
	} finally {
		release();
	}
}
