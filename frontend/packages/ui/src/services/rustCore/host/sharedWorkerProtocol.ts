/**
 * Control protocol (envelope v1) of the single shared Rust core Worker.
 *
 * The page talks to the Worker over the Worker's own message channel with four
 * control requests: `bind` (admit one principal, start a new generation),
 * `unbind` (end that generation and close every port it owns), `open`
 * (attach a MessagePort to one namespace's unit) and `prewarm` (load the
 * realm's single WASM binding early; confers no authority). Every request is answered
 * with `ready` or `refused` carrying a fixed code. Each namespace keeps its own
 * unit protocol on its own port; this router never inspects unit traffic.
 *
 * The router itself is environment-free (no `self`, no WASM import) so it can be
 * unit tested; the web_app Worker entry wires it to `loadBinding()`.
 */

export const SHARED_WORKER_PROTOCOL_VERSION = 1 as const;

/** Static namespace allowlist. Anything else is refused as `unknown_namespace`. */
export const SHARED_NAMESPACES = ['core', 'crypto', 'auth', 'embedData', 'embedWrite', 'chatState', 'ws', 'apps', 'search'] as const;
export type SharedNamespace = (typeof SHARED_NAMESPACES)[number];

/** Namespaces that may open before any principal is bound (login, key preparation, guest app skills, stateless embed field decryption, signed-out public chat search). */
export const PRE_BIND_NAMESPACES: ReadonlySet<SharedNamespace> = new Set<SharedNamespace>(['crypto', 'auth', 'apps', 'embedData', 'search']);

/** Maximum transferred ports per namespace: ports[0] is the unit port, core may add the recovery port as ports[1]. */
export const NAMESPACE_MAX_PORTS: Readonly<Record<SharedNamespace, number>> = Object.freeze({
	core: 2, crypto: 1, auth: 1, embedData: 1, embedWrite: 1, chatState: 1, ws: 1, apps: 1, search: 1
});

export const SHARED_REFUSAL_CODES = [
	'bad_envelope',
	'unsupported_version',
	'unknown_namespace',
	'bad_ports',
	'not_bound',
	'already_bound',
	'stale_generation',
	'unit_unavailable',
	'binding_unavailable',
	'install_failed'
] as const;
export type SharedRefusalCode = (typeof SHARED_REFUSAL_CODES)[number];

export type SharedControlRequest =
	| { v: 1; id: number; type: 'bind'; principal: string }
	| { v: 1; id: number; type: 'unbind'; generation: number }
	| { v: 1; id: number; type: 'open'; ns: SharedNamespace; generation: number | null }
	| { v: 1; id: number; type: 'prewarm' };

export type SharedControlReply =
	| { v: 1; id: number | null; type: 'ready'; generation: number | null }
	| { v: 1; id: number | null; type: 'refused'; code: SharedRefusalCode };

/** What an installer receives when its namespace port opens. */
export interface UnitInstallContext {
	/** The one generated WASM binding of this Worker realm (loaded once). */
	binding: unknown;
	/** ports[0] is the unit port; extra ports keep their documented positions. */
	ports: readonly MessagePort[];
	/** Generation the port belongs to, null for pre-bind namespaces opened unbound. */
	generation: number | null;
	/** Principal admitted by `bind` for that generation, null when opened unbound. */
	principal: string | null;
	/** Aborted when the generation is unbound; the router also closes the ports. */
	signal: AbortSignal;
}
/** Installs one unit on its port. May return a dispose hook run on unbind. */
export type UnitInstaller = (context: UnitInstallContext) => void | (() => void) | Promise<void | (() => void)>;
export type UnitInstallers = Readonly<Partial<Record<SharedNamespace, UnitInstaller>>>;

const PRINCIPAL = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;

export function isSharedNamespace(value: unknown): value is SharedNamespace {
	return typeof value === 'string' && (SHARED_NAMESPACES as readonly string[]).includes(value);
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && Object.getPrototypeOf(value) === Object.prototype;
}
function isRequestId(value: unknown): value is number {
	return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function isGeneration(value: unknown): value is number {
	return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

/** Exactly one of `request` or `refusal` is set (shape chosen to narrow without strictNullChecks). */
type Parsed = { request: SharedControlRequest; refusal: null } | { request: null; refusal: { id: number | null; code: SharedRefusalCode } };
const refused = (id: number | null, code: SharedRefusalCode): Parsed => ({ request: null, refusal: { id, code } });
const accepted = (request: SharedControlRequest): Parsed => ({ request, refusal: null });
/** A positive generation, null, or `false` when the value is neither. */
function generationOrNull(value: unknown): number | null | false {
	if (value === null) return null;
	return isGeneration(value) ? (value as number) : false;
}

/** Strictly parses one control request; unknown keys and wrong types are refused. */
export function parseSharedControlRequest(value: unknown): Parsed {
	if (!isPlainRecord(value)) return refused(null, 'bad_envelope');
	if (!isRequestId(value.id)) return refused(null, 'bad_envelope');
	const id = value.id as number;
	if (value.v !== SHARED_WORKER_PROTOCOL_VERSION) return refused(id, 'unsupported_version');
	const keys = Object.keys(value).sort().join(',');
	if (value.type === 'bind') {
		if (keys !== 'id,principal,type,v' || typeof value.principal !== 'string' || !PRINCIPAL.test(value.principal)) {
			return refused(id, 'bad_envelope');
		}
		return accepted({ v: 1, id, type: 'bind', principal: value.principal as string });
	}
	if (value.type === 'unbind') {
		const generation = generationOrNull(value.generation);
		if (keys !== 'generation,id,type,v' || typeof generation !== 'number') return refused(id, 'bad_envelope');
		return accepted({ v: 1, id, type: 'unbind', generation });
	}
	if (value.type === 'open') {
		const generation = generationOrNull(value.generation);
		if (keys !== 'generation,id,ns,type,v' || generation === false) return refused(id, 'bad_envelope');
		if (!isSharedNamespace(value.ns)) return refused(id, 'unknown_namespace');
		return accepted({ v: 1, id, type: 'open', ns: value.ns as SharedNamespace, generation });
	}
	if (value.type === 'prewarm') {
		if (keys !== 'id,type,v') return refused(id, 'bad_envelope');
		return accepted({ v: 1, id, type: 'prewarm' });
	}
	return refused(id, 'bad_envelope');
}

/** Validates a reply on the page side; anything malformed is reported as null. */
export function parseSharedControlReply(value: unknown): SharedControlReply | null {
	if (!isPlainRecord(value) || value.v !== SHARED_WORKER_PROTOCOL_VERSION) return null;
	if (!(value.id === null || isRequestId(value.id))) return null;
	const id = value.id as number | null;
	const generation = generationOrNull(value.generation);
	if (value.type === 'ready' && generation !== false) return { v: 1, id, type: 'ready', generation };
	if (value.type === 'refused' && (SHARED_REFUSAL_CODES as readonly unknown[]).includes(value.code)) {
		return { v: 1, id, type: 'refused', code: value.code as SharedRefusalCode };
	}
	return null;
}

export interface SharedWorkerRouterDeps {
	installers: UnitInstallers;
	/** The realm's single memoized binding loader. Called at most once per router. */
	loadBinding: () => Promise<unknown>;
	reply: (reply: SharedControlReply) => void;
}

export interface SharedWorkerRouter {
	handle(data: unknown, ports: readonly MessagePort[]): Promise<void>;
	/** Current bound generation, null when unbound. */
	readonly generation: number | null;
}

interface OpenUnit { ports: readonly MessagePort[]; controller: AbortController; dispose: (() => void) | null }

/** Worker-side router. One instance per Worker realm. */
export function createSharedWorkerRouter(deps: SharedWorkerRouterDeps): SharedWorkerRouter {
	let generation: number | null = null;
	let principal: string | null = null;
	let nextGeneration = 1;
	let binding: Promise<unknown> | null = null;
	const bound: OpenUnit[] = [];

	function refuse(id: number | null, code: SharedRefusalCode, ports: readonly MessagePort[]): void {
		for (const port of ports) port.close();
		deps.reply({ v: 1, id, type: 'refused', code });
	}
	function closeBound(): void {
		for (const unit of bound.splice(0)) {
			unit.controller.abort();
			unit.dispose?.();
			for (const port of unit.ports) port.close();
		}
	}

	async function open(request: Extract<SharedControlRequest, { type: 'open' }>, ports: readonly MessagePort[]): Promise<void> {
		const { id, ns } = request;
		if (ports.length < 1 || ports.length > NAMESPACE_MAX_PORTS[ns]) return refuse(id, 'bad_ports', ports);
		const preBind = PRE_BIND_NAMESPACES.has(ns);
		if (request.generation === null) {
			if (!preBind) return refuse(id, 'not_bound', ports);
		} else if (request.generation !== generation) {
			return refuse(id, generation === null ? 'not_bound' : 'stale_generation', ports);
		}
		const installer = deps.installers[ns];
		if (!installer) return refuse(id, 'unit_unavailable', ports);
		binding ??= deps.loadBinding();
		let loaded: unknown;
		try {
			loaded = await binding;
		} catch {
			return refuse(id, 'binding_unavailable', ports);
		}
		// The generation may have been unbound while the binding loaded.
		if (request.generation !== null && request.generation !== generation) return refuse(id, 'stale_generation', ports);
		const controller = new AbortController();
		let dispose: (() => void) | null;
		try {
			const installed = await installer({ binding: loaded, ports, generation: request.generation,
				principal: request.generation === null ? null : principal, signal: controller.signal });
			dispose = typeof installed === 'function' ? installed : null;
		} catch {
			controller.abort();
			return refuse(id, 'install_failed', ports);
		}
		if (request.generation !== null) {
			if (request.generation !== generation) {
				controller.abort();
				dispose?.();
				return refuse(id, 'stale_generation', ports);
			}
			bound.push({ ports, controller, dispose });
		}
		deps.reply({ v: 1, id, type: 'ready', generation: request.generation });
	}

	return {
		get generation() { return generation; },
		async handle(data, ports) {
			const parsed = parseSharedControlRequest(data);
			const { request, refusal } = parsed;
			if (refusal) return refuse(refusal.id, refusal.code, ports);
			if (!request) return refuse(null, 'bad_envelope', ports);
			if (request.type === 'open') return open(request, ports);
			if (ports.length > 0) return refuse(request.id, 'bad_ports', ports);
			if (request.type === 'prewarm') {
				binding ??= deps.loadBinding();
				try {
					await binding;
				} catch {
					return refuse(request.id, 'binding_unavailable', ports);
				}
				return deps.reply({ v: 1, id: request.id, type: 'ready', generation: null });
			}
			if (request.type === 'bind') {
				if (generation !== null) return refuse(request.id, 'already_bound', ports);
				generation = nextGeneration++;
				principal = request.principal;
				return deps.reply({ v: 1, id: request.id, type: 'ready', generation });
			}
			if (generation === null) return refuse(request.id, 'not_bound', ports);
			if (request.generation !== generation) return refuse(request.id, 'stale_generation', ports);
			closeBound();
			generation = null;
			principal = null;
			deps.reply({ v: 1, id: request.id, type: 'ready', generation: null });
		}
	};
}
