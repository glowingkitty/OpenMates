/**
 * Chat-history placement of the core's folded `embed_updated` runs and the
 * Enhance availability rules of the image fullscreen (feature.embed-user-edits).
 */
import { describe, expect, it } from 'vitest';
import { embedEventRows, embedUpdatedCandidateKey, placeEmbedUpdatedGroups } from '../embedUpdatedHistory';
import { imageEditAvailability, imageEditErrorKey } from '../embeds/images/imageEnhance.svelte';
import type { EmbedChatItem } from '../../services/rustCore/embeds/embedEditProtocol';

const event = '{"type":"embed_updated","embed_id":"e1"}';
const history = [
	{ id: 'u1', role: 'user', content: 'mentions "embed_updated" in text' },
	{ id: 's1', role: 'system', content: event },
	{ id: 's2', role: 'system', content: event },
	{ id: 'a1', role: 'assistant', content: '' }
];

describe('embed_updated history rows', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.collapse
	it('sends only system candidate content to the core', () => {
		expect(embedEventRows(history).map((row) => row.content)).toEqual(['', event, event, '']);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.collapse
	it('changes the key only when candidates or their positions change', () => {
		const key = embedUpdatedCandidateKey(history);
		expect(embedUpdatedCandidateKey([...history, { id: 'a2', role: 'assistant', content: 'more' }])).toBe(key);
		expect(embedUpdatedCandidateKey(history.slice(1))).not.toBe(key);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.chat-notice,embed-user-edits.event.collapse
	it('draws a folded run once, at its newest message', () => {
		const items: EmbedChatItem[] = [
			{ kind: 'message', index: 0 },
			{ kind: 'embed_updated', embed_id: 'e1', embed_ref: 'r', embed_kind: 'image', latest_version: 3, change_count: 2,
				latest_action: 'enhance', latest_created_at: 1, message_ids: ['s1', 's2'], surface: 'chat' },
			{ kind: 'message', index: 3 }
		];
		const placement = placeEmbedUpdatedGroups(items);
		expect(Object.keys(placement.shownAt)).toEqual(['s2']);
		expect(placement.shownAt.s2).not.toHaveProperty('kind');
		expect(placement.shownAt.s2.change_count).toBe(2);
		expect([...placement.hidden]).toEqual(['s1']);
	});
});

describe('image Enhance availability', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button
	it('uses the chat scope in an own chat and the Project scope in the Projects workspace', () => {
		expect(imageEditAvailability({ chatId: 'c', chatTeamId: null, readOnly: false }))
			.toEqual({ kind: 'available', scope: { kind: 'chat', chat_id: 'c' } });
		expect(imageEditAvailability({ chatId: null, chatTeamId: null, projectId: 'p', readOnly: false }))
			.toEqual({ kind: 'available', scope: { kind: 'project', project_id: 'p' } });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button
	it('is unavailable for viewers and Team contexts', () => {
		expect(imageEditAvailability({ chatId: 'c', chatTeamId: null, readOnly: true })).toEqual({ kind: 'unavailable', reason: 'read_only' });
		expect(imageEditAvailability({ chatId: null, chatTeamId: null, readOnly: false })).toEqual({ kind: 'unavailable', reason: 'read_only' });
		expect(imageEditAvailability({ chatId: 'c', chatTeamId: 't', readOnly: false })).toEqual({ kind: 'unavailable', reason: 'team' });
		expect(imageEditAvailability({ chatId: null, chatTeamId: null, projectId: 'p', projectTeamId: 't', readOnly: false }))
			.toEqual({ kind: 'unavailable', reason: 'team' });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button
	it('names the core code in the message', () => {
		expect(imageEditErrorKey('insufficient_credits', 'enhance')).toBe('embed_user_edits.enhance_insufficient_credits');
		expect(imageEditErrorKey('embed_version_conflict', 'restore')).toBe('embed_user_edits.version_conflict');
		expect(imageEditErrorKey(undefined, 'restore')).toBe('embed_user_edits.restore_failed');
		expect(imageEditErrorKey('enhance_failed', 'enhance')).toBe('embed_user_edits.enhance_failed');
	});
});
