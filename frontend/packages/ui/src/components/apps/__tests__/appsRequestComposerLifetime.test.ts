/**
 * Protect drafts shared through bindable Apps composer props.
 * Async audio and submission callbacks can outlive a keyed account/Team reset.
 * Exercise the actual component with a lightweight composer child so no audio
 * device, provider call, or product runtime is needed.
 */
import { describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AppsRequestComposer from '../AppsRequestComposer.svelte';

const probe = vi.hoisted(() => ({ props: {} as {
  onAudioRecorded: (event: CustomEvent) => Promise<void>;
  onSubmit: (text: string) => Promise<boolean>;
  onMicClick: () => void;
  onRecordingClose: () => void;
  recordingSendAction?: { onRequest: () => void };
} }));
vi.mock('../../workspace/WorkspacePromptComposer.svelte', () => ({
  default: (_anchor: unknown, props: typeof probe.props) => { probe.props = props; },
}));
vi.mock('../../../i18n/translations', async () => ({
  text: (await import('svelte/store')).writable((key: string) => key),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// contract-test: supporting surface=gui.web assertions=apps.requests.natural-language
describe('Apps composer lifetime', () => {
  it.each(['success', 'failure'] as const)('discards late audio %s after scope remount', async outcome => {
    const correction = deferred<{ transcript: string }>();
    const transcription = deferred<{ transcript: string }>();
    let value = 'Old draft';
    let files: File[] = [];
    const component = mount(AppsRequestComposer, { target: document.createElement('div'), props: {
      appId: 'web', get value() { return value; }, set value(next) { value = next; },
      get files() { return files; }, set files(next) { files = next; }, onSubmit: async () => false,
    } });
    flushSync();
    const pending = probe.props.onAudioRecorded(new CustomEvent('audioRecorded', { detail: {
      blob: new Blob(['private audio']), mimeType: 'audio/webm',
      realtime: { finish: vi.fn(), correction: correction.promise, transcription: transcription.promise },
    } }));
    await unmount(component);
    value = 'New owner draft';
    const newFile = new File(['new'], 'new.txt'); files = [newFile];
    if (outcome === 'success') correction.resolve({ transcript: 'Old private transcript' });
    else { correction.reject(new Error('correction failed')); transcription.reject(new Error('transcription failed')); }
    await pending;
    expect(value).toBe('New owner draft');
    expect(files).toEqual([newFile]);
  });

  // contract-test: supporting surface=gui.web assertions=apps.requests.natural-language
  it('does not clear a new owner draft after a late accepted submission', async () => {
    const accepted = deferred<boolean>();
    let value = 'Old draft';
    let files: File[] = [];
    const component = mount(AppsRequestComposer, { target: document.createElement('div'), props: {
      appId: 'web', get value() { return value; }, set value(next) { value = next; },
      get files() { return files; }, set files(next) { files = next; }, onSubmit: () => accepted.promise,
    } });
    flushSync();
    const pending = probe.props.onSubmit('Old draft');
    await unmount(component);
    value = 'New owner draft';
    const newFile = new File(['new'], 'new.txt'); files = [newFile];
    accepted.resolve(true);
    expect(await pending).toBe(false);
    expect(value).toBe('New owner draft');
    expect(files).toEqual([newFile]);
  });
});

// contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript,apps.results.shared-fullscreen
describe('Fullscreen recording Send', () => {
  it.each([true, false])('waits for correction and preserves the draft when accepted=%s', async accepted => {
    const correction = deferred<{ transcript: string }>();
    let value = 'Keep the mountain.';
    const attachment = new File(['notes'], 'notes.txt');
    let files = [attachment];
    const onSubmit = vi.fn(async () => accepted);
    const component = mount(AppsRequestComposer, { target: document.createElement('div'), props: {
      appId: 'images', presentation: 'embed',
      get value() { return value; }, set value(next) { value = next; },
      get files() { return files; }, set files(next) { files = next; }, onSubmit,
    } });
    flushSync();
    probe.props.onMicClick();
    probe.props.recordingSendAction!.onRequest();
    const pending = probe.props.onAudioRecorded(new CustomEvent('audiorecorded', { detail: {
      blob: new Blob(['audio']), mimeType: 'audio/webm',
      realtime: { finish: vi.fn(), correction: correction.promise, transcription: Promise.resolve({ transcript: 'raw words' }) },
    } }));
    // RecordAudio closes immediately after handing the audio to its owner.
    probe.props.onRecordingClose();
    expect(onSubmit).not.toHaveBeenCalled();
    correction.resolve({ transcript: 'Make the sky brighter.' });
    await pending;
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith('Keep the mountain.\nMake the sky brighter.', [attachment]);
    expect(value).toBe(accepted ? '' : 'Keep the mountain.\nMake the sky brighter.');
    expect(files).toEqual(accepted ? [] : [attachment]);
    await unmount(component);
  });
});
