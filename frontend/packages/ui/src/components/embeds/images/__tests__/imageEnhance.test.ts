// Enhance button state: a saved version is never reported as a failed Enhance (embed-user-edits.enhance.button).
import { describe, expect, it, vi } from 'vitest';
import { createImageEnhance } from '../imageEnhance.svelte';

const SCOPE = { kind: 'chat' as const, chat_id: 'chat-1' };

function setup(overrides: { enhance?: () => Promise<{ version: number }>; reloadHead?: (v: number | null) => Promise<void> } = {}) {
	const reloadHead = vi.fn(overrides.reloadHead ?? (async () => undefined));
	const enhance = vi.fn(overrides.enhance ?? (async () => ({ version: 2 })));
	const controller = createImageEnhance(() => 'embed-1', () => SCOPE, {
		enhance, running: async () => null, translate: (key) => key, reloadHead,
	});
	return { controller, reloadHead, enhance };
}

describe('image Enhance button state', () => {
	// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
	it('shows the saved version after a successful Enhance', async () => {
		const { controller, reloadHead } = setup();
		controller.start();
		await vi.waitFor(() => expect(reloadHead).toHaveBeenCalledWith(2));
		expect(controller.state).toBe('idle');
		expect(controller.error).toBeUndefined();
	});

	// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
	it('keeps a saved Enhance successful when showing the new version fails', async () => {
		const logged = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const { controller, reloadHead } = setup({ reloadHead: async () => { throw new Error('display'); } });
		controller.start();
		await vi.waitFor(() => expect(reloadHead).toHaveBeenCalledWith(2));
		await vi.waitFor(() => expect(logged).toHaveBeenCalled());
		expect(controller.state).toBe('idle');
		expect(controller.error).toBeUndefined();
		logged.mockRestore();
	});

	// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
	it('reports a refused Enhance with its message and does not reload', async () => {
		const logged = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const { controller, reloadHead } = setup({ enhance: async () => { throw Object.assign(new Error('x'), { code: 'insufficient_credits' }); } });
		controller.start();
		await vi.waitFor(() => expect(controller.state).toBe('failed'));
		expect(controller.error).toBe('embed_user_edits.enhance_insufficient_credits');
		expect(reloadHead).not.toHaveBeenCalled();
		logged.mockRestore();
	});
});
