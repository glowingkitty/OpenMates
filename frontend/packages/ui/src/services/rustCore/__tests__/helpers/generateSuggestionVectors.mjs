/**
 * Regenerates packages/openmates-rust/src/web_composer/suggestion_ts_vectors.json
 * from the real flag-off mentionRanking.ts, embedSuggestionSearch.ts and
 * composerGhostDecode.ts. Run from the repo root (Node 22.18+ strips types):
 *   node frontend/packages/ui/src/services/rustCore/__tests__/helpers/generateSuggestionVectors.mjs
 * The import-free modules are copied into a temporary tree as ES modules.
 * suggestionVectors.test.ts re-checks the committed file against the real modules.
 */
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const ui = resolve(import.meta.dirname, '../../../..');
const tmp = mkdtempSync(join(tmpdir(), 'suggestion-vectors-'));
try {
	writeFileSync(join(tmp, 'package.json'), '{"type":"module"}');
	cpSync(join(import.meta.dirname, 'suggestionCases.ts'), join(tmp, 'cases.ts'));
	cpSync(join(ui, 'components/enter_message/services/mentionRanking.ts'), join(tmp, 'mentionRanking.ts'));
	cpSync(join(ui, 'services/embedSuggestionSearch.ts'), join(tmp, 'embedSuggestionSearch.ts'));
	cpSync(join(ui, 'services/composerGhostDecode.ts'), join(tmp, 'composerGhostDecode.ts'));
	const load = (name) => import(pathToFileURL(join(tmp, name)).href);
	const { rankMentionResults } = await load('mentionRanking.ts');
	const { decodeComposerGhostSuggestion } = await load('composerGhostDecode.ts');
	const embed = await load('embedSuggestionSearch.ts');
	const { buildSuggestionVectors } = await load('cases.ts');
	const vectors = buildSuggestionVectors({ rankMentionResults, decodeComposerGhostSuggestion, embed });
	const text = JSON.stringify(vectors, null, 1);
	if (/sk-|AKIA|ghp_|xox|AIza|eyJ|SG\.|hf_|BEGIN/.test(text)) throw new Error('vectors must not contain key-shaped strings');
	writeFileSync(resolve(import.meta.dirname, '../../../../../../../../packages/openmates-rust/src/web_composer/suggestion_ts_vectors.json'), `${text}\n`);
	console.log(`wrote ${Object.entries(vectors).map(([key, value]) => `${value.length} ${key}`).join(', ')}`);
} finally {
	rmSync(tmp, { recursive: true, force: true });
}
