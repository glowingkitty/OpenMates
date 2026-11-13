/**
 * Page client of the shared Worker's `embedData` unit (VITE_OPENMATES_RUST_CORE
 * builds only; the flag-off build folds every caller's gate to the legacy path
 * and drops this module).
 *
 * `rustEmbedData()` is available exactly when the Rust crypto unit client is
 * (same registration, same measurement opt-out `openmates_rust_core_crypto`):
 * embed field decryption is part of the Rust crypto arm. Calls made in the
 * same task are coalesced into one `openFields` request. The port opens lazily
 * (pre-bind, outside any generation); a Worker crash or realm retirement drops
 * it and the next call reopens. In-flight calls hold the realm so idle
 * retirement never cuts them off. Failures reject; there is no TS fallback.
 *
 * `openStoredEmbedContent` / `openedEmbedField` are the embedStore read hooks:
 * each call site is a `VITE_OPENMATES_RUST_CORE === "1" ? hook : TS call`
 * ternary, so default builds fold to the original TS call and drop this module.
 * The TS callback runs only when the Rust crypto arm is inactive (measurement
 * opt-out or no registration), which is the documented TS arm, not a fallback.
 */
import { rustWebCrypto } from '../crypto/webCryptoClient';
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import {
	EMBED_DATA_MAX_ITEMS,
	EMBED_UNIT_CLOSE,
	type EmbedDataProtocol,
	type EmbedFieldsRequest,
	type EmbedFieldsResult,
	type OpenedEmbedFields
} from './embedDataProtocol';
import type { EmbedEventAdmissionRequest } from './readOps';
import type { EmbedSenderDecisions, EmbedSenderOp } from '../../embedSenderPolicy';

export class RustEmbedDataError extends Error {
	constructor(readonly code: string) {
		super(code);
		this.name = 'RustEmbedDataError';
	}
}

interface OpenedUnit { raw: MessagePort; unit: UnitPort<EmbedDataProtocol> }
interface Queued { item: EmbedFieldsRequest; resolve(fields: OpenedEmbedFields): void; reject(error: Error): void }

export class EmbedDataClient {
	private port: Promise<OpenedUnit> | null = null;
	private queue: Queued[] = [];
	private scheduled = false;
	private stopCrashWatch: (() => void) | null = null;
	readonly stats = { requests: 0, rows: 0, failures: 0, toonDecodes: 0, streamedWrites: 0, admissions: 0, senderDecisions: 0 };

	constructor(private readonly core: SharedRustCore) {}

	/** Opens `encrypted_*` fields of one stored embed row with its embed key. */
	openFields(key: Uint8Array, row: { encrypted_content?: unknown; encrypted_type?: unknown; encrypted_text_preview?: unknown }): Promise<OpenedEmbedFields> {
		const text = (value: unknown) => (typeof value === 'string' ? value : null);
		const item: EmbedFieldsRequest = {
			key: new Uint8Array(key),
			encrypted_content: text(row.encrypted_content),
			encrypted_type: text(row.encrypted_type),
			encrypted_text_preview: text(row.encrypted_text_preview)
		};
		return new Promise((resolve, reject) => {
			this.queue.push({ item, resolve, reject });
			if (this.scheduled) return;
			this.scheduled = true;
			queueMicrotask(() => {
				this.scheduled = false;
				while (this.queue.length) void this.flush(this.queue.splice(0, EMBED_DATA_MAX_ITEMS));
			});
		});
	}

	/** Rust replay of one legacy version patch; rejects with `version_patch_refused` where Rust refuses it. */
	async applyVersionPatch(content: string, patch: string): Promise<string> {
		const release = this.core.hold();
		try {
			const { unit } = await this.open();
			const [result] = await unit.request('applyVersionPatches', { items: [{ content, patch }] });
			if (!result) throw new RustEmbedDataError('embed_data_bad_reply');
			if ('code' in result) throw new RustEmbedDataError(result.code);
			return result.content;
		} catch (error) {
			this.stats.failures += 1;
			throw error;
		} finally {
			release();
		}
	}

	/** Rust admission decision for one inbound embed event (`embed_read::admission`). */
	async admitEmbedEvent(request: EmbedEventAdmissionRequest): Promise<boolean> {
		const release = this.core.hold();
		this.stats.admissions += 1;
		try {
			const { unit } = await this.open();
			const decision = await unit.request('admitEmbedEvent', request);
			if (typeof decision !== 'boolean') throw new RustEmbedDataError('embed_data_bad_reply');
			return decision;
		} catch (error) {
			this.stats.failures += 1;
			throw error;
		} finally {
			release();
		}
	}

	/** One canonical embed sender decision in Rust (`embed_read::run_json`); the parsed answer document. */
	async decideSender(op: string, input: unknown): Promise<unknown> {
		const release = this.core.hold();
		this.stats.senderDecisions += 1;
		try {
			const { unit } = await this.open();
			const answer = await unit.request('decideSender', { op, input: JSON.stringify(input) });
			if (typeof answer !== 'string') throw new RustEmbedDataError('embed_data_bad_reply');
			return JSON.parse(answer) as unknown;
		} catch (error) {
			this.stats.failures += 1;
			throw error;
		} finally {
			release();
		}
	}

	/** Rust TOON decode of one text: its JSON text, or null when TOON refused it. */
	async decodeToon(text: string): Promise<string | null> {
		const release = this.core.hold();
		this.stats.toonDecodes += 1;
		try {
			const { unit } = await this.open();
			const [decoded] = await unit.request('decodeToon', { texts: [text] });
			if (decoded !== null && typeof decoded !== 'string') throw new RustEmbedDataError('embed_data_bad_reply');
			return decoded;
		} catch (error) {
			this.stats.failures += 1;
			throw error;
		} finally {
			release();
		}
	}

	close(): void {
		const opened = this.port;
		this.port = null;
		this.stopCrashWatch?.();
		this.stopCrashWatch = null;
		void opened?.then(({ unit, raw }) => {
			if (unit.closed) return;
			raw.postMessage(EMBED_UNIT_CLOSE);
			unit.close();
		}, () => undefined);
	}

	private open(): Promise<OpenedUnit> {
		if (this.port) return this.port;
		const opening = this.core.openUnit('embedData', { unbound: true })
			.then((raw) => ({ raw, unit: createUnitPort<EmbedDataProtocol>(raw) }));
		this.port = opening;
		this.stopCrashWatch ??= this.core.onCrash(() => {
			const dead = this.port;
			this.port = null;
			void dead?.then(({ unit }) => unit.close(), () => undefined);
		});
		opening.catch(() => { if (this.port === opening) this.port = null; });
		return opening;
	}

	private async flush(batch: Queued[]): Promise<void> {
		const release = this.core.hold();
		this.stats.requests += 1;
		this.stats.rows += batch.length;
		let results: EmbedFieldsResult[];
		try {
			const { unit } = await this.open();
			results = await unit.request('openFields', { items: batch.map((queued) => queued.item) });
			if (!Array.isArray(results) || results.length !== batch.length) throw new RustEmbedDataError('embed_data_bad_reply');
		} catch (error) {
			this.stats.failures += 1;
			const failure = error instanceof Error ? error : new RustEmbedDataError('embed_data_failed');
			for (const queued of batch) queued.reject(failure);
			return;
		} finally {
			release();
			for (const queued of batch) queued.item.key.fill(0);
		}
		results.forEach((result, index) => {
			if ('fields' in result) batch[index].resolve(result.fields);
			else batch[index].reject(new RustEmbedDataError(result.code));
		});
	}
}

type StoredEmbedRow = { encrypted_content?: unknown; encrypted_type?: unknown; encrypted_text_preview?: unknown };

/** Fields Rust opened together with a row's content; read by the type/preview branches (lazy: no module side effect). */
let openedRows: WeakMap<object, OpenedEmbedFields> | null = null;

/**
 * Marker the embedStore read sites receive instead of an embed key when the
 * Worker resolved the key and opened the row itself (no key bytes; never used
 * as a key). `openStoredEmbedContent` / `openedEmbedField` then read the
 * remembered fields.
 */
export const WORKER_RESOLVED_EMBED_KEY: Uint8Array = new Uint8Array(0);

/** Remembers the fields the Worker opened for `row` (read by the hooks below). */
export function rememberOpenedRow(row: object, fields: OpenedEmbedFields): void {
	(openedRows ??= new WeakMap()).set(row, fields);
}

/**
 * Opens a stored row's content (and, in the same Rust call, its type and preview).
 * Returns the content, or null when it did not open (the caller marks the row
 * failed, as for the TS decrypt). A Rust rejection propagates to the caller.
 */
export async function openStoredEmbedContent(key: Uint8Array, row: StoredEmbedRow,
	typescript: () => Promise<string | null>): Promise<string | null> {
	// Key resolved in the Worker (embedKeyClient.ts): the row was already opened there.
	if (key === WORKER_RESOLVED_EMBED_KEY) return openedRows?.get(row)?.content ?? null;
	const client = rustEmbedData();
	if (!client) return typescript();
	const fields = await client.openFields(key, row);
	(openedRows ??= new WeakMap()).set(row, fields);
	return fields.content;
}

/** The type/preview Rust opened with this row's content, else the TS decrypt of `ciphertext`. */
export async function openedEmbedField(row: StoredEmbedRow, field: 'type' | 'text_preview', ciphertext: string,
	typescript: (ciphertext: string) => Promise<string | null>): Promise<string | null> {
	const fields = openedRows?.get(row);
	return fields ? fields[field] : typescript(ciphertext);
}

/** Returned by `decodeToonInRust` when the Rust crypto arm is inactive: the caller runs its TS decoder. */
export const RUST_TOON_INACTIVE: unique symbol = Symbol('rust_toon_inactive');

/**
 * embedStore TOON hook: decodes stored embed content in the Worker's Rust TOON
 * parser. Where TOON refuses the text, the TS JSON.parse-else-null semantics of
 * `decodeToonContentLocal` apply (that is the decoder's contract, not a Rust
 * fallback). `RUST_TOON_INACTIVE` only when the Rust crypto arm is inactive
 * (measurement opt-out), the documented TS arm.
 */
export async function decodeToonInRust(text: string): Promise<unknown> {
	const client = rustEmbedData();
	if (!client) return RUST_TOON_INACTIVE;
	const decoded = await client.decodeToon(text);
	if (decoded !== null) return JSON.parse(decoded) as unknown;
	try {
		return JSON.parse(text) as unknown;
	} catch (error) {
		if (error instanceof SyntaxError) return null;
		throw error;
	}
}

/**
 * Version-history hook: replays a legacy artifact patch in the Worker's Rust
 * `embed_read::patch`. Null only when the Rust crypto arm is inactive (the
 * documented TS arm); a Rust refusal rejects like the TS replay threw.
 */
export async function applyVersionPatchInRust(content: string, patch: string): Promise<string | null> {
	const client = rustEmbedData();
	return client ? client.applyVersionPatch(content, patch) : null;
}

/**
 * AI-stream embed event gate: the Rust admission decision. Null only when the
 * Rust crypto arm is inactive (measurement opt-out), the documented TS arm; a
 * Rust failure rejects (the handlers' existing non-blocking catch applies).
 */
export async function admitEmbedEventInRust(request: EmbedEventAdmissionRequest): Promise<boolean | null> {
	const client = rustEmbedData();
	return client ? client.admitEmbedEvent(request) : null;
}

/**
 * Canonical embed sender hook (embedSenders.ts): the Rust decision for `op`.
 * Null only when the Rust crypto arm is inactive (measurement opt-out), the
 * documented TS arm; a Rust failure rejects like the sender's own IO errors.
 */
export async function decideEmbedSenderInRust<O extends EmbedSenderOp>(
	op: O, input: EmbedSenderDecisions[O]['input']
): Promise<EmbedSenderDecisions[O]['output'] | null> {
	const client = rustEmbedData();
	return client ? (client.decideSender(op, input) as Promise<EmbedSenderDecisions[O]['output']>) : null;
}

declare global {
	interface Window {
		/** Bench counters (row counts only) of the page's `embedData` client, read by web-rust-core-embeds.spec.ts. */
		__openmatesRustEmbedStats?: () => EmbedDataClient['stats'];
	}
}

let client: EmbedDataClient | null = null;
let clientCore: SharedRustCore | null = null;

/** The `embedData` client, or null when the Rust crypto arm is not active (TS runs). */
export function rustEmbedData(): EmbedDataClient | null {
	if (!rustWebCrypto()) return null;
	const core = requireSharedRustCore();
	if (client && clientCore === core) return client;
	client?.close();
	const created = new EmbedDataClient(core);
	client = created;
	clientCore = core;
	if (typeof window !== 'undefined') window.__openmatesRustEmbedStats = () => ({ ...created.stats });
	return created;
}
