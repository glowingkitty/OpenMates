/** Delivered shared-context receipts stay Project/chat bound and encrypted. */
// contract-test-file: supporting surface=cli assertions=rules.transparency.applied-set,chats.direction.reviewed-correction
import { it } from "node:test";
import assert from "node:assert/strict";
import { decryptWithAesGcmCombined } from "../src/crypto.ts";
import { registerChatContextEvents, parseChatContextEvent, DIRECTION_CORRECTION_NOTICE } from "../src/chatContextEvents.ts";

const rules = { type: "rules_loaded", event_id: "rule-event", created_at: 123, count: 1, set_key: "set-1",
  rules: [{ id: "guide", title: "Python practices", source: "app", revision: "v1", body: "Use bounded inputs." }] };
function transport() {
  const handlers = new Map<string, (payload: unknown) => void>();
  const messages: Array<Record<string, unknown>> = [];
  return { handlers, messages, ws: {
    onMessageType(name: string, callback: (payload: unknown) => void) { handlers.set(name, callback); return () => handlers.delete(name); },
    async sendAsync(_type: string, payload: Record<string, unknown>) { messages.push(payload); },
  } };
}

// contract-test: supporting surface=cli assertions=rules.transparency.applied-set,chats.direction.reviewed-correction,focus-modes.project-authoring-click
it("persists actual delivery exactly once as encrypted system history, ignoring unrelated and malformed frames", async () => {
  const { handlers, messages, ws } = transport();
  const key = new Uint8Array(32).fill(7);
  const applied: unknown[] = [];
  const listener = registerChatContextEvents({ ws: ws as never, chatId: "chat", chatKey: key,
    existingMessageIds: ["existing"], onApplied: event => { applied.push(event); } });
  const deliver = (chat_id: string, event: unknown) => handlers.get("chat_context_applied")?.({ chat_id, event });
  deliver("other", rules);
  deliver("chat", { ...rules, event_id: "existing" });
  deliver("chat", { ...rules, count: 2 });
  deliver("chat", rules); deliver("chat", rules);
  const correction = { type: "chat_direction_correction", event_id: "correction", created_at: 124,
    notice: DIRECTION_CORRECTION_NOTICE, instruction: "Continue under the actual goal and current grants.", delivery_id: "delivered" };
  deliver("chat", correction);
  await listener.flush();
  assert.equal(messages.length, 2); assert.deepEqual(applied, [rules, correction]);
  for (const [index, expected] of [rules, correction].entries()) {
    const message = messages[index].message as Record<string, unknown>;
    assert.equal(message.role, "system"); assert.equal(message.message_id, expected.event_id);
    assert.deepEqual(JSON.parse(await decryptWithAesGcmCombined(String(message.encrypted_content), key) ?? "null"), expected);
  }
  assert.doesNotMatch(JSON.stringify(messages), /Use bounded inputs|Continue under the actual goal/);
  listener.stop(); assert.equal(handlers.size, 0);
});

// contract-test: supporting surface=cli assertions=rules.transparency.applied-set,chats.direction.reviewed-correction,focus-modes.project-authoring-click
it("does not interpret pending/incomplete correction or inspection tokens as an applied notice/button", () => {
  assert.equal(parseChatContextEvent({ type: "chat_direction_correction", event_id: "event", created_at: 1,
    notice: DIRECTION_CORRECTION_NOTICE, instruction: "Drafted correction." }), null);
  assert.equal(parseChatContextEvent({ type: "project_authoring_recommendation", event_id: "event", created_at: 1,
    action: "inspect", kind: "focus", recommendation_id: "token", project_id: "project" }), null);
});

// contract-test: supporting surface=cli assertions=rules.transparency.applied-set
it("suppresses unchanged applied rule sets across reconnects and keeps an actual changed set", async () => {
  const { handlers, messages, ws } = transport();
  const listener = registerChatContextEvents({ ws: ws as never, chatId: "chat", chatKey: new Uint8Array(32).fill(9), existingMessageIds: [], previousRulesSetKey: "set-1" });
  const deliver = (event: unknown) => handlers.get("chat_context_applied")?.({ chat_id: "chat", event });
  deliver(rules); deliver({ ...rules, event_id: "same-new-id" });
  deliver({ ...rules, event_id: "changed", set_key: "set-2" });
  deliver({ ...rules, event_id: "restored", set_key: "set-1" });
  await listener.flush(); assert.equal(messages.length, 2);
});
