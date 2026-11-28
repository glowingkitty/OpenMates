import { afterEach, describe, expect, it, vi } from 'vitest';
import { mount, unmount } from 'svelte';

vi.mock('@repo/ui', async () => {
  const { readable } = await import('svelte/store');
  return { text: readable((key: string) => key) };
});
import LiveHeaderStatus from '../LiveHeaderStatus.svelte';

let mounted: ReturnType<typeof mount> | undefined;
afterEach(async () => { if (mounted) await unmount(mounted); mounted = undefined; document.body.innerHTML = ''; });

describe('LiveHeaderStatus', () => {
  // contract-test: supporting surface=gui.web assertions=live-collab.saving.automatic
  it.each([
    ['saved', 'live_status_saved'],
    ['saving', 'live_status_saving'],
    ['offline', 'live_status_offline'],
    ['read_only', 'live_status_read_only'],
    ['access_revoked', 'live_status_access_revoked'],
  ] as const)('shows the %s status', (status, key) => {
    mounted = mount(LiveHeaderStatus, { target: document.body, props: { status } });
    expect(document.querySelector('[data-testid="live-status"]')?.textContent).toBe(`embed_user_edits.${key}`);
    expect(document.querySelector('[data-testid="live-peers"]')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
  it('shows one coloured avatar per present person', () => {
    mounted = mount(LiveHeaderStatus, { target: document.body, props: {
      status: 'saved',
      peers: [{ user_id: 'u1', display_name: 'Mara', color: 'rgb(232, 89, 12)' }, { user_id: 'u2', display_name: 'x', color: 'rgb(28, 126, 214)', mate_name: 'Sophia' }],
    } });
    const avatars = [...document.querySelectorAll<HTMLElement>('[data-testid="live-peer"]')];
    expect(avatars.map((a) => a.textContent)).toEqual(['M', 'S']);
    expect(avatars[0].style.background).toBe('rgb(232, 89, 12)');
  });
});
