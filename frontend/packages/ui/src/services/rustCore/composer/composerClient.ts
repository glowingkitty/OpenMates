/**
 * Page side of the shared Rust core Worker `composer` unit.
 *
 * Opens the pre-bind `composer` namespace lazily (unbound: it holds no account
 * state) and reopens it after a Worker crash. Every call holds a registry lease
 * so idle retirement never cuts an in-flight call. There is no TypeScript
 * fallback: a refused or failed call rejects with its fixed code.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort, type UnitRequestOptions } from '../host/unitPort';
import type { ComposerUnitProtocol } from './composerProtocol';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustComposerStats = { calls: 0, failures: 0, opens: 0 };
// Test-only read hook: installed only under browser automation (Playwright sets
// navigator.webdriver), so user sessions never expose it.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustComposerStats?: () => typeof rustComposerStats }).__openmatesRustComposerStats = () => ({ ...rustComposerStats });
}

let port: UnitPort<ComposerUnitProtocol> | null = null;
let opening: Promise<UnitPort<ComposerUnitProtocol>> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<UnitPort<ComposerUnitProtocol>> {
	const opened = createUnitPort<ComposerUnitProtocol>(await core.openUnit('composer', { unbound: true }));
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		opened.close();
		if (port === opened) port = null;
	});
	port = opened;
	rustComposerStats.opens++;
	return opened;
}

function unit(core: SharedRustCore): Promise<UnitPort<ComposerUnitProtocol>> {
	if (port && !port.closed) return Promise.resolve(port);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

export async function composerCall<K extends keyof ComposerUnitProtocol & string>(
	op: K, payload: ComposerUnitProtocol[K]['request'], options?: UnitRequestOptions,
): Promise<ComposerUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustComposerStats.calls++;
	try {
		return await (await unit(core)).request(op, payload, options);
	} catch (error) {
		rustComposerStats.failures++;
		throw error;
	} finally {
		release();
	}
}
