/**
 * `composer` namespace installer of the shared Rust core Worker.
 *
 * Serves the composer operations (composerProtocol.ts) on the unit port from the
 * realm's single WASM binding. It holds no account state, so it is a pre-bind
 * namespace. A malformed payload or a binding rejection answers the fixed code
 * `protocol`; the model-offset contract break answers `invalid_offsets`.
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isComposerBinding, type ComposerBinding, type ComposerUnitProtocol } from './composerProtocol';

function bindingCode(error: unknown): string {
	const text = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return text === 'invalid_offsets' ? 'invalid_offsets' : 'protocol';
}

function call<T>(payload: unknown, run: (json: string) => string): T {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
	let json: string;
	try {
		json = run(JSON.stringify(payload));
	} catch (error) {
		throw new UnitRefusal(bindingCode(error));
	}
	return JSON.parse(json) as T;
}

export function createComposerHandlers(binding: ComposerBinding): UnitHandlers<ComposerUnitProtocol> {
	return {
		pasteClassify: (p) => call(p, (j) => binding.composer_paste_classify(j)),
		plainTextToHtml: (p) => call(p, (j) => binding.composer_plain_text_to_html(j)),
		piiDetect: (p) => call(p, (j) => binding.composer_pii_detect(j)),
		piiReplace: (p) => call(p, (j) => binding.composer_pii_replace(j)),
		piiRestore: (p) => call(p, (j) => binding.composer_pii_restore(j)),
		piiReplaceOriginals: (p) => call(p, (j) => binding.composer_pii_replace_originals(j)),
		piiFindRestored: (p) => call(p, (j) => binding.composer_pii_find_restored(j)),
		piiSummary: (p) => call(p, (j) => binding.composer_pii_summary(j)),
		piiRewrite: (p) => call(p, (j) => binding.composer_pii_rewrite(j)),
		piiWindows: (p) => call(p, (j) => binding.composer_pii_windows(j)),
		piiMergeWindowEntities: (p) => call(p, (j) => binding.composer_pii_merge_window_entities(j)),
		piiMergeMatches: (p) => call(p, (j) => binding.composer_pii_merge_matches(j)),
		mentionsRank: (p) => call(p, (j) => binding.composer_mentions_rank(j)),
		savedEmbedsRank: (p) => call(p, (j) => binding.composer_saved_embeds_rank(j)),
		ghostValidate: (p) => call(p, (j) => binding.composer_ghost_validate(j)),
	};
}

export function installComposerUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isComposerBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<ComposerUnitProtocol>(port, createComposerHandlers(context.binding));
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
