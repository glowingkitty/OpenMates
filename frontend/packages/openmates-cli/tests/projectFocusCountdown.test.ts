/** Automatic Project activation confirms server authority before private reads. */
// contract-test-file: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { registerProjectFocusCountdown } from '../src/projectFocusCountdown.ts';
import { encryptWithAesGcmCombined } from '../src/crypto.ts';
const projectId = '11111111-1111-4111-8111-111111111111';
function wsFixture() {
  const handlers = new Map<string, (value: unknown) => void>(), sent: unknown[] = [];
  return { handlers, sent, ws: { onMessageType(type: string, handler: (value: unknown) => void) { handlers.set(type, handler); return () => handlers.delete(type); },
    onClose() {}, async sendAsync(_type: string, payload: unknown) { sent.push(payload); } } };
}

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('waits four seconds, confirms the server request, then loads/decrypts the private default Focus and activates that exact request', async context => {
  context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100_000 });
  const key = new Uint8Array(32).fill(4), calls: string[] = [], f = wsFixture();
  const encrypted = await encryptWithAesGcmCombined(JSON.stringify({ default_focus: { focus_id: 'private', instructions: 'Private Project goals' } }), key);
  const stop = registerProjectFocusCountdown({ ws: f.ws as never, chatId: 'chat', teamId: null, client: {
    async confirmProjectFocusCountdown(_project: string, input: Record<string, unknown>) { calls.push('confirm'); assert.equal(input.activation_request_id, 'request'); },
    async getProject() { calls.push('private-detail'); return { project: {} }; }, async getProjectSettings() { calls.push('private-settings'); return { encrypted_settings: encrypted, selection_required: false }; },
    async decryptProjectKey() { calls.push('private-key'); return key; }, async activateProjectFocus(_project: string, input: Record<string, unknown>) { calls.push('activate'); assert.equal(input.activation_request_id, 'request'); assert.equal(input.instruction, 'Private Project goals'); },
  } as never });
  f.handlers.get('focus_mode_pending')?.({ chat_id: 'chat', focus_id: 'project-' + projectId, embed_id: 'request', expires_at: 104 });
  context.mock.timers.tick(3999); assert.deepEqual(calls, []); context.mock.timers.tick(1);
  for (let attempt = 0; attempt < 15 && !calls.includes('activate'); attempt++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls[0], 'confirm'); assert.equal(calls.at(-1), 'activate'); stop();
});

// contract-test: supporting surface=cli assertions=focus-modes.countdown,focus-modes.project-specialist-composition
it('rejects or expires without loading private Project context', async context => {
  context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100_000 });
  const f = wsFixture(); let privateReads = 0, confirmed = 0, reject: (() => Promise<void>) | undefined;
  const stop = registerProjectFocusCountdown({ ws: f.ws as never, chatId: 'chat', teamId: null,
    onPending(value) { reject = value?.reject; }, client: { async confirmProjectFocusCountdown() { confirmed++; throw new Error('stale request'); }, async getProject() { privateReads++; } } as never });
  f.handlers.get('focus_mode_pending')?.({ chat_id: 'chat', focus_id: 'project-' + projectId, embed_id: 'cancelled', expires_at: 104 });
  await reject?.(); context.mock.timers.tick(4000); assert.equal(confirmed, 0); assert.equal(privateReads, 0); assert.equal(f.sent.length, 1);
  f.handlers.get('focus_mode_pending')?.({ chat_id: 'chat', focus_id: 'project-' + projectId, embed_id: 'stale', expires_at: 108 });
  context.mock.timers.tick(4000); await new Promise(resolve => setImmediate(resolve)); assert.equal(confirmed, 1); assert.equal(privateReads, 0); stop();
});
