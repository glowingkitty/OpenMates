import { describe, expect, it } from 'vitest';
import { chatSelectionClosesFullscreen, fullscreenOwnerChatId } from './fullscreenChatOwner';

describe('chat embed fullscreen owner', () => {
  // contract-test: supporting surface=gui.web assertions=projects.agentic.files-as-code-embeds
  it('keeps the fullscreen open when its own chat is announced again', () => {
    const owner = fullscreenOwnerChatId(undefined, 'chat-1', null);
    expect(owner).toBe('chat-1');
    expect(chatSelectionClosesFullscreen('chat-1', owner)).toBe(false);
    expect(chatSelectionClosesFullscreen('chat-2', owner)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=projects.agentic.files-as-code-embeds
  it('prefers the explicit owner and closes when no owner is known', () => {
    expect(fullscreenOwnerChatId('deck-chat', 'chat-1', 'source')).toBe('deck-chat');
    expect(fullscreenOwnerChatId(undefined, null, 'source')).toBe('source');
    expect(chatSelectionClosesFullscreen('chat-1', fullscreenOwnerChatId(undefined, null, null))).toBe(true);
  });
});
