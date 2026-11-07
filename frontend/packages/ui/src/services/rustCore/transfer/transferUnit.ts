/**
 * `transfer` namespace installer of the shared Rust core Worker.
 *
 * Serves chat import routing/parsing (transferProtocol.ts) on the unit port from
 * the realm's single WASM binding. It holds no account state and does no IO, so
 * it is a pre-bind namespace. Payload envelopes are re-serialized to JSON text
 * for the binding; the export text itself is passed as its own argument. A
 * malformed payload or a binding rejection answers the fixed code `protocol`.
 * Export payloads carry arbitrary page data, so they are serialized with
 * `exportJson`, which keeps what plain JSON would lose (see below).
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isTransferBinding, type TransferBinding, type TransferUnitProtocol } from './transferProtocol';

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
function record(payload: unknown): Record<string, unknown> {
	if (!isRecord(payload)) throw new UnitRefusal('protocol');
	return payload;
}
function text(value: unknown): string {
	if (typeof value !== 'string') throw new UnitRefusal('protocol');
	return value;
}
/** Binding results are JSON text; a thrown JsValue is the Rust `protocol` code. */
function call<T>(run: () => string): T {
	let json: string;
	try {
		json = run();
	} catch {
		throw new UnitRefusal('protocol');
	}
	return JSON.parse(json) as T;
}

/** Lone surrogates cannot be JSON text; the browser writes U+FFFD for them anyway. */
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;
/** `String.prototype.toWellFormed`: lone surrogates become U+FFFD. */
export function wellFormed(text: string): string {
	return text.replace(LONE_SURROGATE, '\ufffd');
}

/**
 * JSON.stringify replacer for export payloads: `undefined` object members become
 * `null` (the exporter prints `null`), while `NaN`, `Infinity` and `undefined`
 * array items become the `{"$om_raw": text}` marker the YAML emitter prints
 * verbatim, and strings are made well formed.
 */
export function exportJsonReplacer(this: unknown, _key: string, value: unknown): unknown {
	if (value === undefined) return Array.isArray(this) ? { $om_raw: 'undefined' } : null;
	if (typeof value === 'number' && !Number.isFinite(value)) return { $om_raw: String(value) };
	if (typeof value === 'string') return wellFormed(value);
	return value;
}

export function createTransferHandlers(binding: TransferBinding): UnitHandlers<TransferUnitProtocol> {
	const envelope = (payload: unknown) => JSON.stringify(record(payload));
	const exportEnvelope = (payload: unknown) => JSON.stringify(record(payload), exportJsonReplacer);
	return {
		importRoute: (payload) => call(() => binding.transfer_import_route(envelope(payload))),
		parseJson: (payload) => {
			const p = record(payload);
			const meta = JSON.stringify(record(p.meta));
			const body = text(p.text);
			return call(() => binding.transfer_parse_json_import(meta, body));
		},
		zipPlan: (payload) => call(() => binding.transfer_zip_plan(envelope(payload))),
		openmatesManifest: (payload) => call(() => binding.transfer_openmates_manifest(envelope(payload))),
		parseOpenMates: (payload) => call(() => binding.transfer_parse_openmates_archive(envelope(payload))),
		batchPlan: (payload) => call(() => binding.transfer_batch_plan(envelope(payload))),
		exportFilename: (payload) => call(() => binding.transfer_export_filename(exportEnvelope(payload))),
		exportDraftKind: (payload) => call(() => binding.transfer_export_draft_kind(exportEnvelope(payload))),
		exportYaml: (payload) => call(() => binding.transfer_export_yaml(exportEnvelope(payload))),
	};
}

export function installTransferUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isTransferBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<TransferUnitProtocol>(port, createTransferHandlers(context.binding));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		stop();
		port.close();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
