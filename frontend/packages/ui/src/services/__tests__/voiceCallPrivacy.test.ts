import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
vi.mock('../../config/api', () => ({ getApiUrl: () => 'https://first-party.invalid' }));
vi.mock('../../i18n/translations', async () => { const { readable } = await import('svelte/store'); return { text: readable((key: string) => key) }; });
import { notificationStore } from '../../stores/notificationStore';
import { ensureVoiceCallPrivacyAcknowledgement } from '../voiceCallPrivacy';
const absent = { version: 1, acknowledged: false, acknowledged_at: null };
const saved = { version: 1, acknowledged: true, acknowledged_at: 1700000000 };
const response = (value: unknown, ok = true) => ({ ok, json: async () => value });
const notice = () => get(notificationStore).notifications.find(item => item.dedupeKey === 'voice-call-privacy' && !item.isExiting)!;
const opened = async () => { await vi.waitFor(() => expect(notice()).toBeDefined()); return notice(); };

describe('first-call server-profile acknowledgement through shared notifications', () => {
  let fetcher: ReturnType<typeof vi.fn>;
  beforeEach(() => { notificationStore.clearAllNotifications(); fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher); });
  afterEach(() => { notificationStore.clearAllNotifications(); vi.unstubAllGlobals(); });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('checks the authoritative profile across launches without repeating a saved warning', async () => {
    fetcher.mockResolvedValue(response(saved));
    for (let launch = 0; launch < 2; launch++) expect(await ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal, () => {})).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.every(call => call[1].method === 'GET' && call[1].credentials === 'include')).toBe(true);
    expect(notice()).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('shows the existing persistent notification with terms and does not save on Cancel', async () => {
    fetcher.mockResolvedValueOnce(response(absent));
    const gesture = vi.fn();
    const pending = ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal, gesture);
    const current = await opened();
    expect(current).toMatchObject({ type: 'info', title: 'voicecall.privacy_title', message: 'voicecall.privacy_description', duration: 0,
      keepOnAction: true, messageLink: { href: 'https://ai.google.dev/gemini-api/terms#paid-services', label: 'voicecall.privacy_terms' } });
    expect(fetcher).toHaveBeenCalledOnce(); expect(gesture).not.toHaveBeenCalled();
    current.onSecondaryAction!(); expect(await pending).toBe(false);
    expect(fetcher.mock.calls.some(call => call[1].method === 'POST')).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('saves only Continue and resumes after persistence, keeping actions disabled while saving', async () => {
    let complete!: (result: unknown) => void;
    fetcher.mockResolvedValueOnce(response(absent)).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    const gesture = vi.fn(); let resumed = false;
    const pending = ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal, gesture).then(value => { resumed = value; return value; });
    const current = await opened(); const saving = current.onAction!();
    expect(gesture).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[1]).toEqual(['https://first-party.invalid/v1/settings/voice-google-processing-ack', expect.objectContaining({ method: 'POST', credentials: 'include', body: '{"version":1}' })]);
    expect(notice()).toMatchObject({ isProcessing: true, actionsDisabled: true }); expect(resumed).toBe(false);
    await current.onAction!(); expect(fetcher).toHaveBeenCalledTimes(2);
    complete(response(saved)); await saving; expect(await pending).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('keeps a failed save blocked and allows an explicit retry', async () => {
    fetcher.mockResolvedValueOnce(response(absent)).mockResolvedValueOnce(response({}, false)).mockResolvedValueOnce(response(saved));
    let settled = false;
    const pending = ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal, () => {}).then(value => { settled = true; return value; });
    await (await opened()).onAction!();
    expect(settled).toBe(false);
    expect(notice()).toMatchObject({ messageSecondary: 'voicecall.privacy_save_failed', actionsDisabled: false, isProcessing: false });
    await notice().onAction!(); expect(await pending).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it.each(['dismiss', 'clear', 'abort'])('cancels on %s and ignores a late Continue', async action => {
    fetcher.mockResolvedValueOnce(response(absent));
    const abort = new AbortController(); const gesture = vi.fn();
    const pending = ensureVoiceCallPrivacyAcknowledgement(abort.signal, gesture);
    const current = await opened();
    if (action === 'abort') abort.abort();
    else if (action === 'clear') notificationStore.clearAllNotifications();
    else notificationStore.removeNotification(current.id);
    expect(await pending).toBe(false); await current.onAction!();
    expect(fetcher).toHaveBeenCalledOnce(); expect(gesture).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it.each(['dismiss', 'abort'])('ignores a late successful POST after %s during saving', async action => {
    let complete!: (result: unknown) => void;
    fetcher.mockResolvedValueOnce(response(absent)).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    const abort = new AbortController(); const accepted = vi.fn();
    const pending = ensureVoiceCallPrivacyAcknowledgement(abort.signal, () => {}).then(value => { if (value) accepted(); return value; });
    const current = await opened(); const saving = current.onAction!();
    expect(fetcher).toHaveBeenCalledTimes(2);
    if (action === 'abort') abort.abort(); else notificationStore.removeNotification(current.id);
    expect(await pending).toBe(false);
    complete(response(saved)); await saving;
    expect(accepted).not.toHaveBeenCalled(); expect(notice()).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('does not create a second prompt or profile request during an overlapping launch', async () => {
    fetcher.mockResolvedValueOnce(response(absent));
    const pending = ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal, () => {});
    const current = await opened();
    expect(await ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal, () => {})).toBe(false);
    expect(fetcher).toHaveBeenCalledOnce(); expect(get(notificationStore).notifications).toHaveLength(1);
    current.onSecondaryAction!(); expect(await pending).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('rejects unavailable or malformed server acknowledgement instead of a local bypass', async () => {
    for (const value of [response({}, false), response({ ...saved, version: 2 }), response({ ...saved, acknowledged_at: null })]) {
      fetcher.mockResolvedValueOnce(value);
      await expect(ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal, () => {})).rejects.toThrow();
    }
    expect(notice()).toBeUndefined();
  });
});
