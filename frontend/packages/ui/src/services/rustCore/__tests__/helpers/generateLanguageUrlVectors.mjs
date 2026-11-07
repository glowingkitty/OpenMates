/**
 * Regenerates packages/openmates-rust/src/web_composer/language_url_ts_vectors.json
 * from the real flag-off codeLanguageDetection.ts and urlKinds.ts. Run from the repo
 * root (Node 22.18+ strips types):
 *   node frontend/packages/ui/src/services/rustCore/__tests__/helpers/generateLanguageUrlVectors.mjs
 * The import-free modules are copied into a temporary tree as ES modules.
 * languageUrlVectors.test.ts re-checks the committed file against the real modules.
 */
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const ui = resolve(import.meta.dirname, '../../../..');
const tmp = mkdtempSync(join(tmpdir(), 'language-url-vectors-'));
try {
	writeFileSync(join(tmp, 'package.json'), '{"type":"module"}');
	cpSync(join(import.meta.dirname, 'languageUrlCases.ts'), join(tmp, 'cases.ts'));
	cpSync(join(ui, 'components/enter_message/services/codeLanguageDetection.ts'), join(tmp, 'codeLanguageDetection.ts'));
	cpSync(join(ui, 'components/enter_message/services/urlKinds.ts'), join(tmp, 'urlKinds.ts'));
	const load = (name) => import(pathToFileURL(join(tmp, name)).href);
	const modules = { ...(await load('codeLanguageDetection.ts')), ...(await load('urlKinds.ts')) };
	const { buildLanguageUrlVectors } = await load('cases.ts');
	const vectors = buildLanguageUrlVectors(modules);
	const text = JSON.stringify(vectors, null, 1);
	if (/sk-|AKIA|ghp_|xox|AIza|eyJ|SG\.|hf_|BEGIN/.test(text)) throw new Error('vectors must not contain key-shaped strings');
	writeFileSync(resolve(import.meta.dirname, '../../../../../../../../packages/openmates-rust/src/web_composer/language_url_ts_vectors.json'), `${text}\n`);
	console.log(`wrote ${Object.entries(vectors).map(([key, value]) => `${value.length} ${key}`).join(', ')}`);
} finally {
	rmSync(tmp, { recursive: true, force: true });
}
