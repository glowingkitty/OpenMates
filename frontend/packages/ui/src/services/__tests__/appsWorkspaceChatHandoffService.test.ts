import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('../../stores/authState', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'A' }) }));
vi.mock('../../stores/teamStore', async () => ({ activeTeamContext: (await import('svelte/store')).writable({ team: null, teamId: null as string | null, epoch: 0 }) }));
// Root startup must not enter chatSyncService through the full storage facade.
vi.mock('../anonymousChatStorage', () => { throw new Error('Handoff initialization must not load chat sync'); });
import { phasedSyncState, NEW_CHAT_SENTINEL } from '../../stores/phasedSyncStateStore';
import { get } from 'svelte/store';
import { createAppsWorkspaceHandoffNavigation } from '../appsWorkspaceHandoffNavigation.svelte';
import { authStore } from '../../stores/authState';
import { userProfile } from '../../stores/userProfile';
import { activeTeamContext } from '../../stores/teamStore';
import { queueAppsWorkspaceChatHandoff, takeAppsWorkspaceChatHandoff, deliverAppsWorkspaceChatHandoff,
  takeAppsWorkspaceComposerHandoff, isAppsWorkspaceHandoffCurrent, queueAppsWorkspaceWorkflowHandoff,
  takeAppsWorkspaceWorkflowHandoff, appsRequestContextDocument, appsRequestContextText, recordAppsWorkspaceHandoffPhase, submitAppsWorkspaceHandoffDraft, rememberAppsWorkspaceDraftUrls, restoredAppsWorkspaceDraftUrls, forgetAppsWorkspaceDraftUrls, captureAppsWorkspaceDraftUrlCleanup } from '../appsWorkspaceChatHandoffService';
beforeEach(() => { authStore.update(state => ({ ...state, isAuthenticated: true })); userProfile.update(profile => ({ ...profile, user_id: 'reset' })); userProfile.update(profile => ({ ...profile, user_id: 'A' })); activeTeamContext.set({ team: null, teamId: null, epoch: 0 }); });
describe('private Apps handoffs', () => {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('does not let late acceptance clear a newer handoff policy in the same chat and document', async () => {
    const first = { text: 'Explain' }, next = { text: 'Explain' };
    await queueAppsWorkspaceChatHandoff(first); takeAppsWorkspaceChatHandoff();
    rememberAppsWorkspaceDraftUrls(first, 'same-chat', 'same-document', new Set(['https://example.test/first']));
    const finishFirst = captureAppsWorkspaceDraftUrlCleanup('same-chat', 'same-document');
    await queueAppsWorkspaceChatHandoff(next); takeAppsWorkspaceChatHandoff();
    rememberAppsWorkspaceDraftUrls(next, 'same-chat', 'same-document', new Set(['https://example.test/next']));
    finishFirst();
    expect([...restoredAppsWorkspaceDraftUrls('same-chat', 'same-document')]).toEqual(['https://example.test/next']);
    captureAppsWorkspaceDraftUrlCleanup('same-chat', 'same-document')();
    expect(restoredAppsWorkspaceDraftUrls('same-chat', 'same-document').size).toBe(0);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('restores URL suppression only to the exact rejected draft and clears it at ownership boundaries', async () => {
    const request = { text: 'Explain result' };
    await queueAppsWorkspaceChatHandoff(request); takeAppsWorkspaceChatHandoff();
    const ignored = new Set(['https://example.test/practice']);
    rememberAppsWorkspaceDraftUrls(request, 'draft-owner', 'exact literal document', ignored);
    ignored.clear(); // The old editor optimistically clears before rejection.
    expect([...restoredAppsWorkspaceDraftUrls('draft-owner', 'exact literal document')]).toEqual(['https://example.test/practice']);
    expect(restoredAppsWorkspaceDraftUrls('other-chat', 'exact literal document').size).toBe(0);
    expect(restoredAppsWorkspaceDraftUrls('draft-owner', 'ordinary next request').size).toBe(0);
    forgetAppsWorkspaceDraftUrls(request);
    expect(restoredAppsWorkspaceDraftUrls('draft-owner', 'exact literal document').size).toBe(0);
    rememberAppsWorkspaceDraftUrls(request, 'draft-owner', 'exact literal document', new Set(['https://example.test']));
    activeTeamContext.set({ team: null, teamId: 'team-B', epoch: 1 });
    expect(restoredAppsWorkspaceDraftUrls('draft-owner', 'exact literal document').size).toBe(0);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('auto-sends accepted first turns without focus surviving a keyed editor replacement', async () => {
    for (const remounted of [false, true]) {
      const focus = vi.fn();
      let current = true;
      await submitAppsWorkspaceHandoffDraft({
        submit: async () => {
          expect(focus).not.toHaveBeenCalled();
          current = !remounted; // First-turn activation may replace its editor.
          return true;
        },
        isCurrent: () => current,
        focusRejectedDraft: focus,
      });
      expect(focus).not.toHaveBeenCalled();
    }
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('opens a rejected guest draft only after admission and keeps stale editors unfocused', async () => {
    const events: string[] = [];
    await submitAppsWorkspaceHandoffDraft({
      submit: async () => { events.push('budget-rejected'); return false; },
      isCurrent: () => true,
      focusRejectedDraft: () => { events.push('focus-draft'); },
    });
    expect(events).toEqual(['budget-rejected', 'focus-draft']);
    await submitAppsWorkspaceHandoffDraft({
      submit: async () => false,
      isCurrent: () => false, // Account/chat ownership changed during admission.
      focusRejectedDraft: () => { events.push('stale-focus'); },
    });
    expect(events).not.toContain('stale-focus');
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('claims the user chat destination before late startup sync can navigate', () => {
    for (const chatId of [undefined, 'source-chat']) {
      phasedSyncState.reset();
      expect(phasedSyncState.canAutoNavigate()).toBe(true);
      const navigation = createAppsWorkspaceHandoffNavigation();
      navigation.request = { text: 'Explain', context: chatId ? { chat_id: chatId } : undefined };
      expect(get(phasedSyncState).currentActiveChatId).toBe(chatId ?? NEW_CHAT_SENTINEL);
      expect(phasedSyncState.canAutoNavigate()).toBe(false);
      navigation.request = null;
      // Consuming the request and a late auth publication cannot revoke the
      // destination while its local user message waits for the socket.
      phasedSyncState.resetForLogin();
      expect(phasedSyncState.canAutoNavigate()).toBe(false);
      expect(phasedSyncState.shouldAutoSelectPhase1Chat('old-startup-chat')).toBe(false);
    }
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('preserves ownership and private object identity through reactive page navigation', async () => {
    for (const authenticated of [false, true]) {
      authStore.update(state => ({ ...state, isAuthenticated: authenticated }));
      const request = { text: 'Explain', context: { result: { children: [{ title: 'Private' }] } }, attachments: [new File(['x'], 'notes.txt')] };
      const navigation = createAppsWorkspaceHandoffNavigation();
      await queueAppsWorkspaceChatHandoff(request);
      navigation.request = takeAppsWorkspaceChatHandoff();
      const routedRequest = navigation.request!;
      navigation.request = null;
      // Deep reactive state would proxy this object and fail its WeakMap fence.
      expect(routedRequest).toBe(request);
      expect(routedRequest.context).toBe(request.context);
      expect(routedRequest.attachments).toBe(request.attachments);
      expect(isAppsWorkspaceHandoffCurrent(routedRequest)).toBe(true);
      deliverAppsWorkspaceChatHandoff(routedRequest, null);
      expect(takeAppsWorkspaceComposerHandoff('temporary', true)).toBe(request);
      expect(takeAppsWorkspaceComposerHandoff('temporary', true)).toBeNull();
    }
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('records bounded lifecycle phases without retaining private request data', async () => {
    const diagnostics = window as Window & { __openmatesAppsHandoffDebug?: string[] };
    diagnostics.__openmatesAppsHandoffDebug = [];
    const request = { text: 'private request', context: { result: { title: 'private result' } }, attachments: [new File(['private file'], 'private.txt')] };
    await queueAppsWorkspaceChatHandoff(request); takeAppsWorkspaceChatHandoff();
    deliverAppsWorkspaceChatHandoff(request, null);
    takeAppsWorkspaceComposerHandoff('temporary', true);
    expect(diagnostics.__openmatesAppsHandoffDebug).toEqual(['queued', 'navigation-taken', 'delivered', 'editor-claimed']);
    for (let i = 0; i < 30; i++) recordAppsWorkspaceHandoffPhase('send-finished');
    expect(diagnostics.__openmatesAppsHandoffDebug).toHaveLength(24);
    expect(JSON.stringify(diagnostics.__openmatesAppsHandoffDebug)).not.toContain('private');
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('initializes without chat sync and preserves the existing guest identity fence', async () => {
    authStore.update(state => ({ ...state, isAuthenticated: false }));
    localStorage.setItem('openmates_anonymous_id', 'guest-A');
    await queueAppsWorkspaceChatHandoff({ text: 'private guest request' });
    localStorage.setItem('openmates_anonymous_id', 'guest-B');
    expect(takeAppsWorkspaceChatHandoff()).toBeNull();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('retains files and children until the exact ready chat claims the delivery once', async () => {
    const request = { text: 'Explain', context: { chat_id: 'source', result: { children: [{ title: 'Secret' }] } }, attachments: [new File(['x'], 'notes.txt')] };
    const hash = window.location.hash;
    await queueAppsWorkspaceChatHandoff(request);
    expect(takeAppsWorkspaceChatHandoff()).toBe(request); expect(takeAppsWorkspaceChatHandoff()).toBeNull();
    deliverAppsWorkspaceChatHandoff(request, 'source');
    expect(takeAppsWorkspaceComposerHandoff('other', false)).toBeNull();
    expect(takeAppsWorkspaceComposerHandoff('source', false)).toBe(request);
    expect(takeAppsWorkspaceComposerHandoff('source', false)).toBeNull();
    expect(window.location.hash).toBe(hash);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('only allows a reset new-chat editor to consume a new-chat request', async () => {
    const request = { text: 'Explain' }; await queueAppsWorkspaceChatHandoff(request); takeAppsWorkspaceChatHandoff();
    deliverAppsWorkspaceChatHandoff(request, null);
    expect(takeAppsWorkspaceComposerHandoff('old', false)).toBeNull();
    // Mounting the welcome editor precedes asynchronous temporary-ID setup.
    // The incomplete editor must not consume and lose the request on remount.
    expect(takeAppsWorkspaceComposerHandoff(undefined, true)).toBeNull();
    expect(takeAppsWorkspaceComposerHandoff('temporary', true)).toBe(request);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('discards private pending and already-taken data after account A to B to A', async () => {
    const request = { text: 'private' }; await queueAppsWorkspaceChatHandoff(request); takeAppsWorkspaceChatHandoff();
    userProfile.update(profile => ({ ...profile, user_id: 'B' })); userProfile.update(profile => ({ ...profile, user_id: 'A' }));
    expect(isAppsWorkspaceHandoffCurrent(request)).toBe(false);
    deliverAppsWorkspaceChatHandoff(request, null);
    expect(takeAppsWorkspaceComposerHandoff(undefined, true)).toBeNull();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('fences workflow requests on Team switches and consumes current ones once', async () => {
    await queueAppsWorkspaceWorkflowHandoff({ text: 'private workflow' }); activeTeamContext.set({ team: null, teamId: 'team-B', epoch: 1 });
    expect(takeAppsWorkspaceWorkflowHandoff()).toBeNull();
    const request = { text: 'new workflow' }; await queueAppsWorkspaceWorkflowHandoff(request);
    expect(takeAppsWorkspaceWorkflowHandoff()).toBe(request); expect(takeAppsWorkspaceWorkflowHandoff()).toBeNull();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('keeps complete visible result data but excludes decryption/upload secrets from model-visible context', () => {
    const request = { text: 'explain', context: { input: { requests: [{ filename: 'voice.webm', aes_key: 'secret', aes_nonce: 'nonce', vault_wrapped_aes_key: 'wrapped' }] }, result: { children: [{ transcript: 'Meeting at nine' }] } } };
    const text = appsRequestContextText(request);
    expect(text).toContain('Meeting at nine'); expect(text).toContain('voice.webm');
    expect(text).not.toContain('secret'); expect(text).not.toContain('wrapped'); expect(text).not.toContain('nonce');
    expect(request.context.input.requests[0].aes_key).toBe('secret');
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('constructs literal text nodes for arbitrary HTML in the request and result data', () => {
    const html = '<img src=x onerror=alert(1)>';
    const doc = appsRequestContextDocument({ text: html, context: { result: { title: html } } });
    expect(doc.content[0]).toEqual({ type: 'paragraph', content: [{ type: 'text', text: html }] });
    expect(JSON.stringify(doc)).not.toContain('"type":"image"');
    expect(JSON.stringify(doc)).toContain('onerror=alert(1)');
  });
});
