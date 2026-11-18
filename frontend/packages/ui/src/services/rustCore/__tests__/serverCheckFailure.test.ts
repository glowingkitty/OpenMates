import { describe, expect, it } from 'vitest';
import { backsOffServerCheck, isServerRejection, keepsLocalSessionAfterServerCheckFailure } from '../serverCheckFailure';

describe('server-checked admission failure classes', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('an unreachable server keeps the local session; a server rejection ends it', () => {
    expect(keepsLocalSessionAfterServerCheckFailure('unavailable')).toBe(true);
    for (const code of ['session_expired', 'reauthentication_required', 'authentication_failed', 'credential_conflict', 'two_factor_required']) {
      expect(isServerRejection(code), code).toBe(true);
      expect(keepsLocalSessionAfterServerCheckFailure(code), code).toBe(false);
    }
    expect(keepsLocalSessionAfterServerCheckFailure('cancelled')).toBe(false);
    expect(keepsLocalSessionAfterServerCheckFailure('invalidated_snapshot')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('only an unreachable server holds further server checks back', () => {
    expect(backsOffServerCheck('unavailable')).toBe(true);
    expect(backsOffServerCheck('deadline')).toBe(true);
    // An unexpected error while online keeps the local session but retries freely.
    expect(keepsLocalSessionAfterServerCheckFailure('other')).toBe(true);
    expect(backsOffServerCheck('other')).toBe(false);
    expect(backsOffServerCheck('session_expired')).toBe(false);
  });
});
