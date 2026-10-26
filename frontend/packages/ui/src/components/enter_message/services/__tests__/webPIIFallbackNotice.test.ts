import { beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => { sessionStorage.clear(); vi.resetModules(); });

describe('basic PII fallback notification ownership', () => {
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('shows once and remembers the notice across module/page reloads in this tab', async () => {
    const first = await import('../webPIIFallbackNotice');
    expect(first.claimWebPIIFallbackNotice()).toBe(true);
    expect(first.claimWebPIIFallbackNotice()).toBe(false);
    vi.resetModules();
    const reloaded = await import('../webPIIFallbackNotice');
    expect(reloaded.claimWebPIIFallbackNotice()).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('does not repeat when browser storage is unavailable', async () => {
    const blocked = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Storage unavailable'); });
    const notice = await import('../webPIIFallbackNotice');
    expect(notice.claimWebPIIFallbackNotice()).toBe(true);
    expect(notice.claimWebPIIFallbackNotice()).toBe(false);
    blocked.mockRestore();
  });
});
