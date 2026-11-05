// Opt-in shared Rust core for the web app: starts the Rust core Worker and admits
// it as an in-memory second device of the EXISTING TypeScript login.
// Only reachable from the VITE_OPENMATES_RUST_CORE build (dynamic import); the
// normal login, sync and IndexedDB storage stay TypeScript-owned.
import { artifact } from 'virtual:openmates-rust-core-package';
import workerUrl from './production.worker.ts?worker&url';
import { BrowserCoreWorkerHost } from '@openmates/ui/src/services/rustCore/workerHost';
import { validProductionBootstrap } from './productionBootstrap';
import type { ProductionBootstrap } from './productionBootstrap';
import type { LocalSavedChatSession, ProductionSavedChatSession } from '@openmates/ui/src/services/rustCore/secondDeviceSavedChatSession';
import type { SavedChatSelection } from '@openmates/ui/src/services/rustCore/selectedSavedChat';

const READY_TIMEOUT_MS = 30_000;

let prewarmed: Worker | null = null;
function spawnRustCoreWorker(): Worker {
	return new Worker(new URL(workerUrl, window.location.href), { type: 'module', name: 'openmates-rust-core' });
}

/**
 * Start the Worker early so its module and WASM load in parallel with page boot.
 * Loading confers nothing: the Worker stays inert until admission posts its
 * bootstrap (principal/session), exactly as for a freshly spawned Worker.
 */
export function prewarmRustCoreWorker(): void {
	if (prewarmed || typeof window === 'undefined' || !window.isSecureContext || !artifact) return;
	prewarmed = spawnRustCoreWorker();
}

/** Terminate an unused pre-warmed Worker (page teardown). */
export function disposePrewarmedRustCoreWorker(): void {
	prewarmed?.terminate();
	prewarmed = null;
}

/** Start the Worker, load the WASM core and wait for its ready frame. */
export async function createRustCoreWorker(input: {
	apiUrl: string; sessionId: string; expectedPrincipal: string; signal: AbortSignal;
}): Promise<{ host: BrowserCoreWorkerHost; close(): void }> {
	if (typeof window === 'undefined' || !window.isSecureContext || input.signal.aborted) throw new Error('unavailable');
	const bootstrap: ProductionBootstrap = { version: 1, operation: 'bootstrap_existing_key', artifact: artifact ?? '',
		apiUrl: input.apiUrl, appOrigin: window.location.origin, sessionId: input.sessionId, expectedPrincipal: input.expectedPrincipal };
	if (!validProductionBootstrap(bootstrap, window.location.origin, artifact)) throw new Error('rust_core_assets_disabled');
	// A pre-warmed Worker is single-use; later admissions spawn a fresh one.
	const worker = prewarmed ?? spawnRustCoreWorker();
	prewarmed = null;
	let host: BrowserCoreWorkerHost | null = null;
	let closed = false;
	const close = () => {
		if (closed) return;
		closed = true;
		input.signal.removeEventListener('abort', close);
		if (host) host.close(); else worker.terminate();
	};
	input.signal.addEventListener('abort', close, { once: true });
	try {
		await new Promise<void>((resolve, reject) => {
			const finish = (error?: Error) => {
				clearTimeout(timer);
				worker.removeEventListener('message', receive);
				worker.removeEventListener('error', fail);
				worker.removeEventListener('messageerror', fail);
				if (error) reject(error); else resolve();
			};
			const fail = () => finish(new Error('unavailable'));
			const receive = (event: MessageEvent<unknown>) => {
				const data = event.data as { version?: unknown; ready?: unknown; code?: unknown } | null;
				if (data && data.version === 1 && data.ready === true) finish();
				else if (data && data.version === 1 && data.ready === false && typeof data.code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(data.code)) finish(new Error(`worker_${data.code}`));
				else fail();
			};
			const timer = setTimeout(fail, READY_TIMEOUT_MS);
			worker.addEventListener('message', receive);
			worker.addEventListener('error', fail);
			worker.addEventListener('messageerror', fail);
			worker.postMessage(bootstrap);
		});
		if (closed) throw new Error('cancelled');
		performance.mark('openmates:rust:worker-ready');
		host = new BrowserCoreWorkerHost(worker, undefined, input.expectedPrincipal);
		return { host, close };
	} catch (error) {
		close();
		throw error;
	}
}

type SelectionInput = () => Omit<SavedChatSelection, 'ownerId' | 'teamId' | 'workspaceEpoch'>;

function importAdmissionModules() {
	return Promise.all([
		import('@openmates/ui/src/services/rustCore/productionSavedChatPlatform'),
		import('@openmates/ui/src/config/api'),
		import('@openmates/ui/src/services/rustCore/platformLifecycle'),
		import('@openmates/ui/src/services/rustCore/secondDeviceSavedChatSession')
	]);
}
let admissionModules: ReturnType<typeof importAdmissionModules> | null = null;
/** Memoized; a failed load is retried by the next caller. Code only, no authority. */
function loadAdmissionModules(): ReturnType<typeof importAdmissionModules> {
	if (admissionModules) return admissionModules;
	const loading = importAdmissionModules();
	admissionModules = loading;
	loading.catch(() => { if (admissionModules === loading) admissionModules = null; });
	return loading;
}

/**
 * Fetch the admission code at page setup, in parallel with page boot, so local
 * admission does not wait on its chunk waterfall once the TS session is known.
 */
export function preloadRustAdmissionModules(): void {
	void loadAdmissionModules().catch(() => undefined);
}

/**
 * Local-only Rust admission on the TS-optimistic local state (existing key and
 * profile), BEFORE the TS server check finishes, like TS renders cached content
 * before its own check. Cached reads only; `createRustSecondDeviceSession({ local })`
 * then runs the normal server check on the same Worker.
 */
export async function createRustLocalSession(input: {
	signal: AbortSignal; currentSelection: SelectionInput;
}): Promise<LocalSavedChatSession> {
	const [{ createBrowserSavedChatPlatform }, { getApiUrl }, { browserProfileLifecycle }, { admitLocalSavedChatSession }] = await loadAdmissionModules();
	performance.mark('openmates:rust:admission-modules-ready');
	const platform = await createBrowserSavedChatPlatform(input.signal, 'local_first');
	performance.mark('openmates:rust:local-platform-ready');
	try {
		const session = await admitLocalSavedChatSession({
			expectedPrincipal: platform.expectedPrincipal, signal: input.signal, sources: platform.sources,
			currentSelection: () => platform.selection(input.currentSelection()), lifecycle: browserProfileLifecycle,
			page: window, createChannel: (name) => new BroadcastChannel(name),
			createWorker: (signal) => createRustCoreWorker({ apiUrl: getApiUrl(), sessionId: crypto.randomUUID(),
				expectedPrincipal: platform.expectedPrincipal, signal })
		});
		session.signal.addEventListener('abort', () => platform.close(), { once: true });
		return session;
	} catch (error) {
		platform.close();
		throw error;
	}
}

/**
 * Admit Rust on the current TS session/key (server-checked) and return the
 * selected-chat session. With `local`, the check runs on that local session's
 * Worker (handover); a failure tears the local session down too.
 */
export async function createRustSecondDeviceSession(input: {
	signal: AbortSignal;
	currentSelection: SelectionInput;
	local?: LocalSavedChatSession | null;
}): Promise<ProductionSavedChatSession> {
	const [{ createBrowserSavedChatPlatform }, { getApiUrl }, { browserProfileLifecycle }, { admitSecondDeviceSavedChatSession }] = await loadAdmissionModules();
	let platform: Awaited<ReturnType<typeof createBrowserSavedChatPlatform>>;
	try {
		platform = await createBrowserSavedChatPlatform(input.signal);
	} catch (error) {
		input.local?.close();
		throw error;
	}
	performance.mark('openmates:rust:platform-ready');
	try {
		const admission = {
			expectedPrincipal: platform.expectedPrincipal, signal: input.signal, sources: platform.sources,
			currentSelection: () => platform.selection(input.currentSelection()), lifecycle: browserProfileLifecycle,
			page: window, createChannel: (name: string) => new BroadcastChannel(name)
		};
		const local = input.local && !input.local.signal.aborted ? input.local : null;
		const session = local ? await local.upgrade(admission) : await admitSecondDeviceSavedChatSession({ ...admission,
			// A fresh per-page session id makes Rust a separate connection (second device):
			// the server keys WebSockets by device+session, so reusing the TS tab's id
			// would replace the TS socket and strand its pending sends.
			createWorker: (signal) => createRustCoreWorker({ apiUrl: getApiUrl(), sessionId: crypto.randomUUID(),
				expectedPrincipal: platform.expectedPrincipal, signal })
		});
		session.signal.addEventListener('abort', () => platform.close(), { once: true });
		return session;
	} catch (error) {
		platform.close();
		throw error;
	}
}
