import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createWebPIIScanContext, WEB_PII_MAX_ENHANCED_CHARS, WEB_PII_SCAN_BUDGET_MS, detectPIIForWeb, isWebPIIModelSupported, isWebPIIModelEnabled, preloadWebPIIDetector, resetWebPIIDetector, webPIIDetectorState } from '../webPIIDetectionService';
import * as basicDetector from '../piiDetectionService';

const preferences = vi.hoisted(() => ({
  set: (_value: { masterEnabled: boolean; enhancedEnabled: boolean; categories?: Record<string, boolean> }) => {},
  ready: (_value: boolean) => {},
}));
const network = vi.hoisted(() => ({
  initialize: vi.fn(async () => {}), dispose: vi.fn(),
  onViolation: undefined as (() => void) | undefined,
}));
vi.mock('../../../../stores/personalDataStore', async () => {
  const { writable } = await import('svelte/store');
  const settings = writable({ masterEnabled: true, enhancedEnabled: true, categories: {} });
  const enhancementReady = writable(true);
  preferences.set = value => settings.set({ ...value, categories: value.categories ?? {} });
  preferences.ready = value => enhancementReady.set(value);
  return { personalDataStore: { settings, enhancementReady } };
});
vi.mock('../webPIINetworkBroker', () => ({ createWebPIINetworkBroker: (_worker: unknown, options: { onViolation: () => void }) => {
  network.onViolation = options.onViolation;
  return { initialize: network.initialize, dispose: network.dispose, handleMessage: () => false };
} }));

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
  preferences.set({ masterEnabled: true, enhancedEnabled: true });
  preferences.ready(true);
  network.initialize.mockResolvedValue(undefined);
  network.dispose.mockClear();
});
afterEach(() => { resetWebPIIDetector(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe('browser PII runtime lifecycle', () => {
  // contract-test: supporting surface=gui.web assertions=pii.web.enhanced-default-and-opt-out
  it('keeps full basic options without creating a worker when opted out or preferences have not hydrated', async () => {
    const text = 'Amina anna@example.com +1 202-555-0183';
    const options = { personalDataEntries: [{ id: 'name', textToHide: 'Amina', replaceWith: 'MY_NAME' }], disabledCategories: new Set(['phone_numbers']) };
    preferences.set({ masterEnabled: true, enhancedEnabled: false });
    expect(isWebPIIModelSupported()).toBe(true);
    expect(isWebPIIModelEnabled()).toBe(false);
    await preloadWebPIIDetector();
    await expect(detectPIIForWeb(text, options)).resolves.toEqual(basicDetector.detectPII(text, options));
    preferences.set({ masterEnabled: true, enhancedEnabled: true });
    preferences.ready(false);
    const captured = createWebPIIScanContext();
    await preloadWebPIIDetector();
    preferences.ready(true);
    await expect(detectPIIForWeb(text, options, captured)).resolves.toEqual(basicDetector.detectPII(text, options));
    expect(FakeWorker.workers).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.licensing-egress-boundary
  it('terminates and disposes active inference immediately on opt-out and rejects obsolete results', async () => {
    const scan = detectPIIForWeb('anna@example.com');
    const rejected = expect(scan).rejects.toThrow('reset');
    const active = FakeWorker.workers[0];
    await tick(); active.respond(0); await tick();
    preferences.set({ masterEnabled: true, enhancedEnabled: false });
    await rejected;
    expect(active.terminated).toBe(true);
    expect(network.dispose).toHaveBeenCalled();
    active.respond(1, { items: [{ label: 'EMAIL', original: 'anna@example.com', start: 0, end: 16, confidence: 1 }] });
    await expect(detectPIIForWeb('anna@example.com')).resolves.toEqual(basicDetector.detectPII('anna@example.com'));
    expect(FakeWorker.workers).toHaveLength(1);
    expect(get(webPIIDetectorState).status).toBe('disabled');
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('falls back immediately on a broker policy violation even when SDK licensing would ignore it', async () => {
    const scan = detectPIIForWeb('anna@example.com');
    await tick();
    network.onViolation!();
    await expect(scan).resolves.toEqual(basicDetector.detectPII('anna@example.com'));
    expect(FakeWorker.workers[0].terminated).toBe(true);
    expect(get(webPIIDetectorState).status).toBe('error');
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.licensing-egress-boundary
  it('cannot post a load after opt-out interrupts broker initialization', async () => {
    let initialized!: () => void;
    network.initialize.mockReturnValueOnce(new Promise<void>(resolve => { initialized = resolve; }));
    const loading = preloadWebPIIDetector();
    const rejected = expect(loading).rejects.toThrow('reset');
    const original = FakeWorker.workers[0];
    preferences.set({ masterEnabled: true, enhancedEnabled: false });
    initialized();
    await rejected; await tick();
    expect(original.messages).toEqual([]);
    expect(original.terminated).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('enables official production hosts by default and rejects lookalike hosts', async () => {
    expect(isWebPIIModelEnabled()).toBe(true); // jsdom localhost
    for (const [hostname, enabled] of [['app.dev.openmates.org', true], ['localhost', true], ['127.0.0.1', true], ['openmates.org', true], ['app.openmates.org', true], ['app.dev.openmates.org.evil.example', false], ['preview.openmates.org', false]] as const) {
      vi.stubGlobal('window', { location: { hostname } });
      expect(isWebPIIModelSupported()).toBe(enabled);
      expect(isWebPIIModelEnabled()).toBe(enabled);
    }
    vi.stubGlobal('window', { location: { hostname: 'app.openmates.org' } });
    vi.stubEnv('VITE_ENV', 'production');
    expect(isWebPIIModelEnabled()).toBe(true);
    const loading = preloadWebPIIDetector();
    await tick();
    expect(FakeWorker.workers).toHaveLength(1);
    FakeWorker.workers[0].respond(0);
    await loading;
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
    await tick(); FakeWorker.workers[0].respond(0, { error: true });
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
    await tick(); worker.respond(0); await tick();
    worker.respond(1, { error: true });
    await expect(scan).resolves.toEqual(expected);
    expect(get(webPIIDetectorState).status).toBe('error');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('falls back on malformed model offsets and preserves the enhanced error state', async () => {
    const text = 'Amina anna@example.com';
    const scan = detectPIIForWeb(text);
    const worker = FakeWorker.workers[0];
    await tick(); worker.respond(0); await tick();
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
    await tick();
    resetWebPIIDetector();
    const loading = preloadWebPIIDetector();
    const current = FakeWorker.workers[1];
    old.respond(0); old.onerror?.();
    await rejected; await tick();
    expect(get(webPIIDetectorState).status).toBe('loading');
    expect(current.terminated).toBe(false);
    expect(current.messages.map(m => m.kind)).toEqual(['load']);
    await tick(); current.respond(0); await loading;
    expect(get(webPIIDetectorState).status).toBe('ready');
    expect(current.messages).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('rejects inference cancelled by reset instead of returning captured basic matches', async () => {
    const scan = detectPIIForWeb('anna@example.com');
    const rejected = expect(scan).rejects.toThrow('reset');
    const worker = FakeWorker.workers[0];
    await tick(); worker.respond(0); await tick();
    resetWebPIIDetector();
    worker.respond(1, { error: true });
    await rejected;
    expect(get(webPIIDetectorState).status).toBe('disabled');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('coalesces queued previews while preserving every send and snapshots options', async () => {
    const loading = preloadWebPIIDetector();
    const worker = FakeWorker.workers[0];
    await tick(); worker.respond(0); await loading;
    const active = detectPIIForWeb('Amina', {}, { purpose: 'preview' });
    await tick();
    const superseded = detectPIIForWeb('old preview', {}, { purpose: 'preview' });
    const disabledCategories = new Set(['names']);
    const send = detectPIIForWeb('Amina', { disabledCategories });
    const latest = detectPIIForWeb('new preview', {}, { purpose: 'preview' });
    disabledCategories.clear();
    await expect(superseded).resolves.toEqual([]);
    const name = [{ label: 'GIVEN_NAME', original: 'Amina', start: 0, end: 5, confidence: 1 }];
    worker.respond(1, { items: name }); await active; await tick();
    worker.respond(2, { items: name }); await expect(send).resolves.toEqual([]); await tick();
    worker.respond(3); await latest;
    expect(worker.messages.map(m => m.text).filter(Boolean)).toEqual(['Amina', 'Amina', 'new preview']);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('bypasses enhancement for large pastes without posting text and preserves all basic options', async () => {
    const text = `Amina anna@example.com bob@example.com +1 202-555-0183 ${'x'.repeat(WEB_PII_MAX_ENHANCED_CHARS)}`;
    const options = {
      personalDataEntries: [{ id: 'name', textToHide: 'Amina', replaceWith: 'MY_NAME' }],
      disabledCategories: new Set(['phone_numbers']),
      excludedIds: new Set([basicDetector.detectPII(text).find(match => match.match === 'bob@example.com')!.id]),
    };
    await expect(detectPIIForWeb(text, options)).resolves.toEqual(basicDetector.detectPII(text, options).filter(match => match.match !== 'bob@example.com'));
    expect(FakeWorker.workers).toHaveLength(0);
    expect(get(webPIIDetectorState).fallbackReason).toBe('size');
    const loading = preloadWebPIIDetector();
    const worker = FakeWorker.workers[0];
    await tick(); worker.respond(0); await loading;
    await detectPIIForWeb(text, options);
    expect(worker.messages.map(message => message.kind)).toEqual(['load']);
    expect(worker.terminated).toBe(false);
    expect(get(webPIIDetectorState).status).toBe('ready');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('bounds queue and first-load waits while allowing background loading to finish', async () => {
    vi.useFakeTimers();
    const first = detectPIIForWeb('anna@example.com');
    const queued = detectPIIForWeb('bob@example.com');
    const worker = FakeWorker.workers[0];
    await vi.advanceTimersByTimeAsync(WEB_PII_SCAN_BUDGET_MS);
    await expect(first).resolves.toEqual(basicDetector.detectPII('anna@example.com'));
    await expect(queued).resolves.toEqual(basicDetector.detectPII('bob@example.com'));
    expect(worker.terminated).toBe(false);
    expect(get(webPIIDetectorState).fallbackReason).toBe('timeout');
    await tick(); worker.respond(0); await tick();
    expect(get(webPIIDetectorState).status).toBe('ready');
    expect(worker.messages.map(message => message.kind)).toEqual(['load']);
    const recovered = detectPIIForWeb('Amina'); await tick();
    worker.respond(1, { items: [{ label: 'GIVEN_NAME', original: 'Amina', start: 0, end: 5, confidence: 1 }] });
    expect((await recovered)[0].match).toBe('Amina');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('releases hung inference at the shared send deadline and ignores late results until retry', async () => {
    vi.useFakeTimers();
    const context = createWebPIIScanContext();
    await vi.advanceTimersByTimeAsync(10_000);
    const first = detectPIIForWeb('Amina', {}, context);
    const worker = FakeWorker.workers[0];
    await tick(); worker.respond(0); await tick();
    await vi.advanceTimersByTimeAsync(1_500);
    worker.respond(1); await first;
    const second = detectPIIForWeb('anna@example.com', {}, context); await tick();
    await vi.advanceTimersByTimeAsync(999);
    expect(worker.terminated).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(second).resolves.toEqual(basicDetector.detectPII('anna@example.com'));
    expect(worker.terminated).toBe(true);
    worker.respond(2); worker.onmessage?.({ data: { kind: 'progress', progress: 0.8 } });
    expect(get(webPIIDetectorState).status).toBe('error');
    await detectPIIForWeb('next');
    expect(FakeWorker.workers).toHaveLength(1);
    resetWebPIIDetector();
    const retry = detectPIIForWeb('new');
    const current = FakeWorker.workers[1];
    worker.respond(2); worker.onerror?.();
    await tick(); current.respond(0); await tick(); current.respond(1); await retry;
    expect(get(webPIIDetectorState).status).toBe('ready');
    expect(current.terminated).toBe(false);
  });


  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('uses basic protection for later fields after the shared budget expires without restarting a healthy worker', async () => {
    vi.useFakeTimers();
    const context = createWebPIIScanContext();
    const first = detectPIIForWeb('Amina', {}, context);
    const worker = FakeWorker.workers[0];
    await tick(); worker.respond(0); await tick(); worker.respond(1); await first;
    await vi.advanceTimersByTimeAsync(WEB_PII_SCAN_BUDGET_MS);
    await expect(detectPIIForWeb('anna@example.com', {}, context)).resolves.toEqual(basicDetector.detectPII('anna@example.com'));
    expect(worker.messages.map(message => message.kind)).toEqual(['load', 'scan']);
    expect(worker.terminated).toBe(false);
    expect(get(webPIIDetectorState)).toMatchObject({ status: 'ready', fallbackReason: 'timeout' });
  });


  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('does not publish enhancement arriving after its deadline even before the timeout callback runs', async () => {
    vi.useFakeTimers();
    const scan = detectPIIForWeb('Amina anna@example.com');
    const worker = FakeWorker.workers[0];
    await tick(); worker.respond(0); await tick();
    vi.setSystemTime(Date.now() + WEB_PII_SCAN_BUDGET_MS + 1);
    worker.respond(1, { items: [{ label: 'GIVEN_NAME', original: 'Amina', start: 0, end: 5, confidence: 1 }] });
    await expect(scan).resolves.toEqual(basicDetector.detectPII('Amina anna@example.com'));
    expect(get(webPIIDetectorState).fallbackReason).toBe('timeout');
  });


  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('supersedes the active loading preview so ready-state rescans never infer obsolete drafts', async () => {
    const old = detectPIIForWeb('obsolete draft', {}, { purpose: 'preview' });
    const current = detectPIIForWeb('Amina', {}, { purpose: 'preview' });
    await expect(old).resolves.toEqual([]);
    const worker = FakeWorker.workers[0];
    let refreshed: Promise<basicDetector.PIIMatch[]> | undefined;
    const unsubscribe = webPIIDetectorState.subscribe(state => {
      if (state.status === 'ready' && !refreshed) refreshed = detectPIIForWeb('Amina', {}, { purpose: 'preview' });
    });
    await tick(); worker.respond(0); await tick();
    await expect(current).resolves.toEqual([]);
    expect(worker.messages.map(message => message.text).filter(Boolean)).toEqual(['Amina']);
    worker.respond(1, { items: [{ label: 'GIVEN_NAME', original: 'Amina', start: 0, end: 5, confidence: 1 }] });
    expect((await refreshed!)[0].match).toBe('Amina');
    unsubscribe();
  });

});
