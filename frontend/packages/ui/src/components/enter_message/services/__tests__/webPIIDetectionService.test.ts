import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { detectPIIForWeb, isWebPIIModelEnabled, preloadWebPIIDetector, resetWebPIIDetector, webPIIDetectorState } from '../webPIIDetectionService';
import * as basicDetector from '../piiDetectionService';

class FakeWorker {
  static workers: FakeWorker[] = [];
  onmessage?: (event: { data: unknown }) => void;
  onerror?: () => void;
  onmessageerror?: () => void;
  messages: Array<{ id: number; kind: string; text?: string }> = [];
  terminated = false;
  constructor() { FakeWorker.workers.push(this); }
  postMessage(message: { id: number; kind: string; text?: string }) { this.messages.push(message); }
  terminate() { this.terminated = true; }
  respond(index: number, extra = {}) { this.onmessage?.({ data: { id: this.messages[index].id, items: [], ...extra } }); }
}
const tick = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

beforeEach(() => {
  vi.stubEnv('VITE_ENV', 'development');
  vi.stubGlobal('Worker', FakeWorker);
  FakeWorker.workers = [];
  resetWebPIIDetector();
});
afterEach(() => { resetWebPIIDetector(); vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe('dev browser PII runtime lifecycle', () => {
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('uses the exact host and environment gate and never starts a production worker', async () => {
    expect(isWebPIIModelEnabled()).toBe(true); // jsdom localhost
    for (const [hostname, enabled] of [['app.dev.openmates.org', true], ['localhost', true], ['127.0.0.1', true], ['openmates.org', false], ['app.openmates.org', false], ['app.dev.openmates.org.evil.example', false], ['preview.openmates.org', false]] as const) {
      vi.stubGlobal('window', { location: { hostname } });
      expect(isWebPIIModelEnabled()).toBe(enabled);
    }
    vi.stubGlobal('window', { location: { hostname: 'app.dev.openmates.org' } });
    vi.stubEnv('VITE_ENV', 'production');
    expect(isWebPIIModelEnabled()).toBe(false);
    await preloadWebPIIDetector();
    expect(FakeWorker.workers).toHaveLength(0);
    expect((await detectPIIForWeb('anna@example.com'))[0].type).toBe('EMAIL');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('returns full basic protection for every queued send on model error until explicit reset', async () => {
    const firstText = 'anna@example.com +1 202-555-0183';
    const secondText = 'Amina uses 192.0.2.42';
    const options = { disabledCategories: new Set(['phone_numbers']), personalDataEntries: [{ id: 'name', textToHide: 'Amina', replaceWith: 'MY_NAME' }] };
    const first = detectPIIForWeb(firstText, options);
    const second = detectPIIForWeb(secondText, options);
    const firstBasic = basicDetector.detectPII(firstText, options);
    const secondBasic = basicDetector.detectPII(secondText, options);
    options.disabledCategories.clear();
    options.personalDataEntries[0].replaceWith = 'CHANGED_AFTER_ENQUEUE';
    FakeWorker.workers[0].respond(0, { error: true });
    await expect(first).resolves.toEqual(firstBasic);
    await expect(second).resolves.toEqual(secondBasic);
    expect(get(webPIIDetectorState).status).toBe('error');
    await expect(detectPIIForWeb(firstText)).resolves.toEqual(basicDetector.detectPII(firstText));
    expect(FakeWorker.workers).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('keeps regex exclusions in the fallback after inference failure', async () => {
    const text = 'anna@example.com and bob@example.com';
    const excludedIds = new Set([basicDetector.detectPII(text)[0].id]);
    const options = { excludedIds };
    const scan = detectPIIForWeb(text, options);
    const expected = basicDetector.detectPII(text, options).filter(match => match.type === 'EMAIL');
    excludedIds.clear();
    const worker = FakeWorker.workers[0];
    worker.respond(0); await tick();
    worker.respond(1, { error: true });
    await expect(scan).resolves.toEqual(expected);
    expect(get(webPIIDetectorState).status).toBe('error');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('falls back on malformed model offsets and preserves the enhanced error state', async () => {
    const text = 'Amina anna@example.com';
    const scan = detectPIIForWeb(text);
    const worker = FakeWorker.workers[0];
    worker.respond(0); await tick();
    worker.respond(1, { items: [{ label: 'GIVEN_NAME', original: 'Amina', start: 1, end: 6, confidence: 1 }] });
    await expect(scan).resolves.toEqual(basicDetector.detectPII(text));
    expect(get(webPIIDetectorState).status).toBe('error');
    expect(worker.terminated).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('propagates a genuine basic detector failure before starting model work', async () => {
    vi.spyOn(basicDetector, 'detectPII').mockImplementationOnce(() => { throw new Error('basic detector unavailable'); });
    await expect(detectPIIForWeb('anna@example.com')).rejects.toThrow('basic detector unavailable');
    expect(FakeWorker.workers).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('reset during load cannot publish stale ready/error or send old text to a new worker', async () => {
    const stale = detectPIIForWeb('old text');
    const rejected = expect(stale).rejects.toThrow('reset');
    const old = FakeWorker.workers[0];
    resetWebPIIDetector();
    const loading = preloadWebPIIDetector();
    const current = FakeWorker.workers[1];
    old.respond(0); old.onerror?.();
    await rejected; await tick();
    expect(get(webPIIDetectorState).status).toBe('loading');
    expect(current.terminated).toBe(false);
    expect(current.messages.map(m => m.kind)).toEqual(['load']);
    current.respond(0); await loading;
    expect(get(webPIIDetectorState).status).toBe('ready');
    expect(current.messages).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('rejects inference cancelled by reset instead of returning captured basic matches', async () => {
    const scan = detectPIIForWeb('anna@example.com');
    const rejected = expect(scan).rejects.toThrow('reset');
    const worker = FakeWorker.workers[0];
    worker.respond(0); await tick();
    resetWebPIIDetector();
    worker.respond(1, { error: true });
    await rejected;
    expect(get(webPIIDetectorState).status).toBe('disabled');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('coalesces queued previews while preserving every send and snapshots options', async () => {
    const active = detectPIIForWeb('Amina', {}, { purpose: 'preview' });
    const superseded = detectPIIForWeb('old preview', {}, { purpose: 'preview' });
    const disabledCategories = new Set(['names']);
    const send = detectPIIForWeb('Amina', { disabledCategories });
    const latest = detectPIIForWeb('new preview', {}, { purpose: 'preview' });
    disabledCategories.clear();
    await expect(superseded).resolves.toEqual([]);
    const worker = FakeWorker.workers[0];
    worker.respond(0); await tick();
    const name = [{ label: 'GIVEN_NAME', original: 'Amina', start: 0, end: 5, confidence: 1 }];
    worker.respond(1, { items: name }); await active; await tick();
    worker.respond(2, { items: name }); await expect(send).resolves.toEqual([]); await tick();
    worker.respond(3); await latest;
    expect(worker.messages.map(m => m.text).filter(Boolean)).toEqual(['Amina', 'Amina', 'new preview']);
  });
});
