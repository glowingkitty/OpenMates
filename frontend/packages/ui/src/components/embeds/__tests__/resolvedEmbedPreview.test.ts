// contract-test-file: infrastructure
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';
import Harness from './ResolvedEmbedPreviewHarness.svelte';

let instance: ReturnType<typeof mount> | undefined;
afterEach(async () => {
  if (instance) await unmount(instance);
  instance = undefined;
  document.body.replaceChildren();
});

describe('resolved preview presentation provider', () => {
  it('forwards flat props and callbacks without leaking routing controls or adding DOM wrappers', async () => {
    const payload = Object.freeze({ id: 'original-payload' });
    const onSelect = vi.fn();
    const onPreviewMount = vi.fn();
    instance = mount(Harness, { target: document.body, props: { initialPayload: payload, onSelect, onPreviewMount } });
    await tick();
    const button = document.querySelector<HTMLButtonElement>('[data-testid="resolved-preview-probe"]')!;
    expect(document.body.children.length).toBe(1);
    expect(document.body.firstElementChild).toBe(button);
    expect(button.textContent).toBe('Execution result');
    expect(button.dataset.presentation).toBe('execution');
    expect(button.dataset.marker).toBe('forwarded-flat-prop');
    expect(button.dataset.controlProps).toBe('');
    button.click();
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(payload);
    expect(onSelect.mock.calls[0][0]).toBe(payload);
    expect(onPreviewMount).toHaveBeenCalledTimes(1);
  });

  it('updates execution to content context and flat props while preserving the mounted child', async () => {
    const onPreviewMount = vi.fn();
    const onSelect = vi.fn();
    instance = mount(Harness, { target: document.body, props: { initialPayload: { id: 'execution' }, onSelect, onPreviewMount } });
    await tick();
    const before = document.querySelector<HTMLButtonElement>('[data-testid="resolved-preview-probe"]')!;
    expect(before.dataset.presentation).toBe('execution');
    const payload = Object.freeze({ id: 'content-output' });
    instance.navigate({ presentation: 'content', title: 'Updated content output', payload });
    await tick();
    const after = document.querySelector<HTMLButtonElement>('[data-testid="resolved-preview-probe"]')!;
    expect(after).toBe(before);
    expect(onPreviewMount).toHaveBeenCalledTimes(1);
    expect(after.dataset.presentation).toBe('content');
    expect(after.dataset.payloadId).toBe('content-output');
    expect(after.textContent).toBe('Updated content output');
    after.click();
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(payload);
    expect(onSelect.mock.calls[0][0]).toBe(payload);
  });
});
