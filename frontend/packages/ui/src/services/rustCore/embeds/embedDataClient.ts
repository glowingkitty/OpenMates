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
	readonly stats = { requests: 0, rows: 0, failures: 0 };

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
 * Opens a stored row's content (and, in the same Rust call, its type and preview).
 * Returns the content, or null when it did not open (the caller marks the row
 * failed, as for the TS decrypt). A Rust rejection propagates to the caller.
 */
export async function openStoredEmbedContent(key: Uint8Array, row: StoredEmbedRow,
	typescript: () => Promise<string | null>): Promise<string | null> {
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
