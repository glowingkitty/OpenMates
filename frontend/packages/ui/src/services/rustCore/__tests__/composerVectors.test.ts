// TS-generated parity vectors for the shared Rust composer logic. The committed
// JSON (packages/openmates-rust/src/web_composer/ts_vectors.json) holds inputs
// plus the outcomes of the TypeScript services; this test fails if the
// TypeScript behaviour drifts, and web_composer/tests.rs replays the same file
// against Rust. It also checks the Worker handlers' marshalling.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { classifyPastedContent, plainTextToDocumentHtml } from '../../../components/enter_message/services/pasteClassification';
import { detectPII, replacePIIWithPlaceholders, restorePIIInText } from '../../../components/enter_message/services/piiDetectionService';
import { buildWebPIIWindows, mergeWebPIIWindowEntities } from '../../../components/enter_message/services/webPIIWindows';
import { createComposerHandlers } from '../composer/composerUnit';
import { isComposerBinding, type ComposerBinding } from '../composer/composerProtocol';

const vectors = JSON.parse(readFileSync(resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_composer/ts_vectors.json'), 'utf8'));

describe('composer vectors', () => {
	// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
	it('paste classification equals the TypeScript service', () => {
		for (const c of vectors.paste) expect(classifyPastedContent(c.in), JSON.stringify(c.in).slice(0, 80)).toEqual(c.out);
		for (const c of vectors.plain) expect(plainTextToDocumentHtml(c.in.text)).toEqual(c.out);
	});
	// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
	it('detection spans equal the TypeScript service', () => {
		for (const c of vectors.detect) {
			const options = c.in.options && {
				...c.in.options,
				excludedIds: c.in.options.excludedIds && new Set(c.in.options.excludedIds),
				disabledCategories: c.in.options.disabledCategories && new Set(c.in.options.disabledCategories),
			};
			const found = detectPII(c.in.text, options).map(({ match: _match, ...span }) => span);
			expect(found, JSON.stringify(c.in).slice(0, 80)).toEqual(c.out);
		}
	});
	// contract-test: supporting surface=gui.web assertions=pii.message.owner-local-reveal
	it('replace and restore equal the TypeScript service', () => {
		for (const c of vectors.replace) expect(replacePIIWithPlaceholders(c.in.text, c.in.matches)).toEqual(c.out);
		for (const c of vectors.restore) expect(restorePIIInText(c.in.text, c.in.mappings)).toEqual(c.out);
	});
	// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
	it('model windows and entity merge equal the TypeScript service', () => {
		for (const c of vectors.windows) expect(buildWebPIIWindows(c.in.text)).toEqual(c.out);
		for (const c of vectors.mergeEntities) {
			const kept = mergeWebPIIWindowEntities(c.in.entities).map((e) => c.in.entities.indexOf(e));
			expect(kept).toEqual(c.out);
		}
	});
});

describe('composer handlers', () => {
	const fail = () => { throw 'invalid_offsets'; };
	const binding = {
		composer_paste_classify: () => JSON.stringify({ kind: 'text', reason: 'x' }),
		composer_plain_text_to_html: () => '"<p>a</p>"',
		composer_pii_detect: () => '[]',
		composer_pii_replace: () => '"r"',
		composer_pii_restore: () => '"s"',
		composer_pii_replace_originals: () => '"o"',
		composer_pii_find_restored: () => '[]',
		composer_pii_summary: () => '""',
		composer_pii_rewrite: () => JSON.stringify({ markdown: '', applied: [] }),
		composer_pii_windows: () => '[]',
		composer_pii_merge_window_entities: () => '[]',
		composer_pii_merge_matches: fail,
		composer_mentions_rank: () => '[]',
		composer_saved_embeds_rank: () => '[]',
		composer_ghost_validate: () => JSON.stringify({ valid: true }),
	} as ComposerBinding;
	// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
	it('forwards JSON text and maps binding rejection to its code', async () => {
		expect(isComposerBinding(binding)).toBe(true);
		expect(isComposerBinding({})).toBe(false);
		const handlers = createComposerHandlers(binding);
		expect(await handlers.piiReplace({ text: 'a', matches: [] }, undefined as never)).toBe('r');
		await expect(Promise.resolve().then(() => handlers.piiMergeMatches({ text: 'a', entities: [], nonce: 'n' }, undefined as never)))
			.rejects.toMatchObject({ code: 'invalid_offsets' });
		await expect(Promise.resolve().then(() => handlers.piiDetect('x' as never, undefined as never))).rejects.toMatchObject({ code: 'protocol' });
	});
});
