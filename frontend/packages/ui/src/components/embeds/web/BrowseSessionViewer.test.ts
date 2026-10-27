import { mount, tick, unmount } from 'svelte';
import { afterEach, expect, it, vi } from 'vitest';
import BrowseSessionViewer from './BrowseSessionViewer.svelte';
import { BrowseHttpError, type BrowseClient, type BrowseSession } from '../../../services/webBrowseService';

const session: BrowseSession = { session_id: '11111111-1111-4111-8111-111111111111', chat_id: 'chat', status: 'user',
  task: 'Read the public page', url: 'https://example.com', sign_in_notice: '', sign_in_origins: [], max_credits: 50,
  accrued_credits: 5, charged_credits: 5, expires_at: 1793200000, accounting_pending: false };
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.innerHTML = ''; });
async function setup(client: BrowseClient) {
  const target = document.createElement('div'); document.body.append(target);
  const instance = mount(BrowseSessionViewer, { target, props: { sessionId: session.session_id, client, onContinue: vi.fn() } });
  await tick();
  return { target, instance };
}
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)); await tick(); }

// contract-test: supporting surface=gui.web assertions=web-browse.private-storage-and-api,web-browse.embed-and-observation
it('aborts an unmounted viewer and discards a late private frame', async () => {
  const create = vi.fn(); vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() });
  let finish!: (value: Blob) => void;
  let frameSignal!: AbortSignal;
  const client: BrowseClient = { state: async () => session, control: vi.fn(), frame: async (_id, signal) => {
    frameSignal = signal; return new Promise(resolve => { finish = resolve; });
  } };
  const { instance } = await setup(client); await settle();
  expect(frameSignal.aborted).toBe(false);
  await unmount(instance);
  expect(frameSignal.aborted).toBe(true);
  finish(new Blob(['private-frame'])); await settle();
  expect(create).not.toHaveBeenCalled();
});

// contract-test: supporting surface=gui.web assertions=web-browse.exclusive-takeover,web-browse.private-storage-and-api,web-browse.budgets-and-stop
it('clears text immediately and never retries input after an uncertain transport failure', async () => {
  vi.stubGlobal('URL', { createObjectURL: () => 'blob:test', revokeObjectURL: vi.fn() });
  const control = vi.fn().mockRejectedValue(new Error('transport_failed'));
  const client: BrowseClient = { state: async () => session, frame: async () => new Blob(), control };
  const { target, instance } = await setup(client); await settle();
  const input = target.querySelector('input')!;
  input.value = 'private synthetic value'; input.dispatchEvent(new Event('input', { bubbles: true })); await tick();
  target.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await settle();
  expect(input.value).toBe('');
  expect(control).toHaveBeenCalledOnce();
  expect(control.mock.calls[0][1]).toEqual({ operation: 'input', action: { kind: 'type', text: 'private synthetic value' } });
  expect(target.textContent).not.toContain('private synthetic value');
  await unmount(instance);
});

// contract-test: supporting surface=gui.web assertions=web-browse.private-storage-and-api,web-browse.lifecycle
it('removes a live frame and disables further interaction when ownership is denied', async () => {
  const revoke = vi.fn(); vi.stubGlobal('URL', { createObjectURL: () => 'blob:private', revokeObjectURL: revoke });
  const client: BrowseClient = { state: async () => session, frame: async () => new Blob(),
    control: vi.fn().mockRejectedValue(new BrowseHttpError(403)) };
  const { target, instance } = await setup(client); await settle();
  expect(target.querySelector('img')?.src).toBe('blob:private');
  const close = Array.from(target.querySelectorAll('button')).find(button => button.textContent?.includes('Close browser'))!;
  close.click(); await settle();
  expect(revoke).toHaveBeenCalledWith('blob:private');
  expect(target.querySelector('img')).toBeNull();
  expect(target.querySelector('input')).toBeNull();
  expect(target.querySelectorAll('button')).toHaveLength(0);
  await unmount(instance);
});
