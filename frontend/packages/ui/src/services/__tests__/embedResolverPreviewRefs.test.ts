import { describe, expect, it, vi } from 'vitest';
import { authStore } from '../../stores/authState';
import {
	isLocalCodeDocPreviewRef,
	requestEmbedFromServerOnce,
	resolveEmbed
} from '../embedResolver';

const sendMessage = vi.hoisted(() => vi.fn());
vi.mock('../websocketService', () => ({
	webSocketService: { sendMessage }
}));

describe('editor-only code and document previews', () => {
	// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,drafts.sync.version-authoritative
	it.each([
		'preview:code-code:local-code',
		'preview:code:legacy-local-code',
		'preview:docs-doc:local-document'
	])('never requests %s as a persisted server embed', async (localRef) => {
		expect(isLocalCodeDocPreviewRef(localRef)).toBe(true);
		expect(await resolveEmbed(localRef)).toBeNull();
		expect(await requestEmbedFromServerOnce(localRef, 'editor-preview')).toBe(false);
		expect(sendMessage).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,drafts.sync.version-authoritative
	it('still requests a canonical persisted embed ID', async () => {
		sendMessage.mockReset().mockResolvedValue(undefined);
		authStore.set({ isAuthenticated: true, isInitialized: true });
		const persistedId = '49c8b203-f752-46c3-af2c-b4f2d08af115';
		expect(isLocalCodeDocPreviewRef(`embed:${persistedId}`)).toBe(false);
		expect(isLocalCodeDocPreviewRef('preview:other:possibly-persisted')).toBe(false);
		expect(await requestEmbedFromServerOnce(`embed:${persistedId}`, 'persisted')).toBe(true);
		expect(sendMessage).toHaveBeenCalledWith(
			'request_embed',
			expect.objectContaining({ embed_id: persistedId })
		);
	});
});
