/**
 * Page side of the shared Rust core Worker `apps` unit.
 *
 * Opens the pre-bind `apps` namespace lazily (unbound, so unbind/account switch
 * does not close it; it holds no account state) and reopens it after a Worker
 * crash or terminate. Every call holds a registry lease so idle retirement
 * never cuts an in-flight decision. There is no TypeScript fallback: a refused
 * or failed call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import type { AppsUnitProtocol } from './appsProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustAppsStats = { calls: 0, failures: 0, opens: 0 };
// Test-only read hook: installed only under browser automation (Playwright sets
// navigator.webdriver), so user sessions never expose it.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustAppsStats?: () => typeof rustAppsStats }).__openmatesRustAppsStats = () => ({ ...rustAppsStats });
}

let port: UnitPort<AppsUnitProtocol> | null = null;
let opening: Promise<UnitPort<AppsUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<AppsUnitProtocol>> {
	const opened = createUnitPort<AppsUnitProtocol>(await core.openUnit('apps', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustAppsStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<AppsUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function appsCall<K extends keyof AppsUnitProtocol & string>(
	op: K, payload: AppsUnitProtocol[K]['request'],
): Promise<AppsUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustAppsStats.calls++;
	try {
		return await (await unit(core)).request(op, payload);
	} catch (error) {
		rustAppsStats.failures++;
		throw error;
	} finally {
		release();
	}
}
