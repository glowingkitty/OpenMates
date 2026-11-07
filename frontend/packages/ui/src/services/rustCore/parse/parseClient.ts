/**
 * Page side of the shared Rust core Worker `parse` unit.
 *
 * Opens the pre-bind `parse` namespace lazily (unbound, so unbind/account switch
 * does not close it; it holds no account state) and reopens it after a Worker
 * crash or terminate. Every call holds a registry lease so idle retirement
 * never cuts an in-flight decision. There is no TypeScript fallback: a refused
 * or failed call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import type { ParseUnitProtocol } from './parseProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustParseStats = { calls: 0, failures: 0, opens: 0 };
// Test-only read hook: installed only under browser automation (Playwright sets
// navigator.webdriver), so user sessions never expose it.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustParseStats?: () => typeof rustParseStats }).__openmatesRustParseStats = () => ({ ...rustParseStats });
}

let port: UnitPort<ParseUnitProtocol> | null = null;
let opening: Promise<UnitPort<ParseUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<ParseUnitProtocol>> {
	const opened = createUnitPort<ParseUnitProtocol>(await core.openUnit('parse', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustParseStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<ParseUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function parseCall<K extends keyof ParseUnitProtocol & string>(
	op: K, payload: ParseUnitProtocol[K]['request'],
): Promise<ParseUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustParseStats.calls++;
	try {
		return await (await unit(core)).request(op, payload);
	} catch (error) {
		rustParseStats.failures++;
		throw error;
	} finally {
		release();
	}
}
