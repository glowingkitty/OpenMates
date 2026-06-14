/*
 * Minimal TweetNaCl declarations for CLI signup crypto.
 *
 * Purpose: unblock DTS generation for the small secretbox surface we use.
 * Architecture: runtime package is tweetnacl; this file declares only needed APIs.
 * Security: declarations do not implement crypto and must stay aligned with package behavior.
 * Tests: frontend/packages/openmates-cli/tests/crypto.test.ts
 */

declare module "tweetnacl" {
  const nacl: {
    randomBytes(length: number): Uint8Array;
    secretbox(message: Uint8Array, nonce: Uint8Array, key: Uint8Array): Uint8Array;
  };

  export default nacl;
}
