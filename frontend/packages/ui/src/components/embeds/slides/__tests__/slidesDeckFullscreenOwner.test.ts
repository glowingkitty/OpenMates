/**
 * The deck fullscreen hands its opening chat to UnifiedEmbedFullscreen as the
 * owning chat. Without it, any `globalChatSelected` (also the re-announcement of
 * the same chat after a page reload) closed the open deck, which removed the
 * Edit button in the manual edit flow.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';

vi.mock('../../UnifiedEmbedFullscreen.svelte', async () => ({ default: (await import('./UnifiedFullscreenOwnerStub.svelte')).default }));
vi.mock('../../shared/EmbedVersionTimeline.svelte', async () => ({ default: (await import('./UnifiedFullscreenOwnerStub.svelte')).default }));
vi.mock('@repo/ui', async () => ({ text: (await import('svelte/store')).readable((key: string) => key) }));
vi.mock('../slidesDeckVersion', () => ({ saveEditedDeck: vi.fn() }));
vi.mock('../../../../stores/activeChatStore', async () => ({ activeChatStore: (await import('svelte/store')).writable('active-chat') }));
import SlidesDeckEmbedFullscreen from '../SlidesDeckEmbedFullscreen.svelte';
import { activeChatStore } from '../../../../stores/activeChatStore';

let component: ReturnType<typeof mount> | undefined;
afterEach(async () => {
  if (component) await unmount(component);
  component = undefined;
  document.body.innerHTML = '';
});

const owner = () => document.querySelector('[data-testid="owner-probe"]')?.getAttribute('data-owning-chat-id');
const data = { decodedContent: { slides_markup: '' }, embedData: { status: 'finished' } };

describe('SlidesDeckEmbedFullscreen owning chat', () => {
  // contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version
  it('passes the opening chat so re-selecting it keeps the deck open', async () => {
    component = mount(SlidesDeckEmbedFullscreen, { target: document.body, props: { data, onClose: vi.fn(), embedId: 'deck-1', chatId: 'chat-1' } });
    await tick();
    expect(owner()).toBe('chat-1');
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version
  it('falls back to the active chat and keeps it after a later chat switch', async () => {
    component = mount(SlidesDeckEmbedFullscreen, { target: document.body, props: { data, onClose: vi.fn(), embedId: 'deck-1' } });
    await tick();
    expect(owner()).toBe('active-chat');
    (activeChatStore as unknown as { set: (value: string) => void }).set('other-chat');
    await tick();
    expect(owner()).toBe('active-chat');
  });
});
