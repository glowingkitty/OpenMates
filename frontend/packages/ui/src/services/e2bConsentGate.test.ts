// Gating decision for E2B uploads (assertion code-run.e2b.upload-consent).
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const read = vi.fn();
const write = vi.fn();
const dialog = vi.fn();
vi.mock('./rustCore/e2bConsent/e2bConsentClient', () => ({ readE2bConsent: read, writeE2bConsent: write }));
vi.mock('../stores/e2bConsentDialogStore', () => ({ requestE2bConsentDialog: dialog }));
vi.mock('../i18n/translations', async () => {
  const { readable } = await import('svelte/store');
  return { text: readable((key: string) => key) };
});

// Imported after the mocks are registered.
let gate: typeof import('./e2bConsentGate');
beforeAll(async () => { gate = await import('./e2bConsentGate'); });
const record = (decision: 'allowed' | 'declined' | null) => ({ decision, decidedAt: null, version: 1 });

beforeEach(() => { vi.clearAllMocks(); write.mockResolvedValue(record('allowed')); });

describe('e2bStartAction', () => {
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('starts only when allowed; only user starts may ask', () => {
    expect(gate.e2bStartAction('allowed', 'auto')).toBe('start');
    expect(gate.e2bStartAction('allowed', 'user')).toBe('start');
    expect(gate.e2bStartAction(null, 'user')).toBe('ask');
    expect(gate.e2bStartAction(null, 'auto')).toBe('blocked');
    expect(gate.e2bStartAction('declined', 'user')).toBe('blocked');
    expect(gate.e2bStartAction('declined', 'auto')).toBe('blocked');
  });
});

describe('server refusal codes', () => {
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('reads the typed code from the error body', () => {
    expect(gate.e2bConsentCodeFromPayload({ detail: { code: 'e2b_consent_required' } })).toBe('e2b_consent_required');
    expect(gate.e2bConsentCodeFromPayload({ detail: { code: 'e2b_consent_declined' } })).toBe('e2b_consent_declined');
    expect(gate.e2bConsentCodeFromPayload({ detail: { code: 'other' } })).toBeUndefined();
    expect(gate.e2bConsentCodeFromPayload({ detail: 'text' })).toBeUndefined();
    expect(gate.e2bConsentCodeFromPayload(null)).toBeUndefined();
  });
});

describe('ensureE2bConsentForUserStart', () => {
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('starts without asking when allowed', async () => {
    read.mockResolvedValue(record('allowed'));
    await gate.ensureE2bConsentForUserStart();
    expect(dialog).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('records allow and starts', async () => {
    read.mockResolvedValue(record(null));
    dialog.mockResolvedValue('allow');
    await gate.ensureE2bConsentForUserStart();
    expect(write).toHaveBeenCalledWith('allowed');
  });
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it.each(['own_machine', 'not_now'])('records declined and starts nothing on %s', async (choice) => {
    read.mockResolvedValue(record(null));
    dialog.mockResolvedValue(choice);
    await expect(gate.ensureE2bConsentForUserStart()).rejects.toBeInstanceOf(gate.E2bConsentRefusedError);
    expect(write).toHaveBeenCalledWith('declined');
  });
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('records nothing when the dialog is dismissed', async () => {
    read.mockResolvedValue(record(null));
    dialog.mockResolvedValue('dismissed');
    await expect(gate.ensureE2bConsentForUserStart()).rejects.toBeInstanceOf(gate.E2bConsentRefusedError);
    expect(write).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('refuses with the settings notice without asking when declined', async () => {
    read.mockResolvedValue(record('declined'));
    await expect(gate.ensureE2bConsentForUserStart()).rejects.toThrow('e2b_consent.run.declined_notice');
    expect(dialog).not.toHaveBeenCalled();
  });
});

describe('resolveServerE2bConsentRefusal', () => {
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('refuses on declined and asks on required', async () => {
    await expect(gate.resolveServerE2bConsentRefusal('e2b_consent_declined')).rejects.toBeInstanceOf(gate.E2bConsentRefusedError);
    expect(dialog).not.toHaveBeenCalled();
    dialog.mockResolvedValue('allow');
    await gate.resolveServerE2bConsentRefusal('e2b_consent_required');
    expect(write).toHaveBeenCalledWith('allowed');
  });
});

describe('isE2bAutoStartAllowed', () => {
  // contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
  it('is true only for allowed and never prompts', async () => {
    read.mockResolvedValue(record('allowed'));
    expect(await gate.isE2bAutoStartAllowed()).toBe(true);
    read.mockResolvedValue(record(null));
    expect(await gate.isE2bAutoStartAllowed()).toBe(false);
    read.mockResolvedValue(record('declined'));
    expect(await gate.isE2bAutoStartAllowed()).toBe(false);
    read.mockRejectedValue(new Error('unavailable'));
    expect(await gate.isE2bAutoStartAllowed()).toBe(false);
    expect(dialog).not.toHaveBeenCalled();
  });
});
