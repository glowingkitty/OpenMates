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
  onUntranscribedAudio: (audio: { blob: Blob; mimeType: string; failed: boolean }) => void;
  onSubmit: (text: string) => Promise<boolean>;
  onMicClick: () => void;
  onRecordingClose: () => void;
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
  it('discards late untranscribed audio after scope remount', async () => {
    let value = 'Old draft';
    let files: File[] = [];
    const component = mount(AppsRequestComposer, { target: document.createElement('div'), props: {
      appId: 'web', get value() { return value; }, set value(next) { value = next; },
      get files() { return files; }, set files(next) { files = next; }, onSubmit: async () => false,
    } });
    flushSync();
    const keep = probe.props.onUntranscribedAudio;
    await unmount(component);
    value = 'New owner draft';
    const newFile = new File(['new'], 'new.txt'); files = [newFile];
    keep({ blob: new Blob(['private audio']), mimeType: 'audio/webm', failed: true });
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
describe('Untranscribed recording', () => {
  it('keeps audio without a transcript as an attachment', () => {
    let value = 'Keep the mountain.';
    let files: File[] = [];
    const component = mount(AppsRequestComposer, { target: document.createElement('div'), props: {
      appId: 'images', presentation: 'embed',
      get value() { return value; }, set value(next) { value = next; },
      get files() { return files; }, set files(next) { files = next; }, onSubmit: vi.fn(async () => true),
    } });
    flushSync();
    probe.props.onMicClick();
    probe.props.onUntranscribedAudio({ blob: new Blob(['audio']), mimeType: 'audio/webm', failed: false });
    expect(value).toBe('Keep the mountain.');
    expect(files.map(file => [file.name, file.type])).toEqual([['recording.webm', 'audio/webm']]);
    void unmount(component);
  });
});
