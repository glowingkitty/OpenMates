/**
 * Page side of the shared Rust core Worker `persist` unit.
 *
 * Opens the pre-bind `persist` namespace lazily (unbound: it holds no account
 * state, so unbind/account switch does not close it) and reopens it after a
 * Worker crash. Every call holds a registry lease so idle retirement never cuts
 * an in-flight decision. There is no TypeScript fallback: a refused or failed
 * call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import type { PersistUnitProtocol } from './persistProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustPersistStats = { calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number> };
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustPersistStats?: () => typeof rustPersistStats }).__openmatesRustPersistStats =
		() => ({ ...rustPersistStats, ops: { ...rustPersistStats.ops } });
}

let port: UnitPort<PersistUnitProtocol> | null = null;
let opening: Promise<UnitPort<PersistUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<PersistUnitProtocol>> {
	const opened = createUnitPort<PersistUnitProtocol>(await core.openUnit('persist', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustPersistStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<PersistUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function persistCall<K extends keyof PersistUnitProtocol & string>(
	op: K, payload: PersistUnitProtocol[K]['request'],
): Promise<PersistUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustPersistStats.calls++;
	rustPersistStats.ops[op] = (rustPersistStats.ops[op] ?? 0) + 1;
	try {
		return await (await unit(core)).request(op, payload);
	} catch (error) {
		rustPersistStats.failures++;
		throw error;
	} finally {
		release();
	}
}
