import { describe, expect, it } from 'vitest';
import { admissionContextAllowed, type BrowserContext } from '../productionSavedChatPlatform';

const signedIn: BrowserContext = {
  ownerId: '0b8f5a2e-4c1d-4e6f-9a7b-2c3d4e5f6a7b', authenticated: true, initialized: true, checking: false,
  deviceVerification: false, loggingOut: false, forcedLogout: false,
  loginGeneration: 1, teamId: null, teamEpoch: 0, workspaceEpoch: 0,
};

describe('admissionContextAllowed', () => {
  // contract-test: supporting surface=gui.web assertions=live-collab.access.roles
  it('admits a signed-in user in the personal workspace', () => {
    expect(admissionContextAllowed(signedIn, false)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=live-collab.access.roles
  it('admits a signed-in user while a Team workspace is active (Team scope travels per call)', () => {
    const inTeam = { ...signedIn, teamId: '7c6b5a4d-3e2f-4a1b-8c9d-0e1f2a3b4c5d', teamEpoch: 2 };
    expect(admissionContextAllowed(inTeam, false)).toBe(true);
    expect(admissionContextAllowed(inTeam, true)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=live-collab.access.roles
  it('still refuses signed-out, uninitialised, checking, verifying and logging-out states', () => {
    expect(admissionContextAllowed({ ...signedIn, ownerId: null }, false)).toBe(false);
    expect(admissionContextAllowed({ ...signedIn, ownerId: 'not-a-uuid' }, false)).toBe(false);
    expect(admissionContextAllowed({ ...signedIn, authenticated: false }, false)).toBe(false);
    expect(admissionContextAllowed({ ...signedIn, initialized: false }, false)).toBe(false);
    expect(admissionContextAllowed({ ...signedIn, checking: true }, false)).toBe(false);
    expect(admissionContextAllowed({ ...signedIn, checking: true }, true)).toBe(true);
    expect(admissionContextAllowed({ ...signedIn, deviceVerification: true }, false)).toBe(false);
    expect(admissionContextAllowed({ ...signedIn, loggingOut: true }, false)).toBe(false);
    expect(admissionContextAllowed({ ...signedIn, forcedLogout: true }, false)).toBe(false);
  });
});
