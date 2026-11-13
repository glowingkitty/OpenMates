/**
 * Regenerates packages/openmates-rust/src/web_chat_state/view_ts_vectors.json from
 * the TypeScript selection plans, unread store, read gate and shared sub-chat
 * mapper. Run from the repo root (Node 22.18+ strips types):
 *   node frontend/packages/ui/src/services/rustCore/__tests__/helpers/generateChatViewVectors.mjs
 * The unread store reads `import.meta.env` (undefined under plain Node), so it is
 * loaded from a temporary copy with that flag read replaced by `undefined` and
 * extensionless imports made explicit; chatViewVectors.test.ts re-checks the
 * committed file against the real modules.
 */
import { cpSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const ui = resolve(import.meta.dirname, '../../../../..');
const src = (path) => pathToFileURL(join(ui, 'src', path)).href;
const { planUrlUpdate } = await import(src('stores/activeChatUrlPlan.ts'));
const { planGlobalSelected, skipDraftActivation } = await import(src('components/chats/utils/chatSelectionPlan.ts'));
const { sharedSubChatToChat } = await import(src('components/chats/utils/sharedSubChatChat.ts'));
const { chatsOrganizable, planPlacement } = await import(src('utils/chatProjectPlacement.ts'));
const { readGateAllows } = await import(src('services/readGate.ts'));

const tmp = mkdtempSync(join(tmpdir(), 'unread-vectors-'));
try {
	symlinkSync(join(ui, 'node_modules'), join(tmp, 'node_modules'));
	writeFileSync(join(tmp, 'package.json'), '{"type":"module"}');
	cpSync(join(ui, 'src/stores/unreadReducer.ts'), join(tmp, 'unreadReducer.ts'));
	const store = readFileSync(join(ui, 'src/stores/unreadMessagesStore.ts'), 'utf8')
		.replace('"./unreadReducer"', '"./unreadReducer.ts"')
		.replace('import.meta.env.VITE_OPENMATES_RUST_CORE', 'undefined');
	writeFileSync(join(tmp, 'unreadMessagesStore.ts'), store);
	const { unreadMessagesStore: s } = await import(pathToFileURL(join(tmp, 'unreadMessagesStore.ts')).href);
	const { get } = await import(pathToFileURL(join(ui, 'node_modules/svelte/src/store/index-server.js')).href);
	const { buildChatViewVectors } = await import(pathToFileURL(join(import.meta.dirname, 'chatViewBuild.ts')).href);
	const cases = await import(pathToFileURL(join(import.meta.dirname, 'chatViewCases.ts')).href);
	const vectors = buildChatViewVectors({
		cases,
		planUrlUpdate, planGlobalSelected, skipDraftActivation, readGateAllows, sharedSubChatToChat, chatsOrganizable, planPlacement,
		unread: {
			apply: (e) => {
				if (e.type === 'increment') s.incrementUnread(e.chat, e.messageId);
				else if (e.type === 'set') s.setUnread(e.chat, e.count, e.messageId);
				else if (e.type === 'clear') s.clearUnread(e.chat);
				else if (e.type === 'mark_manual') s.markManuallyUnread(e.chat);
				else if (e.type === 'release_manual') s.releaseManualUnread(e.chat);
				else s.clearAll();
			},
			counts: () => [...get(s).unreadCounts.entries()],
			isManual: (chat) => s.isManuallyUnread(chat),
			count: (chat) => s.getUnreadCount(chat),
			// chatReadState.hasUnread imports the database; this is its one-line body.
			hasUnread: (chat, persisted) => s.getUnreadCount(chat) > 0 || (persisted ?? 0) > 0,
		},
	});
	const target = resolve(import.meta.dirname, '../../../../../../../../packages/openmates-rust/src/web_chat_state/view_ts_vectors.json');
	writeFileSync(target, `${JSON.stringify(vectors, null, 1)}\n`);
	console.log(`wrote ${Object.entries(vectors).map(([k, v]) => `${v.length} ${k}`).join(', ')}`);
} finally {
	rmSync(tmp, { recursive: true, force: true });
}
