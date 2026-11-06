/**
 * `embedData` namespace installer of the shared Rust core Worker.
 *
 * Decrypts stored embed rows next to the realm's single WASM binding: every
 * requested row is one `embed_open_row_fields` call (Rust `embed_write::read`,
 * its three fields in one batched WebCrypto call). The unit holds no account
 * state, so it is a pre-bind namespace like `crypto`: the embed key arrives per
 * request (as the crypto unit's chat keys do) and is imported non-extractable
 * by Rust; nothing is cached here and no key or plaintext is logged.
 *
 * Wire: host/unitPort.ts (`openFields`, `decodeToon`), `EMBED_UNIT_CLOSE` disposes the unit.
 * A row that Rust rejects answers `{ok:false, code}` for that row only.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import {
	EMBED_DATA_MAX_ITEMS,
	isEmbedUnitClose,
	type EmbedDataProtocol,
	type EmbedFieldsRequest,
	type EmbedFieldsResult,
	type OpenedEmbedFields
} from './embedDataProtocol';

export interface EmbedDataBinding {
	embed_open_row_fields(
		key: Uint8Array,
		encryptedContent: string | undefined,
		encryptedType: string | undefined,
		encryptedTextPreview: string | undefined
	): Promise<unknown>;
	/** Rust `toon_decode::decode_to_json_text`; throws `toon_decode_failed` for refused TOON. */
	toon_decode(text: string): string;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

export function isEmbedDataBinding(value: unknown): value is EmbedDataBinding {
	const binding = value as Partial<EmbedDataBinding> | null;
	return typeof binding?.embed_open_row_fields === 'function' && typeof binding.toon_decode === 'function';
}

function optionalText(value: unknown): value is string | null {
	return value === null || typeof value === 'string';
}

function validItem(value: unknown): value is EmbedFieldsRequest {
	if (typeof value !== 'object' || value === null) return false;
	const item = value as Record<string, unknown>;
	// Tag check, not instanceof: structured clone may land the bytes in another realm's Uint8Array.
	return Object.prototype.toString.call(item.key) === '[object Uint8Array]' && optionalText(item.encrypted_content)
		&& optionalText(item.encrypted_type) && optionalText(item.encrypted_text_preview);
}

function opened(value: unknown): OpenedEmbedFields {
	const fields = value as Record<string, unknown> | null;
	if (typeof fields !== 'object' || fields === null || typeof fields.content_failed !== 'boolean'
		|| !optionalText(fields.content) || !optionalText(fields.type) || !optionalText(fields.text_preview)) {
		throw new UnitRefusal('embed_data_protocol');
	}
	return { content: fields.content, content_failed: fields.content_failed, type: fields.type, text_preview: fields.text_preview };
}

function rejection(error: unknown): string {
	const code = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return CODE.test(code) ? code : 'embed_data_failed';
}

/** The `embedData` handlers over one binding (exported for in-process tests). */
export function createEmbedDataHandlers(binding: EmbedDataBinding): UnitHandlers<EmbedDataProtocol> {
	const text = (value: string | null) => value ?? undefined;
	return {
		async openFields(payload) {
			const items = (payload as { items?: unknown } | null)?.items;
			if (!Array.isArray(items) || items.length > EMBED_DATA_MAX_ITEMS || !items.every(validItem)) {
				throw new UnitRefusal('embed_data_bad_request');
			}
			return Promise.all(items.map(async (item): Promise<EmbedFieldsResult> => {
				let raw: unknown;
				try {
					raw = await binding.embed_open_row_fields(item.key, text(item.encrypted_content), text(item.encrypted_type),
						text(item.encrypted_text_preview));
				} catch (error) {
					return { ok: false, code: rejection(error) };
				} finally {
					item.key.fill(0);
				}
				return { ok: true, fields: opened(raw) };
			}));
		},
		decodeToon(payload) {
			const texts = (payload as { texts?: unknown } | null)?.texts;
			if (!Array.isArray(texts) || texts.length > EMBED_DATA_MAX_ITEMS || !texts.every((text) => typeof text === 'string')) {
				throw new UnitRefusal('embed_data_bad_request');
			}
			return texts.map((text: string) => {
				try {
					return binding.toon_decode(text);
				} catch (error) {
					// Only TOON's own refusal maps to null (the page then applies the TS JSON fallback).
					const code = rejection(error);
					if (code === 'toon_decode_failed') return null;
					throw new UnitRefusal(code);
				}
			});
		}
	};
}

export function installEmbedDataUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isEmbedDataBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	let disposed = false;
	const stopServing = serveUnitPort<EmbedDataProtocol>(port, createEmbedDataHandlers(context.binding));
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		port.removeEventListener('message', control);
		stopServing();
		port.close();
	};
	function control(event: MessageEvent<unknown>): void {
		if (isEmbedUnitClose(event.data)) dispose();
	}
	port.addEventListener('message', control);
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
