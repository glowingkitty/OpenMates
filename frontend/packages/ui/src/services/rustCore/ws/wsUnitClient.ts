/**
 * Page side of the shared Rust core Worker `ws` unit.
 *
 * Opens the pre-bind `ws` namespace lazily (unbound: it holds no account state,
 * so unbind/account switch does not close it) and reopens it after a Worker
 * crash. Every call holds a registry lease so idle retirement never cuts an
 * in-flight decision. There is no TypeScript fallback: a refused or failed call
 * rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import type { WsUnitProtocol } from './wsProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustWsStats = { calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number> };
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustWsStats?: () => typeof rustWsStats }).__openmatesRustWsStats =
		() => ({ ...rustWsStats, ops: { ...rustWsStats.ops } });
}

let port: UnitPort<WsUnitProtocol> | null = null;
let opening: Promise<UnitPort<WsUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<WsUnitProtocol>> {
	const opened = createUnitPort<WsUnitProtocol>(await core.openUnit('ws', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustWsStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<WsUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function wsCall<K extends keyof WsUnitProtocol & string>(
	op: K, payload: WsUnitProtocol[K]['request'],
): Promise<WsUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustWsStats.calls++;
	rustWsStats.ops[op] = (rustWsStats.ops[op] ?? 0) + 1;
	try {
		return await (await unit(core)).request(op, payload);
	} catch (error) {
		rustWsStats.failures++;
		throw error;
	} finally {
		release();
	}
}
