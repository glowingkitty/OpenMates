// @vitest-environment node
/**
 * Page glue of content edits (feature.embed-user-edits): the save scope picked
 * from where the editor was opened, and the stored TOON head of the next
 * version handed to the Worker's `commitContentRevision`. The Worker and the
 * core are stubs; the core's own behaviour is covered by its crate tests.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { decode } from '@toon-format/toon';

const commitContentRevision = vi.fn();
const requestEmbedFromServerOnce = vi.fn(async () => true);
vi.mock('../embedEditSession', () => ({ commitContentRevision: (...args: unknown[]) => commitContentRevision(...args) }));
vi.mock('../../../embedResolver', () => ({ requestEmbedFromServerOnce: (...args: unknown[]) => requestEmbedFromServerOnce(...(args as [])) }));
// The page cache has no copy of these embeds, so the save reads the head from the server.
vi.mock('../../../embedStore', () => ({ embedStore: { prepareVersionRestoreUpdate: async () => ({ updated: false }) } }));

import { adoptSavedHead, contentEditScope, saveContentEdit, type SavedHeadCache } from '../embedContentEdit';

const SAVED = { version: 4, base_version: 3, event: { state: 'written' }, cache_synchronized: true, content_hash: 'a'.repeat(64) } as const;

beforeEach(() => {
	commitContentRevision.mockReset();
	requestEmbedFromServerOnce.mockClear();
});

describe('contentEditScope', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.chat-notice
	it('saves an edit opened in a personal chat in that chat', () => {
		expect(contentEditScope({ chatId: 'chat-1', chatTeamId: null })).toEqual({ kind: 'chat', chat_id: 'chat-1' });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.project-edit-reaches-chat
	it('saves an edit opened in the Projects workspace in Project scope, even when the embed has a chat', () => {
		expect(contentEditScope({ chatId: 'chat-1', projectId: 'project-1' })).toEqual({ kind: 'project', project_id: 'project-1' });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('leaves Team chats, Team Projects and editors without a place to the earlier save path', () => {
		expect(contentEditScope({ chatId: 'chat-1', chatTeamId: 'team-1' })).toBeNull();
		expect(contentEditScope({ projectId: 'project-1', projectTeamId: 'team-1' })).toBeNull();
		expect(contentEditScope({})).toBeNull();
	});
});

describe('saveContentEdit', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version,embed-user-edits.event.chat-notice
	it('hands the core the TOON head of the next version and reloads the head into the page cache', async () => {
		commitContentRevision.mockResolvedValue(SAVED);
		const scope = { kind: 'chat', chat_id: 'chat-1' } as const;
		await expect(saveContentEdit('sheet-1', scope, 3, (version) => ({ app_id: 'sheets', table: '| a |', version_number: version })))
			.resolves.toEqual(SAVED);
		const [embedId, sentScope, base, content] = commitContentRevision.mock.calls[0] as [string, unknown, number, string];
		expect([embedId, sentScope, base]).toEqual(['sheet-1', scope, 3]);
		expect(decode(content)).toEqual({ app_id: 'sheets', table: '| a |', version_number: 4 });
		expect(requestEmbedFromServerOnce).toHaveBeenCalledWith('sheet-1', 'user embed version saved', { chatId: 'chat-1' });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.project-edit-reaches-chat
	it('reloads a Projects workspace save without a chat', async () => {
		commitContentRevision.mockResolvedValue(SAVED);
		await saveContentEdit('deck-1', { kind: 'project', project_id: 'project-1' }, 3, (version) => ({ version_number: version }));
		expect(requestEmbedFromServerOnce).toHaveBeenCalledWith('deck-1', 'user embed version saved', { chatId: null });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('writes the saved head into the page cache so a reopen or reload shows it', async () => {
		const cache: SavedHeadCache = { update: vi.fn(async () => true), refetch: vi.fn(async () => undefined), announce: vi.fn() };
		await adoptSavedHead('deck-1', { kind: 'chat', chat_id: 'chat-1' }, 'toon-v4', SAVED, cache);
		expect(cache.update).toHaveBeenCalledWith('deck-1', 'toon-v4', 4, 'a'.repeat(64));
		expect(cache.announce).toHaveBeenCalledWith('deck-1', 'chat-1');
		// The server read is suppressed right after the open; it must not be the only update.
		expect(cache.refetch).not.toHaveBeenCalled();
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('passes the core refusal through and reloads nothing', async () => {
		commitContentRevision.mockRejectedValue(Object.assign(new Error('embed_version_conflict'), { code: 'embed_version_conflict' }));
		await expect(saveContentEdit('diagram-1', { kind: 'chat', chat_id: 'chat-1' }, 1, (version) => ({ version_number: version })))
			.rejects.toMatchObject({ code: 'embed_version_conflict' });
		expect(requestEmbedFromServerOnce).not.toHaveBeenCalled();
	});
});
