// contract-test-file: tooling
/**
 * Unit contracts for authenticated post-update quick server tests.
 *
 * These tests keep credit consent, instance-bound authentication, sanitized
 * reporting, and temporary chat cleanup deterministic without live requests.
 * Live CLI proof is recorded separately against the dev server.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  assessQuickServerTestEligibility,
  decideQuickServerTestAction,
  runQuickServerTest,
  type QuickServerTestClient,
} from "../src/serverQuickTest.ts";

function fakeClient(overrides: Partial<QuickServerTestClient> = {}): QuickServerTestClient {
  return {
    apiUrl: "https://api.selfhost.example",
    hasSession: () => true,
    getSession: () => ({ apiUrl: "https://api.selfhost.example" }),
    sendMessage: async (params) => ({
      status: "completed",
      chatId: params.chatId ?? "",
      messageId: "22222222-2222-4222-8222-222222222222",
      assistant: "server quick test passed",
    }),
    getChatMessages: async () => ({
      messages: [
        { role: "user", content: "synthetic" },
        { role: "assistant", content: "server quick test passed" },
      ],
    }),
    deleteChat: async () => undefined,
    runSkill: async ({ app }) => app === "math"
      ? { data: { result: "4" } }
      : { data: { results: [{ id: "quick", results: [{ title: "OpenMates", url: "https://openmates.org" }] }] } },
    ...overrides,
  };
}

describe("post-update quick server test", () => {
  // contract-test: supporting surface=cli assertions=chats.surface.semantic-parity
  it("requires a session bound to the updated installation origin", () => {
    const ready = assessQuickServerTestEligibility({
      role: "core",
      expectedApiUrl: "https://api.selfhost.example/v1",
      client: fakeClient(),
    });
    assert.equal(ready.status, "ready");

    const missing = assessQuickServerTestEligibility({
      role: "core",
      expectedApiUrl: "https://api.selfhost.example",
      client: fakeClient({ hasSession: () => false }),
    });
    assert.equal(missing.status, "login_required");
    assert.match(missing.loginCommand ?? "", /openmates --api-url https:\/\/api\.selfhost\.example login/);

    const mismatch = assessQuickServerTestEligibility({
      role: "core",
      expectedApiUrl: "https://api.selfhost.example",
      client: fakeClient({ getSession: () => ({ apiUrl: "https://api.openmates.org" }) }),
    });
    assert.equal(mismatch.status, "login_required");
    assert.equal(mismatch.reason, "session_instance_mismatch");

    const requestMismatch = assessQuickServerTestEligibility({
      role: "core",
      expectedApiUrl: "https://api.selfhost.example",
      client: fakeClient({ apiUrl: "https://api.openmates.org" }),
    });
    assert.equal(requestMismatch.status, "login_required");
    assert.equal(requestMismatch.reason, "session_instance_mismatch");
  });

  // contract-test: supporting surface=cli assertions=chats.surface.semantic-parity,web-search.surface-parity
  it("never treats --yes or non-interactive defaults as spend consent", () => {
    assert.equal(decideQuickServerTestAction({ interactive: true }), "prompt");
    assert.equal(decideQuickServerTestAction({ interactive: false }), "skip");
    assert.equal(decideQuickServerTestAction({ interactive: true, json: true }), "skip");
    assert.equal(decideQuickServerTestAction({ interactive: true, continuous: true }), "skip");
    assert.equal(decideQuickServerTestAction({ interactive: true, skipQuickTest: true }), "skip");
    assert.equal(decideQuickServerTestAction({ interactive: true, skipQuickTest: true, quickTest: true, confirmSpendCredits: true }), "skip");
    assert.equal(decideQuickServerTestAction({ interactive: false, quickTest: true }), "skip");
    assert.equal(decideQuickServerTestAction({ interactive: false, yes: true }), "skip");
    assert.equal(decideQuickServerTestAction({ interactive: false, quickTest: true, confirmSpendCredits: true }), "run");
    assert.equal(decideQuickServerTestAction({ interactive: true, confirmSpendCredits: true }), "run");
  });

  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity,web-search.response.sanitized,web-search.surface-parity
  it("runs the bounded real-chat and cheap-skill checklist and cleans up", async () => {
    const calls: string[] = [];
    const client = fakeClient({
      sendMessage: async (params) => {
        calls.push(`chat:${params.taskUpdateJobs}:${params.personal}`);
        return {
          status: "completed",
          chatId: params.chatId ?? "",
          messageId: "22222222-2222-4222-8222-222222222222",
          assistant: "server quick test passed",
        };
      },
      getChatMessages: async (_chatId, options) => {
        calls.push(`reload:${options?.personal}`);
        return { messages: [{ role: "user" }, { role: "assistant" }] };
      },
      runSkill: async ({ app, skill, inputData }) => {
        calls.push(`${app}.${skill}`);
        if (app === "math") return { data: { result: 4 } };
        assert.deepEqual(inputData, { requests: [{ id: "quick", query: "site:openmates.org OpenMates", count: 1 }] });
        return { data: { results: [{ id: "quick", results: [{ title: "OpenMates", url: "https://openmates.org" }] }] } };
      },
      deleteChat: async (_chatId, options) => { calls.push(`cleanup:${options?.personal}`); },
    });

    const result = await runQuickServerTest(client, { now: () => 1_000 });

    assert.equal(result.status, "passed");
    assert.deepEqual(result.checks.map((check) => [check.id, check.status]), [
      ["account.session", "passed"],
      ["chat.create", "passed"],
      ["chat.reload", "passed"],
      ["app.math.calculate", "passed"],
      ["app.web.search", "passed"],
      ["chat.cleanup", "passed"],
    ]);
    assert.deepEqual(calls, ["chat:false:true", "reload:true", "math.calculate", "web.search", "cleanup:true"]);
    assert.equal(JSON.stringify(result).includes("server quick test passed"), false);
    assert.equal(JSON.stringify(result).includes("11111111-1111-4111-8111-111111111111"), false);
  });

  // contract-test: supporting surface=cli assertions=chats.surface.semantic-parity,web-search.provider-error.visible,web-search.secrets.never-exposed
  it("sanitizes failures, continues independent checks, and attempts cleanup", async () => {
    const calls: string[] = [];
    const client = fakeClient({
      getChatMessages: async () => { throw new Error("private chat plaintext and sk-secret"); },
      runSkill: async ({ app }) => {
        calls.push(app);
        if (app === "web") throw new Error("Brave raw provider body with token=secret");
        return { data: { result: 4 } };
      },
      deleteChat: async () => { calls.push("cleanup"); },
    });

    const result = await runQuickServerTest(client, { now: () => 1_000 });

    assert.equal(result.status, "failed");
    assert.deepEqual(calls, ["math", "web", "cleanup"]);
    assert.equal(result.checks.find((check) => check.id === "chat.reload")?.sanitized_reason, "chat_reload_failed");
    assert.equal(result.checks.find((check) => check.id === "app.web.search")?.sanitized_reason, "web_search_failed");
    assert.equal(JSON.stringify(result).includes("sk-secret"), false);
    assert.equal(JSON.stringify(result).includes("Brave raw provider"), false);
    assert.equal(result.checks.find((check) => check.id === "chat.cleanup")?.status, "passed");
  });

  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
  it("uses a client-generated chat id so timeout cleanup can still run", async () => {
    let attemptedChatId = "";
    let cleanedChatId = "";
    const result = await runQuickServerTest(fakeClient({
      sendMessage: async (params) => {
        attemptedChatId = params.chatId ?? "";
        throw new Error("timeout after persistence");
      },
      deleteChat: async (chatId) => { cleanedChatId = chatId; },
    }), { now: () => 1_000 });

    assert.match(attemptedChatId, /^[0-9a-f-]{36}$/);
    assert.equal(cleanedChatId, attemptedChatId);
    assert.equal(result.checks.find((check) => check.id === "chat.create")?.status, "failed");
    assert.equal(result.checks.find((check) => check.id === "chat.cleanup")?.status, "passed");
  });

  // contract-test: supporting surface=cli assertions=chats.surface.semantic-parity
  it("rejects an unrelated assistant response and still cleans up", async () => {
    let cleanupCalled = false;
    const result = await runQuickServerTest(fakeClient({
      sendMessage: async (params) => ({
        status: "completed",
        chatId: params.chatId ?? "",
        messageId: "22222222-2222-4222-8222-222222222222",
        assistant: "The server might be working.",
      }),
      deleteChat: async () => { cleanupCalled = true; },
    }), { now: () => 1_000 });

    assert.equal(result.checks.find((check) => check.id === "chat.create")?.status, "failed");
    assert.equal(cleanupCalled, true);
  });
});
