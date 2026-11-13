// Opt-in shared Rust core for the web app: starts the Rust core Worker and admits
// it as an in-memory second device of the EXISTING TypeScript login.
// Only reachable from the VITE_OPENMATES_RUST_CORE build (dynamic import); the
// normal login, sync and IndexedDB storage stay TypeScript-owned.
import { artifact } from 'virtual:openmates-rust-core-package';
import { BrowserCoreWorkerHost } from '@openmates/ui/src/services/rustCore/workerHost';
import { createSessionBroker, type CoreLease, type SessionBroker } from '@openmates/ui/src/services/rustCore/host/sessionBroker';
import { validProductionBootstrap } from './productionBootstrap';
import type { ProductionBootstrap } from './productionBootstrap';
import { registerPrincipalBinder } from '@openmates/ui/src/services/rustCore/host/serverSessionRegistry';
import { startSharedRustCore } from './shared/sharedWorkerStart';
import type { LocalSavedChatSession, ProductionSavedChatSession } from '@openmates/ui/src/services/rustCore/secondDeviceSavedChatSession';
import type { SavedChatSelection } from '@openmates/ui/src/services/rustCore/selectedSavedChat';

const READY_TIMEOUT_MS = 30_000;

// Every Rust core session of this tab is a lease on the one shared Worker (one
// WASM instance); the broker admits each principal once.
let broker: SessionBroker | null = null;
function sessionBroker(): SessionBroker {
	broker ??= createSessionBroker(startSharedRustCore());
	return broker;
}

// Streamed-embed writes need a bound generation even where the saved-chat admission
// refuses (team workspace, device verification): they bind the account principal here.
registerPrincipalBinder((principal) => sessionBroker().ensureBound(principal));

/**
 * Load the shared Worker's WASM now, in parallel with page boot. Loading confers
 * nothing: no principal is bound until admission takes its first lease.
 */
export function prewarmRustCoreWorker(): void {
	if (typeof window === 'undefined' || !window.isSecureContext || !artifact) return;
	void sessionBroker().prewarm().catch(() => undefined);
}

/**
 * The Host drives a Worker; a lease port is that endpoint. Its `terminate()`
 * releases only this lease (the core unit disposes its dispatcher), never the
 * shared Worker. Events keep the port itself as their trusted target.
 */
function leaseEndpoint(lease: CoreLease): Worker {
	Object.defineProperty(lease.port, 'terminate', { value: () => lease.close() });
	return lease.port as unknown as Worker;
}

/** Lease a core unit on the shared Worker, post its bootstrap and wait for its ready frame. */
export async function createRustCoreWorker(input: {
	apiUrl: string; sessionId: string; expectedPrincipal: string; signal: AbortSignal;
}): Promise<{ host: BrowserCoreWorkerHost; close(): void }> {
	if (typeof window === 'undefined' || !window.isSecureContext || input.signal.aborted) throw new Error('unavailable');
	const bootstrap: ProductionBootstrap = { version: 1, operation: 'bootstrap_existing_key', artifact: artifact ?? '',
		apiUrl: input.apiUrl, appOrigin: window.location.origin, sessionId: input.sessionId, expectedPrincipal: input.expectedPrincipal };
	if (!validProductionBootstrap(bootstrap, window.location.origin, artifact)) throw new Error('rust_core_assets_disabled');
	const lease = await sessionBroker().lease(input.expectedPrincipal, { signal: input.signal });
	const port = lease.port;
	let host: BrowserCoreWorkerHost | null = null;
	let closed = false;
	const close = () => {
		if (closed) return;
		closed = true;
		input.signal.removeEventListener('abort', close);
		stopLost();
		if (host) host.close(); else lease.close();
	};
	// Crash or principal switch: the Host fails its pending requests like a dead Worker.
	const stopLost = lease.onLost(() => { if (host) host.close('unavailable'); });
	input.signal.addEventListener('abort', close, { once: true });
	try {
		await new Promise<void>((resolve, reject) => {
			const finish = (error?: Error) => {
				clearTimeout(timer);
				port.removeEventListener('message', receive);
				port.removeEventListener('messageerror', fail);
				stopFail();
				if (error) reject(error); else resolve();
			};
			const fail = () => finish(new Error('unavailable'));
			const stopFail = lease.onLost(fail);
			const receive = (event: MessageEvent<unknown>) => {
				const data = event.data as { version?: unknown; ready?: unknown; code?: unknown } | null;
				if (data && data.version === 1 && data.ready === true) finish();
				else if (data && data.version === 1 && data.ready === false && typeof data.code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(data.code)) finish(new Error(`worker_${data.code}`));
				else fail();
			};
			const timer = setTimeout(fail, READY_TIMEOUT_MS);
			port.addEventListener('message', receive);
			port.addEventListener('messageerror', fail);
			port.start();
			port.postMessage(bootstrap);
		});
		if (closed) throw new Error('cancelled');
		performance.mark('openmates:rust:worker-ready');
		host = new BrowserCoreWorkerHost(leaseEndpoint(lease), undefined, input.expectedPrincipal);
		return { host, close };
	} catch (error) {
		close();
		throw error;
	}
}

type RustCoreWorker = Awaited<ReturnType<typeof createRustCoreWorker>>;

/**
 * Starts the core lease (bind/open/bootstrap round trips) as soon as the
 * principal is known, in parallel with admission's profile capture, instead of
 * after it. Carries no key: admission still restores only after its own checks.
 * `take` hands it to admission (whose signal then owns it); `discard` releases
 * an untaken lease when admission failed before asking for its Worker.
 */
function earlyRustCoreWorker(input: { apiUrl: string; expectedPrincipal: string }) {
	const controller = new AbortController();
	const pending = createRustCoreWorker({ apiUrl: input.apiUrl, sessionId: crypto.randomUUID(),
		expectedPrincipal: input.expectedPrincipal, signal: controller.signal });
	// Observed by `take`'s caller; an untaken failure has nothing left to release.
	pending.catch(() => undefined);
	let taken = false;
	return {
		take(signal: AbortSignal): Promise<RustCoreWorker> {
			taken = true;
			if (signal.aborted) controller.abort();
			else signal.addEventListener('abort', () => controller.abort(), { once: true });
			return pending;
		},
		discard(): void { if (!taken) controller.abort(); }
	};
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
	const early = earlyRustCoreWorker({ apiUrl: getApiUrl(), expectedPrincipal: platform.expectedPrincipal });
	try {
		const session = await admitLocalSavedChatSession({
			expectedPrincipal: platform.expectedPrincipal, signal: input.signal, sources: platform.sources,
			currentSelection: () => platform.selection(input.currentSelection()), lifecycle: browserProfileLifecycle,
			page: window, createChannel: (name) => new BroadcastChannel(name),
			createWorker: (signal) => early.take(signal)
		});
		session.signal.addEventListener('abort', () => platform.close(), { once: true });
		return session;
	} catch (error) {
		early.discard();
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
