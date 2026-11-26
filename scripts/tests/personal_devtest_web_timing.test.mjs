// contract-test-file: tooling
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const helper = new URL('../../frontend/apps/web_app/tests/helpers/personal-devtest-web-timing.ts', import.meta.url);
const browserCode = stripTypeScriptTypes(readFileSync(helper, 'utf8')).replaceAll('export ', '');

function fixture() {
  const listeners = new Map(), animations = new Map(), timers = new Map();
  let clock = 0, next = 0, owner = 'previous-chat';
  let messageId = 'previous-id', consistent = true, messageBottom = 20;
  const text = { nodeValue: 'PRIVATE_BODY', parentElement: { closest: () => null, checkVisibility: () => true } };
  const body = { checkVisibility: () => true, getBoundingClientRect: () => ({ top: 0, bottom: messageBottom }),
    contains: hit => hit === text.parentElement };
  const message = { get dataset() { return { messageId }; }, querySelector: () => body };
  const history = { get dataset() { return { currentChatId: owner }; }, querySelectorAll: () => [message],
    closest: () => ({ getBoundingClientRect: () => ({ top: 0, left: 0, bottom: 30, right: 30 }) }) };
  const active = { get dataset() { return {
    authenticated: 'true', currentChatId: owner, currentMessageChatConsistent: String(consistent),
  }; }, querySelector: () => history };
  class Element {
    closest() { return { dataset: { chatId: 'selected-chat' } }; }
  }
  const window = { setTimeout: callback => { timers.set(++next, callback); return next; },
    clearTimeout: id => timers.delete(id) };
  const doc = { querySelector: () => active, querySelectorAll: () => [history],
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: name => listeners.delete(name),
    createTreeWalker: () => { let pending = text; return { nextNode: () => {
      const node = pending; pending = null; return node;
    } }; },
    createRange: () => ({ selectNodeContents() {}, getClientRects: () => [
      { left: 0, right: 20, top: messageBottom - 10, bottom: messageBottom },
    ] }),
    elementFromPoint: () => text.parentElement };
  const probe = runInNewContext(browserCode + '\n({ armSelectedFrameProbe, takeSelectedFrameProbe, clearSelectedFrameProbe });', {
    document: doc, window, Element, NodeFilter: { SHOW_TEXT: 4 }, CSS: { escape: value => value },
    innerHeight: 30, innerWidth: 30, performance: { now: () => clock },
    requestAnimationFrame: callback => { animations.set(++next, callback); return next; },
    cancelAnimationFrame: id => animations.delete(id),
  });
  return {
    arm: () => probe.armSelectedFrameProbe({ rowSelector: '[data-chat-id]', chatId: 'selected-chat', timeoutMs: 50 }),
    click: isTrusted => listeners.get('click')?.({ isTrusted, target: new Element() }),
    step: (at, state) => {
      clock = at;
      ({ owner = owner, messageId = messageId, consistent = consistent, messageBottom = messageBottom } = state);
      const [id, frame] = [...animations][0]; animations.delete(id); frame();
    },
    active: () => [listeners.size, animations.size, timers.size],
    expire: () => [...timers.values()][0](),
    take: probe.takeSelectedFrameProbe, clear: probe.clearSelectedFrameProbe,
  };
}

test('selected timing requires a trusted click and owned viewport text', async () => {
  const probe = fixture();
  probe.arm();
  probe.click(false);
  assert.deepEqual(probe.active(), [1, 0, 1]);
  probe.click(true);
  probe.step(16, { owner: 'selected-chat' }); // Prior DOM survives transition.
  probe.step(32, { messageId: 'new-id', consistent: false });
  probe.step(48, { consistent: true, messageBottom: 80 }); // Below viewport.
  assert.deepEqual(probe.active(), [0, 1, 1]);
  probe.step(64, { messageBottom: 20 });
  assert.equal(JSON.stringify(await probe.take()), '{"outcome":"visible","click_to_readable_frame_ms":64}');
  assert.deepEqual(probe.active(), [0, 0, 0]);
  probe.clear();
});

test('expiry removes unused click listeners before idle', async () => {
  const probe = fixture();
  probe.arm();
  probe.expire();
  assert.equal((await probe.take()).outcome, 'missing_click');
  assert.deepEqual(probe.active(), [0, 0, 0]);
  probe.clear();
});

test("deadline after click cancels the pending animation frame", async () => {
  const probe = fixture();
  probe.arm();
  probe.click(true);
  probe.expire();
  assert.equal((await probe.take()).outcome, "visible_text_timeout");
  assert.deepEqual(probe.active(), [0, 0, 0]);
  probe.clear();
});
