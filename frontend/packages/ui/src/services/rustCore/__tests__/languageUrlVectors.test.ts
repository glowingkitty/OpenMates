// Page-side handler forwarding for the shared Rust composer code-language and URL-kind
// helpers. The committed vectors (packages/openmates-rust/src/web_composer/
// language_url_ts_vectors.json) are replayed against Rust by web_composer/language_url_tests.rs.
import { describe, expect, it } from 'vitest';
import { createComposerHandlers } from '../composer/composerUnit';
import type { ComposerBinding } from '../composer/composerProtocol';

describe('composer language and URL handlers', () => {
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
