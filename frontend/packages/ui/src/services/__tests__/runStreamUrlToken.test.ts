/**
 * Code Run and notebook stream URL token tests.
 *
 * Purpose: the server refuses a session cookie paired with an expired signed
 * ws_token query, so stream URLs only attach a still-valid token and otherwise
 * rely on the cookie.
 * Contract: architecture.session-owner-consistency@1.
 * Run: python3 scripts/tests.py run --suite vitest
 */

import { afterEach, describe, expect, it } from 'vitest';

import { getCodeRunStreamUrl } from '../codeRunService';
import { getNotebookRunStreamUrl } from '../notebookRunService';

function hmacShapedToken(expirySeconds: number): string {
  return `hash:${Math.floor(expirySeconds)}:signature`;
}

describe('run stream URL ws_token handling', () => {
  afterEach(() => sessionStorage.clear());

  // contract-test: direct surface=gui.web assertions=owner-consistency.ws.dual-principal
  it('attaches a still-valid ws_token to code and notebook stream URLs', () => {
    const token = hmacShapedToken(Date.now() / 1000 + 240);
    sessionStorage.setItem('ws_token', token);
    for (const url of [getCodeRunStreamUrl('exec-1'), getNotebookRunStreamUrl('exec-1')]) {
      expect(new URL(url).searchParams.get('token')).toBe(token);
    }
  });

  // contract-test: direct surface=gui.web assertions=owner-consistency.ws.dual-principal
  it('omits an expired ws_token so the session cookie authenticates alone', () => {
    sessionStorage.setItem('ws_token', hmacShapedToken(Date.now() / 1000 - 10));
    for (const url of [getCodeRunStreamUrl('exec-1'), getNotebookRunStreamUrl('exec-1')]) {
      expect(new URL(url).searchParams.has('token')).toBe(false);
      expect(new URL(url).searchParams.get('sessionId')).toBeTruthy();
    }
  });
});
