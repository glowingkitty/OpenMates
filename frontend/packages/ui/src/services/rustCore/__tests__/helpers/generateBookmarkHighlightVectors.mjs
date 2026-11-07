/**
 * Regenerates packages/openmates-rust/src/chat_state/bookmark_highlight_ts_vectors.json
 * from the real flag-off messageBookmarks.ts, handlersMessageHighlights.ts and
 * sendersMessageHighlights.ts. Run from the repo root (Node 22.18+ strips types):
 *   node frontend/packages/ui/src/services/rustCore/__tests__/helpers/generateBookmarkHighlightVectors.mjs
 * The services are copied into a temporary tree whose imports point at the recording
 * stubs of vectorStubs.ts (extensionless imports made explicit, the Rust flag read
 * replaced by `undefined`). bookmarkHighlightVectors.test.ts re-checks the committed
 * file against the real modules.
 */
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const ui = resolve(import.meta.dirname, '../../../../..');
const nodeModules = process.env.UI_NODE_MODULES ?? join(ui, 'node_modules');
const tmp = mkdtempSync(join(tmpdir(), 'bookmark-highlight-vectors-'));
const write = (path, text) => { mkdirSync(dirname(join(tmp, path)), { recursive: true }); writeFileSync(join(tmp, path), text); };
const stub = (path, names) => write(path, `export { ${names} } from '${pathToFileURL(join(tmp, 'vectorStubs.ts')).href}';\n`);
const service = (path) => readFileSync(join(ui, 'src/services', path), 'utf8')
	.replace(/import\.meta\.env\.VITE_OPENMATES_RUST_CORE/g, 'undefined')
	.replace(/(from\s+|import\()(["'])(\.[^"']*)\2/g, (_, head, quote, spec) => `${head}${quote}${spec}${spec.endsWith('.ts') ? '' : '.ts'}${quote}`);
try {
	symlinkSync(nodeModules, join(tmp, 'node_modules'));
	write('package.json', '{"type":"module"}');
	cpSync(join(import.meta.dirname, 'vectorStubs.ts'), join(tmp, 'vectorStubs.ts'));
	cpSync(join(import.meta.dirname, 'bookmarkHighlightBuild.ts'), join(tmp, 'bookmarkHighlightBuild.ts'));
	cpSync(join(import.meta.dirname, 'bookmarkHighlightCases.ts'), join(tmp, 'bookmarkHighlightCases.ts'));
	write('build.ts', readFileSync(join(tmp, 'bookmarkHighlightBuild.ts'), 'utf8').replace('./bookmarkHighlightCases', './bookmarkHighlightCases.ts'));
	cpSync(join(ui, 'src/services/workspaceCacheLifecycle.ts'), join(tmp, 'services/workspaceCacheLifecycle.ts'));
	stub('stores/authState.ts', 'authStore');
	stub('stores/userProfile.ts', 'userProfile, updateProfile');
	stub('config/api.ts', 'getApiEndpoint');
	stub('services/encryption/MetadataEncryptor.ts', 'decryptWithMasterKey, encryptWithMasterKey');
	stub('services/db.ts', 'chatDB');
	stub('services/websocketService.ts', 'webSocketService');
	stub('services/encryption/ChatKeyManager.ts', 'chatKeyManager');
	stub('services/encryption/MessageEncryptor.ts', 'encryptHighlightPayload, decryptHighlightPayload');
	write('services/db/messageHighlights.ts', `export { upsertHighlightIdb as upsertHighlight, deleteHighlightById, getHighlightsForMessage } from '${pathToFileURL(join(tmp, 'vectorStubs.ts')).href}';\n`);
	write('stores/messageHighlightsStore.ts', `export { upsertHighlightStore as upsertHighlight, removeHighlightStore as removeHighlight, markHighlightAsMine } from '${pathToFileURL(join(tmp, 'vectorStubs.ts')).href}';\n`);
	for (const name of ['messageBookmarks', 'handlersMessageHighlights', 'sendersMessageHighlights']) write(`services/${name}.ts`, service(`${name}.ts`));

	const load = (path) => import(pathToFileURL(join(tmp, path)).href);
	const stubs = await load('vectorStubs.ts');
	stubs.installFetch();
	const memory = new Map();
	globalThis.localStorage = {
		getItem: (key) => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, String(value)),
		removeItem: (key) => memory.delete(key), clear: () => memory.clear(),
	};
	const lifecycle = await load('services/workspaceCacheLifecycle.ts');
	const bookmarks = await load('services/messageBookmarks.ts');
	const { buildBookmarkHighlightVectors } = await load('build.ts');
	const vectors = await buildBookmarkHighlightVectors({
		state: stubs.state, get: stubs.get, bookmarks,
		resetBookmarks: (settings) => { lifecycle.invalidateWorkspaceCaches(); stubs.resetBookmarkAccount(settings); },
		storage: globalThis.localStorage,
		handlers: await load('services/handlersMessageHighlights.ts'),
		senders: await load('services/sendersMessageHighlights.ts'),
	});
	const target = resolve(import.meta.dirname, '../../../../../../../../packages/openmates-rust/src/chat_state/bookmark_highlight_ts_vectors.json');
	writeFileSync(target, `${JSON.stringify(vectors, null, 1)}\n`);
	console.log(`wrote ${Object.entries(vectors).map(([key, value]) => `${value.length} ${key}`).join(', ')}`);
} finally {
	rmSync(tmp, { recursive: true, force: true });
}
