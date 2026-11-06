/**
 * Page side of the shared Rust core Worker `transfer` unit.
 *
 * Opens the pre-bind `transfer` namespace lazily (unbound: it holds no account
 * state) and reopens it after a Worker crash. Every call holds a registry lease
 * so idle retirement never cuts an in-flight parse. There is no TypeScript
 * fallback: a refused or failed call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort, type UnitRequestOptions } from '../host/unitPort';
import type { TransferUnitProtocol } from './transferProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustTransferStats = { calls: 0, failures: 0, opens: 0 };
// Test-only read hook: installed only under browser automation (Playwright sets
// navigator.webdriver), so user sessions never expose it.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustTransferStats?: () => typeof rustTransferStats }).__openmatesRustTransferStats = () => ({ ...rustTransferStats });
}

let port: UnitPort<TransferUnitProtocol> | null = null;
let opening: Promise<UnitPort<TransferUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<TransferUnitProtocol>> {
	const opened = createUnitPort<TransferUnitProtocol>(await core.openUnit('transfer', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustTransferStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<TransferUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function transferCall<K extends keyof TransferUnitProtocol & string>(
	op: K, payload: TransferUnitProtocol[K]['request'], options?: UnitRequestOptions,
): Promise<TransferUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustTransferStats.calls++;
	try {
		return await (await unit(core)).request(op, payload, options);
	} catch (error) {
		rustTransferStats.failures++;
		throw error;
	} finally {
		release();
	}
}
