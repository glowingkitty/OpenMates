/**
 * Page side of the shared Rust core Worker `sendPrep` unit.
 *
 * Opens the pre-bind `sendPrep` namespace lazily (unbound: it holds no account
 * state) and reopens it after a Worker crash. Every call holds a registry lease
 * so idle retirement never cuts an in-flight decision. There is no TypeScript
 * fallback: a refused or failed call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort, type UnitRequestOptions } from '../host/unitPort';
import type { SendPrepUnitProtocol } from './sendPrepProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustSendPrepStats = { calls: 0, failures: 0, opens: 0 };
// Test-only read hook: installed only under browser automation (Playwright sets
// navigator.webdriver), so user sessions never expose it.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustSendPrepStats?: () => typeof rustSendPrepStats }).__openmatesRustSendPrepStats = () => ({ ...rustSendPrepStats });
}

let port: UnitPort<SendPrepUnitProtocol> | null = null;
let opening: Promise<UnitPort<SendPrepUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<SendPrepUnitProtocol>> {
	const opened = createUnitPort<SendPrepUnitProtocol>(await core.openUnit('sendPrep', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustSendPrepStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<SendPrepUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function sendPrepCall<K extends keyof SendPrepUnitProtocol & string>(
	op: K, payload: SendPrepUnitProtocol[K]['request'], options?: UnitRequestOptions,
): Promise<SendPrepUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustSendPrepStats.calls++;
	try {
		return await (await unit(core)).request(op, payload, options);
	} catch (error) {
		rustSendPrepStats.failures++;
		throw error;
	} finally {
		release();
	}
}
