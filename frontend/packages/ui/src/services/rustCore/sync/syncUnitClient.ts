/**
 * Page side of the shared Rust core Worker `sync` unit.
 *
 * Opens the pre-bind `sync` namespace lazily (unbound: it holds no account
 * state, so unbind/account switch does not close it) and reopens it after a
 * Worker crash. Every call holds a registry lease so idle retirement never cuts
 * an in-flight decision. There is no TypeScript fallback: a refused or failed
 * call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import type { SyncUnitProtocol } from './syncProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustSyncStats = { calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number> };
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustSyncStats?: () => typeof rustSyncStats }).__openmatesRustSyncStats =
		() => ({ ...rustSyncStats, ops: { ...rustSyncStats.ops } });
}

let port: UnitPort<SyncUnitProtocol> | null = null;
let opening: Promise<UnitPort<SyncUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<SyncUnitProtocol>> {
	const opened = createUnitPort<SyncUnitProtocol>(await core.openUnit('sync', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustSyncStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<SyncUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function syncCall<K extends keyof SyncUnitProtocol & string>(
	op: K, payload: SyncUnitProtocol[K]['request'],
): Promise<SyncUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustSyncStats.calls++;
	rustSyncStats.ops[op] = (rustSyncStats.ops[op] ?? 0) + 1;
	try {
		return await (await unit(core)).request(op, payload);
	} catch (error) {
		rustSyncStats.failures++;
		throw error;
	} finally {
		release();
	}
}
