/**
 * Page side of the shared Rust core Worker `settings` unit.
 *
 * Opens the pre-bind `settings` namespace lazily (unbound, so unbind/account switch
 * does not close it; it holds no account state) and reopens it after a Worker
 * crash or terminate. Every call holds a registry lease so idle retirement
 * never cuts an in-flight decision. There is no TypeScript fallback: a refused
 * or failed call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import type { SettingsUnitProtocol } from './settingsProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustSettingsStats = { calls: 0, failures: 0, opens: 0 };
// Test-only read hook: installed only under browser automation (Playwright sets
// navigator.webdriver), so user sessions never expose it.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustSettingsStats?: () => typeof rustSettingsStats }).__openmatesRustSettingsStats = () => ({ ...rustSettingsStats });
}

let port: UnitPort<SettingsUnitProtocol> | null = null;
let opening: Promise<UnitPort<SettingsUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<SettingsUnitProtocol>> {
	const opened = createUnitPort<SettingsUnitProtocol>(await core.openUnit('settings', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustSettingsStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<SettingsUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function settingsCall<K extends keyof SettingsUnitProtocol & string>(
	op: K, payload: SettingsUnitProtocol[K]['request'],
): Promise<SettingsUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustSettingsStats.calls++;
	try {
		return await (await unit(core)).request(op, payload);
	} catch (error) {
		rustSettingsStats.failures++;
		throw error;
	} finally {
		release();
	}
}
