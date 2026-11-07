// TS-generated parity vectors for the shared Rust composer code-language and URL-kind
// helpers. The committed JSON (packages/openmates-rust/src/web_composer/
// language_url_ts_vectors.json) is written by helpers/generateLanguageUrlVectors.mjs
// from the real flag-off TypeScript modules; this test rebuilds it from them and fails
// on drift. web_composer/language_url_tests.rs replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import * as language from '../../../components/enter_message/services/codeLanguageDetection';
import * as urls from '../../../components/enter_message/services/urlKinds';
import { createComposerHandlers } from '../composer/composerUnit';
import type { ComposerBinding } from '../composer/composerProtocol';
import { buildLanguageUrlVectors } from './helpers/languageUrlCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_composer/language_url_ts_vectors.json');

describe('composer language and URL parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
	it('the TypeScript detection modules match the committed vectors', () => {
		const fresh = buildLanguageUrlVectors({ ...language, ...urls });
		expect(JSON.parse(JSON.stringify(fresh))).toEqual(JSON.parse(readFileSync(VECTORS, 'utf8')));
	});

	// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
	it('the composer handlers forward the language and URL ops as JSON text', async () => {
		const seen: string[] = [];
		const record = (name: string, answer: unknown) => (input: string) => { seen.push(`${name}:${input}`); return JSON.stringify(answer); };
		const binding = {
			composer_language_detect: record('l', { vsCode: 'python', content: null }),
			composer_url_classify: record('u', { youtube: true, githubRepo: false, videoId: 'dQw4w9WgXcQ' }),
		} as unknown as ComposerBinding;
		const handlers = createComposerHandlers(binding);
		const none = undefined as never;
		expect(await handlers.languageDetect({ text: 'x', vsCodeEditorData: null }, none)).toEqual({ vsCode: 'python', content: null });
		expect(await handlers.urlClassify({ url: 'https://youtu.be/dQw4w9WgXcQ' }, none)).toMatchObject({ youtube: true });
		expect(seen).toHaveLength(2);
		await expect(Promise.resolve().then(() => handlers.urlClassify('x' as never, none))).rejects.toMatchObject({ code: 'protocol' });
	});
});
