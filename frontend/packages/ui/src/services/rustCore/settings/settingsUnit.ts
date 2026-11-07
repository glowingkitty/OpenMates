/**
 * `settings` namespace installer of the shared Rust core Worker.
 *
 * Serves the app settings/memories request policy (settingsProtocol.ts) on the
 * unit port from the realm's single WASM binding. It holds no per-account state
 * and does no IO (the page owns IndexedDB and the decrypted entries), so it is a
 * pre-bind namespace. A malformed payload, or any binding rejection, answers the
 * fixed code `protocol` (the Rust boundary's only code).
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isSettingsBinding, type SettingsBinding, type SettingsUnitProtocol } from './settingsProtocol';

function record(payload: unknown): Record<string, unknown> {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
	return payload as Record<string, unknown>;
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

export function createSettingsHandlers(binding: SettingsBinding): UnitHandlers<SettingsUnitProtocol> {
	return {
		categoryPlan: (payload) => {
			const p = record(payload);
			return call(() => binding.settings_category_plan(text(p.requestedKeys), text(p.counts)));
		},
		requestAnswered: (payload) => {
			const p = record(payload);
			const contents = text(p.systemContents);
			const id = text(p.userMessageId);
			try {
				return binding.settings_request_answered(contents, id);
			} catch {
				throw new UnitRefusal('protocol');
			}
		},
		buildRequestMessage: (payload) => {
			const p = record(payload);
			if (typeof p.voice !== 'boolean') throw new UnitRefusal('protocol');
			const voice = p.voice;
			return call(() => binding.settings_build_request_message(text(p.userMessageId), text(p.requestId), text(p.requestedKeys), text(p.createdAt), text(p.counts), voice));
		},
		planSelectedKeys: (payload) => call(() => binding.settings_plan_selected_keys(text(record(payload).selectedKeys))),
		selectEntryIds: (payload) => {
			const p = record(payload);
			return call(() => binding.settings_select_entry_ids(text(p.entryIds), text(p.selection)));
		},
		responseCategories: (payload) => {
			const p = record(payload);
			return call(() => binding.settings_response_categories(text(p.categories), text(p.released)));
		},
		confirmOutcome: (payload) => {
			const p = record(payload);
			if (typeof p.voice !== 'boolean' || typeof p.hasMessageId !== 'boolean' || !Number.isInteger(p.releasedCount) || (p.releasedCount as number) < 0) throw new UnitRefusal('protocol');
			const { releasedCount, voice, hasMessageId } = p as { releasedCount: number; voice: boolean; hasMessageId: boolean };
			return call(() => binding.settings_confirm_outcome(releasedCount, voice, hasMessageId));
		},
		planPrivacyEntry: (payload) => {
			const p = record(payload);
			return call(() => binding.settings_plan_privacy_entry(text(p.itemType), text(p.data), text(p.defaultCategories)));
		},
		responseContent: (payload) => {
			const p = record(payload);
			// The binding returns the content text itself, not JSON: no parse.
			try {
				return binding.settings_response_content(text(p.userMessageId), text(p.action), text(p.categories));
			} catch {
				throw new UnitRefusal('protocol');
			}
		},
	};
}

export function installSettingsUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isSettingsBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<SettingsUnitProtocol>(port, createSettingsHandlers(context.binding));
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
